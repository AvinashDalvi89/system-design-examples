import asyncio
import random
import time
from dataclasses import dataclass
from typing import Optional, Tuple
import httpx

URL = "http://127.0.0.1:8000/work"

@dataclass
class Result:
    name: str
    workers: int
    ops_per_worker: int
    success: int
    failures: int
    total_requests: int
    duration_sec: float

# ---------------- Retry delay strategies ----------------

def fixed_delay(_: float, __: float, ___: int, ____: Optional[float] = None) -> float:
    return 0.1

def exp_no_jitter(base: float, cap: float, attempt: int, _: Optional[float] = None) -> float:
    return min(cap, base * (2 ** attempt))

def full_jitter_with_floor(base: float, cap: float, attempt: int, _: Optional[float] = None) -> float:
    upper = min(cap, base * (2 ** attempt))
    # floor prevents "immediate retry" storms
    return random.uniform(base, upper)

def equal_jitter(base: float, cap: float, attempt: int, _: Optional[float] = None) -> float:
    upper = min(cap, base * (2 ** attempt))
    half = upper / 2.0
    return half + random.uniform(0, half)

def decorrelated_jitter(base: float, cap: float, _: int, prev_sleep: Optional[float] = None) -> float:
    # Must keep per-operation state (prev_sleep)
    if prev_sleep is None:
        prev_sleep = base
    return min(cap, random.uniform(base, prev_sleep * 3))

# ---------------- Core runner ----------------

async def do_one_op(
    client: httpx.AsyncClient,
    strategy_name: str,
    max_retries: int = 12,
    base: float = 0.05,
    cap: float = 1.0,
) -> Tuple[bool, int]:
    """
    Returns (success, requests_made)
    """
    reqs = 0
    attempt = 0
    prev_sleep = None  # only used by decorrelated jitter

    while True:
        reqs += 1
        try:
            r = await client.get(URL, timeout=2.0)
            if r.status_code == 200:
                return True, reqs

            if r.status_code in (429, 500, 502, 503, 504):
                if attempt >= max_retries:
                    return False, reqs

                if strategy_name == "fixed":
                    sleep = fixed_delay(base, cap, attempt, prev_sleep)
                elif strategy_name == "exp_no_jitter":
                    sleep = exp_no_jitter(base, cap, attempt, prev_sleep)
                elif strategy_name == "full_jitter_floor":
                    sleep = full_jitter_with_floor(base, cap, attempt, prev_sleep)
                elif strategy_name == "equal_jitter":
                    sleep = equal_jitter(base, cap, attempt, prev_sleep)
                elif strategy_name == "decorrelated_jitter":
                    sleep = decorrelated_jitter(base, cap, attempt, prev_sleep)
                    prev_sleep = sleep  # update per-operation state
                else:
                    raise ValueError(f"Unknown strategy: {strategy_name}")

                await asyncio.sleep(sleep)
                attempt += 1
                continue

            # Other statuses: fail fast
            return False, reqs

        except (httpx.TimeoutException, httpx.TransportError):
            if attempt >= max_retries:
                return False, reqs

            if strategy_name == "fixed":
                sleep = fixed_delay(base, cap, attempt, prev_sleep)
            elif strategy_name == "exp_no_jitter":
                sleep = exp_no_jitter(base, cap, attempt, prev_sleep)
            elif strategy_name == "full_jitter_floor":
                sleep = full_jitter_with_floor(base, cap, attempt, prev_sleep)
            elif strategy_name == "equal_jitter":
                sleep = equal_jitter(base, cap, attempt, prev_sleep)
            elif strategy_name == "decorrelated_jitter":
                sleep = decorrelated_jitter(base, cap, attempt, prev_sleep)
                prev_sleep = sleep
            else:
                raise ValueError(f"Unknown strategy: {strategy_name}")

            await asyncio.sleep(sleep)
            attempt += 1

async def run(strategy: str, workers: int, ops_per_worker: int) -> Result:
    start = time.time()
    total_requests = 0
    success = 0
    failures = 0

    async with httpx.AsyncClient() as client:
        sem = asyncio.Semaphore(workers)

        async def worker_task():
            nonlocal total_requests, success, failures
            async with sem:
                for _ in range(ops_per_worker):
                    ok, reqs = await do_one_op(client, strategy)
                    total_requests += reqs
                    if ok:
                        success += 1
                    else:
                        failures += 1

        tasks = [asyncio.create_task(worker_task()) for _ in range(workers)]
        await asyncio.gather(*tasks)

    dur = time.time() - start
    return Result(strategy, workers, ops_per_worker, success, failures, total_requests, dur)

async def main():
    workers = 120
    ops_per_worker = 3

    strategies = [
        "fixed",
        "exp_no_jitter",
        "full_jitter_floor",
        "equal_jitter",
        "decorrelated_jitter",
    ]

    print(f"Target URL: {URL}")
    print(f"workers={workers}, ops_per_worker={ops_per_worker} (total ops={workers * ops_per_worker})")

    for s in strategies:
        r = await run(s, workers, ops_per_worker)
        print(f"\n== {r.name} ==")
        print(f"workers={r.workers}, ops/worker={r.ops_per_worker}")
        print(f"success={r.success}, failures={r.failures}")
        print(f"total_requests={r.total_requests}")
        print(f"duration_sec={r.duration_sec:.2f}")

if __name__ == "__main__":
    asyncio.run(main())