"""End-to-end discovery jobs: mocked HTTP (synthetic payloads) -> real Postgres."""

from __future__ import annotations

import json

import httpx
import respx

from cit.config import Settings
from cit.services import discovery, ops
from cit.services.runtime import ProviderRuntime

from .helpers import synthetic

GT = "https://api.geckoterminal.com/api/v2"
DS = "https://api.dexscreener.com"


def runtime(engine) -> ProviderRuntime:
    return ProviderRuntime(Settings(global_rate_limit_per_minute=100000), engine, http=httpx.AsyncClient())


def only_bsc(conn):
    conn.execute("""insert into app_settings (key, value) values ('discovery', %s)
                    on conflict (key) do update set value = excluded.value""",
                 (json.dumps({"enabled_chains": ["bsc"], "new_pools_max_pages": 2}),))
    # Make tests fast: lift the limiter (budgets come from data_sources).
    conn.execute("update data_sources set rate_limit_per_minute = 100000")


@respx.mock
async def test_discover_then_refresh_deduplicates_tokens(engine, clean_db):
    only_bsc(clean_db)
    respx.get(f"{GT}/networks/bsc/new_pools").mock(return_value=httpx.Response(200, json=synthetic(
        "gt_new_pools_bsc.json")))
    respx.get(url__startswith=f"{DS}/tokens/v1/bsc/").mock(return_value=httpx.Response(200, json=synthetic(
        "ds_tokens_v1_bsc.json")))
    rt = runtime(engine)

    summary = await discovery.discover_new_pools(rt)
    assert summary["bsc"]["new_pools"] == 2
    # Fewer than 20 pools on page 1 -> caught up, only one page read.
    assert respx.calls.call_count == 1

    tokens = clean_db.execute(
        "select address, symbol, is_quote_asset from tokens order by address").fetchall()
    assert ("0x2222222222222222222222222222222222222222", "FOO", False) in tokens
    assert ("0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c", "WBNB", True) in tokens

    # Second source refreshes the same token: no duplicate token, an extra pool.
    await discovery.refresh_tracked_markets(rt)
    foo = clean_db.execute(
        "select id, earliest_pool_created_at, jsonb_array_length(links) from tokens "
        "where chain_id = 1 and address = '0x2222222222222222222222222222222222222222'").fetchall()
    assert len(foo) == 1
    token_id, _, n_links = foo[0]
    assert n_links == 3
    pools = clean_db.execute("select address from pools where base_token_id = %s order by address",
                             (token_id,)).fetchall()
    assert [p[0] for p in pools] == ["0x1111111111111111111111111111111111111111",
                                    "0x6666666666666666666666666666666666666666"]
    snaps = clean_db.execute("select count(*) from market_snapshots where token_id = %s", (token_id,)).fetchone()
    assert snaps[0] == 3  # 1 from GeckoTerminal + 2 pools from DEX Screener
    latest = clean_db.execute(
        "select s.slug, pl.liquidity_usd from pool_latest pl join data_sources s on s.id = pl.source_id "
        "join pools p on p.id = pl.pool_id where p.address = '0x1111111111111111111111111111111111111111'"
    ).fetchone()
    assert latest[0] == "dexscreener" and float(latest[1]) == 26000.5

    # Bookkeeping: runs, freshness, usage.
    runs = clean_db.execute("select job_name, status, http_calls from ingestion_runs order by id").fetchall()
    assert runs == [("discover_new_pools", "success", 1), ("refresh_tracked_markets", "success", 1)]
    fresh = clean_db.execute(
        "select slug from data_sources where last_success_at is not null order by slug").fetchall()
    assert [f[0] for f in fresh] == ["dexscreener", "geckoterminal"]
    assert clean_db.execute("select count(*) from api_usage").fetchone()[0] == 2
    await rt.http.aclose()


@respx.mock
async def test_rediscovery_is_idempotent(engine, clean_db):
    only_bsc(clean_db)
    respx.get(f"{GT}/networks/bsc/new_pools").mock(return_value=httpx.Response(200, json=synthetic(
        "gt_new_pools_bsc.json")))
    rt = runtime(engine)
    await discovery.discover_new_pools(rt)
    first = clean_db.execute("select id, first_observed_at from tokens order by id").fetchall()
    second_summary = await discovery.discover_new_pools(rt)
    assert second_summary["bsc"]["new_pools"] == 0 and second_summary["bsc"]["new_tokens"] == 0
    assert clean_db.execute("select id, first_observed_at from tokens order by id").fetchall() == first
    await rt.http.aclose()


@respx.mock
async def test_provider_outage_is_recorded_not_raised(engine, clean_db):
    only_bsc(clean_db)
    respx.get(f"{GT}/networks/bsc/new_pools").mock(return_value=httpx.Response(500))
    rt = runtime(engine)
    rt_client = await rt.geckoterminal()
    rt_client.client.policy.max_retries = 0
    summary = await discovery.discover_new_pools(rt)
    assert "error" in summary["bsc"]
    run = clean_db.execute("select status, error from ingestion_runs").fetchone()
    assert run[0] == "failed" and "HTTP 500" in run[1]
    src = clean_db.execute(
        "select last_success_at, consecutive_failures, last_error from data_sources where slug='geckoterminal'"
    ).fetchone()
    assert src[0] is None and src[1] == 1 and "HTTP 500" in src[2]
    status = await ops.check_sources(engine)
    assert status["geckoterminal"] == "down"
    await rt.http.aclose()


@respx.mock
async def test_token_profiles_add_links_with_paid_provenance(engine, clean_db):
    respx.get(f"{DS}/token-profiles/latest/v1").mock(return_value=httpx.Response(200, json=synthetic(
        "ds_token_profiles.json")))
    clean_db.execute("update data_sources set rate_limit_per_minute = 100000")
    rt = runtime(engine)
    res = await discovery.ingest_token_profiles(rt)
    assert res == {"profiles": 1, "new_tokens": 1}
    links = clean_db.execute("select links from tokens where chain_id = 3").fetchone()[0]
    assert {li["source"] for li in links} == {"dexscreener:paid_profile"}
    await rt.http.aclose()
