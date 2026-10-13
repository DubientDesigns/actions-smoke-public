# Architecture

## Runtime topology (one small VPS)

```
                Internet
                   │ 443
               ┌───▼───┐
               │ Caddy │  TLS, security headers. Routes ONLY to web.
               └───┬───┘
                   │ edge network
               ┌───▼──────────┐      user JWT + anon key       ┌──────────────────────┐
               │ web (Next.js)├───────────────────────────────►│ Supabase             │
               └───┬──────────┘   (PostgREST, RLS enforced)    │  Auth (no sign-up)   │
                   │ internal network, bearer token            │  Postgres 15+        │
               ┌───▼──────────┐                                │                      │
               │ api (FastAPI)├──── privileged DSN ───────────►│                      │
               └──────────────┘                                │                      │
               ┌──────────────┐                                │                      │
               │ worker       ├──── privileged DSN ───────────►│                      │
               │ (APScheduler)│                                └──────────────────────┘
               └───┬──────────┘
                   │ HTTPS (rate-limited, circuit-broken)
         GeckoTerminal · DEX Screener · GoPlus · (later) Telegram Bot · Claude API
               ┌──────────────┐
               │ backup       │ nightly pg_dump → ./backups (copy off-box)
               └──────────────┘
```

* **Browser → data**: only via Supabase PostgREST as the signed-in user. Every
  public table has RLS enabled; only users in `app_users` can read; per-user
  tables (watchlists, saved views) are owner-scoped. Views are
  `security_invoker` so RLS still applies through them.
* **Workers → data**: a privileged Postgres connection from environment
  variables. It never reaches the web container's client bundle.
* **Internal API**: not routed by Caddy and not published on a host port.
  Mutations that need server-side validation (Phase 6 paper orders, settings
  edits) go browser → Next.js server action → internal API with a shared bearer
  token.
* **Time**: everything is `timestamptz` in UTC; the UI renders Asia/Singapore.

## Key decisions

| Decision | Choice | Why |
|---|---|---|
| Schema source of truth | Plain SQL migrations in `db/migrations`, applied by `cit migrate` with checksums | Supabase-compatible, reviewable, no ORM drift. The same files run on plain Postgres in CI via `db/bootstrap_local.sql` stand-ins. |
| DB access in Python | SQLAlchemy Core + `text()` | Upserts and window functions are clearer in SQL than in an ORM. |
| Async | asyncio + httpx + psycopg 3 | One process can drive all providers while honouring per-provider budgets. |
| Scheduler | APScheduler (in-process, no job store) | Jobs are idempotent and all state lives in Postgres, so a restarted worker simply resumes. Stuck `running` runs are closed by `check_sources`. |
| Rate limiting | Per-provider token bucket **and** a global bucket; daily caps from `data_sources` | Budgets are operator-editable without a deploy. |
| Failure handling | Retry with exponential backoff + jitter (honours `Retry-After`) → circuit breaker (opens after 5 consecutive failed operations, cool-down doubles up to 30 min) | Prevents hammering a provider that is down; status visible in the dashboard. |
| Frontend | Next.js 16 App Router, Cache Components, Tailwind v4, hand-written shadcn-style primitives, Recharts | Static shell + streamed per-user data. (shadcn CLI registry was unreachable from the build sandbox, so primitives are written directly; same patterns.) |
| Auth | Supabase Auth, email+password, sign-ups disabled, `app_users` allowlist | No public sign-up requirement; authorisation enforced in the database. |

## Data model

All tables are in `db/migrations/0001_core_schema.sql`; RLS in `0002_rls.sql`;
dashboard read models in `0003_dashboard_views.sql`.

### Conventions that encode the requirements

* **Unknown is NULL, never 0/false.** Parsers return `None` for missing or
  unparseable values; the UI renders "—". A NULL security field means "not
  checked", never "passed".
* **Market cap ≠ FDV.** `market_snapshots.market_cap_usd` and `fdv_usd` are
  separate. When a provider's market cap equals its FDV (the usual fallback
  when circulating supply is unknown), market cap is stored as NULL
  (`providers/models.py::market_cap_or_none`).
* **Deduplication.** `tokens` unique on `(chain_id, address)`; `pools` unique
  on `(chain_id, address)`; a token has many pools. EVM addresses are
  lowercased, Solana mints keep case. Re-observation never overwrites known
  metadata with NULLs and never moves `first_observed_at`.
* **Provenance and freshness.** Every snapshot carries `source_id`,
  `observed_at` and `ingestion_run_id`; links carry `source` and
  `observed_at`; `data_sources.last_success_at` and `v_job_freshness` show the
  latest successful refresh per source and per chain.
* **No look-ahead in paper trading.** `paper_orders.earliest_fill_at >= signal_at`
  (CHECK) and a trigger rejects any `paper_fills` row whose
  `price_observed_at` is earlier than the order's `earliest_fill_at`.
* **No cherry-picking.** `strategy_evaluations` records every decision,
  including `reject`, `skip`, `missed` and `failed`. Retention never prunes a
  token referenced by evaluations, orders, positions, mentions, scores,
  reports, watchlists or presales.
* **Presales are separate** from trading tokens (`presales`, with per-field
  provenance in `presale_claims`). `verification_status` describes provenance
  only — there is deliberately no "safe"/"legitimate" value.
* **Coordination.** `influencers.coordination_group` lets accounts be
  clustered so they are never counted as independent sources.

### Entities

| Group | Tables |
|---|---|
| Reference & ops | `chains`, `data_sources`, `ingestion_runs`, `api_usage` (+ `api_usage_daily` view), `system_health`, `app_settings`, `app_users`, `audit_log` |
| Market | `tokens`, `pools`, `market_snapshots`, `pool_latest` |
| Security | `security_assessments` (checks JSON with pass/risk/warn/unknown/unsupported per check, `valid_until` for staleness, `ruleset_version`) |
| Presales | `presales`, `presale_claims` |
| Social | `influencers`, `social_channels` (source registry with `access_basis`), `social_mentions`, `mention_outcomes` |
| Wallets | `tracked_wallets`, `wallet_events` |
| Research | `opportunity_scores` (scorecard `token`/`presale`, `scoring_version`, `data_cutoff_at`, components with evidence/missing), `research_reports` (deduped by `input_hash` + `prompt_version`) |
| User | `watchlists`, `watchlist_items`, `saved_views` |
| Alerts | `alerts` (category, severity, `dedup_key`, status incl. suppressed/deferred/digested) |
| Paper trading | `strategy_definitions` (immutable versions), `strategy_evaluations`, `paper_portfolios`, `paper_positions`, `paper_orders`, `paper_fills`, `paper_equity_marks` |

Indexes cover chain, token address, timestamps and watchlist membership
(`watchlist_items_token_idx`), plus partial indexes for running ingestion runs
and pending orders.

### Storage strategy

Raw snapshots are kept 3 days, then downsampled to the last observation per
pool-hour for 30 days, then per pool-day. Tokens that never reached the
tracking liquidity threshold and are not referenced by anything are pruned
after 14 days. All values are in `app_settings.retention`. See
[COSTS.md](COSTS.md) for the size estimate.
