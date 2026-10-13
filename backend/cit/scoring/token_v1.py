"""Token research-priority scorecard, heuristic v1.

THIS IS A HEURISTIC RANKING OF WHAT TO RESEARCH NEXT, NOT A PREDICTION OF
RETURNS. Weights and thresholds are hand-picked starting points, to be
validated by forward testing (Phase 6), not statistically fitted.

Five categories; each produces a fraction in [0, 1] from weighted sub-items and
is multiplied by its configurable weight (default 25/25/25/15/10 = 100).
Rules that keep it honest:
  * An input that is unknown, stale or unsupported contributes 0 and is listed
    under "missing". Nothing unknown ever earns points.
  * Every awarded point carries human-readable evidence.
  * The output records the scoring version, the data cutoff (latest timestamp
    of any input) and a hash of the exact inputs, so a score is reproducible.
The function is pure: same inputs + weights -> same output.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from cit.appsettings import ScoringWeights


@dataclass(frozen=True)
class SecurityInput:
    assessed_at: datetime
    valid_until: datetime
    coverage: str
    risk_level: str
    hard_excluded: bool
    checks: dict[str, str]  # key -> status


@dataclass(frozen=True)
class TokenInputs:
    token_id: int
    chain: str
    as_of: datetime  # evaluation time (for freshness); not part of the hash
    pool_created_at: datetime | None
    market_observed_at: datetime | None
    liquidity_usd: Decimal | None
    volume_h24_usd: Decimal | None
    buys_h24: int | None
    sells_h24: int | None
    price_change_h24: Decimal | None
    fdv_usd: Decimal | None
    pool_count: int
    sources_24h: tuple[str, ...]  # market providers with an observation in the last 24h
    link_types: tuple[str, ...]  # self-reported link types (website, twitter, telegram, ...)
    security: SecurityInput | None
    independent_mentions_7d: int | None = None  # Phase 4; None = not collected yet


@dataclass
class Item:
    key: str
    weight: float  # relative weight within its category
    fraction: float | None  # None = unknown -> 0 and listed as missing
    evidence: str


@dataclass
class Component:
    key: str
    max: float
    score: float = 0.0
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass
class ScoreResult:
    total: float
    components: dict[str, dict[str, Any]]
    missing_data: list[str]
    risk_flags: list[str]
    scoring_version: str
    data_cutoff_at: datetime
    inputs_hash: str


def _band(value: float, bands: list[tuple[float, float]], default: float = 0.0) -> float:
    """bands: [(threshold, fraction)] in descending threshold order; first value >= threshold wins."""
    for threshold, frac in bands:
        if value >= threshold:
            return frac
    return default


def _usd(v: Decimal | None) -> str:
    return "unknown" if v is None else f"${float(v):,.0f}"


def _component(key: str, max_pts: float, items: list[Item]) -> Component:
    c = Component(key, max_pts)
    total_w = sum(i.weight for i in items) or 1.0
    frac = 0.0
    for i in items:
        if i.fraction is None:
            c.missing.append(f"{i.key}: {i.evidence}")
            continue
        frac += i.weight * max(0.0, min(1.0, i.fraction))
        pts = max_pts * i.weight / total_w * max(0.0, min(1.0, i.fraction))
        c.evidence.append(f"{i.key}: {i.evidence} (+{pts:.1f})")
    c.score = round(max_pts * frac / total_w, 2)
    return c


# Security check weights per chain family (relative).
SEC_WEIGHTS_EVM = {
    "honeypot": 0.20,
    "owner_privileges": 0.15,
    "holder_concentration": 0.15,
    "sell_tax": 0.10,
    "open_source": 0.10,
    "buy_tax": 0.05,
    "transfer_pausable": 0.05,
    "blacklist": 0.05,
    "mintable": 0.05,
    "proxy": 0.05,
    "deployer_history": 0.05,
}
SEC_WEIGHTS_SOLANA = {
    "mint_authority": 0.20,
    "freeze_authority": 0.20,
    "holder_concentration": 0.20,
    "balance_mutable": 0.10,
    "transfer_fee": 0.10,
    "closable": 0.05,
    "transfer_hook": 0.05,
    "non_transferable": 0.05,
    "metadata_mutable": 0.05,
}
STATUS_FRACTION = {"pass": 1.0, "warn": 0.5, "risk": 0.0}


def _hash_inputs(inp: TokenInputs) -> str:
    d = asdict(inp)
    d.pop("as_of")
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def score(inp: TokenInputs, w: ScoringWeights) -> ScoreResult:
    flags: list[str] = []
    now = inp.as_of

    # ---- market structure ------------------------------------------------
    age_h = (now - inp.pool_created_at).total_seconds() / 3600 if inp.pool_created_at else None
    txns = (inp.buys_h24 + inp.sells_h24) if inp.buys_h24 is not None and inp.sells_h24 is not None else None
    buy_ratio = (inp.buys_h24 / txns) if txns else None
    vol_liq = (
        float(inp.volume_h24_usd) / float(inp.liquidity_usd)
        if inp.volume_h24_usd is not None and inp.liquidity_usd
        else None
    )
    chg = float(inp.price_change_h24) if inp.price_change_h24 is not None else None
    if vol_liq is not None and vol_liq > 10:
        flags.append("possible_wash_trading")
    if chg is not None and chg <= -80:
        flags.append("price_collapse_24h")
    if buy_ratio is not None and txns is not None and txns >= 20 and (buy_ratio < 0.2 or buy_ratio > 0.9):
        flags.append("one_sided_flow")
    market = _component(
        "market_structure",
        w.market_structure,
        [
            Item(
                "pool_age",
                0.20,
                None
                if age_h is None
                else (0.2 if age_h < 0.5 else 0.6 if age_h < 6 else 1.0 if age_h <= 24 * 14 else 0.7),
                "pool creation time unknown" if age_h is None else f"pool age {age_h:.1f}h",
            ),
            Item(
                "activity",
                0.25,
                None if txns is None else _band(txns, [(500, 1.0), (100, 0.6), (20, 0.3)]),
                "24h transaction counts unknown" if txns is None else f"{txns} txns in 24h",
            ),
            Item(
                "buy_sell_balance",
                0.20,
                None if buy_ratio is None else (0.3 if txns < 20 else 1.0 if 0.35 <= buy_ratio <= 0.75 else 0.4),
                "buy/sell counts unknown" if buy_ratio is None else f"buy share {buy_ratio:.0%}",
            ),
            Item(
                "volume_to_liquidity",
                0.20,
                None
                if vol_liq is None
                else (0.0 if vol_liq > 10 else 0.5 if vol_liq > 3 else 1.0 if vol_liq >= 0.1 else 0.3),
                "volume or liquidity unknown" if vol_liq is None else f"24h volume/liquidity {vol_liq:.2f}",
            ),
            Item(
                "price_stability",
                0.15,
                None if chg is None else (0.0 if chg <= -80 else 0.3 if chg <= -50 else 1.0),
                "24h price change unknown" if chg is None else f"24h change {chg:+.1f}%",
            ),
        ],
    )

    # ---- liquidity & tradeability ------------------------------------------
    liq = float(inp.liquidity_usd) if inp.liquidity_usd is not None else None
    sec_checks = inp.security.checks if inp.security else {}
    lp = sec_checks.get("lp_lock")
    liq_fdv = (liq / float(inp.fdv_usd)) if liq is not None and inp.fdv_usd else None
    liquidity = _component(
        "liquidity",
        w.liquidity,
        [
            Item(
                "depth",
                0.45,
                None
                if liq is None
                else _band(liq, [(250_000, 1.0), (100_000, 0.8), (50_000, 0.6), (20_000, 0.4), (5_000, 0.2)]),
                "liquidity unknown" if liq is None else f"best-pool liquidity {_usd(inp.liquidity_usd)}",
            ),
            Item("lp_lock", 0.25, STATUS_FRACTION.get(lp or ""), f"LP lock check: {lp or 'not assessed'}"),
            Item(
                "liquidity_to_fdv",
                0.15,
                None if liq_fdv is None else _band(liq_fdv, [(0.1, 1.0), (0.03, 0.6), (0.01, 0.3)]),
                "FDV unknown" if liq_fdv is None else f"liquidity/FDV {liq_fdv:.3f}",
            ),
            Item("pool_count", 0.15, 1.0 if inp.pool_count >= 2 else 0.5, f"{inp.pool_count} pool(s)"),
        ],
    )

    # ---- security & tokenomics ----------------------------------------------
    sec = inp.security
    if sec is None:
        security = Component("security", w.security, missing=["security assessment: none yet"])
    elif sec.valid_until < now:
        security = Component(
            "security", w.security, missing=[f"security assessment: stale since {sec.valid_until.isoformat()}"]
        )
        flags.append("security_stale")
    elif sec.hard_excluded:
        security = Component("security", w.security, evidence=["hard exclusion rule triggered (0 points)"])
        flags.append("hard_excluded")
    else:
        weights = SEC_WEIGHTS_EVM if inp.chain != "solana" else SEC_WEIGHTS_SOLANA
        security = _component(
            "security",
            w.security,
            [
                Item(k, wt, STATUS_FRACTION.get(sec.checks.get(k, "unknown")), f"{sec.checks.get(k, 'unknown')}")
                for k, wt in weights.items()
            ],
        )
    if sec is not None and sec.risk_level in ("critical", "high"):
        flags.append(f"security_{sec.risk_level}")

    # ---- social & development evidence ---------------------------------------
    links = set(inp.link_types)
    social = _component(
        "social",
        w.social,
        [
            Item(
                "website_listed",
                0.20,
                1.0 if "website" in links else 0.0,
                "website link present (self-reported)" if "website" in links else "no website link",
            ),
            Item(
                "twitter_listed",
                0.15,
                1.0 if "twitter" in links else 0.0,
                "X/Twitter link present (self-reported)" if "twitter" in links else "no X/Twitter link",
            ),
            Item(
                "telegram_listed",
                0.15,
                1.0 if "telegram" in links else 0.0,
                "Telegram link present (self-reported)" if "telegram" in links else "no Telegram link",
            ),
            Item(
                "independent_mentions",
                0.50,
                None
                if inp.independent_mentions_7d is None
                else _band(inp.independent_mentions_7d, [(5, 1.0), (2, 0.6), (1, 0.3)]),
                "monitored-source mentions not collected yet (Phase 4)"
                if inp.independent_mentions_7d is None
                else f"{inp.independent_mentions_7d} independent mentions in 7d",
            ),
        ],
    )

    # ---- data quality & freshness ---------------------------------------------
    mkt_age = (now - inp.market_observed_at) if inp.market_observed_at else None
    quality = _component(
        "data_quality",
        w.data_quality,
        [
            Item(
                "market_freshness",
                0.4,
                None
                if mkt_age is None
                else (1.0 if mkt_age <= timedelta(minutes=30) else 0.5 if mkt_age <= timedelta(hours=2) else 0.0),
                "no market observation"
                if mkt_age is None
                else f"market data {int(mkt_age.total_seconds() // 60)} min old",
            ),
            Item(
                "source_agreement",
                0.3,
                1.0 if len(inp.sources_24h) >= 2 else 0.4 if inp.sources_24h else 0.0,
                f"observed by {len(inp.sources_24h)} market source(s) in 24h",
            ),
            Item(
                "security_coverage",
                0.3,
                0.0
                if sec is None or sec.valid_until < now
                else (1.0 if sec.coverage == "complete" else 0.5 if sec.coverage == "partial" else 0.0),
                "no current security assessment"
                if sec is None or sec.valid_until < now
                else f"security coverage {sec.coverage}",
            ),
        ],
    )

    comps = [market, liquidity, security, social, quality]
    total = round(sum(c.score for c in comps), 2)
    cutoff_candidates = [t for t in (inp.market_observed_at, sec.assessed_at if sec else None) if t is not None]
    return ScoreResult(
        total=min(100.0, total),
        components={
            c.key: {"score": c.score, "max": c.max, "evidence": c.evidence, "missing": c.missing} for c in comps
        },
        missing_data=[m for c in comps for m in c.missing],
        risk_flags=sorted(set(flags)),
        scoring_version=w.version,
        data_cutoff_at=max(cutoff_candidates) if cutoff_candidates else now,
        inputs_hash=_hash_inputs(inp),
    )
