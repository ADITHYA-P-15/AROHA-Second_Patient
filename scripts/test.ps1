$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'backend'
py -m pytest backend\tests -q
Push-Location frontend
npm run lint
npm run typecheck
npm test
npm run build
Pop-Location
