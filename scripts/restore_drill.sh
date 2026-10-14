#!/usr/bin/env bash
# Restore drill: restores the newest backup into a throwaway Postgres container,
# checks it, then deletes the container. Touches nothing in production.
#   scripts/restore_drill.sh [backups/cit-....dump]
set -euo pipefail
cd "$(dirname "$0")/.."
f="${1:-$(ls -1t backups/cit-*.dump 2>/dev/null | head -1)}"
[ -n "$f" ] && [ -f "$f" ] || { echo "no backup file found in backups/"; exit 1; }
name="cit-restore-drill-$$"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
echo "restoring $f ($(du -h "$f" | cut -f1)) into a temporary container..."
docker run -d --name "$name" -e POSTGRES_PASSWORD=drill -v "$PWD/$f:/drill.dump:ro" \
  -v "$PWD/db/bootstrap_local.sql:/bootstrap.sql:ro" postgres:16-alpine >/dev/null
for _ in $(seq 1 30); do docker exec "$name" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
sleep 2
# Supabase provides the roles, the auth schema and the extensions; the dump does not
# contain them (same preparation as a real restore, see docs/OPERATIONS.md section 4).
docker exec "$name" psql -q -U postgres -v ON_ERROR_STOP=1 -f /bootstrap.sql >/dev/null
docker exec "$name" psql -q -U postgres -v ON_ERROR_STOP=1 \
  -c "create extension if not exists pgcrypto; create extension if not exists citext;" >/dev/null
errs=$(docker exec "$name" pg_restore --no-owner --no-privileges -U postgres -d postgres /drill.dump 2>&1 \
  | grep 'ERROR' | grep -v 'schema "public" already exists' || true)
if [ -n "$errs" ]; then
  echo "restore errors:"; echo "$errs" | head -20
  echo "restore drill: FAILED (the backup does not restore cleanly)"; exit 1
fi
docker exec -i "$name" psql -U postgres -At <<'SQL'
select 'migrations applied: ' || count(*) from cit_meta.schema_migrations;
select 'app users: ' || count(*) from public.app_users;
select 'tokens: ' || count(*) from public.tokens;
select 'market snapshots: ' || count(*) from public.market_snapshots;
select 'security assessments: ' || count(*) from public.security_assessments;
select 'scores: ' || count(*) from public.opportunity_scores;
select 'paper orders: ' || count(*) from public.paper_orders;
select 'strategy evaluations: ' || count(*) from public.strategy_evaluations;
select 'newest snapshot: ' || coalesce(max(observed_at)::text, 'none') from public.market_snapshots;
SQL
n=$(docker exec "$name" psql -U postgres -At -c "select count(*) from cit_meta.schema_migrations")
[ "$n" -gt 0 ] && echo "restore drill: OK" || { echo "restore drill: FAILED (no migrations table)"; exit 1; }
