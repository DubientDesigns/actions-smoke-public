"""GeckoTerminal public API v2 adapter (discovery of new pools).

Docs: https://www.geckoterminal.com/dex-api  — keyless public tier is documented
at ~10 calls/minute and may fluctuate, so our budget is 8/min. Attribution to
GeckoTerminal is shown wherever this data is displayed.

Response shape (JSON:API): data[] of pools with attributes and relationships to
base_token / quote_token / dex; `include=` returns the related objects in
`included[]`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cit.chains import BY_SLUG, Chain, InvalidAddress, normalize_address
from cit.log import get_logger
from cit.providers.http import ProviderClient, ProviderPolicy
from cit.providers.models import (
    MarketObs,
    PoolObservation,
    TokenRef,
    dec,
    intval,
    market_cap_or_none,
    nonneg,
    ts_iso,
)

log = get_logger(__name__)

SOURCE = "geckoterminal"
BASE_URL = "https://api.geckoterminal.com/api/v2"
HEADERS = {"Accept": "application/json;version=20230302"}


def policy(rate_per_minute: float = 8, daily_cap: int | None = 8000) -> ProviderPolicy:
    return ProviderPolicy(SOURCE, BASE_URL, rate_per_minute, daily_cap, headers=HEADERS)


def _rel_id(item: dict[str, Any], rel: str) -> str | None:
    data = ((item.get("relationships") or {}).get(rel) or {}).get("data") or {}
    rid = data.get("id")
    return rid if isinstance(rid, str) else None


def _address_from_token_id(network: str, token_id: str) -> str | None:
    prefix = f"{network}_"
    return token_id[len(prefix) :] if token_id.startswith(prefix) else None


def _token_ref(chain: Chain, token_id: str | None, included: dict[str, dict[str, Any]]) -> TokenRef | None:
    if not token_id:
        return None
    attrs = (included.get(token_id) or {}).get("attributes") or {}
    raw_addr = attrs.get("address") or _address_from_token_id(chain.geckoterminal_network, token_id)
    if not isinstance(raw_addr, str):
        return None
    try:
        addr = normalize_address(chain, raw_addr)
    except InvalidAddress:
        return None
    name = attrs.get("name") if isinstance(attrs.get("name"), str) else None
    symbol = attrs.get("symbol") if isinstance(attrs.get("symbol"), str) else None
    decimals = intval(attrs.get("decimals"))
    return TokenRef(addr, name, symbol, decimals)


def _window(d: Any, key: str) -> Any:
    return d.get(key) if isinstance(d, dict) else None


def parse_pools(chain: Chain, payload: Any, observed_at: datetime | None = None) -> list[PoolObservation]:
    """Parse a /networks/{network}/new_pools (or pools) response into observations.

    Items that cannot be parsed safely are skipped and logged, never guessed.
    """
    observed_at = observed_at or datetime.now(UTC)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("unexpected GeckoTerminal payload: missing data[]")
    included = {
        i["id"]: i for i in payload.get("included") or [] if isinstance(i, dict) and isinstance(i.get("id"), str)
    }
    out: list[PoolObservation] = []
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        a = item.get("attributes") or {}
        try:
            pool_addr = normalize_address(chain, str(a.get("address", "")))
        except InvalidAddress:
            log.warning("gt_skip_pool_bad_address", chain=chain.slug, id=item.get("id"))
            continue
        base = _token_ref(chain, _rel_id(item, "base_token"), included)
        if base is None:
            log.warning("gt_skip_pool_no_base", chain=chain.slug, pool=pool_addr)
            continue
        quote = _token_ref(chain, _rel_id(item, "quote_token"), included)
        tx = a.get("transactions") or {}
        vol = a.get("volume_usd") or {}
        pc = a.get("price_change_percentage") or {}
        fdv = nonneg(a.get("fdv_usd"))
        market = MarketObs(
            price_usd=nonneg(a.get("base_token_price_usd")),
            price_native=nonneg(a.get("base_token_price_native_currency")),
            liquidity_usd=nonneg(a.get("reserve_in_usd")),
            volume_m5_usd=nonneg(_window(vol, "m5")),
            volume_h1_usd=nonneg(_window(vol, "h1")),
            volume_h6_usd=nonneg(_window(vol, "h6")),
            volume_h24_usd=nonneg(_window(vol, "h24")),
            buys_m5=intval(_window(_window(tx, "m5"), "buys")),
            sells_m5=intval(_window(_window(tx, "m5"), "sells")),
            buys_h1=intval(_window(_window(tx, "h1"), "buys")),
            sells_h1=intval(_window(_window(tx, "h1"), "sells")),
            buys_h24=intval(_window(_window(tx, "h24"), "buys")),
            sells_h24=intval(_window(_window(tx, "h24"), "sells")),
            price_change_m5=dec(_window(pc, "m5")),
            price_change_h1=dec(_window(pc, "h1")),
            price_change_h24=dec(_window(pc, "h24")),
            market_cap_usd=market_cap_or_none(nonneg(a.get("market_cap_usd")), fdv),
            fdv_usd=fdv,
        )
        out.append(
            PoolObservation(
                source=SOURCE,
                chain_slug=chain.slug,
                pool_address=pool_addr,
                dex=_rel_id(item, "dex"),
                base=base,
                quote=quote,
                pool_created_at=ts_iso(a.get("pool_created_at")),
                observed_at=observed_at,
                market=market,
            )
        )
    return out


class GeckoTerminal:
    def __init__(self, client: ProviderClient):
        self.client = client

    async def new_pools(self, chain_slug: str, page: int = 1) -> list[PoolObservation]:
        chain = BY_SLUG[chain_slug]
        payload = await self.client.get_json(
            f"/networks/{chain.geckoterminal_network}/new_pools",
            {"page": page, "include": "base_token,quote_token,dex"},
            endpoint="new_pools",
        )
        return parse_pools(chain, payload)

    async def networks(self) -> Any:
        return await self.client.get_json("/networks", {"page": 1}, endpoint="networks")
