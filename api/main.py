import os
import json
import asyncio
import time
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, APIRouter, Response, Query
import redis.asyncio as redis
from api.routing import RoutingService

# Setup JSON structured logging
logging.basicConfig(level=logging.INFO, format='{"time": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}')
logger = logging.getLogger("api")

from fastapi.middleware.cors import CORSMiddleware

def create_app() -> FastAPI:
    app = FastAPI(title="GeoPulse API")
    app.state.redis = None
    app.state.routing = None
    app.state.start_time = time.time()
    app.state.pings_in = 0
    app.state.pings_rejected = 0

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup_event():
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        db_url = os.getenv("DATABASE_URL", "postgresql://geopulse:password@localhost:5432/geopulse_db")
        
        # Lazy Redis
        r = redis.from_url(redis_url, decode_responses=True)
        try:
            await r.ping()
            app.state.redis = r
            logger.info("Connected to Redis")
        except Exception as e:
            logger.warning(f"Redis connection failed on startup: {e}")
            app.state.redis = r
            
        # DB connection
        try:
            routing = RoutingService(db_url)
            await routing.connect()
            app.state.routing = routing
            logger.info("Connected to Database")
        except Exception as e:
            logger.warning(f"DB connection failed on startup: {e}")

    @app.on_event("shutdown")
    async def shutdown_event():
        if app.state.redis:
            await app.state.redis.close()
        if app.state.routing:
            await app.state.routing.close()

    @app.get("/health")
    async def health_check():
        r = app.state.redis
        if not r:
            return {"status": "degraded", "reason": "redis_unavailable"}
        try:
            hb = await r.get("worker:heartbeat")
            now = time.time()
            if hb is None:
                return {"status": "degraded", "worker": "missing_heartbeat"}
            last_tick = float(hb)
            if now - last_tick > 60:
                return {"status": "degraded", "worker": "stale_heartbeat", "age_s": round(now - last_tick, 1)}
            return {"status": "ok"}
        except Exception as e:
            return {"status": "degraded", "error": str(e)}

    @app.get("/metrics")
    async def get_metrics():
        r = app.state.redis
        now = time.time()
        
        stream_lag = 0
        worker_last_tick = None
        worker_healthy = False

        if r:
            try:
                groups = await r.xinfo_groups("geopulse:pings")
                for g in groups:
                    if g.get("name") == "congestion_group":
                        # In Redis 7+, lag is directly reported; fallback to pending count
                        stream_lag = g.get("lag") if g.get("lag") is not None else g.get("pending", 0)
                        break
            except Exception:
                stream_lag = 0

            try:
                hb = await r.get("worker:heartbeat")
                if hb is not None:
                    worker_last_tick = int(float(hb))
                    if now - worker_last_tick <= 60:
                        worker_healthy = True
            except Exception:
                pass

        uptime_seconds = int(now - app.state.start_time)

        return {
            "pings_in": app.state.pings_in,
            "pings_rejected": app.state.pings_rejected,
            "stream_lag": stream_lag,
            "worker_last_tick": worker_last_tick,
            "worker_healthy": worker_healthy,
            "uptime_seconds": uptime_seconds
        }

    @app.get("/vehicles")
    async def get_vehicles():
        r = app.state.redis
        if not r:
            return {"error": "Redis not connected"}
        vehicles_data = await r.hgetall("vehicles:latest")
        # parse json strings back to dicts
        return {vid: json.loads(vdata) for vid, vdata in vehicles_data.items()}

    @app.get("/multipliers")
    async def get_multipliers():
        routing = app.state.routing
        if not routing:
            return {"error": "Routing service unavailable"}
        
        all_mults = await routing.get_multipliers()
        # Return only edges with multiplier > 1.0 for efficiency
        congested = {edge_id: mult for edge_id, mult in all_mults.items() if mult > 1.0}
        return congested

    @app.get("/route")
    async def get_route(
        response: Response,
        src_lat: float, src_lon: float, 
        dst_lat: float, dst_lon: float, 
        static: bool = False
    ):
        routing = app.state.routing
        if not routing:
            return {"error": "Routing service unavailable"}
            
        start_time = time.time()
        path = await routing.route(src_lat, src_lon, dst_lat, dst_lon, static=static)
        latency_ms = (time.time() - start_time) * 1000
        
        response.headers["X-Route-Latency"] = f"{latency_ms:.2f}ms"
        logger.info(f"Route calculated in {latency_ms:.2f}ms")
        
        if not path:
            return {"error": "No route found"}
        return {"path": path}

    @app.websocket("/ws/ingest")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        r = app.state.redis
        
        while True:
            try:
                data = await websocket.receive_text()
                app.state.pings_in += 1
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    app.state.pings_rejected += 1
                    await websocket.send_json({"error": "Invalid JSON format"})
                    continue

                required_keys = {"vehicle_id", "lat", "lon", "speed_kmh", "ts"}
                if not required_keys.issubset(payload.keys()):
                    app.state.pings_rejected += 1
                    await websocket.send_json({"error": f"Missing fields. Required: {required_keys}"})
                    continue

                if r:
                    try:
                        await r.xadd(
                            "geopulse:pings",
                            {k: str(v) for k, v in payload.items()},
                            maxlen=10000,
                            approximate=True
                        )
                    except Exception as e:
                        logger.error(f"Redis write error: {e}")
            
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WS error: {e}")
                break

    return app

app = create_app()
