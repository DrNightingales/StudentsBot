import time
from collections import deque
from threading import Lock


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._lock = Lock()
        self._hits: dict[str, deque[float]] = {}
        self._last_cleanup = 0.0
        self._cleanup_interval = max(window_seconds, 60)

    def allow(self, key: str) -> bool:
        if self._max_requests <= 0 or self._window_seconds <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                self._hits[key] = hits
            while hits and (now - hits[0]) > self._window_seconds:
                hits.popleft()
            if len(hits) >= self._max_requests:
                return False
            hits.append(now)
            if now - self._last_cleanup >= self._cleanup_interval:
                cutoff = now - self._window_seconds
                stale = [k for k, v in self._hits.items() if not v or v[-1] < cutoff]
                for stale_key in stale:
                    self._hits.pop(stale_key, None)
                self._last_cleanup = now
            return True
