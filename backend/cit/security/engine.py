"""Security rules engine: provider fields -> explicit per-check results.

Every check resolves to exactly one of:
  pass         the provider affirmatively reported the safe value
  warn         a weaker red flag; worth knowing, not disqualifying alone
  risk         a detected risk
  unknown      the provider did not return a usable value
  unsupported  this check is not available for this chain/provider

A missing value is ALWAYS "unknown" and an unavailable check is ALWAYS
"unsupported" — neither is ever treated as "pass". The overall risk level is
"low" only when the core checks are complete and clean; with gaps and no
detected risk it is "unknown".

These are heuristics from a third-party API. They are not an audit and can
miss malicious contracts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from cit.appsettings import SecurityPolicy
from cit.chains import BY_SLUG

Status = Literal["pass", "warn", "risk", "unknown", "unsupported"]

BURN_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
    "0xdead000000000000000042069420694206942069",
    "1nc1nerator11111111111111111111111111111111",
}


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    status: Status
    value: Any = None
    detail: str | None = None
    source: str = "goplus"


@dataclass
class Assessment:
    chain_slug: str
    coverage: str  # complete | partial | not_found | unsupported | error
    risk_level: str  # critical | high | medium | low | unknown
    hard_excluded: bool
    needs_review: bool
    checks: list[Check]
    risk_flags: list[str] = field(default_factory=list)
    is_honeypot: bool | None = None
    buy_tax_pct: Decimal | None = None
    sell_tax_pct: Decimal | None = None
    top10_holder_pct: Decimal | None = None
    total_supply: str | None = None

    def checks_json(self) -> list[dict[str, Any]]:
        out = []
        for c in self.checks:
            d = asdict(c)
            if isinstance(d["value"], Decimal):
                d["value"] = str(d["value"])
            out.append(d)
        return out


# Checks that must be pass/warn/risk (not unknown) for coverage to be "complete".
CORE_EVM = ("honeypot", "sell_tax", "buy_tax", "owner_privileges", "open_source", "holder_concentration")
CORE_SOLANA = ("mint_authority", "freeze_authority", "holder_concentration")

# Checks the provider cannot answer on a given chain family (shown explicitly).
UNSUPPORTED_ON_SOLANA = {
    "honeypot": "Honeypot simulation",
    "buy_tax": "Buy tax",
    "sell_tax": "Sell tax",
    "owner_privileges": "Owner privileges",
    "open_source": "Verified source",
    "proxy": "Upgradeable proxy",
    "blacklist": "Blacklist function",
    "lp_lock": "Liquidity lock",
}
UNSUPPORTED_ON_EVM = {
    "mint_authority": "Mint authority",
    "freeze_authority": "Freeze authority",
}


# ---------------------------------------------------------------------------
# Field helpers (GoPlus sends "1"/"0"/"" strings)
# ---------------------------------------------------------------------------


def flag(v: Any) -> bool | None:
    if v in ("1", 1, True):
        return True
    if v in ("0", 0, False):
        return False
    return None


def frac_pct(v: Any) -> Decimal | None:
    """GoPlus taxes/percents are fractions ("0.05"); return percent (5)."""
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite() or d < 0:
        return None
    return (d * 100).quantize(Decimal("0.01"))


def status_obj(v: Any) -> bool | None:
    """Solana fields look like {"status": "1", "authority": [...]}."""
    if isinstance(v, dict):
        return flag(v.get("status"))
    return flag(v)


def binary(
    key: str,
    label: str,
    value: bool | None,
    *,
    risk_when: bool = True,
    level: Status = "risk",
    detail_true: str | None = None,
) -> Check:
    if value is None:
        return Check(key, label, "unknown", None, "not reported by provider")
    bad = value is risk_when
    return Check(key, label, level if bad else "pass", value, detail_true if bad else None)


def threshold_check(key: str, label: str, pct: Decimal | None, warn: float, risk: float, what: str) -> Check:
    if pct is None:
        return Check(key, label, "unknown", None, "not reported by provider")
    if pct >= Decimal(str(risk)):
        return Check(key, label, "risk", pct, f"{what} {pct}% >= {risk}%")
    if pct >= Decimal(str(warn)):
        return Check(key, label, "warn", pct, f"{what} {pct}% >= {warn}%")
    return Check(key, label, "pass", pct)


def holder_concentration(holders: Any, exclude: set[str], pol: SecurityPolicy, *, case_sensitive: bool) -> Check:
    """Top-10 holder share, excluding burn addresses, locked balances and known pool addresses."""
    label = "Top-10 holder concentration"
    if not isinstance(holders, list) or not holders:
        return Check("holder_concentration", label, "unknown", None, "holder list not reported")
    total = Decimal(0)
    counted = 0
    for h in holders:
        if not isinstance(h, dict):
            continue
        addr = str(h.get("address") or h.get("account") or "")
        key = addr if case_sensitive else addr.lower()
        if key in exclude or key.lower() in BURN_ADDRESSES or flag(h.get("is_locked")) is True:
            continue
        pct = frac_pct(h.get("percent"))
        if pct is None:
            continue
        total += pct
        counted += 1
        if counted == 10:
            break
    if counted == 0:
        return Check("holder_concentration", label, "unknown", None, "no usable holder entries")
    c = threshold_check(
        "holder_concentration",
        label,
        total,
        pol.top10_warn_pct,
        pol.top10_risk_pct,
        "top-10 (excl. burn/locked/pools) hold",
    )
    return c


def lp_lock_check(lp_holders: Any, pol: SecurityPolicy) -> Check:
    label = "Liquidity locked or burned"
    if not isinstance(lp_holders, list) or not lp_holders:
        return Check("lp_lock", label, "unknown", None, "LP holder list not reported")
    secured = Decimal(0)
    for h in lp_holders:
        if not isinstance(h, dict):
            continue
        pct = frac_pct(h.get("percent"))
        if pct is None:
            continue
        addr = str(h.get("address") or "").lower()
        if flag(h.get("is_locked")) is True or addr in BURN_ADDRESSES:
            secured += pct
    secured = min(secured, Decimal(100))
    if secured >= Decimal(str(pol.lp_locked_pass_pct)):
        return Check("lp_lock", label, "pass", secured, f"{secured}% of LP locked/burned")
    if secured >= Decimal(str(pol.lp_locked_warn_pct)):
        return Check("lp_lock", label, "warn", secured, f"only {secured}% of LP locked/burned")
    return Check("lp_lock", label, "risk", secured, f"only {secured}% of LP locked/burned")


def supply_change_check(current: str | None, previous: str | None) -> Check:
    label = "Total supply unchanged since last assessment"
    if current in (None, ""):
        return Check("supply_change", label, "unknown", None, "total supply not reported")
    if previous in (None, ""):
        return Check("supply_change", label, "unknown", current, "no earlier assessment to compare")
    if str(current) == str(previous):
        return Check("supply_change", label, "pass", current)
    return Check("supply_change", label, "warn", current, f"supply changed from {previous} to {current}")


# ---------------------------------------------------------------------------
# Chain-family evaluators
# ---------------------------------------------------------------------------


def _evm_checks(d: dict[str, Any], pol: SecurityPolicy, pools: set[str], prev_supply: str | None) -> list[Check]:
    checks: list[Check] = []
    in_dex = flag(d.get("is_in_dex"))
    hp = flag(d.get("is_honeypot"))
    if in_dex is False:
        checks.append(
            Check(
                "honeypot",
                "Honeypot (sell simulation)",
                "unknown",
                None,
                "provider reports token not in a DEX; simulation not meaningful",
            )
        )
    else:
        checks.append(binary("honeypot", "Honeypot (sell simulation)", hp, detail_true="cannot sell in simulation"))
    checks.append(binary("cannot_buy", "Buying blocked", flag(d.get("cannot_buy"))))
    checks.append(binary("cannot_sell_all", "Cannot sell entire balance", flag(d.get("cannot_sell_all"))))
    checks.append(
        threshold_check("buy_tax", "Buy tax", frac_pct(d.get("buy_tax")), pol.tax_warn_pct, pol.tax_risk_pct, "buy tax")
    )
    checks.append(
        threshold_check(
            "sell_tax", "Sell tax", frac_pct(d.get("sell_tax")), pol.tax_warn_pct, pol.tax_risk_pct, "sell tax"
        )
    )
    checks.append(
        binary("tax_modifiable", "Owner can change tax/slippage", flag(d.get("slippage_modifiable")), level="warn")
    )
    checks.append(binary("transfer_pausable", "Transfers can be paused", flag(d.get("transfer_pausable"))))
    checks.append(binary("blacklist", "Blacklist function", flag(d.get("is_blacklisted")), level="warn"))
    checks.append(binary("whitelist", "Whitelist function", flag(d.get("is_whitelisted")), level="warn"))
    checks.append(binary("mintable", "Owner can mint", flag(d.get("is_mintable")), level="warn"))
    checks.append(binary("proxy", "Upgradeable proxy", flag(d.get("is_proxy")), level="warn"))
    checks.append(
        binary(
            "open_source",
            "Verified source code",
            flag(d.get("is_open_source")),
            risk_when=False,
            detail_true="source not verified",
        )
    )

    privs = {k: flag(d.get(k)) for k in ("can_take_back_ownership", "hidden_owner", "owner_change_balance")}
    if any(v is True for v in privs.values()):
        bad = [k for k, v in privs.items() if v is True]
        checks.append(Check("owner_privileges", "Dangerous owner privileges", "risk", bad, ", ".join(bad)))
    elif all(v is False for v in privs.values()):
        checks.append(Check("owner_privileges", "Dangerous owner privileges", "pass", []))
    else:
        checks.append(
            Check(
                "owner_privileges",
                "Dangerous owner privileges",
                "unknown",
                None,
                "one or more privilege fields not reported",
            )
        )
    checks.append(binary("selfdestruct", "Self-destruct", flag(d.get("selfdestruct"))))
    checks.append(binary("external_call", "External calls in transfer", flag(d.get("external_call")), level="warn"))
    checks.append(binary("anti_whale", "Anti-whale limits", flag(d.get("is_anti_whale")), level="warn"))
    checks.append(binary("trading_cooldown", "Trading cooldown", flag(d.get("trading_cooldown")), level="warn"))
    checks.append(
        binary(
            "deployer_history",
            "Deployer created honeypots before",
            flag(d.get("honeypot_with_same_creator")),
            detail_true="same creator deployed known honeypots",
        )
    )
    checks.append(holder_concentration(d.get("holders"), pools, pol, case_sensitive=False))
    checks.append(lp_lock_check(d.get("lp_holders"), pol))
    checks.append(supply_change_check(d.get("total_supply"), prev_supply))
    for key, label in UNSUPPORTED_ON_EVM.items():
        checks.append(Check(key, label, "unsupported", None, "Solana-specific"))
    return checks


def _solana_checks(d: dict[str, Any], pol: SecurityPolicy, pools: set[str], prev_supply: str | None) -> list[Check]:
    checks = [
        binary(
            "mint_authority",
            "Mint authority active",
            status_obj(d.get("mintable")),
            detail_true="supply can be increased",
        ),
        binary(
            "freeze_authority",
            "Freeze authority active",
            status_obj(d.get("freezable")),
            detail_true="holder accounts can be frozen",
        ),
        binary("closable", "Token can be closed", status_obj(d.get("closable"))),
        binary("balance_mutable", "Balances mutable by authority", status_obj(d.get("balance_mutable_authority"))),
        binary("non_transferable", "Non-transferable", flag(d.get("non_transferable"))),
        binary("metadata_mutable", "Metadata mutable", status_obj(d.get("metadata_mutable")), level="warn"),
    ]
    fee = d.get("transfer_fee")
    if fee is None:
        checks.append(Check("transfer_fee", "Transfer fee", "unknown", None, "not reported by provider"))
    elif isinstance(fee, dict) and not fee:
        checks.append(Check("transfer_fee", "Transfer fee", "pass", {}))
    else:
        checks.append(Check("transfer_fee", "Transfer fee", "warn", fee, "token-2022 transfer fee configured"))
    hook = d.get("transfer_hook")
    if hook is None:
        checks.append(Check("transfer_hook", "Transfer hook", "unknown", None, "not reported by provider"))
    elif isinstance(hook, list) and not hook:
        checks.append(Check("transfer_hook", "Transfer hook", "pass", []))
    else:
        checks.append(Check("transfer_hook", "Transfer hook", "warn", hook, "custom program runs on every transfer"))
    das = d.get("default_account_state")
    if das in (None, ""):
        checks.append(Check("default_account_state", "Default account state", "unknown", None, "not reported"))
    elif str(das) == "2":
        checks.append(Check("default_account_state", "Default account state", "risk", das, "new accounts start frozen"))
    else:
        checks.append(Check("default_account_state", "Default account state", "pass", das))
    checks.append(holder_concentration(d.get("holders"), pools, pol, case_sensitive=True))
    checks.append(supply_change_check(d.get("total_supply"), prev_supply))
    checks.append(
        Check("deployer_history", "Deployer history", "unsupported", None, "not provided for Solana by this provider")
    )
    for key, label in UNSUPPORTED_ON_SOLANA.items():
        checks.append(Check(key, label, "unsupported", None, "not available for Solana from this provider"))
    return checks


def evaluate(
    chain_slug: str,
    found: bool,
    data: dict[str, Any],
    pol: SecurityPolicy,
    *,
    pool_addresses: set[str] | None = None,
    previous_total_supply: str | None = None,
) -> Assessment:
    chain = BY_SLUG[chain_slug]
    pools = {a if not chain.is_evm else a.lower() for a in (pool_addresses or set())}
    if not found:
        return Assessment(
            chain_slug,
            "not_found",
            "unknown",
            False,
            False,
            [
                Check(
                    "provider_coverage",
                    "Provider has data for this token",
                    "unknown",
                    None,
                    "token not found in provider response",
                )
            ],
        )
    checks = (_evm_checks if chain.is_evm else _solana_checks)(data, pol, pools, previous_total_supply)
    by_key = {c.key: c for c in checks}

    core = CORE_EVM if chain.is_evm else CORE_SOLANA
    core_unknown = [k for k in core if by_key.get(k) is None or by_key[k].status == "unknown"]
    coverage = "complete" if not core_unknown else "partial"

    risks = [c for c in checks if c.status == "risk"]
    warns = [c for c in checks if c.status == "warn"]
    hard = [c.key for c in risks if c.key in pol.hard_exclude_checks]
    review = [c.key for c in risks + warns if c.key in pol.review_checks]

    if hard:
        level = "critical"
    elif risks:
        level = "high"
    elif coverage != "complete":
        level = "unknown"  # nothing bad found, but not enough to call it low
    elif len(warns) >= 2:
        level = "medium"
    else:
        level = "low"

    flags = [f"risk:{c.key}" for c in risks] + [f"warn:{c.key}" for c in warns]
    flags += [f"unknown:{k}" for k in core_unknown]

    def num(key: str) -> Decimal | None:
        c = by_key.get(key)
        return c.value if c is not None and isinstance(c.value, Decimal) else None

    hp = by_key.get("honeypot")
    return Assessment(
        chain_slug=chain_slug,
        coverage=coverage,
        risk_level=level,
        hard_excluded=bool(hard),
        needs_review=bool(review) or bool(risks and not hard),
        checks=checks,
        risk_flags=flags,
        is_honeypot=(hp.status == "risk") if hp is not None and hp.status in ("pass", "risk") else None,
        buy_tax_pct=num("buy_tax"),
        sell_tax_pct=num("sell_tax"),
        top10_holder_pct=num("holder_concentration"),
        total_supply=str(data.get("total_supply")) if data.get("total_supply") not in (None, "") else None,
    )
