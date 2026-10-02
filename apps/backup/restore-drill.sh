#!/bin/sh
set -eu

latest_db="$(ls -1t /backups/db-*.dump 2>/dev/null | head -n 1 || true)"
latest_media="$(ls -1t /backups/media-*.tar.gz 2>/dev/null | head -n 1 || true)"

if [ -z "$latest_db" ] || [ -z "$latest_media" ]; then
  echo "Restore drill failed: database dump and media archive are both required." >&2
  exit 1
fi

echo "Using database backup: $latest_db"
echo "Using media backup: $latest_media"

pg_restore --list "$latest_db" >/dev/null
tar -tzf "$latest_media" >/dev/null

pg_restore --clean --if-exists --no-owner --no-privileges -d "$PGDATABASE" "$latest_db"

table_count="$(psql -Atc "select count(*) from pg_tables where schemaname='public';")"
if [ "$table_count" -lt 1 ]; then
  echo "Restore drill failed: restored database has no public tables." >&2
  exit 1
fi

rm -rf /restore-media/*
tar -xzf "$latest_media" -C /restore-media

file_count="$(find /restore-media -type f | wc -l | tr -d ' ')"
echo "Restore drill passed: $table_count database tables restored; $file_count media files extracted."
