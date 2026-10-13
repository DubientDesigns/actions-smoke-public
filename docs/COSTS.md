# Estimated monthly operating cost

Target: **S$30–60/month, preferably less.** Exchange-rate assumptions
(approximate, check before budgeting): 1 USD ≈ S$1.30, 1 EUR ≈ S$1.45. Prices
are from research on 2026-10-13 and partly **UNVERIFIED** (see
[API_RESEARCH.md](API_RESEARCH.md)).

| Item | Choice | USD/EUR | S$/month | Notes |
|---|---|---|---|---|
| VPS | 2 vCPU / 4 GB (Hetzner CX23) **or** 2 GB (DigitalOcean/Vultr) | €5.49 – US$12 | **8 – 16** | 2 GB+ recommended. If the VPS has less than 2 GB, build the Next.js image elsewhere. Hetzner CX/CAX reportedly out of stock. |
| Database + auth | Supabase Free | 0 | **0** | 500 MB limit (sizing below). Pro is US$25 ≈ S$33 — **needs your approval**. |
| Market data | GeckoTerminal + DEX Screener public APIs | 0 | 0 | Keyless free tiers. |
| Security data | GoPlus free tier | 0 | 0 | May shrink (reported move to paid); degrades to "unknown". |
| AI reports | Claude Haiku 5.5, ≤ 20 reports/day, Batch API | ≈ US$0.6–1.2 | **≈ 1–2** | 20 × (10K in + 2K out) tokens/day. Hard cap default US$10/mo. Sonnet 5.5 for the same volume would be ≈ US$24/mo, so it is opt-in per report only. Max-plan API credits, if present on your account, would cover this. |
| Telegram bot | Bot API | 0 | 0 | |
| Wallet data (Phase 4) | Alchemy free, Helius free | 0 | 0 | Etherscan Lite (US$49) **not** planned. |
| Off-site backups | Cloudflare R2 / Backblaze B2 free 10 GB | 0 | 0 | Daily dumps are a few MB to tens of MB. |
| Domain (optional) | any .com | ≈ US$12/yr | ≈ 1.3 | Or a free DuckDNS subdomain. |
| **Total (free DB tier)** | | | **≈ S$10–20** | |
| Total if Supabase Pro is approved | | | ≈ S$43–53 | Still within budget. |

## Spending controls in code

* Every external call is metered in `api_usage` (calls, tokens, `cost_usd`).
* Per-provider daily call caps are enforced before each request (`DailyCapExceeded`).
* `app_settings.ai.budget`: `daily_request_cap`, `daily_token_cap`,
  `monthly_usd_cap`; AI is **disabled by default** (Phase 5).
* `app_settings.budget.monthly_budget_sgd` with alert thresholds at 50/80/100 %
  (Telegram alerts from Phase 5; the daily health report shows month-to-date
  metered cost now).
* No paid service is enabled without an explicit configuration change.

## Database size estimate (Supabase free tier, 500 MB)

| Data | Volume | Retention | Steady state |
|---|---|---|---|
| Raw snapshots | ~55K rows/day (≤ 300 tracked tokens × ~1.5 pools × 96 refreshes + discovery) at ~350 B with indexes | 3 days | ≈ 60 MB |
| Hourly snapshots | ~11K rows/day | 30 days | ≈ 90 MB |
| Daily snapshots | ~450 rows/day | indefinite | ≈ 5 MB/year |
| Tokens + pools | up to ~11K new pools/day if every page is new; most never reach liquidity | 14 days unless tracked or referenced | ≈ 100–150 MB |
| Runs, usage, health | ~1.5K runs + ~3K calls/day | 60 / 120 days | ≈ 30 MB |
| **Total** | | | **≈ 300 MB + Postgres overhead** |

That leaves only modest headroom. The daily health report shows the database
size. If it passes ~400 MB, options are:
(a) tighten `retention` / `discovery.max_tracked_tokens`;
(b) Supabase Pro (US$25/mo; needs approval);
(c) self-host Postgres on the VPS and keep Supabase for auth only (a larger
architectural change; needs approval).
