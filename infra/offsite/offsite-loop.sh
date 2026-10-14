#!/bin/sh
# Copies ./backups to off-site object storage once a day (after the nightly dump).
# Configure an rclone remote named "offsite" with RCLONE_CONFIG_OFFSITE_* variables in .env
# (e.g. Cloudflare R2 or Backblaze B2 free tier) and RCLONE_REMOTE=offsite:<bucket>/cit.
set -eu
: "${RCLONE_REMOTE:?set RCLONE_REMOTE, e.g. offsite:my-bucket/cit}"
HOUR_UTC="${OFFSITE_HOUR_UTC:-20}"   # 04:00 Asia/Singapore, one hour after the dump
while true; do
  if [ "$(date -u +%H)" = "$HOUR_UTC" ]; then
    # copy (not sync): deleting locally never deletes the off-site copy.
    if rclone copy /backups "$RCLONE_REMOTE" --include 'cit-*.dump' --max-age 3d --no-traverse; then
      echo "{\"event\":\"offsite_ok\"}"
    else
      echo "{\"event\":\"offsite_failed\"}"
    fi
    sleep 3700
  else
    sleep 600
  fi
done
