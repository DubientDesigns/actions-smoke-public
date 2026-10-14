# Ingestion schedule and rate-limit budget

All jobs run in the `worker` container (`cit/worker/scheduler.py`). Every
outbound call goes through a per-provider token bucket, a global bucket
(120/min), a daily cap, retries with backoff, and a circuit breaker. Budgets
live in `data_sources` and can be changed without a deploy.

| Job | Every | Provider / endpoint | Calls per run | Calls/day (typ.) | Budget used |
|---|---|---|---|---|---|
| `discover_new_pools` | 10 min | GeckoTerminal `new_pools` × 4 chains | 4 (8 when a page is full) | 576–1,152 | limiter 8/min vs ~10/min documented; cap 8,000/day |
| `ingest_token_profiles` | 10 min | DEX Screener `token-profiles/latest/v1` | 1 | 144 | 60 rpm endpoint |
| `refresh_tracked_markets` | 15 min | DEX Screener `tokens/v1` (30 addresses/call) | ≤ ⌈tracked/30⌉ per chain ≈ 10–13 | ~1,000–1,250 | limiter 50/min vs 300 rpm; cap 40,000/day |
| `check_sources` | 5 min | — (database) | 0 | 0 | — |
| `apply_retention` | 03:15 SGT | — | 0 | 0 | — |
| `daily_health_report` | 08:00 SGT | — (Telegram from Phase 5) | 0 | 0 | — |
| `assess_security` | 10 min | GoPlus `token_security` (1 address/call) | ≤ 25 (never-assessed first, then stale, deepest liquidity first) | ~150–400 typ., ≤ 3,600 max | limiter 20/min, cap 5,000/day |
| `score_tokens` | 15 min | — (database) | 0 | 0 | stores a row only on material change |
| `collect_telegram` | 2 min | Telegram Bot `getUpdates` | 1 | 720 | well below Bot API limits; skipped without a token |
| `resolve_mentions` | 15 min | DEX Screener `latest/dex/tokens` + `tokens/v1/solana` | ≤ 3 (only unresolved contracts) | ≤ 288 | shares the 50/min budget |
| `update_mention_outcomes` | 30 min | — (database) | 0 | 0 | — |
| `score_presales` | 30 min | — (database) | 0 | 0 | stores only when inputs change |
| `sync_wallets` | 15 min | Alchemy `alchemy_getAssetTransfers` (2/EVM wallet) · Helius (1/Solana wallet) | 1–3 per wallet | 20 wallets ≈ 4,000 | 30/min per source; free-tier credits ample for tens of wallets |
| `generate_alerts` | 10 min | — (database) | 0 | 0 | dedup + cooldowns per alert key |
| `dispatch_alerts` | 1 min | Telegram Bot `sendMessage` | ≤ 12/hour (critical exempt) | ≤ ~300 | quiet hours 23:00–07:30 SGT |
| `daily_health_report` | 08:00 SGT | Telegram Bot `sendMessage` | 1–2 | 1–2 | digest + health report |
| `generate_research_reports` | hourly (:20) | Claude Messages API (`claude-haiku-5-5`) | ≤ 5 | ≤ 20 (cap) | daily request/token caps, US$10/month hard cap |
| `paper_cycle` | 2 min | — (database) | 0 | 0 | fills due orders, marks positions, stop-loss/take-profit/max-hold |
| `evaluate_strategies` | 15 min | — (database) | 0 | 0 | each new stored score evaluated once per active strategy version |
| `record_equity_marks` | hourly (:05) | — (database) | 0 | 0 | equity at liquidation value |

**Tracked set.** A token is refreshed while it is ≤ 14 days old and its best
pool has ≥ US$2,000 liquidity (or is unknown yet), or it is on any watchlist,
capped at 300 tokens (watchlist first, then deepest liquidity). All three
values are in `app_settings.discovery`. Tokens mentioned by a monitored source in the
last 35 days are always tracked, so mention outcomes have prices. Tokens in open
paper positions or pending paper orders are always tracked (even if later excluded),
so they can be marked and filled.

## Coverage and latency — honest limits

* GeckoTerminal returns the most recent 20 pools per page. The job reads
  page 1 and continues to page 2 only if every pool on page 1 was new. If it
  still has not reached an already-known pool, the run is marked **partial**
  ("page limit reached before catching up"). On Solana and BSC, where
  hundreds of pools can be created in 10 minutes, **many new pools will be
  missed**. That is visible per chain on the System page.
* Discovery latency (`tokens.first_observed_at − earliest_pool_created_at`) is
  recorded per token and summarised (p50/p90) in the daily health report.
  Expect minutes, not seconds.
* Raising `new_pools_max_pages` improves coverage at 1 call per page per chain
  and is bounded by the ~10/min public limit: at most ~3 pages/chain/10 min
  without starving other GeckoTerminal uses.
* No websockets or paid feeds are used; this is not a sniper-grade feed and
  is not intended to be.
