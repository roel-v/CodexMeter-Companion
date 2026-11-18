[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^COM[0-9]+$')][string]$Port,
    [ValidateSet('waveshare_c6_amoled_216', 'waveshare_amoled_216', 'spotpear_ball_v2')]
    [string]$Board = 'waveshare_c6_amoled_216',
    [string]$BuildRoot = 'D:\build\CodexMeter',
    [string]$ExpectedDeviceId,
    [switch]$FirstFlash
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\scripts\windows-env.ps1" -BuildRoot $BuildRoot
if (-not (Test-Path -LiteralPath $MeterPython)) { throw 'Run build-windows.ps1 -Firmware first.' }
if ((Get-PSDrive D).Free -lt 8GB) { throw 'At least 8 GiB free on D: is required. Review cold storage before building.' }
# Complete compilation before starting the finite device-side maintenance lease.
# The upload invocation reuses this build; no source/configuration changes occur between these steps.
& $MeterPython -m platformio run -d "$PSScriptRoot\firmware" -e $Board
if ($LASTEXITCODE) { throw 'Firmware preparation failed; no maintenance lease or flash was started.' }
$maintenanceLease = $null
try {
    if (-not $FirstFlash) {
        $maintenanceArgs = @('acquire', '--port', $Port)
        if ($ExpectedDeviceId) { $maintenanceArgs += @('--device-id', $ExpectedDeviceId) }
        $leaseJson = & $MeterPython "$PSScriptRoot\tools\maintenance.py" @maintenanceArgs
        if ($LASTEXITCODE) { throw 'Maintenance acquire failed; no firmware was written.' }
        $maintenanceLease = $leaseJson | ConvertFrom-Json
    }
if (-not $FirstFlash) {
    if ($Board -eq 'spotpear_ball_v2' -and -not $ExpectedDeviceId) {
        throw 'Ball upgrades require -ExpectedDeviceId from a verified board. COM number alone is insufficient.'
    }
    $identityJson = & $MeterPython "$PSScriptRoot\tools\serial_device.py" --identify $Port
    if ($LASTEXITCODE) { throw 'The port is not a running CodexMeter. For initial setup, verify the board and use -FirstFlash.' }
    $identity = $identityJson | ConvertFrom-Json
    if ($ExpectedDeviceId -and $identity.device_id -ne $ExpectedDeviceId) {
        throw "Device identity mismatch on $Port. No firmware was written."
    }
    Write-Host $identityJson
}
Write-Host "Writing $Board to $Port. This replaces the board's installed application."
# esptool checks the chip family. Never use --force to bypass that check.
& $MeterPython -m platformio run -d "$PSScriptRoot\firmware" -e $Board -t upload --upload-port $Port
if ($LASTEXITCODE) { throw 'Firmware upload failed.' }
# C6's normal upload includes the raw artwork pack through FLASH_EXTRA_IMAGES.
# Its artwork partition is not LittleFS; do not run uploadfs for C6.
if ($Board -eq 'waveshare_amoled_216') {
    & $MeterPython -m platformio run -d "$PSScriptRoot\firmware" -e $Board -t uploadfs --upload-port $Port
    if ($LASTEXITCODE) { throw 'Filesystem upload failed.' }
}

} finally {
    if ($maintenanceLease) {
        $maintenanceLease | ConvertTo-Json -Compress | & $MeterPython "$PSScriptRoot\tools\maintenance.py" release
        if ($LASTEXITCODE) { Write-Warning 'Maintenance pause retained. Close all tools and use Displays > Resume.' }
    }
}
