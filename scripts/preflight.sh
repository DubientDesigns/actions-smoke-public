#!/usr/bin/env bash
# Checks .env before deploying. Prints problems; exits non-zero if any are fatal.
# Never prints secret values.
set -uo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${1:-.env}"
fail=0; warn=0
bad()  { echo "  FAIL  $*"; fail=1; }
note() { echo "  WARN  $*"; warn=1; }
ok()   { echo "  ok    $*"; }

[ -f "$ENV_FILE" ] || { echo "no $ENV_FILE (cp .env.example .env)"; exit 1; }
perm=$(stat -c %a "$ENV_FILE" 2>/dev/null || echo "?")
[ "$perm" = "600" ] && ok ".env permissions 600" || bad ".env permissions are $perm (run: chmod 600 $ENV_FILE)"

get() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }

for v in CIT_DOMAIN CIT_DATABASE_URL NEXT_PUBLIC_SUPABASE_URL NEXT_PUBLIC_SUPABASE_ANON_KEY CIT_INTERNAL_API_TOKEN; do
  val=$(get "$v")
  if [ -z "$val" ]; then bad "$v is empty"
  elif printf '%s' "$val" | grep -q '[<>]\|example\.com'; then bad "$v still has a placeholder"
  else ok "$v set"; fi
done

tok=$(get CIT_INTERNAL_API_TOKEN)
[ "${#tok}" -ge 32 ] || bad "CIT_INTERNAL_API_TOKEN shorter than 32 chars (openssl rand -hex 32)"

db=$(get CIT_DATABASE_URL)
case "$db" in
  postgresql+psycopg://*) ok "database URL uses the psycopg driver";;
  *) bad "CIT_DATABASE_URL must start with postgresql+psycopg://";;
esac
case "$db" in *:6543/*)
  [ "$(get CIT_DATABASE_DISABLE_PREPARED_STATEMENTS)" = "true" ] || bad "transaction pooler (6543) needs CIT_DATABASE_DISABLE_PREPARED_STATEMENTS=true";;
esac

# Nothing privileged may be NEXT_PUBLIC_ (those values are shipped to every browser).
if grep -E '^NEXT_PUBLIC_' "$ENV_FILE" | grep -qiE 'service_role|postgres(ql)?://|sk-ant-|bot[0-9]+:'; then
  bad "a NEXT_PUBLIC_ variable contains a privileged secret"
fi
anon=$(get NEXT_PUBLIC_SUPABASE_ANON_KEY)
role=$(printf '%s' "$anon" | python3 -c '
import base64, json, sys
t = sys.stdin.read().strip().split(".")
try:
    p = t[1] + "=" * (-len(t[1]) % 4)
    print(json.loads(base64.urlsafe_b64decode(p)).get("role", "?"))
except Exception:
    print("not-a-jwt")' 2>/dev/null)
case "$role" in
  anon) ok "NEXT_PUBLIC_SUPABASE_ANON_KEY is the anon key";;
  service_role) bad "NEXT_PUBLIC_SUPABASE_ANON_KEY is the SERVICE ROLE key: replace it with the anon key now";;
  not-a-jwt) note "anon key is not a legacy JWT (new sb_publishable_ keys are fine)";;
  *) note "anon key role: $role";;
esac
case "$anon" in sb_secret_*) bad "NEXT_PUBLIC_SUPABASE_ANON_KEY is a SECRET key";; esac

for v in CIT_TELEGRAM_BOT_TOKEN CIT_TELEGRAM_ALERT_CHAT_ID CIT_ANTHROPIC_API_KEY CIT_ALCHEMY_API_KEY CIT_HELIUS_API_KEY CIT_HEALTHCHECK_PING_URL; do
  [ -n "$(get "$v")" ] && ok "$v set" || note "$v empty (feature stays off)"
done

dom=$(get CIT_DOMAIN)
if [ -n "$dom" ] && command -v getent >/dev/null; then
  ip=$(getent ahostsv4 "$dom" | awk 'NR==1{print $1}')
  [ -n "$ip" ] && ok "$dom resolves to $ip (must be this server's public IP)" || note "$dom does not resolve yet (TLS will fail until the A record exists)"
fi

[ -n "$(get RCLONE_REMOTE)" ] && ok "off-site backups configured" || note "RCLONE_REMOTE empty: backups stay on this disk only"

echo
[ $fail -eq 0 ] && { [ $warn -eq 1 ] && echo "preflight: OK (with warnings)" || echo "preflight: OK"; } || echo "preflight: FIX THE FAILURES ABOVE"
exit $fail
