"""assess_security job: GoPlus checks for tracked tokens, persisted as security_assessments.

Which tokens: liquid tracked tokens (best pool >= discovery.track_min_liquidity_usd)
or watchlisted ones, with no assessment yet or whose last one is past
`valid_until`. Never-assessed tokens go first, then deepest liquidity. At most
`security.policy.max_assessments_per_run` provider calls per run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cit import appsettings
from cit.chains import BY_ID, BY_SLUG
from cit.log import get_logger
from cit.providers.goplus import SOURCE as GP
from cit.providers.http import CircuitOpenError, DailyCapExceeded, ProviderError
from cit.security.engine import Assessment, evaluate
from cit.services import runs
from cit.services.runtime import ProviderRuntime

log = get_logger(__name__)

NOT_FOUND_RETRY = timedelta(hours=6)
MAX_RAW_LIST = 20

_CANDIDATES = text("""
with best as (
  select token_id, max(liquidity_usd) as liq from pool_latest group by token_id
), latest as (
  select distinct on (token_id) token_id, valid_until, raw ->> 'total_supply' as total_supply
  from security_assessments order by token_id, assessed_at desc
), watched as (
  select distinct token_id from watchlist_items where token_id is not null
)
select t.id, t.chain_id, t.address, b.liq, l.total_supply as prev_supply, (l.token_id is null) as never
from tokens t
left join best b on b.token_id = t.id
left join latest l on l.token_id = t.id
left join watched w on w.token_id = t.id
where not t.is_quote_asset and not t.is_excluded and t.chain_id = any(:chains)
  and (w.token_id is not null or b.liq >= :min_liq)
  and (l.token_id is null or l.valid_until < now())
order by (l.token_id is null) desc, b.liq desc nulls last
limit :n
""")

_INSERT = text("""
insert into security_assessments (token_id, source_id, assessed_at, valid_until, coverage, risk_level,
  hard_excluded, needs_review, checks, risk_flags, is_honeypot, buy_tax_pct, sell_tax_pct, top10_holder_pct,
  raw, ruleset_version)
select :token_id, s.id, :assessed_at, :valid_until, :coverage, :risk_level, :hard_excluded, :needs_review,
  cast(:checks as jsonb), :risk_flags, :is_honeypot, :buy_tax_pct, :sell_tax_pct, :top10_holder_pct,
  cast(:raw as jsonb), :ruleset_version
from data_sources s where s.slug = :source
returning id
""")


def trim_raw(data: dict[str, Any]) -> dict[str, Any]:
    """Keep the provider response for audit, but cap large lists (holders) to bound storage."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        out[k] = v[:MAX_RAW_LIST] if isinstance(v, list) else v
    return out


async def store_assessment(
    conn: AsyncConnection,
    token_id: int,
    a: Assessment,
    *,
    assessed_at: datetime,
    valid_until: datetime,
    raw: dict[str, Any],
    ruleset_version: str,
) -> int:
    return (
        await conn.execute(
            _INSERT,
            {
                "token_id": token_id,
                "assessed_at": assessed_at,
                "valid_until": valid_until,
                "coverage": a.coverage,
                "risk_level": a.risk_level,
                "hard_excluded": a.hard_excluded,
                "needs_review": a.needs_review,
                "checks": json.dumps(a.checks_json(), default=str),
                "risk_flags": a.risk_flags,
                "is_honeypot": a.is_honeypot,
                "buy_tax_pct": a.buy_tax_pct,
                "sell_tax_pct": a.sell_tax_pct,
                "top10_holder_pct": a.top10_holder_pct,
                "raw": json.dumps(trim_raw(raw), default=str),
                "ruleset_version": ruleset_version,
                "source": GP,
            },
        )
    ).scalar_one()


async def assess_security(rt: ProviderRuntime) -> dict[str, Any]:
    async with rt.engine.connect() as conn:
        pol = await appsettings.load(conn, "security.policy", appsettings.SecurityPolicy)
        disc = await appsettings.load(conn, "discovery", appsettings.DiscoverySettings)
        enabled = (await conn.execute(text("select enabled from data_sources where slug = :s"), {"s": GP})).scalar()
        if not enabled:
            return {"skipped": "goplus source disabled"}
        chain_ids = [BY_SLUG[c].id for c in disc.enabled_chains if c in BY_SLUG]
        rows = (
            await conn.execute(
                _CANDIDATES,
                {"chains": chain_ids, "min_liq": disc.track_min_liquidity_usd, "n": pol.max_assessments_per_run},
            )
        ).all()
    if not rows:
        return {"candidates": 0}

    gp = await rt.goplus()
    gp.client.job_name = "assess_security"
    async with rt.engine.begin() as conn:
        run_id = await runs.start_run(conn, GP, "assess_security")
    counters = runs.RunCounters()
    before = gp.client.calls_this_client
    stats = {"assessed": 0, "not_found": 0, "errors": 0, "hard_excluded": 0}
    last_error: str | None = None
    stopped_early: str | None = None

    for r in rows:
        chain_slug = BY_ID[r.chain_id].slug
        try:
            res = await gp.token_security(chain_slug, r.address)
        except (CircuitOpenError, DailyCapExceeded) as exc:
            stopped_early = str(exc)
            break
        except ProviderError as exc:
            stats["errors"] += 1
            last_error = str(exc)
            log.warning("security_assess_failed", token_id=r.id, error=last_error)
            continue
        async with rt.engine.begin() as conn:
            pools = {
                p
                for (p,) in (
                    await conn.execute(text("select address from pools where base_token_id = :t"), {"t": r.id})
                ).all()
            }
            a = evaluate(
                chain_slug, res.found, res.data, pol, pool_addresses=pools, previous_total_supply=r.prev_supply
            )
            ttl = timedelta(hours=pol.assessment_ttl_hours) if res.found else NOT_FOUND_RETRY
            await store_assessment(
                conn,
                r.id,
                a,
                assessed_at=res.observed_at,
                valid_until=res.observed_at + ttl,
                raw=res.data,
                ruleset_version=pol.ruleset_version,
            )
        stats["assessed"] += 1
        stats["not_found"] += int(not res.found)
        stats["hard_excluded"] += int(a.hard_excluded)

    counters.http_calls = gp.client.calls_this_client - before
    counters.items_fetched = len(rows)
    counters.items_new = stats["assessed"]
    counters.details = {**stats, "stopped_early": stopped_early}
    ok = stats["assessed"] > 0 or (stats["errors"] == 0 and stopped_early is None)
    status = "success" if ok and not stats["errors"] and not stopped_early else ("partial" if ok else "failed")
    async with rt.engine.begin() as conn:
        await runs.finish_run(conn, run_id, status, counters, last_error or stopped_early)
        await runs.record_source_result(conn, GP, ok=ok, error=last_error or stopped_early, breaker=gp.client.breaker)
    await rt.flush_usage()
    return {
        "candidates": len(rows),
        **stats,
        "stopped_early": stopped_early,
        "finished_at": datetime.now(UTC).isoformat(),
    }
