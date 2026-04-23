#!/usr/bin/env bash
# pg_dump the ZTNA database once a day and rotate old dumps.
# Runs inside the `backup` sidecar (dcron fires this per the crontab).
set -euo pipefail

: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"
: "${POSTGRES_DB:?}"
: "${BACKUP_RETENTION_DAYS:=7}"

export PGPASSWORD="$POSTGRES_PASSWORD"

BACKUP_DIR=/backups
mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
OUTFILE="${BACKUP_DIR}/ztna-${STAMP}.dump"

pg_dump -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -Fc --no-owner --no-acl -Z 6 -f "$OUTFILE"

# Rotate: delete dumps older than retention (preserve at least the newest).
find "$BACKUP_DIR" -name "ztna-*.dump" -type f -mtime "+${BACKUP_RETENTION_DAYS}" -print -delete

echo "backup ok: $OUTFILE"
