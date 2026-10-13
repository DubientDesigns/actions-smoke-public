"""sync_wallets job: transfers for operator-tracked wallets.

EVM chains via Alchemy (block cursor per wallet; first sync looks back ~7 days),
Solana via Helius (signature cursor). Each source is skipped, not failed, when
its API key is not configured or the source is disabled. USD values use our
latest observed price for the token when we track it; otherwise NULL (unknown).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cit.chains import BY_ID
from cit.log import get_logger
from cit.providers import alchemy, helius
from cit.providers.http import ProviderError
from cit.services import runs
from cit.services.runtime import ProviderRuntime

log = get_logger(__name__)

_INSERT = text("""
insert into wallet_events (wallet_id, chain_id, tx_hash, log_index, block_number, block_time, event_type,
  token_id, token_address, amount, value_usd, counterparty, source_id, raw)
select :wallet_id, :chain_id, :tx, :li, :block, :time, :etype,
  t.id, cast(:token as text), cast(:amount as numeric),
  case when cast(:amount as numeric) is not null then cast(:amount as numeric) * (
    select pl.price_usd from pool_latest pl where pl.token_id = t.id order by pl.liquidity_usd desc nulls last limit 1)
  end,
  :cp, s.id, cast(:raw as jsonb)
from data_sources s left join tokens t on t.chain_id = :chain_id and t.address = cast(:token as text)
where s.slug = :source
on conflict (wallet_id, chain_id, tx_hash, log_index) do nothing
""")


async def _enabled(conn: AsyncConnection, slug: str) -> bool:
    return bool((await conn.execute(text("select enabled from data_sources where slug = :s"), {"s": slug})).scalar())


async def _finish_wallet(conn: AsyncConnection, wallet_id: int, cursor: str | None, error: str | None) -> None:
    await conn.execute(
        text("""
        update tracked_wallets set sync_cursor = coalesce(cast(:c as text), sync_cursor),
          last_sync_error = cast(:e as text),
          last_synced_at = case when cast(:e as text) is null then now() else last_synced_at end
        where id = :id
    """),
        {"c": cursor, "e": error, "id": wallet_id},
    )


async def sync_wallets(rt: ProviderRuntime) -> dict[str, Any]:
    s = rt.settings
    alchemy_key = s.alchemy_api_key.get_secret_value() if s.alchemy_api_key else ""
    helius_key = s.helius_api_key.get_secret_value() if s.helius_api_key else ""
    async with rt.engine.connect() as conn:
        wallets = (
            await conn.execute(
                text("select id, chain_id, address, sync_cursor from tracked_wallets where enabled order by id")
            )
        ).all()
        use_alchemy = bool(alchemy_key) and await _enabled(conn, alchemy.SOURCE)
        use_helius = bool(helius_key) and await _enabled(conn, helius.SOURCE)
    stats: dict[str, Any] = {"wallets": len(wallets), "events": 0, "errors": 0, "skipped": []}
    if not use_alchemy:
        stats["skipped"].append("alchemy: key not set or source disabled")
    if not use_helius:
        stats["skipped"].append("helius: key not set or source disabled")
    results: dict[str, list[str | None]] = {}

    for w in wallets:
        chain = BY_ID[w.chain_id]
        try:
            if chain.slug == "solana":
                if not use_helius:
                    continue
                client = await rt.client(helius.policy(helius_key))
                client.job_name = "sync_wallets"
                events, newest = await helius.Helius(client, helius_key).transactions(w.address, w.sync_cursor)
                async with rt.engine.begin() as conn:
                    for e in events:
                        await conn.execute(
                            _INSERT,
                            {
                                "wallet_id": w.id,
                                "chain_id": chain.id,
                                "tx": e.signature,
                                "li": e.index,
                                "block": None,
                                "time": e.block_time,
                                "etype": e.event_type,
                                "token": e.mint,
                                "amount": e.amount,
                                "cp": e.counterparty,
                                "raw": json.dumps(e.raw, default=str),
                                "source": helius.SOURCE,
                            },
                        )
                    await _finish_wallet(conn, w.id, newest, None)
                stats["events"] += len(events)
                results.setdefault(helius.SOURCE, []).append(None)
            else:
                if not use_alchemy:
                    continue
                client = await rt.client(alchemy.policy(chain.slug, alchemy_key))
                client.job_name = "sync_wallets"
                api = alchemy.Alchemy(client)
                if w.sync_cursor:
                    start = int(w.sync_cursor) + 1
                else:
                    start = max(0, await api.block_number() - alchemy.INITIAL_LOOKBACK_BLOCKS[chain.slug])
                transfers = await api.transfers(w.address, start, "out") + await api.transfers(w.address, start, "in")
                async with rt.engine.begin() as conn:
                    for t in transfers:
                        await conn.execute(
                            _INSERT,
                            {
                                "wallet_id": w.id,
                                "chain_id": chain.id,
                                "tx": t.tx_hash,
                                "li": t.log_index,
                                "block": t.block_number,
                                "time": t.block_time,
                                "etype": "transfer_out" if t.direction == "out" else "transfer_in",
                                "token": t.token_address,
                                "amount": t.amount,
                                "cp": t.counterparty,
                                "raw": json.dumps(t.raw, default=str),
                                "source": alchemy.SOURCE,
                            },
                        )
                    newest = max((t.block_number for t in transfers), default=start - 1)
                    await _finish_wallet(conn, w.id, str(newest), None)
                stats["events"] += len(transfers)
                results.setdefault(alchemy.SOURCE, []).append(None)
        except ProviderError as exc:
            stats["errors"] += 1
            src = helius.SOURCE if chain.slug == "solana" else alchemy.SOURCE
            results.setdefault(src, []).append(str(exc))
            async with rt.engine.begin() as conn:
                await _finish_wallet(conn, w.id, None, str(exc)[:500])
            log.warning("wallet_sync_failed", wallet_id=w.id, error=str(exc))

    async with rt.engine.begin() as conn:
        for src, outcomes in results.items():
            errors = [o for o in outcomes if o]
            await runs.record_source_result(
                conn, src, ok=len(errors) < len(outcomes), error=errors[-1] if errors else None, breaker=None
            )
    await rt.flush_usage()
    return stats
