from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import respx

from cit.alerts import dispatch
from cit.alerts import engine as alerts
from cit.config import Settings
from cit.services.runtime import ProviderRuntime

TOKEN = "999:BOT"
TG = f"https://api.telegram.org/bot{TOKEN}"


def rt(engine, **kw) -> ProviderRuntime:
    base = {
        "telegram_bot_token": TOKEN,
        "telegram_alert_chat_id": "42",
        "global_rate_limit_per_minute": 100000,
        "public_url": "https://cit.example.com",
    }
    base.update(kw)
    return ProviderRuntime(Settings(**base), engine, http=httpx.AsyncClient())


async def test_emit_dedups_within_cooldown_and_routes_low_severity_to_digest(engine, clean_db):
    async with engine.begin() as conn:
        a = await alerts.emit(
            conn, category="new_token", severity="medium", dedup_key="k1", title="t", body="b", cooldown_minutes=60
        )
        b = await alerts.emit(
            conn, category="new_token", severity="medium", dedup_key="k1", title="t", body="b", cooldown_minutes=60
        )
        c = await alerts.emit(
            conn, category="spend_threshold", severity="low", dedup_key="k2", title="t", body="b", cooldown_minutes=60
        )
    assert a and b is None and c
    assert dict(clean_db.execute("select dedup_key, status from alerts").fetchall()) == {
        "k1": "pending",
        "k2": "deferred",
    }


def make_token(conn, liq=50000, score=70, risk="low", excluded=False, age_hours=1):
    tok = conn.execute(
        "insert into tokens (chain_id, address, symbol, first_observed_at) values (1, %s, '<b>X</b>', "
        "now() - make_interval(hours => %s)) returning id",
        (f"0x{abs(hash((liq, score, risk))) % 10**40:040d}", age_hours),
    ).fetchone()[0]
    pool = conn.execute(
        "insert into pools (chain_id, address, base_token_id) values (1, %s, %s) returning id", (f"0xpool{tok}", tok)
    ).fetchone()[0]
    conn.execute(
        "insert into pool_latest (pool_id, token_id, source_id, observed_at, liquidity_usd) "
        "values (%s, %s, 1, now(), %s)",
        (pool, tok, liq),
    )
    conn.execute(
        "insert into security_assessments (token_id, source_id, valid_until, coverage, risk_level, "
        "hard_excluded, ruleset_version) values (%s, 3, now() + interval '1 day', 'complete', %s, %s, 'v')",
        (tok, risk, excluded),
    )
    conn.execute(
        "insert into opportunity_scores (token_id, scorecard, scoring_version, data_cutoff_at, total, "
        "components, inputs_hash) values (%s, 'token', 'v', now(), %s, '{}', 'h')",
        (tok, score),
    )
    return tok, pool


async def test_generators(engine, clean_db):
    good, _ = make_token(clean_db)
    make_token(clean_db, score=20)  # below score threshold
    make_token(clean_db, risk="critical", excluded=True)  # excluded -> contract risk, not new_token
    _, pool = make_token(clean_db, liq=10000, score=60, risk="medium")
    drop_tok = clean_db.execute("select token_id from pool_latest where pool_id = %s", (pool,)).fetchone()[0]
    clean_db.execute(
        "insert into market_snapshots (pool_id, token_id, source_id, observed_at, liquidity_usd) "
        "values (%s, %s, 1, now() - interval '60 minutes', 40000)",
        (pool, drop_tok),
    )
    clean_db.execute(
        "insert into presales (project_name, slug, created_by, sale_end_at, status) values "
        "('P', 'p', 't', now() + interval '5 hours', 'live')"
    )
    clean_db.execute("update data_sources set last_failure_at = now(), last_error = 'boom' where slug = 'goplus'")
    res = await alerts.generate_alerts(engine)
    assert res["new_token"] == 1 and res["contract_risk"] == 1 and res["liquidity_change"] == 1
    assert res["presale"] == 1 and res["source_outage"] >= 1
    titles = [r[0] for r in clean_db.execute("select title from alerts order by id").fetchall()]
    assert any("Liquidity fell 75%" in t for t in titles)
    assert clean_db.execute("select token_id from alerts where category = 'new_token'").fetchone()[0] == good
    again = await alerts.generate_alerts(engine)
    assert sum(again.values()) == 0  # everything deduplicated


async def test_spend_thresholds(engine, clean_db):
    clean_db.execute(
        "insert into app_settings (key, value) values ('budget', %s)",
        (json.dumps({"monthly_budget_sgd": 10, "fixed_monthly_costs_sgd": 8.5, "sgd_per_usd": 1.3}),),
    )
    clean_db.execute(
        "insert into api_usage (source_id, endpoint, ok, cost_usd) select id, 'messages', true, 0.5 "
        "from data_sources where slug = 'anthropic'"
    )
    res = await alerts.generate_alerts(engine)
    assert res["spend_threshold"] == 2  # 9.15 of 10 SGD crosses 50% and 80%, not 100%
    sev = sorted(r[0] for r in clean_db.execute("select severity from alerts").fetchall())
    assert sev == ["low", "medium"]


def test_quiet_hours_wraps_midnight():
    sgt = lambda h, m: datetime(2026, 10, 13, h, m, tzinfo=UTC) - timedelta(hours=8)  # noqa: E731
    assert dispatch.in_quiet_hours(sgt(23, 30), "23:00", "07:30")
    assert dispatch.in_quiet_hours(sgt(3, 0), "23:00", "07:30")
    assert not dispatch.in_quiet_hours(sgt(7, 30), "23:00", "07:30")
    assert not dispatch.in_quiet_hours(sgt(12, 0), "23:00", "07:30")


@respx.mock
async def test_dispatch_sends_escapes_and_respects_cap(engine, clean_db, monkeypatch):
    monkeypatch.setattr(dispatch, "in_quiet_hours", lambda *a: False)
    clean_db.execute("update data_sources set rate_limit_per_minute = 100000")
    clean_db.execute("insert into app_settings (key, value) values ('alerts', '{\"max_alerts_per_hour\": 2}')")
    sent = respx.post(f"{TG}/sendMessage").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with engine.begin() as conn:
        for i, sev in enumerate(["medium", "high", "critical", "medium"]):
            await alerts.emit(
                conn,
                category="new_token",
                severity=sev,
                dedup_key=f"k{i}",
                title=f"<script>{sev}</script>",
                body="/tokens/bsc/0xabc",
                cooldown_minutes=60,
            )
    res = await dispatch.dispatch_alerts(rt(engine))
    # critical + high sent first; cap of 2 reached, then mediums deferred (critical is exempt from the cap).
    assert res == {"sent": 2, "deferred": 2, "failed": 0}
    body = json.loads(sent.calls[0].request.content)
    assert body["chat_id"] == "42" and body["parse_mode"] == "HTML"
    assert "&lt;script&gt;critical&lt;/script&gt;" in body["text"] and "<script>" not in body["text"]
    assert "https://cit.example.com/tokens/bsc/0xabc" in body["text"]


@respx.mock
async def test_quiet_hours_defer_and_failures_retry(engine, clean_db, monkeypatch):
    monkeypatch.setattr(dispatch, "in_quiet_hours", lambda *a: True)
    clean_db.execute("update data_sources set rate_limit_per_minute = 100000")
    respx.post(f"{TG}/sendMessage").mock(return_value=httpx.Response(400, json={"ok": False}))
    async with engine.begin() as conn:
        await alerts.emit(
            conn, category="presale", severity="medium", dedup_key="m", title="m", body="b", cooldown_minutes=60
        )
        await alerts.emit(
            conn, category="contract_risk", severity="high", dedup_key="h", title="h", body="b", cooldown_minutes=60
        )
    for _ in range(3):
        await dispatch.dispatch_alerts(rt(engine))
    st = dict(clean_db.execute("select dedup_key, status from alerts").fetchall())
    assert st == {"m": "deferred", "h": "failed"}  # high is allowed in quiet hours; failed after 3 attempts


async def test_dispatch_skipped_without_chat_id(engine, clean_db):
    assert "skipped" in await dispatch.dispatch_alerts(rt(engine, telegram_alert_chat_id=None))


@respx.mock
async def test_daily_digest(engine, clean_db):
    clean_db.execute("update data_sources set rate_limit_per_minute = 100000")
    sent = respx.post(f"{TG}/sendMessage").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with engine.begin() as conn:
        for i in range(3):
            await alerts.emit(
                conn,
                category="spend_threshold",
                severity="low",
                dedup_key=f"d{i}",
                title=f"note {i}",
                body="b",
                cooldown_minutes=60,
            )
    res = await dispatch.send_daily_digest(rt(engine))
    assert res["digested"] == 3
    text = json.loads(sent.calls[0].request.content)["text"]
    assert "Daily digest" in text and "note 2" in text and "CIT daily health" in text
    assert clean_db.execute("select count(*) from alerts where status = 'digested'").fetchone()[0] == 3
    # Health report heartbeat is stored even when delivery happens.
    assert clean_db.execute("select status from system_health where component = 'daily_health_report'").fetchone()


def test_chunking():
    parts = dispatch.chunk("\n".join("x" * 100 for _ in range(100)), limit=1000)
    assert all(len(p) <= 1000 for p in parts) and len(parts) > 1
