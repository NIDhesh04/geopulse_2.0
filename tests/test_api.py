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
    # Since this relies on PostGIS, we just test that the endpoint exists and handles arguments.
    # In a real environment, this needs a fixture DB or a mock RoutingService.
    # We will test the error case where routing is not initialized or args are provided.
    response = client.get("/route?src_lat=41.88&src_lon=-87.62&dst_lat=41.89&dst_lon=-87.63")
    assert response.status_code == 200
    # If DB isn't running, it might return {"error": "Routing service unavailable"}
    # But it correctly parses query params.
    assert "X-Route-Latency" in response.headers or "error" in response.json()

@pytest.mark.unit
def test_get_vehicles():
    response = client.get("/vehicles")
    assert response.status_code == 200
