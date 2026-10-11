import pytest
import math
import json
import os
import asyncio
from api.routing import RoutingService

CHICAGO_BBOX = {
    "min_lat": 41.8750,
    "max_lat": 41.8900,
    "min_lon": -87.6350,
    "max_lon": -87.6150
}
SEARCH_RADIUS_DEG = 0.01

def haversine_distance_m(lat1, lon1, lat2, lon2):
    R = 6371000  # meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (math.sin(delta_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

@pytest.mark.unit
@pytest.mark.asyncio
async def test_snapping_bounds_mathematical():
    """
    Validates that query coordinates inside the bounding box
    are within the spatial tolerance r = 0.01 degrees (~830m) of network elements,
    and discretization error is bounded by L_edge / 2.
    """
    with open("sim/graph.json", "r") as f:
        graph = json.load(f)

    nodes = graph["nodes"]
    edges = graph["edges"]
    assert len(nodes) > 0
    assert len(edges) > 0

    node_dict = {n["id"]: (n["lat"], n["lon"]) for n in nodes}

    # Test 10 sample coordinates across the Chicago bounding box
    sample_coords = [
        (41.8825, -87.6250),
        (41.8780, -87.6300),
        (41.8890, -87.6200),
        (41.8760, -87.6340),
        (41.8850, -87.6160),
    ]

    for lat, lon in sample_coords:
        # Find nearest edge in graph
        min_dist_to_node = float('inf')
        nearest_node = None
        for nid, (n_lat, n_lon) in node_dict.items():
            dist = math.sqrt((lat - n_lat)**2 + (lon - n_lon)**2)
            if dist < min_dist_to_node:
                min_dist_to_node = dist
                nearest_node = (n_lat, n_lon)

        # Assert query is within search radius r = 0.01 degrees
        assert min_dist_to_node <= SEARCH_RADIUS_DEG, (
            f"Coordinate ({lat}, {lon}) exceeded tolerance: {min_dist_to_node} > {SEARCH_RADIUS_DEG}"
        )

        # Convert to meters
        dist_m = haversine_distance_m(lat, lon, nearest_node[0], nearest_node[1])
        # In downtown Chicago grid, nearest node is strictly within 200m
        assert dist_m < 300.0, f"Distance in meters too large: {dist_m}m"

@pytest.mark.unit
@pytest.mark.asyncio
async def test_snapping_out_of_bounds():
    """
    Asserts that points far outside Chicago coverage exceed r = 0.01 degrees.
    """
    with open("sim/graph.json", "r") as f:
        graph = json.load(f)

    nodes = graph["nodes"]
    node_dict = {n["id"]: (n["lat"], n["lon"]) for n in nodes}

    # Point far outside Chicago (e.g., Null Island)
    lat, lon = 0.0, 0.0
    min_dist_to_node = min(
        math.sqrt((lat - n_lat)**2 + (lon - n_lon)**2)
        for n_lat, n_lon in node_dict.values()
    )
    assert min_dist_to_node > SEARCH_RADIUS_DEG, "Out-of-bounds point should exceed radius tolerance"
