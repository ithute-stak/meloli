#!/bin/sh
set -eu

interval="${BACKUP_INTERVAL_SECONDS:-86400}"
retention="${BACKUP_RETENTION_DAYS:-14}"

while true; do
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  tmp_db="/backups/db-$ts.dump.tmp"
  final_db="/backups/db-$ts.dump"
  tmp_media="/backups/media-$ts.tar.gz.tmp"
  final_media="/backups/media-$ts.tar.gz"

  pg_dump -Fc -f "$tmp_db"
  mv "$tmp_db" "$final_db"

  tar -czf "$tmp_media" -C /media .
  mv "$tmp_media" "$final_media"

  # Verify that both artifacts can be read before reporting success.
  pg_restore --list "$final_db" >/dev/null
  tar -tzf "$final_media" >/dev/null

  date -u +%Y-%m-%dT%H:%M:%SZ > /backups/last-success
  find /backups -type f \( -name 'db-*.dump' -o -name 'media-*.tar.gz' \) -mtime +"$retention" -delete
  sleep "$interval"
done
