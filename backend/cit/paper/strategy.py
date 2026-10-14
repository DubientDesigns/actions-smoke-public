"""Rule-based paper strategies (pure, versioned, reproducible).

A strategy version's rules are immutable (enforced by a DB trigger). Each
evaluation stores its exact inputs and the decision, so re-running
`evaluate_entry(rules, inputs)` on stored inputs must reproduce the stored
decision. Every evaluation is recorded, including rejections, so performance
cannot be cherry-picked.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3, "unknown": 4}


class EntryRules(BaseModel):
    min_score: float = Field(70, ge=0, le=100)
    max_risk_level: Literal["low", "medium", "high"] = "medium"
    require_complete_security: bool = True
    min_liquidity_usd: float = Field(50_000, ge=0)
    max_token_age_hours: float = Field(72, gt=0)
    exclude_flags: list[str] = ["possible_wash_trading", "price_collapse_24h", "hard_excluded", "security_stale"]


class TakeProfit(BaseModel):
    gain_pct: float = Field(gt=0)
    sell_pct: float = Field(gt=0, le=100)


class ExitRules(BaseModel):
    stop_loss_pct: float | None = Field(30, gt=0, lt=100)
    take_profit: list[TakeProfit] = [TakeProfit(gain_pct=100, sell_pct=50), TakeProfit(gain_pct=300, sell_pct=100)]
    max_hold_hours: float | None = Field(24 * 7, gt=0)


class StrategyRules(BaseModel):
    notional_usd: float = Field(200, gt=0)
    max_open_positions: int = Field(10, ge=1)
    entry: EntryRules = EntryRules()
    exits: ExitRules = ExitRules()


def inputs_hash(inputs: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()


def evaluate_entry(rules: StrategyRules, x: dict[str, Any]) -> tuple[str, list[str]]:
    """Return ("enter" | "reject", reasons). Unknown inputs never satisfy a rule."""
    e = rules.entry
    reasons: list[str] = []
    score = x.get("score_total")
    if score is None or score < e.min_score:
        reasons.append(f"score {score} < {e.min_score}")
    risk = x.get("risk_level") or "unknown"
    if RISK_ORDER.get(risk, 4) > RISK_ORDER[e.max_risk_level]:
        reasons.append(f"risk {risk} above {e.max_risk_level}")
    if x.get("hard_excluded"):
        reasons.append("hard excluded")
    if e.require_complete_security and x.get("security_coverage") != "complete":
        reasons.append(f"security coverage {x.get('security_coverage') or 'none'}")
    liq = x.get("liquidity_usd")
    if liq is None or liq < e.min_liquidity_usd:
        reasons.append(f"liquidity {liq} < {e.min_liquidity_usd}")
    age = x.get("token_age_hours")
    if age is None or age > e.max_token_age_hours:
        reasons.append(f"token age {age}h outside {e.max_token_age_hours}h")
    bad = sorted(set(x.get("risk_flags") or []) & set(e.exclude_flags))
    if bad:
        reasons.append(f"flags {bad}")
    if x.get("already_held"):
        reasons.append("already held")
    if (x.get("open_positions") or 0) >= rules.max_open_positions:
        reasons.append("max open positions reached")
    if (x.get("cash_usd") or 0) < rules.notional_usd:
        reasons.append("insufficient paper cash")
    return ("reject", reasons) if reasons else ("enter", ["all entry rules satisfied"])
