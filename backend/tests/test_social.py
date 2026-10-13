"""Social intelligence: Telegram collection, mention resolution, outcomes, independence.

HTTP is mocked with SYNTHETIC payloads (fixtures/synthetic); the database is real.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from cit.config import Settings
from cit.providers.telegram import parse_updates
from cit.services import social
from cit.services.runtime import ProviderRuntime

from .helpers import synthetic

TOKEN = "123456:TEST-BOT-TOKEN"
TG = f"https://api.telegram.org/bot{TOKEN}"
FOO = "0x2222222222222222222222222222222222222222"


def runtime(engine, **kw) -> ProviderRuntime:
    return ProviderRuntime(Settings(global_rate_limit_per_minute=100000, **kw), engine, http=httpx.AsyncClient())


def register_channel(conn, external_id="-1001111111111", influencer=None, official=False):
    inf_id = None
    if influencer:
        inf_id = conn.execute(
            "insert into influencers (display_name) values (%s) returning id", (influencer,)
        ).fetchone()[0]
    ch = conn.execute(
        "insert into social_channels (platform, external_id, handle, title, influencer_id, access_basis, "
        "is_official_project) values ('telegram', %s, 'alphacalls', 'Alpha Calls', %s, 'public', %s) returning id",
        (external_id, inf_id, official),
    ).fetchone()[0]
    return ch, inf_id


def test_parse_updates_skips_edits_and_hides_forwarding_users():
    msgs, max_id = parse_updates(synthetic("telegram_updates.json"))
    assert max_id == 1005 and len(msgs) == 4
    fwd = next(m for m in msgs if m.is_forwarded)
    assert fwd.forwarded_from == "user (hidden)"
    assert msgs[0].link == "https://t.me/alphacalls/55"
    assert msgs[0].urls == ("https://dexscreener.com/bsc/0x2222222222222222222222222222222222222222",)


@respx.mock
async def test_collect_telegram_registered_only(engine, clean_db):
    clean_db.execute(
        "update data_sources set enabled = true, rate_limit_per_minute = 100000 where slug = 'telegram_bot'"
    )
    clean_db.execute("insert into tokens (chain_id, address, symbol) values (1, %s, 'FOO')", (FOO,))
    register_channel(clean_db, influencer="Alpha")
    route = respx.get(f"{TG}/getUpdates").mock(
        return_value=httpx.Response(200, json=synthetic("telegram_updates.json"))
    )
    rt = runtime(engine, telegram_bot_token=TOKEN)

    res = await social.collect_telegram(rt)
    assert res == {"updates": 4, "stored": 2, "unregistered": 1, "ignored_chats": 0}
    rows = clean_db.execute(
        "select contract_address, token_id is not null, category, promo_disclosure, is_forwarded, forwarded_from, "
        "referral_links, mentioned_symbols, source_url from social_mentions order by published_at"
    ).fetchall()
    call, promo = rows
    assert call[0] == FOO and call[1] is True and call[2] == "call" and call[8] == "https://t.me/alphacalls/55"
    assert promo[0] is None and promo[3] == "disclosed" and promo[4] is True and promo[5] == "user (hidden)"
    assert promo[6] == ["https://launch.example/sale?ref=xyz"] and promo[7] == ["BAR"]
    # Unregistered chat: metadata only, its content is never stored.
    req = clean_db.execute("select external_id, title, messages_seen, status from social_chat_requests").fetchone()
    assert req == ("-1002222222222", "Unregistered Group", 1, "pending")
    assert (
        clean_db.execute("select count(*) from social_mentions where text_excerpt like '%secret%'").fetchone()[0] == 0
    )
    # "gm" chatter without any contract or cashtag is discarded.
    assert clean_db.execute("select count(*) from social_mentions where text_excerpt like 'gm%'").fetchone()[0] == 0

    await social.collect_telegram(rt)
    assert route.calls[1].request.url.params["offset"] == "1006"
    assert clean_db.execute("select count(*) from social_mentions").fetchone()[0] == 2  # idempotent
    await rt.http.aclose()


async def test_collect_telegram_skipped_without_token(engine, clean_db):
    assert "skipped" in await social.collect_telegram(runtime(engine))


@respx.mock
async def test_bot_token_never_in_errors(engine, clean_db):
    clean_db.execute(
        "update data_sources set enabled = true, rate_limit_per_minute = 100000 where slug = 'telegram_bot'"
    )
    respx.get(f"{TG}/getUpdates").mock(side_effect=httpx.ConnectError(f"failed {TG}/getUpdates"))
    rt = runtime(engine, telegram_bot_token=TOKEN)
    (await rt.telegram()).client.policy.max_retries = 0
    res = await social.collect_telegram(rt)
    assert TOKEN not in res["error"]
    err = clean_db.execute("select last_error from data_sources where slug = 'telegram_bot'").fetchone()[0]
    assert TOKEN not in err and "***" in err
    await rt.http.aclose()


@respx.mock
async def test_resolve_mentions_discovers_chain(engine, clean_db):
    ch, _ = register_channel(clean_db)
    clean_db.execute("update data_sources set rate_limit_per_minute = 100000")
    clean_db.execute(
        "insert into social_mentions (channel_id, external_message_id, published_at, contract_address) "
        "values (%s, '1', now(), %s)",
        (ch, FOO),
    )
    respx.get(url__startswith="https://api.dexscreener.com/latest/dex/tokens/").mock(
        return_value=httpx.Response(200, json={"pairs": synthetic("ds_tokens_v1_bsc.json")})
    )
    rt = runtime(engine)
    res = await social.resolve_mentions(rt)
    assert res["mentions_linked"] == 1
    tok, chain = clean_db.execute(
        "select t.address, c.slug from social_mentions m join tokens t on t.id = m.token_id "
        "join chains c on c.id = m.chain_id"
    ).fetchone()
    assert (tok, chain) == (FOO, "bsc")
    await rt.http.aclose()


def _snap(conn, pool, token, when, price, liq=50000):
    conn.execute(
        "insert into market_snapshots (pool_id, token_id, source_id, observed_at, price_usd, liquidity_usd) "
        "values (%s, %s, 1, %s, %s, %s)",
        (pool, token, when, price, liq),
    )


async def test_mention_outcomes_use_only_prices_after_publication(engine, clean_db):
    ch, _ = register_channel(clean_db)
    tok = clean_db.execute("insert into tokens (chain_id, address) values (1, %s) returning id", (FOO,)).fetchone()[0]
    pool = clean_db.execute(
        "insert into pools (chain_id, address, base_token_id) values (1, '0xp', %s) returning id", (tok,)
    ).fetchone()[0]
    now = datetime.now(UTC)
    published = now - timedelta(days=8)
    _snap(clean_db, pool, tok, published - timedelta(minutes=5), 0.5)  # before mention: must be ignored
    _snap(clean_db, pool, tok, published + timedelta(minutes=10), 1.0)  # first observable price
    _snap(clean_db, pool, tok, published + timedelta(hours=3), 3.0)  # peak
    _snap(clean_db, pool, tok, published + timedelta(hours=25), 0.6)  # 24h
    _snap(clean_db, pool, tok, published + timedelta(days=7, hours=1), 0.4, liq=30000)  # 7d, trough
    _snap(clean_db, pool, tok, now - timedelta(hours=1), 0.45, liq=30000)
    clean_db.execute(
        "insert into pool_latest (pool_id, token_id, source_id, observed_at, liquidity_usd) "
        "values (%s, %s, 1, now(), 30000)",
        (pool, tok),
    )
    mid = clean_db.execute(
        "insert into social_mentions (channel_id, external_message_id, published_at, token_id) "
        "values (%s, '1', %s, %s) returning id",
        (ch, published, tok),
    ).fetchone()[0]
    await social.update_mention_outcomes(runtime(engine))
    o = clean_db.execute(
        "select first_price_usd, price_24h_usd, price_7d_usd, price_30d_usd, max_gain_pct, "
        "max_drawdown_pct, exit_feasible, outcome_status from mention_outcomes where mention_id = %s",
        (mid,),
    ).fetchone()
    assert float(o[0]) == 1.0 and float(o[1]) == 0.6 and float(o[2]) == 0.4 and o[3] is None
    assert float(o[4]) == pytest.approx(200) and float(o[5]) == pytest.approx(-60)
    assert o[6] is False  # $30k liquidity * 2% < $1,000 reference position
    assert o[7] == "tracking"


async def test_no_price_outcome_is_recorded_not_dropped(engine, clean_db):
    ch, _ = register_channel(clean_db)
    tok = clean_db.execute("insert into tokens (chain_id, address) values (1, %s) returning id", (FOO,)).fetchone()[0]
    clean_db.execute(
        "insert into social_mentions (channel_id, external_message_id, published_at, token_id) "
        "values (%s, '1', now() - interval '5 days', %s)",
        (ch, tok),
    )
    await social.update_mention_outcomes(runtime(engine))
    assert clean_db.execute("select outcome_status from mention_outcomes").fetchone()[0] == "no_price"
    stats = clean_db.execute("select projects, no_price from v_influencer_stats").fetchall()
    assert stats == []  # channel has no influencer; covered below with one


async def test_independent_mentions_and_coordination(engine, clean_db):
    tok = clean_db.execute("insert into tokens (chain_id, address) values (1, %s) returning id", (FOO,)).fetchone()[0]
    async with engine.connect() as conn:
        assert await social.independent_mentions(conn, [tok]) is None  # nothing monitored -> unknown
    a, inf_a = register_channel(clean_db, "-1", influencer="A")
    a2 = clean_db.execute(
        "insert into social_channels (platform, external_id, influencer_id, access_basis) "
        "values ('x', 'a_alt', %s, 'public') returning id",
        (inf_a,),
    ).fetchone()[0]
    b, _inf_b = register_channel(clean_db, "-2", influencer="B")
    c, inf_c = register_channel(clean_db, "-3", influencer="C")
    d, inf_d = register_channel(clean_db, "-4", influencer="D")
    clean_db.execute("update influencers set coordination_group = 'ring1' where id in (%s, %s)", (inf_c, inf_d))

    def mention(ch, ext, mins_ago, fwd=False, h=None, refs=()):
        clean_db.execute(
            "insert into social_mentions (channel_id, external_message_id, published_at, token_id, is_forwarded, "
            "content_hash, referral_links) values (%s, %s, now() - make_interval(mins => %s), %s, %s, %s, %s)",
            (ch, ext, mins_ago, tok, fwd, h, list(refs)),
        )

    mention(a, "1", 60)  # influencer A
    mention(a2, "2", 50)  # same influencer A on another account -> same cluster
    mention(b, "3", 40, h="copy", refs=["https://x.example/?ref=1"])  # B shares a referral link with ring1
    mention(c, "4", 30, h="copy", refs=["https://x.example/?ref=1"])  # ring1, same text as B -> collapses
    mention(d, "5", 20)  # ring1 again -> same cluster
    mention(b, "6", 10, fwd=True)  # forwards never count
    async with engine.connect() as conn:
        counts = await social.independent_mentions(conn, [tok])
    # Clusters: influencer:A, and {B, ring1} collapse via identical text "copy" -> A + dup:copy + ring1(d) = 3
    assert counts == {tok: 3}
    signals = {r[0] for r in clean_db.execute("select signal from v_coordination_signals").fetchall()}
    assert {"same_token_30min", "shared_referral_link", "identical_text"} <= signals
    # A referral link shared only inside one known coordination group is not a new signal.
    clean_db.execute("update social_mentions set referral_links = '{}' where external_message_id = '3'")
    signals = {r[0] for r in clean_db.execute("select signal from v_coordination_signals").fetchall()}
    assert "shared_referral_link" not in signals
    stats = {r[0]: r[1] for r in clean_db.execute("select display_name, mentions from v_influencer_stats").fetchall()}
    assert stats["A"] == 2 and stats["B"] == 2


def test_outcome_status_rules():
    now = datetime(2026, 10, 13, tzinfo=UTC)
    assert social.outcome_status(now, now - timedelta(hours=1), None, None, None) == "pending"
    assert social.outcome_status(now, now - timedelta(days=3), None, None, None) == "no_price"
    assert social.outcome_status(now, now - timedelta(days=3), 1, 500, now) == "untradeable"
    assert social.outcome_status(now, now - timedelta(days=3), 1, 50000, now - timedelta(days=4)) == "delisted"
    assert social.outcome_status(now, now - timedelta(days=40), 1, 50000, now) == "final"
    assert json.dumps("ok")
