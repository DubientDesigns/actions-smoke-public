"""Job registry: name -> coroutine factory. Used by the scheduler and `cit run-job`."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from cit.ai import research
from cit.alerts import dispatch, engine
from cit.log import get_logger
from cit.paper import service as paper
from cit.services import discovery, ops, presales, runs, scoring, security, social, wallets
from cit.services.runtime import ProviderRuntime

log = get_logger(__name__)

JobFn = Callable[[ProviderRuntime], Awaitable[Any]]


JOBS: dict[str, JobFn] = {
    "discover_new_pools": discovery.discover_new_pools,
    "ingest_token_profiles": discovery.ingest_token_profiles,
    "refresh_tracked_markets": discovery.refresh_tracked_markets,
    "assess_security": security.assess_security,
    "score_tokens": scoring.score_tokens,
    "collect_telegram": social.collect_telegram,
    "resolve_mentions": social.resolve_mentions,
    "update_mention_outcomes": social.update_mention_outcomes,
    "score_presales": presales.score_presales,
    "sync_wallets": wallets.sync_wallets,
    "check_sources": lambda rt: ops.check_sources(rt.engine),
    "apply_retention": lambda rt: ops.apply_retention(rt.engine),
    "generate_alerts": lambda rt: engine.generate_alerts(rt.engine),
    "dispatch_alerts": dispatch.dispatch_alerts,
    "generate_research_reports": research.generate_research_reports,
    "paper_cycle": lambda rt: paper.paper_cycle(rt.engine),
    "evaluate_strategies": lambda rt: paper.strategy_cycle(rt.engine),
    "record_equity_marks": lambda rt: paper.equity_cycle(rt.engine),
    # Daily digest: deferred alerts + the operational health report (stored even without Telegram).
    "daily_health_report": dispatch.send_daily_digest,
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
