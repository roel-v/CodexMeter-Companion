"""Bounded negotiated delivery and USB connection attempt."""

from __future__ import annotations
import asyncio
import contextlib
import time
from .delivery import negotiated_replay
from .usb_transport import UsbSession
from .delivery_pump import DeliveryPump


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
            await self.session.open()
            delivery = DeliveryPump(state, self.session)
            if self.identity_observer:
                from .device_identity import DeviceIdentity

                identity = discovered.identity
                self.slot.config = self.identity_observer(
                    self.slot.config,
                    DeviceIdentity(
                        identity.device_id,
                        identity.short_id or "",
                        identity.name or "",
                        identity.metadata,
                    ),
                )
            state.connected = True
            state.transport = "usb"
            state.generation = self.session.generation
            state.observed_device_id = discovered.identity.device_id
            state.last_connected_at = time.monotonic()
            state.last_error = None
            state.last_discovered_at = discovered.seen_at
            state.last_discovery_source = "usb"
            state.last_discovered_address = port
            state.device_state = {
                **self.session.state,
                "boot": self.session.identity.boot,
            }
            # Reconcile before evaluating policy or consuming any queued controls.
            while not self.slot.queue.empty():
                self.slot.queue.get_nowait()
            replay = negotiated_replay(state, same_host=self.session.state["same_host"])
            # Fresh policy hook: recompute live OS policy after reconciliation, before replay.
            # No cached ble_restored or saved manual presets are replayed.
            if self.on_reconciled:
                await self.on_reconciled(state, self.session)
            for payload in replay:
                await delivery.deliver(payload)
            while not stop.is_set() and not self.session.failure:
                payload_task = asyncio.create_task(self.slot.queue.get())
                stop_task = asyncio.create_task(stop.wait())
                try:
                    done, _ = await asyncio.wait(
                        {payload_task, stop_task},
                        timeout=0.1,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if stop_task in done:
                        break
                    if payload_task in done:
                        await delivery.deliver(payload_task.result())
                finally:
                    for task in (payload_task, stop_task):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(
                        payload_task, stop_task, return_exceptions=True
                    )
            if self.session.failure:
                raise self.session.failure
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.last_error = str(exc) or type(exc).__name__
            state.consecutive_failures += 1
        finally:
            state.connected = False
            state.last_disconnected_at = time.monotonic()
            if self.session:
                with contextlib.suppress(Exception):
                    await self.session.close()
            self.session = None
            self.discovery.active_ports.discard(port)
            # Require a fresh identity exchange before any reconnect claim.
            self.discovery.invalidate(port)
