"""One-time first-run setup token (issue #52).

Until an admin account exists, /admin/setup/account is necessarily open —
whoever reaches it first owns the instance. To make sure that's the operator
and not a drive-by visitor, account creation requires a token that is only
ever printed to the server log (the Jellyfin/Grafana pattern).

The token lives in process memory: one per server run, generated lazily,
gone once setup completes or the process restarts.
"""

import logging
import secrets

logger = logging.getLogger(__name__)

_token: str | None = None


def get_setup_token() -> str:
    """Return this run's setup token, generating it on first use."""
    global _token
    if _token is None:
        _token = secrets.token_urlsafe(24)
    return _token


def verify_setup_token(submitted: str) -> bool:
    """Constant-time comparison against the current setup token."""
    return secrets.compare_digest(submitted.strip(), get_setup_token())


def announce_setup_token() -> None:
    """Print the setup token to the server log, loudly."""
    token = get_setup_token()
    logger.warning(
        "\n"
        "============================================================\n"
        "  FIRST-RUN SETUP\n"
        "  No admin account exists yet. To create one, open /admin\n"
        "  and enter this setup token when asked:\n"
        "\n"
        "      %s\n"
        "\n"
        "  (Anyone who can reach this server before setup completes\n"
        "  could otherwise claim it. The token proves you're the\n"
        "  operator: only you can read this log.)\n"
        "============================================================",
        token,
    )


def reset_setup_token_for_tests() -> None:
    """Test hook: forget the current token so a fresh one is generated."""
    global _token
    _token = None
