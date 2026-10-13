"""Shared outbound HTTP machinery for every external provider.

Every request passes through, in order:
  1. the provider's circuit breaker (fail fast while a provider is down),
  2. the provider's daily call cap,
  3. a per-provider token bucket AND the process-wide global token bucket,
  4. httpx with a timeout,
  5. retry with exponential backoff + jitter for 429 / 5xx / network errors
     (honouring Retry-After),
  6. usage accounting (one api_usage row per HTTP attempt).
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from cit.log import get_logger

log = get_logger(__name__)


class ProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, status_code: int | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status_code = status_code


class CircuitOpenError(ProviderError):
    pass


class DailyCapExceeded(ProviderError):
    pass


class TokenBucket:
    """Async token bucket. `rate_per_minute` tokens refill continuously."""

    def __init__(
        self, rate_per_minute: float, capacity: float | None = None, clock: Callable[[], float] = time.monotonic
    ):
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive")
        self.rate_per_sec = rate_per_minute / 60.0
        # Small burst capacity keeps us well inside provider sliding windows.
        self.capacity = capacity if capacity is not None else max(1.0, min(3.0, rate_per_minute / 10))
        self._tokens = self.capacity
        self._clock = clock
        self._last = clock()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate_per_sec)
        self._last = now

    async def acquire(self) -> float:
        """Wait for a token; return seconds waited."""
        waited = 0.0
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return waited
                delay = (1 - self._tokens) / self.rate_per_sec
                waited += delay
                await asyncio.sleep(delay)


@dataclass
class CircuitBreaker:
    """Opens after `threshold` consecutive failures; cool-down doubles each time it re-opens."""

    threshold: int = 5
    base_cooldown_s: float = 60.0
    max_cooldown_s: float = 1800.0
    consecutive_failures: int = 0
    open_count: int = 0
    open_until: datetime | None = None
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    @property
    def state(self) -> str:
        if self.open_until is None:
            return "closed"
        return "open" if self.now() < self.open_until else "half_open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.open_count = 0
        self.open_until = None

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.state == "half_open" or self.consecutive_failures >= self.threshold:
            cooldown = min(self.max_cooldown_s, self.base_cooldown_s * (2**self.open_count))
            self.open_count += 1
            self.open_until = self.now() + timedelta(seconds=cooldown)


@dataclass(frozen=True)
class ApiCall:
    provider: str
    endpoint: str
    occurred_at: datetime
    status_code: int | None
    latency_ms: int
    ok: bool
    job_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float = 0.0


UsageSink = Callable[[ApiCall], Awaitable[None] | None]


@dataclass
class ProviderPolicy:
    name: str
    base_url: str
    rate_per_minute: float
    daily_cap: int | None = None
    max_retries: int = 3
    backoff_base_s: float = 2.0
    backoff_max_s: float = 60.0
    headers: dict[str, str] = field(default_factory=dict)


RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504, 520, 522, 524}


class ProviderClient:
    def __init__(
        self,
        policy: ProviderPolicy,
        *,
        http: httpx.AsyncClient,
        global_bucket: TokenBucket | None = None,
        usage_sink: UsageSink | None = None,
        breaker: CircuitBreaker | None = None,
        calls_today: int = 0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.policy = policy
        self.http = http
        self.bucket = TokenBucket(policy.rate_per_minute)
        self.global_bucket = global_bucket
        self.usage_sink = usage_sink
        self.breaker = breaker or CircuitBreaker()
        self.calls_today = calls_today
        self.calls_this_client = 0
        self._sleep = sleep
        self.job_name: str | None = None

    async def _record(self, call: ApiCall) -> None:
        if self.usage_sink is None:
            return
        res = self.usage_sink(call)
        if asyncio.iscoroutine(res):
            await res

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(self.policy.backoff_max_s, max(0.0, float(retry_after)))
            except ValueError:
                pass
        exp = self.policy.backoff_base_s * (2**attempt)
        return min(self.policy.backoff_max_s, exp) * (0.5 + random.random() / 2)  # noqa: S311

    async def get_json(self, path: str, params: dict[str, Any] | None = None, *, endpoint: str | None = None) -> Any:
        name = self.policy.name
        label = endpoint or path
        if not self.breaker.allow():
            raise CircuitOpenError(name, f"circuit open until {self.breaker.open_until}")
        url = self.policy.base_url.rstrip("/") + "/" + path.lstrip("/")
        last_exc: Exception | None = None
        for attempt in range(self.policy.max_retries + 1):
            if self.policy.daily_cap is not None and self.calls_today >= self.policy.daily_cap:
                raise DailyCapExceeded(name, f"daily cap of {self.policy.daily_cap} calls reached")
            await self.bucket.acquire()
            if self.global_bucket is not None:
                await self.global_bucket.acquire()
            started = time.monotonic()
            status: int | None = None
            retry_after: str | None = None
            try:
                resp = await self.http.get(url, params=params, headers=self.policy.headers)
                status = resp.status_code
                retry_after = resp.headers.get("retry-after")
                ok = 200 <= status < 300
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                ok = False
                last_exc = exc
            latency = int((time.monotonic() - started) * 1000)
            self.calls_today += 1
            self.calls_this_client += 1
            await self._record(ApiCall(name, label, datetime.now(UTC), status, latency, ok, self.job_name))

            if ok:
                try:
                    data = resp.json()
                except ValueError as exc:
                    self.breaker.record_failure()
                    raise ProviderError(name, f"invalid JSON from {label}", status) from exc
                self.breaker.record_success()
                return data

            # 404 is a valid "not found" answer, not a provider failure.
            if status == 404:
                self.breaker.record_success()
                raise ProviderError(name, f"404 from {label}", 404)
            retryable = status is None or status in RETRYABLE_STATUS
            if not retryable:
                self.breaker.record_failure()
                raise ProviderError(name, f"HTTP {status} from {label}", status)
            if attempt < self.policy.max_retries:
                delay = self._backoff(attempt, retry_after)
                log.warning(
                    "provider_retry",
                    provider=name,
                    endpoint=label,
                    status=status,
                    attempt=attempt + 1,
                    delay_s=round(delay, 2),
                )
                await self._sleep(delay)
                continue
            self.breaker.record_failure()
            msg = f"HTTP {status}" if status else f"network error: {last_exc!r}"
            raise ProviderError(name, f"{msg} from {label} after {attempt + 1} attempts", status)
        raise AssertionError("unreachable")  # pragma: no cover
