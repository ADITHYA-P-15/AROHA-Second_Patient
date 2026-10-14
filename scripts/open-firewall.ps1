param([switch]$Remove)
$name = 'The Second Patient LAN (TCP 8000)'
if ($Remove) { Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule; exit 0 }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run PowerShell as Administrator to open the LAN firewall rule.' }
if (-not (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)) { New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Any | Out-Null }
Write-Host 'Inbound TCP 8000 allowed on all Windows profiles.'
