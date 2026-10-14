$ErrorActionPreference = 'Stop'
if (-not (Test-Path '.venv')) { py -m venv .venv }
& .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Push-Location frontend; npm install; npm run build; Pop-Location
$env:PYTHONPATH = 'backend'; $env:DATABASE_URL = 'sqlite:///./second_patient.db'; $env:SEED_DEMO = 'true'
& .venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
& .venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
