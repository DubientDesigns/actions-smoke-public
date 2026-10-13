# Phase log

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
