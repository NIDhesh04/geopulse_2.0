import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from asyncpg.exceptions import PostgresConnectionError, CannotConnectNowError
from api.main import app
from api.routing import RoutingService, DatabaseUnavailableError

client = TestClient(app)

@pytest.mark.unit
def test_route_returns_503_when_routing_service_uninitialized():
    """
    When app.state.routing is None or cannot connect, GET /route must return
    HTTP 503 with exact DB Outage Contract: Retry-After header and error schema.
    """
    original_routing = app.state.routing
    try:
        app.state.routing = None
        response = client.get("/route?src_lat=41.88&src_lon=-87.62&dst_lat=41.89&dst_lon=-87.63")
        assert response.status_code == 503
        assert response.headers.get("Retry-After") == "5"
        data = response.json()
        assert data == {
            "error": "database_unavailable",
            "message": "Routing engine temporarily unable to connect to database",
            "retry_after_seconds": 5
        }
    finally:
        app.state.routing = original_routing

@pytest.mark.unit
def test_route_returns_503_on_postgres_connection_error():
    """
    When the database throws PostgresConnectionError or CannotConnectNowError during routing,
    the endpoint must catch it and return HTTP 503 with Retry-After: 5.
    """
    mock_routing = MagicMock()
    mock_routing.route = AsyncMock(side_effect=DatabaseUnavailableError("Simulated DB connection failure"))
    mock_routing.decay_multipliers = AsyncMock()
    original_routing = app.state.routing

    try:
        app.state.routing = mock_routing
        response = client.get("/route?src_lat=41.88&src_lon=-87.62&dst_lat=41.89&dst_lon=-87.63")
        assert response.status_code == 503
        assert response.headers.get("Retry-After") == "5"
        data = response.json()
        assert data["error"] == "database_unavailable"
        assert data["retry_after_seconds"] == 5
    finally:
        app.state.routing = original_routing

@pytest.mark.unit
def test_route_returns_503_on_cannot_connect_now_error():
    """
    Verifies CannotConnectNowError is translated to 503.
    """
    mock_routing = MagicMock()
    mock_routing.route = AsyncMock(side_effect=CannotConnectNowError("PostgreSQL shutting down"))
    mock_routing.decay_multipliers = AsyncMock()
    original_routing = app.state.routing

    try:
        app.state.routing = mock_routing
        response = client.get("/route?src_lat=41.88&src_lon=-87.62&dst_lat=41.89&dst_lon=-87.63")
        assert response.status_code == 503
        assert response.headers.get("Retry-After") == "5"
        data = response.json()
        assert data["error"] == "database_unavailable"
    finally:
        app.state.routing = original_routing

@pytest.mark.unit
def test_health_check_reports_database_disconnected():
    """
    Verifies /health reports {"status": "degraded", "database": "disconnected"}
    when DB pool is closed or failing queries.
    """
    mock_routing = MagicMock()
    mock_routing.db_active = True
    mock_routing.pool = MagicMock()
    mock_routing.pool._closed = False
    
    # Mock pool acquire context manager to raise an exception
    class FailingContext:
        async def __aenter__(self):
            raise PostgresConnectionError("Connection to server lost")
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_routing.pool.acquire = FailingContext
    
    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.get = AsyncMock(return_value=str(time.time() - 10))
    
    orig_routing = app.state.routing
    orig_redis = app.state.redis
    try:
        app.state.routing = mock_routing
        app.state.redis = mock_redis
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "degraded"
        assert response.json()["database"] == "disconnected"
    finally:
        app.state.routing = orig_routing
        app.state.redis = orig_redis

@pytest.mark.unit
@pytest.mark.asyncio
async def test_routing_service_wraps_db_exceptions():
    """
    Unit test RoutingService methods directly to ensure connection errors raise DatabaseUnavailableError.
    """
    service = RoutingService("postgresql://invalid:5432/nonexistent")
    
    # Mock pool that raises CannotConnectNowError on acquire
    mock_pool = MagicMock()
    class FailingContext:
        async def __aenter__(self):
            raise CannotConnectNowError("Simulated DB shutdown")
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_pool.acquire.side_effect = FailingContext
    service.pool = mock_pool

    with pytest.raises(DatabaseUnavailableError):
        await service.snap_to_edge(41.88, -87.62)

    with pytest.raises(DatabaseUnavailableError):
        await service.route(41.88, -87.62, 41.89, -87.63)

    with pytest.raises(DatabaseUnavailableError):
        await service.apply_multipliers({101: 2.5})

    with pytest.raises(DatabaseUnavailableError):
        await service.decay_multipliers()
