import os
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import redis.asyncio as redis

def create_app() -> FastAPI:
    app = FastAPI(title="GeoPulse API")
    app.state.redis = None

    @app.on_event("startup")
    async def startup_event():
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        # Lazy connection: test ping but don't crash if down
        r = redis.from_url(redis_url, decode_responses=True)
        try:
            await r.ping()
            app.state.redis = r
        except Exception as e:
            print(f"Warning: Redis connection failed on startup: {e}")
            app.state.redis = r # Keep the object for later retries

    @app.on_event("shutdown")
    async def shutdown_event():
        if app.state.redis:
            await app.state.redis.close()

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    @app.websocket("/ws/ingest")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        r = app.state.redis
        
        while True:
            try:
                data = await websocket.receive_text()
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    await websocket.send_json({"error": "Invalid JSON format"})
                    continue

                required_keys = {"vehicle_id", "lat", "lon", "speed_kmh", "ts"}
                if not required_keys.issubset(payload.keys()):
                    await websocket.send_json({"error": f"Missing fields. Required: {required_keys}"})
                    continue

                # Push to Redis stream
                if r:
                    try:
                        await r.xadd(
                            "geopulse:pings",
                            {k: str(v) for k, v in payload.items()},
                            maxlen=10000,
                            approximate=True
                        )
                    except Exception as e:
                        # Log Redis error but don't drop WS
                        print(f"Redis write error: {e}")
            
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"WS error: {e}")
                break

    return app

app = create_app()
