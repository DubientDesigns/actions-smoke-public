"""Discovery and market-refresh jobs (Phase 2).

discover_new_pools      GeckoTerminal new_pools per chain (primary discovery feed)
ingest_token_profiles   DEX Screener latest token profiles (paid listings -> links + candidates)
refresh_tracked_markets DEX Screener batched market refresh for tracked tokens

Coverage is incomplete by design: GeckoTerminal's new_pools returns the most
recent 20 pools per page, so on busy chains (Solana, BSC) bursts of pool
creation between scans can be missed. Each run records how many pages it read
and whether it "caught up" (saw an already-known pool) so the gap is visible.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from cit import appsettings
from cit.chains import BY_ID, BY_SLUG
from cit.log import get_logger
from cit.providers.dexscreener import SOURCE as DS
from cit.providers.geckoterminal import SOURCE as GT
from cit.providers.http import ProviderError
from cit.providers.models import TokenRef
from cit.services import market_store, runs
from cit.services.runtime import ProviderRuntime

log = get_logger(__name__)

GT_PAGE_SIZE = 20


async def _known_pool_count(rt: ProviderRuntime, chain_slug: str, addresses: list[str]) -> int:
    if not addresses:
        return 0
    async with rt.engine.connect() as conn:
        return (
            await conn.execute(
                text("select count(*) from pools where chain_id = :c and address = any(:a)"),
                {"c": BY_SLUG[chain_slug].id, "a": addresses},
            )
        ).scalar_one()


async def discover_new_pools(rt: ProviderRuntime) -> dict[str, Any]:
    async with rt.engine.connect() as conn:
        cfg = await appsettings.load(conn, "discovery", appsettings.DiscoverySettings)
        sources = await market_store.source_ids(conn)
    gt = await rt.geckoterminal()
    gt.client.job_name = "discover_new_pools"
    summary: dict[str, Any] = {}
    any_ok, last_error = False, None

    for chain_slug in cfg.enabled_chains:
        if chain_slug not in BY_SLUG:
            continue
        async with rt.engine.begin() as conn:
            run_id = await runs.start_run(conn, GT, "discover_new_pools", chain_slug)
        counters = runs.RunCounters()
        calls_before = gt.client.calls_this_client
        try:
            observations = []
            caught_up = False
            for page in range(1, cfg.new_pools_max_pages + 1):
                page_obs = await gt.new_pools(chain_slug, page)
                observations.extend(page_obs)
                known = await _known_pool_count(rt, chain_slug, [o.pool_address for o in page_obs])
                if known > 0 or len(page_obs) < GT_PAGE_SIZE:
                    caught_up = True
                    break
            counters.details.update(pages=page, caught_up=caught_up)
            async with rt.engine.begin() as conn:
                stats = await market_store.store_observations(conn, observations, source_id=sources[GT], run_id=run_id)
                counters.items_fetched = len(observations)
                counters.items_new = stats.pools_new
                counters.items_updated = stats.pools_seen - stats.pools_new
                counters.details.update(tokens_new=stats.tokens_new, new_token_ids=stats.new_token_ids[:100])
                counters.http_calls = gt.client.calls_this_client - calls_before
                await runs.finish_run(
                    conn,
                    run_id,
                    "success" if caught_up else "partial",
                    counters,
                    None if caught_up else "page limit reached before catching up; some new pools may have been missed",
                )
            any_ok = True
            summary[chain_slug] = {
                "pools": len(observations),
                "new_pools": stats.pools_new,
                "new_tokens": stats.tokens_new,
                "caught_up": caught_up,
            }
        except (ProviderError, ValueError) as exc:
            last_error = str(exc)
            counters.http_calls = gt.client.calls_this_client - calls_before
            async with rt.engine.begin() as conn:
                await runs.finish_run(conn, run_id, "failed", counters, last_error)
            log.warning("discovery_chain_failed", chain=chain_slug, error=last_error)
            summary[chain_slug] = {"error": last_error}

    async with rt.engine.begin() as conn:
        await runs.record_source_result(conn, GT, ok=any_ok, error=last_error, breaker=gt.client.breaker)
    await rt.flush_usage()
    return summary


async def ingest_token_profiles(rt: ProviderRuntime) -> dict[str, Any]:
    ds = await rt.dexscreener()
    ds.client.job_name = "ingest_token_profiles"
    async with rt.engine.begin() as conn:
        run_id = await runs.start_run(conn, DS, "ingest_token_profiles")
        sources = await market_store.source_ids(conn)
    counters = runs.RunCounters()
    try:
        profiles = await ds.latest_token_profiles()
        counters.http_calls = 1
        counters.items_fetched = len(profiles)
        async with rt.engine.begin() as conn:
            for p in profiles:
                token_id, is_new = await market_store.upsert_token(
                    conn, p.chain_slug, TokenRef(p.token_address), sources[DS], p.observed_at, None
                )
                counters.items_new += int(is_new)
                await market_store.merge_links(conn, token_id, p.links, "dexscreener:paid_profile", p.observed_at)
            await runs.finish_run(conn, run_id, "success", counters)
            await runs.record_source_result(conn, DS, ok=True, error=None, breaker=ds.client.breaker)
    except (ProviderError, ValueError) as exc:
        async with rt.engine.begin() as conn:
            await runs.finish_run(conn, run_id, "failed", counters, str(exc))
            await runs.record_source_result(conn, DS, ok=False, error=str(exc), breaker=ds.client.breaker)
    await rt.flush_usage()
    return {"profiles": counters.items_fetched, "new_tokens": counters.items_new}


_TRACKED_SQL = text("""
with best as (
  select token_id, max(liquidity_usd) as liq, max(observed_at) as last_seen
  from pool_latest group by token_id
), watched as (
  select distinct token_id from watchlist_items where token_id is not null
)
select t.id, t.chain_id, t.address, (w.token_id is not null) as watched, b.liq
from tokens t
left join best b on b.token_id = t.id
left join watched w on w.token_id = t.id
where not t.is_quote_asset and not t.is_excluded and t.chain_id = any(:chains)
  and (
    w.token_id is not null
    or (t.first_observed_at >= now() - make_interval(days => :track_days)
        and (b.liq is null or b.liq >= :min_liq))
  )
order by watched desc, b.liq desc nulls first, t.first_observed_at desc
limit :max_tokens
""")


async def tracked_tokens(conn: Any, cfg: appsettings.DiscoverySettings) -> list[Any]:
    chain_ids = [BY_SLUG[c].id for c in cfg.enabled_chains if c in BY_SLUG]
    return list(
        (
            await conn.execute(
                _TRACKED_SQL,
                {
                    "chains": chain_ids,
                    "track_days": cfg.track_days,
                    "min_liq": cfg.track_min_liquidity_usd,
                    "max_tokens": cfg.max_tracked_tokens,
                },
            )
        ).all()
    )


async def refresh_tracked_markets(rt: ProviderRuntime) -> dict[str, Any]:
    async with rt.engine.connect() as conn:
        cfg = await appsettings.load(conn, "discovery", appsettings.DiscoverySettings)
        sources = await market_store.source_ids(conn)
        rows = await tracked_tokens(conn, cfg)
    by_chain: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by_chain[BY_ID[r.chain_id].slug].append(r.address)

    ds = await rt.dexscreener()
    ds.client.job_name = "refresh_tracked_markets"
    summary: dict[str, Any] = {"tracked": len(rows)}
    any_ok, last_error = False, None
    for chain_slug, addresses in by_chain.items():
        async with rt.engine.begin() as conn:
            run_id = await runs.start_run(conn, DS, "refresh_tracked_markets", chain_slug)
        counters = runs.RunCounters()
        before = ds.client.calls_this_client
        try:
            observations = await ds.pairs_for_tokens(chain_slug, addresses)
            async with rt.engine.begin() as conn:
                stats = await market_store.store_observations(conn, observations, source_id=sources[DS], run_id=run_id)
                returned = {o.base.address for o in observations} | {o.quote.address for o in observations if o.quote}
                missing = [a for a in addresses if a not in returned]
                counters.http_calls = ds.client.calls_this_client - before
                counters.items_fetched = len(observations)
                counters.items_new = stats.pools_new
                counters.items_updated = stats.snapshots
                counters.details.update(
                    requested=len(addresses), no_pairs_returned=len(missing), missing_sample=missing[:20]
                )
                await runs.finish_run(conn, run_id, "success", counters)
            any_ok = True
            summary[chain_slug] = {"requested": len(addresses), "pairs": len(observations), "no_pairs": len(missing)}
        except (ProviderError, ValueError) as exc:
            last_error = str(exc)
            counters.http_calls = ds.client.calls_this_client - before
            async with rt.engine.begin() as conn:
                await runs.finish_run(conn, run_id, "failed", counters, last_error)
            summary[chain_slug] = {"error": last_error}
    if by_chain:
        async with rt.engine.begin() as conn:
            await runs.record_source_result(conn, DS, ok=any_ok, error=last_error, breaker=ds.client.breaker)
    await rt.flush_usage()
    summary["finished_at"] = datetime.now(UTC).isoformat()
    return summary
