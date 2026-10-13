#!/usr/bin/env bash
# Capture REAL provider responses into backend/tests/fixtures/live/ so the
# parsers can be verified against actual data (pytest -m live).
# Run from a host that can reach the providers (e.g. the VPS). ~8 requests total,
# spaced out to respect GeckoTerminal's ~10 calls/minute public limit.
set -euo pipefail
cd "$(dirname "$0")/../backend/tests/fixtures/live"

fetch() { # name url
  echo "-> $1"
  curl -sS --fail -m 30 -H 'Accept: application/json' -o "$1.json" "$2"
  sleep 7
}

for net in bsc eth solana base; do
  fetch "gt_new_pools_${net}" "https://api.geckoterminal.com/api/v2/networks/${net}/new_pools?page=1&include=base_token,quote_token,dex"
done
fetch gt_networks "https://api.geckoterminal.com/api/v2/networks?page=1"
fetch ds_token_profiles "https://api.dexscreener.com/token-profiles/latest/v1"
# Wrapped-native tokens: always have pairs.
fetch ds_tokens_v1_base "https://api.dexscreener.com/tokens/v1/base/0x4200000000000000000000000000000000000006"
fetch ds_tokens_v1_solana "https://api.dexscreener.com/tokens/v1/solana/So11111111111111111111111111111111111111112"
echo "Captured into $(pwd). Now run: cd backend && uv run pytest -m live -v"
