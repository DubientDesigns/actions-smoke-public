"""Alert generation: deterministic signals -> deduplicated rows in `alerts`.

Every generator is idempotent: an alert's dedup_key is suppressed for its
cooldown, so re-running never spams. Delivery (Telegram, quiet hours, hourly
cap, digest) is handled separately in cit.alerts.dispatch; alerts are always
visible on the dashboard even when delivery is not configured.

Severity policy: info/low go to the daily digest only; medium and above are
sent immediately unless quiet hours apply.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cit import appsettings
from cit.services import ops

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
FOREVER_MIN = 60 * 24 * 365


async def emit(
    conn: AsyncConnection,
    *,
    category: str,
    severity: str,
    dedup_key: str,
    title: str,
    body: str,
    cooldown_minutes: int,
    token_id: int | None = None,
    presale_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> int | None:
    """Insert an alert unless the same dedup_key fired within the cooldown. Returns the new id or None."""
    recent = (
        await conn.execute(
            text("""
        select 1 from alerts where dedup_key = :k and created_at > now() - make_interval(mins => :m) limit 1
    """),
            {"k": dedup_key, "m": cooldown_minutes},
        )
    ).first()
    if recent is not None:
        return None
    status = "deferred" if SEVERITY_RANK[severity] < SEVERITY_RANK["medium"] else "pending"
    return (
        await conn.execute(
            text("""
        insert into alerts (category, severity, dedup_key, title, body, token_id, presale_id, payload, status,
                            status_reason)
        values (:c, :s, :k, :t, :b, :tok, :pre, cast(:p as jsonb), :st, :r) returning id
    """),
            {
                "c": category,
                "s": severity,
                "k": dedup_key,
                "t": title[:200],
                "b": body[:3000],
                "tok": token_id,
                "pre": presale_id,
                "p": json.dumps(payload or {}, default=str),
                "st": status,
                "r": "digest-only severity" if status == "deferred" else None,
            },
        )
    ).scalar_one()


def _usd(v: Any) -> str:
    return "unknown" if v is None else f"${float(v):,.0f}"


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


async def new_tokens(conn: AsyncConnection, a: appsettings.AlertSettings, d: appsettings.DiscoverySettings) -> int:
    rows = (
        await conn.execute(
            text("""
        select token_id, chain, address, symbol, score_total, liquidity_usd, risk_level, security_coverage
        from v_token_overview
        where first_observed_at > now() - interval '24 hours' and liquidity_usd >= :liq
          and score_total >= :score and coalesce(hard_excluded, false) = false and risk_level in ('low', 'medium')
    """),
            {"liq": d.alert_min_liquidity_usd, "score": a.new_token_min_score},
        )
    ).all()
    n = 0
    for r in rows:
        n += bool(
            await emit(
                conn,
                category="new_token",
                severity="medium",
                dedup_key=f"new_token:{r.token_id}",
                cooldown_minutes=FOREVER_MIN,
                token_id=r.token_id,
                title=f"New token meets research filters: {r.symbol or '?'} ({r.chain})",
                body=(
                    f"Score {float(r.score_total):.0f} (heuristic), liquidity {_usd(r.liquidity_usd)}, "
                    f"security {r.risk_level} ({r.security_coverage}).\n/tokens/{r.chain}/{r.address}\n"
                    "Research priority only - not a buy signal."
                ),
                payload={"chain": r.chain, "address": r.address},
            )
        )
    return n


async def multi_source_mentions(conn: AsyncConnection, a: appsettings.AlertSettings) -> int:
    rows = (
        await conn.execute(
            text("""
        with recent as (
          select d.token_id, d.cluster, m.content_hash from v_mention_detail d join social_mentions m on m.id = d.id
          where d.token_id is not null and not d.is_forwarded and d.published_at > now() - interval '24 hours'
        ), dup as (
          select content_hash from recent where content_hash is not null
          group by content_hash having count(distinct cluster) > 1
        )
        select r.token_id, t.symbol, c.slug as chain, t.address,
               count(distinct case when r.content_hash in (select content_hash from dup)
                                   then 'dup:' || r.content_hash else r.cluster end) as clusters
        from recent r join tokens t on t.id = r.token_id join chains c on c.id = t.chain_id
        group by r.token_id, t.symbol, c.slug, t.address
        having count(distinct case when r.content_hash in (select content_hash from dup)
                                   then 'dup:' || r.content_hash else r.cluster end) >= :n
    """),
            {"n": a.multi_mention_min_clusters},
        )
    ).all()
    today = datetime.now(UTC).date().isoformat()
    n = 0
    for r in rows:
        n += bool(
            await emit(
                conn,
                category="multi_source_mention",
                severity="medium",
                dedup_key=f"multi:{r.token_id}:{today}",
                cooldown_minutes=60 * 24,
                token_id=r.token_id,
                title=f"{r.clusters} independent sources mentioned {r.symbol or '?'} ({r.chain}) in 24h",
                body=(
                    f"Forwards excluded; identical text and known coordination groups count once.\n"
                    f"/tokens/{r.chain}/{r.address}\nCoordinated promotion is still possible - check "
                    "Influencer Intelligence."
                ),
            )
        )
    return n


_LIQ = text("""
with best as (
  select distinct on (pl.token_id) pl.token_id, pl.pool_id, pl.liquidity_usd, pl.observed_at
  from pool_latest pl order by pl.token_id, pl.liquidity_usd desc nulls last
), relevant as (
  select token_id from opportunity_scores where token_id is not null and scored_at > now() - interval '3 days'
  union select token_id from watchlist_items where token_id is not null
  union select token_id from social_mentions where token_id is not null and published_at > now() - interval '7 days'
)
select b.token_id, t.symbol, c.slug as chain, t.address, b.liquidity_usd as now_liq,
  (select s.liquidity_usd from market_snapshots s where s.pool_id = b.pool_id
     and s.observed_at between now() - interval '90 minutes' and now() - interval '45 minutes'
     order by s.observed_at limit 1) as prev_liq
from best b join relevant r on r.token_id = b.token_id
join tokens t on t.id = b.token_id join chains c on c.id = t.chain_id
where b.observed_at > now() - interval '30 minutes'
""")


async def liquidity_changes(conn: AsyncConnection, a: appsettings.AlertSettings) -> int:
    n = 0
    for r in (await conn.execute(_LIQ)).all():
        if r.prev_liq is None or r.now_liq is None or float(r.prev_liq) <= 0:
            continue
        change = (float(r.now_liq) / float(r.prev_liq) - 1) * 100
        if change <= -a.liquidity_drop_pct:
            n += bool(
                await emit(
                    conn,
                    category="liquidity_change",
                    severity="high",
                    dedup_key=f"liq_drop:{r.token_id}",
                    cooldown_minutes=360,
                    token_id=r.token_id,
                    title=f"Liquidity fell {abs(change):.0f}% in ~1h: {r.symbol or '?'} ({r.chain})",
                    body=(
                        f"{_usd(r.prev_liq)} -> {_usd(r.now_liq)}. Possible liquidity removal.\n"
                        f"/tokens/{r.chain}/{r.address}"
                    ),
                )
            )
        elif change >= a.liquidity_rise_pct:
            n += bool(
                await emit(
                    conn,
                    category="liquidity_change",
                    severity="medium",
                    dedup_key=f"liq_rise:{r.token_id}",
                    cooldown_minutes=360,
                    token_id=r.token_id,
                    title=f"Liquidity rose {change:.0f}% in ~1h: {r.symbol or '?'} ({r.chain})",
                    body=f"{_usd(r.prev_liq)} -> {_usd(r.now_liq)}.\n/tokens/{r.chain}/{r.address}",
                )
            )
    return n


async def wallet_activity(conn: AsyncConnection, a: appsettings.AlertSettings) -> int:
    rows = (
        await conn.execute(
            text("""
        select e.id, e.event_type, e.value_usd, e.token, e.chain, e.tx_hash, w.label, w.category
        from v_wallet_events e join tracked_wallets w on w.id = e.wallet_id
        join wallet_events we on we.id = e.id
        where we.collected_at > now() - interval '2 hours'
          and (coalesce(e.value_usd, 0) >= :min
               or (w.category in ('deployer', 'team') and e.event_type in ('sell', 'transfer_out', 'remove_liquidity')))
    """),
            {"min": a.wallet_min_value_usd},
        )
    ).all()
    n = 0
    for r in rows:
        insider_out = r.category in ("deployer", "team") and r.event_type in (
            "sell",
            "transfer_out",
            "remove_liquidity",
        )
        n += bool(
            await emit(
                conn,
                category="wallet_activity",
                severity="high" if insider_out else "medium",
                dedup_key=f"wallet:{r.id}",
                cooldown_minutes=FOREVER_MIN,
                title=f"{r.label} ({r.category}): {r.event_type.replace('_', ' ')} {r.token or 'native'} on {r.chain}",
                body=f"Value {_usd(r.value_usd)} (unknown if untracked token). tx {r.tx_hash}",
            )
        )
    return n


async def contract_risks(conn: AsyncConnection) -> int:
    rows = (
        await conn.execute(
            text("""
        with latest as (
          select a.*, lag(a.risk_level) over (partition by a.token_id order by a.assessed_at) as prev_level,
                 lag(a.hard_excluded) over (partition by a.token_id order by a.assessed_at) as prev_excluded
          from security_assessments a
        ), relevant as (
          select token_id from opportunity_scores where token_id is not null and scored_at > now() - interval '3 days'
          union select token_id from watchlist_items where token_id is not null
          union select token_id from social_mentions where token_id is not null
        )
        select l.id, l.token_id, l.risk_level, l.hard_excluded, l.risk_flags, t.symbol, c.slug as chain, t.address,
               (select 1 from watchlist_items w where w.token_id = l.token_id limit 1) is not null as watched
        from latest l join relevant r on r.token_id = l.token_id
        join tokens t on t.id = l.token_id join chains c on c.id = t.chain_id
        where l.assessed_at > now() - interval '2 hours'
          and (l.hard_excluded or l.risk_level in ('high', 'critical'))
          and not (coalesce(l.prev_excluded, false) or coalesce(l.prev_level, '') in ('high', 'critical'))
    """)
        )
    ).all()
    n = 0
    for r in rows:
        risks = [f.removeprefix("risk:") for f in (r.risk_flags or []) if f.startswith("risk:")][:6]
        n += bool(
            await emit(
                conn,
                category="contract_risk",
                severity="critical" if r.hard_excluded and r.watched else "high",
                dedup_key=f"risk:{r.id}",
                cooldown_minutes=FOREVER_MIN,
                token_id=r.token_id,
                title=f"New contract risk ({r.risk_level}): {r.symbol or '?'} ({r.chain})",
                body=(
                    f"Detected: {', '.join(risks) or 'see checks'}."
                    f"{' Hard exclusion rule triggered.' if r.hard_excluded else ''}\n/tokens/{r.chain}/{r.address}"
                ),
            )
        )
    return n


async def presale_deadlines(conn: AsyncConnection, a: appsettings.AlertSettings) -> int:
    rows = (
        await conn.execute(
            text("""
        select p.id, p.project_name, p.slug, f.field, f.at
        from presales p cross join lateral (values ('sale_start_at', p.sale_start_at), ('sale_end_at', p.sale_end_at),
                                                   ('tge_at', p.tge_at)) as f(field, at)
        where p.status not in ('cancelled', 'tge_done') and f.at > now()
          and f.at <= now() + make_interval(hours => :h)
    """),
            {"h": a.presale_lead_hours},
        )
    ).all()
    label = {"sale_start_at": "sale starts", "sale_end_at": "sale ends", "tge_at": "TGE"}
    n = 0
    for r in rows:
        hours = (r.at - datetime.now(UTC)).total_seconds() / 3600
        n += bool(
            await emit(
                conn,
                category="presale",
                severity="medium",
                dedup_key=f"presale:{r.id}:{r.field}:{r.at.isoformat()}",
                cooldown_minutes=FOREVER_MIN,
                presale_id=r.id,
                title=f"Presale {label[r.field]} in {hours:.0f}h: {r.project_name}",
                body=f"/presales/{r.slug}\nDates are claims from the presale record; verify on the official source.",
            )
        )
    return n


async def source_outages(conn: AsyncConnection) -> int:
    now = datetime.now(UTC)
    n = 0
    for r in (await conn.execute(text("select * from data_sources where enabled and kind <> 'manual'"))).all():
        status, msg = ops.source_status(r, now)
        if status == "down":
            n += bool(
                await emit(
                    conn,
                    category="source_outage",
                    severity="high",
                    dedup_key=f"outage:{r.slug}",
                    cooldown_minutes=360,
                    title=f"Data source down: {r.name}",
                    body=msg,
                )
            )
    return n


async def spend(conn: AsyncConnection) -> int:
    b = await appsettings.load(conn, "budget", appsettings.BudgetSettings)
    ai = await appsettings.load(conn, "ai.budget", appsettings.AiBudget)
    month_usd = float(
        (
            await conn.execute(
                text("select coalesce(sum(cost_usd), 0) from api_usage where occurred_at >= date_trunc('month', now())")
            )
        ).scalar_one()
    )
    ai_usd = float(
        (
            await conn.execute(
                text("""
        select coalesce(sum(u.cost_usd), 0) from api_usage u join data_sources s on s.id = u.source_id
        where s.slug = 'anthropic' and u.occurred_at >= date_trunc('month', now())
    """)
            )
        ).scalar_one()
    )
    total_sgd = b.fixed_monthly_costs_sgd + month_usd * b.sgd_per_usd
    month = datetime.now(UTC).strftime("%Y-%m")
    n = 0
    for pct in sorted(b.alert_thresholds_pct):
        if b.monthly_budget_sgd > 0 and total_sgd >= b.monthly_budget_sgd * pct / 100:
            sev = "high" if pct >= 100 else "medium" if pct >= 80 else "low"
            n += bool(
                await emit(
                    conn,
                    category="spend_threshold",
                    severity=sev,
                    dedup_key=f"spend:{month}:{pct}",
                    cooldown_minutes=60 * 24 * 40,
                    title=f"Monthly spend reached {pct}% of budget",
                    body=(
                        f"S${total_sgd:.2f} of S${b.monthly_budget_sgd:.2f} (fixed S${b.fixed_monthly_costs_sgd:.2f} + "
                        f"metered US${month_usd:.2f} at {b.sgd_per_usd} SGD/USD)."
                    ),
                )
            )
    if ai.monthly_usd_cap > 0 and ai_usd >= ai.monthly_usd_cap * 0.9:
        n += bool(
            await emit(
                conn,
                category="spend_threshold",
                severity="medium",
                dedup_key=f"ai_cap:{month}",
                cooldown_minutes=60 * 24 * 40,
                title="AI spend at 90% of its monthly cap",
                body=f"US${ai_usd:.2f} of US${ai.monthly_usd_cap:.2f}. New reports stop at the cap.",
            )
        )
    return n


async def generate_alerts(engine: Any) -> dict[str, int]:
    async with engine.begin() as conn:
        a = await appsettings.load(conn, "alerts", appsettings.AlertSettings)
        d = await appsettings.load(conn, "discovery", appsettings.DiscoverySettings)
        return {
            "new_token": await new_tokens(conn, a, d),
            "multi_source_mention": await multi_source_mentions(conn, a),
            "liquidity_change": await liquidity_changes(conn, a),
            "wallet_activity": await wallet_activity(conn, a),
            "contract_risk": await contract_risks(conn),
            "presale": await presale_deadlines(conn, a),
            "source_outage": await source_outages(conn),
            "spend_threshold": await spend(conn),
        }
