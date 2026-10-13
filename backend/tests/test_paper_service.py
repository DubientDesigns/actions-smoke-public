"""Paper trading service against real Postgres: delay-only fills, expiry/missed, partial sells,
untradeable marking, rule exits, strategies (append-only, reproducible), vesting, equity marks."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import psycopg
import pytest

from cit.paper import service as paper
from cit.paper.strategy import StrategyRules, evaluate_entry, inputs_hash

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
s = timedelta(seconds=1)


def add_market(conn, address="0x" + "a" * 40):
    tid = conn.execute("insert into tokens (chain_id, address, symbol, earliest_pool_created_at) "
                       "values (1, %s, 'PAPR', %s) returning id", (address, T0 - timedelta(hours=5))).fetchone()[0]
    pid = conn.execute("insert into pools (chain_id, address, base_token_id, pool_created_at) "
                       "values (1, %s, %s, %s) returning id", ("0x" + address[-6:] * 6 + "beef", tid,
                                                               T0 - timedelta(hours=5))).fetchone()[0]
    return tid, pid


def snap(conn, tid, pid, at, price, liq=1_000_000):
    sid = conn.execute("insert into market_snapshots (pool_id, token_id, source_id, observed_at, price_usd, "
                       "liquidity_usd) values (%s, %s, 1, %s, %s, %s) returning id",
                       (pid, tid, at, price, liq)).fetchone()[0]
    conn.execute("""
        insert into pool_latest (pool_id, token_id, snapshot_id, source_id, observed_at, price_usd, liquidity_usd)
        values (%s, %s, %s, 1, %s, %s, %s)
        on conflict (pool_id) do update set observed_at = excluded.observed_at, price_usd = excluded.price_usd,
          liquidity_usd = excluded.liquidity_usd, snapshot_id = excluded.snapshot_id
    """, (pid, tid, sid, at, price, liq))
    return sid


def add_portfolio(conn, strategy_id=None, delay=60):
    return conn.execute("""
        insert into paper_portfolios (name, starting_capital, starting_capital_usd, fx_sgd_per_usd, strategy_id,
          execution_delay_seconds)
        values ('test', 13000, 10000, 1.30, %s, %s) returning id
    """, (strategy_id, delay)).fetchone()[0]


def add_strategy(conn, rules=None, version=1):
    rules = rules or StrategyRules().model_dump()
    return conn.execute("insert into strategy_definitions (slug, version, name, rules, is_active) "
                        "values ('t', %s, 't', %s, true) returning id", (version, json.dumps(rules))).fetchone()[0]


async def run(engine, fn, *args):
    async with engine.begin() as conn:
        return await fn(conn, *args)


async def place(engine, **kw):
    async with engine.begin() as conn:
        return await paper.place_order(conn, **kw)


def order(conn, oid):
    return conn.execute("select status, reject_reason, position_id from paper_orders where id = %s",
                        (oid,)).fetchone()


async def test_fill_uses_first_price_after_delay_never_before(engine, clean_db):
    tid, pid = add_market(clean_db)
    pf = add_portfolio(clean_db)
    snap(clean_db, tid, pid, T0, 1)          # at signal time: must NOT be used
    snap(clean_db, tid, pid, T0 + 30 * s, 1)  # inside the delay: must NOT be used
    oid = await place(engine, portfolio_id=pf, side="buy", signal_at=T0, origin="manual", token_id=tid,
                      notional_usd=D(1000))
    assert (await run(engine, paper.fill_pending_orders, T0 + 59 * s))["filled"] == 0  # not due yet
    assert (await run(engine, paper.fill_pending_orders, T0 + 70 * s))["waiting"] == 1  # due, no price yet
    snap(clean_db, tid, pid, T0 + 90 * s, 2)
    snap(clean_db, tid, pid, T0 + 120 * s, 3)
    assert (await run(engine, paper.fill_pending_orders, T0 + 200 * s))["filled"] == 1
    f = clean_db.execute("select price_observed_at, reference_price_usd, executed_price_usd, notional_usd "
                         "from paper_fills").fetchone()
    assert f[0] == T0 + 90 * s and f[1] == 2 and f[2] > 2 and f[3] == 1000
    assert order(clean_db, oid)[0] == "filled"
    cash = clean_db.execute("select cash_usd from v_paper_cash where portfolio_id = %s", (pf,)).fetchone()[0]
    assert cash == 9000

    # The database itself rejects a fill priced before earliest_fill_at.
    with pytest.raises(psycopg.errors.CheckViolation, match="look-ahead"):
        clean_db.execute("insert into paper_fills (order_id, price_observed_at, reference_price_usd, "
                         "executed_price_usd, quantity) values (%s, %s, 1, 1, 1)", (oid, T0))


async def test_expired_strategy_order_is_recorded_as_missed(engine, clean_db):
    tid, _ = add_market(clean_db)
    sid = add_strategy(clean_db)
    pf = add_portfolio(clean_db, strategy_id=sid)
    ev = clean_db.execute("insert into strategy_evaluations (strategy_id, token_id, data_cutoff_at, decision, "
                          "inputs, inputs_hash) values (%s, %s, %s, 'enter', '{\"a\": 1}', 'h') returning id",
                          (sid, tid, T0)).fetchone()[0]
    oid = await place(engine, portfolio_id=pf, side="buy", signal_at=T0, origin="strategy", token_id=tid,
                      notional_usd=D(200), evaluation_id=ev)
    assert (await run(engine, paper.fill_pending_orders, T0 + timedelta(minutes=10)))["waiting"] == 1
    assert (await run(engine, paper.fill_pending_orders, T0 + timedelta(minutes=40)))["expired"] == 1
    assert order(clean_db, oid)[0] == "expired"
    missed = clean_db.execute("select decision, reasons, inputs_hash from strategy_evaluations "
                              "where decision = 'missed'").fetchall()
    assert len(missed) == 1 and missed[0][2] == "h" and "missed" in missed[0][1][0]


async def test_buy_rejected_without_cash_or_liquidity(engine, clean_db):
    tid, pid = add_market(clean_db)
    pf = add_portfolio(clean_db)
    snap(clean_db, tid, pid, T0 + 61 * s, 1, liq=5_000)
    illiquid = await place(engine, portfolio_id=pf, side="buy", signal_at=T0, origin="manual", token_id=tid,
                           notional_usd=D(10))
    too_big = await place(engine, portfolio_id=pf, side="buy", signal_at=T0, origin="manual", token_id=tid,
                          notional_usd=D(20_000))
    await run(engine, paper.fill_pending_orders, T0 + 120 * s)
    assert order(clean_db, illiquid)[:2] == ("rejected", "liquidity $5,000 below minimum $10,000")
    assert order(clean_db, too_big)[:2] == ("rejected", "insufficient paper cash")


async def test_partial_sell_realised_pnl_and_untradeable(engine, clean_db):
    tid, pid = add_market(clean_db)
    pf = add_portfolio(clean_db)
    snap(clean_db, tid, pid, T0 + 61 * s, 1, liq=500_000)
    buy = await place(engine, portfolio_id=pf, side="buy", signal_at=T0, origin="manual", token_id=tid,
                      notional_usd=D(5000))
    await run(engine, paper.fill_pending_orders, T0 + 70 * s)
    pos_id = order(clean_db, buy)[2]
    qty0 = clean_db.execute("select quantity from paper_positions where id = %s", (pos_id,)).fetchone()[0]

    # Liquidity shrinks: a full sell only fills up to 2% of the pool.
    t1 = T0 + timedelta(hours=1)
    snap(clean_db, tid, pid, t1 + 61 * s, 2, liq=100_000)  # cap = $2,000 = 1,000 tokens at $2
    sell = await place(engine, portfolio_id=pf, side="sell", signal_at=t1, origin="manual", token_id=tid,
                       position_id=pos_id, sell_fraction=D(1))
    assert (await run(engine, paper.fill_pending_orders, t1 + 70 * s))["partial"] == 1
    assert order(clean_db, sell)[0] == "partially_filled"
    qty, status, pnl = clean_db.execute("select quantity, status, realised_pnl_usd from paper_positions "
                                        "where id = %s", (pos_id,)).fetchone()
    assert qty == qty0 - 1000 and status == "open" and pnl > 0

    # Pool drains below the minimum: the position is marked untradeable and worth zero, not dropped.
    t2 = T0 + timedelta(hours=2)
    snap(clean_db, tid, pid, t2, 2, liq=3_000)
    await run(engine, paper.mark_positions, t2)
    status, value, why = clean_db.execute("select status, last_value_usd, untradeable_reason from paper_positions "
                                          "where id = %s", (pos_id,)).fetchone()
    assert status == "untradeable" and value == 0 and why == "liquidity below minimum"
    sell2 = await place(engine, portfolio_id=pf, side="sell", signal_at=t2, origin="manual", token_id=tid,
                        position_id=pos_id, sell_fraction=D(1))
    snap(clean_db, tid, pid, t2 + 61 * s, 2, liq=3_000)
    await run(engine, paper.fill_pending_orders, t2 + 70 * s)
    assert order(clean_db, sell2)[0] == "rejected"
    # No price for 72h is also untradeable.
    await run(engine, paper.mark_positions, t2 + timedelta(hours=73))
    assert clean_db.execute("select untradeable_reason from paper_positions where id = %s",
                            (pos_id,)).fetchone()[0] == "no price for 72h"


async def test_stop_loss_signals_at_observation_and_fills_after_delay(engine, clean_db):
    tid, pid = add_market(clean_db)
    pf = add_portfolio(clean_db)
    snap(clean_db, tid, pid, T0 + 61 * s, 1)
    buy = await place(engine, portfolio_id=pf, side="buy", signal_at=T0, origin="manual", token_id=tid,
                      notional_usd=D(1000), note=json.dumps({"stop_loss_pct": 30, "take_profit": None}))
    await run(engine, paper.fill_pending_orders, T0 + 70 * s)
    pos_id = order(clean_db, buy)[2]
    t1 = T0 + timedelta(hours=3)
    snap(clean_db, tid, pid, t1, D("0.6"))  # -40%
    res = await run(engine, paper.evaluate_position_rules, t1 + 10 * s)
    assert res["stop_loss"] == 1
    sig, earliest, typ = clean_db.execute("select signal_at, earliest_fill_at, order_type from paper_orders "
                                          "where side = 'sell'").fetchone()
    assert sig == t1 and earliest == t1 + 60 * s and typ == "stop_loss"
    # Not re-triggered while the sell is pending.
    assert (await run(engine, paper.evaluate_position_rules, t1 + 20 * s))["stop_loss"] == 0
    snap(clean_db, tid, pid, t1 + 90 * s, D("0.5"))  # fills at the later, worse price
    await run(engine, paper.fill_pending_orders, t1 + 100 * s)
    status, pnl = clean_db.execute("select status, realised_pnl_usd from paper_positions "
                                        "where id = %s", (pos_id,)).fetchone()
    assert status == "closed" and pnl < -490
    assert clean_db.execute("select category, severity, status from alerts").fetchone() == (
        "paper_rule", "low", "deferred")


async def test_take_profit_legs_fire_in_order(engine, clean_db):
    tid, pid = add_market(clean_db)
    pf = add_portfolio(clean_db)
    snap(clean_db, tid, pid, T0 + 61 * s, 1)
    tp = [{"gain_pct": 100, "sell_pct": 50}, {"gain_pct": 300, "sell_pct": 100}]
    buy = await place(engine, portfolio_id=pf, side="buy", signal_at=T0, origin="manual", token_id=tid,
                      notional_usd=D(1000), note=json.dumps({"stop_loss_pct": None, "take_profit": tp}))
    await run(engine, paper.fill_pending_orders, T0 + 70 * s)
    pos_id = order(clean_db, buy)[2]
    t1 = T0 + timedelta(hours=1)
    snap(clean_db, tid, pid, t1, 5)  # +400%: only the first leg fires this round
    assert (await run(engine, paper.evaluate_position_rules, t1))["take_profit"] == 1
    assert clean_db.execute("select sell_fraction from paper_orders where side = 'sell'").fetchone()[0] == D("0.5")
    snap(clean_db, tid, pid, t1 + 61 * s, 5)
    await run(engine, paper.fill_pending_orders, t1 + 70 * s)
    assert (await run(engine, paper.evaluate_position_rules, t1 + 80 * s))["take_profit"] == 1
    assert clean_db.execute("select tp_done from paper_positions where id = %s", (pos_id,)).fetchone()[0] == [0, 1]


def test_strategy_versions_immutable_and_evaluations_append_only(clean_db):
    sid = add_strategy(clean_db)
    clean_db.execute("update strategy_definitions set is_active = false where id = %s", (sid,))  # allowed
    with pytest.raises(psycopg.errors.CheckViolation, match="immutable"):
        clean_db.execute("update strategy_definitions set rules = '{}' where id = %s", (sid,))
    ev = clean_db.execute("insert into strategy_evaluations (strategy_id, data_cutoff_at, decision, inputs, "
                          "inputs_hash) values (%s, now(), 'reject', '{}', 'h') returning id", (sid,)).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
        clean_db.execute("update strategy_evaluations set decision = 'enter' where id = %s", (ev,))
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
        clean_db.execute("delete from strategy_evaluations where id = %s", (ev,))


def score_token(conn, tid, total, coverage="complete", risk="low", at=None):
    at = at or T0
    conn.execute("insert into security_assessments (token_id, source_id, assessed_at, valid_until, coverage, "
                 "risk_level, ruleset_version) values (%s, 1, %s, %s, %s, %s, 'test')",
                 (tid, at, at + timedelta(days=1), coverage, risk))
    conn.execute("insert into opportunity_scores (token_id, scorecard, scoring_version, scored_at, data_cutoff_at, "
                 "total, components, inputs_hash) values (%s, 'token', 'test', %s, %s, %s, '{}', 'x')",
                 (tid, at, at, total))


async def test_strategy_records_every_decision_reproducibly(engine, clean_db):
    sid = add_strategy(clean_db)
    clean_db.execute("update strategy_definitions set created_at = %s", (T0 - timedelta(hours=1),))
    pf = add_portfolio(clean_db, strategy_id=sid)
    good, gp = add_market(clean_db)
    weak, wp = add_market(clean_db, "0x" + "b" * 40)
    unk, up = add_market(clean_db, "0x" + "c" * 40)
    for t, p in ((good, gp), (weak, wp), (unk, up)):
        snap(clean_db, t, p, T0, 1, liq=100_000)
    score_token(clean_db, good, 82)
    score_token(clean_db, weak, 40)
    score_token(clean_db, unk, 90, coverage="partial", risk="unknown")
    now = T0 + timedelta(minutes=5)
    res = await run(engine, paper.evaluate_strategies, now)
    assert res == {"evaluated": 3, "entered": 1}
    rows = clean_db.execute("select token_id, decision, reasons, inputs, inputs_hash from strategy_evaluations "
                            "order by token_id").fetchall()
    assert [r[1] for r in rows] == ["enter", "reject", "reject"]
    rules = StrategyRules.model_validate(clean_db.execute("select rules from strategy_definitions").fetchone()[0])
    for _, decision, reasons, inputs, h in rows:  # replaying stored inputs reproduces each decision
        assert evaluate_entry(rules, inputs) == (decision, reasons) and inputs_hash(inputs) == h
    o = clean_db.execute("select origin, signal_at, earliest_fill_at, requested_notional_usd from paper_orders "
                         "where portfolio_id = %s", (pf,)).fetchone()
    assert o == ("strategy", now, now + 60 * s, 200)
    # Same scores are not re-evaluated; a new stored score is.
    assert (await run(engine, paper.evaluate_strategies, now + s))["evaluated"] == 0
    score_token(clean_db, weak, 45, at=T0 + timedelta(minutes=10))
    assert (await run(engine, paper.evaluate_strategies, now + timedelta(minutes=15)))["evaluated"] == 1

    # Fill + rules from the strategy version; equity marks and performance view.
    snap(clean_db, good, gp, now + 61 * s, 1, liq=100_000)
    await run(engine, paper.fill_pending_orders, now + 70 * s)
    sl, tp = clean_db.execute("select stop_loss_pct, take_profit from paper_positions").fetchone()
    assert sl == 30 and tp[0] == {"gain_pct": 100.0, "sell_pct": 50.0}
    await run(engine, paper.mark_positions, now + 80 * s)
    assert await run(engine, paper.record_equity_marks, now + 80 * s) == 1
    perf = clean_db.execute("select equity_usd, return_pct, evaluations, evaluations_enter, evaluations_reject, "
                            "equity_marks, max_drawdown_pct from v_paper_performance where portfolio_id = %s",
                            (pf,)).fetchone()
    assert perf[0] < 10_000 and perf[1] < 0  # marked at liquidation value: fees + impact both ways
    assert perf[2:6] == (4, 1, 3, 1) and perf[6] == 0


async def test_presale_allocation_vests_and_is_locked(engine, clean_db):
    tid, pid = add_market(clean_db)
    pf = add_portfolio(clean_db)
    tge = T0 + timedelta(days=10)
    pre = clean_db.execute("""
        insert into presales (slug, project_name, status, sale_price_usd, tge_at, vesting_terms, token_id, created_by)
        values ('p', 'P', 'live', 0.01, %s, %s, %s, 'test') returning id
    """, (tge, json.dumps({"tge_unlock_pct": 25, "cliff_months": 0, "vesting_months": 3}), tid)).fetchone()[0]
    oid = await place(engine, portfolio_id=pf, side="buy", signal_at=T0, origin="manual", presale_id=pre,
                      notional_usd=D(500), order_type="presale_allocation")
    await run(engine, paper.fill_pending_orders, T0 + s)
    pos_id = order(clean_db, oid)[2]
    st, qty, locked = clean_db.execute("select status, quantity, locked_quantity from paper_positions "
                                       "where id = %s", (pos_id,)).fetchone()
    assert st == "vesting" and qty == 50_000 and locked == qty
    # At TGE + 45 days: 25% + 75% * 0.5 = 62.5% unlocked; only the unlocked part has liquid value.
    snap(clean_db, tid, pid, tge + timedelta(days=45), D("0.02"))
    await run(engine, paper.mark_positions, tge + timedelta(days=45))
    st, locked, value = clean_db.execute("select status, locked_quantity, last_value_usd from paper_positions "
                                         "where id = %s", (pos_id,)).fetchone()
    assert st == "vesting" and locked == D(50_000) * D("0.375")
    assert D(0) < value < D(31_250) * D("0.02")
    # A closed/ended sale cannot be joined after the fact.
    clean_db.execute("update presales set status = 'ended'")
    late = await place(engine, portfolio_id=pf, side="buy", signal_at=T0, origin="manual", presale_id=pre,
                       notional_usd=D(100), order_type="presale_allocation")
    await run(engine, paper.fill_pending_orders, T0 + s)
    assert order(clean_db, late)[0] == "rejected"


def test_internal_api_paper_orders(engine, clean_db, monkeypatch):
    from fastapi.testclient import TestClient

    from cit.api import main
    from cit.config import get_settings

    tid, _ = add_market(clean_db)
    user = "11111111-1111-1111-1111-111111111111"
    monkeypatch.setenv("CIT_INTERNAL_API_TOKEN", "secret-token")
    get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        body = {"requested_by": user, "kind": "buy", "token_id": tid, "notional_usd": 250, "stop_loss_pct": 25}
        assert client.post("/v1/paper/orders", json=body).status_code == 401
        h = {"Authorization": "Bearer secret-token"}
        r = client.post("/v1/paper/orders", json=body, headers=h)
        assert r.status_code == 202, r.text
        oid, pf = r.json()["order_id"], r.json()["portfolio_id"]
        owner, cap = clean_db.execute("select owner_id::text, starting_capital_usd from paper_portfolios "
                                      "where id = %s", (pf,)).fetchone()
        assert owner == user and cap == D("7692.31")
        assert client.post("/v1/paper/orders", json={**body, "token_id": 999999}, headers=h).status_code == 404
        assert client.post("/v1/paper/orders", json={**body, "notional_usd": None}, headers=h).status_code == 422
        sell = {"requested_by": user, "kind": "sell", "position_id": 999, "sell_fraction": 0.5}
        assert client.post("/v1/paper/orders", json=sell, headers=h).status_code == 404
        other = "22222222-2222-2222-2222-222222222222"
        assert client.post(f"/v1/paper/orders/{oid}/cancel", json={"requested_by": other}, headers=h).status_code == 404
        r = client.post(f"/v1/paper/orders/{oid}/cancel", json={"requested_by": user}, headers=h)
        assert r.status_code == 200 and order(clean_db, oid)[0] == "cancelled"
        assert clean_db.execute("select count(*) from audit_log where action like 'paper_order%'").fetchone()[0] == 2
    finally:
        get_settings.cache_clear()


async def test_tokens_held_on_paper_stay_tracked(engine, clean_db):
    from cit import appsettings
    from cit.services import discovery

    tid, _ = add_market(clean_db)
    clean_db.execute("update tokens set first_observed_at = now() - interval '90 days', is_excluded = true "
                     "where id = %s", (tid,))
    pf = add_portfolio(clean_db)

    async def tracked():
        async with engine.connect() as conn:
            rows = await discovery.tracked_tokens(conn, appsettings.DiscoverySettings())
        return {r.id for r in rows}

    assert tid not in await tracked()
    clean_db.execute("insert into paper_positions (portfolio_id, token_id, status, quantity) "
                     "values (%s, %s, 'open', 1)",
                     (pf, tid))
    assert tid in await tracked()
