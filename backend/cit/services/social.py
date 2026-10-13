"""Social intelligence jobs.

collect_telegram         Bot getUpdates -> social_mentions, for REGISTERED chats only.
                         Unregistered chats are recorded as requests (metadata only,
                         no message content) for the owner to approve or ignore.
resolve_mentions         Link mentioned contract addresses to tokens; unknown tokens
                         are looked up on DEX Screener (chain-agnostic) and ingested.
update_mention_outcomes  Forward performance of each mention, measured only from
                         prices observed AFTER the mention was published.

Only messages that reference a contract address or a cashtag (or come from an
official project channel) are stored, as a short excerpt; other chat content
is discarded.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from cit.chains import BY_SLUG
from cit.log import get_logger
from cit.providers import dexscreener
from cit.providers.dexscreener import SOURCE as DS
from cit.providers.http import ProviderError
from cit.providers.telegram import SOURCE as TG
from cit.providers.telegram import TgMessage
from cit.services import market_store, runs
from cit.services.runtime import ProviderRuntime
from cit.social.extract import excerpt, extract

log = get_logger(__name__)

OFFSET_KEY = "telegram.update_offset"
# Exit feasibility: could a reference position be sold within this share of pool liquidity?
REFERENCE_POSITION_USD = 1_000
MAX_LIQUIDITY_SHARE = 0.02
UNTRADEABLE_LIQUIDITY_USD = 1_000


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


async def find_token(conn: AsyncConnection, address: str, chain_slug: str | None) -> tuple[int | None, int | None]:
    """Return (token_id, chain_id) when the address resolves to exactly one known token."""
    if chain_slug:
        chain = BY_SLUG[chain_slug]
        row = (
            await conn.execute(
                text("select id from tokens where chain_id = :c and address = :a"), {"c": chain.id, "a": address}
            )
        ).first()
        return (row.id if row else None), chain.id
    rows = (await conn.execute(text("select id, chain_id from tokens where address = :a"), {"a": address})).all()
    if len(rows) == 1:
        return rows[0].id, rows[0].chain_id
    return None, None


_INSERT_MENTION = text("""
insert into social_mentions (channel_id, influencer_id, external_message_id, published_at, token_id, chain_id,
  contract_address, source_url, category, promo_disclosure, is_forwarded, forwarded_from, referral_links,
  text_excerpt, content_hash, mentioned_symbols, origin)
values (:channel_id, :influencer_id, :ext_id, :published_at, :token_id, :chain_id, :contract, :url, :category,
  :disclosure, :fwd, :fwd_from, :refs, :excerpt, :hash, :symbols, 'collector')
on conflict (channel_id, external_message_id) do nothing
returning id
""")


async def store_message(conn: AsyncConnection, channel: Any, msg: TgMessage) -> int:
    body = msg.text + ("\n" + "\n".join(msg.urls) if msg.urls else "")
    ex = extract(body)
    if not ex.contracts and not ex.symbols and not channel.is_official_project:
        return 0
    refs: list[Any] = ex.contracts or [None]
    stored = 0
    for n, ref in enumerate(refs):
        token_id = chain_id = None
        if ref is not None:
            token_id, chain_id = await find_token(conn, ref.address, ref.chain)
        res = await conn.execute(
            _INSERT_MENTION,
            {
                "channel_id": channel.id,
                "influencer_id": channel.influencer_id,
                "ext_id": f"{msg.message_id}" if n == 0 else f"{msg.message_id}:{n}",
                "published_at": msg.date,
                "token_id": token_id,
                "chain_id": chain_id,
                "contract": ref.address if ref else None,
                "url": msg.link,
                "category": ex.category,
                "disclosure": ex.promo_disclosure,
                "fwd": msg.is_forwarded,
                "fwd_from": msg.forwarded_from,
                "refs": ex.referral_links[:10],
                "excerpt": excerpt(msg.text),
                "hash": ex.content_hash,
                "symbols": ex.symbols,
            },
        )
        stored += int(res.first() is not None)
    return stored


async def _note_request(conn: AsyncConnection, msg: TgMessage) -> None:
    await conn.execute(
        text("""
        insert into social_chat_requests (platform, external_id, title, chat_type, messages_seen)
        values ('telegram', :id, :title, :type, 1)
        on conflict (platform, external_id) do update set last_seen_at = now(),
          messages_seen = social_chat_requests.messages_seen + 1,
          title = coalesce(excluded.title, social_chat_requests.title)
    """),
        {"id": msg.chat_id, "title": msg.chat_title or msg.chat_username, "type": msg.chat_type},
    )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


async def collect_telegram(rt: ProviderRuntime) -> dict[str, Any]:
    token = rt.settings.telegram_bot_token.get_secret_value() if rt.settings.telegram_bot_token else ""
    async with rt.engine.connect() as conn:
        enabled = (await conn.execute(text("select enabled from data_sources where slug = :s"), {"s": TG})).scalar()
        offset = (await conn.execute(text("select value from worker_state where key = :k"), {"k": OFFSET_KEY})).scalar()
    if not token or not enabled:
        return {"skipped": "telegram bot not configured or source disabled"}
    bot = await rt.telegram()
    bot.client.job_name = "collect_telegram"
    async with rt.engine.begin() as conn:
        run_id = await runs.start_run(conn, TG, "collect_telegram")
    counters = runs.RunCounters()
    stats = {"updates": 0, "stored": 0, "unregistered": 0, "ignored_chats": 0}
    try:
        messages, max_id = await bot.get_updates(int(offset) + 1 if offset is not None else None)
        counters.http_calls = 1
        async with rt.engine.begin() as conn:
            for msg in messages:
                stats["updates"] += 1
                ch = (
                    await conn.execute(
                        text("""
                    select id, influencer_id, is_official_project, enabled from social_channels
                    where platform = 'telegram' and external_id = :id
                """),
                        {"id": msg.chat_id},
                    )
                ).first()
                if ch is None:
                    await _note_request(conn, msg)
                    stats["unregistered"] += 1
                    continue
                if not ch.enabled:
                    stats["ignored_chats"] += 1
                    continue
                stats["stored"] += await store_message(conn, ch, msg)
                await conn.execute(
                    text("update social_channels set last_collected_at = now() where id = :id"), {"id": ch.id}
                )
            if max_id is not None:
                # Advance the offset in the same transaction as the stored messages.
                await conn.execute(
                    text("""
                    insert into worker_state (key, value) values (:k, cast(:v as jsonb))
                    on conflict (key) do update set value = excluded.value, updated_at = now()
                """),
                    {"k": OFFSET_KEY, "v": json.dumps(max_id)},
                )
            counters.items_fetched, counters.items_new, counters.details = stats["updates"], stats["stored"], stats
            await runs.finish_run(conn, run_id, "success", counters)
            await runs.record_source_result(conn, TG, ok=True, error=None, breaker=bot.client.breaker)
    except ProviderError as exc:
        async with rt.engine.begin() as conn:
            await runs.finish_run(conn, run_id, "failed", counters, str(exc))
            await runs.record_source_result(conn, TG, ok=False, error=str(exc), breaker=bot.client.breaker)
        stats["error"] = str(exc)
    await rt.flush_usage()
    return stats


_UNRESOLVED = text("""
select distinct m.contract_address, c.slug as chain
from social_mentions m left join chains c on c.id = m.chain_id
where m.token_id is null and m.contract_address is not null and m.published_at > now() - interval '35 days'
limit 60
""")


async def resolve_mentions(rt: ProviderRuntime) -> dict[str, Any]:
    async with rt.engine.connect() as conn:
        rows = (await conn.execute(_UNRESOLVED)).all()
        sources = await market_store.source_ids(conn)
    if not rows:
        return {"unresolved": 0}
    ds = await rt.dexscreener()
    ds.client.job_name = "resolve_mentions"
    evm = [r.contract_address for r in rows if r.contract_address.startswith("0x")]
    sol = [r.contract_address for r in rows if not r.contract_address.startswith("0x")]
    fetched = 0
    try:
        for i in range(0, len(evm), dexscreener.MAX_ADDRESSES_PER_CALL):
            batch = evm[i : i + dexscreener.MAX_ADDRESSES_PER_CALL]
            payload = await ds.client.get_json(f"/latest/dex/tokens/{','.join(batch)}", endpoint="latest_dex_tokens")
            obs = dexscreener.parse_pairs(payload)
            async with rt.engine.begin() as conn:
                await market_store.store_observations(conn, obs, source_id=sources[DS], run_id=None)
            fetched += len(obs)
        if sol:
            obs = await ds.pairs_for_tokens("solana", sol)
            async with rt.engine.begin() as conn:
                await market_store.store_observations(conn, obs, source_id=sources[DS], run_id=None)
            fetched += len(obs)
    except ProviderError as exc:
        log.warning("resolve_mentions_lookup_failed", error=str(exc))
    linked = 0
    async with rt.engine.begin() as conn:
        for r in rows:
            # Prefer the explicit chain; otherwise the chain where the token trades deepest.
            res = (
                await conn.execute(
                    text("""
                select t.id, t.chain_id from tokens t
                left join lateral (
                  select max(liquidity_usd) as liq from pool_latest pl where pl.token_id = t.id
                ) b on true
                where t.address = :a and (cast(:chain as text) is null or t.chain_id = (
                  select id from chains where slug = cast(:chain as text)))
                order by b.liq desc nulls last limit 1
            """),
                    {"a": r.contract_address, "chain": r.chain},
                )
            ).first()
            if res is None:
                continue
            upd = await conn.execute(
                text("""
                update social_mentions set token_id = :t, chain_id = :c
                where contract_address = :a and token_id is null
            """),
                {"t": res.id, "c": res.chain_id, "a": r.contract_address},
            )
            linked += upd.rowcount
    await rt.flush_usage()
    return {"unresolved": len(rows), "pairs_fetched": fetched, "mentions_linked": linked}


_OUTCOME_INPUT = text("""
with best as (
  select distinct on (pl.token_id) pl.token_id, pl.pool_id
  from pool_latest pl order by pl.token_id, pl.liquidity_usd desc nulls last
)
select m.id, m.published_at, b.pool_id,
  f.observed_at as first_at, f.price_usd as first_price, f.liquidity_usd as first_liq,
  (select price_usd from market_snapshots s where s.pool_id = b.pool_id
     and s.observed_at between m.published_at + interval '24 hours' and m.published_at + interval '30 hours'
     order by s.observed_at limit 1) as p24,
  (select price_usd from market_snapshots s where s.pool_id = b.pool_id
     and s.observed_at between m.published_at + interval '7 days' and m.published_at + interval '7 days 12 hours'
     order by s.observed_at limit 1) as p7d,
  (select price_usd from market_snapshots s where s.pool_id = b.pool_id
     and s.observed_at between m.published_at + interval '30 days' and m.published_at + interval '31 days'
     order by s.observed_at limit 1) as p30d,
  (select max(price_usd) from market_snapshots s where s.pool_id = b.pool_id
     and s.observed_at >= f.observed_at and s.observed_at <= m.published_at + interval '30 days') as hi,
  (select min(price_usd) from market_snapshots s where s.pool_id = b.pool_id
     and s.observed_at >= f.observed_at and s.observed_at <= m.published_at + interval '30 days') as lo,
  (select liquidity_usd from market_snapshots s where s.pool_id = b.pool_id
     and s.observed_at <= m.published_at + interval '30 days' order by s.observed_at desc limit 1) as last_liq,
  (select max(observed_at) from market_snapshots s where s.pool_id = b.pool_id) as last_seen
from social_mentions m
left join best b on b.token_id = m.token_id
left join lateral (
  -- First observation AT OR AFTER publication: never a price from before the mention.
  select s.observed_at, s.price_usd, s.liquidity_usd from market_snapshots s
  where s.pool_id = b.pool_id and s.observed_at >= m.published_at and s.price_usd is not null
  order by s.observed_at limit 1
) f on true
left join mention_outcomes o on o.mention_id = m.id
where m.token_id is not null and coalesce(o.outcome_status, 'pending') not in ('final', 'no_price')
  and m.published_at > now() - interval '45 days'
""")


def outcome_status(
    now: datetime, published: datetime, first_price: Any, last_liq: Any, last_seen: datetime | None
) -> str:
    age_days = (now - published).total_seconds() / 86400
    if first_price is None:
        return "no_price" if age_days > 2 else "pending"
    if last_liq is not None and float(last_liq) < UNTRADEABLE_LIQUIDITY_USD:
        return "untradeable"
    if age_days < 30 and last_seen is not None and (now - last_seen).total_seconds() > 72 * 3600:
        return "delisted"
    return "final" if age_days >= 31 else "tracking"


async def update_mention_outcomes(rt: ProviderRuntime) -> dict[str, Any]:
    now = datetime.now(UTC)
    updated = 0
    async with rt.engine.begin() as conn:
        for r in (await conn.execute(_OUTCOME_INPUT)).all():
            first = float(r.first_price) if r.first_price else None
            gain = (float(r.hi) / first - 1) * 100 if first and r.hi is not None else None
            dd = (float(r.lo) / first - 1) * 100 if first and r.lo is not None else None
            exit_ok = None if r.last_liq is None else float(r.last_liq) * MAX_LIQUIDITY_SHARE >= REFERENCE_POSITION_USD
            status = outcome_status(now, r.published_at, r.first_price, r.last_liq, r.last_seen)
            await conn.execute(
                text("""
                insert into mention_outcomes (mention_id, first_price_usd, first_price_observed_at,
                  liquidity_at_first_usd, price_24h_usd, price_7d_usd, price_30d_usd, max_gain_pct,
                  max_drawdown_pct, exit_feasible, outcome_status, updated_at)
                values (:id, :fp, :fa, :fl, :p24, :p7, :p30, :g, :d, :x, :s, now())
                on conflict (mention_id) do update set first_price_usd = excluded.first_price_usd,
                  first_price_observed_at = excluded.first_price_observed_at,
                  liquidity_at_first_usd = excluded.liquidity_at_first_usd,
                  price_24h_usd = excluded.price_24h_usd, price_7d_usd = excluded.price_7d_usd,
                  price_30d_usd = excluded.price_30d_usd, max_gain_pct = excluded.max_gain_pct,
                  max_drawdown_pct = excluded.max_drawdown_pct, exit_feasible = excluded.exit_feasible,
                  outcome_status = excluded.outcome_status, updated_at = now()
            """),
                {
                    "id": r.id,
                    "fp": r.first_price,
                    "fa": r.first_at,
                    "fl": r.first_liq,
                    "p24": r.p24,
                    "p7": r.p7d,
                    "p30": r.p30d,
                    "g": gain,
                    "d": dd,
                    "x": exit_ok,
                    "s": status,
                },
            )
            updated += 1
    return {"updated": updated}


_INDEPENDENT = text("""
with recent as (
  select d.token_id, d.cluster, m.content_hash
  from v_mention_detail d join social_mentions m on m.id = d.id
  where d.token_id = any(:ids) and not d.is_forwarded and d.published_at > now() - interval '7 days'
), dup as (
  select content_hash from recent where content_hash is not null
  group by content_hash having count(distinct cluster) > 1
)
select token_id, count(distinct case when content_hash in (select content_hash from dup)
                                     then 'dup:' || content_hash else cluster end) as n
from recent group by token_id
""")


async def independent_mentions(conn: AsyncConnection, token_ids: list[int]) -> dict[int, int] | None:
    """Independent original mentions per token over 7 days, or None if no source is monitored at all.

    Clusters (coordination group / influencer / channel) count once; forwards
    never count; identical text posted by several clusters counts once.
    """
    monitored = (await conn.execute(text("select count(*) from social_channels where enabled"))).scalar_one()
    if not monitored:
        return None
    if not token_ids:
        return {}
    rows = (await conn.execute(_INDEPENDENT, {"ids": token_ids})).all()
    return {r.token_id: r.n for r in rows}
