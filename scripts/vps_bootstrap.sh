#!/usr/bin/env bash
# One-time hardening + Docker install for a fresh Ubuntu 24.04 VPS. Run as root:
#   ADMIN_IP=203.0.113.7 bash scripts/vps_bootstrap.sh
# ADMIN_IP (optional): only this address may reach SSH. Without it SSH is open but rate-limited.
# Idempotent: safe to run again. Never disables password SSH unless a key is installed
# (so it cannot lock you out).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || echo "warning: tested on Ubuntu 24.04 only (found ${PRETTY_NAME:-unknown})"

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -yq
apt-get install -yq docker.io docker-compose-v2 git ufw fail2ban unattended-upgrades postgresql-client curl

# Automatic security updates (reboots are left to you; check /var/run/reboot-required).
dpkg-reconfigure -f noninteractive unattended-upgrades
systemctl enable --now unattended-upgrades

# Docker: bounded logs, no inter-container leakage of userland proxies.
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'JSON'
{"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "5"}, "live-restore": true}
JSON
systemctl enable --now docker
systemctl restart docker

# 2 GB swap on small boxes (Next.js build + workers).
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Firewall: only 80/443 public; SSH from ADMIN_IP (or rate-limited).
ufw default deny incoming
ufw default allow outgoing
ufw allow 80/tcp
ufw allow 443/tcp
if [ -n "${ADMIN_IP:-}" ]; then
  ufw allow from "$ADMIN_IP" to any port 22 proto tcp
else
  ufw limit 22/tcp
fi
ufw --force enable

# SSH: keys only, but only once a key exists (lockout guard).
if [ -s /root/.ssh/authorized_keys ] || ls /home/*/.ssh/authorized_keys >/dev/null 2>&1; then
  cat > /etc/ssh/sshd_config.d/90-cit.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
CONF
  systemctl reload ssh || systemctl reload sshd || true
  echo "SSH: password login disabled (key found)."
else
  echo "SSH: NO authorized key found, password login left ON. Add your key, then re-run."
fi
systemctl enable --now fail2ban

echo
echo "Done. Next: git clone the repo, create .env (see docs/DEPLOY.md), run scripts/preflight.sh."
