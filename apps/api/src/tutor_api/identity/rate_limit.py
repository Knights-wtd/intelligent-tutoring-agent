import threading
import time
from collections.abc import Callable

_MAX_TRACKED_KEYS = 65_536


class LoginRateLimiter:
    """In-memory sliding-window throttle for failed logins, keyed by identifier + client IP.

    Single-instance only: the Compose deployment runs one API process, so process memory
    is the natural store. Fails open — an oversized table is dropped rather than
    blocking legitimate logins.
    """

    def __init__(
        self,
        max_attempts: int,
        lockout_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._lockout_seconds = lockout_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def _recent_failures(self, key: str, now: float) -> list[float]:
        return [
            stamp for stamp in self._failures.get(key, ()) if now - stamp < self._lockout_seconds
        ]

    def is_locked(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            return len(self._recent_failures(key, now)) >= self._max_attempts

    def seconds_until_unlock(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            failures = self._recent_failures(key, now)
            if len(failures) < self._max_attempts:
                return 0
            return max(1, int(self._lockout_seconds - (now - failures[0])) + 1)

    def record_failure(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            failures = self._recent_failures(key, now)
            failures.append(now)
            if len(self._failures) >= _MAX_TRACKED_KEYS:
                self._failures.clear()
            self._failures[key] = failures

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
