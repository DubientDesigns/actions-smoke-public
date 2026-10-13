"""Internal FastAPI service.

Bound to the private Docker network only (never published by Caddy). The
Next.js server calls it with a bearer token for operations that need backend
validation; browsers never reach it.
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from cit.ai.schema import PROMPT_VERSION
from cit.config import get_settings
from cit.db.engine import get_engine
from cit.services import ops

app = FastAPI(title="CIT internal API", docs_url=None, redoc_url=None, openapi_url=None)

WORKER_HEARTBEAT_MAX_AGE_S = 180


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().internal_api_token.get_secret_value()
    if not expected:
        raise HTTPException(503, "internal API token not configured")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "unauthorised")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. No dependencies."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, Any]:
    """Readiness: database reachable and worker heartbeat recent."""
    try:
        async with get_engine().connect() as conn:
            hb = (await conn.execute(text("select checked_at from system_health where component = 'worker'"))).scalar()
    except Exception as exc:
        raise HTTPException(503, f"database unavailable: {type(exc).__name__}") from exc
    age = (datetime.now(UTC) - hb).total_seconds() if hb else None
    worker_ok = age is not None and age < WORKER_HEARTBEAT_MAX_AGE_S
    return {"status": "ok" if worker_ok else "degraded", "database": "ok", "worker_heartbeat_age_s": age}


@app.get("/v1/health/report", dependencies=[Depends(require_token)])
async def health_report() -> dict[str, Any]:
    async with get_engine().connect() as conn:
        return await ops.build_health_report(conn)


class ResearchRequest(BaseModel):
    token_id: int = Field(gt=0)
    requested_by: str = Field(min_length=1, max_length=200)


@app.post("/v1/research/requests", dependencies=[Depends(require_token)], status_code=202)
async def request_research(req: ResearchRequest) -> dict[str, Any]:
    """Queue a report for a token (called by the Next.js server for an owner).

    The hourly job processes the queue first; budget caps still apply.
    """
    import uuid

    async with get_engine().begin() as conn:
        exists = (await conn.execute(text("select 1 from tokens where id = :t"), {"t": req.token_id})).first()
        if exists is None:
            raise HTTPException(404, "token not found")
        pending = (
            await conn.execute(
                text(
                    "select id from research_reports where token_id = :t and status in ('queued', 'generating') limit 1"
                ),
                {"t": req.token_id},
            )
        ).first()
        if pending is not None:
            return {"status": "already_queued", "report_id": pending.id}
        rid = (
            await conn.execute(
                text("""
            insert into research_reports (token_id, status, prompt_version, input_hash, evidence)
            values (:t, 'queued', :v, :h, '{}'::jsonb) returning id
        """),
                {"t": req.token_id, "v": PROMPT_VERSION, "h": f"request:{uuid.uuid4()}"},
            )
        ).scalar_one()
        await conn.execute(
            text(
                "insert into audit_log (actor, action, entity, entity_id) "
                "values (:a, 'research_requested', 'token', :t)"
            ),
            {"a": f"user:{req.requested_by}", "t": str(req.token_id)},
        )
    return {"status": "queued", "report_id": rid}
