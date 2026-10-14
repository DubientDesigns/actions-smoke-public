#!/usr/bin/env bash
# Post-deploy smoke test, run on the VPS from the repo root after `docker compose up -d`.
set -uo pipefail
cd "$(dirname "$0")/.."
C="docker compose -f infra/docker-compose.yml"
DOMAIN=$(grep -E '^CIT_DOMAIN=' .env | cut -d= -f2-)
fail=0
check() { if eval "$2" >/dev/null 2>&1; then echo "  ok    $1"; else echo "  FAIL  $1"; fail=1; fi; }

echo "containers"
for s in api worker web caddy backup; do
  check "$s running" "[ \"\$($C ps --format '{{.State}}' $s)\" = running ]"
done
check "worker healthy" "[ \"\$($C ps --format '{{.Health}}' worker)\" != unhealthy ]"

echo "internal API (from inside the network)"
check "api /healthz" "$C exec -T api python -c \"import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz',timeout=5)\""
check "api /readyz: database + worker heartbeat ok" "$C exec -T api python -c \"import json,urllib.request;r=json.load(urllib.request.urlopen('http://localhost:8000/readyz',timeout=5));assert r['status']=='ok',r\""

echo "public site"
check "https://$DOMAIN/login loads (200)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' https://$DOMAIN/login)\" = 200 ]"
check "http redirects to https" "curl -sI http://$DOMAIN/login | grep -qi '^location: https://'"
check "HSTS header" "curl -sI https://$DOMAIN/login | grep -qi '^strict-transport-security'"
check "frame protection header" "curl -sI https://$DOMAIN/login | grep -qi '^x-frame-options: deny'"
check "dashboard requires login" "curl -sI https://$DOMAIN/ | grep -qi '^location: .*/login'"
check "internal API not reachable publicly" "! curl -s https://$DOMAIN/v1/health/report | grep -q generated_at"
check "only 22/80/443 listening publicly" "! ss -ltnH | awk '{print \$4}' | grep -vE '(127\\.0\\.0\\.|\\[::1\\]|:22\$|:80\$|:443\$)' | grep -q ."

echo
[ $fail -eq 0 ] && echo "smoke: OK" || echo "smoke: FAILURES (see above; logs: $C logs --tail 100 <service>)"
exit $fail
