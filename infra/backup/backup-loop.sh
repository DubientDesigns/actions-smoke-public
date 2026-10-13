#!/bin/sh
# Nightly logical backup of the application schema(s) to /backups, keeping
# BACKUP_KEEP_DAYS days. Uses CIT_DATABASE_URL (the same privileged DSN as the
# workers). Copy ./backups off the VPS (e.g. rclone to free object storage) for
# real disaster recovery — a backup on the same disk is not enough.
set -eu
KEEP="${BACKUP_KEEP_DAYS:-14}"
HOUR_UTC="${BACKUP_HOUR_UTC:-19}"   # 03:00 Asia/Singapore
DSN="$(echo "$CIT_DATABASE_URL" | sed 's#postgresql+psycopg://#postgresql://#')"

while true; do
  now_h=$(date -u +%H)
  if [ "$now_h" = "$HOUR_UTC" ]; then
    f="/backups/cit-$(date -u +%Y%m%dT%H%M%SZ).dump"
    if pg_dump --format=custom --no-owner --no-privileges --schema=public --schema=cit_meta \
         --file="$f.partial" "$DSN"; then
      mv "$f.partial" "$f"
      echo "{\"event\":\"backup_ok\",\"file\":\"$f\",\"bytes\":$(wc -c < "$f")}"
    else
      rm -f "$f.partial"
      echo "{\"event\":\"backup_failed\"}"
    fi
    find /backups -name 'cit-*.dump' -mtime +"$KEEP" -delete
    sleep 3700
  else
    sleep 600
  fi
done
