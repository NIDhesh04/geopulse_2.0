import os
import time
import asyncio
import redis.asyncio as redis
from worker.fake_routing import FakeRouting

class CongestionWorker:
    def __init__(self, routing_service, redis_url: str):
        self.routing = routing_service
        self.r = redis.from_url(redis_url, decode_responses=True)
        self.group_name = "congestion_group"
        self.consumer_name = "worker_1"
        self.stream_name = "geopulse:pings"
        self.dead_stream = "geopulse:pings:dead"
        
        self.params = {
            'jam_vehicles': 5,
            'max_multiplier': 5.0,
            'alpha': 0.3,
            'free_flow': 50.0
        }
        self.current_multipliers = {}

    def clamp(self, val, min_val=0.0, max_val=1.0):
        return max(min_val, min(val, max_val))

    async def setup(self):
        await self.routing.connect()
        try:
            await self.r.xgroup_create(self.stream_name, self.group_name, id='0', mkstream=True)
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def run(self):
        print("Worker started...")
        while True:
            try:
                # Block for 1 second waiting for new messages
                streams = await self.r.xreadgroup(
                    self.group_name, 
                    self.consumer_name, 
                    {self.stream_name: '>'}, 
                    count=100, 
                    block=1000
                )
                
                if not streams:
                    continue
                
                messages = streams[0][1]
                await self.process_batch(messages)
            except Exception as e:
                print(f"Worker loop error: {e}")
                await asyncio.sleep(1)

    async def process_batch(self, messages):
        valid_pings = []
        msg_ids_to_ack = []
        
        for msg_id, payload in messages:
            try:
                ping = {
                    'vehicle_id': payload['vehicle_id'],
                    'lat': float(payload['lat']),
                    'lon': float(payload['lon']),
                    'speed': float(payload['speed_kmh']),
                    'ts': int(payload['ts'])
                }
                
                # Snap to edge
                edge = await self.routing.snap_to_edge(ping['lat'], ping['lon'])
                if edge:
                    ping['edge_id'] = edge['id']
                    valid_pings.append(ping)
                msg_ids_to_ack.append(msg_id)

            except (KeyError, ValueError) as e:
                # Dead-letter queue
                await self.r.xadd(self.dead_stream, payload)
                msg_ids_to_ack.append(msg_id)

        if valid_pings:
            new_multipliers = self.calculate_multipliers(valid_pings)
            
            # Apply to database
            await self.routing.apply_multipliers(new_multipliers)
            
            # Update local state
            for edge_id, mult in new_multipliers.items():
                self.current_multipliers[edge_id] = mult

        # Ack after apply
        if msg_ids_to_ack:
            await self.r.xack(self.stream_name, self.group_name, *msg_ids_to_ack)

    def calculate_multipliers(self, pings):
        # Group by edge
        edge_pings = {}
        for p in pings:
            edge_pings.setdefault(p['edge_id'], []).append(p)
            
        new_mults = {}
        for edge_id, p_list in edge_pings.items():
            avg_speed = sum(p['speed'] for p in p_list) / len(p_list)
            num_vehicles = len(p_list)
            
            speed_factor = self.clamp(1.0 - (avg_speed / self.params['free_flow']))
            density_factor = self.clamp(num_vehicles / self.params['jam_vehicles'])
            
            score = speed_factor * density_factor
            target = 1.0 + (self.params['max_multiplier'] - 1.0) * score
            
            prev = self.current_multipliers.get(edge_id, 1.0)
            new_mults[edge_id] = (self.params['alpha'] * target) + ((1 - self.params['alpha']) * prev)
            
        return new_mults

async def main():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    worker = CongestionWorker(FakeRouting(), redis_url)
    await worker.setup()
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
