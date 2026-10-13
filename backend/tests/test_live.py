"""Verification against REAL provider data. Skipped by default.

Two modes (both `pytest -m live`):
  * captured fixtures in fixtures/live/ (scripts/capture_fixtures.sh), and
  * direct calls to the providers (needs outbound network access).
An integration is only considered verified once these pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from cit.appsettings import SecurityPolicy
from cit.chains import BY_GECKO, BY_SLUG, CHAINS
from cit.providers import dexscreener, geckoterminal, goplus
from cit.providers.http import ProviderClient
from cit.security.engine import evaluate

LIVE = Path(__file__).parent / "fixtures" / "live"
pytestmark = pytest.mark.live


def _load(name: str):
    p = LIVE / f"{name}.json"
    if not p.exists():
        pytest.skip(f"{p.name} not captured; run scripts/capture_fixtures.sh")
    return json.loads(p.read_text())


@pytest.mark.parametrize("net", ["bsc", "eth", "solana", "base"])
def test_captured_geckoterminal_new_pools_parse(net):
    payload = _load(f"gt_new_pools_{net}")
    obs = geckoterminal.parse_pools(BY_GECKO[net], payload)
    assert len(obs) >= len(payload["data"]) * 0.9, "parser dropped too many real pools"
    assert all(o.base.address for o in obs)
    assert sum(o.market.price_usd is not None for o in obs) >= len(obs) * 0.8
    assert sum(o.pool_created_at is not None for o in obs) >= len(obs) * 0.8


def test_captured_network_ids_exist():
    ids = {n["id"] for n in _load("gt_networks")["data"]}
    # Only page 1 is captured; eth/bsc/solana/base are among the largest networks.
    assert {c.geckoterminal_network for c in CHAINS} <= ids


@pytest.mark.parametrize("chain", ["base", "solana"])
def test_captured_dexscreener_pairs_parse(chain):
    obs = dexscreener.parse_pairs(_load(f"ds_tokens_v1_{chain}"))
    assert obs and all(o.chain_slug == chain for o in obs)
    assert any(o.market.liquidity_usd for o in obs)


def test_captured_dexscreener_profiles_parse():
    dexscreener.parse_token_profiles(_load("ds_token_profiles"))


async def test_direct_geckoterminal_and_dexscreener():
    async with httpx.AsyncClient(timeout=20) as http:
        try:
            gt = geckoterminal.GeckoTerminal(ProviderClient(geckoterminal.policy(), http=http))
            obs = await gt.new_pools("base")
            ds = dexscreener.DexScreener(ProviderClient(dexscreener.policy(), http=http))
            pairs = await ds.pairs_for_tokens("base", ["0x4200000000000000000000000000000000000006"])
        except Exception as exc:  # network blocked etc.
            pytest.skip(f"providers unreachable: {exc}")
    assert obs and pairs
    assert BY_SLUG["base"]


@pytest.mark.parametrize("name,chain,address", [
    ("goplus_evm_bsc", "bsc", "0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82"),
    ("goplus_solana", "solana", "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"),
])
def test_captured_goplus_maps_core_checks(name, chain, address):
    res = goplus.parse_envelope(chain, address, _load(name))
    assert res.found, "token missing from real GoPlus response"
    a = evaluate(chain, res.found, res.data, SecurityPolicy())
    known = [c.key for c in a.checks if c.status in ("pass", "warn", "risk")]
    # If the real field names differ from the documented ones, most checks become
    # "unknown" -- fail loudly instead of silently under-assessing.
    assert len(known) >= 5, f"only {known} resolved; check GoPlus field names"
