"""Ingestion-run bookkeeping, source freshness and API usage persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cit.chains import BY_SLUG
from cit.providers.http import ApiCall, CircuitBreaker


@dataclass
class RunCounters:
    http_calls: int = 0
    items_fetched: int = 0
    items_new: int = 0
    items_updated: int = 0
    details: dict[str, Any] = field(default_factory=dict)


async def start_run(conn: AsyncConnection, source_slug: str, job_name: str, chain_slug: str | None = None) -> int:
    return (
        await conn.execute(
            text("""
        insert into ingestion_runs (source_id, job_name, chain_id)
        select id, :job, :chain_id from data_sources where slug = :slug
        returning id
    """),
            {"slug": source_slug, "job": job_name, "chain_id": BY_SLUG[chain_slug].id if chain_slug else None},
        )
    ).scalar_one()


async def finish_run(
    conn: AsyncConnection, run_id: int, status: str, counters: RunCounters, error: str | None = None
) -> None:
    import json

    await conn.execute(
        text("""
        update ingestion_runs set finished_at = now(), status = :status, http_calls = :http_calls,
          items_fetched = :items_fetched, items_new = :items_new, items_updated = :items_updated,
          error = :error, details = cast(:details as jsonb)
        where id = :id
    """),
        {
            "id": run_id,
            "status": status,
            "http_calls": counters.http_calls,
            "items_fetched": counters.items_fetched,
            "items_new": counters.items_new,
            "items_updated": counters.items_updated,
            "error": (error or None) and error[:2000],
            "details": json.dumps(counters.details, default=str),
        },
    )


async def record_source_result(
    conn: AsyncConnection, source_slug: str, *, ok: bool, error: str | None, breaker: CircuitBreaker | None
) -> None:
    """Update the source's freshness and circuit state. Partial success counts as success."""
    now = datetime.now(UTC)
    state = breaker.state if breaker else "closed"
    open_until = breaker.open_until if breaker and state != "closed" else None
    if ok:
        await conn.execute(
            text("""
            update data_sources set last_attempt_at = :now, last_success_at = :now,
              consecutive_failures = 0, circuit_state = :state, circuit_open_until = :open_until
            where slug = :slug
        """),
            {"now": now, "slug": source_slug, "state": state, "open_until": open_until},
        )
    else:
        await conn.execute(
            text("""
            update data_sources set last_attempt_at = :now, last_failure_at = :now,
              last_error = :error, consecutive_failures = consecutive_failures + 1,
              circuit_state = :state, circuit_open_until = :open_until
            where slug = :slug
        """),
            {
                "now": now,
                "slug": source_slug,
                "error": (error or "unknown error")[:2000],
                "state": state,
                "open_until": open_until,
            },
        )


async def flush_usage(conn: AsyncConnection, calls: list[ApiCall]) -> int:
    if not calls:
        return 0
    rows = [
        {
            "slug": c.provider,
            "occurred_at": c.occurred_at,
            "job": c.job_name,
            "endpoint": c.endpoint,
            "status": c.status_code,
            "latency": c.latency_ms,
            "ok": c.ok,
            "in_t": c.input_tokens,
            "out_t": c.output_tokens,
            "cost": c.cost_usd,
        }
        for c in calls
    ]
    await conn.execute(
        text("""
        insert into api_usage (source_id, occurred_at, job_name, endpoint, status_code, latency_ms, ok,
                               input_tokens, output_tokens, cost_usd)
        select s.id, :occurred_at, :job, :endpoint, :status, :latency, :ok, :in_t, :out_t, :cost
        from data_sources s where s.slug = :slug
    """),
        rows,
    )
    return len(rows)


async def calls_today(conn: AsyncConnection, source_slug: str) -> int:
    return (
        await conn.execute(
            text("""
        select count(*) from api_usage u join data_sources s on s.id = u.source_id
        where s.slug = :slug and u.occurred_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc'
    """),
            {"slug": source_slug},
        )
    ).scalar_one()


async def heartbeat(
    conn: AsyncConnection,
    component: str,
    status: str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    import json

    await conn.execute(
        text("""
        insert into system_health (component, status, checked_at, last_ok_at, message, details)
        values (:c, :s, now(), case when :s = 'ok' then now() end, :m, cast(:d as jsonb))
        on conflict (component) do update set status = excluded.status, checked_at = excluded.checked_at,
          last_ok_at = coalesce(excluded.last_ok_at, system_health.last_ok_at),
          message = excluded.message, details = excluded.details
    """),
        {"c": component, "s": status, "m": message, "d": json.dumps(details or {}, default=str)},
    )
