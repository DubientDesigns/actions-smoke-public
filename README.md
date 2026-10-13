# Crypto Intelligence Terminal

A private, self-hosted research platform that discovers, monitors and
paper-tracks early-stage tokens on **BNB Chain, Ethereum, Solana and Base**.

> **Research only.** There is no live trading, no wallet connection, no
> private keys, no order signing and no real-money execution anywhere in this
> codebase, and none will be added. Scores rank what to research next; they
> are not predictions of returns.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Repository, infrastructure, database | **Done** (see [docs/PHASE_LOG.md](docs/PHASE_LOG.md)) |
| 2 | Market discovery on all four chains | **Built; not yet verified against live providers** (sandbox egress blocked) |
| 3 | Security filters, scoring, token dashboard | **Built; GoPlus not yet verified against live responses** |
| 4 | Social intelligence, presale watchlists | Next |
| 5 | AI reports, Telegram alerts, cost controls | Planned |
| 6 | Paper portfolio, forward performance | Planned (schema + look-ahead guard already in place) |
| 7 | Testing, production deployment, monitoring | Planned |

## Layout

```
backend/            Python 3.12 workers + internal FastAPI (package `cit`)
  cit/providers/    rate-limited provider clients and adapters
  cit/services/     discovery, persistence, ops (health, retention)
  cit/worker/       APScheduler schedule and job registry
  tests/            pytest (Postgres-backed); fixtures/synthetic vs fixtures/live
db/migrations/      SQL migrations — single source of truth for the schema
web/                Next.js 16 dashboard (Supabase auth + RLS)
infra/              docker-compose, Caddy, backup loop
scripts/            capture_fixtures.sh (real provider responses for verification)
docs/               architecture, research, budgets, risks, operations, phase log
```

## Quick start (development)

```bash
# Postgres 16 locally (or: docker compose -f infra/docker-compose.yml --profile localdb up db)
cd backend
uv sync
export CIT_DATABASE_URL=postgresql+psycopg://cit:cit@localhost:5432/cit
uv run cit migrate --local-bootstrap   # --local-bootstrap only on plain Postgres, never Supabase
uv run cit seed-settings
uv run cit run-job discover_new_pools  # one-off run
uv run cit worker                       # full schedule
uv run pytest                           # 65 tests; `pytest -m live` for real-provider checks

cd ../web
npm ci && npm run dev
```

Production deployment: [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Documentation

- [Architecture & schema](docs/ARCHITECTURE.md)
- [API research: limits, terms, verification status](docs/API_RESEARCH.md)
- [Ingestion schedule & rate-limit budget](docs/INGESTION.md)
- [Monthly cost estimate](docs/COSTS.md)
- [Integration risks](docs/RISKS.md)
- [Implementation checklist](docs/CHECKLIST.md)
- [Operations runbook](docs/OPERATIONS.md)
- [Phase log: completed features, limitations, next steps](docs/PHASE_LOG.md)
