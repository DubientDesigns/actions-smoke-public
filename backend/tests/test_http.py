from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from cit.providers.http import (
    CircuitBreaker,
    CircuitOpenError,
    DailyCapExceeded,
    ProviderClient,
    ProviderError,
    ProviderPolicy,
    TokenBucket,
)

BASE = "https://provider.test/api"


def make_client(**kw):
    calls = []
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    pol = ProviderPolicy("geckoterminal", BASE, rate_per_minute=6000, max_retries=kw.pop("max_retries", 3))
    c = ProviderClient(pol, http=httpx.AsyncClient(), usage_sink=calls.append, sleep=fake_sleep, **kw)
    return c, calls, sleeps


async def test_token_bucket_paces_requests():
    t = [0.0]
    b = TokenBucket(60, capacity=1, clock=lambda: t[0])
    assert await b.acquire() == 0
    # Without advancing the fake clock the bucket must ask to wait ~1s (60/min).
    import asyncio

    async def advance():
        await asyncio.sleep(0)
        t[0] += 1.0

    waited, _ = await asyncio.gather(b.acquire(), advance())
    assert waited == pytest.approx(1.0)


def test_circuit_breaker_opens_and_half_opens():
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    br = CircuitBreaker(threshold=3, base_cooldown_s=60, now=lambda: now[0])
    for _ in range(2):
        br.record_failure()
    assert br.state == "closed"
    br.record_failure()
    assert br.state == "open" and not br.allow()
    now[0] += timedelta(seconds=61)
    assert br.state == "half_open" and br.allow()
    br.record_failure()  # failed probe re-opens with doubled cool-down
    assert br.state == "open"
    assert br.open_until == now[0] + timedelta(seconds=120)
    now[0] += timedelta(seconds=121)
    br.record_success()
    assert br.state == "closed"


@respx.mock
async def test_retries_429_then_succeeds_and_records_usage():
    route = respx.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(429, headers={"retry-after": "7"}), httpx.Response(200, json={"ok": 1})]
    )
    c, calls, sleeps = make_client()
    assert await c.get_json("/x") == {"ok": 1}
    assert route.call_count == 2
    assert sleeps == [7.0]
    assert [(x.status_code, x.ok) for x in calls] == [(429, False), (200, True)]
    assert c.breaker.state == "closed"


@respx.mock
async def test_gives_up_after_retries_and_counts_failure():
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(503))
    c, calls, _ = make_client(max_retries=2)
    with pytest.raises(ProviderError, match="after 3 attempts"):
        await c.get_json("/x")
    assert len(calls) == 3
    assert c.breaker.consecutive_failures == 1


@respx.mock
async def test_non_retryable_status_fails_fast():
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(401))
    c, calls, _ = make_client()
    with pytest.raises(ProviderError) as ei:
        await c.get_json("/x")
    assert ei.value.status_code == 401 and len(calls) == 1


@respx.mock
async def test_network_errors_are_retried():
    respx.get(f"{BASE}/x").mock(side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json=[])])
    c, calls, _ = make_client()
    assert await c.get_json("/x") == []
    assert calls[0].status_code is None and not calls[0].ok


@respx.mock
async def test_open_circuit_blocks_without_http():
    route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, json={}))
    br = CircuitBreaker(threshold=1)
    br.record_failure()
    c, _, _ = make_client(breaker=br)
    with pytest.raises(CircuitOpenError):
        await c.get_json("/x")
    assert route.call_count == 0


@respx.mock
async def test_daily_cap_enforced():
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, json={}))
    c, _, _ = make_client(calls_today=5)
    c.policy.daily_cap = 5
    with pytest.raises(DailyCapExceeded):
        await c.get_json("/x")


@respx.mock
async def test_invalid_json_is_a_failure():
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, text="<html>"))
    c, _, _ = make_client()
    with pytest.raises(ProviderError, match="invalid JSON"):
        await c.get_json("/x")


@respx.mock
async def test_post_and_secret_redaction():
    route = respx.post(f"{BASE}/rpc").mock(return_value=httpx.Response(200, json={"result": 1}))
    c, _calls, _ = make_client()
    assert await c.post_json("/rpc", {"id": 1}) == {"result": 1}
    assert route.calls[0].request.content == b'{"id":1}'
    secret = "123456:SECRET-TOKEN"
    pol = ProviderPolicy("telegram_bot", f"https://provider.test/bot{secret}", 6000, max_retries=0, redact=(secret,))
    respx.get(f"https://provider.test/bot{secret}/getUpdates").mock(side_effect=httpx.ConnectError(f"boom {secret}"))
    c2 = ProviderClient(pol, http=httpx.AsyncClient())
    with pytest.raises(ProviderError) as ei:
        await c2.get_json("/getUpdates")
    assert secret not in str(ei.value) and "***" in str(ei.value)
