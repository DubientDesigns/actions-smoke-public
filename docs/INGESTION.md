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
| *Phase 5* AI reports | hourly batch | Claude Messages / Batches | only after deterministic filters | ≤ 20 requests/day default | hard caps in `ai.budget` |

**Tracked set.** A token is refreshed while it is ≤ 14 days old and its best
pool has ≥ US$2,000 liquidity (or is unknown yet), or it is on any watchlist,
capped at 300 tokens (watchlist first, then deepest liquidity). All three
values are in `app_settings.discovery`.

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
