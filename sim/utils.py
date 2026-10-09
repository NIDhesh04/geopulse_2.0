import random
import asyncio

def get_backoff_delay(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    """
    Calculate exponential backoff with full jitter.
    Wait time = min(max_delay, random(0, base_delay * 2^attempt))
    """
    temp_delay = min(max_delay, base_delay * (2 ** attempt))
    return random.uniform(0, temp_delay)

async def connect_with_backoff(connect_func, *args, **kwargs):
    attempt = 0
    while True:
        try:
            return await connect_func(*args, **kwargs)
        except Exception as e:
            delay = get_backoff_delay(attempt)
            print(f"Connection failed: {e}. Retrying in {delay:.2f}s...")
            await asyncio.sleep(delay)
            attempt += 1
