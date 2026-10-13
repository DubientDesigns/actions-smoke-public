"""Alert delivery to Telegram: severity, quiet hours (SGT), hourly cap, retries, digest.

pending  -> sent       (delivered)
pending  -> deferred   (quiet hours / hourly cap / digest-only severity) -> digested
pending  -> failed     (3 failed attempts)
Delivery is skipped (alerts stay visible on the dashboard) when alerts are
disabled or the bot token / chat id is missing. All alert text is HTML-escaped:
titles can contain token names and other third-party strings.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import text

from cit import appsettings
from cit.alerts.engine import SEVERITY_RANK
from cit.config import DISPLAY_TZ
from cit.log import get_logger
from cit.providers.http import ProviderError
from cit.services import ops, runs
from cit.services.runtime import ProviderRuntime

log = get_logger(__name__)
MAX_ATTEMPTS = 3
ICON = {"info": "\u2139\ufe0f", "low": "▫️", "medium": "🔸", "high": "🔴", "critical": "🚨"}


def in_quiet_hours(now: datetime, start: str, end: str) -> bool:
    local = now.astimezone(DISPLAY_TZ).time()
    s, e = time.fromisoformat(start), time.fromisoformat(end)
    return (s <= local or local < e) if s > e else (s <= local < e)


def format_alert(row: Any, base_url: str | None) -> str:
    body = html.escape(row.body)
    if base_url:
        # Turn app-relative paths (/tokens/..., /presales/...) into links.
        body = "\n".join(f"{base_url.rstrip('/')}{line}" if line.startswith("/") else line for line in body.split("\n"))
    return f"{ICON.get(row.severity, '')} <b>{html.escape(row.title)}</b>\n{body}"


def _delivery_ready(rt: ProviderRuntime) -> tuple[bool, str]:
    s = rt.settings
    if not (s.telegram_bot_token and s.telegram_bot_token.get_secret_value()):
        return False, "CIT_TELEGRAM_BOT_TOKEN not set"
    if not s.telegram_alert_chat_id:
        return False, "CIT_TELEGRAM_ALERT_CHAT_ID not set"
    return True, ""


async def dispatch_alerts(rt: ProviderRuntime) -> dict[str, Any]:
    async with rt.engine.connect() as conn:
        cfg = await appsettings.load(conn, "alerts", appsettings.AlertSettings)
    ready, why = _delivery_ready(rt)
    if not cfg.enabled or not ready:
        return {"skipped": "alerts disabled" if not cfg.enabled else why}
    bot = await rt.telegram()
    bot.client.job_name = "dispatch_alerts"
    now = datetime.now(UTC)
    quiet = in_quiet_hours(now, cfg.quiet_hours_start, cfg.quiet_hours_end)
    stats = {"sent": 0, "deferred": 0, "failed": 0}
    provider_down = False
    async with rt.engine.begin() as conn:
        sent_last_hour = (
            await conn.execute(
                text("select count(*) from alerts where status = 'sent' and sent_at > now() - interval '1 hour'")
            )
        ).scalar_one()
        rows = (
            await conn.execute(
                text("""
            select * from alerts where status = 'pending'
            order by case severity when 'critical' then 0 when 'high' then 1 when 'medium' then 2 else 3 end, created_at
            limit 50 for update skip locked
        """)
            )
        ).all()
        for r in rows:
            reason = None
            if quiet and SEVERITY_RANK[r.severity] < SEVERITY_RANK[cfg.quiet_hours_min_severity]:
                reason = "quiet hours"
            elif sent_last_hour >= cfg.max_alerts_per_hour and r.severity != "critical":
                reason = "hourly cap"
            if reason:
                await conn.execute(
                    text("update alerts set status = 'deferred', status_reason = :r where id = :id"),
                    {"r": reason, "id": r.id},
                )
                stats["deferred"] += 1
                continue
            if provider_down:
                continue  # leave pending; retried next round
            try:
                await bot.send_message(
                    rt.settings.telegram_alert_chat_id or "", format_alert(r, rt.settings.public_url)
                )
                await conn.execute(
                    text("update alerts set status = 'sent', sent_at = now(), attempts = attempts + 1 where id = :id"),
                    {"id": r.id},
                )
                sent_last_hour += 1
                stats["sent"] += 1
            except ProviderError as exc:
                failed = r.attempts + 1 >= MAX_ATTEMPTS
                await conn.execute(
                    text("""
                    update alerts set attempts = attempts + 1, status = :s, status_reason = :r where id = :id
                """),
                    {"s": "failed" if failed else "pending", "r": str(exc)[:300], "id": r.id},
                )
                stats["failed"] += int(failed)
                log.warning("alert_send_failed", alert_id=r.id, error=str(exc))
                # Stop sending this round (deferral decisions above still run); retry next minute.
                provider_down = True
    await rt.flush_usage()
    return stats


def chunk(text_: str, limit: int = 4000) -> list[str]:
    parts, cur = [], ""
    for line in text_.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


async def send_daily_digest(rt: ProviderRuntime) -> dict[str, Any]:
    """Daily digest: deferred alerts + the operational health report."""
    async with rt.engine.begin() as conn:
        cfg = await appsettings.load(conn, "alerts", appsettings.AlertSettings)
        report = await ops.build_health_report(conn)
        report_text = ops.format_health_report_text(report)
        await runs.heartbeat(conn, "daily_health_report", "ok", f"overall={report['overall']}", {"text": report_text})
        rows = (
            await conn.execute(
                text("""
            select id, category, severity, title from alerts
            where status = 'deferred' and created_at > now() - interval '3 days'
            order by created_at
        """)
            )
        ).all()
    ready, why = _delivery_ready(rt)
    if not cfg.enabled or not ready:
        return {"skipped": "alerts disabled" if not cfg.enabled else why, "deferred": len(rows)}
    by_cat: dict[str, list[Any]] = {}
    for r in rows:
        by_cat.setdefault(r.category, []).append(r)
    lines = [f"<b>Daily digest — {html.escape(report['generated_at_sgt'])}</b>"]
    if not rows:
        lines.append("No deferred alerts.")
    for cat, items in sorted(by_cat.items()):
        lines.append(f"\n<b>{html.escape(cat.replace('_', ' '))}</b> ({len(items)})")
        for it in items[:8]:
            lines.append(f"{ICON.get(it.severity, '')} {html.escape(it.title)}")
        if len(items) > 8:
            lines.append(f"… and {len(items) - 8} more on the Alerts page")
    lines.append(f"\n<pre>{html.escape(report_text)}</pre>")
    bot = await rt.telegram()
    bot.client.job_name = "daily_digest"
    try:
        for part in chunk("\n".join(lines)):
            await bot.send_message(rt.settings.telegram_alert_chat_id or "", part)
    except ProviderError as exc:
        await rt.flush_usage()
        return {"error": str(exc), "deferred": len(rows)}
    async with rt.engine.begin() as conn:
        await conn.execute(
            text("""
            update alerts set status = 'digested', digest_sent_at = now() where id = any(:ids)
        """),
            {"ids": [r.id for r in rows]},
        )
    await rt.flush_usage()
    return {"digested": len(rows), "overall": report["overall"]}
