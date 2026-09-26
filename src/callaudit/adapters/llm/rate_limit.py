"""Client-side request pacing, so the free tier quota is not hit in the first place."""

import asyncio
import time
from collections.abc import Awaitable, Callable


class MinIntervalRateLimiter:
    """Spaces request starts evenly: at most `requests_per_minute`, never in bursts.

    Retries with backoff handle a 429 after the fact; pacing avoids most of
    them, which matters because every rejected request still counts against
    some quotas.
    """

    def __init__(
        self,
        requests_per_minute: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = 60.0 / requests_per_minute
        self._clock = clock
        self._sleep = sleep
        self._next_slot = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
            if slot > now:
                await self._sleep(slot - now)
