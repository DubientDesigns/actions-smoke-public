"""Paper trading pure models: execution (price impact, fees, caps), vesting, strategy rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from cit.paper.execution import ExecParams, liquidation_value, quote_buy, quote_sell
from cit.paper.strategy import StrategyRules, evaluate_entry, inputs_hash
from cit.paper.vesting import Vesting, unlocked_fraction

P = ExecParams()  # 30 bps fee, 50 bps extra, 2% cap, $10k minimum liquidity


def test_buy_includes_fee_impact_and_extra_slippage():
    q = quote_buy(D(1), D(1_000_000), D(1000), P)
    assert q.ok and q.notional_usd == D(1000) and q.fee_usd == D(3)
    # avg = 1 * (1 + 997/500000) * 1.005
    expected_avg = (1 + D(997) / D(500_000)) * D("1.005")
    assert q.executed_price == expected_avg
    assert q.quantity < D(997)  # never filled at the displayed price
    assert 69 < q.slippage_bps < 71


def test_buy_rejections_never_assume_liquidity():
    assert quote_buy(D(1), D(1_000_000), D(30_000), P).reason.startswith("size")  # > 2% of liquidity
    assert quote_buy(D(1), None, D(100), P).reason == "liquidity unknown"
    assert "below minimum" in quote_buy(D(1), D(5_000), D(10), P).reason
    assert quote_buy(None, D(1_000_000), D(10), P).reason == "no usable price"
    assert quote_buy(D(0), D(1_000_000), D(10), P).reason == "no usable price"


def test_sell_partially_fills_above_the_cap():
    q = quote_sell(D(1), D(100_000), D(5000), P)  # cap = $2,000 at price 1
    assert q.ok and q.quantity == D(2000) and q.unfilled_quantity == D(3000)
    assert q.executed_price < D(1) and q.notional_usd < D(2000)


def test_round_trip_at_unchanged_price_loses_money():
    b = quote_buy(D("0.5"), D(200_000), D(1000), P)
    s = quote_sell(D("0.5"), D(200_000), b.quantity, P)
    assert s.notional_usd < D(1000) * D("0.98")  # two fees + two impacts + extra slippage


def test_liquidation_value_is_conservative():
    full = D(10_000) * D(1)
    v = liquidation_value(D(1), D(100_000), D(10_000), P)  # 10% of the pool: big impact, no cap
    assert D(0) < v < full * D("0.85")
    assert liquidation_value(D(1), D(5_000), D(10), P) == 0  # untradeable
    assert liquidation_value(D(1), None, D(10), P) == 0


T = datetime(2026, 1, 1, tzinfo=UTC)


def test_vesting_schedule():
    v = Vesting.from_terms(T, {"tge_unlock_pct": 20, "cliff_months": 3, "vesting_months": 12, "source": "claimed"})
    assert unlocked_fraction(v, T - timedelta(days=1)) == 0
    assert unlocked_fraction(v, T) == D("0.2")
    assert unlocked_fraction(v, T + timedelta(days=60)) == D("0.2")  # inside the cliff
    assert unlocked_fraction(v, T + timedelta(days=270)) == D("0.6")  # 6 of 12 months vested
    assert unlocked_fraction(v, T + timedelta(days=900)) == 1


def test_unknown_vesting_unlocks_nothing():
    assert unlocked_fraction(Vesting.from_terms(None, {"tge_unlock_pct": 100, "vesting_months": 0}), T) == 0
    assert unlocked_fraction(Vesting.from_terms(T, {"cliff_months": 1}), T + timedelta(days=999)) == 0
    assert unlocked_fraction(Vesting.from_terms(T, None), T + timedelta(days=999)) == 0


GOOD = {
    "score_id": 1, "score_total": 80.0, "risk_level": "low", "hard_excluded": False, "security_coverage": "complete",
    "liquidity_usd": 100_000.0, "token_age_hours": 10.0, "risk_flags": [], "already_held": False,
    "open_positions": 0, "cash_usd": 5000.0,
}


def test_strategy_enters_only_when_every_rule_passes():
    rules = StrategyRules()
    assert evaluate_entry(rules, GOOD) == ("enter", ["all entry rules satisfied"])
    for key, bad in [("score_total", 69.9), ("risk_level", "high"), ("hard_excluded", True),
                     ("security_coverage", "partial"), ("liquidity_usd", 10.0), ("token_age_hours", 100.0),
                     ("risk_flags", ["possible_wash_trading"]), ("already_held", True), ("open_positions", 10),
                     ("cash_usd", 10.0)]:
        decision, reasons = evaluate_entry(rules, {**GOOD, key: bad})
        assert decision == "reject" and reasons, key


def test_unknown_inputs_never_satisfy_a_rule():
    for key in ("score_total", "risk_level", "security_coverage", "liquidity_usd", "token_age_hours"):
        assert evaluate_entry(StrategyRules(), {**GOOD, key: None})[0] == "reject", key


def test_evaluation_is_reproducible():
    rules = StrategyRules.model_validate({"notional_usd": 200, "entry": {"min_score": 75}})
    shuffled = dict(reversed(list(GOOD.items())))
    assert inputs_hash(GOOD) == inputs_hash(shuffled)
    assert evaluate_entry(rules, GOOD) == evaluate_entry(rules, shuffled)
