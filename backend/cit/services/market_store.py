"""Idempotent persistence of market observations.

Deduplication: tokens are unique on (chain_id, address) and pools on
(chain_id, address); a token may have many pools. Re-observing an existing
token never overwrites known metadata with NULLs and never moves
first_observed_at.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cit.chains import BY_SLUG, is_quote_asset
from cit.providers.models import Link, PoolObservation, TokenRef


@dataclass
class UpsertStats:
    tokens_new: int = 0
    tokens_seen: int = 0
    pools_new: int = 0
    pools_seen: int = 0
    snapshots: int = 0
    new_token_ids: list[int] | None = None

    def __post_init__(self) -> None:
        if self.new_token_ids is None:
            self.new_token_ids = []


async def source_ids(conn: AsyncConnection) -> dict[str, int]:
    rows = (await conn.execute(text("select slug, id from data_sources"))).all()
    return {r.slug: r.id for r in rows}


_UPSERT_TOKEN = text("""
insert into tokens (chain_id, address, name, symbol, decimals, first_observed_at,
                    first_observed_source_id, earliest_pool_created_at, is_quote_asset)
values (:chain_id, :address, :name, :symbol, :decimals, :observed_at, :source_id, :pool_created_at, :is_quote)
on conflict (chain_id, address) do update set
  name = coalesce(tokens.name, excluded.name),
  symbol = coalesce(tokens.symbol, excluded.symbol),
  decimals = coalesce(tokens.decimals, excluded.decimals),
  earliest_pool_created_at = least(tokens.earliest_pool_created_at, excluded.earliest_pool_created_at),
  is_quote_asset = tokens.is_quote_asset or excluded.is_quote_asset
returning id, (xmax = 0) as inserted
""")

_UPSERT_POOL = text("""
insert into pools (chain_id, address, base_token_id, quote_token_id, quote_symbol, dex,
                   pool_created_at, first_observed_at, first_observed_source_id)
values (:chain_id, :address, :base_token_id, :quote_token_id, :quote_symbol, :dex,
        :pool_created_at, :observed_at, :source_id)
on conflict (chain_id, address) do update set
  quote_token_id = coalesce(pools.quote_token_id, excluded.quote_token_id),
  quote_symbol = coalesce(pools.quote_symbol, excluded.quote_symbol),
  dex = coalesce(pools.dex, excluded.dex),
  pool_created_at = coalesce(pools.pool_created_at, excluded.pool_created_at)
returning id, (xmax = 0) as inserted
""")

_SNAPSHOT_COLS = (
    "price_usd",
    "price_native",
    "liquidity_usd",
    "volume_m5_usd",
    "volume_h1_usd",
    "volume_h6_usd",
    "volume_h24_usd",
    "buys_m5",
    "sells_m5",
    "buys_h1",
    "sells_h1",
    "buys_h24",
    "sells_h24",
    "price_change_m5",
    "price_change_h1",
    "price_change_h24",
    "market_cap_usd",
    "fdv_usd",
)

_COLS = ", ".join(_SNAPSHOT_COLS)
_PARAMS = ", ".join(":" + c for c in _SNAPSHOT_COLS)
# Built from the fixed column tuple above; no external input reaches this string.
_INSERT_SNAPSHOT = text(
    "insert into market_snapshots (pool_id, token_id, source_id, ingestion_run_id, observed_at, "  # noqa: S608
    f"{_COLS}) values (:pool_id, :token_id, :source_id, :run_id, :observed_at, {_PARAMS}) returning id"
)

_UPSERT_LATEST = text("""
insert into pool_latest (pool_id, token_id, snapshot_id, source_id, observed_at, price_usd, liquidity_usd,
                         volume_h24_usd, volume_h1_usd, buys_h24, sells_h24, price_change_h24,
                         market_cap_usd, fdv_usd)
values (:pool_id, :token_id, :snapshot_id, :source_id, :observed_at, :price_usd, :liquidity_usd,
        :volume_h24_usd, :volume_h1_usd, :buys_h24, :sells_h24, :price_change_h24, :market_cap_usd, :fdv_usd)
on conflict (pool_id) do update set
  snapshot_id = excluded.snapshot_id, source_id = excluded.source_id, observed_at = excluded.observed_at,
  price_usd = excluded.price_usd, liquidity_usd = excluded.liquidity_usd,
  volume_h24_usd = excluded.volume_h24_usd, volume_h1_usd = excluded.volume_h1_usd,
  buys_h24 = excluded.buys_h24, sells_h24 = excluded.sells_h24,
  price_change_h24 = excluded.price_change_h24, market_cap_usd = excluded.market_cap_usd,
  fdv_usd = excluded.fdv_usd
where pool_latest.observed_at <= excluded.observed_at
""")


async def upsert_token(
    conn: AsyncConnection,
    chain_slug: str,
    ref: TokenRef,
    source_id: int,
    observed_at: datetime,
    pool_created_at: datetime | None,
) -> tuple[int, bool]:
    chain = BY_SLUG[chain_slug]
    row = (
        await conn.execute(
            _UPSERT_TOKEN,
            {
                "chain_id": chain.id,
                "address": ref.address,
                "name": ref.name,
                "symbol": ref.symbol,
                "decimals": ref.decimals,
                "observed_at": observed_at,
                "source_id": source_id,
                "pool_created_at": pool_created_at,
                "is_quote": is_quote_asset(chain, ref.address),
            },
        )
    ).one()
    return row.id, bool(row.inserted)


async def merge_links(
    conn: AsyncConnection, token_id: int, links: tuple[Link, ...], source: str, observed_at: datetime
) -> None:
    if not links:
        return
    current = (
        await conn.execute(text("select links from tokens where id = :id for update"), {"id": token_id})
    ).scalar_one()
    existing: list[dict[str, Any]] = list(current or [])
    known = {e.get("url") for e in existing}
    added = False
    for li in links:
        if li.url in known:
            continue
        existing.append(
            {
                "type": li.type,
                "url": li.url,
                "label": li.label,
                "source": source,
                "observed_at": observed_at.isoformat(),
            }
        )
        known.add(li.url)
        added = True
    if added:
        await conn.execute(
            text("update tokens set links = cast(:links as jsonb) where id = :id"),
            {"links": json.dumps(existing[:50]), "id": token_id},
        )


async def store_observations(
    conn: AsyncConnection, observations: list[PoolObservation], *, source_id: int, run_id: int | None
) -> UpsertStats:
    stats = UpsertStats()
    for obs in observations:
        chain = BY_SLUG[obs.chain_slug]
        base_id, base_new = await upsert_token(
            conn, obs.chain_slug, obs.base, source_id, obs.observed_at, obs.pool_created_at
        )
        stats.tokens_seen += 1
        if base_new:
            stats.tokens_new += 1
            if not is_quote_asset(chain, obs.base.address):
                stats.new_token_ids.append(base_id)  # type: ignore[union-attr]
        quote_id: int | None = None
        if obs.quote is not None:
            quote_id, _ = await upsert_token(conn, obs.chain_slug, obs.quote, source_id, obs.observed_at, None)
        pool = (
            await conn.execute(
                _UPSERT_POOL,
                {
                    "chain_id": chain.id,
                    "address": obs.pool_address,
                    "base_token_id": base_id,
                    "quote_token_id": quote_id,
                    "quote_symbol": obs.quote.symbol if obs.quote else None,
                    "dex": obs.dex,
                    "pool_created_at": obs.pool_created_at,
                    "observed_at": obs.observed_at,
                    "source_id": source_id,
                },
            )
        ).one()
        stats.pools_seen += 1
        if pool.inserted:
            stats.pools_new += 1
        await merge_links(conn, base_id, obs.links, obs.source, obs.observed_at)

        m = obs.market
        values = {c: getattr(m, c) for c in _SNAPSHOT_COLS}
        snap_id = (
            await conn.execute(
                _INSERT_SNAPSHOT,
                {
                    "pool_id": pool.id,
                    "token_id": base_id,
                    "source_id": source_id,
                    "run_id": run_id,
                    "observed_at": obs.observed_at,
                    **values,
                },
            )
        ).scalar_one()
        stats.snapshots += 1
        await conn.execute(
            _UPSERT_LATEST,
            {
                "pool_id": pool.id,
                "token_id": base_id,
                "snapshot_id": snap_id,
                "source_id": source_id,
                "observed_at": obs.observed_at,
                **{
                    k: values[k]
                    for k in (
                        "price_usd",
                        "liquidity_usd",
                        "volume_h24_usd",
                        "volume_h1_usd",
                        "buys_h24",
                        "sells_h24",
                        "price_change_h24",
                        "market_cap_usd",
                        "fdv_usd",
                    )
                },
            },
        )
    return stats
