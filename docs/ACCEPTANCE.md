# Acceptance walkthrough

How to confirm each requirement on the deployed system. **Status** says what is proven
today: `tested` = automated tests in CI; `needs live` = built and tested with synthetic data,
must be confirmed on the VPS with real providers/keys (tick it when you have seen it).

| # | Requirement | Status | How to confirm on the live site |
|---|---|---|---|
| 1 | Private: invitation only, no sign-up, every page behind login | tested (Playwright, desktop + mobile) | Signed out, any page redirects to /login; a non-allowlisted user sees "Account not allowlisted". |
| 2 | No privileged Supabase key in the browser | tested (bundle scan, preflight) | `scripts/preflight.sh` passes; Playwright bundle check passes against production. |
| 3 | New pools discovered on BNB, Ethereum, Solana, Base | needs live | *Live Discoveries* fills within ~10 min; *Data Sources & Health* shows GeckoTerminal/DEX Screener **ok** per chain. |
| 4 | Market cap never shown as FDV; unknowns shown as "—" | tested | Token page: FDV and market cap separate; missing values are "—", never 0. |
| 5 | Security checks; unknown ≠ pass | tested; GoPlus needs live | *Security Analysis* shows assessments; a token without data says NOT ASSESSED. |
| 6 | Scores with components and missing data | tested | Token page score card lists components and missing inputs. |
| 7 | Telegram intelligence, bot-only, approved chats only | tested; Bot API needs live | Add the bot to a chat; it appears under *Chats waiting for approval*; nothing is stored before approval. |
| 8 | Presale radar with claim provenance + vesting | tested | Add a presale; every field shows its source; vesting shown as claimed. |
| 9 | Wallet watchlist | tested; Alchemy/Helius need live | Add a wallet; events appear after the next 15-min sync. |
| 10 | AI reports cite evidence, within budget | tested; Claude needs live | Request a report; it cites evidence ids; spend panel shows cost vs US$10 cap. |
| 11 | Alerts with quiet hours and daily digest | tested; Telegram needs live | Alerts arrive in Telegram; low-severity ones appear in the 08:00 SGT digest. |
| 12 | Paper trading without look-ahead; realistic fills | tested (DB trigger + service tests) | Place a paper buy; it fills ≥ 60 s later at a price observed after the signal, with slippage and fees shown. |
| 13 | All strategy decisions recorded, reproducible | tested | *Historical Performance → Evaluation log* lists enter/reject/missed with input hashes. |
| 14 | Costs within S$30–60/month | needs live | *Settings/Alerts* spend panel; VPS price set in `app_settings.budget.fixed_monthly_costs_sgd`. |
| 15 | Survives restarts; failed runs visible | tested (abandoned runs/reports closed) | DEPLOY.md §11.1 restart drill. |
| 16 | Backups restorable, off-site | drill script tested locally | `scripts/restore_drill.sh` → OK; R2 bucket shows nightly files. |
| 17 | Monitored when the server itself is down | tested (ping only after a healthy heartbeat) | Stop the worker for 15 min; healthchecks.io notifies you. |
| 18 | Mobile usable | tested (Pixel 7 viewport, no horizontal scroll) | Open on your phone. |
| 19 | No trading keys, wallets, signing or real execution | by design | There is no code path or setting for it; code search finds none. |
