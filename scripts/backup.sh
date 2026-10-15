#!/usr/bin/env bash
# Dump the production database to backups/ (compressed, verified). Keeps the newest KEEP files (default 14).
#   bash scripts/backup.sh            # run before every deploy, and daily from cron
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"
set -a; . ./.env.production; set +a
KEEP="${KEEP:-14}"
mkdir -p backups
FILE="backups/carecircle-$(date -u +%Y%m%d-%H%M%S).sql.gz"
$COMPOSE exec -T db pg_dump -U "${POSTGRES_USER:-carecircle}" --no-owner "${POSTGRES_DB:-carecircle}" | gzip > "$FILE"
gzip -t "$FILE"                                   # the archive must be readable
[ "$(wc -c < "$FILE")" -gt 1000 ] || { echo "backup looks empty: $FILE" >&2; rm -f "$FILE"; exit 1; }
echo "backup written: $FILE ($(du -h "$FILE" | cut -f1))"
ls -1t backups/carecircle-*.sql.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
