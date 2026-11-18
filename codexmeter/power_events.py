"""Service-owned power notifications; no window, tray or sleep prevention required."""
from __future__ import annotations
import asyncio
import ctypes
import logging
import sys


class WindowsPowerEvents:
    """PowrProf callback registration, retained until explicit unregistration.

    https://learn.microsoft.com/windows/win32/api/powerbase/nf-powerbase-powerregistersuspendresumenotification
    """
    def __init__(self):
        self.handle = ctypes.c_void_p()
        self.callback = self.parameters = self.library = None

    def start(self, notify):
        if sys.platform != "win32":
            return False
        from ctypes import wintypes
        routine = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p,
                                     wintypes.ULONG, ctypes.c_void_p)
        class Parameters(ctypes.Structure):
            _fields_ = [("Callback", routine), ("Context", ctypes.c_void_p)]

        def receive(context, kind, setting):
            if kind in (4, 7, 18):  # suspend, user resume, automatic resume
                notify(kind == 4)
            return 0

        self.callback = routine(receive)
        self.parameters = Parameters(self.callback, None)
        self.library = ctypes.WinDLL("PowrProf.dll")
        register = self.library.PowerRegisterSuspendResumeNotification
        register.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        register.restype = wintypes.DWORD
        unregister = self.library.PowerUnregisterSuspendResumeNotification
        unregister.argtypes = [ctypes.c_void_p]
        unregister.restype = wintypes.DWORD
        code = register(2, ctypes.byref(self.parameters), ctypes.byref(self.handle))
        if code:
            raise OSError(code, "Power notification registration failed")
        return True

    def close(self):
        if self.handle.value:
            code = self.library.PowerUnregisterSuspendResumeNotification(self.handle)
            if code:
                # Keep callback storage alive if Windows still owns the registration.
                raise OSError(code, "Power notification unregistration failed")
            self.handle = ctypes.c_void_p()


async def power_event_loop(monitor, stop_event, *, source=None):
    source = source or WindowsPowerEvents()
    loop = asyncio.get_running_loop()
    active = True
    last = None

    def apply(suspended):
        nonlocal last
        if active and suspended != last:
            last = suspended
            monitor.power(suspended)

    def notify(suspended):
        if active and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(apply, suspended)
            except RuntimeError:
                pass  # event-loop shutdown fences native callbacks

    try:
        try:
            monitor.power_events_available = bool(source.start(notify))
        except Exception:
            logging.warning("Power notifications unavailable; using elapsed-time fallback")
        await stop_event.wait()
    finally:
        active = False
        monitor.power_events_available = False
        try:
            source.close()
        except Exception:
            logging.warning("Power notification cleanup failed")
            # Keep native callback storage alive if unregistration failed.
            _retained_sources.append(source)


_retained_sources = []
