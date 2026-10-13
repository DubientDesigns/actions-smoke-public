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
from sqlalchemy import text

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
