import argparse
import asyncio
import json
import random
import time
import websockets
from sim.utils import connect_with_backoff

async def vehicle_loop(vehicle_id: int, ws_url: str):
    async def connect():
        return await websockets.connect(ws_url)
        
    try:
        ws = await connect_with_backoff(connect)
        
        while True:
            # Mock ping data
            ping = {
                "vehicle_id": f"v_{vehicle_id}",
                "lat": 41.8825 + random.uniform(-0.005, 0.005),
                "lon": -87.6250 + random.uniform(-0.005, 0.005),
                "speed_kmh": random.uniform(10.0, 60.0),
                "ts": int(time.time())
            }
            
            await ws.send(json.dumps(ping))
            await asyncio.sleep(1.0) # 1 ping per second
            
    except Exception as e:
        print(f"Vehicle {vehicle_id} loop terminated: {e}")


async def run_simulation(args):
    if args.seed is not None:
        random.seed(args.seed)
        
    ws_url = "ws://localhost:8000/ws/ingest"
    tasks = []
    
    for i in range(args.vehicles):
        tasks.append(asyncio.create_task(vehicle_loop(i, ws_url)))
        
    # Run for a certain duration or indefinitely (ticks currently maps to seconds in this basic mock)
    try:
        await asyncio.sleep(args.ticks)
    except KeyboardInterrupt:
        pass
    
    for task in tasks:
        task.cancel()

def main():
    parser = argparse.ArgumentParser(description="GeoPulse Fleet Simulator")
    parser.add_argument("--ticks", type=int, default=100, help="Number of ticks to simulate")
    parser.add_argument("--vehicles", type=int, default=10, help="Number of vehicles to simulate")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--slow-segment", type=str, help="Format: ID@T1..T2 to force slow speed on edge")
    
    args = parser.parse_args()
    
    print(f"Starting simulator with {args.vehicles} vehicles for {args.ticks} ticks...")
    if args.slow_segment:
        print(f"Applying slow segment override: {args.slow_segment}")
        
    asyncio.run(run_simulation(args))

if __name__ == "__main__":
    main()
