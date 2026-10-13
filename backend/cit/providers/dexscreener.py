"""DEX Screener public API adapter.

Docs: https://docs.dexscreener.com/api/reference
  * /tokens/v1/{chainId}/{a,b,...}   up to 30 token addresses; 300 rpm documented
  * /token-profiles/latest/v1        60 rpm documented (paid project profiles)
Terms: https://docs.dexscreener.com/api/api-terms-and-conditions — no resale /
redistribution of the API; data shown privately only.

Used for (a) refreshing market data for tracked tokens in batches and
(b) collecting project links. Token profiles are paid listings and are
labelled as such (they are promotional, not evidence of quality).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from cit.chains import BY_DEXSCREENER, BY_SLUG, Chain, InvalidAddress, normalize_address
from cit.log import get_logger
from cit.providers.http import ProviderClient, ProviderPolicy
from cit.providers.models import (
    Link,
    MarketObs,
    PoolObservation,
    TokenProfile,
    TokenRef,
    classify_link,
    dec,
    intval,
    market_cap_or_none,
    nonneg,
    safe_url,
    ts_millis,
)

log = get_logger(__name__)

SOURCE = "dexscreener"
BASE_URL = "https://api.dexscreener.com"
MAX_ADDRESSES_PER_CALL = 30


def policy(rate_per_minute: float = 50, daily_cap: int | None = 40000) -> ProviderPolicy:
    return ProviderPolicy(SOURCE, BASE_URL, rate_per_minute, daily_cap)


def _links_from_info(info: Any) -> tuple[Link, ...]:
    if not isinstance(info, dict):
        return ()
    links: list[Link] = []
    for w in info.get("websites") or []:
        if isinstance(w, dict) and (u := safe_url(w.get("url"))):
            label = w.get("label") if isinstance(w.get("label"), str) else None
            links.append(Link(classify_link("website", u), u, label))
    for s in info.get("socials") or []:
        if isinstance(s, dict) and (u := safe_url(s.get("url"))):
            links.append(Link(classify_link(s.get("type"), u), u))
    return tuple(links)


def _w(d: Any, k: str) -> Any:
    return d.get(k) if isinstance(d, dict) else None


def parse_pairs(
    payload: Any, observed_at: datetime | None = None, only_chains: Iterable[str] | None = None
) -> list[PoolObservation]:
    """Parse /tokens/v1 (a bare list) or /latest/dex/* ({"pairs": [...]}) responses."""
    observed_at = observed_at or datetime.now(UTC)
    if isinstance(payload, dict):
        pairs = payload.get("pairs") or []
    elif isinstance(payload, list):
        pairs = payload
    else:
        raise ValueError("unexpected DEX Screener payload")
    allowed = set(only_chains) if only_chains else None
    out: list[PoolObservation] = []
    for p in pairs:
        if not isinstance(p, dict):
            continue
        chain: Chain | None = BY_DEXSCREENER.get(str(p.get("chainId")))
        if chain is None or (allowed is not None and chain.slug not in allowed):
            continue
        try:
            pool_addr = normalize_address(chain, str(p.get("pairAddress", "")))
            bt = p.get("baseToken") or {}
            base = TokenRef(
                normalize_address(chain, str(bt.get("address", ""))),
                bt.get("name") if isinstance(bt.get("name"), str) else None,
                bt.get("symbol") if isinstance(bt.get("symbol"), str) else None,
            )
        except InvalidAddress:
            log.warning("ds_skip_pair_bad_address", chain=chain.slug, pair=p.get("pairAddress"))
            continue
        quote: TokenRef | None = None
        qt = p.get("quoteToken") or {}
        try:
            quote = TokenRef(
                normalize_address(chain, str(qt.get("address", ""))),
                qt.get("name") if isinstance(qt.get("name"), str) else None,
                qt.get("symbol") if isinstance(qt.get("symbol"), str) else None,
            )
        except InvalidAddress:
            quote = None
        tx, vol, pc = p.get("txns") or {}, p.get("volume") or {}, p.get("priceChange") or {}
        fdv = nonneg(p.get("fdv"))
        market = MarketObs(
            price_usd=nonneg(p.get("priceUsd")),
            price_native=nonneg(p.get("priceNative")),
            liquidity_usd=nonneg(_w(p.get("liquidity"), "usd")),
            volume_m5_usd=nonneg(_w(vol, "m5")),
            volume_h1_usd=nonneg(_w(vol, "h1")),
            volume_h6_usd=nonneg(_w(vol, "h6")),
            volume_h24_usd=nonneg(_w(vol, "h24")),
            buys_m5=intval(_w(_w(tx, "m5"), "buys")),
            sells_m5=intval(_w(_w(tx, "m5"), "sells")),
            buys_h1=intval(_w(_w(tx, "h1"), "buys")),
            sells_h1=intval(_w(_w(tx, "h1"), "sells")),
            buys_h24=intval(_w(_w(tx, "h24"), "buys")),
            sells_h24=intval(_w(_w(tx, "h24"), "sells")),
            price_change_m5=dec(_w(pc, "m5")),
            price_change_h1=dec(_w(pc, "h1")),
            price_change_h24=dec(_w(pc, "h24")),
            market_cap_usd=market_cap_or_none(nonneg(p.get("marketCap")), fdv),
            fdv_usd=fdv,
        )
        labels = tuple(x for x in (p.get("labels") or []) if isinstance(x, str))
        out.append(
            PoolObservation(
                source=SOURCE,
                chain_slug=chain.slug,
                pool_address=pool_addr,
                dex=p.get("dexId") if isinstance(p.get("dexId"), str) else None,
                base=base,
                quote=quote,
                pool_created_at=ts_millis(p.get("pairCreatedAt")),
                observed_at=observed_at,
                market=market,
                links=_links_from_info(p.get("info")),
                labels=labels,
            )
        )
    return out


def parse_token_profiles(payload: Any, observed_at: datetime | None = None) -> list[TokenProfile]:
    observed_at = observed_at or datetime.now(UTC)
    if not isinstance(payload, list):
        raise ValueError("unexpected token-profiles payload")
    out: list[TokenProfile] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        chain = BY_DEXSCREENER.get(str(item.get("chainId")))
        if chain is None:
            continue
        try:
            addr = normalize_address(chain, str(item.get("tokenAddress", "")))
        except InvalidAddress:
            continue
        links = []
        for li in item.get("links") or []:
            if isinstance(li, dict) and (u := safe_url(li.get("url"))):
                links.append(
                    Link(
                        classify_link(li.get("type") or li.get("label"), u),
                        u,
                        li.get("label") if isinstance(li.get("label"), str) else None,
                    )
                )
        desc = item.get("description")
        out.append(
            TokenProfile(
                SOURCE,
                chain.slug,
                addr,
                desc[:2000] if isinstance(desc, str) else None,
                tuple(links),
                observed_at,
                is_paid_listing=True,
            )
        )
    return out


class DexScreener:
    def __init__(self, client: ProviderClient):
        self.client = client

    async def pairs_for_tokens(self, chain_slug: str, addresses: list[str]) -> list[PoolObservation]:
        chain = BY_SLUG[chain_slug]
        out: list[PoolObservation] = []
        for i in range(0, len(addresses), MAX_ADDRESSES_PER_CALL):
            batch = addresses[i : i + MAX_ADDRESSES_PER_CALL]
            payload = await self.client.get_json(
                f"/tokens/v1/{chain.dexscreener_chain}/{','.join(batch)}", endpoint="tokens_v1"
            )
            out.extend(parse_pairs(payload, only_chains=[chain.slug]))
        return out

    async def latest_token_profiles(self) -> list[TokenProfile]:
        payload = await self.client.get_json("/token-profiles/latest/v1", endpoint="token_profiles_latest")
        return parse_token_profiles(payload)
