# Integration risks

| # | Risk | Likelihood / impact | Mitigation in the design |
|---|---|---|---|
| 1 | **Adapters untested against real responses** (build sandbox could not reach providers) | High / High | Defensive parsers (unknown → NULL, bad items skipped and logged). `scripts/capture_fixtures.sh` + `pytest -m live` must pass on the VPS before Phase 2 is signed off. |
| 2 | GeckoTerminal public limit (~10/min, "may fluctuate") and 20-pool pages ⇒ missed pools on busy chains | High / Medium | 8/min limiter, page-until-caught-up, runs marked `partial`, per-chain coverage on the System page. Documented as incomplete coverage. |
| 3 | Provider schema or limit changes; API revocation (DEX Screener's licence is revocable) | Medium / High | Two independent market providers; circuit breakers; outage → source shown `down` (alerts in Phase 5). |
| 4 | GoPlus free tier shrinking / moving to paid | Medium / High | Missing security data is `unknown` and blocks "assessed" status; never a pass. Scoring gives unknown security 0 points. RugCheck as an optional Solana cross-check. |
| 5 | Telegram ToS (2026 anti-scraping, no AI use of platform data); account bans for user-account readers | High / High | Bot-only collection in chats where the bot is added, plus manual entry. No MTProto user session without explicit approval; if approved, session secrets go in Docker secrets, never in the database. |
| 6 | Presale data has no reliable free/legal feed; promotional claims are unverified | High / Medium | Manual watchlist with per-claim provenance; verification status describes provenance only; no "safe/legit" label exists in the schema. |
| 7 | Supabase free tier: 500 MB DB, pausing after inactivity | Medium / High | Retention + pruning (see COSTS.md); DB size in daily report; Pro or self-hosted Postgres as approval-gated fallbacks. |
| 8 | Supabase transaction pooler incompatible with prepared statements | Medium / Low | `CIT_DATABASE_DISABLE_PREPARED_STATEMENTS=true`; recommended to use the session pooler (5432). |
| 9 | Etherscan free tier no longer covers BSC/Base | Certain / Medium | Use Alchemy (EVM) and Helius (Solana) free tiers for wallet events in Phase 4. |
| 10 | Security heuristics miss malicious contracts; honeypot checks are simulations | Certain / High | UI wording: "not an audit". Hard exclusions only for detected risks; nothing is labelled safe. |
| 11 | Prompt injection via websites/Telegram/social text into AI reports | Medium / High | **Implemented:** third-party text only in `untrusted_text` / `self_reported` evidence fields; system prompt forbids following it or using outside knowledge; structured JSON output; every claim must cite existing evidence ids; numbers must exist in non-untrusted evidence; failures stored as `rejected_schema` and never shown as findings. Alert text is HTML-escaped before Telegram. |
| 12 | AI cost overrun | Low / Medium | **Implemented:** inert without an API key + enabled source; daily request/token caps and a US$10 monthly cap checked with a worst-case estimate before every call; usage metered per call; material-change hash and 12 h minimum gap; 90%-of-cap and budget-threshold alerts. |
| 13 | Look-ahead / survivorship bias in paper results | Medium / High | DB trigger forbids fills priced before `earliest_fill_at`; all evaluations recorded (incl. rejects/misses); pruning never deletes referenced tokens; liquidity-haircut marks; untradeable positions marked, not dropped. |
| 14 | Wash trading / fake volume on new pools | High / Medium | Buy/sell counts and liquidity shown together; Phase 3 scoring penalises volume ≫ liquidity and one-sided flow; holder concentration from GoPlus. |
| 15 | Single VPS failure | Low / Medium | Stateless containers; `restart: unless-stopped`; DB is managed; nightly dumps copied off-box; rebuild documented in OPERATIONS.md. |
| 16 | Next.js 16 / Supabase SSR API churn | Medium / Low | Pinned lockfile; code follows the bundled Next 16 docs (proxy.ts, async request APIs, Cache Components). |
| 17 | Docker Hub pull limits (seen in the sandbox) | Low / Low | Build images on the VPS or in CI; consider a registry mirror. |
