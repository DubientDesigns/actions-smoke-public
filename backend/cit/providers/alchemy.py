"""Alchemy adapter: ERC-20 and native transfers for tracked EVM wallets.

Docs: https://docs.alchemy.com/reference/alchemy-getassettransfers (JSON-RPC POST).
Network subdomains: eth-mainnet, base-mainnet, bnb-mainnet (BNB support on the
free tier is UNVERIFIED). The API key is part of the URL and is redacted from
errors. Response shapes are from the docs and unverified against a live call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from cit.providers.http import ProviderClient, ProviderError, ProviderPolicy
from cit.providers.models import ts_iso

SOURCE = "alchemy"
NETWORKS = {"ethereum": "eth-mainnet", "base": "base-mainnet", "bsc": "bnb-mainnet"}
# Roughly 7 days of blocks, used only for a wallet's first sync.
INITIAL_LOOKBACK_BLOCKS = {"ethereum": 50_400, "base": 302_400, "bsc": 201_600}


def policy(chain_slug: str, api_key: str, rate_per_minute: float = 30, daily_cap: int | None = 20000) -> ProviderPolicy:
    return ProviderPolicy(
        SOURCE,
        f"https://{NETWORKS[chain_slug]}.g.alchemy.com/v2/{api_key}",
        rate_per_minute,
        daily_cap,
        redact=(api_key,),
    )


@dataclass(frozen=True)
class Transfer:
    tx_hash: str
    log_index: int
    block_number: int
    block_time: datetime
    direction: str  # in | out
    token_address: str | None  # None = native coin
    amount: Decimal | None
    counterparty: str | None
    raw: dict[str, Any]


def _rpc_result(payload: Any) -> Any:
    if not isinstance(payload, dict):
        raise ProviderError(SOURCE, "unexpected JSON-RPC payload")
    if payload.get("error"):
        raise ProviderError(SOURCE, f"JSON-RPC error: {str(payload['error'])[:200]}")
    return payload.get("result")


def parse_transfers(payload: Any, wallet: str) -> tuple[list[Transfer], str | None]:
    result = _rpc_result(payload) or {}
    w = wallet.lower()
    out: list[Transfer] = []
    for t in result.get("transfers") or []:
        if not isinstance(t, dict):
            continue
        frm, to = str(t.get("from") or "").lower(), str(t.get("to") or "").lower()
        if w not in (frm, to):
            continue
        when = ts_iso((t.get("metadata") or {}).get("blockTimestamp"))
        try:
            block = int(str(t.get("blockNum")), 16)
        except ValueError:
            continue
        if when is None or not t.get("hash"):
            continue
        unique = str(t.get("uniqueId") or "")
        log_index = int(unique.rsplit(":", 1)[1]) if ":log:" in unique and unique.rsplit(":", 1)[1].isdigit() else -1
        raw_contract = t.get("rawContract") or {}
        token = raw_contract.get("address") if t.get("category") in ("erc20", "token") else None
        try:
            amount = Decimal(str(t["value"])) if t.get("value") is not None else None
        except (InvalidOperation, ValueError):
            amount = None
        out.append(
            Transfer(
                str(t["hash"]).lower(),
                log_index,
                block,
                when,
                "out" if frm == w else "in",
                token.lower() if isinstance(token, str) else None,
                amount,
                to if frm == w else frm,
                {k: t.get(k) for k in ("asset", "category", "uniqueId")},
            )
        )
    return out, result.get("pageKey")


class Alchemy:
    def __init__(self, client: ProviderClient):
        self.client = client

    async def block_number(self) -> int:
        res = _rpc_result(
            await self.client.post_json(
                "", {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}, endpoint="eth_blockNumber"
            )
        )
        return int(str(res), 16)

    async def transfers(self, wallet: str, from_block: int, direction: str) -> list[Transfer]:
        params: dict[str, Any] = {
            "fromBlock": hex(from_block),
            "toBlock": "latest",
            "category": ["external", "erc20"],
            "withMetadata": True,
            "excludeZeroValue": True,
            "maxCount": "0x64",
            "order": "asc",
            ("fromAddress" if direction == "out" else "toAddress"): wallet,
        }
        payload = await self.client.post_json(
            "",
            {"jsonrpc": "2.0", "id": 1, "method": "alchemy_getAssetTransfers", "params": [params]},
            endpoint="getAssetTransfers",
        )
        transfers, _ = parse_transfers(payload, wallet)
        return transfers
