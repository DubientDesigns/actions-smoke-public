# Phase log

## Phase 6 — 2026-10-13

Paper trading and forward performance. Simulation only: no wallets, keys, signing,
swaps or real execution exist anywhere in the code.

### What was built
* **Execution model** (`cit/paper/execution.py`, pure): constant-product price impact
  on the quote reserve (liquidity/2), 30 bps fee per side, 50 bps extra slippage, buys
  above 2% of pool liquidity rejected, sells partially filled up to that cap, pools
  below US$10k or without price untradeable. Marks use **liquidation value** (one
  hypothetical full sell incl. impact and fees), not the displayed price.
* **Order lifecycle** (`cit/paper/service.py`): `signal_at` → `earliest_fill_at`
  (+60 s) → fill with the first snapshot observed at/after it (deepest pool, or the
  position's pool for sells) → `expires_at` (+30 min) → `expired`, recorded as a
  `missed` strategy evaluation. The DB trigger still rejects any earlier price.
* **Rules:** stop-loss, staged take-profits (in order, each once), max hold; signalled
  at the observation time of the triggering snapshot and filled under the same delay;
  `paper_rule` alerts (low severity → digest only).
* **Strategies:** versioned and immutable (trigger); every new stored score of a
  token is evaluated once per active version; evaluations are append-only (trigger)
  and store exact inputs + hash; seed `baseline v1` with its own S$10,000 portfolio.
* **Presales:** allocations only while the sale is `upcoming`/`live`, at the recorded
  sale price; vesting (TGE %, cliff, linear months) keeps tokens locked; unknown
  schedule ⇒ nothing unlocked; locked tokens are valued at zero.
* **Metrics view** `v_paper_performance`: return, max drawdown, win rate and profit
  factor (closed positions only), avg MFE/MAE, hold time, slippage, filled/rejected/
  expired orders, enter/reject/missed evaluations.
* **Internal API:** `POST /v1/paper/orders` (buy / presale / sell) and
  `POST /v1/paper/orders/{id}/cancel`, bearer token, owner's manual portfolio, audit log.
* **Web:** Paper Portfolio (equity, positions incl. untradeable/vesting, all orders with
  reasons, sell/cancel for owners), Historical Performance (metrics table, equity and
  drawdown charts, strategy versions, evaluation log); paper buy card on token pages,
  allocation card on open presales.
* Tokens held on paper stay in the tracked set so they keep getting prices.

### Tests run
* Backend **132 passed** (11 live deselected); ruff clean. New: execution math (fees,
  impact, extra slippage, size cap, unknown/low liquidity, partial sells, round-trip
  loss, conservative liquidation value); vesting (cliff, linear, unknown ⇒ locked);
  strategy rules (each rule rejects, unknown never passes, reproducible hash);
  service against Postgres: fill uses first price after the delay and never the
  signal-time price, DB look-ahead trigger, expiry ⇒ `missed`, cash/liquidity
  rejections, partial sell + realised P&L, untradeable on drained pool and on 72 h
  without price, stop-loss signal/fill timing and no re-trigger, take-profit legs in
  order, immutability and append-only triggers, end-to-end strategy evaluation with
  replay of stored inputs, equity marks + performance view, presale vesting and
  closed-sale rejection, internal API (auth, 404/422, owner-scoped cancel, audit),
  held tokens stay tracked.
* Web: lint, typecheck, **18 Vitest tests** (adds paper order parsing and drawdown),
  `next build`.

### Failures found and fixed
* Strategy candidate query referenced a non-existent `v_score_latest.id` → `score_id`.
* Fully vested presale positions skipped the liquidity check → uses the new status.
* Paper-held tokens could drop out of the tracked set after 14 days (or on exclusion)
  and be wrongly marked untradeable → always tracked while held.

### Limitations (honest)
1. The impact model assumes full-range liquidity; concentrated-liquidity pools can be
   much thinner near the price, so results are optimistic there (mitigated by the 2%
   cap and extra slippage, not eliminated).
2. Fill prices are our ~15-minute market snapshots, not on-chain execution; between
   snapshots an order waits (up to 30 min, then it is recorded as missed).
3. SGD figures use an operator-maintained reference rate (`budget.sgd_per_usd`).
4. Strategy `baseline v1` is a heuristic benchmark; forward results need weeks of data
   before they mean anything.
5. Token buy/sell taxes are not deducted from paper fills; GoPlus-reported taxes only
   affect eligibility (security policy thresholds), so taxed tokens look better on paper.

### Next: Phase 7 — testing, deployment, monitoring
VPS provisioning and hardening, deploy, restart-recovery drill, live provider fixture
capture and `pytest -m live`, Playwright smoke tests (desktop + mobile), off-box
backups + restore drill, acceptance walkthrough. Needs your VPS and keys.

## Phase 5 — 2026-10-13

Operator-approved defaults: Claude Haiku 5.5, hard cap US$10/month, ≤ 20 reports/day;
quiet hours 23:00–07:30 SGT with high/critical still sent; 08:00 SGT digest.

### Tests run
* Backend **111 passed**; ruff clean. New: Claude pricing (incl. Haiku long-prompt
  card); report validation (accepts cited numbers within rounding, rejects
  fabricated numbers, numbers only present in untrusted text, unknown evidence ids,
  claims without evidence, invalid enums); budget gate (request/token/monthly caps);
  research job with an injected fake caller (complete + metered cost recorded in
  `api_usage`, rejected on fabrication, refusal recorded, budget blocks *before*
  calling, queued owner request processed first, skipped without key/when disabled,
  no regeneration without material change); internal API request endpoint (401 without
  token, queue, dedupe, 404); alert dedup/cooldown and digest-only severities; all
  generators; spend thresholds incl. fixed costs; quiet hours across midnight;
  dispatch ordering, hourly cap with critical exemption, HTML escaping of untrusted
  titles, app links, retries → failed, deferral still applied while the provider fails;
  daily digest; chunking.
* Web: lint, typecheck, 14 Vitest tests, `next build`.
* CLI: migration 0006; `generate_alerts` produced a real outage alert (GoPlus is
  blocked here); delivery, digest and AI skipped cleanly without keys.

### Failures found and fixed
* Dispatcher stopped the whole round after one failed send, leaving alerts that only
  needed deferring stuck in `pending` → deferral continues; sending pauses until next round.
* Report content was bound as text into a `jsonb` column → explicit cast.
* `daily_digest_time` setting was never honoured → removed; digest is fixed at 08:00 SGT
  (documented) rather than offering a setting that does nothing.

### Limitations (honest)
1. **Claude and Telegram delivery are untested against the live APIs** (no keys here);
   the Claude call uses the official SDK per its documentation.
2. The fabricated-number check is a heuristic: it compares numbers in the prose with
   numbers in the evidence (2% tolerance, small vocabulary numbers allowed). It can
   reject a correct report that rephrases a figure (e.g. a computed ratio) — such
   reports are kept as `rejected_schema` with the reason, never shown as findings.
3. Reports cover tokens only; presale reports are not generated yet.
4. The Batch API is not used; at ~20 reports/day the saving would be cents.
5. Alert thresholds are heuristics; tune `app_settings.alerts` after a week of data.

### Next: Phase 6 — paper portfolio and forward performance
Order service with execution delay, fees, constant-product slippage and liquidity caps
(DB look-ahead guard already enforced); manual and rule-based entries with every
evaluation recorded; partial exits, stop-loss/take-profit, untradeable marking, presale
vesting; equity curve, drawdown, win rate, profit factor, MAE/MFE; paper-rule alerts.


## Phase 4 — 2026-10-13

### Tests run
* Backend **91 passed**; ruff clean. New: extraction (contracts, 32-byte
  Solana check, chain from URLs, no false positives from unrelated URLs,
  referrals, disclosure, categories, prompt-injection text treated as data);
  Telegram collection end to end (registered chats only, unregistered chats
  recorded as metadata only, chatter discarded, forwarding users hidden,
  offset advanced, idempotent, bot token redacted from errors, skipped
  without token); mention resolution via DEX Screener; outcomes ignore
  pre-publication prices and keep no-price results; independent-mention
  counting (clusters, forwards, identical text); coordination signals;
  presale scorecard and job; Alchemy/Helius parsers and wallet sync end to end
  (lookback, cursors, dedup, USD valuation, skipped without keys); RLS for
  owner curation and worker-private state; HTTP POST + secret redaction.
* Web: lint, typecheck, **14 Vitest tests** (adds input validation: SGT→UTC,
  URL schemes, per-chain address checks), `next build`.
* CLI: all new jobs ran against Postgres and skipped cleanly without keys.

### Failures found and fixed
* POSTing to an empty path produced `…/v2/KEY/` (trailing slash) → URL join fixed.
* An unreviewed presale earned points for "not flagged" → now unknown until reviewed.
* Untyped NULL parameters in wallet SQL failed in Postgres → explicit casts.
* Provider clients were cached by name, so all Alchemy networks would have
  shared one host → cached by name + base URL.
* Server-action error handling would have swallowed framework redirects →
  `unstable_rethrow`.

### Limitations (honest)
1. Telegram Bot API, Alchemy and Helius are **untested against live
   responses** (no keys/egress here). Follow docs/OPERATIONS.md §3a.
2. Social coverage is limited to chats the bot is added to plus manual
   entries. X/Twitter and YouTube collection are not built (paid APIs).
3. Wallet events are transfers; buy/sell is inferred only for Helius SWAP
   transactions. EVM swaps appear as transfer in/out.
4. Mention outcomes use the token's current deepest pool and our snapshot
   cadence (15 min, downsampled to hourly after 3 days), so intrahour peaks
   can be missed; max gain is therefore conservative.
5. "Exit feasible" uses a fixed reference position (US$1,000 at ≤2% of pool
   liquidity), a heuristic not an execution model (Phase 6 adds slippage).
6. Presale data is manual; there is no automated presale feed.

### Next: Phase 5 — AI reports, Telegram alerts, cost controls
Evidence bundles with provenance, Claude structured outputs with schema
validation and budget gates (needs your API key + budget confirmation),
Telegram alerts with dedup/severity/quiet hours/cooldowns/digest, outage and
spend-threshold alerts, daily health report delivery.


## Phase 3 — 2026-10-13

### Tests run
* Backend: **65 passed** (`uv run pytest`); ruff clean. New coverage:
  security engine on synthetic GoPlus-shaped payloads (clean token, honeypot,
  sparse/partial data, Solana freeze authority, not-found and rate-limit
  envelopes, policy overrides, empty data → nothing passes); scorecard (strong
  token, all-unknown token earns nothing, unknown checks score 0, hard
  exclusion, stale security, red flags, configurable/validated weights,
  reproducible input hash); end-to-end jobs against Postgres (candidate
  selection skips illiquid tokens, pool addresses excluded from concentration,
  fresh assessments not repeated, stale ones re-run with supply comparison,
  not-found retried after 6h, rate-limited envelope stores nothing and marks
  the run failed, disabled source skipped, scores stored only on material
  change); RLS on the new views.
* Web: ESLint, typecheck, **10 Vitest tests** (incl. server-rendering the
  security/score components with sample data), `next build`.
* CLI: `cit migrate` applied 0004; `assess_security` against the blocked
  GoPlus host recorded the failure without raising; `score_tokens` stored a
  score with security listed as missing.

### Failures found and fixed
* A test left GoPlus disabled, silently skipping assessments in later tests →
  the `clean_db` fixture now restores `data_sources.enabled`, and the scoring
  test asserts that assessment actually ran.
* Storing a score every refresh would add ~58 MB/day → scores are stored only
  on material change (≥ 2 points, flag change, new security assessment, or 6h
  heartbeat) and thinned to one per token per day after 7 days.
* Vitest 5 / Vite 8 rejects the `esbuild.jsx` option → removed (not needed).

### Completed features
See [CHECKLIST.md](CHECKLIST.md) Phase 3.

### Limitations (honest)
1. **GoPlus not verified against a live response** (host blocked here). Field
   names follow the docs; if they differ, checks degrade to "unknown" (never
   "pass"), and the live test fails loudly. Run `scripts/capture_fixtures.sh`
   and `pytest -m live` on the VPS.
2. On Solana, GoPlus holder entries may be token accounts rather than owner
   addresses, so pool holdings may not be excluded from concentration; the
   check can over-report concentration (conservative direction).
3. Honeypot detection, LP lock, taxes and owner privileges are unavailable for
   Solana from this provider and are shown as **unsupported**.
4. "Suspicious deployer history" is limited to GoPlus's
   `honeypot_with_same_creator` (EVM only); a fuller deployer analysis needs
   on-chain data (Phase 4 wallet work).
5. Social category can reach at most 7.5/15 until mention collection exists
   (Phase 4); links are self-reported and paid profile links earn nothing.
6. RugCheck cross-check deferred (auth and terms unverified).
7. Weights and thresholds are heuristics, to be validated by forward testing
   in Phase 6.

### Next: Phase 4 — social intelligence and presale watchlists
Source registry UI, Telegram bot ingestion (only chats where the bot is
added), manual mention entry, coordination groups, mention forward
performance (incl. failed/delisted tokens), presale manual watchlist with
per-claim provenance and a separate presale scorecard, wallet watchlist via
Alchemy/Helius free tiers.


## Phases 1 & 2 — 2026-10-13

### Tests run
* Backend: `uv run pytest` → **43 passed**. Covers migrations and idempotency,
  checksum tamper detection, RLS (anon denied, non-allowlisted users see
  nothing, browser users cannot write research tables, watchlists private per
  user, views respect RLS), DB look-ahead guard, rate limiter, circuit
  breaker, retry/Retry-After, daily caps, parsers, end-to-end discovery →
  Postgres (dedup across providers, idempotent re-discovery, outage
  recording), retention downsampling and pruning, and health report status.
  `ruff check` clean; `pip-audit`: no known vulnerabilities.
* Web: ESLint, `tsc`, Vitest (6 tests: formatting, SGT display, freshness),
  `next build` all pass; `npm audit --omit=dev`: 0 vulnerabilities.
* Runtime: `cit migrate`, `seed-settings`, `worker` and `api` ran against a
  local Postgres. Heartbeats, `/readyz` and the bearer-protected report all
  worked; provider calls failed on the sandbox egress policy and were
  recorded correctly (runs `failed`, usage metered, retries with backoff).
* Docker: backend and web images built and run as above (the `uv` binary is
  now installed from PyPI because the GHCR image was unreachable).
* Browser (Playwright/Chromium): unauthenticated requests redirect to
  `/login?next=…`; login renders at 1366 px and 390 px with no horizontal
  overflow; bad credentials show an error.

### Failures found and fixed during the phase
* Health report said `ok` before any source had ever succeeded → enabled
  sources without a success now degrade the overall status (test added).
* Storage estimate showed the free 500 MB tier would overflow from junk-pool
  growth → retention tightened and pruning of illiquid, unreferenced tokens
  added; pruning never removes anything referenced by evaluations, trades,
  mentions, scores, reports, watchlists or presales (test added).
* Next.js 16 prerender error from `usePathname()` outside `<Suspense>` → nav
  highlighting now streams inside a Suspense boundary.
* Data sections could be prerendered at build time when Supabase env was
  absent → `connection()` forces them to request time.

### Completed features
See [CHECKLIST.md](CHECKLIST.md) Phase 1 and 2 items marked `[x]`.

### Limitations (honest)
1. **Not tested against real provider responses.** The sandbox could not reach
   GeckoTerminal, DEX Screener or GoPlus, so parsers were tested only with
   synthetic payloads written from the documented schemas
   (`backend/tests/fixtures/synthetic/`, clearly labelled). Phase 2 is
   **not accepted** until `scripts/capture_fixtures.sh` + `pytest -m live`
   pass on the VPS.
2. **Dashboard data pages not rendered against a live Supabase.** The Supabase
   local stack images were unreachable (GHCR blob host blocked). The auth gate
   and login page were browser-tested; the data pages were type-checked and
   built, and the views they query are tested in Postgres.
3. **Compose stack not run end to end.** Both images were built and run in
   the sandbox, using a temporary overlay that only adds the sandbox's proxy
   CA. The backend container (uid 10001, read-only root) applied the bundled
   migrations and served `/healthz` and `/readyz`; the web container served
   the auth redirect and login page. Caddy/TLS, the backup loop and the full
   `docker compose up` are first exercised on the VPS.
4. Discovery coverage is incomplete by design (20 pools/page, ~10 calls/min);
   busy chains will miss pools. Runs say so (`partial`).
5. Settings are read-only in the UI; edit via SQL for now.
6. No alerts yet: outages are visible in the dashboard and daily report only.

### Decisions needing your input (none block Phase 3)
* **Supabase Pro (US$25/mo)** only if the database approaches 400 MB.
* **Telegram user-account (MTProto) reading** is not planned because of
  Telegram's 2026 terms; bot-only collection is the default.
* **Claude API key and budget** for Phase 5 (default cap US$10/month, Haiku 5.5).
  Check whether your Max plan includes API credits in the Console.

### Next: Phase 3 — security filters, scoring, token dashboard
1. GoPlus adapters (EVM chains 1/56/8453 and Solana) with per-check
   pass/risk/warn/unknown/unsupported mapping, freshness (`valid_until`) and
   a versioned ruleset; optional RugCheck cross-check after verifying its terms.
2. Policy in `app_settings.security.policy`: hard exclusions (e.g. honeypot,
   cannot sell, sell tax ≥ threshold), warnings, review requirements.
3. Token scorecard v1 (labelled heuristic weights 25/25/25/15/10) computed
   from data available at a recorded cutoff, with evidence, missing data and
   risk flags; unknown inputs score zero.
4. Security Analysis page; score and flag columns and saved views in
   Discoveries; security panel on token detail.
