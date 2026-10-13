"""Parser tests against SYNTHETIC, documentation-shaped payloads (see fixtures/synthetic/README.md)."""

from decimal import Decimal

from cit.chains import BY_SLUG
from cit.providers import dexscreener, geckoterminal
from cit.providers.models import market_cap_or_none

from .helpers import synthetic


def test_geckoterminal_new_pools():
    obs = geckoterminal.parse_pools(BY_SLUG["bsc"], synthetic("gt_new_pools_bsc.json"))
    assert len(obs) == 2  # garbage item skipped, not guessed
    foo = obs[0]
    assert foo.pool_address == "0x1111111111111111111111111111111111111111"
    assert foo.base.address == "0x2222222222222222222222222222222222222222"
    assert foo.base.symbol == "FOO" and foo.base.decimals == 18
    assert foo.quote.address == "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"  # normalised
    assert foo.dex == "pancakeswap_v2"
    assert foo.market.price_usd == Decimal("0.000123456789")
    assert foo.market.liquidity_usd == Decimal("25000.55")
    assert foo.market.buys_m5 == 4 and foo.market.sells_h24 == 22
    assert foo.market.fdv_usd == Decimal("123456.78")
    assert foo.market.market_cap_usd is None
    assert foo.pool_created_at.isoformat() == "2026-10-13T07:30:00+00:00"


def test_geckoterminal_missing_values_are_unknown_not_zero():
    bar = geckoterminal.parse_pools(BY_SLUG["bsc"], synthetic("gt_new_pools_bsc.json"))[1]
    # Base token not in `included`: address recovered from relationship id, metadata unknown.
    assert bar.base.address == "0x4444444444444444444444444444444444444444"
    assert bar.base.symbol is None
    assert bar.market.liquidity_usd is None          # "not-a-number" -> unknown
    assert bar.market.volume_h24_usd is None
    assert bar.market.buys_h1 is None
    # Market cap equal to FDV is treated as unknown, never as a real market cap.
    assert bar.market.fdv_usd == Decimal("500000")
    assert bar.market.market_cap_usd is None


def test_market_cap_never_substitutes_fdv():
    assert market_cap_or_none(Decimal(5), Decimal(5)) is None
    assert market_cap_or_none(Decimal(4), Decimal(5)) == Decimal(4)
    assert market_cap_or_none(Decimal(0), Decimal(5)) is None
    assert market_cap_or_none(Decimal(4), None) == Decimal(4)


def test_dexscreener_pairs():
    obs = dexscreener.parse_pairs(synthetic("ds_tokens_v1_bsc.json"))
    assert len(obs) == 2  # unsupported chain dropped
    a, b = obs
    assert a.pool_address == "0x1111111111111111111111111111111111111111"
    assert a.base.address == b.base.address == "0x2222222222222222222222222222222222222222"
    assert a.market.liquidity_usd == Decimal("26000.5")
    assert a.market.market_cap_usd is None and a.market.fdv_usd == Decimal(126000)
    assert b.market.market_cap_usd == Decimal(90000)
    assert a.pool_created_at is not None and a.pool_created_at.tzinfo is not None
    urls = {li.url for li in a.links}
    assert urls == {"https://foo.example", "https://x.com/foo", "https://t.me/foo"}  # javascript: URL rejected
    assert {li.type for li in a.links} == {"website", "twitter", "telegram"}


def test_dexscreener_only_chains_filter():
    assert dexscreener.parse_pairs(synthetic("ds_tokens_v1_bsc.json"), only_chains=["base"]) == []


def test_dexscreener_profiles_are_paid_listings():
    profiles = dexscreener.parse_token_profiles(synthetic("ds_token_profiles.json"))
    assert len(profiles) == 1
    p = profiles[0]
    assert p.chain_slug == "solana" and p.is_paid_listing
    assert p.token_address == "SyntheticMint1111111111111111111111111111"
