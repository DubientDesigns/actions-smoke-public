"""Presale research-priority scorecard, heuristic v1.

Presales have no price history or liquidity, so this scores how well-documented,
verifiable and structurally sane a sale looks — NOT whether it is legitimate,
safe, or will appreciate. Self-reported claims count as "claimed", never as
verified facts. Unknown inputs score zero and are listed as missing.

Categories (fixed weights, labelled heuristic): documentation 30,
verification 25, tokenomics 25, risk controls 20.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from cit.scoring.token_v1 import Item, ScoreResult, _component

VERSION = "presale-heuristic-v1"
WEIGHTS = {"documentation": 30.0, "verification": 25.0, "tokenomics": 25.0, "risk_controls": 20.0}

VERIFICATION_FRACTION = {
    "partially_verified": 0.8,
    "official_source_seen": 0.5,
    "unverified": 0.0,
    "disputed": 0.0,
    "red_flag": 0.0,
}


@dataclass(frozen=True)
class PresaleInputs:
    presale_id: int
    as_of: datetime
    status: str
    sale_type: str
    verification_status: str
    official_website: str | None
    platform: str | None
    team_info: str | None
    vesting_terms: dict[str, Any] | None
    lockup_terms: str | None
    audit_claims: tuple[str, ...]
    sale_price_usd: Decimal | None
    claimed_valuation_usd: Decimal | None
    hard_cap_usd: Decimal | None
    sale_start_at: datetime | None
    sale_end_at: datetime | None
    source_domains: tuple[str, ...]
    claims_total: int
    claims_contradicted: int
    updated_at: datetime


def _num(d: dict[str, Any] | None, key: str) -> float | None:
    if not isinstance(d, dict) or d.get(key) is None:
        return None
    try:
        return float(d[key])
    except (TypeError, ValueError):
        return None


def score_presale(p: PresaleInputs) -> ScoreResult:
    flags: list[str] = []
    if p.verification_status in ("red_flag", "disputed"):
        flags.append(f"verification_{p.verification_status}")
    if not p.official_website:
        flags.append("no_official_website")
    if p.claims_contradicted:
        flags.append("contradicted_claims")
    if p.sale_end_at is not None and p.sale_end_at < p.as_of and p.status not in ("tge_done", "ended"):
        flags.append("sale_end_passed")

    def present(v: Any, label: str) -> tuple[float, str]:
        return (1.0, f"{label} provided (claimed)") if v else (0.0, f"no {label}")

    docs = []
    for key, w, val, label in (
        ("official_website", 0.2, p.official_website, "official website"),
        ("team_info", 0.2, p.team_info, "team information"),
        ("vesting_terms", 0.2, p.vesting_terms, "vesting terms"),
        ("hard_cap", 0.1, p.hard_cap_usd, "hard cap"),
        ("sale_price", 0.1, p.sale_price_usd, "sale price"),
        ("dates", 0.1, p.sale_start_at or p.sale_end_at, "sale dates"),
        ("platform", 0.1, p.platform, "sale platform"),
    ):
        frac, ev = present(val, label)
        docs.append(Item(key, w, frac, ev))

    domains = len(set(p.source_domains))
    verification = [
        Item(
            "verification_status",
            0.5,
            VERIFICATION_FRACTION.get(p.verification_status, 0.0),
            f"verification status: {p.verification_status}",
        ),
        Item(
            "independent_sources",
            0.25,
            1.0 if domains >= 3 else 0.5 if domains == 2 else 0.0,
            f"{domains} distinct source domain(s)",
        ),
        Item(
            "claim_consistency",
            0.25,
            None if p.claims_total == 0 else (0.0 if p.claims_contradicted else 1.0),
            "no claims recorded yet"
            if p.claims_total == 0
            else f"{p.claims_contradicted} of {p.claims_total} claims contradicted",
        ),
    ]

    tge = _num(p.vesting_terms, "tge_unlock_pct")
    vest_m = _num(p.vesting_terms, "vesting_months")
    val = float(p.claimed_valuation_usd) if p.claimed_valuation_usd is not None else None
    if tge is not None and tge > 50:
        flags.append("high_tge_unlock")
    tokenomics = [
        Item(
            "tge_unlock",
            0.4,
            None if tge is None else (1.0 if tge <= 25 else 0.5 if tge <= 50 else 0.0),
            "TGE unlock unknown" if tge is None else f"TGE unlock {tge:.0f}% (claimed)",
        ),
        Item(
            "vesting_length",
            0.3,
            None if vest_m is None else (1.0 if vest_m >= 6 else 0.4),
            "vesting length unknown" if vest_m is None else f"vesting {vest_m:.0f} months (claimed)",
        ),
        Item(
            "valuation",
            0.3,
            None if val is None else (1.0 if val <= 50e6 else 0.5 if val <= 250e6 else 0.0),
            "valuation unknown" if val is None else f"claimed valuation ${val:,.0f}",
        ),
    ]

    risk = [
        Item(
            "audit_claimed",
            0.3,
            1.0 if p.audit_claims else 0.0,
            f"{len(p.audit_claims)} audit claim(s), unverified" if p.audit_claims else "no audit claimed",
        ),
        Item(
            "lockup_terms",
            0.2,
            1.0 if p.lockup_terms else 0.0,
            "lock-up terms provided (claimed)" if p.lockup_terms else "no lock-up terms",
        ),
        Item("sale_type_known", 0.2, 0.0 if p.sale_type == "unknown" else 1.0, f"sale type: {p.sale_type}"),
        Item(
            "no_red_flag_status",
            0.3,
            # Only a reviewed record can be "not flagged"; an unreviewed one is unknown.
            None
            if p.verification_status == "unverified"
            else 0.0
            if p.verification_status in ("red_flag", "disputed")
            else 1.0,
            "not reviewed by operator yet"
            if p.verification_status == "unverified"
            else "operator flagged"
            if p.verification_status in ("red_flag", "disputed")
            else "reviewed, not flagged",
        ),
    ]

    comps = [
        _component("documentation", WEIGHTS["documentation"], docs),
        _component("verification", WEIGHTS["verification"], verification),
        _component("tokenomics", WEIGHTS["tokenomics"], tokenomics),
        _component("risk_controls", WEIGHTS["risk_controls"], risk),
    ]
    d = asdict(p)
    d.pop("as_of")
    return ScoreResult(
        total=round(min(100.0, sum(c.score for c in comps)), 2),
        components={
            c.key: {"score": c.score, "max": c.max, "evidence": c.evidence, "missing": c.missing} for c in comps
        },
        missing_data=[m for c in comps for m in c.missing],
        risk_flags=sorted(set(flags)),
        scoring_version=VERSION,
        data_cutoff_at=p.updated_at,
        inputs_hash=hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest(),
    )
