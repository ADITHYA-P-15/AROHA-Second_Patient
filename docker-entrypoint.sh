#!/bin/sh
set -eu
cd /app/backend
if [ "${APP_ENV:-dev}" = "prod" ] && [ "${SECRET_KEY:-}" = "change-me-before-production" ]; then echo "SECRET_KEY must be changed in production" >&2; exit 1; fi
if [ "${APP_ENV:-dev}" = "prod" ] && [ "${#SECRET_KEY}" -lt 32 ]; then echo "SECRET_KEY must be at least 32 characters in production" >&2; exit 1; fi
if [ "${APP_ENV:-dev}" = "prod" ] && [ "${COOKIE_SECURE:-false}" != "true" ]; then echo "COOKIE_SECURE=true is required in production (serve over HTTPS)" >&2; exit 1; fi
python - <<'PY'
import os, time
from sqlalchemy import create_engine, text
engine=create_engine(os.environ["DATABASE_URL"])
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
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers
