"""Keep Windows awake while the local Codex observer reports running work."""
from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import logging

from .settings import APP_DIR


SYSTEM_REQUIRED = 1
STALE_ACTIVITY_SECONDS = 300


class SleepPreference:
    """The presence of the per-user opt-out file disables automatic sleep prevention."""

    def __init__(self, directory=APP_DIR):
        self.opt_out = directory / "prevent-sleep.disabled"

    def enabled(self):
        return not self.opt_out.exists()

    def save(self, enabled):
        if enabled:
            self.opt_out.unlink(missing_ok=True)
        else:
            self.opt_out.parent.mkdir(parents=True, exist_ok=True)
            self.opt_out.touch()


class DetailedReason(ctypes.Structure):
    _fields_ = [("module", wintypes.HMODULE), ("id", wintypes.ULONG),
                ("count", wintypes.ULONG), ("strings", ctypes.POINTER(wintypes.LPWSTR))]


class Reason(ctypes.Union):
    _fields_ = [("text", wintypes.LPWSTR), ("detail", DetailedReason)]


class ReasonContext(ctypes.Structure):
    _fields_ = [("version", wintypes.ULONG), ("flags", wintypes.DWORD), ("reason", Reason)]


class CodexSleepGuard:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.running = False
        self.handle = None
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.create = kernel.PowerCreateRequest
        self.create.argtypes = [ctypes.POINTER(ReasonContext)]
        self.create.restype = wintypes.HANDLE
        self.request = kernel.PowerSetRequest
        self.request.argtypes = [wintypes.HANDLE, ctypes.c_int]
        self.request.restype = wintypes.BOOL
        self.clear = kernel.PowerClearRequest
        self.clear.argtypes = self.request.argtypes
        self.clear.restype = wintypes.BOOL
        self.close = kernel.CloseHandle
        self.close.argtypes = [wintypes.HANDLE]
        self.close.restype = wintypes.BOOL

    def update(self, running, desktop_running=None):
        # Preserve protection across reconnects while the desktop is present.
        if running is None and desktop_running is not False:
            return
        self.running = bool(running)
        self._apply()

    def set_enabled(self, enabled):
        if self.enabled != enabled:
            self.enabled = enabled
            self._apply()

    def _apply(self):
        required = self.enabled and self.running
        if required == (self.handle is not None):
            return
        if required:
            context = ReasonContext(0, 1, Reason(text="CodexMeter: local Codex work is running"))
            handle = self.create(ctypes.byref(context))
            if handle == ctypes.c_void_p(-1).value:
                logging.error("PowerCreateRequest failed: %s", ctypes.get_last_error())
                return
            if not self.request(handle, SYSTEM_REQUIRED):
                logging.error("PowerSetRequest failed: %s", ctypes.get_last_error())
                self.close(handle)
                return
            self.handle = handle
        else:
            if not self.clear(self.handle, SYSTEM_REQUIRED):
                logging.warning("Clearing Codex sleep request failed: %s", ctypes.get_last_error())
            if self.close(self.handle):
                self.handle = None
            else:
                logging.error("Closing Codex sleep request failed: %s", ctypes.get_last_error())

async def observe_with_guard(chats, broadcast, stop_event, guard, *, stale_after=STALE_ACTIVITY_SECONDS):
    """Renew the Windows request only on positive evidence of a running turn."""
    loop = asyncio.get_running_loop()
    expiry = None

    async def publish(payload):
        nonlocal expiry
        running = payload.data["run"]
        if running is not None or chats.desktop_running is False:
            if expiry is not None:
                expiry.cancel()
                expiry = None
            guard.update(running, chats.desktop_running)
            if running:
                expiry = loop.call_later(stale_after, guard.update, 0)
        await broadcast(payload)

    try:
        await chats.run(publish, stop_event)
    finally:
        if expiry is not None:
            expiry.cancel()
        guard.update(0)
