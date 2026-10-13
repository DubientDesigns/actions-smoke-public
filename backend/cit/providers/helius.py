"""Helius adapter: parsed Solana transactions for tracked wallets.

Docs: https://www.helius.dev/docs/api-reference/enhanced-transactions
  GET /v0/addresses/{address}/transactions?api-key=...&limit=..&until=<signature>
Response fields (signature, timestamp, type, tokenTransfers, nativeTransfers)
follow the docs and are UNVERIFIED against a live response. The API key is a
query parameter and is redacted from errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from cit.providers.http import ProviderClient, ProviderError, ProviderPolicy

SOURCE = "helius"
LAMPORTS = Decimal(1_000_000_000)
WSOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", WSOL}


def policy(api_key: str, rate_per_minute: float = 30, daily_cap: int | None = 20000) -> ProviderPolicy:
    return ProviderPolicy(SOURCE, "https://api.helius.xyz/v0", rate_per_minute, daily_cap, redact=(api_key,))


@dataclass(frozen=True)
class SolEvent:
    signature: str
    index: int
    block_time: datetime
    event_type: str  # buy | sell | transfer_in | transfer_out
    mint: str | None  # None = native SOL
    amount: Decimal | None
    counterparty: str | None
    raw: dict[str, Any]


def _dec(v: Any) -> Decimal | None:
    try:
        return Decimal(str(v)) if v is not None else None
    except (InvalidOperation, ValueError):
        return None


def parse_transactions(payload: Any, wallet: str) -> list[SolEvent]:
    if not isinstance(payload, list):
        raise ProviderError(SOURCE, "unexpected transactions payload")
    out: list[SolEvent] = []
    for tx in payload:
        if not isinstance(tx, dict) or not tx.get("signature") or not isinstance(tx.get("timestamp"), int):
            continue
        when = datetime.fromtimestamp(tx["timestamp"], tz=UTC)
        is_swap = str(tx.get("type", "")).upper() == "SWAP"
        idx = 0
        for t in tx.get("tokenTransfers") or []:
            if not isinstance(t, dict):
                continue
            frm, to, mint = t.get("fromUserAccount"), t.get("toUserAccount"), t.get("mint")
            if wallet not in (frm, to):
                continue
            incoming = to == wallet
            if is_swap and mint not in STABLES:
                etype = "buy" if incoming else "sell"
            else:
                etype = "transfer_in" if incoming else "transfer_out"
            out.append(
                SolEvent(
                    tx["signature"],
                    idx,
                    when,
                    etype,
                    mint,
                    _dec(t.get("tokenAmount")),
                    frm if incoming else to,
                    {"type": tx.get("type"), "source": tx.get("source")},
                )
            )
            idx += 1
        for n in tx.get("nativeTransfers") or []:
            if not isinstance(n, dict) or wallet not in (n.get("fromUserAccount"), n.get("toUserAccount")):
                continue
            incoming = n.get("toUserAccount") == wallet
            lamports = _dec(n.get("amount"))
            out.append(
                SolEvent(
                    tx["signature"],
                    idx,
                    when,
                    "transfer_in" if incoming else "transfer_out",
                    None,
                    lamports / LAMPORTS if lamports is not None else None,
                    n.get("fromUserAccount") if incoming else n.get("toUserAccount"),
                    {"type": tx.get("type"), "native": True},
                )
            )
            idx += 1
    return out


class Helius:
    def __init__(self, client: ProviderClient, api_key: str):
        self.client = client
        self.api_key = api_key

    async def transactions(self, wallet: str, until: str | None) -> tuple[list[SolEvent], str | None]:
        params: dict[str, Any] = {"api-key": self.api_key, "limit": 100}
        if until:
            params["until"] = until
        payload = await self.client.get_json(
            f"/addresses/{wallet}/transactions", params, endpoint="address_transactions"
        )
        newest = (
            payload[0].get("signature")
            if isinstance(payload, list) and payload and isinstance(payload[0], dict)
            else None
        )
        return parse_transactions(payload, wallet), newest
