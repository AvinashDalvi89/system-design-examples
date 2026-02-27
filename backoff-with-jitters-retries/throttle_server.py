import time
import asyncio
from collections import deque
from fastapi import FastAPI, Response

app = FastAPI()

# ---- Brownout settings (simulates brief downstream outage windows) ----
BROWNOUT_PERIOD_SEC = 3.0   # every 3 seconds...
BROWNOUT_DURATION_SEC = 0.8 # ...fail for first 0.8s

# ---- Rate limit settings (optional) ----
# Set to None to disable rate limiting entirely
RPS_LIMIT = 25              # try 10, 25, or None
WINDOW_SEC = 1.0

hits = deque()
lock = asyncio.Lock()

@app.get("/work")
async def work(response: Response):
    now = time.time()

    # 1) Brownout: fail everything during the outage window
    if (now % BROWNOUT_PERIOD_SEC) < BROWNOUT_DURATION_SEC:
        response.status_code = 503
        return {"ok": False, "error": "brownout"}

    # 2) Optional RPS limiter (simple sliding window)
    if RPS_LIMIT is not None:
        async with lock:
            while hits and now - hits[0] > WINDOW_SEC:
                hits.popleft()

            if len(hits) >= RPS_LIMIT:
                response.status_code = 429
                return {"ok": False, "error": "throttled"}

            hits.append(now)

    # 3) Simulate some work time (downstream processing latency)
    await asyncio.sleep(0.02)
    return {"ok": True}