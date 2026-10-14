#!/bin/sh
set -eu
command -v docker >/dev/null 2>&1 || { echo 'Docker is required.' >&2; exit 1; }
if [ ! -f .env ]; then
  cp .env.example .env
  python3 -c 'from pathlib import Path; import secrets; p=Path(".env"); p.write_text(p.read_text().replace("change-me-before-production",secrets.token_hex(32)),encoding="utf-8")'
fi
docker compose up --build -d
python3 -c 'import time,urllib.request; [(time.sleep(2),urllib.request.urlopen("http://localhost:8000/api/health",timeout=2)) for _ in range(60)]'
python3 scripts/lan-info.py
