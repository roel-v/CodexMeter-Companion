"""Logical display management for CodexMeter displays."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from typing import Callable

from .device_identity import DeviceIdentity
from .ble import BleTransport
from .device_registry import DeviceConfig, default_legacy_device, is_full_device_id, normalize_device_id
from .payloads import Payload
from .delivery import remember_desired, discard_intents, sweep_commands
from .queueing import put_latest
from .settings import DEVICE_NAME, AUTO_SCREEN_TIMEOUT_SEC
from .supervision import supervise

log = logging.getLogger(__name__)
IdentityObserver = Callable[[DeviceConfig, DeviceIdentity], DeviceConfig]


from .device_slot import DeviceSlot
from .ble_worker import DeviceWorker
from .ble_discovery import DiscoveryService
from .async_utils import sleep_or_stop as _sleep_or_stop


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
        screen_timeout_sec=AUTO_SCREEN_TIMEOUT_SEC,
        policy=None,
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
        self.policy = policy or LockScreenPolicy(timeout_sec=screen_timeout_sec)
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
        self._transport_options = dict(
            connect_timeout_sec=min(5, connect_timeout_sec), disconnect_timeout_sec=min(.5, disconnect_timeout_sec),
            write_timeout_sec=write_timeout_sec, ack_timeout_sec=ack_timeout_sec,
            notify_timeout_sec=notify_timeout_sec, healthcheck_interval_sec=healthcheck_interval_sec)
        self._workers = [
            DeviceWorker(
                slot,
                self.discovery,
                BleTransport(
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
                record = worker.slot.config.maintenance
                self.usb_discovery.restore_pause(record.get('port'), worker.slot.config.device_id,
                                                 record.get('instance_id'))

    async def _reconciled(self, state, session):
        from .screen_policy import MacLockDetector, WindowsLockDetector
        from .payloads import build_screen_control_payload
        import sys
        detector = self.policy_detector or (WindowsLockDetector() if sys.platform == 'win32' else MacLockDetector())
        locked = await detector.is_locked()
        if locked is None:
            return
        # Read the OS now, after learning firmware manual intent. Policy never changes manual intent.
        result = self.observe_lock(locked, time.monotonic())
        self.set_connect_control(result.connect_control)
        for pending in result.payloads:
            await self.broadcast(pending)
        policy_on = not (locked and self.policy.lock_off_sent)
        payload = build_screen_control_payload(policy_on, reason='unlock' if policy_on else 'lock')
        result = await session.send(payload)
        if result.outcome != 'accepted':
            raise RuntimeError(result.reason or 'Live policy was not acknowledged')
        state.last_ack_at = time.monotonic()

    def observe_lock(self, locked, now):
        return self.policy.observe(locked, now=now)

    async def _ble_discovery(self, stop_event):
        from .ble_availability import bluetooth_availability
        while not stop_event.is_set():
            eligible = any(s.config.enabled and not s.config.maintenance and
                s.config.connection_mode != 'usb_only' and not (s.state.connected and s.state.transport == 'usb')
                for s in self.slots)
            if eligible:
                available, reason = await bluetooth_availability()
                self.ble_available, self.ble_unavailable_reason = available, reason
                if not available:
                    self.discovery.clear()
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
                        self.discovery.record_error(exc)
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
                    sweep_commands(coordinator.slot.state)
                    if not coordinator.slot.config.enabled:
                        coordinator.slot.state.commands.cancel_queued('Display disabled or removed')
                    if coordinator not in tasks:
                        tasks[coordinator] = asyncio.create_task(coordinator.run(stop))
                    elif tasks[coordinator].done():
                        tasks[coordinator].result()
                await _sleep_or_stop(stop, .1)
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            for slot in self.slots:
                slot.state.commands.cancel_queued('Companion stopped')
                sweep_commands(slot.state)

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
                    BleTransport(**self._transport_options),
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
                BleTransport(**self._transport_options),
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
            remember_desired(payload, slot.state)
            discard_intents(slot.state, await put_latest(slot.queue, payload))

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
        async with asyncio.timeout(12):
            return await self._device_operation(event)

    async def _device_operation(self, event):
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
            if operation == 'command_result':
                command_id = event.get('command_id')
                if not isinstance(command_id, str) or len(command_id) != 32 or any(
                        c not in '0123456789abcdef' for c in command_id):
                    raise ValueError('Invalid command ID')
                sweep_commands(slot.state)
                return {'ok': True, 'device_id': device_id, 'result': slot.state.commands.get(command_id)}
            if operation == 'device_state_refresh':
                session = coordinator.worker.session if coordinator.worker else None
                if slot.config.maintenance or not slot.state.connected or session is None:
                    raise ValueError('Connected negotiated display required to check settings')
                current = await session.read_state()
                if not slot.state.connected or session.failure:
                    raise ValueError('Display disconnected while checking settings')
                slot.state.device_state = {**current, 'boot': session.identity.boot}
                return {'ok': True, 'device_id': device_id, 'state': dict(slot.state.device_state)}
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
                          'instance_id': found.candidate.instance_id if found else self.usb_discovery.instance_for_port(port)}
                # Durable pause precedes quiescence or relinquishing any handle.
                self._persist_config(slot, replace(slot.config, maintenance=record))
                await self.usb_discovery.pause(port, device_id, record.get("instance_id"))
                if not port:
                    await coordinator.fence()
                    coordinator.transition('maintenance', 'Local pause; USB required for cross-PC quiescence')
                    return {'ok':True, 'device_id':device_id, 'ready':False, 'local_pause':True}
                try:
                    lease = await coordinator.maintenance_lease()
                    if lease is not None:
                        record.update(lease)
                    else:
                        # Claim USB maintenance before releasing a live BLE owner.
                        # Firmware can then preserve same-host telemetry atomically.
                        from .usb_transport import inspect_maintenance_identity
                        raw, legacy = await inspect_maintenance_identity(port)
                        if raw['device_id'] != device_id:
                            raise ValueError('Maintenance device identity mismatch')
                        if legacy:
                            await coordinator.fence()
                            record.update(ready=True, quiescence='unsupported_legacy')
                            self._persist_config(slot, replace(slot.config, maintenance=record))
                            coordinator.transition('maintenance', 'Local pause; legacy firmware cannot quiesce other PCs')
                            return {'ok':True, 'device_id':device_id, **record}
                        session = await maintenance_connection(port, self._host_id or load_host_id(),
                            record['token'], device_id)
                        record.update(boot=session.identity.boot, token=session.token)
                        await session.close(release=False)
                        await coordinator.fence()
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
                self.usb_discovery.resume(record.get('port'), device_id, record.get('instance_id'))
                coordinator.transition('disconnected', 'Maintenance completed')
                return {'ok': True, 'device_id': device_id}
            raise ValueError('Unknown device operation')

    async def control_device(self, event: dict) -> dict:
        device_id = event.get("device_id")
        if device_id is None:
            results = []
            for target in self.slots:
                try:
                    result = await self.control_device({**event, "device_id": target.config.device_id})
                except ValueError as exc:
                    result = {"ok": False, "device_id": target.config.device_id, "error": str(exc)}
                results.append(result)
            return {"ok": bool(results) and all(r["ok"] for r in results), "results": results,
                    "queued": sum(r["ok"] for r in results)}
        slot = next((s for s in self.slots if s.config.device_id == device_id), None)
        if slot is None or not slot.config.enabled or slot.config.maintenance:
            raise ValueError("Select an enabled display outside maintenance")
        if not slot.config.metadata.compatible:
            raise ValueError("Display protocol is incompatible")
        if not slot.state.connected:
            raise ValueError("Display must be connected before changing settings")
        if slot.state.transport == "usb" and not slot.state.device_state:
            raise ValueError("Verified device state required")
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
        import secrets
        payload = Payload("control", data, secrets.token_hex(16))
        slot.state.commands.admit(payload)
        for key,existing in list(slot.state.explicit_payloads.items()):
            if existing.data.get('cmd')==command:
                discard_intents(slot.state, [existing])
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
        remember_desired(payload, slot.state)
        discard_intents(slot.state, await put_latest(slot.queue, payload))
        return {"ok": True, "queued": command, "device_id": device_id, "command_id": payload.command_id}

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
