#!/bin/sh
# Daily PostgreSQL backup (the `backup-db` service in docker-compose.prod.yml).
#
#   /backups/db/javon-YYYYMMDD-HHMM.dump   pg_dump custom format, compressed
#   kept BACKUP_KEEP_DAYS days (14 by default)
#
# The dump is written as *.part and renamed when complete, so a half-written file
# is never mistaken for a backup. Restore (stop backend and worker first):
#   pg_restore -h postgres -U javon_owner -d javon --clean --if-exists /backups/db/<file>.dump
#
# The backups stay on this server, in Uzbekistan (personal-data law). Copy the
# folder to a second server in Uzbekistan as well: one disk is not a backup.
set -eu

KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
INTERVAL="${BACKUP_INTERVAL_S:-86400}"
mkdir -p /backups/db
export PGPASSWORD="$JAVON_OWNER_PASSWORD"

until pg_isready -h postgres -U javon_owner -d javon >/dev/null 2>&1; do sleep 5; done

while true; do
  stamp="$(date -u +%Y%m%d-%H%M)"
  target="/backups/db/javon-$stamp.dump"
  if pg_dump -h postgres -U javon_owner -d javon --format=custom --compress=6 --file="$target.part"; then
    mv "$target.part" "$target"
    echo "{\"msg\": \"database backup written\", \"file\": \"$target\", \"bytes\": $(wc -c < "$target")}"
  else
    rm -f "$target.part"
    echo "{\"msg\": \"database backup FAILED\", \"level\": \"ERROR\"}" >&2
  fi
  find /backups/db -name 'javon-*.dump' -mtime +"$KEEP_DAYS" -delete
  sleep "$INTERVAL"
done
