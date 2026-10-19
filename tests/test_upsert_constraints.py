"""Every upsert needs a unique constraint the database actually has (issue #144).

Postgres rejects INSERT ... ON CONFLICT (cols) unless a unique constraint
on exactly those columns exists. Body and skin temperature upserted on
columns with no constraint, which aborted every sync on a device that
returned temperature data. The unit tests build the schema with
create_all, so they never saw it, and nothing checked the migrations
against the models.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import UniqueConstraint, create_engine, inspect, text
from sqlalchemy.exc import OperationalError

import polar_flow_server.models as models
from polar_flow_server.models.base import Base

SRC = Path(models.__file__).resolve().parent.parent
REPO = SRC.parent.parent
PG_URL = "postgresql+psycopg://polar:polar@localhost:5432"
MIGRATION_DB = "polar_migrations_test"


def _upserts() -> list[tuple[str, str, tuple[str, ...]]]:
    """(function, model, conflict columns) for each on_conflict_do_update in src."""
    found = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            calls = sorted(
                (n for n in ast.walk(func) if isinstance(n, ast.Call)), key=lambda n: n.lineno
            )
            model = None
            for node in calls:
                name = getattr(node.func, "id", getattr(node.func, "attr", None))
                if name == "insert" and node.args and isinstance(node.args[0], ast.Name):
                    model = node.args[0].id
                if name == "on_conflict_do_update":
                    for kw in node.keywords:
                        if kw.arg == "index_elements":
                            cols = tuple(ast.literal_eval(kw.value))
                            found.append((f"{path.name}:{func.name}", model, cols))
    return found


def _unique_column_sets(table) -> set[frozenset[str]]:
    sets = {frozenset(c.name for c in table.primary_key.columns)}
    sets |= {
        frozenset(c.name for c in con.columns)
        for con in table.constraints
        if isinstance(con, UniqueConstraint)
    }
    sets |= {frozenset(c.name for c in ix.columns) for ix in table.indexes if ix.unique}
    return sets


def test_scan_finds_the_upserts():
    upserts = _upserts()
    assert len(upserts) >= 10
    assert all(model for _, model, _ in upserts)


@pytest.mark.parametrize(("where", "model", "cols"), _upserts())
def test_upsert_target_has_unique_constraint(where, model, cols):
    table = getattr(models, model).__table__
    assert frozenset(cols) in _unique_column_sets(table), (
        f"{where} upserts {table.name} ON CONFLICT {cols} but the model has no "
        "unique constraint on those columns"
    )


def test_migrations_create_every_model_unique_constraint():
    """alembic upgrade head must produce the unique constraints the models declare."""
    try:
        admin = create_engine(f"{PG_URL}/polar_test", isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {MIGRATION_DB}"))
            conn.execute(text(f"CREATE DATABASE {MIGRATION_DB}"))
    except OperationalError as exc:  # pragma: no cover
        pytest.skip(f"Postgres test database unavailable: {exc}")

    try:
        env = {**os.environ, "DATABASE_URL": f"{PG_URL}/{MIGRATION_DB}"}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO,
            env=env,
            check=True,
            capture_output=True,
        )

        migrated = create_engine(f"{PG_URL}/{MIGRATION_DB}")
        insp = inspect(migrated)
        missing = []
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            db_sets = {
                frozenset(uc["column_names"]) for uc in insp.get_unique_constraints(table.name)
            }
            db_sets |= {
                frozenset(ix["column_names"]) for ix in insp.get_indexes(table.name) if ix["unique"]
            }
            for con in table.constraints:
                if isinstance(con, UniqueConstraint):
                    cols = frozenset(c.name for c in con.columns)
                    if cols not in db_sets:
                        missing.append(f"{table.name}{sorted(cols)}")
        migrated.dispose()
        assert not missing, (
            f"models declare unique constraints the migrations never create: {missing}"
        )
    finally:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {MIGRATION_DB}"))
        admin.dispose()
