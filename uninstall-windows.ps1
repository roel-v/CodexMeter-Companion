[CmdletBinding()]
param([string]$BuildRoot = 'D:\build\CodexMeter')
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\scripts\windows-env.ps1" -BuildRoot $BuildRoot
if (Test-Path -LiteralPath $MeterPython) {
    & $MeterPython -c 'import asyncio; from codexmeter.events import send_event; asyncio.run(send_event({"type":"shutdown"}))'
}
$meterWrapper = Join-Path $env:LOCALAPPDATA 'CodexMeter\desktop-wrapper\CodexMeterDesktopCLI.exe'
if ([Environment]::GetEnvironmentVariable('CODEX_CLI_PATH','User') -eq $meterWrapper) {
    [Environment]::SetEnvironmentVariable('CODEX_CLI_PATH', $null, 'User')
}
$shortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'CodexMeter Bridge.lnk'
if (Test-Path -LiteralPath $shortcut) { Remove-Item -LiteralPath $shortcut }
$shortcut = Join-Path $PSScriptRoot 'CodexMeter.lnk'
if (Test-Path -LiteralPath $shortcut) { Remove-Item -LiteralPath $shortcut }
Write-Host 'Bridge stopped and launchers removed. Source, D: dependencies and personal data are retained.'
Write-Host 'If you installed hooks, disable the two CodexMeter hooks in Codex /hooks.'
