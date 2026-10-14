"""Paper execution model (pure functions, no I/O).

Prices come from observed pool snapshots. A fill is never assumed at the
displayed price:

* Price impact uses the constant-product (x*y=k) model. With pool liquidity L
  (USD, both sides) the quote-side reserve is R = L/2. Buying with notional q
  (after fees) moves the average price to p*(1 + q/R); selling base worth v at
  mid price receives p/(1 + v/R) on average.
* Fees (`fee_bps`, per side) and an extra slippage allowance (`extra_bps`, for
  MEV/sandwiching and routing) are applied on top.
* Size cap: a buy larger than `max_pool_liquidity_pct` of liquidity is rejected;
  a sell is partially filled up to that cap and the rest stays open.
* Pools below `min_liquidity_usd`, or without a usable price, are untradeable.

Concentrated-liquidity pools (Uniswap v3/v4, CLMM) can have far less depth near
the price than their headline TVL suggests; the model is therefore optimistic
for those and the size cap is deliberately small.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

ZERO = Decimal(0)
BPS = Decimal(10_000)


@dataclass(frozen=True)
class ExecParams:
    fee_bps: Decimal = Decimal(30)
    extra_bps: Decimal = Decimal(50)
    max_pool_liquidity_pct: Decimal = Decimal(2)
    min_liquidity_usd: Decimal = Decimal(10_000)


@dataclass(frozen=True)
class Quote:
    ok: bool
    reason: str | None
    reference_price: Decimal | None  # observed mid price
    executed_price: Decimal | None  # average price incl. impact + extra slippage
    quantity: Decimal  # base tokens bought / sold
    notional_usd: Decimal  # quote spent (buy, incl. fee) / received (sell, after fee)
    fee_usd: Decimal
    slippage_bps: Decimal  # executed vs reference, incl. impact
    unfilled_quantity: Decimal = ZERO


def _reject(reason: str, price: Decimal | None = None) -> Quote:
    return Quote(False, reason, price, None, ZERO, ZERO, ZERO, ZERO)


def _usable(price: Decimal | None, liquidity: Decimal | None, p: ExecParams) -> str | None:
    if price is None or price <= 0:
        return "no usable price"
    if liquidity is None:
        return "liquidity unknown"
    if liquidity < p.min_liquidity_usd:
        return f"liquidity ${liquidity:,.0f} below minimum ${p.min_liquidity_usd:,.0f}"
    return None


def quote_buy(price: Decimal | None, liquidity: Decimal | None, notional_usd: Decimal, p: ExecParams) -> Quote:
    """Buy with `notional_usd` total spend (fee included)."""
    if (why := _usable(price, liquidity, p)) is not None:
        return _reject(why, price)
    assert price is not None and liquidity is not None
    if notional_usd <= 0:
        return _reject("notional must be positive", price)
    cap = liquidity * p.max_pool_liquidity_pct / 100
    if notional_usd > cap:
        return _reject(
            f"size ${notional_usd:,.2f} exceeds {p.max_pool_liquidity_pct}% of liquidity (${cap:,.2f})", price
        )
    fee = notional_usd * p.fee_bps / BPS
    spend = notional_usd - fee
    reserve = liquidity / 2
    avg = price * (1 + spend / reserve) * (1 + p.extra_bps / BPS)
    qty = (spend / avg).quantize(Decimal("1e-18"), rounding=ROUND_DOWN)
    return Quote(True, None, price, avg, qty, notional_usd, fee, (avg / price - 1) * BPS)


def quote_sell(price: Decimal | None, liquidity: Decimal | None, quantity: Decimal, p: ExecParams) -> Quote:
    """Sell `quantity` base tokens; partially fills when the size exceeds the liquidity cap."""
    if (why := _usable(price, liquidity, p)) is not None:
        return _reject(why, price)
    assert price is not None and liquidity is not None
    if quantity <= 0:
        return _reject("quantity must be positive", price)
    cap_usd = liquidity * p.max_pool_liquidity_pct / 100
    sell_qty = min(quantity, (cap_usd / price).quantize(Decimal("1e-18"), rounding=ROUND_DOWN))
    if sell_qty <= 0:
        return _reject("size cap leaves nothing sellable", price)
    reserve = liquidity / 2
    value_mid = sell_qty * price
    avg = price / (1 + value_mid / reserve) * (1 - p.extra_bps / BPS)
    gross = sell_qty * avg
    fee = gross * p.fee_bps / BPS
    return Quote(
        True,
        None,
        price,
        avg,
        sell_qty,
        gross - fee,
        fee,
        (1 - avg / price) * BPS,
        unfilled_quantity=quantity - sell_qty,
    )


def liquidation_value(price: Decimal | None, liquidity: Decimal | None, quantity: Decimal, p: ExecParams) -> Decimal:
    """Conservative mark: what selling the WHOLE position now would return.

    Unlike quote_sell this ignores the size cap (one hypothetical market sell),
    so a position that is large relative to the pool is marked down by its own
    price impact. Untradeable positions are worth zero.
    """
    if quantity <= 0 or _usable(price, liquidity, p) is not None:
        return ZERO
    assert price is not None and liquidity is not None
    reserve = liquidity / 2
    avg = price / (1 + quantity * price / reserve) * (1 - p.extra_bps / BPS)
    gross = quantity * avg
    return gross - gross * p.fee_bps / BPS
