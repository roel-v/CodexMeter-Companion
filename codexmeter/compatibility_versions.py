"""Best-effort local executable metadata; never launches Codex or contacts a server."""
import json
import os
import re
import subprocess
import sys

def local_versions(codex_bin):
    from . import __version__
    result = {"codexmeter": __version__, "desktop": "unknown", "quota_cli": "unknown",
              "provenance": "local executable metadata", "desktop_running": None}
    if sys.platform != "win32":
        return result
    from .app_server import resolve_codex_binary
    try:
        cli = resolve_codex_binary(codex_bin) or ""
        command = """
$ErrorActionPreference='Stop'
$apps = @(Get-Process -Name ChatGPT -ErrorAction SilentlyContinue | Where-Object { $_.Path -match 'OpenAI.Codex' })
$versions = @($apps | ForEach-Object { if ($_.Path -match 'OpenAI.Codex_([0-9.]+)_') { $Matches[1] } } | Sort-Object -Unique)
$cliVersion = if (Test-Path -LiteralPath $env:CODEXMETER_VERSION_TARGET) { (Get-Item -LiteralPath $env:CODEXMETER_VERSION_TARGET).VersionInfo.ProductVersion } else { $null }
@{desktop_running=($apps.Count -gt 0); desktop=$versions; quota_cli=$cliVersion} | ConvertTo-Json -Compress
"""
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            env={**os.environ, "CODEXMETER_VERSION_TARGET": cli}, capture_output=True,
            text=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        raw = json.loads(completed.stdout) if completed.returncode == 0 else {}
        if type(raw.get("desktop_running")) is bool:
            result["desktop_running"] = raw["desktop_running"]
        versions = raw.get("desktop")
        if isinstance(versions, list) and len(versions) == 1:
            result["desktop"] = versions[0]
        result["quota_cli"] = raw.get("quota_cli") or "unknown"
        for key in ("desktop", "quota_cli"):
            if not isinstance(result[key], str) or not re.fullmatch(r"[0-9A-Za-z.+_-]{1,64}", result[key]):
                result[key] = "unknown"
    except Exception:
        pass
    return result
