"""Every upsert needs a unique constraint the database actually has (issue #144).

Postgres rejects INSERT ... ON CONFLICT (cols) unless a unique constraint
on exactly those columns exists. Body temperature, skin temperature, SpO2
and ECG upserted on columns with no constraint, which aborted every sync
on a device that returned that data. The unit tests build the schema with
create_all, so they never saw it, and nothing checked the migrations
against the models.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import UniqueConstraint, create_engine, inspect, make_url, text
from sqlalchemy.exc import OperationalError

import polar_flow_server.models as models
from polar_flow_server.models.base import Base

SRC = Path(models.__file__).resolve().parent.parent
REPO = SRC.parent.parent
# conftest points DATABASE_URL at the polar_test database; alembic runs sync.
TEST_DB_URL = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql+psycopg")
MIGRATION_DB = "polar_migrations_test"
MIGRATION_DB_URL = TEST_DB_URL.set(database=MIGRATION_DB)
PRE_144_REVISION = "l3m4n5o6p7q8"


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
    """Column sets the model guarantees unique: PK, unique constraints and indexes."""
    sets = {frozenset(c.name for c in table.primary_key.columns)}
    sets |= {
        frozenset(c.name for c in con.columns)
        for con in table.constraints
        if isinstance(con, UniqueConstraint)
    }
    sets |= {frozenset(c.name for c in ix.columns) for ix in table.indexes if ix.unique}
    return sets


def _db_unique_column_sets(insp, table: str) -> set[frozenset[str]]:
    sets = {frozenset(uc["column_names"]) for uc in insp.get_unique_constraints(table)}
    sets |= {frozenset(ix["column_names"]) for ix in insp.get_indexes(table) if ix["unique"]}
    return sets


def test_scan_finds_the_upserts():
    upserts = _upserts()
    assert len(upserts) >= 10
    unresolved = [where for where, model, _ in upserts if model is None]
    assert not unresolved, (
        f"could not find the insert(Model) for the upsert in {unresolved}; "
        "teach _upserts() the new pattern so the constraint check still covers it"
    )


@pytest.mark.parametrize(("where", "model", "cols"), _upserts())
def test_upsert_target_has_unique_constraint(where, model, cols):
    table = getattr(models, model).__table__
    assert frozenset(cols) in _unique_column_sets(table), (
        f"{where} upserts {table.name} ON CONFLICT {cols} but the model has no "
        "unique constraint on those columns"
    )


# =============================================================================
# Migrations against a real Postgres (skipped when it is unreachable)
# =============================================================================


def _alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": MIGRATION_DB_URL.render_as_string(hide_password=False)}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"alembic {' '.join(args)} failed:\n{proc.stderr}"


@pytest.fixture
def migration_db():
    """A fresh, empty Postgres database for running migrations, dropped afterwards."""
    admin = create_engine(TEST_DB_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {MIGRATION_DB}"))
            conn.execute(text(f"CREATE DATABASE {MIGRATION_DB}"))
    except OperationalError as exc:  # pragma: no cover
        admin.dispose()
        pytest.skip(f"Postgres test database unavailable: {exc}")

    engine = create_engine(MIGRATION_DB_URL)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {MIGRATION_DB}"))
        admin.dispose()


def test_migrations_create_every_model_unique_constraint(migration_db):
    """alembic upgrade head must produce the unique constraints the models declare."""
    _alembic("upgrade", "head")

    insp = inspect(migration_db)
    missing = []
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        db_sets = _db_unique_column_sets(insp, table.name)
        model_sets = _unique_column_sets(table) - {
            frozenset(c.name for c in table.primary_key.columns)
        }
        missing += [f"{table.name}{sorted(cols)}" for cols in model_sets if cols not in db_sets]
    assert not missing, f"models declare unique constraints the migrations never create: {missing}"


def _row(table: str, **values: object) -> str:
    base = {"user_id": "u1", "created_at": "now()", "updated_at": "now()"}
    base.update(values)
    cols = ", ".join(base)
    vals = ", ".join(str(v) if v == "now()" else f"'{v}'" for v in base.values())
    return f"INSERT INTO {table} ({cols}) VALUES ({vals})"


def test_migration_dedupes_and_respects_the_issue_workaround(migration_db):
    """Duplicates can't block startup; a hand-added constraint isn't duplicated."""
    _alembic("upgrade", PRE_144_REVISION)
    with migration_db.begin() as conn:
        for avg in (36.1, 36.4):
            conn.execute(
                text(
                    _row(
                        "body_temperature",
                        device_id="d",
                        start_time="2026-10-01T00:00:00Z",
                        end_time="2026-10-01T01:00:00Z",
                        measurement_type="CONTINUOUS",
                        sensor_location="WRIST",
                        temp_avg=avg,
                        sample_count=0,
                    )
                )
            )
        # The SQL posted on the issue, under a name of the user's choosing.
        conn.execute(
            text(
                "ALTER TABLE skin_temperature "
                "ADD CONSTRAINT my_workaround UNIQUE (user_id, sleep_date)"
            )
        )

    _alembic("upgrade", "head")

    with migration_db.connect() as conn:
        temps = conn.execute(text("SELECT temp_avg FROM body_temperature")).scalars().all()
    assert temps == [36.4], "the newest duplicate row is kept"
    skin = inspect(migration_db).get_unique_constraints("skin_temperature")
    assert [uc["name"] for uc in skin] == ["my_workaround"]

    _alembic("downgrade", PRE_144_REVISION)
    _alembic("upgrade", "head")
