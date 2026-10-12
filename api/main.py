import os
import json
import asyncio
import time
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, APIRouter, Response, Query
from fastapi.responses import JSONResponse
import redis.asyncio as redis
from asyncpg.exceptions import PostgresConnectionError, CannotConnectNowError
from api.routing import RoutingService, DatabaseUnavailableError

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
            try:
                await app.state.redis.close()
            except Exception:
                pass
        if app.state.routing:
            try:
                await app.state.routing.close()
            except Exception:
                pass

    @app.get("/health")
    async def health_check():
        routing = app.state.routing
        if routing and getattr(routing, "db_active", False) is True:
            if not routing.pool:
                return {"status": "degraded", "database": "disconnected"}
            try:
                async with routing.pool.acquire() as conn:
                    await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout=1.0)
            except Exception:
                return {"status": "degraded", "database": "disconnected"}

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
        redis_status = "offline"

        if r:
            try:
                try:
                    await asyncio.wait_for(r.ping(), timeout=1.0)
                    redis_status = "online"
                except Exception:
                    redis_status = "offline"
                
                try:
                    groups = await r.xinfo_groups("geopulse:pings")
                    for g in groups:
                        if g.get("name") == "congestion_group":
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
            except Exception:
                redis_status = "offline"

        uptime_seconds = int(now - app.state.start_time)

        return {
            "pings_in": app.state.pings_in,
            "pings_rejected": app.state.pings_rejected,
            "stream_lag": stream_lag,
            "worker_last_tick": worker_last_tick,
            "worker_healthy": worker_healthy,
            "uptime_seconds": uptime_seconds,
            "redis": redis_status
        }

    @app.get("/vehicles")
    async def get_vehicles():
        r = app.state.redis
        if not r:
            return {"error": "Redis not connected"}
        try:
            vehicles_data = await r.hgetall("vehicles:latest")
            return {vid: json.loads(vdata) for vid, vdata in vehicles_data.items()}
        except Exception as e:
            return {"error": f"Failed to get vehicles: {e}"}

    @app.get("/multipliers")
    async def get_multipliers():
        routing = app.state.routing
        if not routing:
            return {"error": "Routing service unavailable"}
        
        try:
            all_mults = await routing.get_multipliers()
            congested = {edge_id: mult for edge_id, mult in all_mults.items() if mult > 1.0}
            return congested
        except DatabaseUnavailableError:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "database_unavailable",
                    "message": "Routing engine temporarily unable to connect to database",
                    "retry_after_seconds": 5
                },
                headers={"Retry-After": "5"}
            )
        except Exception as e:
            return {"error": f"Error retrieving multipliers: {e}"}

    @app.get("/route")
    async def get_route(
        response: Response,
        src_lat: float, src_lon: float, 
        dst_lat: float, dst_lon: float, 
        static: bool = False
    ):
        routing = app.state.routing
        if not routing or routing.pool is None or getattr(routing, "_down", False) is True:
            db_url = os.getenv("DATABASE_URL", "postgresql://geopulse:password@localhost:5432/geopulse_db")
            if not routing:
                routing = RoutingService(db_url)
                app.state.routing = routing
            try:
                await asyncio.wait_for(routing.connect(), timeout=2.0)
                routing._down = False
            except Exception:
                routing._down = True
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "database_unavailable",
                        "message": "Routing engine temporarily unable to connect to database",
                        "retry_after_seconds": 5
                    },
                    headers={"Retry-After": "5"}
                )

        # Check worker heartbeat in Redis for staleness
        costs_stale = False
        worker_heartbeat_age_s = None
        r = app.state.redis
        if r:
            try:
                hb = await asyncio.wait_for(r.get("worker:heartbeat"), timeout=1.0)
                if hb is not None:
                    last_tick = float(hb)
                    worker_heartbeat_age_s = round(time.time() - last_tick, 1)
                    if worker_heartbeat_age_s > 60.0:
                        costs_stale = True
                else:
                    costs_stale = True
            except Exception as e:
                logger.warning(f"Redis heartbeat check error: {e}")
                costs_stale = True
        else:
            costs_stale = True

        # If costs are stale, trigger asymptotic decay query
        if costs_stale:
            try:
                asyncio.create_task(routing.decay_multipliers())
            except Exception as e:
                logger.warning(f"Failed to trigger decay_multipliers: {e}")
            
        start_time = time.time()
        try:
            path = await routing.route(src_lat, src_lon, dst_lat, dst_lon, static=static)
            routing._down = False
        except (DatabaseUnavailableError, PostgresConnectionError, CannotConnectNowError, asyncio.TimeoutError, TimeoutError, OSError) as e:
            logger.warning(f"Database unavailable during route calculation: {e}")
            routing._down = True
            routing.pool = None
            return JSONResponse(
                status_code=503,
                content={
                    "error": "database_unavailable",
                    "message": "Routing engine temporarily unable to connect to database",
                    "retry_after_seconds": 5
                },
                headers={"Retry-After": "5"}
            )
        except Exception as e:
            logger.error(f"Unexpected routing error: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": "routing_error", "message": str(e)}
            )

        latency_ms = (time.time() - start_time) * 1000
        response.headers["X-Route-Latency"] = f"{latency_ms:.2f}ms"
        logger.info(f"Route calculated in {latency_ms:.2f}ms")
        
        if not path:
            return {
                "error": "No route found",
                "costs_stale": costs_stale,
                "worker_heartbeat_age_s": worker_heartbeat_age_s
            }

        return {
            "path": path,
            "costs_stale": costs_stale,
            "worker_heartbeat_age_s": worker_heartbeat_age_s
        }

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
                        await asyncio.wait_for(
                            r.xadd(
                                "geopulse:pings",
                                {k: str(v) for k, v in payload.items()},
                                maxlen=10000,
                                approximate=True
                            ),
                            timeout=1.0
                        )
                    except Exception as e:
                        logger.error(f"Redis write error: {e}")
                        app.state.pings_rejected += 1
                        await websocket.send_json({"error": "Redis unavailable", "details": str(e)})
                else:
                    app.state.pings_rejected += 1
                    await websocket.send_json({"error": "Redis unavailable"})
            
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WS error: {e}")
                break

    return app

app = create_app()

