"""Health check endpoint."""

from litestar import Router, get
from litestar.status_codes import HTTP_200_OK

from polar_flow_server import __version__


@get("/health", status_code=HTTP_200_OK, sync_to_thread=False)
def health_check() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        Status and version information
    """
    return {
        "status": "ok",
        "version": __version__,
    }


health_router = Router(path="/", route_handlers=[health_check])
