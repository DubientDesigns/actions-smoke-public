"""score_tokens job: compute the token scorecard for liquid tracked tokens.

A new opportunity_scores row is written only on material change (total moves
by >= MIN_DELTA points, risk flags change, the security assessment changes) or
when the latest stored score is older than HEARTBEAT, which keeps the table
small on the free database tier while preserving every meaningful change.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from cit import appsettings
from cit.chains import BY_SLUG
from cit.log import get_logger
from cit.scoring.token_v1 import ScoreResult, SecurityInput, TokenInputs, score
from cit.services import runs
from cit.services.runtime import ProviderRuntime

log = get_logger(__name__)

MIN_DELTA = 2.0
HEARTBEAT = timedelta(hours=6)

_INPUTS = text("""
with watched as (select distinct token_id from watchlist_items where token_id is not null)
select o.token_id, o.chain, o.liquidity_usd, o.volume_h24_usd, o.buys_h24, o.sells_h24, o.price_change_h24,
       o.fdv_usd, o.market_observed_at, o.pool_count, o.links, p.pool_created_at
from v_token_overview o
left join pools p on p.id = o.best_pool_id
left join watched w on w.token_id = o.token_id
where not o.is_excluded and o.chain = any(:chains)
  and (w.token_id is not null or o.liquidity_usd >= :min_liq)
order by (w.token_id is not null) desc, o.liquidity_usd desc nulls last
limit :n
""")

_SOURCES = text("""
select ms.token_id, array_agg(distinct s.slug order by s.slug) as sources
from market_snapshots ms join data_sources s on s.id = ms.source_id
where ms.token_id = any(:ids) and ms.observed_at > now() - interval '24 hours'
group by ms.token_id
""")

_SECURITY = text("""
select distinct on (token_id) id, token_id, assessed_at, valid_until, coverage, risk_level, hard_excluded, checks
from security_assessments where token_id = any(:ids)
order by token_id, assessed_at desc
""")

_LATEST_SCORE = text("""
select distinct on (token_id) token_id, total, risk_flags, scored_at, components
from opportunity_scores where token_id = any(:ids) and scorecard = 'token'
order by token_id, scored_at desc
""")

_INSERT = text("""
insert into opportunity_scores (token_id, scorecard, scoring_version, scored_at, data_cutoff_at, total,
  components, missing_data, risk_flags, inputs_hash)
values (:token_id, 'token', :version, :scored_at, :cutoff, :total, cast(:components as jsonb), :missing,
  :flags, :hash)
""")


def _dec(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def build_inputs(row: Any, sources: list[str], sec_row: Any, now: datetime) -> TokenInputs:
    sec = None
    if sec_row is not None:
        sec = SecurityInput(
            assessed_at=sec_row.assessed_at,
            valid_until=sec_row.valid_until,
            coverage=sec_row.coverage,
            risk_level=sec_row.risk_level,
            hard_excluded=sec_row.hard_excluded,
            checks={c["key"]: c["status"] for c in (sec_row.checks or []) if isinstance(c, dict) and "key" in c},
        )
    return TokenInputs(
        token_id=row.token_id,
        chain=row.chain,
        as_of=now,
        pool_created_at=row.pool_created_at,
        market_observed_at=row.market_observed_at,
        liquidity_usd=_dec(row.liquidity_usd),
        volume_h24_usd=_dec(row.volume_h24_usd),
        buys_h24=row.buys_h24,
        sells_h24=row.sells_h24,
        price_change_h24=_dec(row.price_change_h24),
        fdv_usd=_dec(row.fdv_usd),
        pool_count=row.pool_count,
        sources_24h=tuple(sources),
        link_types=tuple(
            sorted(
                {
                    li.get("type")
                    for li in (row.links or [])
                    if isinstance(li, dict) and not str(li.get("source", "")).endswith("paid_profile")
                }
                - {None}
            )
        ),
        security=sec,
    )


def is_material(new: ScoreResult, prev: Any, sec_assessed_at: datetime | None, now: datetime) -> bool:
    if prev is None:
        return True
    if abs(float(prev.total) - new.total) >= MIN_DELTA:
        return True
    if sorted(prev.risk_flags or []) != new.risk_flags:
        return True
    if now - prev.scored_at >= HEARTBEAT:
        return True
    return sec_assessed_at is not None and sec_assessed_at > prev.scored_at


async def score_tokens(rt: ProviderRuntime) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with rt.engine.connect() as conn:
        disc = await appsettings.load(conn, "discovery", appsettings.DiscoverySettings)
        weights = await appsettings.load(conn, "scoring.token_weights", appsettings.ScoringWeights)
        rows = (
            await conn.execute(
                _INPUTS,
                {
                    "chains": [c for c in disc.enabled_chains if c in BY_SLUG],
                    "min_liq": disc.track_min_liquidity_usd,
                    "n": disc.max_tracked_tokens,
                },
            )
        ).all()
        ids = [r.token_id for r in rows]
        if not ids:
            return {"scored": 0, "stored": 0}
        sources = {r.token_id: list(r.sources) for r in (await conn.execute(_SOURCES, {"ids": ids})).all()}
        secs = {r.token_id: r for r in (await conn.execute(_SECURITY, {"ids": ids})).all()}
        prevs = {r.token_id: r for r in (await conn.execute(_LATEST_SCORE, {"ids": ids})).all()}

    stored = 0
    async with rt.engine.begin() as conn:
        for r in rows:
            sec_row = secs.get(r.token_id)
            inp = build_inputs(r, sources.get(r.token_id, []), sec_row, now)
            res = score(inp, weights)
            if not is_material(res, prevs.get(r.token_id), sec_row.assessed_at if sec_row else None, now):
                continue
            await conn.execute(
                _INSERT,
                {
                    "token_id": r.token_id,
                    "version": res.scoring_version,
                    "scored_at": now,
                    "cutoff": res.data_cutoff_at,
                    "total": res.total,
                    "components": json.dumps(res.components),
                    "missing": res.missing_data,
                    "flags": res.risk_flags,
                    "hash": res.inputs_hash,
                },
            )
            stored += 1
        await runs.heartbeat(
            conn, "scoring", "ok", f"scored {len(rows)}, stored {stored}", {"version": weights.version}
        )
    return {"scored": len(rows), "stored": stored, "version": weights.version}
