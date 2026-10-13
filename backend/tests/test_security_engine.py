"""Security rules engine on SYNTHETIC GoPlus-shaped payloads (see fixtures/synthetic/README.md)."""

from decimal import Decimal

import pytest

from cit.appsettings import SecurityPolicy
from cit.providers.goplus import parse_envelope
from cit.providers.http import ProviderError
from cit.security.engine import evaluate

from .helpers import synthetic

POL = SecurityPolicy()
CLEAN = "0x2222222222222222222222222222222222222222"
POOL = "0x1111111111111111111111111111111111111111"


def _eval(chain, fixture, address, **kw):
    res = parse_envelope(chain, address, synthetic(fixture))
    return res, evaluate(chain, res.found, res.data, POL, **kw)


def statuses(a):
    return {c.key: c.status for c in a.checks}


def test_clean_evm_token_is_low_risk_with_complete_coverage():
    _, a = _eval("bsc", "goplus_evm_clean.json", CLEAN, pool_addresses={POOL}, previous_total_supply="1000000000")
    s = statuses(a)
    assert a.coverage == "complete" and a.risk_level == "low" and not a.hard_excluded
    assert s["honeypot"] == s["sell_tax"] == s["owner_privileges"] == s["open_source"] == "pass"
    assert a.buy_tax_pct == Decimal("2.00") and a.sell_tax_pct == Decimal("3.00")  # fractions -> percent
    # Pool (40%), burn address (20%) and locked balance (10%) are excluded: 5% + 4%.
    assert a.top10_holder_pct == Decimal("9.00") and s["holder_concentration"] == "pass"
    assert s["lp_lock"] == "pass" and s["supply_change"] == "pass"
    # Solana-only checks are explicitly unsupported, never silently passed.
    assert s["mint_authority"] == s["freeze_authority"] == "unsupported"


def test_pool_not_excluded_inflates_concentration():
    _, a = _eval("bsc", "goplus_evm_clean.json", CLEAN, pool_addresses=set())
    # Pool counted when we don't know it: 40 + 5 + 4 = 49% -> warn (>= 30, < 50).
    assert statuses(a)["holder_concentration"] == "warn" and a.top10_holder_pct == Decimal("49.00")


def test_honeypot_is_critical_and_hard_excluded():
    _, a = _eval("ethereum", "goplus_evm_honeypot.json", "0x4444444444444444444444444444444444444444")
    s = statuses(a)
    assert a.risk_level == "critical" and a.hard_excluded and a.is_honeypot is True
    assert s["honeypot"] == s["cannot_sell_all"] == s["sell_tax"] == s["owner_privileges"] == "risk"
    assert s["open_source"] == "risk"
    assert "risk:honeypot" in a.risk_flags


def test_missing_fields_are_unknown_never_pass():
    res, a = _eval("base", "goplus_evm_sparse.json", "0x5555555555555555555555555555555555555555")
    s = statuses(a)
    assert res.partial
    assert s["honeypot"] == "unknown" and s["buy_tax"] == "unknown"
    assert s["owner_privileges"] == "unknown" and s["holder_concentration"] == "unknown"
    assert s["lp_lock"] == "unknown" and s["transfer_pausable"] == "unknown"
    assert a.coverage == "partial"
    # Nothing bad found, but too little data to call it low risk.
    assert a.risk_level == "unknown" and not a.hard_excluded
    assert a.is_honeypot is None
    assert "unknown:honeypot" in a.risk_flags


def test_no_check_passes_on_empty_data():
    from cit.security.engine import evaluate as ev

    for chain in ("bsc", "solana"):
        a = ev(chain, True, {}, POL)
        assert all(c.status in ("unknown", "unsupported") for c in a.checks), chain
        assert a.risk_level == "unknown"


def test_solana_freeze_authority_excluded_and_evm_checks_unsupported():
    _, a = _eval("solana", "goplus_solana_freeze.json", "SyntheticMint1111111111111111111111111111")
    s = statuses(a)
    assert s["freeze_authority"] == "risk" and a.hard_excluded and a.risk_level == "critical"
    assert s["mint_authority"] == "pass" and s["transfer_fee"] == "pass" and s["transfer_hook"] == "pass"
    assert s["metadata_mutable"] == "warn"
    assert s["honeypot"] == s["lp_lock"] == s["sell_tax"] == "unsupported"
    assert a.top10_holder_pct == Decimal("20.00")


def test_supply_change_detected():
    _, a = _eval("bsc", "goplus_evm_clean.json", CLEAN, pool_addresses={POOL}, previous_total_supply="999")
    assert statuses(a)["supply_change"] == "warn" and a.needs_review


def test_not_found_and_error_envelopes():
    res = parse_envelope("bsc", CLEAN, synthetic("goplus_not_found.json"))
    a = evaluate("bsc", res.found, res.data, POL)
    assert not res.found and a.coverage == "not_found" and a.risk_level == "unknown"
    with pytest.raises(ProviderError, match="4029"):
        parse_envelope("bsc", CLEAN, synthetic("goplus_rate_limited.json"))


def test_policy_controls_exclusion():
    pol = SecurityPolicy(hard_exclude_checks=[], review_checks=["honeypot"])
    res = parse_envelope("ethereum", "0x4444444444444444444444444444444444444444",
                         synthetic("goplus_evm_honeypot.json"))
    a = evaluate("ethereum", True, res.data, pol)
    assert not a.hard_excluded and a.risk_level == "high" and a.needs_review
