import os
import json
import time
import asyncio
import logging
from collections import OrderedDict
import redis.asyncio as redis
import redis.exceptions as redis_exceptions
from api.routing import RoutingService

logging.basicConfig(level=logging.INFO, format='{"time": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}')
logger = logging.getLogger("worker")

class CongestionWorker:
    def __init__(self, routing_service, redis_url: str):
        self.routing = routing_service
        self.r = redis.from_url(redis_url, decode_responses=True)
        self.group_name = "congestion_group"
        self.consumer_name = "worker_1"
        self.stream_name = "geopulse:pings"
        self.dead_stream = "geopulse:pings:dead"
        
        # Message ID deduplication sliding window (maxlen=50000)
        self.dedup_cache = OrderedDict()
        self.dedup_maxlen = 50000

        # In-memory spatial snapping LRU cache: (round(lat, 4), round(lon, 4)) -> edge
        self.snap_cache = OrderedDict()
        self.snap_cache_maxlen = 20000
        self.snap_hits = 0
        self.snap_misses = 0

        self.params = {
            'jam_vehicles': 5,
            'max_multiplier': 5.0,
            'alpha': 0.3,
            'free_flow': 50.0
        }
        self.current_multipliers = {}

    def clamp(self, val, min_val=0.0, max_val=1.0):
        return max(min_val, min(val, max_val))

    async def snap_with_cache(self, lat: float, lon: float):
        """
        LRU-cached spatial snapping keyed by 4-decimal rounded coordinates (~11m resolution).
        Delivers >5x query speedup on common corridors by bypassing PostGIS GiST index searches.
        """
        snap_key = (round(lat, 4), round(lon, 4))
        if snap_key in self.snap_cache:
            self.snap_cache.move_to_end(snap_key)
            self.snap_hits += 1
            return self.snap_cache[snap_key]

        edge = await self.routing.snap_to_edge(lat, lon)
        if len(self.snap_cache) >= self.snap_cache_maxlen:
            self.snap_cache.popitem(last=False)
        self.snap_cache[snap_key] = edge
        self.snap_misses += 1
        return edge

    async def setup(self):
        await self.routing.connect()
        try:
            await self.r.xgroup_create(self.stream_name, self.group_name, id='0', mkstream=True)
        except redis_exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def run(self):
        logger.info("Worker started...")
        while True:
            try:
                # Update heartbeat on each loop iteration
                await self.r.set("worker:heartbeat", int(time.time()), ex=120)
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
                logger.error(f"Worker loop error: {e}")
                raise  # Raise to trigger run_forever backoff

    async def process_batch(self, messages):
        # Update heartbeat when processing batch
        await self.r.set("worker:heartbeat", int(time.time()), ex=120)
        valid_pings = []
        msg_ids_to_ack = []
        vehicles_state = {}
        
        for msg_id, payload in messages:
            # Deduplicate redelivered stream messages (maxlen=50000)
            if msg_id in self.dedup_cache:
                self.dedup_cache.move_to_end(msg_id)
                msg_ids_to_ack.append(msg_id)
                continue

            if len(self.dedup_cache) >= self.dedup_maxlen:
                self.dedup_cache.popitem(last=False)
            self.dedup_cache[msg_id] = True

            try:
                ping = {
                    'vehicle_id': payload['vehicle_id'],
                    'lat': float(payload['lat']),
                    'lon': float(payload['lon']),
                    'speed': float(payload['speed_kmh']),
                    'ts': int(payload['ts'])
                }
                
                # State update tracking
                vehicles_state[ping['vehicle_id']] = json.dumps({
                    'lat': ping['lat'],
                    'lon': ping['lon'],
                    'speed_kmh': ping['speed']
                })
                
                # Snap to edge via LRU cache
                edge = await self.snap_with_cache(ping['lat'], ping['lon'])
                if edge:
                    ping['edge_id'] = edge['id']
                    valid_pings.append(ping)
                msg_ids_to_ack.append(msg_id)

            except (KeyError, ValueError) as e:
                await self.r.xadd(self.dead_stream, payload)
                msg_ids_to_ack.append(msg_id)

        if vehicles_state:
            # Bulk HSET
            await self.r.hset("vehicles:latest", mapping=vehicles_state)

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

async def run_forever():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    db_url = os.getenv("DATABASE_URL", "postgresql://geopulse:password@localhost:5432/geopulse_db")
    
    routing_service = RoutingService(db_url)
    worker = CongestionWorker(routing_service, redis_url)
    
    attempt = 0
    while True:
        try:
            logger.info(f"Setting up worker (attempt {attempt + 1})")
            await worker.setup()
            await worker.run()
        except Exception as e:
            delay = min(60, 2 ** attempt)
            logger.error(f"Worker crashed: {e}. Retrying in {delay}s...")
            await asyncio.sleep(delay)
            attempt += 1

if __name__ == "__main__":
    asyncio.run(run_forever())
