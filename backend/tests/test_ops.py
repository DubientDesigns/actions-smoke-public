from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import respx

from cit.services import ops

NOW = datetime(2026, 10, 13, tzinfo=UTC)


def src(**kw):
    base = dict(enabled=True, circuit_state="closed", circuit_open_until=None, last_success_at=None,
                last_failure_at=None, last_error=None, freshness_sla_seconds=1800, consecutive_failures=0)
    base.update(kw)
    return SimpleNamespace(**base)


def test_source_status_classification():
    assert ops.source_status(src(enabled=False), NOW)[0] == "unknown"
    assert ops.source_status(src(), NOW)[0] == "unknown"
    assert ops.source_status(src(last_failure_at=NOW, last_error="x"), NOW)[0] == "down"
    assert ops.source_status(src(last_success_at=NOW - timedelta(minutes=5)), NOW)[0] == "ok"
    assert ops.source_status(src(last_success_at=NOW - timedelta(minutes=45)), NOW)[0] == "degraded"
    assert ops.source_status(src(last_success_at=NOW - timedelta(hours=2)), NOW)[0] == "down"
    assert ops.source_status(src(last_success_at=NOW, consecutive_failures=2, last_error="e"), NOW)[0] == "degraded"
    assert ops.source_status(src(last_success_at=NOW, circuit_state="open",
                                 circuit_open_until=NOW + timedelta(minutes=1)), NOW)[0] == "down"


async def test_retention_downsamples_keeping_last_per_hour(engine, clean_db):
    tok = clean_db.execute("insert into tokens (chain_id, address) values (1, '0x01') returning id").fetchone()[0]
    pool = clean_db.execute("insert into pools (chain_id, address, base_token_id) values (1, '0xp', %s) returning id",
                            (tok,)).fetchone()[0]
    old = datetime.now(UTC) - timedelta(days=10)
    hour = old.replace(minute=0, second=0, microsecond=0)
    for minute, price in ((5, 1), (20, 2), (50, 3)):
        clean_db.execute("insert into market_snapshots (pool_id, token_id, source_id, observed_at, price_usd) "
                         "values (%s, %s, 1, %s, %s)", (pool, tok, hour + timedelta(minutes=minute), price))
    clean_db.execute("insert into market_snapshots (pool_id, token_id, source_id, observed_at, price_usd) "
                     "values (%s, %s, 1, now(), 9)", (pool, tok))
    res = await ops.apply_retention(engine)
    assert res["promoted_hourly"] == 1 and res["deleted_raw"] == 2
    rows = clean_db.execute("select resolution, price_usd from market_snapshots order by observed_at").fetchall()
    assert [(r[0], float(r[1])) for r in rows] == [("hourly", 3.0), ("raw", 9.0)]


async def test_health_report_builds(engine, clean_db):
    async with engine.connect() as conn:
        report = await ops.build_health_report(conn)
    assert {c["chain"] for c in report["chains"]} == {"bsc", "ethereum", "solana", "base"}
    text = ops.format_health_report_text(report)
    assert "CIT daily health" in text and "SGT" in text


async def test_health_report_is_not_ok_before_any_success(engine, clean_db):
    async with engine.connect() as conn:
        report = await ops.build_health_report(conn)
    assert report["overall"] == "degraded"
    clean_db.execute("update data_sources set last_success_at = now() where enabled")
    async with engine.connect() as conn:
        assert (await ops.build_health_report(conn))["overall"] == "ok"
    clean_db.execute("update data_sources set last_success_at = null, last_failure_at = now(), last_error = 'x' "
                     "where slug = 'geckoterminal'")
    async with engine.connect() as conn:
        assert (await ops.build_health_report(conn))["overall"] == "down"


async def test_prune_removes_only_unreferenced_illiquid_old_tokens(engine, clean_db):
    def token(addr, days_old):
        return clean_db.execute(
            "insert into tokens (chain_id, address, first_observed_at) "
            "values (1, %s, now() - make_interval(days => %s))"
            " returning id", (addr, days_old)).fetchone()[0]

    junk, liquid, fresh, evaluated = token("0xa1", 20), token("0xa2", 20), token("0xa3", 1), token("0xa4", 20)
    pool = clean_db.execute("insert into pools (chain_id, address, base_token_id) values (1, '0xp2', %s) returning id",
                            (liquid,)).fetchone()[0]
    clean_db.execute("insert into pool_latest (pool_id, token_id, source_id, observed_at, liquidity_usd) "
                     "values (%s, %s, 1, now(), 50000)", (pool, liquid))
    strat = clean_db.execute("insert into strategy_definitions (slug, version, name, rules) "
                             "values ('s', 1, 's', '{}') returning id").fetchone()[0]
    clean_db.execute("insert into strategy_evaluations (strategy_id, token_id, data_cutoff_at, decision, inputs, "
                     "inputs_hash) values (%s, %s, now(), 'reject', '{}', 'h')", (strat, evaluated))
    res = await ops.apply_retention(engine)
    assert res["pruned_tokens"] == 1
    left = {r[0] for r in clean_db.execute("select id from tokens").fetchall()}
    assert left == {liquid, fresh, evaluated} and junk not in left


async def test_restart_recovery_closes_abandoned_runs_and_reports(engine, clean_db):
    from cit.services import ops

    tid = clean_db.execute("insert into tokens (chain_id, address) values (1, '0x" + "e" * 40 + "') "
                           "returning id").fetchone()[0]
    clean_db.execute("insert into ingestion_runs (source_id, job_name, status, started_at) "
                     "values (1, 'discover_new_pools', 'running', now() - interval '2 hours')")
    clean_db.execute("insert into ingestion_runs (source_id, job_name, status, started_at) "
                     "values (1, 'discover_new_pools', 'running', now())")
    clean_db.execute("insert into research_reports (token_id, status, prompt_version, input_hash, evidence, "
                     "created_at) "
                     "values (%s, 'generating', 'v', 'h1', '{}', now() - interval '2 hours'), "
                     "(%s, 'generating', 'v', 'h2', '{}', now())", (tid, tid))
    await ops.check_sources(engine)
    runs_ = clean_db.execute("select status from ingestion_runs order by id").fetchall()
    assert [r[0] for r in runs_] == ["failed", "running"]  # only the stale one is closed
    reports = clean_db.execute("select status, error from research_reports order by id").fetchall()
    assert reports[0][0] == "failed" and reports[0][1].startswith("abandoned") and reports[1][0] == "generating"


@respx.mock
async def test_dead_mans_switch_ping(engine, clean_db):
    import httpx
    from pydantic import SecretStr

    from cit.config import Settings
    from cit.services.runtime import ProviderRuntime
    from cit.worker import scheduler

    rt = ProviderRuntime(Settings(), engine, http=httpx.AsyncClient())
    assert await scheduler.ping_dead_mans_switch(rt) is False  # not configured: no request
    route = respx.get("https://hc-ping.example/abc").mock(return_value=httpx.Response(200))
    rt = ProviderRuntime(Settings(healthcheck_ping_url=SecretStr("https://hc-ping.example/abc")), engine,
                         http=httpx.AsyncClient())
    await scheduler._heartbeat(rt)
    assert route.called
    assert clean_db.execute("select status from system_health where component = 'worker'").fetchone()[0] == "ok"
    respx.get("https://hc-ping.example/abc").mock(side_effect=httpx.ConnectError("down"))
    assert await scheduler.ping_dead_mans_switch(rt) is False  # failure is swallowed
