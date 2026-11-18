"""Multi-device BLE coordination for CodexMeter displays."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Callable

from .device_identity import DeviceIdentity, DeviceIdentityError
from .ble import BleAckError, BleAckTimeout, BleConnectTimeout, BleNotifyError, BleTransport, BleWriteTimeout
from .device_registry import DeviceConfig, is_full_device_id, normalize_device_id, normalize_short_id

log = logging.getLogger(__name__)
IdentityObserver = Callable[[DeviceConfig, DeviceIdentity], DeviceConfig]


from .device_slot import DeviceSlot
from .ble_discovery import DiscoveryService


class DeviceWorker:
    def __init__(
        self,
        slot: DeviceSlot,
        discovery: DiscoveryService,
        transport: BleTransport,
        identity_observer: IdentityObserver | None = None,
    ) -> None:
        self.slot = slot
        self.discovery = discovery
        self.transport = transport
        self.identity_observer = identity_observer

    @property
    def session(self):
        return self.transport.session

    async def run(self, stop_event: asyncio.Event) -> None:
        try:
            discovered = self.discovery.find(self.slot.config)
            if discovered is None or stop_event.is_set():
                return
            log.info("Connecting CodexMeter %s at %s via %s", self.slot.config.label,
                     discovered.address, discovered.source)
            self.slot.state.last_discovered_at = discovered.seen_at
            self.slot.state.last_discovery_source = discovered.source
            self.slot.state.last_discovered_address = discovered.address
            await self.transport.connect_and_write(
                discovered.device, self.slot.queue, self.slot.state, stop_event,
                require_identity=not self.slot.config.legacy,
                identity_validator=self._validate_identity)
            if not stop_event.is_set():
                self._record_failure("BLE disconnected; waiting for rediscovery")
        except asyncio.CancelledError:
            raise
        except (BleConnectTimeout, BleWriteTimeout, BleAckTimeout, BleAckError,
                BleNotifyError, DeviceIdentityError) as exc:
            self._record_failure(str(exc))
        except Exception as exc:
            self._record_failure(str(exc) or "BLE worker error")
            log.exception("BLE worker error for %s", self.slot.config.label)

    def _record_failure(self, error: str) -> None:
        state = self.slot.state
        state.connected = False
        if not any(value in error for value in ("busy_usb", "busy_ble", "busy_maintenance")):
            state.consecutive_failures += 1
            state.ble_failures += 1
        state.last_error = error
        log.warning("CodexMeter %s: %s", self.slot.config.label, error)

    def _validate_identity(self, identity: DeviceIdentity) -> None:
        config = self.slot.config
        if config.short_id and normalize_short_id(identity.short_id) != config.short_id:
            raise DeviceIdentityError(
                f"BLE identity short id {identity.short_id} does not match {config.short_id}"
            )
        if is_full_device_id(config.device_id) and normalize_device_id(
            identity.device_id
        ) != normalize_device_id(config.device_id):
            raise DeviceIdentityError(
                f"BLE identity {identity.device_id} does not match {config.device_id}"
            )
        expected_name = config.name
        if expected_name and identity.name != expected_name:
            raise DeviceIdentityError(
                f"BLE identity name {identity.name} does not match {expected_name}"
            )
        if self.identity_observer is not None:
            self.slot.config = self.identity_observer(config, identity)
        else:
            self.slot.config = replace(config, metadata=identity.metadata)
        if not identity.metadata.compatible:
            raise DeviceIdentityError(f"Unsupported display protocol {identity.metadata.protocol}; update the companion")

