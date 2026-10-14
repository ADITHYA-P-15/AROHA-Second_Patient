$ErrorActionPreference = 'Stop'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop is required.' }
if (-not (Test-Path '.env')) {
  Copy-Item '.env.example' '.env'
  $secretBytes = New-Object byte[] 32
  $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($secretBytes)
  $secret = ([BitConverter]::ToString($secretBytes) -replace '-', '').ToLower()
  (Get-Content '.env' -Raw).Replace('change-me-before-production', $secret) | Set-Content '.env' -NoNewline
}
docker compose up --build -d
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose build/start failed.' }
$healthy = $false
for ($i=0; $i -lt 60; $i++) { try { Invoke-RestMethod 'http://localhost:8000/api/health' -TimeoutSec 2 | Out-Null; $healthy = $true; break } catch { Start-Sleep 2 } }
if (-not $healthy) { docker compose logs app; throw 'App did not become healthy within 120 seconds.' }
python scripts/lan-info.py
