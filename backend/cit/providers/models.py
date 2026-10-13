"""Provider-neutral records produced by adapters.

Adapters must never invent values: anything the provider did not return (or
returned in an unparseable form) is None, which downstream code treats as
"unknown".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class TokenRef:
    address: str  # normalised
    name: str | None = None
    symbol: str | None = None
    decimals: int | None = None


@dataclass(frozen=True)
class Link:
    type: str  # website | twitter | telegram | discord | docs | other
    url: str
    label: str | None = None


@dataclass(frozen=True)
class MarketObs:
    price_usd: Decimal | None = None
    price_native: Decimal | None = None
    liquidity_usd: Decimal | None = None
    volume_m5_usd: Decimal | None = None
    volume_h1_usd: Decimal | None = None
    volume_h6_usd: Decimal | None = None
    volume_h24_usd: Decimal | None = None
    buys_m5: int | None = None
    sells_m5: int | None = None
    buys_h1: int | None = None
    sells_h1: int | None = None
    buys_h24: int | None = None
    sells_h24: int | None = None
    price_change_m5: Decimal | None = None
    price_change_h1: Decimal | None = None
    price_change_h24: Decimal | None = None
    market_cap_usd: Decimal | None = None
    fdv_usd: Decimal | None = None


@dataclass(frozen=True)
class PoolObservation:
    source: str  # data_sources.slug
    chain_slug: str
    pool_address: str  # normalised
    dex: str | None
    base: TokenRef
    quote: TokenRef | None
    pool_created_at: datetime | None
    observed_at: datetime
    market: MarketObs
    links: tuple[Link, ...] = field(default_factory=tuple)
    labels: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TokenProfile:
    """A token listing/profile entry (e.g. DEX Screener paid token profile)."""

    source: str
    chain_slug: str
    token_address: str
    description: str | None
    links: tuple[Link, ...]
    observed_at: datetime
    is_paid_listing: bool


# ---------------------------------------------------------------------------
# Defensive parsing helpers
# ---------------------------------------------------------------------------


def dec(value: Any) -> Decimal | None:
    """Parse a provider number (often a string) into Decimal; None if absent/invalid."""
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite():
        return None
    return d


def nonneg(value: Any) -> Decimal | None:
    d = dec(value)
    return d if d is not None and d >= 0 else None


def intval(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        i = int(value)
    except (TypeError, ValueError):
        return None
    return i if i >= 0 else None


def ts_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def ts_millis(value: Any) -> datetime | None:
    i = intval(value)
    if i is None or i == 0:
        return None
    try:
        return datetime.fromtimestamp(i / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def market_cap_or_none(market_cap: Decimal | None, fdv: Decimal | None) -> Decimal | None:
    """Never let FDV masquerade as market cap.

    Several providers fall back to FDV when circulating supply is unknown, which
    makes the two numbers identical. In that case we cannot tell whether the
    value is a real circulating market cap, so we record market cap as unknown.
    """
    if market_cap is None or market_cap <= 0:
        return None
    if fdv is not None and market_cap == fdv:
        return None
    return market_cap


def classify_link(kind: str | None, url: str) -> str:
    k = (kind or "").lower()
    u = url.lower()
    if k in {"twitter", "x"} or "twitter.com/" in u or "//x.com/" in u:
        return "twitter"
    if k == "telegram" or "t.me/" in u or "telegram.me/" in u:
        return "telegram"
    if k == "discord" or "discord.gg/" in u or "discord.com/" in u:
        return "discord"
    if k in {"docs", "whitepaper"} or "gitbook" in u or "/docs" in u:
        return "docs"
    if k in {"website", "site", ""} and u.startswith(("http://", "https://")):
        return "website"
    return "other"


def safe_url(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    u = url.strip()
    if not u.lower().startswith(("https://", "http://")) or len(u) > 2048:
        return None
    return u
