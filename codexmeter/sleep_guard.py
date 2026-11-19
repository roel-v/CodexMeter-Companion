"""Keep Windows awake while the local Codex observer reports running work."""
from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import logging


SYSTEM_REQUIRED = 1
STALE_ACTIVITY_SECONDS = 300


class DetailedReason(ctypes.Structure):
    _fields_ = [("module", wintypes.HMODULE), ("id", wintypes.ULONG),
                ("count", wintypes.ULONG), ("strings", ctypes.POINTER(wintypes.LPWSTR))]


class Reason(ctypes.Union):
    _fields_ = [("text", wintypes.LPWSTR), ("detail", DetailedReason)]


class ReasonContext(ctypes.Structure):
    _fields_ = [("version", wintypes.ULONG), ("flags", wintypes.DWORD), ("reason", Reason)]


class CodexSleepGuard:
    def __init__(self):
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
        required = bool(running)
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
            if running and guard.handle is not None:
                expiry = loop.call_later(stale_after, guard.update, 0)
        await broadcast(payload)

    try:
        await chats.run(publish, stop_event)
    finally:
        if expiry is not None:
            expiry.cancel()
        guard.update(0)
