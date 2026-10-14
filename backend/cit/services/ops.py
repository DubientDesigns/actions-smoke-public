"""Operational jobs: source freshness, retention, and the daily health report."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from cit import appsettings
from cit.config import DISPLAY_TZ
from cit.services import runs


def source_status(row: Any, now: datetime) -> tuple[str, str]:
    """Classify a data_sources row -> (status, human message)."""
    if not row.enabled:
        return "unknown", "disabled"
    if row.circuit_state == "open" and row.circuit_open_until and row.circuit_open_until > now:
        return "down", f"circuit open until {row.circuit_open_until.isoformat()}"
    if row.last_success_at is None:
        return ("down", f"never succeeded: {row.last_error}") if row.last_failure_at else ("unknown", "no runs yet")
    age = (now - row.last_success_at).total_seconds()
    if age > row.freshness_sla_seconds * 3:
        return "down", f"stale: last success {int(age // 60)} min ago"
    if age > row.freshness_sla_seconds:
        return "degraded", f"stale: last success {int(age // 60)} min ago"
    if row.consecutive_failures > 0:
        return "degraded", f"{row.consecutive_failures} consecutive failures; last error: {row.last_error}"
    return "ok", f"last success {int(age // 60)} min ago"


async def check_sources(engine: AsyncEngine) -> dict[str, str]:
    now = datetime.now(UTC)
    out: dict[str, str] = {}
    async with engine.begin() as conn:
        rows = (await conn.execute(text("select * from data_sources where kind <> 'manual'"))).all()
        for r in rows:
            status, msg = source_status(r, now)
            out[r.slug] = status
            await runs.heartbeat(conn, f"source:{r.slug}", status, msg)
        # Runs left in 'running' by a crashed worker are closed out so they do not
        # look like they are still in progress.
        await conn.execute(
            text("""
            update ingestion_runs set status = 'failed', finished_at = now(),
              error = coalesce(error, 'abandoned: worker stopped before the run finished')
            where status = 'running' and started_at < now() - interval '30 minutes'
        """)
        )
        # Same for AI reports interrupted mid-call (they would otherwise show 'generating' forever).
        await conn.execute(
            text("""
            update research_reports set status = 'failed', completed_at = now(),
              error = coalesce(error, 'abandoned: worker stopped before the report finished')
            where status = 'generating' and created_at < now() - interval '30 minutes'
        """)
        )
    return out


# Deletes low-signal tokens to stay inside the free database tier. Anything
# referenced by research, scoring, strategy evaluation, paper trading, social
# mentions, watchlists or presales is never pruned, so rejected and failed
# opportunities stay on record (no survivorship bias).
_PRUNE_TOKENS = text("""
delete from tokens t
where not t.is_quote_asset
  and t.first_observed_at < now() - make_interval(days => :days)
  and coalesce((select max(liquidity_usd) from pool_latest pl where pl.token_id = t.id), 0) < :min_liq
  and not exists (select 1 from watchlist_items x where x.token_id = t.id)
  and not exists (select 1 from strategy_evaluations x where x.token_id = t.id)
  and not exists (select 1 from paper_positions x where x.token_id = t.id)
  and not exists (select 1 from paper_orders x where x.token_id = t.id)
  and not exists (select 1 from social_mentions x where x.token_id = t.id)
  and not exists (select 1 from opportunity_scores x where x.token_id = t.id)
  and not exists (select 1 from research_reports x where x.token_id = t.id)
  and not exists (select 1 from presales x where x.token_id = t.id)
  and not exists (select 1 from pools p where p.quote_token_id = t.id)
""")


async def apply_retention(engine: AsyncEngine) -> dict[str, int]:
    async with engine.begin() as conn:
        cfg = await appsettings.load(conn, "retention", appsettings.RetentionSettings)
        raw_cut = datetime.now(UTC) - timedelta(days=cfg.raw_snapshot_days)
        hourly_cut = datetime.now(UTC) - timedelta(days=cfg.hourly_snapshot_days)
        promoted_h = (
            await conn.execute(
                text("""
            with ranked as (
              select id, row_number() over (
                partition by pool_id, date_trunc('hour', observed_at) order by observed_at desc) as rn
              from market_snapshots where resolution = 'raw' and observed_at < :cut)
            update market_snapshots m set resolution = 'hourly'
            from ranked r where r.id = m.id and r.rn = 1
        """),
                {"cut": raw_cut},
            )
        ).rowcount
        deleted_raw = (
            await conn.execute(
                text("delete from market_snapshots where resolution = 'raw' and observed_at < :cut"), {"cut": raw_cut}
            )
        ).rowcount
        promoted_d = (
            await conn.execute(
                text("""
            with ranked as (
              select id, row_number() over (
                partition by pool_id, date_trunc('day', observed_at) order by observed_at desc) as rn
              from market_snapshots where resolution = 'hourly' and observed_at < :cut)
            update market_snapshots m set resolution = 'daily'
            from ranked r where r.id = m.id and r.rn = 1
        """),
                {"cut": hourly_cut},
            )
        ).rowcount
        deleted_hourly = (
            await conn.execute(
                text("delete from market_snapshots where resolution = 'hourly' and observed_at < :cut"),
                {"cut": hourly_cut},
            )
        ).rowcount
        # Scores: keep everything for 7 days, then the last score per token per day.
        thinned_scores = (
            await conn.execute(
                text("""
            delete from opportunity_scores o using (
              select id, row_number() over (
                partition by coalesce(token_id, 0), coalesce(presale_id, 0), date_trunc('day', scored_at)
                order by scored_at desc) as rn
              from opportunity_scores where scored_at < now() - interval '7 days') r
            where o.id = r.id and r.rn > 1
        """)
            )
        ).rowcount
        disc = await appsettings.load(conn, "discovery", appsettings.DiscoverySettings)
        pruned_tokens = (
            await conn.execute(
                _PRUNE_TOKENS,
                {"days": cfg.prune_untracked_token_days, "min_liq": disc.track_min_liquidity_usd},
            )
        ).rowcount
        deleted_usage = (
            await conn.execute(
                text("delete from api_usage where occurred_at < now() - make_interval(days => :d)"),
                {"d": cfg.api_usage_days},
            )
        ).rowcount
        deleted_runs = (
            await conn.execute(
                text("delete from ingestion_runs where started_at < now() - make_interval(days => :d)"),
                {"d": cfg.ingestion_run_days},
            )
        ).rowcount
    return {
        "promoted_hourly": promoted_h,
        "deleted_raw": deleted_raw,
        "promoted_daily": promoted_d,
        "deleted_hourly": deleted_hourly,
        "deleted_api_usage": deleted_usage,
        "deleted_runs": deleted_runs,
        "pruned_tokens": pruned_tokens,
        "thinned_scores": thinned_scores,
    }


async def build_health_report(conn: AsyncConnection) -> dict[str, Any]:
    now = datetime.now(UTC)
    sources = []
    for r in (await conn.execute(text("select * from data_sources where kind <> 'manual' order by id"))).all():
        status, msg = source_status(r, now)
        sources.append(
            {
                "slug": r.slug,
                "enabled": r.enabled,
                "status": status,
                "message": msg,
                "last_success_at": r.last_success_at,
            }
        )
    chains = [
        dict(r._mapping)
        for r in (
            await conn.execute(
                text("""
        select c.slug as chain,
          max(r.finished_at) filter (where r.status in ('success','partial')) as last_success_at,
          count(*) filter (where r.started_at > now() - interval '24 hours') as runs_24h,
          count(*) filter (where r.status = 'failed' and r.started_at > now() - interval '24 hours') as failed_24h,
          count(*) filter (where r.status = 'partial' and r.started_at > now() - interval '24 hours') as partial_24h
        from chains c left join ingestion_runs r on r.chain_id = c.id
        group by c.slug, c.id order by c.id
    """)
            )
        ).all()
    ]
    discovery = [
        dict(r._mapping)
        for r in (
            await conn.execute(
                text("""
        select c.slug as chain, count(*) as new_tokens_24h,
          percentile_cont(0.5) within group (
            order by extract(epoch from t.first_observed_at - t.earliest_pool_created_at))
            filter (where t.earliest_pool_created_at is not null) as latency_p50_s,
          percentile_cont(0.9) within group (
            order by extract(epoch from t.first_observed_at - t.earliest_pool_created_at))
            filter (where t.earliest_pool_created_at is not null) as latency_p90_s
        from tokens t join chains c on c.id = t.chain_id
        where t.first_observed_at > now() - interval '24 hours' and not t.is_quote_asset
        group by c.slug, c.id order by c.id
    """)
            )
        ).all()
    ]
    usage = [
        dict(r._mapping)
        for r in (
            await conn.execute(
                text("""
        select s.slug as source, count(*) as calls, count(*) filter (where not u.ok) as failed,
               coalesce(sum(u.cost_usd), 0) as cost_usd
        from api_usage u join data_sources s on s.id = u.source_id
        where u.occurred_at > now() - interval '24 hours' group by s.slug order by s.slug
    """)
            )
        ).all()
    ]
    month_cost = (
        await conn.execute(
            text("select coalesce(sum(cost_usd),0) from api_usage where occurred_at >= date_trunc('month', now())")
        )
    ).scalar_one()
    components = [
        dict(r._mapping)
        for r in (
            await conn.execute(
                text(
                    "select component, status, checked_at, message from system_health "
                    "where component not like 'source:%' order by component"
                )
            )
        ).all()
    ]
    db_bytes = (await conn.execute(text("select pg_database_size(current_database())"))).scalar_one()
    counts = dict(
        (
            await conn.execute(
                text("""
        select (select count(*) from tokens where not is_quote_asset) as tokens,
               (select count(*) from pools) as pools,
               (select count(*) from market_snapshots) as snapshots
    """)
            )
        )
        .one()
        ._mapping
    )
    # Only enabled sources count. An enabled source that has never succeeded is
    # "unknown", which must not read as healthy: it degrades the overall status.
    enabled = [s["status"] for s in sources if s["enabled"]]
    comp = [c["status"] for c in components]
    overall = "ok"
    if "down" in enabled or "down" in comp:
        overall = "down"
    elif "degraded" in enabled or "unknown" in enabled or "degraded" in comp:
        overall = "degraded"
    return {
        "generated_at": now,
        "generated_at_sgt": now.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M SGT"),
        "overall": overall,
        "sources": sources,
        "chains": chains,
        "discovery_24h": discovery,
        "api_usage_24h": usage,
        "metered_cost_month_usd": month_cost,
        "components": components,
        "database_bytes": db_bytes,
        "row_counts": counts,
    }


def format_health_report_text(report: dict[str, Any]) -> str:
    """Plain-text rendering (used for logs and, from Phase 5, the Telegram digest)."""
    lines = [f"CIT daily health — {report['generated_at_sgt']} — overall: {report['overall'].upper()}", ""]
    lines.append("Sources:")
    for s in report["sources"]:
        lines.append(f"  {s['slug']:<14} {s['status']:<9} {s['message']}")
    lines.append("Chains (24h runs / failed / partial):")
    for c in report["chains"]:
        lines.append(f"  {c['chain']:<9} {c['runs_24h']:>4} / {c['failed_24h']:>3} / {c['partial_24h']:>3}")
    lines.append("New tokens (24h) and discovery latency p50/p90:")
    for d in report["discovery_24h"]:
        p50 = f"{d['latency_p50_s'] / 60:.1f}m" if d["latency_p50_s"] is not None else "n/a"
        p90 = f"{d['latency_p90_s'] / 60:.1f}m" if d["latency_p90_s"] is not None else "n/a"
        lines.append(f"  {d['chain']:<9} {d['new_tokens_24h']:>5}  {p50} / {p90}")
    lines.append(f"Metered API cost this month: ${float(report['metered_cost_month_usd']):.2f}")
    lines.append(f"Database size: {report['database_bytes'] / 1_048_576:.1f} MB; rows: {report['row_counts']}")
    return "\n".join(lines)
