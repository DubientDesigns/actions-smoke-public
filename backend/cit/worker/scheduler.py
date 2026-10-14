"""Worker process: APScheduler running the ingestion schedule.

Schedule (see docs/INGESTION.md for the rate-limit budget):
  discover_new_pools       every 10 min   GeckoTerminal  4-8 calls/run
  ingest_token_profiles    every 10 min   DEX Screener   1 call/run
  refresh_tracked_markets  every 15 min   DEX Screener   <=10 calls/run (300 tokens / 30)
  assess_security          every 10 min   GoPlus         <=25 calls/run (new/stale liquid tokens)
  score_tokens             every 15 min   database only (material changes stored)
  collect_telegram         every 2 min    Telegram Bot   1 call (skipped without a bot token)
  resolve_mentions         every 15 min   DEX Screener   <=3 calls (unknown mentioned contracts)
  update_mention_outcomes  every 30 min   database only
  score_presales           every 30 min   database only
  sync_wallets             every 15 min   Alchemy/Helius 1-3 calls per tracked wallet (skipped without keys)
  check_sources            every 5 min    database only
  apply_retention          daily 03:15 SGT
  daily_health_report      daily 08:00 SGT  digest of deferred alerts + health report (Telegram)
  generate_alerts          every 10 min   database only
  dispatch_alerts          every 1 min    Telegram Bot   <=12 messages/hour (quiet hours 23:00-07:30 SGT)
  generate_research_reports hourly        Claude API     <=5/run, hard daily/monthly caps
  paper_cycle              every 2 min    database only  fills (after delay), marks, SL/TP/max-hold rules
  evaluate_strategies      every 15 min   database only  every new score evaluated per strategy version
  record_equity_marks      hourly :05     database only  equity at liquidation value
State lives in Postgres, so a restarted worker simply resumes the schedule.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from cit.config import DISPLAY_TZ, get_settings
from cit.db.engine import get_engine
from cit.log import get_logger
from cit.services import runs
from cit.services.runtime import ProviderRuntime
from cit.worker.jobs import run_job

log = get_logger(__name__)


def build_scheduler(rt: ProviderRuntime) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(
        timezone=UTC, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
    )
    soon = datetime.now(UTC) + timedelta(seconds=15)

    def add(name: str, trigger: object, first_run_delay_s: int | None = None) -> None:
        kwargs = {}
        if first_run_delay_s is not None:
            kwargs["next_run_time"] = soon + timedelta(seconds=first_run_delay_s)
        sched.add_job(run_job, trigger, args=[name, rt], id=name, name=name, **kwargs)

    add("discover_new_pools", IntervalTrigger(minutes=10), 0)
    add("ingest_token_profiles", IntervalTrigger(minutes=10), 120)
    add("refresh_tracked_markets", IntervalTrigger(minutes=15), 240)
    add("assess_security", IntervalTrigger(minutes=10), 300)
    add("score_tokens", IntervalTrigger(minutes=15), 420)
    add("collect_telegram", IntervalTrigger(minutes=2), 30)
    add("resolve_mentions", IntervalTrigger(minutes=15), 360)
    add("update_mention_outcomes", IntervalTrigger(minutes=30), 480)
    add("score_presales", IntervalTrigger(minutes=30), 90)
    add("sync_wallets", IntervalTrigger(minutes=15), 540)
    add("generate_alerts", IntervalTrigger(minutes=10), 150)
    add("dispatch_alerts", IntervalTrigger(minutes=1), 170)
    add("generate_research_reports", CronTrigger(minute=20), None)
    add("paper_cycle", IntervalTrigger(minutes=2), 200)
    add("evaluate_strategies", IntervalTrigger(minutes=15), 600)
    add("record_equity_marks", CronTrigger(minute=5), None)
    add("check_sources", IntervalTrigger(minutes=5), 60)
    add("apply_retention", CronTrigger(hour=3, minute=15, timezone=DISPLAY_TZ))
    add("daily_health_report", CronTrigger(hour=8, minute=0, timezone=DISPLAY_TZ))
    sched.add_job(
        _heartbeat, IntervalTrigger(minutes=1), args=[rt], id="worker_heartbeat", next_run_time=datetime.now(UTC)
    )
    sched.add_job(rt.reset_daily_counters, CronTrigger(hour=0, minute=0, timezone=UTC), id="reset_daily")
    return sched


async def _heartbeat(rt: ProviderRuntime) -> None:
    try:
        async with rt.engine.begin() as conn:
            await runs.heartbeat(conn, "worker", "ok", "scheduler alive")
    except Exception:
        log.exception("worker_heartbeat_failed")


async def run_worker() -> None:
    settings = get_settings()
    rt = ProviderRuntime(settings, get_engine())
    sched = build_scheduler(rt)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    sched.start()
    log.info("worker_started", jobs=[j.id for j in sched.get_jobs()])
    await stop.wait()
    log.info("worker_stopping")
    sched.shutdown(wait=False)
    await rt.aclose()
    await get_engine().dispose()
