"""Multi-device BLE coordination for CodexMeter displays."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable

from .device_identity import DeviceIdentity, DeviceIdentityError
from .ble import BleAckError, BleAckTimeout, BleConnectTimeout, BleNotifyError, BleState, BleTransport, BleWriteTimeout, MacConnectedDeviceLookup
from .device_registry import (
    DeviceConfig,
    default_legacy_device,
    is_full_device_id,
    normalize_device_id,
    normalize_short_id,
    parse_short_id_from_name,
)
from .payloads import Payload
from .queueing import put_latest
from .settings import DEVICE_NAME, SERVICE_UUID
from .supervision import supervise

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

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.raw_result_count = None
                self._last_error = str(exc)
                log.warning("BLE discovery failed: %s", exc)
            if self.after_scan is not None:
                try:
                    await self.after_scan(self.raw_result_count)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("Bluetooth recovery monitor failed")
            await _sleep_or_stop(stop_event, self.scan_interval_sec)

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


@dataclass
class DeviceSlot:
    config: DeviceConfig
    queue: "asyncio.Queue[Payload]" = field(
        default_factory=lambda: asyncio.Queue(maxsize=32)
    )
    state: BleState = field(default_factory=BleState)

    def status(self, now: float | None = None) -> dict[str, object]:
        data = self.state.status(queue_depth=self.queue.qsize(), now=now)
        data.update(
            {
                "device_id": self.config.device_id,
                "short_id": self.config.short_id,
                "alias": self.config.alias,
                "label": self.config.label,
                "enabled": self.config.enabled,
                "connection_mode": self.config.connection_mode,
                "maintenance": bool(self.config.maintenance),
                "maintenance_recovery": "Resume after verifying the tool has closed" if self.config.maintenance else None,
            }
        )
        data.update(self.config.metadata.to_json())
        data["compatibility"] = self.config.metadata.compatibility
        return data


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
        self.single_attempt = False

    async def run(self, stop_event: asyncio.Event) -> None:
        backoff = 1.0
        label = self.slot.config.label
        while not stop_event.is_set():
            try:
                discovered = await self.discovery.wait_for(self.slot.config, stop_event)
                if discovered is None:
                    break
                log.info(
                    "Connecting CodexMeter %s at %s via %s",
                    label,
                    discovered.address,
                    discovered.source,
                )
                self.slot.state.last_discovered_at = discovered.seen_at
                self.slot.state.last_discovery_source = discovered.source
                self.slot.state.last_discovered_address = discovered.address
                used = await self.transport.connect_and_write(
                    discovered.device,
                    self.slot.queue,
                    self.slot.state,
                    stop_event,
                    require_identity=not self.slot.config.legacy,
                    identity_validator=self._validate_identity,
                )
                if self.single_attempt:
                    if not stop_event.is_set():
                        self._record_failure("BLE disconnected; waiting for rediscovery")
                    return
                backoff = 1.0 if used else min(backoff * 2, 60.0)
                if not stop_event.is_set():
                    self._record_failure("BLE disconnected; waiting for rediscovery")
                    await _sleep_or_stop(stop_event, _with_jitter(backoff))
            except asyncio.CancelledError:
                raise
            except (
                BleConnectTimeout,
                BleWriteTimeout,
                BleAckTimeout,
                BleAckError,
                BleNotifyError,
                DeviceIdentityError,
            ) as exc:
                self._record_failure(str(exc))
                if self.single_attempt:
                    return
                await _sleep_or_stop(stop_event, _with_jitter(backoff))
                backoff = min(backoff * 2, 60.0)
            except Exception as exc:
                self._record_failure(str(exc) or "BLE worker error")
                log.exception("BLE worker error for %s: %s", label, exc)
                if self.single_attempt:
                    return
                await _sleep_or_stop(stop_event, _with_jitter(backoff))
                backoff = min(backoff * 2, 60.0)

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


class DeviceManager:
    def __init__(
        self,
        configs: list[DeviceConfig],
        *,
        scan_timeout_sec: float = 4.0,
        scan_interval_sec: float = 8.0,
        connect_timeout_sec: float,
        disconnect_timeout_sec: float,
        write_timeout_sec: float,
        ack_timeout_sec: float,
        notify_timeout_sec: float,
        healthcheck_interval_sec: float,
        fallback_device_name: str = DEVICE_NAME,
        fallback_when_empty: bool = True,
        identity_observer: IdentityObserver | None = None,
        usb_discovery=None,
        host_id: str | None = None,
        registry=None,
        policy_detector=None,
        screen_timeout_sec=60,
        clock=time.monotonic,
        retry_wait=None,
    ) -> None:
        import sys
        from .usb_transport import UsbDiscovery
        self.usb_discovery = usb_discovery or UsbDiscovery()
        self._usb_enabled = sys.platform == "win32" or usb_discovery is not None
        self.registry = registry
        self.policy_detector = policy_detector
        from .screen_policy import LockScreenPolicy
        self._live_policy = LockScreenPolicy(timeout_sec=screen_timeout_sec)
        self._clock = clock
        self._retry_wait = retry_wait
        self._host_id = host_id
        self._identity_observer = identity_observer
        active_configs = list(configs)
        if not active_configs and fallback_when_empty and not self._usb_enabled:
            active_configs = [default_legacy_device(fallback_device_name)]
        self.slots = [DeviceSlot(config) for config in active_configs]
        self.discovery = DiscoveryService(
            scan_timeout_sec=scan_timeout_sec,
            scan_interval_sec=scan_interval_sec,
        )
        self._transport_options = dict(scan_timeout_sec=scan_timeout_sec,
            connect_timeout_sec=min(5, connect_timeout_sec), disconnect_timeout_sec=min(.5, disconnect_timeout_sec),
            write_timeout_sec=write_timeout_sec, ack_timeout_sec=ack_timeout_sec,
            notify_timeout_sec=notify_timeout_sec, healthcheck_interval_sec=healthcheck_interval_sec)
        self._workers = [
            DeviceWorker(
                slot,
                self.discovery,
                BleTransport(
                    device_name=slot.config.name or DEVICE_NAME,
                    scan_timeout_sec=scan_timeout_sec,
                    connect_timeout_sec=min(5, connect_timeout_sec),
                    disconnect_timeout_sec=min(.5, disconnect_timeout_sec),
                    write_timeout_sec=write_timeout_sec,
                    ack_timeout_sec=ack_timeout_sec,
                    notify_timeout_sec=notify_timeout_sec,
                    healthcheck_interval_sec=healthcheck_interval_sec,
                ),
                identity_observer,
            )
            for slot in self.slots
        ]

    def _coordinators_init(self):
        if not hasattr(self, 'coordinators'):
            self.coordinators = []
        from .device_coordinator import DeviceCoordinator
        from .usb_worker import UsbDeviceWorker
        from .host_identity import load_host_id
        for worker in self._workers:
            if any(c.slot is worker.slot for c in self.coordinators):
                continue
            worker.transport.on_reconciled = self._reconciled
            def usb_factory(slot=worker.slot):
                usb = UsbDeviceWorker(slot, self.usb_discovery, self._host_id or load_host_id(),
                                      identity_observer=self._identity_observer)
                usb.on_reconciled = self._reconciled
                return usb
            self.coordinators.append(DeviceCoordinator(worker.slot, self.usb_discovery,
                worker, usb_factory, usb_enabled=self._usb_enabled,
                clock=self._clock, wait=self._retry_wait))
            if worker.slot.config.maintenance:
                self.usb_discovery.paused_ids.add(worker.slot.config.device_id)
                instance = worker.slot.config.maintenance.get("instance_id")
                if instance:
                    self.usb_discovery.paused_instances.add(instance)
                port = worker.slot.config.maintenance.get('port')
                if port:
                    self.usb_discovery.paused_ports.add(port)

    async def _reconciled(self, state, session):
        from .screen_policy import MacLockDetector, WindowsLockDetector
        from .payloads import build_screen_control_payload
        import sys
        detector = self.policy_detector or (WindowsLockDetector() if sys.platform == 'win32' else MacLockDetector())
        locked = await detector.is_locked()
        if locked is None:
            return
        # Read the OS now, after learning firmware manual intent. Policy never changes manual intent.
        self.observe_lock(locked, time.monotonic())
        policy_on = not (locked and self._live_policy.lock_off_sent)
        payload = build_screen_control_payload(policy_on, reason='unlock' if policy_on else 'lock')
        result = await session.send(payload)
        if result.outcome != 'accepted':
            raise RuntimeError(result.reason or 'Live policy was not acknowledged')
        state.last_ack_at = time.monotonic()

    def observe_lock(self, locked, now):
        self._live_policy.observe(locked, now=now)

    async def _initial_worker(self, worker, stop_event):
        self._coordinators_init()
        coordinator = next(c for c in self.coordinators if c.slot is worker.slot)
        await coordinator.run(stop_event)

    async def _ble_discovery(self, stop_event):
        from .usb_transport import bluetooth_availability
        while not stop_event.is_set():
            eligible = any(s.config.enabled and not s.config.maintenance and
                s.config.connection_mode != 'usb_only' and not (s.state.connected and s.state.transport == 'usb')
                for s in self.slots)
            if eligible:
                available, reason = await bluetooth_availability()
                self.ble_available, self.ble_unavailable_reason = available, reason
                if not available:
                    self.discovery._devices.clear()
                    self._coordinators_init()
                    for coordinator in self.coordinators:
                        async with coordinator.lock:
                            if coordinator.kind == 'bluetooth':
                                await coordinator.fence()
                if available:
                    try:
                        await self.discovery.scan_once()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self.discovery._last_error = str(exc)
                        self.discovery.raw_result_count = None
                    if self.discovery.after_scan:
                        await self.discovery.after_scan(self.discovery.raw_result_count)
            await _sleep_or_stop(stop_event, min(5, self.discovery.scan_interval_sec))

    async def run(self, stop_event: asyncio.Event) -> None:
        self._coordinators_init()
        services = {'ble_discovery': self._ble_discovery(stop_event)}
        if self._usb_enabled:
            services['usb_discovery'] = self.usb_discovery.run(stop_event)
        services['device_coordinators'] = self._run_coordinators(stop_event)
        await supervise(stop_event, services)

    async def _run_coordinators(self, stop):
        tasks = {}
        try:
            while not stop.is_set():
                self._coordinators_init()
                for coordinator in self.coordinators:
                    if coordinator not in tasks:
                        tasks[coordinator] = asyncio.create_task(coordinator.run(stop))
                    elif tasks[coordinator].done():
                        tasks[coordinator].result()
                await _sleep_or_stop(stop, .1)
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)

    async def reload_devices(self):
        from .device_registry import DeviceRegistry
        if self.registry is None:
            raise ValueError('Registry unavailable')
        loaded = DeviceRegistry.load(self.registry.path)
        self._coordinators_init()
        current = {c.slot.config.device_id:c for c in self.coordinators}
        for config in loaded.devices:
            coordinator = current.get(config.device_id)
            if coordinator:
                async with coordinator.lock:
                    # An external registry edit never clears a live maintenance pause.
                    if coordinator.slot.config.maintenance:
                        config = replace(config, maintenance=coordinator.slot.config.maintenance)
                    coordinator.slot.config = config
                    if coordinator.kind and not coordinator.permitted(coordinator.kind):
                        await coordinator.fence()
            else:
                slot = DeviceSlot(config)
                self.slots.append(slot)
                self._workers.append(DeviceWorker(slot, self.discovery,
                    BleTransport(device_name=config.name or DEVICE_NAME, **self._transport_options),
                    self._identity_observer))
        for device_id, coordinator in current.items():
            if not any(config.device_id == device_id for config in loaded.devices):
                async with coordinator.lock:
                    coordinator.slot.config = replace(coordinator.slot.config, enabled=False)
                    await coordinator.fence()
        self.registry.devices = [s.config for s in self.slots]
        self._coordinators_init()
        return {'ok':True, 'configured_count':sum(s.config.enabled for s in self.slots)}

    async def update_registry(self, event):
        if self.registry is None:
            raise ValueError('Registry unavailable')
        action = event.get('action')
        device_id = event.get('device_id')
        self._coordinators_init()
        coordinator = next((c for c in self.coordinators if c.slot.config.device_id == device_id), None)
        if action == 'adopt':
            config = DeviceConfig.from_json(event.get('config', {}))
            if config.device_id != device_id:
                raise ValueError('Registry device ID mismatch')
            if coordinator:
                async with coordinator.lock:
                    old = coordinator.slot.config
                    updated = replace(old, connection_mode=config.connection_mode,
                        alias=config.alias or old.alias, metadata=config.metadata)
                    self._persist_config(coordinator.slot, updated)
                    if coordinator.kind and not coordinator.permitted(coordinator.kind):
                        await coordinator.fence()
                return {'ok':True, **updated.to_json()}
            previous = list(self.registry.devices)
            self.registry.upsert(config)
            try:
                self.registry.save()
            except BaseException:
                self.registry.devices = previous
                raise
            slot = DeviceSlot(config)
            self.slots.append(slot)
            self._workers.append(DeviceWorker(slot, self.discovery,
                BleTransport(device_name=config.name or DEVICE_NAME, **self._transport_options),
                self._identity_observer))
            self._coordinators_init()
            return {'ok':True, **config.to_json()}
        if coordinator is None:
            raise ValueError('Unknown registered display')
        async with coordinator.lock:
            if action == 'rename' and (event.get('alias') is None or isinstance(event.get('alias'), str)):
                updated = replace(coordinator.slot.config, alias=event.get('alias'))
            elif action == 'enabled' and type(event.get('enabled')) is bool:
                updated = replace(coordinator.slot.config, enabled=event['enabled'])
            else:
                raise ValueError('Invalid registry operation')
            self._persist_config(coordinator.slot, updated)
            if coordinator.kind and not coordinator.permitted(coordinator.kind):
                await coordinator.fence()
            return {'ok':True, **updated.to_json()}

    def bluetooth_status(self):
        status = self.status()
        devices = [d for d in status['devices'] if d.get('enabled') and
            d.get('connection_state') not in ('owned_elsewhere', 'maintenance') and
            not any(busy in (d.get('last_error') or '') for busy in ('busy_usb', 'busy_ble', 'busy_maintenance')) and
            d.get('connection_mode') != 'usb_only' and
            (d.get('ble_failures', 0) > 0 or (d.get('connected') and d.get('transport') == 'bluetooth')) and
            not (d.get('connected') and d.get('transport') == 'usb') and
            getattr(self, 'ble_available', True)]
        return {**status, 'devices': devices, 'configured_count': len(devices),
                'connected': any(d['connected'] for d in devices),
                'connected_count': sum(bool(d['connected']) for d in devices)}

    async def broadcast(self, payload: Payload) -> None:
        for slot in self.slots:
            BleTransport.remember_desired(payload, slot.state)
            await put_latest(slot.queue, payload)

    def _persist_config(self, slot, updated):
        if self.registry is not None:
            previous = list(self.registry.devices)
            self.registry.upsert(updated)
            try:
                self.registry.save()
            except BaseException:
                self.registry.devices = previous
                raise
        slot.config = updated

    async def device_operation(self, event):
        import secrets
        from .device_registry import CONNECTION_MODES
        from .host_identity import load_host_id
        from .usb_transport import maintenance_connection
        if event.get('type') == 'device_registry_update':
            return await self.update_registry(event)
        if event.get('type') == 'devices_reload':
            return await self.reload_devices()
        device_id = event.get('device_id')
        if not is_full_device_id(device_id) or device_id != normalize_device_id(device_id):
            raise ValueError('Use the full lowercase registered device ID')
        self._coordinators_init()
        coordinator = next((c for c in self.coordinators if c.slot.config.device_id == device_id), None)
        if coordinator is None:
            raise ValueError('Unknown registered display')
        slot = coordinator.slot
        operation = event.get('type')
        async with coordinator.lock:
            if operation == 'device_mode':
                mode = event.get('connection_mode')
                if mode not in CONNECTION_MODES:
                    raise ValueError('Invalid connection mode')
                self._persist_config(slot, replace(slot.config, connection_mode=mode))
                if coordinator.kind and not coordinator.permitted(coordinator.kind):
                    await coordinator.fence()
                return {'ok': True, 'connection_mode': mode, 'device_id': device_id}
            if operation == 'maintenance_acquire':
                if slot.config.maintenance:
                    raise ValueError('Already paused; close the previous tool and Resume first')
                found = self.usb_discovery.find(slot.config)
                port = found.candidate.port if found else event.get('port') or (slot.state.last_discovered_address if slot.state.last_discovery_source == 'usb' else None)
                if not port and event.get('tool'):
                    raise ValueError('Verified USB endpoint required for exclusive tool maintenance')
                record = {'token': secrets.token_hex(16), 'port': port,
                          'kind': 'tool' if event.get('tool') else 'manual', 'ready': False,
                          'instance_id': found.candidate.instance_id if found else next((instance for candidate_port,instance in self.usb_discovery._last_candidates if candidate_port == port), None)}
                # Durable pause precedes quiescence or relinquishing any handle.
                self._persist_config(slot, replace(slot.config, maintenance=record))
                await self.usb_discovery.pause(port, device_id, record.get("instance_id"))
                if not port:
                    await coordinator.fence()
                    coordinator.transition('maintenance', 'Local pause; USB required for cross-PC quiescence')
                    return {'ok':True, 'device_id':device_id, 'ready':False, 'local_pause':True}
                session = getattr(coordinator.worker, 'session', None)
                try:
                    if session and coordinator.kind == 'usb':
                        async with session._send_lock:
                            lease = await session.maintenance()
                            record.update(lease)
                            await coordinator.fence()
                    else:
                        await coordinator.fence()
                        from .usb_transport import inspect_maintenance_identity
                        raw, legacy = await inspect_maintenance_identity(port)
                        if raw['device_id'] != device_id:
                            raise ValueError('Maintenance device identity mismatch')
                        if legacy:
                            record.update(ready=True, quiescence='unsupported_legacy')
                            self._persist_config(slot, replace(slot.config, maintenance=record))
                            coordinator.transition('maintenance', 'Local pause; legacy firmware cannot quiesce other PCs')
                            return {'ok':True, 'device_id':device_id, **record}
                        session = await maintenance_connection(port, self._host_id or load_host_id(),
                            record['token'], device_id)
                        record.update(boot=session.identity.boot, token=session.token)
                        await session.close(release=False)
                    record['ready'] = True
                    record['quiescence'] = 'device_maintenance'
                    self._persist_config(slot, replace(slot.config, maintenance=record))
                    coordinator.transition('maintenance', 'Paused for maintenance')
                    return {'ok': True, 'device_id': device_id, **record}
                except Exception:
                    await coordinator.fence()
                    coordinator.transition('maintenance', 'Quiescence failed; pause retained. Close tool then Resume')
                    raise
            if operation in ('maintenance_release', 'maintenance_resume'):
                record = slot.config.maintenance
                if not record:
                    return {'ok': True, 'device_id': device_id}
                if operation == 'maintenance_release' and event.get('token') != record.get('token'):
                    raise ValueError('Maintenance token mismatch')
                # Exclusive open proves no active tool owns the port. Failure retains the pause.
                if record.get('port'):
                    from .usb_transport import UsbDiscovery, inspect_maintenance_identity
                    rediscovery = UsbDiscovery()
                    await rediscovery.scan_once()
                    found = rediscovery.find(slot.config)
                    matches = [d.candidate.port for d in rediscovery.devices.values()
                               if d.identity.device_id == device_id]
                    matches += [d['port'] for d in rediscovery.unsupported.values()
                                if d['device_id'] == device_id]
                    if len(matches) != 1:
                        raise ValueError('Display USB unavailable, ambiguous or busy; pause retained. Close tool and reconnect USB before Resume')
                    port = matches[0]
                    raw, legacy = await inspect_maintenance_identity(port)
                    if raw['device_id'] != device_id:
                        raise ValueError('Maintenance device identity mismatch; pause retained')
                    if not legacy:
                        session = await maintenance_connection(port, self._host_id or load_host_id(),
                            record['token'], device_id)
                        try:
                            await session.end_maintenance()
                        finally:
                            await session.close(release=False)
                self._persist_config(slot, replace(slot.config, maintenance=None))
                self.usb_discovery.paused_ids.discard(device_id)
                self.usb_discovery.paused_ports.discard(record.get('port'))
                self.usb_discovery.paused_instances.discard(record.get('instance_id'))
                self.usb_discovery.devices.pop(record['port'], None)
                self.usb_discovery.stability.pop(record['port'], None)
                coordinator.transition('disconnected', 'Maintenance completed')
                return {'ok': True, 'device_id': device_id}
            raise ValueError('Unknown device operation')

    async def control_device(self, event: dict) -> dict:
        device_id = event.get("device_id")
        slot = next((s for s in self.slots if s.config.device_id == device_id), None)
        if slot is None or not slot.config.enabled or slot.config.maintenance:
            raise ValueError("Select an enabled display outside maintenance")
        if not slot.config.metadata.compatible:
            raise ValueError("Display protocol is incompatible")
        command = event.get("command")
        capability = {"screen": "screen", "brightness": "brightness", "rotation": "rotation"}.get(command)
        if capability is None:
            raise ValueError("Unknown display control")
        supported = slot.config.metadata.supports(capability)
        if supported is False or (supported is None and command != "screen"):
            raise ValueError("Display does not advertise this control")
        value = event.get("value")
        if command == "screen":
            if type(value) is not bool:
                raise ValueError("Screen value must be boolean")
            data = {"k": "control", "cmd": "screen", "on": value, "why": "manual"}
        else:
            if type(value) is not int or (command == "brightness" and not 10 <= value <= 100) or (command == "rotation" and value not in (0,90,180,270)):
                raise ValueError("Invalid display setting")
            data = {"k": "control", "cmd": command, "value": value}
        data["v"] = 1
        data["t"] = int(time.time())
        payload = Payload("control", data)
        for key,existing in list(slot.state.explicit_payloads.items()):
            if existing.data.get('cmd')==command:
                slot.state.explicit_payloads.pop(key,None);slot.state.explicit_intents.pop(key,None)
        if slot.state.device_state:
            observed=slot.state.device_state
            if not slot.state.connected or not observed:
                raise ValueError('Display must be connected before changing settings')
            slot.state.explicit_intents[id(payload)]=(str(slot.state.device_state.get('boot','')),
                observed['rev'],time.monotonic())
            # Boot is the verified discovery generation, never an invented address/name.
            found=self.usb_discovery.find(slot.config) if slot.state.transport=='usb' else None
            if found: slot.state.explicit_intents[id(payload)]=(found.identity.boot,observed['rev'],time.monotonic())
            slot.state.explicit_payloads[id(payload)]=payload
        BleTransport.remember_desired(payload, slot.state)
        await put_latest(slot.queue, payload)
        return {"ok": True, "queued": command, "device_id": device_id}

    def set_connect_control(self, payload: Payload | None) -> None:
        for slot in self.slots:
            slot.state.connect_control = payload

    def status(self) -> dict[str, object]:
        now = asyncio.get_running_loop().time()
        devices = [slot.status(now=now) for slot in self.slots]
        for device in devices:
            if device['connection_mode']=='bluetooth_only':continue
            unsupported=next((d for d in self.usb_discovery.unsupported.values()
                if d['device_id']==device['device_id']),None)
            if unsupported and not device['connected']:
                device['last_error']='USB firmware upgrade required: '+unsupported['reason']
                device['usb_compatibility']='incompatible'
                if device['connection_mode']=='usb_only':device['compatibility']='incompatible'
        connected_count = sum(1 for item in devices if item.get("connected") is True)
        return {
            "connected": connected_count > 0,
            "configured_count": sum(s.config.enabled for s in self.slots),
            "bluetooth_available": getattr(self, "ble_available", None),
            "bluetooth_unavailable_reason": getattr(self, "ble_unavailable_reason", None),
            "connected_count": connected_count,
            "devices": devices,
            "discovery": self.discovery.status(now),
            "usb_discovery": self.usb_discovery.status(now),
            "unknown_devices": self.usb_discovery.unknown_devices([slot.config for slot in self.slots]) + self.discovery.unknown_devices(
                [slot.config for slot in self.slots]
            ),
        }


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


async def _sleep_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def _wait_any(*awaitables: Any) -> None:
    tasks = [asyncio.create_task(awaitable) for awaitable in awaitables]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _with_jitter(seconds: float) -> float:
    return seconds * random.uniform(0.8, 1.2)
