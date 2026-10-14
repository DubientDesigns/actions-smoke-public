"""Paper trading service: orders, fills, positions, rules, strategies, equity marks.

Timing rules (no look-ahead):
* Every order has `signal_at` (when the information that motivated it became
  available to us) and `earliest_fill_at = signal_at + execution delay`.
* A fill uses the FIRST snapshot observed at/after earliest_fill_at (the DB
  trigger rejects anything earlier). If no snapshot arrives before
  `expires_at`, the order expires and, for strategy orders, a `missed`
  evaluation is recorded.
* Rule exits (stop-loss / take-profit / max hold) use the latest observed
  snapshot as their signal time and are filled under the same delay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cit.alerts.engine import emit
from cit.log import get_logger
from cit.paper.execution import ExecParams, liquidation_value, quote_buy, quote_sell
from cit.paper.strategy import StrategyRules, evaluate_entry, inputs_hash
from cit.paper.vesting import Vesting, unlocked_fraction

log = get_logger(__name__)

DUST = Decimal("1e-12")
STALE_PRICE = timedelta(hours=72)
PRESALE_OPEN = ("upcoming", "live")


class OrderError(ValueError):
    pass


def D(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


@dataclass
class Portfolio:
    id: int
    fee_bps: Decimal
    delay: timedelta
    window: timedelta
    params: ExecParams
    fx: Decimal
    strategy_id: int | None


async def load_portfolio(conn: AsyncConnection, portfolio_id: int) -> Portfolio:
    r = (await conn.execute(text("select * from paper_portfolios where id = :id"), {"id": portfolio_id})).one()
    extra = Decimal(str((r.slippage_model or {}).get("extra_bps", 50)))
    return Portfolio(
        r.id,
        D(r.fee_bps) or Decimal(30),
        timedelta(seconds=r.execution_delay_seconds),
        timedelta(minutes=r.max_fill_window_minutes),
        ExecParams(
            D(r.fee_bps) or Decimal(30),
            extra,
            D(r.max_pool_liquidity_pct) or Decimal(2),
            D(r.min_liquidity_usd) or Decimal(10_000),
        ),
        D(r.fx_sgd_per_usd) or Decimal("1.30"),
        r.strategy_id,
    )


async def ensure_manual_portfolio(conn: AsyncConnection, owner_id: str, sgd_per_usd: Decimal) -> int:
    row = (
        await conn.execute(
            text(
                "select id from paper_portfolios where owner_id = cast(:o as uuid) and strategy_id is null "
                "order by id limit 1"
            ),
            {"o": owner_id},
        )
    ).first()
    if row:
        return row.id
    return (
        await conn.execute(
            text("""
        insert into paper_portfolios (owner_id, name, starting_capital, starting_capital_usd, fx_sgd_per_usd)
        values (cast(:o as uuid), 'My paper portfolio', 10000, round(10000 / :fx, 2), :fx) returning id
    """),
            {"o": owner_id, "fx": sgd_per_usd},
        )
    ).scalar_one()


async def cash_usd(conn: AsyncConnection, portfolio_id: int) -> Decimal:
    return D(
        (
            await conn.execute(text("select cash_usd from v_paper_cash where portfolio_id = :p"), {"p": portfolio_id})
        ).scalar_one()
    ) or Decimal(0)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


async def place_order(
    conn: AsyncConnection,
    *,
    portfolio_id: int,
    side: str,
    signal_at: datetime,
    origin: str,
    token_id: int | None = None,
    presale_id: int | None = None,
    notional_usd: Decimal | None = None,
    sell_fraction: Decimal | None = None,
    position_id: int | None = None,
    order_type: str = "market",
    evaluation_id: int | None = None,
    note: str | None = None,
) -> int:
    pf = await load_portfolio(conn, portfolio_id)
    if side == "buy" and (notional_usd is None or notional_usd <= 0):
        raise OrderError("buy needs a positive notional_usd")
    if side == "sell" and (sell_fraction is None or not (0 < sell_fraction <= 1) or position_id is None):
        raise OrderError("sell needs a position and a sell_fraction in (0, 1]")
    if side == "buy" and order_type == "market" and token_id is None:
        raise OrderError("market buy needs a token")
    earliest = signal_at + (timedelta(0) if order_type == "presale_allocation" else pf.delay)
    return (
        await conn.execute(
            text("""
        insert into paper_orders (portfolio_id, position_id, token_id, presale_id, side, order_type, origin,
          strategy_evaluation_id, signal_at, earliest_fill_at, expires_at, requested_notional_usd, sell_fraction, note)
        values (:pf, :pos, :tok, :pre, :side, :type, :origin, :ev, :sig, :earliest, :exp, :notional, :frac, :note)
        returning id
    """),
            {
                "pf": portfolio_id,
                "pos": position_id,
                "tok": token_id,
                "pre": presale_id,
                "side": side,
                "type": order_type,
                "origin": origin,
                "ev": evaluation_id,
                "sig": signal_at,
                "earliest": earliest,
                "exp": earliest + pf.window,
                "notional": notional_usd,
                "frac": sell_fraction,
                "note": note,
            },
        )
    ).scalar_one()


_FIRST_SNAPSHOT = text("""
-- First observation per pool at/after the earliest fill time, then the deepest of those.
select * from (
  select distinct on (s.pool_id) s.id, s.pool_id, s.observed_at, s.price_usd, s.liquidity_usd
  from market_snapshots s
  where s.token_id = :t and s.observed_at >= :earliest and s.observed_at <= :until and s.price_usd is not null
    and (cast(:pool as bigint) is null or s.pool_id = cast(:pool as bigint))
  order by s.pool_id, s.observed_at
) firsts order by liquidity_usd desc nulls last, observed_at limit 1
""")


async def _reject(conn: AsyncConnection, order_id: int, reason: str, status: str = "rejected") -> None:
    await conn.execute(
        text("update paper_orders set status = :s, reject_reason = :r where id = :id"),
        {"s": status, "r": reason[:500], "id": order_id},
    )


async def _record_missed(conn: AsyncConnection, order: Any, reason: str) -> None:
    if order.origin != "strategy" or order.strategy_evaluation_id is None:
        return
    ev = (
        await conn.execute(
            text("select strategy_id, token_id, inputs, inputs_hash from strategy_evaluations where id = :id"),
            {"id": order.strategy_evaluation_id},
        )
    ).one()
    await conn.execute(
        text("""
        insert into strategy_evaluations (strategy_id, token_id, data_cutoff_at, decision, reasons, inputs, inputs_hash)
        values (:s, :t, :cut, 'missed', cast(:r as jsonb), cast(:i as jsonb), :h)
    """),
        {
            "s": ev.strategy_id,
            "t": ev.token_id,
            "cut": order.earliest_fill_at,
            "r": json.dumps([reason]),
            "i": json.dumps(ev.inputs),
            "h": ev.inputs_hash,
        },
    )


async def _insert_fill(conn: AsyncConnection, order_id: int, snap: Any, q: Any, fx: Decimal) -> None:
    await conn.execute(
        text("""
        insert into paper_fills (order_id, snapshot_id, price_observed_at, reference_price_usd, executed_price_usd,
          quantity, fee_usd, slippage_bps, liquidity_usd, fx_sgd_per_usd, notional_usd)
        values (:o, :s, :obs, :ref, :exe, :qty, :fee, :slip, :liq, :fx, :notional)
    """),
        {
            "o": order_id,
            "s": snap.id if snap is not None else None,
            "obs": snap.observed_at if snap is not None else datetime.now(UTC),
            "ref": q["ref"],
            "exe": q["exe"],
            "qty": q["qty"],
            "fee": q["fee"],
            "slip": q["slip"],
            "liq": q["liq"],
            "fx": fx,
            "notional": q["notional"],
        },
    )


async def fill_pending_orders(conn: AsyncConnection, now: datetime) -> dict[str, int]:
    stats = {"filled": 0, "partial": 0, "rejected": 0, "expired": 0, "waiting": 0}
    orders = (
        await conn.execute(
            text("""
        select * from paper_orders where status = 'pending' and earliest_fill_at <= :now order by earliest_fill_at
        for update skip locked
    """),
            {"now": now},
        )
    ).all()
    for o in orders:
        pf = await load_portfolio(conn, o.portfolio_id)
        if o.order_type == "presale_allocation":
            await _fill_presale(conn, o, pf, stats)
            continue
        pos = None
        if o.side == "sell":
            pos = (
                await conn.execute(
                    text("select * from paper_positions where id = :id for update"), {"id": o.position_id}
                )
            ).one()
        snap = (
            await conn.execute(
                _FIRST_SNAPSHOT,
                {
                    "t": o.token_id,
                    "earliest": o.earliest_fill_at,
                    "until": o.expires_at,
                    "pool": pos.pool_id if pos is not None else None,
                },
            )
        ).first()
        if snap is None:
            if now > o.expires_at:
                reason = "no price observed within the fill window (missed)"
                await _reject(conn, o.id, reason, "expired")
                await _record_missed(conn, o, reason)
                stats["expired"] += 1
            else:
                stats["waiting"] += 1
            continue
        price, liq = D(snap.price_usd), D(snap.liquidity_usd)
        if o.side == "buy":
            notional = D(o.requested_notional_usd) or Decimal(0)
            if notional > await cash_usd(conn, o.portfolio_id):
                await _reject(conn, o.id, "insufficient paper cash")
                stats["rejected"] += 1
                continue
            q = quote_buy(price, liq, notional, pf.params)
            if not q.ok:
                await _reject(conn, o.id, q.reason or "rejected")
                await _record_missed(conn, o, q.reason or "rejected")
                stats["rejected"] += 1
                continue
            await _insert_fill(
                conn,
                o.id,
                snap,
                {
                    "ref": price,
                    "exe": q.executed_price,
                    "qty": q.quantity,
                    "fee": q.fee_usd,
                    "slip": q.slippage_bps,
                    "liq": liq,
                    "notional": q.notional_usd,
                },
                pf.fx,
            )
            sl, tp, ev_id = await _exit_rules_for(conn, o)
            pos_id = (
                await conn.execute(
                    text("""
                insert into paper_positions (portfolio_id, token_id, status, opened_at, quantity, cost_basis_usd,
                  entry_price_usd, pool_id, stop_loss_pct, take_profit, strategy_evaluation_id, last_price_usd,
                  last_marked_at, max_favourable_pct, max_adverse_pct)
                values (:pf, :t, 'open', :at, :qty, :cost, :entry, :pool, :sl,
                        cast(:tp as jsonb), :ev, :price, :at, 0, 0)
                returning id
            """),
                    {
                        "pf": o.portfolio_id,
                        "t": o.token_id,
                        "at": snap.observed_at,
                        "qty": q.quantity,
                        "cost": q.notional_usd,
                        "entry": q.notional_usd / q.quantity if q.quantity else None,
                        "pool": snap.pool_id,
                        "sl": sl,
                        "tp": json.dumps(tp) if tp is not None else None,
                        "ev": ev_id,
                        "price": price,
                    },
                )
            ).scalar_one()
            await conn.execute(
                text("update paper_orders set status = 'filled', position_id = :p where id = :id"),
                {"p": pos_id, "id": o.id},
            )
            stats["filled"] += 1
        else:
            assert pos is not None
            sellable = D(pos.quantity) - D(pos.locked_quantity or 0)
            qty = (sellable * D(o.sell_fraction)).quantize(Decimal("1e-18"))
            q = quote_sell(price, liq, qty, pf.params)
            if not q.ok:
                await _reject(conn, o.id, q.reason or "rejected")
                if "liquidity" in (q.reason or "") or "price" in (q.reason or ""):
                    await conn.execute(
                        text("""
                        update paper_positions set status = 'untradeable', untradeable_reason = :r where id = :id
                    """),
                        {"r": q.reason, "id": pos.id},
                    )
                stats["rejected"] += 1
                continue
            await _insert_fill(
                conn,
                o.id,
                snap,
                {
                    "ref": price,
                    "exe": q.executed_price,
                    "qty": q.quantity,
                    "fee": q.fee_usd,
                    "slip": q.slippage_bps,
                    "liq": liq,
                    "notional": q.notional_usd,
                },
                pf.fx,
            )
            basis_sold = D(pos.cost_basis_usd) * q.quantity / D(pos.quantity)
            remaining = D(pos.quantity) - q.quantity
            closed = remaining <= DUST
            await conn.execute(
                text("""
                update paper_positions set quantity = :rem, cost_basis_usd = cost_basis_usd - :basis,
                  realised_pnl_usd = realised_pnl_usd + :pnl,
                  status = case when :closed then 'closed' else status end,
                  closed_at = case when :closed then :at else closed_at end
                where id = :id
            """),
                {
                    "rem": max(remaining, Decimal(0)),
                    "basis": basis_sold,
                    "pnl": q.notional_usd - basis_sold,
                    "closed": closed,
                    "at": snap.observed_at,
                    "id": pos.id,
                },
            )
            partial = q.unfilled_quantity > DUST
            await conn.execute(
                text("update paper_orders set status = :s where id = :id"),
                {"s": "partially_filled" if partial else "filled", "id": o.id},
            )
            stats["partial" if partial else "filled"] += 1
    return stats


async def _exit_rules_for(conn: AsyncConnection, o: Any) -> tuple[Any, Any, int | None]:
    """Stop-loss / take-profit attached to a buy: from the strategy, or from the manual order note JSON."""
    if o.origin == "strategy" and o.strategy_evaluation_id is not None:
        rules = (
            await conn.execute(
                text("""
            select sd.rules from strategy_evaluations e join strategy_definitions sd on sd.id = e.strategy_id
            where e.id = :id
        """),
                {"id": o.strategy_evaluation_id},
            )
        ).scalar_one()
        r = StrategyRules.model_validate(rules)
        return r.exits.stop_loss_pct, [t.model_dump() for t in r.exits.take_profit], o.strategy_evaluation_id
    try:
        meta = json.loads(o.note) if o.note and o.note.startswith("{") else {}
    except ValueError:
        meta = {}
    return meta.get("stop_loss_pct"), meta.get("take_profit"), None


async def _fill_presale(conn: AsyncConnection, o: Any, pf: Portfolio, stats: dict[str, int]) -> None:
    pre = (await conn.execute(text("select * from presales where id = :id"), {"id": o.presale_id})).one()
    price = D(pre.sale_price_usd)
    notional = D(o.requested_notional_usd) or Decimal(0)
    if pre.status not in PRESALE_OPEN:
        # Only a sale that was open when the order was signalled can be joined (no hindsight entries).
        await _reject(conn, o.id, f"presale status is {pre.status}; allocations need an open sale")
        stats["rejected"] += 1
        return
    if price is None or price <= 0:
        await _reject(conn, o.id, "presale has no sale price; cannot size the allocation")
        stats["rejected"] += 1
        return
    if notional > await cash_usd(conn, o.portfolio_id):
        await _reject(conn, o.id, "insufficient paper cash")
        stats["rejected"] += 1
        return
    qty = notional / price
    await _insert_fill(
        conn,
        o.id,
        None,
        {"ref": price, "exe": price, "qty": qty, "fee": Decimal(0), "slip": 0, "liq": None, "notional": notional},
        pf.fx,
    )
    pos_id = (
        await conn.execute(
            text("""
        insert into paper_positions (portfolio_id, presale_id, token_id, status, opened_at, quantity,
          locked_quantity, cost_basis_usd, entry_price_usd, vesting_schedule, max_favourable_pct, max_adverse_pct)
        values (:pf, :pre, :tok, 'vesting', :at, :qty, :qty, :cost, :price, cast(:v as jsonb), 0, 0) returning id
    """),
            {
                "pf": o.portfolio_id,
                "pre": pre.id,
                "tok": pre.token_id,
                "at": o.signal_at,
                "qty": qty,
                "cost": notional,
                "price": price,
                "v": json.dumps(
                    {"tge_at": pre.tge_at.isoformat() if pre.tge_at else None, **(pre.vesting_terms or {})}
                ),
            },
        )
    ).scalar_one()
    await conn.execute(
        text("update paper_orders set status = 'filled', position_id = :p where id = :id"), {"p": pos_id, "id": o.id}
    )
    stats["filled"] += 1


# ---------------------------------------------------------------------------
# Marking, rules, strategies, equity
# ---------------------------------------------------------------------------

_LATEST = text("""
select s.observed_at, s.price_usd, s.liquidity_usd from market_snapshots s
where s.pool_id = :pool and s.price_usd is not null order by s.observed_at desc limit 1
""")


async def mark_positions(conn: AsyncConnection, now: datetime) -> dict[str, int]:
    stats = {"marked": 0, "untradeable": 0}
    rows = (
        await conn.execute(
            text("""
        select pos.*, pr.token_id as presale_token_id from paper_positions pos
        left join presales pr on pr.id = pos.presale_id
        where pos.status in ('open', 'vesting', 'untradeable')
    """)
        )
    ).all()
    for pos in rows:
        pf = await load_portfolio(conn, pos.portfolio_id)
        token_id = pos.token_id or pos.presale_token_id
        pool_id = pos.pool_id
        if pool_id is None and token_id is not None:
            pool_id = (
                await conn.execute(
                    text(
                        "select pool_id from pool_latest where token_id = :t "
                        "order by liquidity_usd desc nulls last limit 1"
                    ),
                    {"t": token_id},
                )
            ).scalar()
        locked = D(pos.locked_quantity or 0) or Decimal(0)
        status = pos.status
        if pos.presale_id is not None:
            v = pos.vesting_schedule or {}
            tge = datetime.fromisoformat(v["tge_at"]) if v.get("tge_at") else None
            frac = unlocked_fraction(Vesting.from_terms(tge, v), now)
            locked = (D(pos.quantity) * (1 - frac)).quantize(Decimal("1e-18"))
            status = "open" if frac >= 1 else "vesting"
        latest = (await conn.execute(_LATEST, {"pool": pool_id})).first() if pool_id else None
        price = D(latest.price_usd) if latest else None
        liq = D(latest.liquidity_usd) if latest else None
        stale = latest is None or now - latest.observed_at > STALE_PRICE
        sellable = D(pos.quantity) - locked
        value = Decimal(0) if stale else liquidation_value(price, liq, sellable, pf.params)
        if status != "vesting" and (stale or liq is None or liq < pf.params.min_liquidity_usd):
            status = "untradeable"
            stats["untradeable"] += 1
        elif pos.status == "untradeable" and not stale and liq is not None and liq >= pf.params.min_liquidity_usd:
            status = "open"
        extremes = None
        if pool_id and pos.entry_price_usd and pos.opened_at:
            extremes = (
                await conn.execute(
                    text("""
                select max(price_usd) as hi, min(price_usd) as lo from market_snapshots
                where pool_id = :p and observed_at >= :since and price_usd is not null
            """),
                    {"p": pool_id, "since": pos.opened_at},
                )
            ).one()
        entry = D(pos.entry_price_usd)
        mfe = ((D(extremes.hi) / entry - 1) * 100) if extremes and extremes.hi and entry else D(pos.max_favourable_pct)
        mae = ((D(extremes.lo) / entry - 1) * 100) if extremes and extremes.lo and entry else D(pos.max_adverse_pct)
        await conn.execute(
            text("""
            update paper_positions set last_price_usd = :price, last_value_usd = :value, last_marked_at = :now,
              locked_quantity = :locked, status = :status, pool_id = coalesce(pool_id, :pool),
              token_id = coalesce(token_id, :tok),
              max_favourable_pct = greatest(coalesce(max_favourable_pct, 0), coalesce(:mfe, 0)),
              max_adverse_pct = least(coalesce(max_adverse_pct, 0), coalesce(:mae, 0)),
              untradeable_reason = case when :status = 'untradeable'
                then coalesce(:why, untradeable_reason) else null end
            where id = :id
        """),
            {
                "price": price,
                "value": value,
                "now": now,
                "locked": locked,
                "status": status,
                "pool": pool_id,
                "tok": token_id,
                "mfe": mfe,
                "mae": mae,
                "id": pos.id,
                "why": "no price for 72h" if stale else "liquidity below minimum" if status == "untradeable" else None,
            },
        )
        stats["marked"] += 1
    return stats


async def evaluate_position_rules(conn: AsyncConnection, now: datetime) -> dict[str, int]:
    """Stop-loss, take-profit and max-hold: create sell orders signalled at the observation time."""
    stats = {"stop_loss": 0, "take_profit": 0, "max_hold": 0}
    rows = (
        await conn.execute(
            text("""
        select pos.*, pf.strategy_id, sd.rules from paper_positions pos
        join paper_portfolios pf on pf.id = pos.portfolio_id
        left join strategy_definitions sd on sd.id = pf.strategy_id
        where pos.status = 'open' and pos.entry_price_usd is not null and pos.pool_id is not null
          and not exists (select 1 from paper_orders o where o.position_id = pos.id and o.side = 'sell'
                          and o.status = 'pending')
    """)
        )
    ).all()
    for pos in rows:
        latest = (await conn.execute(_LATEST, {"pool": pos.pool_id})).first()
        if latest is None or latest.observed_at < pos.opened_at:
            continue
        change = (D(latest.price_usd) / D(pos.entry_price_usd) - 1) * 100
        reason, fraction, kind = None, None, None
        done = list(pos.tp_done or [])
        if pos.stop_loss_pct is not None and change <= -D(pos.stop_loss_pct):
            reason, fraction, kind = f"stop-loss: {change:.1f}% <= -{pos.stop_loss_pct}%", Decimal(1), "stop_loss"
        else:
            for i, tp in enumerate(pos.take_profit or []):
                if i in done:
                    continue
                if change >= Decimal(str(tp["gain_pct"])):
                    reason = f"take-profit {i + 1}: {change:.1f}% >= {tp['gain_pct']}%"
                    fraction, kind = Decimal(str(tp["sell_pct"])) / 100, "take_profit"
                    done.append(i)
                break
        if reason is None and pos.rules:
            max_hold = (pos.rules.get("exits") or {}).get("max_hold_hours")
            if max_hold and now - pos.opened_at >= timedelta(hours=float(max_hold)):
                reason, fraction, kind = f"max hold {max_hold}h reached", Decimal(1), "max_hold"
        if reason is None:
            continue
        order_type = "stop_loss" if kind == "stop_loss" else "take_profit" if kind == "take_profit" else "market"
        await place_order(
            conn,
            portfolio_id=pos.portfolio_id,
            side="sell",
            signal_at=latest.observed_at,
            origin="strategy" if pos.strategy_id else "manual",
            token_id=pos.token_id,
            position_id=pos.id,
            sell_fraction=min(fraction, Decimal(1)),
            order_type=order_type,
            note=reason,
        )
        if kind == "take_profit":
            await conn.execute(
                text("update paper_positions set tp_done = cast(:d as jsonb) where id = :id"),
                {"d": json.dumps(done), "id": pos.id},
            )
        await emit(
            conn,
            category="paper_rule",
            severity="low",
            dedup_key=f"paper:{pos.id}:{kind}:{len(done)}",
            cooldown_minutes=60 * 24 * 365,
            token_id=pos.token_id,
            title=f"Paper rule triggered: {reason}",
            body=f"Paper position #{pos.id}; sell order placed.",
        )
        stats[kind] += 1
    return stats


_STRATEGY_CANDIDATES = text("""
-- Each new stored score (material change) of a token is evaluated once per strategy version.
select o.token_id, o.score_total, o.risk_level, o.hard_excluded, o.security_coverage, o.liquidity_usd,
       o.earliest_pool_created_at, o.score_risk_flags, o.scored_at, o.market_observed_at,
       sl.score_id, sl.data_cutoff_at
from v_token_overview o
join v_score_latest sl on sl.token_id = o.token_id
where o.scored_at >= :since
  and not exists (select 1 from strategy_evaluations e where e.strategy_id = :sid and e.token_id = o.token_id
                  and e.inputs->>'score_id' = sl.score_id::text)
order by o.scored_at
limit 200
""")


async def evaluate_strategies(conn: AsyncConnection, now: datetime) -> dict[str, int]:
    """Evaluate each newly scored token once per active strategy version; record every decision."""
    stats = {"evaluated": 0, "entered": 0}
    strategies = (
        await conn.execute(
            text("""
        select sd.*, pf.id as portfolio_id from strategy_definitions sd
        join paper_portfolios pf on pf.strategy_id = sd.id and pf.is_active
        where sd.is_active
    """)
        )
    ).all()
    for sd in strategies:
        rules = StrategyRules.model_validate(sd.rules)
        cash = await cash_usd(conn, sd.portfolio_id)
        open_n = (
            await conn.execute(
                text(
                    "select count(*) from paper_positions where portfolio_id = :p and status in ('open', 'untradeable')"
                ),
                {"p": sd.portfolio_id},
            )
        ).scalar_one()
        held = {
            r[0]
            for r in (
                await conn.execute(
                    text("select token_id from paper_positions where portfolio_id = :p and status <> 'closed'"),
                    {"p": sd.portfolio_id},
                )
            ).all()
        }
        for c in (await conn.execute(_STRATEGY_CANDIDATES, {"since": sd.created_at, "sid": sd.id})).all():
            age = ((now - c.earliest_pool_created_at).total_seconds() / 3600) if c.earliest_pool_created_at else None
            inputs = {
                "score_id": c.score_id,
                "score_total": float(c.score_total) if c.score_total is not None else None,
                "risk_level": c.risk_level,
                "hard_excluded": c.hard_excluded,
                "security_coverage": c.security_coverage,
                "liquidity_usd": float(c.liquidity_usd) if c.liquidity_usd is not None else None,
                "token_age_hours": round(age, 2) if age is not None else None,
                "risk_flags": list(c.score_risk_flags or []),
                "already_held": c.token_id in held,
                "open_positions": open_n,
                "cash_usd": float(cash),
            }
            decision, reasons = evaluate_entry(rules, inputs)
            ev_id = (
                await conn.execute(
                    text("""
                insert into strategy_evaluations (strategy_id, token_id, evaluated_at, data_cutoff_at, decision,
                  reasons, inputs, inputs_hash)
                values (:s, :t, :now, :cut, :d, cast(:r as jsonb), cast(:i as jsonb), :h) returning id
            """),
                    {
                        "s": sd.id,
                        "t": c.token_id,
                        "now": now,
                        "cut": max(x for x in (c.data_cutoff_at, c.market_observed_at, c.scored_at) if x is not None),
                        "d": decision,
                        "r": json.dumps(reasons),
                        "i": json.dumps(inputs),
                        "h": inputs_hash(inputs),
                    },
                )
            ).scalar_one()
            stats["evaluated"] += 1
            if decision == "enter":
                await place_order(
                    conn,
                    portfolio_id=sd.portfolio_id,
                    side="buy",
                    signal_at=now,
                    origin="strategy",
                    token_id=c.token_id,
                    notional_usd=Decimal(str(rules.notional_usd)),
                    evaluation_id=ev_id,
                )
                stats["entered"] += 1
                cash -= Decimal(str(rules.notional_usd))
                open_n += 1
                held.add(c.token_id)
    return stats


async def record_equity_marks(conn: AsyncConnection, now: datetime) -> int:
    marked_at = now.replace(minute=0, second=0, microsecond=0)
    res = await conn.execute(
        text("""
        insert into paper_equity_marks (portfolio_id, marked_at, cash_usd, positions_value_usd, equity_usd, equity_sgd)
        select s.id, :at, s.cash_usd, s.positions_value_usd, s.equity_usd,
               s.equity_usd * coalesce(s.fx_sgd_per_usd, 1.30)
        from v_paper_portfolio_summary s where s.is_active
        on conflict (portfolio_id, marked_at) do update set cash_usd = excluded.cash_usd,
          positions_value_usd = excluded.positions_value_usd, equity_usd = excluded.equity_usd,
          equity_sgd = excluded.equity_sgd
    """),
        {"at": marked_at},
    )
    return res.rowcount


async def paper_cycle(engine: Any, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    async with engine.begin() as conn:
        fills = await fill_pending_orders(conn, now)
        marks = await mark_positions(conn, now)
        rules = await evaluate_position_rules(conn, now)
    return {"fills": fills, "marks": marks, "rules": rules}


async def strategy_cycle(engine: Any, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    async with engine.begin() as conn:
        return await evaluate_strategies(conn, now)


async def equity_cycle(engine: Any, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    async with engine.begin() as conn:
        await mark_positions(conn, now)
        return {"portfolios_marked": await record_equity_marks(conn, now)}
