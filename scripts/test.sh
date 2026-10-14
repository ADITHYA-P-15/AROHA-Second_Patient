#!/bin/sh
set -eu
PYTHONPATH=backend python3 -m pytest backend/tests -q
(cd frontend && npm run lint && npm run typecheck && npm test && npm run build)
