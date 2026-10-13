"""Runtime-tunable settings stored in the app_settings table.

Each key has a Pydantic model with conservative defaults. Defaults are seeded
with `cit seed-settings` (insert-if-missing). Invalid stored values fall back
to defaults and are logged, so a bad edit cannot crash the workers.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cit.log import get_logger

log = get_logger(__name__)


class DiscoverySettings(BaseModel):
    enabled_chains: list[str] = ["bsc", "ethereum", "solana", "base"]
    new_pools_max_pages: int = Field(2, ge=1, le=10)
    # Tokens are tracked (market refresh) for this many days after discovery…
    track_days: int = Field(14, ge=1, le=90)
    # …as long as their best pool has at least this much liquidity.
    track_min_liquidity_usd: float = Field(2000, ge=0)
    max_tracked_tokens: int = Field(300, ge=10, le=2000)
    # Research-filter threshold for "new token" alerts.
    alert_min_liquidity_usd: float = Field(20000, ge=0)


class ScoringWeights(BaseModel):
    """Heuristic weights (labelled as such). Must sum to 100."""

    version: str = "token-heuristic-v1"
    market_structure: float = 25
    liquidity: float = 25
    security: float = 25
    social: float = 15
    data_quality: float = 10

    @model_validator(mode="after")
    def _sum_100(self) -> ScoringWeights:
        total = self.market_structure + self.liquidity + self.security + self.social + self.data_quality
        if abs(total - 100) > 1e-6:
            raise ValueError(f"scoring weights must sum to 100, got {total}")
        return self


class AiBudget(BaseModel):
    enabled: bool = False
    model: str = "claude-haiku-5-5"
    daily_request_cap: int = Field(20, ge=0)
    daily_token_cap: int = Field(200_000, ge=0)
    monthly_usd_cap: float = Field(10.0, ge=0)
    use_batch_api: bool = True


class AlertSettings(BaseModel):
    enabled: bool = False
    quiet_hours_start: str = "23:00"  # Asia/Singapore
    quiet_hours_end: str = "07:30"
    quiet_hours_min_severity: Literal["info", "low", "medium", "high", "critical"] = "high"
    default_cooldown_minutes: int = 360
    daily_digest_time: str = "08:00"
    max_alerts_per_hour: int = 12


class RetentionSettings(BaseModel):
    """Sized for the Supabase free tier (500 MB); see docs/COSTS.md."""

    raw_snapshot_days: int = Field(3, ge=1)
    hourly_snapshot_days: int = Field(30, ge=7)
    # Tokens that never reached the tracking liquidity threshold and are not
    # referenced by any research record are deleted after this many days.
    prune_untracked_token_days: int = Field(14, ge=3)
    api_usage_days: int = Field(120, ge=31)
    ingestion_run_days: int = Field(60, ge=7)


class BudgetSettings(BaseModel):
    monthly_budget_sgd: float = 60.0
    sgd_per_usd: float = 1.30  # operator-maintained reference rate
    alert_thresholds_pct: list[int] = [50, 80, 100]


REGISTRY: dict[str, type[BaseModel]] = {
    "discovery": DiscoverySettings,
    "scoring.token_weights": ScoringWeights,
    "ai.budget": AiBudget,
    "alerts": AlertSettings,
    "retention": RetentionSettings,
    "budget": BudgetSettings,
}


async def load[M: BaseModel](conn: AsyncConnection, key: str, model: type[M]) -> M:
    raw = (await conn.execute(text("select value from app_settings where key = :k"), {"k": key})).scalar()
    if raw is None:
        return model()
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        log.error("invalid_app_setting_using_defaults", key=key, error=str(exc))
        return model()


async def seed_defaults(conn: AsyncConnection) -> list[str]:
    seeded: list[str] = []
    for key, model in REGISTRY.items():
        res = await conn.execute(
            text("""
            insert into app_settings (key, value, description, updated_by)
            values (:k, cast(:v as jsonb), :d, 'seed') on conflict (key) do nothing
        """),
            {"k": key, "v": json.dumps(model().model_dump()), "d": (model.__doc__ or "").strip() or None},
        )
        if res.rowcount:
            seeded.append(key)
    return seeded
