"""Route-aware global in-memory fixed-window request rate limiting."""

import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from app.api.errors import public_error_response
from app.config.application import DEFAULT_RATE_LIMIT_MAX_ENTRIES
from starlette.types import ASGIApp, Receive, Scope, Send

TASK_RUN_PATH = re.compile(r"^/api/v1/tasks/[^/]+/runs/?$")
NETWORK_TEST_PATH = re.compile(
    r"^/api/v1/settings/markets/[^/]+/network-test/?$"
)
COMPUTE_PATH = "/api/v1/indicators/compute"
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class RateBucket(StrEnum):
    READ = "read"
    WRITE = "write"
    COMPUTE = "compute"


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    read: int
    write: int
    compute: int
    window_seconds: float
    max_entries: int = DEFAULT_RATE_LIMIT_MAX_ENTRIES

    def __post_init__(self) -> None:
        if min(self.read, self.write, self.compute) < 1:
            raise ValueError("Rate limits must be positive")
        if self.window_seconds <= 0:
            raise ValueError("Rate-limit window must be positive")
        if self.max_entries < 1:
            raise ValueError("Rate-limit entry capacity must be positive")

    def for_bucket(self, bucket: RateBucket) -> int:
        return {
            RateBucket.READ: self.read,
            RateBucket.WRITE: self.write,
            RateBucket.COMPUTE: self.compute,
        }[bucket]


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0


class InMemoryFixedWindowRateLimiter:
    """Share one bounded counter map per client and route-policy bucket."""

    def __init__(
        self,
        policy: RateLimitPolicy,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policy = policy
        self._clock = clock
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, RateBucket], tuple[int, int]] = {}

    def check(self, client: str, bucket: RateBucket) -> RateLimitDecision:
        now = self._clock()
        window = int(now // self._policy.window_seconds)
        key = (client, bucket)
        with self._lock:
            active = {
                item: count
                for item, count in self._counters.items()
                if count[0] == window
            }
            previous = active.get(key)
            if previous is None and len(active) >= self._policy.max_entries:
                # Fail closed without eviction: attackers cannot replace existing
                # counters to bypass their limits or grow the map beyond capacity.
                self._counters = active
                return self._limited(window, now)
            count = 1 if previous is None else previous[1] + 1
            if count > self._policy.for_bucket(bucket):
                self._counters = active
                return self._limited(window, now)
            self._counters = {**active, key: (window, count)}
            return RateLimitDecision(True)

    def _limited(self, window: int, now: float) -> RateLimitDecision:
        retry = math.ceil((window + 1) * self._policy.window_seconds - now)
        return RateLimitDecision(False, max(1, retry))


def bucket_for_request(method: str, path: str) -> RateBucket:
    normalized_path = path.rstrip("/") or "/"
    if method == "POST" and (
        normalized_path == COMPUTE_PATH
        or TASK_RUN_PATH.fullmatch(path) is not None
        or NETWORK_TEST_PATH.fullmatch(normalized_path) is not None
    ):
        return RateBucket.COMPUTE
    return RateBucket.READ if method in READ_METHODS else RateBucket.WRITE


class RateLimitMiddleware:
    """Apply local-client limits before routing, body parsing, or computation."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        policy: RateLimitPolicy,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.limiter = InMemoryFixedWindowRateLimiter(policy, clock=clock)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        client_key = client[0] if client is not None else "local"
        decision = self.limiter.check(
            client_key,
            bucket_for_request(scope["method"], scope["path"]),
        )
        if not decision.allowed:
            response = public_error_response(
                scope["path"],
                code="rate_limit_exceeded",
                message="Too many requests",
                status_code=429,
                headers={"Retry-After": str(decision.retry_after)},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
