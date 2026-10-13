# Operations runbook

## 1. Supabase project (one-time)

1. Create a project (free tier). Region close to Singapore.
2. **Authentication → Providers → Email:** enable email+password; **disable
   "Allow new users to sign up".** Create your user under Authentication → Users.
3. Copy the project URL and the **anon** key (browser-safe) and the database
   connection string for the **session pooler** (port 5432). Never put the
   `service_role` key or DB password in any `NEXT_PUBLIC_` variable.
4. Apply the schema from a trusted machine (or the VPS):
   ```bash
   cd backend && uv sync
   export CIT_DATABASE_URL='postgresql+psycopg://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres'
   uv run cit migrate          # NO --local-bootstrap on Supabase
   uv run cit seed-settings
   ```
5. Allowlist yourself (SQL editor):
   ```sql
   insert into app_users (user_id, email, role)
   select id, email, 'owner' from auth.users where email = 'you@example.com';
   ```

## 2. VPS

```bash
# Ubuntu 24.04, 2 GB+ RAM. Firewall: allow 80, 443; SSH from your IP only.
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
git clone <repo> cit && cd cit
cp .env.example .env && chmod 600 .env && $EDITOR .env    # fill values
openssl rand -hex 32   # → CIT_INTERNAL_API_TOKEN

# Verify the adapters against real provider data BEFORE trusting Phase 2:
scripts/capture_fixtures.sh
cd backend && uv sync && uv run pytest -m live -v && cd ..

docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml ps
docker compose -f infra/docker-compose.yml logs -f worker
```

Point your domain's A record at the VPS; Caddy obtains TLS automatically
(`CIT_DOMAIN` in `.env`).

## 3. Day-to-day

| Task | Command |
|---|---|
| Health report | `docker compose -f infra/docker-compose.yml exec api cit health-report` |
| Run a job now | `docker compose -f infra/docker-compose.yml exec worker cit run-job discover_new_pools` |
| Change a budget | `update data_sources set rate_limit_per_minute = 6 where slug = 'geckoterminal';` (picked up on worker restart) |
| Change settings | `update app_settings set value = jsonb_set(value, '{max_tracked_tokens}', '200') where key = 'discovery';` (validated on read; invalid values fall back to defaults and are logged) |
| Disable a source | `update data_sources set enabled = false where slug = '...';` |
| Restart | `docker compose -f infra/docker-compose.yml restart worker` |
| Upgrade | `git pull && docker compose -f infra/docker-compose.yml up -d --build` (the `migrate` service runs first) |

## 4. Backups and restore

The `backup` service writes `backups/cit-<UTC>.dump` nightly (03:00 SGT) and
keeps 14 days. **Copy them off the VPS**, for example with rclone to
Cloudflare R2 / Backblaze B2 (free tiers) from a cron job.

Restore into a fresh database:
```bash
pg_restore --no-owner --no-privileges --clean --if-exists -d "$TARGET_DSN" backups/cit-YYYYMMDDTHHMMSSZ.dump
```
Supabase's `auth` schema is not included in these dumps (it is managed by
Supabase); recreate users and the `app_users` rows after a full project loss.

## 5. Security notes

* Internal API and worker are never routed by Caddy and publish no host ports.
* `.env` is chmod 600 and never committed; the browser only receives
  `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
* Containers run as non-root with read-only root filesystems and
  `no-new-privileges`.
* There are no private keys, wallet connections or trading permissions to
  protect — keep it that way.
