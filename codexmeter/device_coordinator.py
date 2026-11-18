"""One active transport worker per logical display; all retry decisions live here."""
from __future__ import annotations
import asyncio
import contextlib
import logging
import time
from .transport_types import ConnectionWorker

log = logging.getLogger(__name__)
from .device_policy import is_busy


class DeviceCoordinator:
    def __init__(self, slot, usb_discovery, ble_worker, usb_factory, *,
                 usb_enabled=True, clock=time.monotonic, wait=None):
        self.slot, self.usb, self.ble = slot, usb_discovery, ble_worker
        self.usb_factory = usb_factory
        self.usb_enabled = usb_enabled
        self.clock = clock
        self.wait = wait or asyncio.sleep
        self.task = None
        self.worker: ConnectionWorker | None = None
        self.kind = None
        self.retry_at = {'usb': 0., 'bluetooth': 0.}
        self.failures = {'usb': 0, 'bluetooth': 0}
        self.lock = asyncio.Lock()
        self.changed_at = clock()

    def transition(self, state, reason=None):
        old = self.slot.state.connection_state
        if old != state or self.slot.state.fallback_reason != reason:
            log.info('Display %s transport %s -> %s reason=%s elapsed_ms=%d',
                     self.slot.config.device_id, old, state, reason or 'selection',
                     (self.clock() - self.changed_at) * 1000)
            self.changed_at = self.clock()
        self.slot.state.connection_state = state
        self.slot.state.fallback_reason = reason

    async def fence(self):
        task, self.task = self.task, None
        if task:
            self.transition('switching')
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.slot.state.connected = False
        self.slot.state.generation = None
        self.worker: ConnectionWorker | None = None
        self.kind = None

    async def maintenance_lease(self):
        """Called under coordinator.lock; no worker cleanup needs that lock."""
        if self.kind != "usb":
            return None
        session = self.worker.session if self.worker else None
        lease = await session.try_maintenance() if session else None
        # Ready claims and definitely-unsent stale sessions both relinquish the old handle.
        await self.fence()
        return lease

    def permitted(self, kind):
        config = self.slot.config
        return config.enabled and not config.maintenance and config.connection_mode != (
            'bluetooth_only' if kind == 'usb' else 'usb_only')

    async def step(self, stop):
        async with self.lock:
            state = self.slot.state
            if self.slot.config.maintenance:
                await self.fence()
                self.transition('maintenance', 'Paused; Resume explicitly after the tool closes')
                return
            if not self.slot.config.enabled:
                await self.fence()
                self.transition('disconnected', 'Disabled')
                return
            if self.task and not self.permitted(self.kind):
                await self.fence()
            if self.task and self.task.done():
                kind = self.kind
                error = state.last_error or 'Connection ended'
                with contextlib.suppress(BaseException):
                    self.task.result()
                self.task = None
                self.worker: ConnectionWorker | None = None
                self.kind = None
                busy = is_busy(error)
                self.failures[kind] += 1
                self.retry_at[kind] = self.clock() + (2 if busy else min(
                    16 if kind == 'usb' else 8, 2 ** min(self.failures[kind]-1, 4)))
                self.transition('owned_elsewhere' if busy else 'disconnected', error)
            stable = self.usb.stable(self.slot.config) if self.usb_enabled else None
            if self.task and self.kind == 'bluetooth' and stable and self.permitted('usb') and self.clock() >= self.retry_at['usb']:
                self.transition('switching', 'Stable USB preferred')
                await self.fence()
            if self.task:
                if state.connected:
                    self.failures[self.kind] = 0
                    self.transition('usb_active' if self.kind == 'usb' else 'ble_active')
                return
            kind = None
            if stable and self.permitted('usb') and self.clock() >= self.retry_at['usb']:
                kind = 'usb'
            elif self.permitted('bluetooth') and self.clock() >= self.retry_at['bluetooth'] and self.ble.discovery.find(self.slot.config):
                kind = 'bluetooth'
            if kind is None:
                if state.connection_state != 'owned_elsewhere':
                    self.transition('probing', state.last_error or 'Waiting for a permitted transport')
                return
            self.kind = kind
            self.worker = self.usb_factory() if kind == 'usb' else self.ble
            self.transition('switching', 'Selecting ' + kind)
            self.task = asyncio.create_task(self.worker.run(stop))

    async def run(self, stop):
        try:
            while not stop.is_set():
                await self.step(stop)
                await self.wait(.1)
        finally:
            async with self.lock:
                await self.fence()
