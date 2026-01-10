"""API endpoint tests."""

import pytest
from litestar.status_codes import HTTP_200_OK
from litestar.testing import AsyncTestClient

from polar_flow_server.app import create_app


@pytest.fixture
def client() -> AsyncTestClient:
    """Create test client."""
    return AsyncTestClient(app=create_app())


async def test_health_check(client: AsyncTestClient) -> None:
    """Test health check endpoint."""
    response = await client.get("/health")

    assert response.status_code == HTTP_200_OK
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
