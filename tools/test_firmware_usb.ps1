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
  $compile='call "'+$VcVars+'" >nul && cl /nologo /std:c++17 /EHsc /W4 /D_CRT_SECURE_NO_WARNINGS /I"'+$repo+'\tests\firmware_native" /I"'+$source+'" /I"'+$json+'" "'+$repo+'\tests\firmware_usb_protocol.cpp" "'+$source+'\serial_protocol.cpp" "'+$source+'\companion_session.cpp" "'+$source+'\companion_protocol.cpp" "'+$source+'\model.cpp" /Fe:firmware_usb_protocol.exe'
  & cmd.exe /d /s /c $compile
  if($LASTEXITCODE){throw 'Native firmware compile failed'}
  & .\firmware_usb_protocol.exe
  if($LASTEXITCODE){throw 'Native firmware tests failed'}
} finally {Pop-Location}
