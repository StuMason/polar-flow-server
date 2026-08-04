"""Guards against the stale documentation claims fixed in issue #88.

Docs drift silently; these pin the claims that were actively wrong: CLAUDE.md
said data endpoints are open without API_KEY (false since the per-user guard
landed), the superseded api_key_guard lingered as dead code, and docs claimed
DuckDB support and a shipped MCP server.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_claude_md_does_not_claim_open_endpoints():
    text = (ROOT / "CLAUDE.md").read_text()
    assert "data endpoints are open" not in text
    assert "ALWAYS required" in text


def test_dead_api_key_guard_is_gone():
    import polar_flow_server.core.auth as auth

    assert not hasattr(auth, "api_key_guard")
    assert not hasattr(auth, "validate_simple_api_key")
    assert hasattr(auth, "per_user_api_key_guard")


def test_docs_do_not_claim_duckdb():
    for doc in ("docs/index.md", "README.md"):
        text = (ROOT / doc).read_text()
        assert "DuckDB" not in text, doc


def test_mcp_claims_match_reality():
    """The MCP server ships now (#80) - docs must say so, not 'planned'."""
    index = (ROOT / "docs" / "index.md").read_text()
    assert "planned" not in index.split("MCP")[1][:80].lower()
    assert (ROOT / "docs" / "mcp-server.md").exists()
    readme = (ROOT / "README.md").read_text()
    assert "/mcp" in readme
