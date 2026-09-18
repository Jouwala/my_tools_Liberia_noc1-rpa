param(
    [switch]$Restore
)

$ErrorActionPreference = 'Stop'
$adapter = Get-NetAdapter -Name 'Wi-Fi' -ErrorAction Stop
$pnp = $adapter.PnPDeviceID
Write-Host "Wi-Fi PnPDeviceID: $pnp"

$targets = Get-CimInstance -Namespace root/wmi -ClassName MSPower_DeviceEnable |
    Where-Object { $_.InstanceName.StartsWith($pnp, [StringComparison]::OrdinalIgnoreCase) }

if (-not $targets) {
    Write-Host "[WARN] No power-management entry found for the Wi-Fi adapter; nothing changed."
    exit 0
}

$allow = [bool]$Restore   # Restore -> Enable=True (allow turn off); default -> False
foreach ($t in $targets) {
    Set-CimInstance -InputObject $t -Property @{ Enable = $allow }
    Write-Host ("Set Enable={0} on {1}" -f $allow, $t.InstanceName)
}
if ($Restore) {
    Write-Host "Restored: Windows may again turn off the Wi-Fi adapter to save power."
} else {
    Write-Host "Done: Windows can no longer turn off the Wi-Fi adapter to save power."
}
