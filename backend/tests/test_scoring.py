from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from cit.appsettings import ScoringWeights
from cit.scoring.token_v1 import SecurityInput, TokenInputs, score

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)
W = ScoringWeights()

GOOD_SEC = SecurityInput(
    assessed_at=NOW - timedelta(hours=1), valid_until=NOW + timedelta(hours=23), coverage="complete",
    risk_level="low", hard_excluded=False,
    checks={k: "pass" for k in ("honeypot", "owner_privileges", "holder_concentration", "sell_tax", "open_source",
                                "buy_tax", "transfer_pausable", "blacklist", "mintable", "proxy",
                                "deployer_history", "lp_lock")},
)

GOOD = TokenInputs(
    token_id=1, chain="bsc", as_of=NOW, pool_created_at=NOW - timedelta(days=2),
    market_observed_at=NOW - timedelta(minutes=5), liquidity_usd=Decimal(300_000),
    volume_h24_usd=Decimal(400_000), buys_h24=700, sells_h24=500, price_change_h24=Decimal(12),
    fdv_usd=Decimal(2_000_000), pool_count=3, sources_24h=("dexscreener", "geckoterminal"),
    link_types=("telegram", "twitter", "website"), security=GOOD_SEC,
)

UNKNOWN = TokenInputs(
    token_id=2, chain="bsc", as_of=NOW, pool_created_at=None, market_observed_at=None, liquidity_usd=None,
    volume_h24_usd=None, buys_h24=None, sells_h24=None, price_change_h24=None, fdv_usd=None, pool_count=1,
    sources_24h=(), link_types=(), security=None,
)


def test_strong_token_scores_high_but_social_capped_until_phase4():
    r = score(GOOD, W)
    c = r.components
    assert c["market_structure"]["score"] == pytest.approx(25)
    assert c["liquidity"]["score"] == pytest.approx(25)
    assert c["security"]["score"] == pytest.approx(25)
    assert c["data_quality"]["score"] == pytest.approx(10)
    # Mentions are not collected yet: half of the social category is unreachable and listed as missing.
    assert c["social"]["score"] == pytest.approx(7.5)
    assert any("independent_mentions" in m for m in r.missing_data)
    assert r.total == pytest.approx(92.5) and r.risk_flags == []


def test_unknown_inputs_earn_nothing():
    r = score(UNKNOWN, W)
    c = r.components
    assert c["market_structure"]["score"] == 0
    assert c["security"]["score"] == 0 and c["security"]["missing"]
    assert c["social"]["score"] == 0
    assert c["data_quality"]["score"] == 0
    # Only the pool-count item (always known) contributes.
    assert c["liquidity"]["score"] == pytest.approx(25 * 0.15 * 0.5, abs=0.01)
    assert len(r.missing_data) >= 8


def test_unknown_security_checks_score_zero_not_full():
    sec = replace(GOOD_SEC, coverage="partial", checks={"honeypot": "pass"})
    r = score(replace(GOOD, security=sec), W)
    assert r.components["security"]["score"] == pytest.approx(25 * 0.20)
    assert any(m.startswith("owner_privileges") for m in r.components["security"]["missing"])


def test_hard_exclusion_and_stale_security():
    excl = score(replace(GOOD, security=replace(GOOD_SEC, hard_excluded=True, risk_level="critical")), W)
    assert excl.components["security"]["score"] == 0
    assert "hard_excluded" in excl.risk_flags and "security_critical" in excl.risk_flags
    stale = score(replace(GOOD, security=replace(GOOD_SEC, valid_until=NOW - timedelta(minutes=1))), W)
    assert stale.components["security"]["score"] == 0 and "security_stale" in stale.risk_flags
    assert stale.components["data_quality"]["score"] < 10


def test_red_flags():
    r = score(replace(GOOD, volume_h24_usd=Decimal(5_000_000), price_change_h24=Decimal(-85),
                      buys_h24=950, sells_h24=50), W)
    assert {"possible_wash_trading", "price_collapse_24h", "one_sided_flow"} <= set(r.risk_flags)


def test_weights_are_configurable_and_validated():
    w = ScoringWeights(version="custom", market_structure=40, liquidity=20, security=20, social=10, data_quality=10)
    r = score(GOOD, w)
    assert r.components["market_structure"]["max"] == 40 and r.scoring_version == "custom"
    assert r.components["market_structure"]["score"] == pytest.approx(40)
    with pytest.raises(ValidationError):
        ScoringWeights(market_structure=50)


def test_deterministic_and_reproducible():
    a, b = score(GOOD, W), score(replace(GOOD, as_of=NOW + timedelta(seconds=1)), W)
    assert a.inputs_hash == b.inputs_hash  # evaluation time is not an input
    assert score(GOOD, W).total == a.total
    assert score(replace(GOOD, liquidity_usd=Decimal(1)), W).inputs_hash != a.inputs_hash
    assert a.data_cutoff_at == GOOD.market_observed_at
