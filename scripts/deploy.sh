#!/usr/bin/env bash
# Deploy a version to this server with a safety net. Run from the repository on the server:
#   bash scripts/deploy.sh [git-ref]        # a tag, branch or commit; default: what is checked out now
#
# Order matters: back up -> build (the build runs the whole test suite; failure leaves the live app untouched)
# -> switch the app (migrations run on boot) -> wait for health -> verify -> roll back automatically if anything fails.
set -euo pipefail

main() {
  cd "$(dirname "$0")/.."
  [ -f .env.production ] || { echo ".env.production is missing (copy .env.production.example)" >&2; exit 1; }
  COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"
  set -a; . ./.env.production; set +a

  REF="${1:-}"
  # The image is labelled with the commit it is built from, so the tree must match that commit exactly.
  if [ "${ALLOW_DIRTY:-}" != "1" ] && [ -n "$(git status --porcelain)" ]; then
    echo "the working tree has local changes: deploy a clean commit (or set ALLOW_DIRTY=1 for a throwaway test)" >&2; exit 1
  fi
  if [ -n "$REF" ]; then
    git fetch --tags --prune origin
    git checkout --detach "$REF"
  fi
  SHA="$(git rev-parse --short=10 HEAD)"
  PREVIOUS_ID="$($COMPOSE ps -q app 2>/dev/null || true)"
  PREVIOUS_TAG=""
  [ -n "$PREVIOUS_ID" ] && PREVIOUS_TAG="$(docker inspect --format '{{.Config.Image}}' "$PREVIOUS_ID" | awk -F: '{print $NF}')"
  echo "==> deploying $SHA (currently running: ${PREVIOUS_TAG:-nothing})"

  echo "==> 1/6 backup"
  $COMPOSE up -d db
  if [ -n "$PREVIOUS_TAG" ]; then bash scripts/backup.sh; else echo "first deployment: nothing to back up"; fi

  echo "==> 2/6 build (runs the test suite; the running app is untouched)"
  GIT_SHA="$SHA" APP_TAG="$SHA" $COMPOSE build app

  wait_healthy() {
    for _ in $(seq 1 60); do
      ID="$($COMPOSE ps -q app)"
      STATE="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$ID" 2>/dev/null || echo none)"
      [ "$STATE" = "healthy" ] && return 0
      sleep 3
    done
    return 1
  }
  rollback() {
    echo "!! deployment failed: $1" >&2
    if [ -n "$PREVIOUS_TAG" ]; then
      echo "==> rolling back to $PREVIOUS_TAG"
      GIT_SHA="$PREVIOUS_TAG" APP_TAG="$PREVIOUS_TAG" $COMPOSE up -d --no-deps app
      wait_healthy && echo "rolled back; the database was only extended, so the previous version runs on it" || echo "ROLLBACK DID NOT BECOME HEALTHY: see docs/DEPLOYMENT.md, restore from backups/" >&2
    fi
    exit 1
  }

  echo "==> 3/6 switch the app (migrations run on boot)"
  GIT_SHA="$SHA" APP_TAG="$SHA" $COMPOSE up -d --no-deps app
  echo "==> 4/6 wait for health"
  wait_healthy || { $COMPOSE logs --tail 60 app >&2; rollback "the new version did not become healthy"; }
  echo "==> 5/6 front door (HTTPS)"
  GIT_SHA="$SHA" APP_TAG="$SHA" $COMPOSE up -d caddy
  echo "==> 6/6 verify"
  # CHECK_INSECURE=1 accepts the self-signed certificate of a private-network deployment
  python3 scripts/postdeploy_check.py --base-url "https://${DOMAIN}" --expect-sha "$SHA" --wait-scheduler --expect-prod ${CHECK_INSECURE:+--insecure} \
    || rollback "post-deploy checks failed"

  docker tag "carecircle-app:$SHA" carecircle-app:latest
  # keep the three newest images for quick rollbacks
  docker images carecircle-app --format '{{.Tag}} {{.CreatedAt}}' | grep -v latest | sort -k2 -r | awk 'NR>3 {print $1}' | xargs -r -I{} docker rmi "carecircle-app:{}" 2>/dev/null || true
  echo "==> done: $SHA is live at https://${DOMAIN}"
}
main "$@"
exit $?
