"""Job registry: name -> coroutine factory. Used by the scheduler and `cit run-job`."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from cit.log import get_logger
from cit.services import discovery, ops, runs
from cit.services.runtime import ProviderRuntime

log = get_logger(__name__)

JobFn = Callable[[ProviderRuntime], Awaitable[Any]]


async def _health_report(rt: ProviderRuntime) -> dict[str, Any]:
    async with rt.engine.begin() as conn:
        report = await ops.build_health_report(conn)
        await runs.heartbeat(
            conn,
            "daily_health_report",
            "ok",
            f"overall={report['overall']}",
            {"text": ops.format_health_report_text(report)},
        )
    log.info("daily_health_report", text=ops.format_health_report_text(report))
    return {"overall": report["overall"]}


JOBS: dict[str, JobFn] = {
    "discover_new_pools": discovery.discover_new_pools,
    "ingest_token_profiles": discovery.ingest_token_profiles,
    "refresh_tracked_markets": discovery.refresh_tracked_markets,
    "check_sources": lambda rt: ops.check_sources(rt.engine),
    "apply_retention": lambda rt: ops.apply_retention(rt.engine),
    "daily_health_report": _health_report,
}


async def run_job(name: str, rt: ProviderRuntime) -> Any:
    """Run one job with timing, structured logging and a per-job heartbeat.

    Never raises: a failing job must not take down the scheduler.
    """
    fn = JOBS[name]
    started = time.monotonic()
    try:
        result = await fn(rt)
        status, msg = "ok", None
    except Exception as exc:
        log.exception("job_failed", job=name)
        result, status, msg = None, "degraded", f"{type(exc).__name__}: {exc}"[:500]
    elapsed = round(time.monotonic() - started, 2)
    try:
        async with rt.engine.begin() as conn:
            await runs.heartbeat(conn, f"job:{name}", status, msg, {"elapsed_s": elapsed, "result": result})
    except Exception:
        log.exception("heartbeat_failed", job=name)
    log.info("job_finished", job=name, status=status, elapsed_s=elapsed, result=result)
    return result
