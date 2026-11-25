[CmdletBinding()]
param([string]$BuildRoot = 'D:\build\CodexMeter')
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\windows-env.ps1" -BuildRoot $BuildRoot
$env:GOCACHE = Join-Path $BuildRoot 'go-cache'
$env:GOMODCACHE = Join-Path $BuildRoot 'go-modules'
$env:GOPATH = Join-Path $BuildRoot 'go'
$env:GOTMPDIR = $env:TEMP
$out = Join-Path $BuildRoot 'desktop-wrapper'
New-Item -ItemType Directory -Force -Path $out | Out-Null
Push-Location "$PSScriptRoot\..\tools\desktop-wrapper"
try {
    & go test ./...
    if ($LASTEXITCODE) { throw 'Desktop wrapper tests failed.' }
    & go build -trimpath -o "$out\CodexMeterDesktopCLI.exe" .
    if ($LASTEXITCODE) { throw 'Desktop wrapper build failed.' }
} finally { Pop-Location }
