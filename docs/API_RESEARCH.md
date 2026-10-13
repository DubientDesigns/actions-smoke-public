# API research (as of 2026-10-13)

**How this was gathered.** The build sandbox's egress policy blocked every
provider host (GeckoTerminal, DEX Screener, GoPlus) and the documentation
fetcher could not resolve them either. Findings below come from web-search
results of official docs pages plus some third-party pages; anything not
confirmed from an official 2026 source is marked **UNVERIFIED**. Re-check the
live docs before relying on a number, and run `scripts/capture_fixtures.sh` +
`pytest -m live` on the VPS before treating any integration as working.

**Integration verification status**

| Integration | Code | Tested against real response? |
|---|---|---|
| GeckoTerminal `new_pools` | `providers/geckoterminal.py` | **No** — synthetic, doc-shaped payloads only |
| DEX Screener `tokens/v1`, `token-profiles/latest/v1` | `providers/dexscreener.py` | **No** — synthetic payloads only |
| GoPlus, RugCheck, Telegram, Claude, Alchemy, Helius | not yet built | — |

## GeckoTerminal (primary discovery)

* Base `https://api.geckoterminal.com/api/v2`, keyless public beta.
* **Rate limit: ~10 calls/min, "may fluctuate"** (current docs; older FAQ said
  30). We budget **8/min** and a daily cap of 8,000.
* `GET /networks/{network}/new_pools?page=N&include=base_token,quote_token,dex`:
  20 pools per page; pages beyond 10 require a paid plan; data refreshes ~60 s.
* Network ids: `eth`, `bsc`, `solana`, `base` (`eth` documented; others
  **UNVERIFIED** until `test_captured_network_ids_exist` passes).
* Attribution to GeckoTerminal/CoinGecko is required on the free tier — the
  dashboard shows it under every market table.
* Cheapest paid tier (CoinGecko Basic, keyed `api.coingecko.com/api/v3/onchain`)
  ≈ US$35/mo (**UNVERIFIED**). Not used.

## DEX Screener (market refresh, links)

* Base `https://api.dexscreener.com`, keyless.
* 60 rpm: `/token-profiles/latest/v1`, `/token-boosts/*`, `/orders/v1/*`
  (official reference). 300 rpm: `/latest/dex/*`, `/token-pairs/v1/*`,
  `/tokens/v1/{chainId}/{a,b,…}` (≤30 addresses) — **UNVERIFIED**, widely
  repeated. We budget **50/min** across all endpoints.
* Chain ids: `ethereum`, `bsc`, `solana`, `base` (`solana` confirmed; others
  **UNVERIFIED**).
* Terms (2023-08-18): commercial and non-commercial use allowed; no competing
  product; **no resale/redistribution**; revocable. A private dashboard fits.
* `token-profiles` are **paid** project listings — stored as promotional links
  (`source: dexscreener:paid_profile`), never as quality evidence.
* `marketCap` often equals `fdv` when circulating supply is unknown → stored
  as unknown market cap.

## GoPlus Security (Phase 3)

* Base `https://api.gopluslabs.io/api/v1`; free tier needs no key; app
  key/secret → access token for higher limits.
* Limits conflict across official pages: 30 calls/min (support docs) vs
  150 CU/min, 30K CU/day, 150K CU/month (pricing page). A CoinDesk report
  says token security moved toward a **paid model from end-2025**. Plan for
  the free tier to shrink; degrade to "unknown".
* `/token_security/{chain_id}?contract_addresses=…` (1, 56, 8453),
  `/solana/token_security?contract_addresses=…` (beta),
  `/rugpull_detecting/{chain_id}`, `/address_security/{address}`.
* EVM fields (**UNVERIFIED** names, "1"/"0" strings): `is_honeypot`,
  `buy_tax`, `sell_tax`, `cannot_sell_all`, `is_mintable`, `owner_address`,
  `can_take_back_ownership`, `hidden_owner`, `is_proxy`, `is_blacklisted`,
  `transfer_pausable`, `slippage_modifiable`, `holders[]`, `lp_holders[]`
  (`is_locked`), `is_open_source`, `creator_address`.
* Solana fields (**UNVERIFIED**): `mintable`, `freezable`, `closable`,
  `transfer_fee`, `transfer_hook`, `metadata_mutable`, `holders`.

## RugCheck (optional Solana cross-check)

`GET https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary`. Auth
requirement, limits and terms **UNVERIFIED** (some sources say an API key + a
wallet-signed JWT is needed). Seeded **disabled**.

## Telegram

* Bot API: ~30 msg/s global; ~20 msg/min per group (community figure);
  honour `retry_after` on 429. `sendMessage` text ≤ 4096 chars; use
  `parse_mode=HTML`.
* **Compliance risk:** Telegram's ToS added an explicit anti-scraping clause
  (2026-02-03) and the content-licensing terms forbid aggregating platform data
  or using it to deploy AI/ML models. Reading channels with a user account
  (MTProto/Telethon) and feeding text to an AI is in tension with these
  terms and risks account bans. **Design decision:** Phase 4 collects only
  messages delivered to *our bot* in chats where it is explicitly added, plus
  operator-entered mentions. A user-account reader is **not** built without
  your explicit approval.

## Anthropic Claude API (Phase 5)

* Per MTok: Haiku 5.5 $0.10 in / $0.50 out (≤100K-token prompts); Sonnet 5.5
  $2 / $10. Prompt-cache reads ~0.1×; Message Batches 50 % off.
* Structured outputs via JSON schema (`output_config.format`) or strict tools.
* **Claude Max and API credits:** Anthropic's current platform docs say Max
  plans include monthly API credits (US$100 Max 5x / US$200 Max 20x) once a
  Console organisation is linked; credits do not roll over. Older support
  articles say no API access is included. **Verify in your Console** — the
  budget below does not depend on these credits.

## Supabase

Free: 500 MB database, 5 GB egress, 2 projects; paused after 7 days of low
activity (constant worker writes should prevent this — **UNVERIFIED** whether
DB connections alone count as activity). Pro: US$25/mo, 8 GB DB.

## RPC / explorers (Phase 4 wallets)

* **Etherscan V2 free tier no longer covers BSC or Base** (Lite US$49/mo).
* Alchemy free: 30M CU/month, 25 req/s (covers Ethereum, Base; BNB **UNVERIFIED**).
* Helius free: 1M credits/month, 10 RPC req/s (Solana).
* Public Solana RPC: no SLA, not for production.

## Presale data

No reliable, free, ToS-compatible feed found. CryptoRank's free sandbox is
non-commercial (BY-NC-SA) and overview-only; public-sale data needs a US$1,490/yr
plan. PinkSale and ICODrops publish no API/RSS. **Plan:** manual watchlist plus
monitoring of official project channels the operator registers; optionally
read launchpad contracts on-chain later.

## VPS

Hetzner CX23 ≈ €5.49/mo after the June 2026 increase but **reportedly out of
stock since Sept 2026**; DigitalOcean from US$4–6/mo (1 GB); Vultr from
US$5 (1 GB). All **UNVERIFIED** on the providers' own pricing pages.
