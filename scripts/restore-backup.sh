#!/usr/bin/env bash
# Restore the ZTNA database from a `backup` sidecar dump.
# Usage:
#   ./scripts/restore-backup.sh backups/ztna-2026-04-22T02-15-00Z.dump
#
# Requires the working directory to be the repo root and docker-compose
# services available. Prompts before destructive actions.
set -euo pipefail

DUMP="${1:?usage: $0 <backup-file>}"
[ -f "$DUMP" ] || { echo "no such file: $DUMP" >&2; exit 1; }

# Load env so POSTGRES_USER/_DB are available for psql/pg_restore.
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
: "${POSTGRES_USER:?set POSTGRES_USER in .env}"
: "${POSTGRES_DB:?set POSTGRES_DB in .env}"

echo "This will STOP app services, WIPE the public schema in ${POSTGRES_DB},"
echo "and restore from ${DUMP}."
read -r -p "Type RESTORE to continue: " answer
[ "$answer" = "RESTORE" ] || { echo "aborted"; exit 1; }

docker compose stop api flow-ingest id-ingest correlator
docker compose up -d postgres redis
sleep 3

docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
  DROP SCHEMA public CASCADE;
  CREATE SCHEMA public;
SQL

docker compose exec -T postgres pg_restore \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-acl \
  < "$DUMP"

# Re-apply migrations so schema matches current code, then bring stack back up.
docker compose up -d --no-deps migrate
docker compose up -d
echo "restore complete"
