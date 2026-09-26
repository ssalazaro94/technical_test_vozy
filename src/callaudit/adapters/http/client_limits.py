"""Per-client request limit for the audit routes.

A sliding window per client IP, in memory. It keeps one client from using up
the whole daily model budget; the hard spending cap is the daily call budget,
which lives in the database. The window resets if the process restarts, and a
client could spoof its forwarded address: acceptable for a fairness limit,
not for a spending guarantee.
"""

import time
from collections import deque
from collections.abc import Callable
from math import ceil

MAX_TRACKED_CLIENTS = 10_000


class ClientRateLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: float = 3600,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_requests = max_requests
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, client: str) -> int | None:
        """Register a request; return None if allowed, or the seconds to wait if not."""
        now = self._clock()
        if len(self._hits) > MAX_TRACKED_CLIENTS:
            self._forget_idle(now)
        hits = self._hits.setdefault(client, deque())
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._max_requests:
            return max(1, ceil(self._window - (now - hits[0])))
        hits.append(now)
        return None

    def _forget_idle(self, now: float) -> None:
        """Drop clients whose requests all left the window, so memory stays bounded."""
        idle = [c for c, hits in self._hits.items() if not hits or now - hits[-1] >= self._window]
        for client in idle:
            del self._hits[client]
