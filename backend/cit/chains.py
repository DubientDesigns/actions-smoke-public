"""Chain registry and address normalisation.

Mirrors the `chains` seed rows in db/migrations/0001_core_schema.sql. The ids
must stay in sync; tests/test_migrations.py checks this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Chain:
    id: int
    slug: str
    name: str
    is_evm: bool
    evm_chain_id: int | None
    geckoterminal_network: str
    dexscreener_chain: str
    goplus_chain: str


CHAINS: tuple[Chain, ...] = (
    Chain(1, "bsc", "BNB Chain", True, 56, "bsc", "bsc", "56"),
    Chain(2, "ethereum", "Ethereum", True, 1, "eth", "ethereum", "1"),
    Chain(3, "solana", "Solana", False, None, "solana", "solana", "solana"),
    Chain(4, "base", "Base", True, 8453, "base", "base", "8453"),
)

BY_SLUG = {c.slug: c for c in CHAINS}
BY_ID = {c.id: c for c in CHAINS}
BY_GECKO = {c.geckoterminal_network: c for c in CHAINS}
BY_DEXSCREENER = {c.dexscreener_chain: c for c in CHAINS}

_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
# Base58 alphabet (no 0, O, I, l); Solana pubkeys are 32 bytes -> 32..44 chars.
_SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class InvalidAddress(ValueError):
    pass


def normalize_address(chain: Chain, address: str) -> str:
    """Return the canonical stored form of an address, or raise InvalidAddress.

    EVM addresses are case-insensitive (checksum casing is presentation only),
    so they are lowercased. Solana base58 is case-sensitive and kept as-is.
    """
    a = address.strip()
    if chain.is_evm:
        if not _EVM_RE.match(a):
            raise InvalidAddress(f"not an EVM address: {address!r}")
        return a.lower()
    if not _SOL_RE.match(a):
        raise InvalidAddress(f"not a Solana address: {address!r}")
    return a


def is_valid_address(chain: Chain, address: str) -> bool:
    try:
        normalize_address(chain, address)
    except InvalidAddress:
        return False
    return True


# Common quote / wrapped-native / stable assets. Pools are recorded for these,
# but they are never treated as "discovered" research targets.
QUOTE_ASSETS: dict[str, frozenset[str]] = {
    "bsc": frozenset(
        {
            "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
            "0x55d398326f99059ff775485246999027b3197955",  # USDT
            "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
            "0xe9e7cea3dedca5984780bafc599bd69add087d56",  # BUSD
            "0x2170ed0880ac9a755fd29b2688956bd959f933f8",  # ETH (Binance-Peg)
        }
    ),
    "ethereum": frozenset(
        {
            "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH
            "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC
            "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
            "0x6b175474e89094c44da98b954eedeac495271d0f",  # DAI
            "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",  # WBTC
        }
    ),
    "solana": frozenset(
        {
            "So11111111111111111111111111111111111111112",  # wSOL
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
        }
    ),
    "base": frozenset(
        {
            "0x4200000000000000000000000000000000000006",  # WETH
            "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # USDC
            "0x50c5725949a6f0c72e6c4a641f24049a917db0cb",  # DAI
        }
    ),
}


def is_quote_asset(chain: Chain, normalized_address: str) -> bool:
    return normalized_address in QUOTE_ASSETS.get(chain.slug, frozenset())
