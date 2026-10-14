#!/bin/sh
set -eu
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)
export PYTHONPATH=backend DATABASE_URL="sqlite:///./second_patient.db" SEED_DEMO=true
python -m alembic -c backend/alembic.ini upgrade head
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
