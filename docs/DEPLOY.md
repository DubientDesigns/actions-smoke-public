# Deploying the terminal: step by step

This guide takes you from nothing to a running, monitored site. Allow about an hour.
Commands go in the server's terminal unless a step says otherwise.

> **Never paste a password, API key or `.env` contents into a chat, issue or PR.** Share
> only script *output*; it never prints secrets.

## What it costs

| Item | Suggested | Approx. monthly |
|---|---|---|
| VPS (2 vCPU / 2–4 GB, Ubuntu 24.04) | Hetzner, DigitalOcean or Vultr; a Singapore region if offered | US$5–7 |
| Domain | any registrar (~US$10/year), or a free DuckDNS subdomain | ~US$1 |
| Supabase | free tier (500 MB; free projects can be paused when inactive, the always-on worker normally prevents this) | 0 |
| healthchecks.io (dead-man's switch) | free tier | 0 |
| Cloudflare R2 (off-site backups) | free tier, 10 GB | 0 |
| Claude API (optional) | Haiku, hard cap in app | ≤ US$10 |
| **Total** | | **≈ S$10–25** (inside the S$30–60 budget) |

## 1. Supabase (database + logins)

1. Create a project at supabase.com (free tier), region **Southeast Asia (Singapore)**.
2. **Authentication → Sign In / Providers → Email**: keep email on, turn **off** "Allow new
   users to sign up". Then **Authentication → Users → Add user** with your email + a strong
   password.
3. Collect three values (Project Settings):
   * **Project URL**, e.g. `https://abcd.supabase.co`
   * **anon / publishable key** (safe for browsers). Never the `service_role` / secret key.
   * **Database → Connection string → Session pooler** (port 5432), with your DB password.

## 2. Server

1. Create the VPS (Ubuntu 24.04) and **add your SSH public key** during creation.
2. From your computer: `ssh root@<server-ip>`
3. On the server:
   ```bash
   git clone https://github.com/DubientDesigns/actions-smoke-public.git cit && cd cit
   ADMIN_IP=<your-home-ip> bash scripts/vps_bootstrap.sh   # omit ADMIN_IP if your IP changes often
   ```
   This installs Docker, a firewall (only 80/443 public, SSH restricted), automatic security
   updates, fail2ban and swap, and turns off password SSH once a key is present.

## 3. Domain

Create an **A record** for your domain (e.g. `cit.yourdomain.com`) pointing to the server IP.
HTTPS certificates are issued automatically once it resolves.

## 4. Configuration

```bash
cp .env.example .env && chmod 600 .env
openssl rand -hex 32          # copy the output into CIT_INTERNAL_API_TOKEN
nano .env                     # fill CIT_DOMAIN, CIT_PUBLIC_URL, CIT_DATABASE_URL,
                              # NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY
bash scripts/preflight.sh     # must end with "preflight: OK"
```
`CIT_DATABASE_URL` is the session-pooler string with `postgresql://` changed to
`postgresql+psycopg://`.

## 5. Check the data providers against real responses

```bash
bash scripts/verify_live.sh
```
This is the check the build sandbox could not do. Share the final summary line
(e.g. `N passed, M skipped`). A failure means a provider changed its format, so tell me before relying
on that data.

## 6. Start everything

```bash
docker compose -f infra/docker-compose.yml up -d --build    # first build ~5–10 min
bash scripts/smoke.sh                                       # must end with "smoke: OK"
```
The `migrate` step creates the schema in Supabase automatically. `smoke.sh` may report the
worker heartbeat as failing for the first minute; run it again.

## 7. Let yourself in

Supabase → **SQL Editor**:
```sql
insert into app_users (user_id, email, role)
select id, email, 'owner' from auth.users where email = 'you@example.com';
```
Open `https://<your-domain>` and sign in. Discoveries appear within ~10 minutes.

## 8. Monitoring (recommended, free)

The app alerts you on Telegram about problems it can see. It cannot tell you when the whole
server is down, so add an outside watcher:
1. healthchecks.io → new check, period **5 min**, grace **10 min**; add your email or
   Telegram as an integration.
2. Put its ping URL in `.env` as `CIT_HEALTHCHECK_PING_URL`, then
   `docker compose -f infra/docker-compose.yml up -d worker`.
3. The worker pings every minute while it and the database are healthy.

## 9. Off-site backups (recommended, free)

Nightly dumps land in `backups/` on the server. Copy them elsewhere:
1. Cloudflare → R2 → create bucket `cit-backups` → create an API token (Object Read & Write,
   that bucket only).
2. In `.env`, uncomment and fill the `RCLONE_CONFIG_OFFSITE_*` lines; set
   `RCLONE_REMOTE=offsite:cit-backups`.
3. `docker compose -f infra/docker-compose.yml --profile offsite up -d offsite`
4. After the first night, prove the backup restores:
   ```bash
   bash scripts/restore_drill.sh      # must end with "restore drill: OK"
   ```

## 10. Optional features

Telegram collection and alerts, Claude reports, wallet tracking: see
[OPERATIONS.md §3a](OPERATIONS.md#3a-optional-integrations). Each needs a key in `.env`,
a one-line SQL switch and a worker restart.

## 11. Final checks (acceptance)

1. **Restart recovery:** `docker compose -f infra/docker-compose.yml kill worker && docker compose -f infra/docker-compose.yml up -d worker`.
   Within 30 min, unfinished runs show as failed ("abandoned") on *Data Sources & Health* and the
   schedule continues.
2. **Browser tests against the live site** (from your computer with Node 22, or the server):
   ```bash
   cd web && npm ci && npx playwright install chromium
   BASE_URL=https://<your-domain> E2E_EMAIL=you@example.com E2E_PASSWORD='…' npx playwright test
   ```
   Runs on a desktop and a phone-sized screen and visits every page signed in.
3. Walk through [ACCEPTANCE.md](ACCEPTANCE.md) and tick what you have seen working.

## Updating later

```bash
cd ~/cit && git pull && docker compose -f infra/docker-compose.yml up -d --build && bash scripts/smoke.sh
```
