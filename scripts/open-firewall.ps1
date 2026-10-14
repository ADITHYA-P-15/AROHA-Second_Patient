param([switch]$Remove)
$name = 'The Second Patient LAN (TCP 8000)'
if ($Remove) { Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule; exit 0 }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run PowerShell as Administrator to open the LAN firewall rule.' }
$rule = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
if ($rule) {
  $remote = $rule | Get-NetFirewallAddressFilter
  $port = $rule | Get-NetFirewallPortFilter
  if ($rule.Enabled -eq 'True' -and $rule.Profile -eq 'Any' -and $remote.RemoteAddress -contains 'LocalSubnet' -and $port.Protocol -eq 'TCP' -and $port.LocalPort -contains '8000') {
    Write-Host 'LAN access is already enabled for TCP 8000 (local subnet only).'
    exit 0
  }
  $rule | Remove-NetFirewallRule
}
New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -RemoteAddress LocalSubnet -Profile Any | Out-Null
Write-Host 'Inbound TCP 8000 allowed from the local subnet on all Windows profiles.'
