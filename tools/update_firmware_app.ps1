param(
  [Parameter(Mandatory)][string]$Port,
  [Parameter(Mandatory)][string]$ExpectedDeviceId,
  [Parameter(Mandatory)][ValidateSet('esp32c6','esp32s3')][string]$Chip,
  [Parameter(Mandatory)][string]$Firmware,
  [Parameter(Mandatory)][string]$BackupMetadata,
  [Parameter(Mandatory)][string]$Log
)
$ErrorActionPreference='Stop'
. "$PSScriptRoot\..\scripts\windows-env.ps1"
$backup=Get-Content -LiteralPath $BackupMetadata -Raw | ConvertFrom-Json
$backupImage=Join-Path (Split-Path -Parent $BackupMetadata) 'current-full-16MiB.bin'
if($backup.identity_before_bootloader.device_id -ne $ExpectedDeviceId -or $backup.chip -ne $Chip){throw 'Rollback identity/chip mismatch'}
if((Get-Item -LiteralPath $backupImage).Length -ne 16777216 -or (Get-FileHash -LiteralPath $backupImage -Algorithm SHA256).Hash.ToLowerInvariant() -ne $backup.sha256){throw 'Rollback image length/hash mismatch'}
if((Get-Item -LiteralPath $Firmware).Length -gt 3145728){throw 'Application exceeds target partition'}
$maintenanceLease = $null
try {
    if ($ExpectedDeviceId) {
        $leaseJson = & $MeterPython "$PSScriptRoot\maintenance.py" acquire --port $Port --device-id $ExpectedDeviceId
        if ($LASTEXITCODE) { throw 'Maintenance acquire failed; no firmware was written.' }
        $maintenanceLease = $leaseJson | ConvertFrom-Json
    }
$identityJson=& $MeterPython "$PSScriptRoot\serial_device.py" --identify $Port
if($LASTEXITCODE){throw 'Live identity unavailable; no write issued'}
$identity=$identityJson | ConvertFrom-Json
if($identity.device_id -ne $ExpectedDeviceId){throw 'Live full identity mismatch; no write issued'}
Write-Host "Verified $ExpectedDeviceId. Writing only application at0x10000; rollback hash verified."
& D:/build/CodexMeter/platformio/penv/Scripts/esptool.exe --chip $Chip --port $Port --baud 460800 --after hard-reset write-flash 0x10000 $Firmware *> $Log
if($LASTEXITCODE){throw "Application write failed; retained log: $Log"}
Get-Content -LiteralPath $Log -Tail 12

} finally {
    if ($maintenanceLease) {
        $maintenanceLease | ConvertTo-Json -Compress | & $MeterPython "$PSScriptRoot\maintenance.py" release
        if ($LASTEXITCODE) { Write-Warning 'Maintenance pause retained. Close all tools and use Displays > Resume.' }
    }
}
