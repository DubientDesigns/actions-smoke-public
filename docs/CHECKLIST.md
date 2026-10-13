# Implementation checklist

`[x]` done and tested · `[~]` built, awaiting verification against real providers or real infrastructure · `[ ]` not started

## Phase 1 — Repository, infrastructure, database
- [x] Repository layout (backend / web / db / infra / scripts / docs)
- [x] SQL migrations for all required entities, with uniqueness constraints, FKs and indexes
- [x] RLS on every public table; allowlist (`app_users`); owner-scoped user tables; `security_invoker` views
- [x] DB-level look-ahead guard for paper fills; signal/fill ordering CHECK
- [x] Migration runner with checksums and advisory lock; local Supabase stand-ins for CI
- [x] Config from environment; secrets never sent to the browser
- [x] Structured JSON logging
- [x] Provider HTTP core: per-provider + global rate limits, daily caps, retry/backoff, circuit breaker, usage accounting
- [x] Health: `/healthz`, `/readyz`, worker heartbeat, source freshness, abandoned-run cleanup
- [x] Daily operational health report (`cit health-report`, stored in `system_health`)
- [x] Retention / downsampling / pruning sized for the Supabase free tier
- [~] Docker Compose (caddy, web, api, worker, backup, optional local db) — both images built and run; full `compose up` + TLS first run on the VPS
- [x] CI workflow (lint, tests on Postgres, typecheck, build, dependency audits)
- [ ] Apply migrations to the real Supabase project — **needs credentials**
- [ ] Off-box backup copy (rclone to R2/B2) — **needs a bucket**

## Phase 2 — Market discovery (all four chains)
- [~] GeckoTerminal `new_pools` adapter (BSC, Ethereum, Solana, Base)
- [~] DEX Screener `tokens/v1` batched refresh and `token-profiles` (paid-listing links)
- [x] Dedup by chain + address with multiple pools per token; idempotent re-discovery
- [x] Snapshots with provenance and freshness; `pool_latest`; market cap never inferred from FDV
- [x] Discovery latency recorded; partial-coverage runs flagged
- [x] Dashboard: Overview, Live Discoveries (filters/sort/search), Token Explorer, token detail (charts, pools, links), Data Sources & Health, Settings
- [ ] Run `scripts/capture_fixtures.sh` + `pytest -m live` on the VPS; fix any parser gaps
- [ ] Confirm every chain shows a latest successful refresh in production

## Phase 3 — Security, scoring, token dashboard
- [ ] GoPlus EVM + Solana adapters → `security_assessments` with per-check pass/risk/warn/unknown/unsupported
- [ ] Optional RugCheck Solana cross-check (after verifying auth/terms)
- [ ] Configurable hard exclusions / warnings / review rules (`app_settings.security.policy`)
- [ ] Staleness: `valid_until`, re-assessment schedule; stale treated as unknown
- [ ] Token scorecard v1 (25/25/25/15/10, labelled heuristic), evidence + missing data + risk flags + version + cutoff
- [ ] Unknown metrics score 0; tests proving it
- [ ] Security Analysis page; scores and flags in Discoveries and token detail; saved views

## Phase 4 — Social intelligence and presales
- [ ] Source registry UI (`social_channels` with access basis)
- [ ] Telegram bot ingestion (only chats where the bot is added); contract-address extraction; forwarded/original; referral-link capture
- [ ] Manual mention entry; coordination groups
- [ ] Mention outcomes (24h/7d/30d, max gain, max drawdown, exit feasibility), including failed/delisted tokens
- [ ] Presale manual watchlist with per-claim provenance; presale scorecard; deadline tracking
- [ ] Wallet watchlist via Alchemy/Helius free tiers

## Phase 5 — AI reports, Telegram alerts, cost controls
- [ ] Evidence bundle builder with provenance ids; untrusted-text isolation
- [ ] Claude structured outputs + schema validation; cache by input hash; Batch API
- [ ] Budget gate (daily requests/tokens, monthly USD) checked before every call; spend in `api_usage`
- [ ] Telegram alerts: dedup, severity, quiet hours, cooldowns, hourly cap, daily digest, outage + spend alerts
- [ ] Daily health report delivered via Telegram

## Phase 6 — Paper portfolio and forward performance
- [ ] Order service (internal API) applying execution delay, fees, constant-product slippage, liquidity cap
- [ ] Manual and rule-based entries; strategy versions immutable; every evaluation recorded
- [ ] Partial exits, stop-loss / take-profit simulation, untradeable marking, presale vesting
- [ ] Equity marks with liquidity haircut; drawdown, win rate, profit factor, MAE/MFE
- [ ] Reproducibility test: re-running an evaluation from stored inputs yields identical decisions

## Phase 7 — Testing, deployment, monitoring
- [ ] Provision VPS; firewall (22 restricted, 80/443 only); unattended upgrades
- [ ] Deploy stack; verify restart recovery (kill worker mid-run → run closed, schedule resumes)
- [ ] Playwright smoke tests (desktop + mobile) against production
- [ ] Off-box backups + restore drill
- [ ] Acceptance criteria walkthrough (README §16 of the brief)
