"""Bounded negotiated delivery and USB connection attempt."""

from __future__ import annotations
import asyncio
import contextlib
import time
from .delivery import (
    remember_accepted,
    should_send,
    negotiated_replay,
    accepted_alert,
    prune_alerts,
)
from .usb_transport import UsbSession, UsbError
from .payloads import Payload


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
        self.single_attempt = False

    async def _deliver(self, payload):
        state = self.slot.state
        if payload.kind in ("usage", "activity"):
            if (
                time.monotonic() - state.observed_at.get(payload.kind, float("-inf"))
                >= 300
            ):
                return
            if not should_send(payload, state):
                return
        if payload.kind == "alert":
            prune_alerts(state)
            if not any(
                p.data.get("id") == payload.data.get("id") for _, p in state.alerts
            ):
                return
        expected = state.explicit_intents.get(id(payload))
        data = payload.data
        if payload.kind == "control" and data.get("cmd") == "screen":
            why = data.get("why")
            if why == "ble_restored":
                return
            if why in ("mac_locked", "mac_unlocked"):
                payload = Payload(
                    payload.kind,
                    {**data, "why": "lock" if why == "mac_locked" else "unlock"},
                )
        state.last_write_at = time.monotonic()
        result = await self.session.send(
            payload,
            expected_boot=expected[0] if expected else None,
            expected_revision=expected[1] if expected else None,
        )
        if result.outcome == "unknown":
            raise UsbError(result.reason)
        if result.outcome == "rejected":
            state.explicit_intents.pop(id(payload), None)
            state.explicit_payloads.pop(id(payload), None)
            state.last_error = result.reason
            if result.reason == "conflict":
                state.device_state = {
                    **await self.session.read_state(),
                    "boot": self.session.identity.boot,
                }
            return
        state.explicit_intents.pop(id(payload), None)
        state.explicit_payloads.pop(id(payload), None)
        remember_accepted(payload, state)
        if payload.kind == "alert":
            accepted_alert(payload, state)
        state.last_ack_at = time.monotonic()
        state.consecutive_failures = 0
        state.last_error = None
        if payload.kind == "control":
            state.device_state = {
                **await self.session.read_state(),
                "boot": self.session.identity.boot,
            }

    async def run(self, stop):
        backoff = 1
        state = self.slot.state
        while not stop.is_set():
            discovered = self.discovery.find(self.slot.config)
            if discovered is None:
                try:
                    await asyncio.wait_for(stop.wait(), 0.2)
                except TimeoutError:
                    pass
                continue
            port = discovered.candidate.port
            self.discovery.active_ports.add(port)
            try:
                self.session = self.session_factory(discovered, self.host_id)
                await self.session.open()
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
                backoff = 1
                # Reconcile before evaluating policy or consuming any queued controls.
                while not self.slot.queue.empty():
                    self.slot.queue.get_nowait()
                replay = negotiated_replay(state, same_host=self.session.state["same_host"])
                # Fresh policy hook: recompute live OS policy after reconciliation, before replay.
                # No cached ble_restored or saved manual presets are replayed.
                if self.on_reconciled:
                    await self.on_reconciled(self.slot, self.session)
                for payload in replay:
                    await self._deliver(payload)
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
                            await self._deliver(payload_task.result())
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
                self.discovery.devices.pop(port, None)
            if self.single_attempt:
                return
            try:
                await asyncio.wait_for(stop.wait(), backoff)
            except TimeoutError:
                pass
            backoff = min(16, backoff * 2)
