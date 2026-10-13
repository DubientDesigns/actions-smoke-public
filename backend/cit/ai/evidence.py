"""Deterministic evidence bundles for AI research reports.

Everything the model sees comes from this bundle, and every item carries an
id, its source and when it was observed, so each claim in a report can be
traced. Third-party text (social excerpts, project-supplied links) is placed in
`untrusted_text` / marked `self_reported` and the system prompt tells the model
to treat it strictly as data.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _num(v: Any) -> float | None:
    if v is None:
        return None
    f = float(v) if isinstance(v, (Decimal, int, float)) else None
    if f is None or not math.isfinite(f):
        return None
    return float(f"{f:.6g}")


def _ts(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def _clean(s: str | None, limit: int = 400) -> str | None:
    if not s:
        return None
    s = CONTROL_RE.sub(" ", s)
    return s[:limit]


class Bundle:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, kind: str, source: str | None, observed_at: datetime | None, **data: Any) -> str:
        eid = f"E{len(self.items) + 1}"
        self.items.append({"id": eid, "kind": kind, "source": source, "observed_at": _ts(observed_at), **data})
        return eid


async def build_token_bundle(conn: AsyncConnection, token_id: int) -> tuple[dict[str, Any], str] | None:
    """Return (bundle, material_hash) for a token, or None if the token does not exist."""
    t = (await conn.execute(text("select * from v_token_overview where token_id = :t"), {"t": token_id})).first()
    if t is None:
        return None
    b = Bundle()
    b.add(
        "identity",
        "cit",
        t.first_observed_at,
        chain=t.chain,
        address=t.address,
        symbol=t.symbol,
        name=t.name,
        first_seen_by=t.first_source,
        earliest_pool_created_at=_ts(t.earliest_pool_created_at),
    )
    b.add(
        "market_best_pool",
        t.market_source,
        t.market_observed_at,
        dex=t.best_pool_dex,
        quote=t.quote_symbol,
        price_usd=_num(t.price_usd),
        liquidity_usd=_num(t.liquidity_usd),
        volume_h1_usd=_num(t.volume_h1_usd),
        volume_h24_usd=_num(t.volume_h24_usd),
        buys_h24=t.buys_h24,
        sells_h24=t.sells_h24,
        price_change_h24_pct=_num(t.price_change_h24),
        fdv_usd=_num(t.fdv_usd),
        market_cap_usd=_num(t.market_cap_usd),
        note="market_cap_usd is null when unknown; it is never inferred from FDV",
    )

    pools = (
        await conn.execute(
            text("""
        select address, dex, quote_symbol, liquidity_usd, volume_h24_usd, observed_at, market_source, pool_created_at
        from v_pool_detail where token_id = :t order by liquidity_usd desc nulls last limit 5
    """),
            {"t": token_id},
        )
    ).all()
    for p in pools:
        b.add(
            "pool",
            p.market_source,
            p.observed_at,
            address=p.address,
            dex=p.dex,
            quote=p.quote_symbol,
            liquidity_usd=_num(p.liquidity_usd),
            volume_h24_usd=_num(p.volume_h24_usd),
            pool_created_at=_ts(p.pool_created_at),
        )

    trend = (
        (
            await conn.execute(
                text("""
        select min(observed_at) as since, max(observed_at) as until, count(*) as n,
          (array_agg(price_usd order by observed_at))[1] as first_price,
          (array_agg(price_usd order by observed_at desc))[1] as last_price,
          max(price_usd) as max_price, min(price_usd) as min_price,
          (array_agg(liquidity_usd order by observed_at))[1] as first_liquidity,
          (array_agg(liquidity_usd order by observed_at desc))[1] as last_liquidity
        from market_snapshots where pool_id = :p and observed_at > now() - interval '24 hours'
    """),
                {"p": t.best_pool_id},
            )
        ).first()
        if t.best_pool_id
        else None
    )
    if trend is not None and trend.n:
        b.add(
            "price_trend_24h",
            "cit:snapshots",
            trend.until,
            observations=trend.n,
            since=_ts(trend.since),
            first_price_usd=_num(trend.first_price),
            last_price_usd=_num(trend.last_price),
            max_price_usd=_num(trend.max_price),
            min_price_usd=_num(trend.min_price),
            first_liquidity_usd=_num(trend.first_liquidity),
            last_liquidity_usd=_num(trend.last_liquidity),
        )

    sec = (await conn.execute(text("select * from v_security_latest where token_id = :t"), {"t": token_id})).first()
    if sec is not None:
        b.add(
            "security_summary",
            sec.source,
            sec.assessed_at,
            risk_level=sec.risk_level,
            coverage=sec.coverage,
            hard_excluded=sec.hard_excluded,
            stale=sec.is_stale,
            ruleset=sec.ruleset_version,
            note="third-party heuristics, not an audit; 'unknown' and 'unsupported' are not passes",
        )
        for c in sec.checks or []:
            if c.get("status") == "unsupported":
                continue
            value = c.get("value")
            b.add(
                "security_check",
                sec.source,
                sec.assessed_at,
                check=c.get("key"),
                label=c.get("label"),
                status=c.get("status"),
                value=_num(Decimal(value))
                if isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value)
                else value
                if isinstance(value, (int, float))
                else None,
                detail=c.get("detail"),
            )
    sc = (await conn.execute(text("select * from v_score_latest where token_id = :t"), {"t": token_id})).first()
    if sc is not None:
        b.add(
            "score",
            "cit:scoring",
            sc.scored_at,
            version=sc.scoring_version,
            total=_num(sc.total),
            components={k: {"score": v.get("score"), "max": v.get("max")} for k, v in (sc.components or {}).items()},
            risk_flags=list(sc.risk_flags or []),
            missing=list(sc.missing_data or [])[:15],
            note="heuristic research-priority score, not a return prediction",
        )

    mentions = (
        await conn.execute(
            text("""
        select published_at, platform, channel_title, influencer_name, category, promo_disclosure, is_forwarded,
               referral_links, text_excerpt, cluster, outcome_status
        from v_mention_detail where token_id = :t and published_at > now() - interval '30 days'
        order by published_at desc limit 10
    """),
            {"t": token_id},
        )
    ).all()
    for m in mentions:
        b.add(
            "social_mention",
            f"{m.platform}:{m.channel_title or 'unknown'}",
            m.published_at,
            influencer=m.influencer_name,
            cluster=m.cluster,
            category=m.category,
            promo_disclosure=m.promo_disclosure,
            forwarded=m.is_forwarded,
            has_referral_link=bool(m.referral_links),
            untrusted_text=_clean(m.text_excerpt, 280),
        )
    for li in (t.links or [])[:10]:
        b.add(
            "project_link",
            li.get("source"),
            datetime.fromisoformat(li["observed_at"]) if li.get("observed_at") else None,
            link_type=li.get("type"),
            url=_clean(li.get("url"), 300),
            self_reported=True,
            paid_listing=str(li.get("source", "")).endswith("paid_profile"),
        )

    bundle = {"token": {"chain": t.chain, "address": t.address, "symbol": t.symbol}, "evidence": b.items}
    liq = _num(t.liquidity_usd)
    material = {
        "score": sc.score_id if sc is not None else None,
        "security": sec.assessment_id if sec is not None else None,
        "mentions": len(mentions),
        "links": len(t.links or []),
        "liquidity_bucket": round(math.log2(liq)) if liq and liq > 0 else None,
    }
    return bundle, hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
