"""Internal FastAPI service.

Bound to the private Docker network only (never published by Caddy). The
Next.js server calls it with a bearer token for operations that need backend
validation; browsers never reach it.
"""

from __future__ import annotations

import hmac
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from cit import appsettings
from cit.ai.schema import PROMPT_VERSION
from cit.config import get_settings
from cit.db.engine import get_engine
from cit.paper import service as paper
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


# ---------------------------------------------------------------------------
# Paper trading (simulation only: no wallets, keys, signing or real execution)
# ---------------------------------------------------------------------------


class TakeProfitLeg(BaseModel):
    gain_pct: float = Field(gt=0, le=10_000)
    sell_pct: float = Field(gt=0, le=100)


class PaperOrderRequest(BaseModel):
    requested_by: uuid.UUID
    kind: Literal["buy", "sell", "presale"]
    token_id: int | None = Field(None, gt=0)
    presale_id: int | None = Field(None, gt=0)
    position_id: int | None = Field(None, gt=0)
    notional_usd: Decimal | None = Field(None, gt=0, le=1_000_000)
    sell_fraction: Decimal | None = Field(None, gt=0, le=1)
    stop_loss_pct: float | None = Field(None, gt=0, lt=100)
    take_profit: list[TakeProfitLeg] = Field(default_factory=list, max_length=5)


@app.post("/v1/paper/orders", dependencies=[Depends(require_token)], status_code=202)
async def place_paper_order(req: PaperOrderRequest) -> dict[str, Any]:
    """Queue a manual paper order in the owner's paper portfolio.

    The signal time is when this request arrives; the worker fills it with the
    first price observed after the portfolio's execution delay.
    """
    now = datetime.now(UTC)
    owner = str(req.requested_by)
    async with get_engine().begin() as conn:
        budget = await appsettings.load(conn, "budget", appsettings.BudgetSettings)
        pid = await paper.ensure_manual_portfolio(conn, owner, Decimal(str(budget.sgd_per_usd)))
        try:
            if req.kind == "buy":
                if req.token_id is None or req.notional_usd is None:
                    raise paper.OrderError("buy needs token_id and notional_usd")
                if (
                    await conn.execute(text("select 1 from tokens where id = :t"), {"t": req.token_id})
                ).first() is None:
                    raise HTTPException(404, "token not found")
                note = json.dumps(
                    {
                        "stop_loss_pct": req.stop_loss_pct,
                        "take_profit": [t.model_dump() for t in req.take_profit] or None,
                    }
                )
                oid = await paper.place_order(
                    conn,
                    portfolio_id=pid,
                    side="buy",
                    signal_at=now,
                    origin="manual",
                    token_id=req.token_id,
                    notional_usd=req.notional_usd,
                    note=note,
                )
            elif req.kind == "presale":
                if req.presale_id is None or req.notional_usd is None:
                    raise paper.OrderError("presale allocation needs presale_id and notional_usd")
                pre = (
                    await conn.execute(
                        text("select status, sale_price_usd from presales where id = :p"), {"p": req.presale_id}
                    )
                ).first()
                if pre is None:
                    raise HTTPException(404, "presale not found")
                if pre.status not in paper.PRESALE_OPEN:
                    raise paper.OrderError(f"presale status is {pre.status}; allocations need an open sale")
                if pre.sale_price_usd is None:
                    raise paper.OrderError("presale has no recorded sale price")
                oid = await paper.place_order(
                    conn,
                    portfolio_id=pid,
                    side="buy",
                    signal_at=now,
                    origin="manual",
                    presale_id=req.presale_id,
                    notional_usd=req.notional_usd,
                    order_type="presale_allocation",
                )
            else:
                if req.position_id is None or req.sell_fraction is None:
                    raise paper.OrderError("sell needs position_id and sell_fraction")
                pos = (
                    await conn.execute(
                        text("select token_id, status from paper_positions where id = :id and portfolio_id = :p"),
                        {"id": req.position_id, "p": pid},
                    )
                ).first()
                if pos is None:
                    raise HTTPException(404, "position not found in your paper portfolio")
                if pos.status == "closed" or pos.token_id is None:
                    raise paper.OrderError("position is closed or its token is not trading yet")
                oid = await paper.place_order(
                    conn,
                    portfolio_id=pid,
                    side="sell",
                    signal_at=now,
                    origin="manual",
                    token_id=pos.token_id,
                    position_id=req.position_id,
                    sell_fraction=req.sell_fraction,
                )
        except paper.OrderError as exc:
            raise HTTPException(422, str(exc)) from exc
        await conn.execute(
            text(
                "insert into audit_log (actor, action, entity, entity_id, details) "
                "values (:a, 'paper_order_placed', 'paper_order', :o, cast(:d as jsonb))"
            ),
            {"a": f"user:{owner}", "o": str(oid), "d": req.model_dump_json(exclude={"requested_by"})},
        )
    return {"status": "pending", "order_id": oid, "portfolio_id": pid}


class PaperCancelRequest(BaseModel):
    requested_by: uuid.UUID


@app.post("/v1/paper/orders/{order_id}/cancel", dependencies=[Depends(require_token)])
async def cancel_paper_order(order_id: int, req: PaperCancelRequest) -> dict[str, Any]:
    async with get_engine().begin() as conn:
        row = (
            await conn.execute(
                text("""
            update paper_orders o set status = 'cancelled', reject_reason = 'cancelled by owner'
            from paper_portfolios p
            where o.id = :id and p.id = o.portfolio_id and p.owner_id = cast(:u as uuid) and o.status = 'pending'
            returning o.id
        """),
                {"id": order_id, "u": str(req.requested_by)},
            )
        ).first()
        if row is None:
            raise HTTPException(404, "no pending order with that id in your paper portfolio")
        await conn.execute(
            text(
                "insert into audit_log (actor, action, entity, entity_id) "
                "values (:a, 'paper_order_cancelled', 'paper_order', :o)"
            ),
            {"a": f"user:{req.requested_by}", "o": str(order_id)},
        )
    return {"status": "cancelled", "order_id": order_id}
