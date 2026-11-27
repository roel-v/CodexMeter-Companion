"""Windows Desktop CLI selection and read-only status snapshots."""
from __future__ import annotations

import ctypes
import gzip
import logging
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .compatibility import ContractError
from .compatibility_readers import read_roots
from .settings import APP_DIR

VARIABLE = "CODEX_CLI_PATH"
FILENAME = "CodexMeterDesktopCLI.exe"


class WrapperPreference:
    """Keep an explicit opt-out across companion and Desktop upgrades."""

    def __init__(self, directory=APP_DIR):
        self.opt_out = directory / "desktop-wrapper.disabled"

    def wanted(self):
        return not self.opt_out.exists()

    def save(self, wanted):
        if wanted:
            self.opt_out.unlink(missing_ok=True)
        else:
            self.opt_out.parent.mkdir(parents=True, exist_ok=True)
            self.opt_out.touch()


class WrapperSetup:
    """The bridge is the sole writer of the helper and CLI registration."""

    def __init__(self, directory=APP_DIR):
        self.preference = WrapperPreference(directory)
        self.applied = None
        self.retry_at = 0
        self.error = ""

    def reconcile(self):
        wanted = self.preference.wanted()
        if wanted == self.applied and (not self.error or time.monotonic() < self.retry_at):
            return
        try:
            configure(wanted)
        except (OSError, RuntimeError) as exc:
            message = str(exc)
            if message != self.error:
                logging.warning("Desktop wrapper setup: %s", message)
            self.error = message
            self.retry_at = time.monotonic() + 60
        else:
            self.error = ""
        self.applied = wanted


def installed_path():
    return Path(os.environ["LOCALAPPDATA"]) / "CodexMeter" / "desktop-wrapper" / FILENAME


def configured_cli():
    if sys.platform != "win32":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return winreg.QueryValueEx(key, VARIABLE)[0]
    except FileNotFoundError:
        return ""


def enabled():
    value = configured_cli()
    return bool(value and Path(value) == installed_path())


def bundled_binary():
    resource = Path(__file__).with_name("desktop-wrapper.gz")
    if resource.is_file():
        with gzip.open(resource, "rb") as stream:
            return stream.read()
    if "__compiled__" in globals():
        raise RuntimeError("The packaged Desktop wrapper is missing. Replace this CodexMeter executable.")
    default = Path(sys.prefix).parent if Path(sys.prefix).name == "venv" else Path(r"D:\build\CodexMeter")
    build = Path(os.environ.get("CODEXMETER_BUILD_ROOT", default))
    try:
        return (build / "desktop-wrapper" / FILENAME).read_bytes()
    except FileNotFoundError:
        raise RuntimeError("Build the helper with scripts/build-desktop-wrapper.ps1 first.") from None


def configure(turn_on):
    import winreg
    target = installed_path()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
        current = configured_cli()
        inherited = os.environ.get(VARIABLE)
        if turn_on and not current and inherited and Path(inherited) != target:
            raise RuntimeError("This process inherits a different CODEX_CLI_PATH. Its setting was preserved.")
        if not turn_on and (not current or Path(current) != target):
            return
        if current and Path(current) != target:
            raise RuntimeError("Another application already sets CODEX_CLI_PATH. Its setting was preserved.")
        if turn_on:
            data = bundled_binary()
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file() or target.read_bytes() != data:
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as f:
                    tmp = Path(f.name)
                    try:
                        f.write(data)
                    except BaseException:
                        f.close()
                        tmp.unlink(missing_ok=True)
                        raise
                try:
                    os.replace(tmp, target)
                except PermissionError:
                    raise RuntimeError("Close Codex Desktop before replacing the active wrapper.") from None
                finally:
                    tmp.unlink(missing_ok=True)
            if current and Path(current) == target:
                return
            winreg.SetValueEx(key, VARIABLE, 0, winreg.REG_SZ, str(target))
        elif current:
            winreg.DeleteValue(key, VARIABLE)
    # Explorer refreshes the environment for future launches from Start.
    ctypes.windll.user32.SendMessageTimeoutW(0xffff, 0x1a, 0, "Environment", 2, 1000, None)


def sidebar_roots(home):
    data = json.loads((home / ".codex-global-state.json").read_text(encoding="utf-8"))
    keys = {"thread-project-assignments": dict, "projectless-thread-ids": list, "pinned-thread-ids": list}
    if not isinstance(data, dict) or not keys.keys() & data.keys():
        raise ContractError(field="inventory")
    visible = set()
    for key, kind in keys.items():
        items = data.get(key, kind())
        if not isinstance(items, kind) or not all(isinstance(i, str) for i in items):
            raise ContractError(field="inventory")
        visible.update(items)
    return read_roots(home, sidebar_ids=visible)


def read_snapshot(home, roots):
    exe = installed_path()
    if not exe.is_file():
        return "wrapper_missing", {}
    proc = subprocess.run([str(exe), "--meter-snapshot"], input=json.dumps(sorted(roots)),
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                          encoding="utf-8", timeout=13, creationflags=subprocess.CREATE_NO_WINDOW,
                          env={**os.environ, "CODEX_HOME": str(home)})
    if proc.returncode:
        raise ConnectionError()
    return validate_snapshot(json.loads(proc.stdout), roots)


def validate_snapshot(data, roots):
    if isinstance(data, dict):
        health = data.get("health")
        if health in ("inactive", "listener_failed", "connection"):
            return {"inactive": "wrapper_inactive", "listener_failed": "wrapper_listener",
                    "connection": "connection"}[health], {}
        states = data.get("states")
        if (health == "ok" and isinstance(states, dict)
                and all(k in roots and v in ("running", "waiting") for k, v in states.items())):
            return "ok", states
    raise ContractError("wrapper_protocol", "runtime_status", definitive=True)
