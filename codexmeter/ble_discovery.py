"""Multi-device BLE coordination for CodexMeter displays."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .device_identity import DeviceIdentity
from .ble import MacConnectedDeviceLookup
from .device_registry import DeviceConfig, parse_short_id_from_name
from .settings import DEVICE_NAME, SERVICE_UUID

log = logging.getLogger(__name__)
IdentityObserver = Callable[[DeviceConfig, DeviceIdentity], DeviceConfig]


@dataclass
class DiscoveredDevice:
    address: str
    name: str | None
    short_id: str | None
    device: Any
    source: str = "advertisement"
    seen_at: float = field(default_factory=time.monotonic)

    def status(self, now: float | None = None) -> dict[str, object]:
        now = time.monotonic() if now is None else now
        return {
            "address": self.address,
            "name": self.name,
            "short_id": self.short_id,
            "source": self.source,
            "last_seen_age_sec": round(max(0.0, now - self.seen_at), 1),
        }


class DiscoveryService:
    def __init__(
        self,
        *,
        scan_timeout_sec: float = 4.0,
        scan_interval_sec: float = 8.0,
        max_age_sec: float = 30.0,
        scanner: Callable[[float], Awaitable[list[DiscoveredDevice]]] | None = None,
    ) -> None:
        self.scan_timeout_sec = scan_timeout_sec
        self.scan_interval_sec = scan_interval_sec
        self.max_age_sec = max_age_sec
        self._connected_lookup: MacConnectedDeviceLookup | None = None
        self.raw_result_count: int | None = None
        self.after_scan = None
        if scanner is None:
            connected_lookup = MacConnectedDeviceLookup()
            self._connected_lookup = connected_lookup

            async def scan_with_connected(timeout: float) -> list[DiscoveredDevice]:
                return await scan_codexmeter_devices(
                    timeout, connected_lookup=connected_lookup,
                    raw_count_observer=lambda count: setattr(self, "raw_result_count", count),
                )

            self._scanner = scan_with_connected
        else:
            self._scanner = scanner
        self._devices: dict[str, DiscoveredDevice] = {}
        self._changed = asyncio.Event()
        self._last_scan_at: float | None = None
        self._last_result_count = 0
        self._last_connected_result_count = 0
        self._last_error: str | None = None

    def clear(self):
        self._devices.clear()

    def record_error(self, error):
        self.raw_result_count = None
        self._last_error = str(error)

    async def scan_once(self) -> list[DiscoveredDevice]:
        self._last_scan_at = time.monotonic()
        found = await self._scanner(self.scan_timeout_sec)
        now = time.monotonic()
        for device in found:
            device.seen_at = now
            self._devices[device.address] = device
        self._prune(now)
        self._last_result_count = len(found)
        self._last_connected_result_count = sum(
            device.source == "connected" for device in found
        )
        self._last_error = None
        self._changed.set()
        log.debug("Discovered %d CodexMeter BLE device(s)", len(found))
        return found

    def status(self, now: float | None = None) -> dict[str, object]:
        now = time.monotonic() if now is None else now
        self._prune(now)
        scan_age = None
        if self._last_scan_at is not None:
            scan_age = round(max(0.0, now - self._last_scan_at), 1)
        return {
            "last_scan_age_sec": scan_age,
            "last_result_count": self._last_result_count,
            "raw_result_count": self.raw_result_count,
            "connected_result_count": self._last_connected_result_count,
            "cached_count": len(self._devices),
            "last_error": self._last_error,
            "connected_lookup_error": (
                self._connected_lookup.last_error if self._connected_lookup else None
            ),
        }

    async def wait_for(
        self,
        config: DeviceConfig,
        stop_event: asyncio.Event,
    ) -> DiscoveredDevice | None:
        while not stop_event.is_set():
            match = self.find(config)
            if match is not None:
                return match
            self._changed.clear()
            try:
                await asyncio.wait_for(
                    _wait_any(self._changed.wait(), stop_event.wait()), timeout=10.0
                )
            except asyncio.TimeoutError:
                pass
        return None

    def find(self, config: DeviceConfig) -> DiscoveredDevice | None:
        now = time.monotonic()
        self._prune(now)
        for device in self._devices.values():
            if config.matches(
                short_id=device.short_id,
                name=device.name,
                address=device.address,
            ):
                return device
        return None

    def unknown_devices(self, configs: list[DeviceConfig]) -> list[dict[str, object]]:
        now = time.monotonic()
        self._prune(now)
        result: list[dict[str, object]] = []
        for device in self._devices.values():
            known = any(
                config.matches(
                    short_id=device.short_id,
                    name=device.name,
                    address=device.address,
                )
                for config in configs
            )
            if not known:
                result.append(device.status(now))
        return result

    def _prune(self, now: float) -> None:
        stale = [
            address
            for address, device in self._devices.items()
            if now - device.seen_at > self.max_age_sec
        ]
        for address in stale:
            del self._devices[address]


async def scan_codexmeter_devices(
    timeout: float = 4.0,
    *,
    discover: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    connected_lookup: Callable[[], Awaitable[list[Any]]] | None = None,
    raw_count_observer: Callable[[int], None] | None = None,
) -> list[DiscoveredDevice]:
    if discover is None:
        try:
            from bleak import BleakScanner
        except ImportError as exc:
            raise RuntimeError("bleak is required for BLE support") from exc
        discover = BleakScanner.discover
    if connected_lookup is None:
        connected_lookup = MacConnectedDeviceLookup()

    raw = await discover(timeout=timeout, return_adv=True)
    if raw_count_observer is not None:
        raw_count_observer(len(raw))
    result: dict[str, DiscoveredDevice] = {}
    for address, item in raw.items():
        device, adv = item
        name = getattr(adv, "local_name", None) or getattr(device, "name", None)
        service_uuids = {
            str(uuid).lower() for uuid in getattr(adv, "service_uuids", []) or []
        }
        is_codexmeter = str(SERVICE_UUID).lower() in service_uuids
        if name == DEVICE_NAME or (isinstance(name, str) and name.startswith(f"{DEVICE_NAME}-")):
            is_codexmeter = True
        if not is_codexmeter:
            continue
        normalized_address = str(address)
        result[normalized_address] = DiscoveredDevice(
            address=normalized_address,
            name=name,
            short_id=parse_short_id_from_name(name),
            device=device,
        )

    for device in await connected_lookup():
        address = str(getattr(device, "address", ""))
        name = getattr(device, "name", None)
        if not address or address in result:
            continue
        if not (
            name == DEVICE_NAME
            or (isinstance(name, str) and name.startswith(f"{DEVICE_NAME}-"))
        ):
            continue
        result[address] = DiscoveredDevice(
            address=address,
            name=name,
            short_id=parse_short_id_from_name(name),
            device=device,
            source="connected",
        )
    return list(result.values())



from .async_utils import sleep_or_stop as _sleep_or_stop, wait_any as _wait_any
