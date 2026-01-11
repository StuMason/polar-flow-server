"""Root application routes."""

from litestar import get
from litestar.response import Redirect
from litestar.status_codes import HTTP_303_SEE_OTHER


@get("/", sync_to_thread=False, include_in_schema=False)
async def root_redirect() -> Redirect:
    """Redirect root to admin panel."""
    return Redirect(path="/admin", status_code=HTTP_303_SEE_OTHER)
