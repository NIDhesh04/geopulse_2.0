import pytest
import time
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from asyncpg.exceptions import PostgresConnectionError, CannotConnectNowError
from api.main import app
from api.routing import RoutingService, DatabaseUnavailableError

client = TestClient(app)

@pytest.mark.unit
def test_chaos_worker_down_and_recovery():
    """
    Simulates Worker container termination:
    1. Heartbeat key becomes older than 60s -> /route returns costs_stale: true and triggers decay.
    2. Multiplier decay query verified.
    3. Worker resumes -> heartbeat updated (<10s) -> costs_stale becomes false.
    """
    mock_routing = MagicMock()
    mock_routing.db_active = True
    mock_routing._down = False
    mock_routing.pool = MagicMock()
    mock_routing.pool._closed = False
    mock_routing.route = AsyncMock(return_value=[
        {"seq": 1, "node": 101, "edge": 1420, "cost": 12.4, "agg_cost": 12.4}
    ])
    mock_routing.decay_multipliers = AsyncMock()
    
    mock_redis = MagicMock()
    
    orig_routing = app.state.routing
    orig_redis = app.state.redis
    app.state.routing = mock_routing
    app.state.redis = mock_redis

    try:
        # Step 1: Worker down (heartbeat 75s old)
        stale_time = time.time() - 75.0
        mock_redis.get = AsyncMock(return_value=str(stale_time))

        resp = client.get("/route?src_lat=41.88&src_lon=-87.62&dst_lat=41.89&dst_lon=-87.63")
        assert resp.status_code == 200
        data = resp.json()
        assert data["costs_stale"] is True
        assert data["worker_heartbeat_age_s"] >= 75.0
        # Verify asymptotic decay was triggered
        assert mock_routing.decay_multipliers.called

        # Step 2: Worker restarted (heartbeat 2s old)
        fresh_time = time.time() - 2.0
        mock_redis.get = AsyncMock(return_value=str(fresh_time))

        resp = client.get("/route?src_lat=41.88&src_lon=-87.62&dst_lat=41.89&dst_lon=-87.63")
        assert resp.status_code == 200
        data = resp.json()
        assert data["costs_stale"] is False
        assert data["worker_heartbeat_age_s"] < 60.0

    finally:
        app.state.routing = orig_routing
        app.state.redis = orig_redis

@pytest.mark.unit
def test_chaos_redis_down_and_recovery():
    """
    Simulates Redis container termination:
    1. /metrics reports redis: offline.
    2. /route continues serving static baseline route.
    3. Redis reconnection restores redis: online in /metrics.
    """
    mock_routing = MagicMock()
    mock_routing.db_active = True
    mock_routing._down = False
    mock_routing.pool = MagicMock()
    mock_routing.pool._closed = False
    mock_routing.route = AsyncMock(return_value=[
        {"seq": 1, "node": 101, "edge": 1420, "cost": 10.0, "agg_cost": 10.0}
    ])
    mock_routing.decay_multipliers = AsyncMock()

    # Failing Redis mock
    failing_redis = MagicMock()
    failing_redis.ping = AsyncMock(side_effect=ConnectionRefusedError("Redis down"))
    failing_redis.get = AsyncMock(side_effect=ConnectionRefusedError("Redis down"))
    failing_redis.xinfo_groups = AsyncMock(side_effect=ConnectionRefusedError("Redis down"))
    failing_redis.xadd = AsyncMock(side_effect=ConnectionRefusedError("Redis down"))

    orig_routing = app.state.routing
    orig_redis = app.state.redis
    app.state.routing = mock_routing
    app.state.redis = failing_redis

    try:
        # Step 1: /metrics reports offline
        resp = client.get("/metrics")
        assert resp.status_code == 200
        metrics = resp.json()
        assert metrics["redis"] == "offline"

        # Step 2: /route serves static baseline with costs_stale: true fallback
        resp = client.get("/route?src_lat=41.88&src_lon=-87.62&dst_lat=41.89&dst_lon=-87.63&static=true")
        assert resp.status_code == 200
        route_data = resp.json()
        assert "path" in route_data
        assert route_data["costs_stale"] is True

        # Step 3: Redis recovered
        healthy_redis = MagicMock()
        healthy_redis.ping = AsyncMock(return_value=True)
        healthy_redis.xinfo_groups = AsyncMock(return_value=[])
        healthy_redis.get = AsyncMock(return_value=str(time.time() - 5))
        app.state.redis = healthy_redis

        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert resp.json()["redis"] == "online"

    finally:
        app.state.routing = orig_routing
        app.state.redis = orig_redis

@pytest.mark.unit
def test_chaos_database_down_and_recovery():
    """
    Simulates PostGIS database container termination:
    1. /route returns HTTP 503 with Retry-After: 5 and database_unavailable body.
    2. /health reports {"status": "degraded", "database": "disconnected"}.
    3. Database recovered -> connection pool reconnects on next request -> 200 OK.
    """
    mock_routing = MagicMock()
    mock_routing.db_active = True
    mock_routing._down = False
    mock_routing.decay_multipliers = AsyncMock()
    
    # DB Down behavior
    mock_routing.route = AsyncMock(side_effect=DatabaseUnavailableError("Cannot connect to server"))
    mock_routing.pool = MagicMock()
    mock_routing.pool._closed = False
    
    class FailingAcquire:
        async def __aenter__(self):
            raise PostgresConnectionError("Database offline")
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_routing.pool.acquire = FailingAcquire
    
    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.get = AsyncMock(return_value=str(time.time() - 5))

    orig_routing = app.state.routing
    orig_redis = app.state.redis
    app.state.routing = mock_routing
    app.state.redis = mock_redis

    try:
        # Step 1: /route returns 503
        resp = client.get("/route?src_lat=41.88&src_lon=-87.62&dst_lat=41.89&dst_lon=-87.63")
        assert resp.status_code == 503
        assert resp.headers.get("Retry-After") == "5"
        assert resp.json() == {
            "error": "database_unavailable",
            "message": "Routing engine temporarily unable to connect to database",
            "retry_after_seconds": 5
        }

        # Step 2: /health reports database disconnected
        h_resp = client.get("/health")
        assert h_resp.status_code == 200
        assert h_resp.json()["status"] == "degraded"
        assert h_resp.json()["database"] == "disconnected"

        # Step 3: Database restart and connection pool recovery
        recovered_routing = MagicMock()
        recovered_routing.db_active = True
        recovered_routing._down = False
        recovered_routing.pool = MagicMock()
        recovered_routing.pool._closed = False
        recovered_routing.route = AsyncMock(return_value=[
            {"seq": 1, "node": 101, "edge": 1420, "cost": 12.0, "agg_cost": 12.0}
        ])
        recovered_routing.decay_multipliers = AsyncMock()
        
        class HealthyAcquire:
            async def __aenter__(self):
                conn = MagicMock()
                conn.fetchval = AsyncMock(return_value=1)
                return conn
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
        recovered_routing.pool.acquire = HealthyAcquire

        app.state.routing = recovered_routing

        # Next request seamlessly recovers
        rec_resp = client.get("/route?src_lat=41.88&src_lon=-87.62&dst_lat=41.89&dst_lon=-87.63")
        assert rec_resp.status_code == 200
        assert "path" in rec_resp.json()

        rec_health = client.get("/health")
        assert rec_health.status_code == 200
        assert rec_health.json()["status"] == "ok"

    finally:
        app.state.routing = orig_routing
        app.state.redis = orig_redis
