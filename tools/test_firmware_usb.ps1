param([string]$BuildRoot='D:\build\CodexMeter',[string]$VcVars='C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat')
$ErrorActionPreference='Stop'
. "$PSScriptRoot\..\scripts\windows-env.ps1" -BuildRoot $BuildRoot
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$out=Join-Path $BuildRoot 'usb-phase2-native'
New-Item -ItemType Directory -Force $out | Out-Null
$json=Join-Path $BuildRoot 'libdeps\waveshare_c6_amoled_216\ArduinoJson\src'
$source=Join-Path $repo 'firmware\src'
Push-Location $out
try {
  $compile='call "'+$VcVars+'" >nul && cl /nologo /std:c++17 /EHsc /W4 /D_CRT_SECURE_NO_WARNINGS /I"'+$repo+'\tests\firmware_native" /I"'+$source+'" /I"'+$json+'" "'+$repo+'\tests\firmware_usb_protocol.cpp" "'+$source+'\serial_protocol.cpp" "'+$source+'\companion_session.cpp" "'+$source+'\companion_protocol.cpp" "'+$source+'\model.cpp" "'+$source+'\dashboard_view_model.cpp" /Fe:firmware_usb_protocol.exe'
  & cmd.exe /d /s /c $compile
  if($LASTEXITCODE){throw 'Native firmware compile failed'}
  & .\firmware_usb_protocol.exe
  if($LASTEXITCODE){throw 'Native firmware tests failed'}
} finally {Pop-Location}

# Compile the real parser twice, including an isolated smaller-limit variant.
# The copied header is test-only; production sources and builds remain untouched.
foreach($variant in @('production','reduced')) {
  $variantRoot=Join-Path $out ('limits-'+$variant)
  New-Item -ItemType Directory -Force $variantRoot | Out-Null
  Copy-Item -Path (Join-Path $source '*.h') -Destination $variantRoot -Force
  foreach($name in @('serial_protocol.cpp','companion_session.cpp','companion_protocol.cpp')) {
    Copy-Item -LiteralPath (Join-Path $source $name) -Destination $variantRoot -Force
  }
  if($variant -eq 'reduced') {
    $header=Join-Path $variantRoot 'protocol_limits.h'
    $text=[IO.File]::ReadAllText($header).Replace('frame_limit = 640','frame_limit = 320').Replace('payload_limit = 512','payload_limit = 128')
    [IO.File]::WriteAllText($header,$text)
  }
  Push-Location $variantRoot
  try {
    $compile='call "'+$VcVars+'" >nul && cl /nologo /std:c++17 /EHsc /W4 /D_CRT_SECURE_NO_WARNINGS /I"'+$repo+'\tests\firmware_native" /I"'+$variantRoot+'" /I"'+$json+'" "'+$repo+'\tests\firmware_protocol_limits.cpp" serial_protocol.cpp companion_session.cpp companion_protocol.cpp /Fe:limits.exe'
    & cmd.exe /d /s /c $compile
    if($LASTEXITCODE){throw 'Limit-test compile failed'}
    & .\limits.exe
    if($LASTEXITCODE){throw 'Parser boundary tests failed'}
  } finally {Pop-Location}
}

# Exercise the production theme helpers against a minimal LVGL boundary.
Push-Location $out
try {
  $compile='call "'+$VcVars+'" >nul && cl /nologo /std:c++17 /EHsc /W4 /I"'+$repo+'\tests\theme_native" /I"'+$source+'" "'+$repo+'\tests\theme_helpers.cpp" /Fe:theme_helpers.exe'
  & cmd.exe /d /s /c $compile
  if($LASTEXITCODE){throw 'Theme-helper compile failed'}
  & .\theme_helpers.exe
  if($LASTEXITCODE){throw 'Theme-helper tests failed'}
} finally {Pop-Location}
