#!/bin/sh
set -eu
cd /app/backend
# Render exposes the deployed commit as RENDER_GIT_COMMIT; show it in /api/health so a deploy can be verified.
if [ "${GIT_SHA:-dev}" = "dev" ] && [ -n "${RENDER_GIT_COMMIT:-}" ]; then GIT_SHA="$(printf %s "$RENDER_GIT_COMMIT" | cut -c1-10)"; export GIT_SHA; fi
if [ "${APP_ENV:-dev}" = "prod" ] && [ "${SECRET_KEY:-}" = "change-me-before-production" ]; then echo "SECRET_KEY must be changed in production" >&2; exit 1; fi
if [ "${APP_ENV:-dev}" = "prod" ] && [ "${#SECRET_KEY}" -lt 32 ]; then echo "SECRET_KEY must be at least 32 characters in production" >&2; exit 1; fi
if [ "${APP_ENV:-dev}" = "prod" ] && [ "${COOKIE_SECURE:-false}" != "true" ]; then echo "COOKIE_SECURE=true is required in production (serve over HTTPS)" >&2; exit 1; fi
python - <<'PY'
import time
from sqlalchemy import create_engine, text
from app.core.config import settings   # normalises postgres:// URLs from hosting platforms
engine = create_engine(settings.database_url)
for attempt in range(60):
    try:
        with engine.connect() as conn: conn.execute(text("SELECT 1"))
        break
    except Exception:
        if attempt == 59: raise
        time.sleep(2)
PY
python -m alembic upgrade head
if [ "${SEED_DEMO:-true}" = "true" ]; then python -c 'from app.main import seed; seed()'; fi
# PORT is set by hosting platforms (Render, Railway, Cloud Run); FORWARDED_ALLOW_IPS=* trusts the platform's proxy for the client IP and scheme.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
