from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

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
