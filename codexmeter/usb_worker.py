"""Bounded negotiated delivery and USB connection attempt."""

from __future__ import annotations
import asyncio
import time
from .usb_transport import UsbSession
from .session_runner import run_session


class UsbDeviceWorker:
    def __init__(
        self,
        slot,
        discovery,
        host_id,
        *,
        session_factory=UsbSession,
        identity_observer=None,
    ):
        self.slot = slot
        self.discovery = discovery
        self.host_id = host_id
        self.session_factory = session_factory
        self.identity_observer = identity_observer
        self.session = None
        self.on_reconciled = None

    async def run(self, stop):
        state = self.slot.state
        discovered = self.discovery.find(self.slot.config)
        if stop.is_set() or discovered is None:
            return
        port = discovered.candidate.port
        self.discovery.active_ports.add(port)
        try:
            self.session = self.session_factory(discovered, self.host_id)
            def observed():
                if self.identity_observer:
                    from .device_identity import DeviceIdentity
                    identity = discovered.identity
                    self.slot.config = self.identity_observer(
                        self.slot.config, DeviceIdentity(identity.device_id,
                            identity.short_id or "", identity.name or "", identity.metadata))
                state.last_discovered_at = discovered.seen_at
                state.last_discovery_source = "usb"
                state.last_discovered_address = port
            await run_session(self.session, state, self.slot.queue, stop,
                              transport="usb", on_open=observed,
                              on_reconciled=self.on_reconciled)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.last_error = str(exc) or type(exc).__name__
            state.consecutive_failures += 1
        finally:
            state.connected = False
            state.last_disconnected_at = time.monotonic()
            self.session = None
            self.discovery.active_ports.discard(port)
            # Require a fresh identity exchange before any reconnect claim.
            self.discovery.invalidate(port)
