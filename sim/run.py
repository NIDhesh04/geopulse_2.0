import argparse
import asyncio
import json
import random
import time
import os
import httpx
import websockets
from sim.utils import connect_with_backoff

# Shared edge vehicle occupancy tracker for BPR model
edge_occupancy = {}
occupancy_lock = asyncio.Lock()

def calculate_bpr_speed(edge: dict, num_vehicles: int, free_flow_kmh: float = 40.0, min_speed_kmh: float = 5.0) -> float:
    """
    BPR (Bureau of Public Roads) speed-density model:
    v = v_free / (1 + 0.15 * (n / capacity)^4)
    Capacity is dynamically derived from edge length (1 vehicle per 50m, minimum 3).
    """
    length_m = edge.get("length", 100.0)
    capacity = max(3, round(length_m / 50.0))
    ratio = num_vehicles / capacity
    speed = free_flow_kmh / (1.0 + 0.15 * (ratio ** 4))
    return max(min_speed_kmh, speed)

async def request_route(src_lat: float, src_lon: float, dst_lat: float, dst_lon: float, route_api_url: str):
    """
    Query GET /route to obtain planned path of edges from start to destination.
    """
    params = {
        "src_lat": src_lat,
        "src_lon": src_lon,
        "dst_lat": dst_lat,
        "dst_lon": dst_lon
    }
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(route_api_url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                if "path" in data and data["path"]:
                    return data["path"]
    except Exception:
        pass
    return None

async def vehicle_loop(vehicle_id: int, ws_url: str, route_api_url: str, graph: dict, scenario_incident: dict = None, sim_start_time: float = 0.0):
    async def connect():
        return await websockets.connect(ws_url)

    try:
        ws = await connect_with_backoff(connect)
        
        nodes = graph['nodes']
        edges = graph['edges']
        node_map = {n['id']: n for n in nodes}
        edge_map = {e['id']: e for e in edges}
        
        if not nodes or not edges:
            print("Graph empty.")
            return

        current_node = random.choice(nodes)

        while True:
            # Plan a trip to a random destination node
            destination_node = random.choice(nodes)
            while destination_node['id'] == current_node['id']:
                destination_node = random.choice(nodes)

            # Query GET /route at trip start
            planned_path = await request_route(
                current_node['lat'], current_node['lon'],
                destination_node['lat'], destination_node['lon'],
                route_api_url
            )

            # Extract edges to traverse
            edges_to_traverse = []
            if planned_path:
                for step in planned_path:
                    edge_id = step.get('edge')
                    if edge_id and edge_id in edge_map:
                        edges_to_traverse.append(edge_map[edge_id])

            # Fallback if no route returned: pick local connected edges
            if not edges_to_traverse:
                possible_edges = [e for e in edges if e['source'] == current_node['id']]
                if possible_edges:
                    edges_to_traverse = [random.choice(possible_edges)]
                else:
                    current_node = random.choice(nodes)
                    await asyncio.sleep(1.0)
                    continue

            # Traverse the planned route edge-by-edge
            for edge in edges_to_traverse:
                edge_id = edge['id']

                # Register vehicle on edge (BPR model)
                async with occupancy_lock:
                    edge_occupancy[edge_id] = edge_occupancy.get(edge_id, 0) + 1
                    current_occ = edge_occupancy[edge_id]

                # Dynamic BPR speed calculation
                speed = calculate_bpr_speed(edge, current_occ)

                # Check scenario incident override
                if scenario_incident:
                    elapsed = time.time() - sim_start_time
                    inc_edge = scenario_incident.get('edge_id')
                    t1 = scenario_incident.get('start_s', 0)
                    t2 = scenario_incident.get('end_s', float('inf'))
                    inc_spd = scenario_incident.get('speed_kmh', 5.0)

                    if str(edge_id) == str(inc_edge) and t1 <= elapsed <= t2:
                        speed = min(speed, inc_spd)

                target_node = node_map.get(edge['target'])
                if not target_node:
                    async with occupancy_lock:
                        edge_occupancy[edge_id] = max(0, edge_occupancy.get(edge_id, 1) - 1)
                    break

                ping = {
                    "vehicle_id": f"v_{vehicle_id}",
                    "lat": target_node['lat'],
                    "lon": target_node['lon'],
                    "speed_kmh": round(speed, 2),
                    "ts": int(time.time())
                }

                try:
                    await ws.send(json.dumps(ping))
                except Exception:
                    # WebSocket dropped, reconnect
                    ws = await connect_with_backoff(connect)
                    await ws.send(json.dumps(ping))

                current_node = target_node

                # Sleep 1 second per edge traversal step (rate-limiting 1 ping/sec)
                await asyncio.sleep(1.0)

                # Deregister vehicle from edge
                async with occupancy_lock:
                    edge_occupancy[edge_id] = max(0, edge_occupancy.get(edge_id, 1) - 1)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Vehicle {vehicle_id} loop terminated: {e}")

async def run_simulation(args):
    if args.seed is not None:
        random.seed(args.seed)
        
    ws_url = os.getenv("WS_URL", "ws://localhost:8000/ws/ingest")
    route_api_url = os.getenv("ROUTE_API_URL")
    if not route_api_url:
        if "api:8000" in ws_url:
            route_api_url = "http://api:8000/route"
        else:
            route_api_url = "http://localhost:8000/route"

    # Load scenario configuration if provided
    scenario_incident = None
    num_vehicles = args.vehicles
    total_ticks = args.ticks

    scenario_arg = getattr(args, "scenario", None)
    if scenario_arg:
        scenario_path = scenario_arg
        if not os.path.exists(scenario_path):
            # Check under sim/scenarios/
            alt_path = os.path.join("sim", "scenarios", os.path.basename(scenario_path))
            if os.path.exists(alt_path):
                scenario_path = alt_path
            elif os.path.exists(f"{scenario_path}.json"):
                scenario_path = f"{scenario_path}.json"
            elif os.path.exists(os.path.join("sim", "scenarios", f"{scenario_path}.json")):
                scenario_path = os.path.join("sim", "scenarios", f"{scenario_path}.json")

        if os.path.exists(scenario_path):
            with open(scenario_path, "r") as sf:
                sc_data = json.load(sf)
                print(f"Loaded scenario: {sc_data.get('name', scenario_path)}")
                if "duration_s" in sc_data and args.ticks == 100: # not overridden explicitly
                    total_ticks = sc_data["duration_s"]
                if "vehicles" in sc_data and args.vehicles == 10: # not overridden explicitly
                    num_vehicles = sc_data["vehicles"]
                scenario_incident = sc_data.get("incident")
        else:
            print(f"Warning: scenario file {args.scenario} not found. Running with defaults.")

    # Override incident if --slow-segment passed
    if args.slow_segment:
        try:
            seg_id, times = args.slow_segment.split('@')
            t1, t2 = map(int, times.split('..'))
            scenario_incident = {
                "edge_id": seg_id,
                "start_s": t1,
                "end_s": t2,
                "speed_kmh": 6.0
            }
        except Exception as e:
            print(f"Error parsing slow-segment: {e}")

    # Load graph
    try:
        with open("sim/graph.json", "r") as f:
            graph = json.load(f)
    except FileNotFoundError:
        print("Graph not found. Run export_graph.py first.")
        return

    print(f"Starting simulation: {num_vehicles} vehicles for {total_ticks} ticks...")
    if scenario_incident:
        print(f"Active incident: Edge {scenario_incident.get('edge_id')} slowed to {scenario_incident.get('speed_kmh')} km/h between t={scenario_incident.get('start_s')}s and t={scenario_incident.get('end_s')}s")

    sim_start_time = time.time()
    tasks = []
    for i in range(num_vehicles):
        tasks.append(asyncio.create_task(
            vehicle_loop(i, ws_url, route_api_url, graph, scenario_incident, sim_start_time)
        ))

    try:
        await asyncio.sleep(total_ticks)
    except KeyboardInterrupt:
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    print("Simulation completed.")

def main():
    parser = argparse.ArgumentParser(description="GeoPulse Fleet Simulator with BPR Dynamic Congestion")
    parser.add_argument("--ticks", type=int, default=100, help="Number of ticks to simulate")
    parser.add_argument("--vehicles", type=int, default=10, help="Number of vehicles to simulate")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--slow-segment", type=str, help="Format: ID@T1..T2 to force slow speed on edge")
    parser.add_argument("--scenario", type=str, help="Path or name of scenario JSON (e.g. sim/scenarios/s2.json)")
    
    args = parser.parse_args()
    asyncio.run(run_simulation(args))

if __name__ == "__main__":
    main()
