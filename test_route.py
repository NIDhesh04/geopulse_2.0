import asyncio
from api.routing import RoutingService
async def main():
    r = RoutingService("postgresql://geopulse:password@localhost:5432/geopulse_db")
    await r.connect()
    try:
        res = await r.route(41.8845, -87.6330, 41.8785, -87.6250, static=True)
        print("Success:", res is not None)
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(main())
