import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

@pytest.mark.unit
def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] in ("ok", "degraded")

@pytest.mark.unit
def test_get_route():
    # When DB is offline, returns 503 with Retry-After header.
    # When DB is live, returns 200 with X-Route-Latency.
    response = client.get("/route?src_lat=41.88&src_lon=-87.62&dst_lat=41.89&dst_lon=-87.63")
    assert response.status_code in (200, 503)
    if response.status_code == 503:
        assert response.json()["error"] == "database_unavailable"
        assert response.headers.get("Retry-After") == "5"
    else:
        assert "X-Route-Latency" in response.headers or "error" in response.json()

@pytest.mark.unit
def test_get_vehicles():
    response = client.get("/vehicles")
    assert response.status_code == 200
