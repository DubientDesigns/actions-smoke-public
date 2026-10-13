"""GoPlus Security API adapter (token security heuristics; NOT an audit).

Docs: https://docs.gopluslabs.io/reference/api-overview
  EVM:    GET /token_security/{chain_id}?contract_addresses=<addr>
  Solana: GET /solana/token_security?contract_addresses=<mint>   (beta)
Response envelope: {"code": 1, "message": "OK", "result": {"<address>": {...}}}
Field values are mostly strings ("1"/"0"/""); taxes are fractions ("0.05" = 5 %).

Field names follow the published docs but have NOT been verified against a
live response from this project's environment (see docs/API_RESEARCH.md);
the parser therefore treats anything absent or unexpected as unknown.
One address per call: batching on the keyless tier is unverified.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cit.chains import BY_SLUG
from cit.providers.http import ProviderClient, ProviderError, ProviderPolicy

SOURCE = "goplus"
BASE_URL = "https://api.gopluslabs.io/api/v1"

# GoPlus envelope codes. 1 = OK, 2 = partial data. Anything else is an error
# (rate limiting is reported this way as well as via HTTP 429).
OK_CODES = {1, 2}


def policy(rate_per_minute: float = 20, daily_cap: int | None = 5000) -> ProviderPolicy:
    return ProviderPolicy(SOURCE, BASE_URL, rate_per_minute, daily_cap)


@dataclass(frozen=True)
class GoPlusResult:
    chain_slug: str
    address: str
    found: bool
    partial: bool
    data: dict[str, Any]
    observed_at: datetime


def parse_envelope(chain_slug: str, address: str, payload: Any, observed_at: datetime | None = None) -> GoPlusResult:
    observed_at = observed_at or datetime.now(UTC)
    if not isinstance(payload, dict):
        raise ProviderError(SOURCE, "unexpected payload type")
    code = payload.get("code")
    if code not in OK_CODES:
        raise ProviderError(SOURCE, f"envelope code {code!r}: {str(payload.get('message'))[:200]}")
    result = payload.get("result") or {}
    if not isinstance(result, dict):
        raise ProviderError(SOURCE, "unexpected result type")
    # EVM keys come back lowercased; Solana mints keep case. Match either way.
    data = result.get(address)
    if data is None:
        lowered = {str(k).lower(): v for k, v in result.items()}
        data = lowered.get(address.lower())
    if not isinstance(data, dict) or not data:
        return GoPlusResult(chain_slug, address, False, code == 2, {}, observed_at)
    return GoPlusResult(chain_slug, address, True, code == 2, data, observed_at)


class GoPlus:
    def __init__(self, client: ProviderClient):
        self.client = client

    async def token_security(self, chain_slug: str, address: str) -> GoPlusResult:
        chain = BY_SLUG[chain_slug]
        if chain.is_evm:
            path, endpoint = f"/token_security/{chain.goplus_chain}", "token_security_evm"
        else:
            path, endpoint = "/solana/token_security", "token_security_solana"
        payload = await self.client.get_json(path, {"contract_addresses": address}, endpoint=endpoint)
        return parse_envelope(chain_slug, address, payload)
