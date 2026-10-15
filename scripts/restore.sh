#!/usr/bin/env bash
# Restore a backup into the production database. DESTRUCTIVE: replaces everything. Usage:
#   bash scripts/restore.sh backups/carecircle-20261015-101500.sql.gz --yes
set -euo pipefail
cd "$(dirname "$0")/.."
FILE="${1:-}"; CONFIRM="${2:-}"
[ -f "$FILE" ] || { echo "usage: $0 <backup.sql.gz> --yes" >&2; exit 2; }
[ "$CONFIRM" = "--yes" ] || { echo "This replaces the production database with $FILE. Re-run with --yes to confirm." >&2; exit 2; }
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"
set -a; . ./.env.production; set +a
U="${POSTGRES_USER:-carecircle}"; D="${POSTGRES_DB:-carecircle}"
gzip -t "$FILE"
echo "Taking a safety backup of the current state first..."; bash scripts/backup.sh
$COMPOSE stop app
$COMPOSE exec -T db psql -U "$U" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$D\" WITH (FORCE);" -c "CREATE DATABASE \"$D\" OWNER \"$U\";"
gunzip -c "$FILE" | $COMPOSE exec -T db psql -U "$U" -d "$D" -v ON_ERROR_STOP=1 -q
$COMPOSE up -d --no-deps app
echo "restored from $FILE; the app is starting (it applies any newer migrations on boot)."
