"""BLE transport for the CodexMeter display."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from typing import Any, Callable

from .payloads import Payload
from .settings import (
    BLE_ACK_TIMEOUT_SEC,
    BLE_CONNECT_TIMEOUT_SEC,
    BLE_DISCONNECT_TIMEOUT_SEC,
    BLE_HEALTHCHECK_INTERVAL_SEC,
    BLE_NOTIFY_TIMEOUT_SEC,
    BLE_WRITE_TIMEOUT_SEC,
    IDENTITY_CHAR_UUID,
    REQ_CHAR_UUID,
    RX_CHAR_UUID,
    SERVICE_UUID,
    TX_CHAR_UUID,
)

log = logging.getLogger(__name__)


class MacConnectedDeviceLookup:
    """Reusable CoreBluetooth lookup for peripherals that are not advertising."""

    def __init__(
        self,
        service_uuids: tuple[str, ...] = (SERVICE_UUID, "1812"),
        ready_timeout_sec: float = 5.0,
    ) -> None:
        self.service_uuids = service_uuids
        self.ready_timeout_sec = ready_timeout_sec
        self._manager: Any | None = None
        self.last_error: str | None = None

    async def __call__(self) -> list[Any]:
        if sys.platform != "darwin":
            return []
        try:
            from CoreBluetooth import CBUUID  # type: ignore
            from bleak.backends.corebluetooth.CentralManagerDelegate import (  # type: ignore
                CentralManagerDelegate,
            )
            from bleak.backends.device import BLEDevice  # type: ignore
        except Exception:
            self.last_error = "CoreBluetooth connected lookup unavailable"
            return []

        try:
            if self._manager is None:
                self._manager = CentralManagerDelegate()
                await asyncio.wait_for(
                    self._manager.wait_until_ready(), timeout=self.ready_timeout_sec
                )
            central = self._manager.central_manager
            result: list[Any] = []
            seen: set[str] = set()
            for service in self.service_uuids:
                peripherals = central.retrieveConnectedPeripheralsWithServices_(
                    [CBUUID.UUIDWithString_(service)]
                )
                for peripheral in peripherals or []:
                    address = str(peripheral.identifier().UUIDString())
                    if address in seen:
                        continue
                    seen.add(address)
                    name = peripheral.name()
                    result.append(
                        BLEDevice(
                            address,
                            str(name) if name is not None else None,
                            (peripheral, self._manager),
                        )
                    )
            self.last_error = None
            return result
        except Exception as exc:
            self._manager = None
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.debug("macOS connected-peripheral lookup failed", exc_info=True)
            return []


class BleWriteTimeout(RuntimeError):
    """Raised when CoreBluetooth accepts a connection but a GATT write stalls."""


class BleConnectTimeout(RuntimeError):
    """Raised when CoreBluetooth does not finish connecting in time."""


class BleAckTimeout(RuntimeError):
    """Raised when the device does not confirm a payload after it is written."""


class BleAckError(RuntimeError):
    """Raised when the device reports that a payload was not accepted."""


class BleNotifyError(RuntimeError):
    """Raised when mandatory BLE notifications cannot be subscribed."""


from .device_identity import DeviceIdentity, DeviceIdentityError


class BleAckTracker:
    def __init__(self) -> None:
        self.count = 0
        self.last_text = ""
        self.event = asyncio.Event()

    def notify(self, data: bytearray) -> str:
        text = bytes(data).decode("utf-8", errors="replace")
        self.last_text = text
        self.count += 1
        self.event.set()
        return text

    async def wait_for_next(self, previous_count: int, timeout_sec: float) -> str:
        while self.count <= previous_count:
            self.event.clear()
            if self.count > previous_count:
                break
            try:
                await asyncio.wait_for(self.event.wait(), timeout=timeout_sec)
            except asyncio.TimeoutError as exc:
                raise BleAckTimeout(
                    f"BLE ACK timed out after {timeout_sec:.1f}s"
                ) from exc
        return self.last_text


from .delivery import DeliveryState
from .delivery import remember_accepted, should_send, telemetry_fresh


class BleTransport:
    def __init__(
        self,
        connect_timeout_sec: float = BLE_CONNECT_TIMEOUT_SEC,
        disconnect_timeout_sec: float = BLE_DISCONNECT_TIMEOUT_SEC,
        write_timeout_sec: float = BLE_WRITE_TIMEOUT_SEC,
        ack_timeout_sec: float = BLE_ACK_TIMEOUT_SEC,
        notify_timeout_sec: float = BLE_NOTIFY_TIMEOUT_SEC,
        healthcheck_interval_sec: float = BLE_HEALTHCHECK_INTERVAL_SEC,
    ) -> None:
        self.session = None
        self.connect_timeout_sec = connect_timeout_sec
        self.disconnect_timeout_sec = disconnect_timeout_sec
        self.write_timeout_sec = write_timeout_sec
        self.ack_timeout_sec = ack_timeout_sec
        self.notify_timeout_sec = notify_timeout_sec
        self.healthcheck_interval_sec = healthcheck_interval_sec

    def _create_client(self, target: Any) -> Any:
        from bleak import BleakClient

        return BleakClient(target, timeout=self.connect_timeout_sec)

    async def _disconnect(self, client: Any, display: str) -> None:
        # Ownership revocation can start cleanup before the coordinator cancels
        # the worker. Do not let that cancellation strand the native GATT handle.
        cleanup = asyncio.create_task(self._disconnect_bounded(client, display))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise

    async def _disconnect_bounded(self, client: Any, display: str) -> None:
        try:
            await asyncio.wait_for(
                client.disconnect(), timeout=self.disconnect_timeout_sec
            )
        except asyncio.TimeoutError:
            log.warning(
                "BLE disconnect from %s timed out after %.1fs",
                display,
                self.disconnect_timeout_sec,
            )
        except Exception:
            log.warning("BLE disconnect from %s failed", display, exc_info=True)

    async def _connect_and_write(
        self,
        target: Any,
        queue: "asyncio.Queue[Payload]",
        state: DeliveryState,
        stop_event: asyncio.Event,
        *,
        require_identity: bool = False,
        identity_validator: Callable[[DeviceIdentity], None] | None = None,
    ) -> bool:
        from bleak.exc import BleakError

        refresh_requested = asyncio.Event()
        import secrets
        generation = secrets.token_hex(16)
        state.generation = generation
        state.transport = "bluetooth"
        active = True

        def on_refresh(_char: Any, _data: bytearray) -> None:
            if not active or state.generation != generation:
                return
            log.info("Device requested a refresh")
            refresh_requested.set()

        display = getattr(target, "address", str(target))
        log.info("Connecting to %s", display)
        used_successfully = False
        client = self._create_client(target)
        loop = asyncio.get_running_loop()
        try:
            try:
                await asyncio.wait_for(
                    client.connect(), timeout=self.connect_timeout_sec
                )
            except asyncio.TimeoutError as exc:
                raise BleConnectTimeout(
                    f"BLE connect timed out after {self.connect_timeout_sec:.1f}s"
                ) from exc
            log.info("Connected to %s", display)
            if require_identity:
                identity = await self._read_identity(client)
                if identity_validator is not None:
                    identity_validator(identity)
                state.observed_device_id = identity.device_id
                if identity.raw and identity.raw.get('ble_owner') == 1:
                    return await self._negotiated(client,identity,queue,state,stop_event)
            ack_tracker: BleAckTracker | None = BleAckTracker()
            try:
                await self._start_notify(
                    client,
                    TX_CHAR_UUID,
                    lambda char, data: self._on_ack(char, data, ack_tracker) if active and state.generation == generation else None,
                )
            except (BleakError, ValueError, BleNotifyError) as exc:
                raise BleNotifyError("BLE ACK notifications unavailable") from exc

            try:
                await self._start_notify(client, REQ_CHAR_UUID, on_refresh)
            except (BleakError, ValueError, BleNotifyError) as exc:
                log.debug("BLE refresh notifications unavailable: %s", exc)

            state.connected = True
            state.last_connected_at = loop.time()
            state.last_error = None

            try:
                for reconnect_control in (state.desired_control, state.desired_policy or state.connect_control):
                    if reconnect_control is not None and should_send(reconnect_control, state):
                        await self._write_payload(client, reconnect_control, ack_tracker, state)
                        used_successfully = True
                for setting in list(state.desired_settings.values()):
                    await self._write_payload(client, setting, ack_tracker, state)
                if state.last_usage is not None:
                    await self._write_payload(
                        client, state.last_usage, ack_tracker, state
                    )
                    used_successfully = True
                if state.last_activity is not None:
                    await self._write_payload(
                        client, state.last_activity, ack_tracker, state
                    )
                    used_successfully = True
                if state.pending_alert is not None and not should_send(state.pending_alert, state):
                    state.pending_alert = None
                if state.pending_alert is not None:
                    pending_alert = state.pending_alert
                    await self._write_reliably(
                        client, pending_alert, ack_tracker, state
                    )
                    used_successfully = True

                while client.is_connected and not stop_event.is_set():
                    payload_task = asyncio.create_task(queue.get())
                    refresh_task = asyncio.create_task(refresh_requested.wait())
                    stop_task = asyncio.create_task(stop_event.wait())
                    health_task = asyncio.create_task(
                        asyncio.sleep(self.healthcheck_interval_sec)
                    )
                    tasks = {payload_task, refresh_task, stop_task, health_task}
                    try:
                        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        for task in tasks:
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)

                    payload = payload_task.result() if payload_task in done else None
                    if payload is not None and payload.kind == "alert":
                        state.pending_alert = payload

                    if stop_task in done:
                        break
                    if not client.is_connected:
                        break
                    if payload is not None:
                        if not should_send(payload, state):
                            log.info("Skipped stale BLE payload %s", payload.kind)
                            if state.pending_alert is payload:
                                state.pending_alert = None
                            continue
                        await self._write_reliably(client, payload, ack_tracker, state)
                        used_successfully = True
                        continue
                    if refresh_task in done and refresh_requested.is_set():
                        refresh_requested.clear()
                        for snapshot in (state.last_usage, state.last_activity):
                            if snapshot is not None and telemetry_fresh(snapshot, state):
                                await self._write_payload(client, snapshot, ack_tracker, state)
                                used_successfully = True
                        continue
                    if health_task in done:
                        heartbeat = next((p for p in (state.last_usage, state.last_activity)
                                          if p is not None and telemetry_fresh(p, state)), None)
                        if heartbeat is not None:
                            log.info("BLE health check with %s payload", heartbeat.kind)
                            await self._write_payload(client, heartbeat, ack_tracker, state)
                            used_successfully = True
            finally:
                state.connected = False
                state.last_disconnected_at = loop.time()
        finally:
            active = False
            await self._disconnect(client, display)
            log.info("BLE disconnected from %s", display)
        return used_successfully

    async def _negotiated(self, client, identity, queue, state, stop_event):
        from .ble_session import BleSession
        from .host_identity import load_host_id
        from .delivery_pump import DeliveryPump
        from .delivery import negotiated_replay
        session=BleSession(client,identity,load_host_id())
        self.session = session
        delivery=DeliveryPump(state, session)
        try:
            await session.open()
            state.connected=True;state.transport='bluetooth';state.generation=session.generation
            state.last_connected_at=time.monotonic();state.last_error=None
            state.device_state={**session.state,'boot':session.identity.boot}
            while not queue.empty():
                queue.get_nowait()
            replay = negotiated_replay(state, same_host=session.state['same_host'])
            hook = getattr(self, 'on_reconciled', None)
            if hook:
                await hook(state, session)
            for payload in replay:
                await delivery.deliver(payload)
            while client.is_connected and not stop_event.is_set() and not session.failure:
                try: payload=await asyncio.wait_for(queue.get(),.1)
                except TimeoutError:continue
                await delivery.deliver(payload)
            if session.failure:raise session.failure
            return True
        finally:
            state.connected=False;state.last_disconnected_at=time.monotonic()
            try:
                await session.close()
            finally:
                self.session = None

    async def connect_and_write(
        self,
        target: Any,
        queue: "asyncio.Queue[Payload]",
        state: DeliveryState,
        stop_event: asyncio.Event,
        *,
        require_identity: bool = False,
        identity_validator: Callable[[DeviceIdentity], None] | None = None,
    ) -> bool:
        return await self._connect_and_write(
            target,
            queue,
            state,
            stop_event,
            require_identity=require_identity,
            identity_validator=identity_validator,
        )

    async def _read_identity(self, client: Any) -> DeviceIdentity:
        try:
            raw = await asyncio.wait_for(
                client.read_gatt_char(IDENTITY_CHAR_UUID),
                timeout=self.notify_timeout_sec,
            )
        except asyncio.TimeoutError as exc:
            raise DeviceIdentityError("BLE identity read timed out") from exc
        except Exception as exc:
            raise DeviceIdentityError("BLE identity characteristic unavailable") from exc
        return DeviceIdentity.from_bytes(raw)

    async def _write_payload(
        self, client, payload, ack_tracker=None, state=None,
    ):
        if state is None or not payload.command_id:
            return await self._write_legacy(client, payload, ack_tracker, state)
        from .delivery import sweep_commands
        sweep_commands(state)
        generation = state.generation or 'legacy'
        if not state.commands.start(payload, generation):
            return
        try:
            await self._write_legacy(client, payload, ack_tracker, state)
        except BaseException as exc:
            state.commands.finish(payload, 'rejected' if isinstance(exc, BleAckError) else 'unknown',
                                  str(exc) or 'Connection ended before acknowledgement', generation=generation)
            sweep_commands(state)
            raise
        state.commands.finish(payload, 'applied', generation=generation)
        # Legacy reconnect restores the acknowledged preference, not a new tracked user request.
        restored = Payload(payload.kind, dict(payload.data))
        if state.desired_control is payload:
            state.desired_control = restored
        if state.desired_settings.get(payload.data.get('cmd')) is payload:
            state.desired_settings[payload.data['cmd']] = restored
        sweep_commands(state)

    async def _write_legacy(
        self,
        client: Any,
        payload: Payload,
        ack_tracker: BleAckTracker | None = None,
        state: DeliveryState | None = None,
    ) -> None:
        if state is not None and payload.kind in ("usage", "activity") and not telemetry_fresh(payload, state):
            return
        # Only the legacy wire adapter translates historical policy reason names.
        wire_payload = payload
        if payload.kind == "control" and payload.data.get("cmd") == "screen":
            reason = {"lock": "mac_locked", "unlock": "mac_unlocked",
                      "connection_restored": "ble_restored"}.get(payload.data.get("why"))
            if reason:
                wire_payload = Payload(payload.kind, {**payload.data, "why": reason})
        data = wire_payload.to_json_bytes()
        log.debug(
            "BLE write %s: %s",
            payload.kind,
            data.decode("utf-8", errors="replace"),
        )
        previous_ack_count = ack_tracker.count if ack_tracker is not None else 0
        loop = asyncio.get_running_loop()
        if state is not None:
            state.last_write_at = loop.time()
        try:
            await asyncio.wait_for(
                client.write_gatt_char(RX_CHAR_UUID, data, response=True),
                timeout=self.write_timeout_sec,
            )
        except asyncio.TimeoutError as exc:
            raise BleWriteTimeout(
                f"BLE write {payload.kind} timed out after {self.write_timeout_sec:.1f}s"
            ) from exc

        if ack_tracker is None:
            raise BleNotifyError("BLE ACK tracker is unavailable")

        try:
            ack_text = await ack_tracker.wait_for_next(
                previous_ack_count, self.ack_timeout_sec
            )
        except BleAckTimeout as exc:
            raise BleAckTimeout(
                f"BLE ACK for {payload.kind} timed out after {self.ack_timeout_sec:.1f}s"
            ) from exc
        self._require_ack(payload, ack_text)
        if state is not None:
            remember_accepted(payload, state)
            state.last_ack_at = loop.time()
            state.consecutive_failures = 0
            state.last_error = None

    async def _write_reliably(
        self,
        client: Any,
        payload: Payload,
        ack_tracker: BleAckTracker,
        state: DeliveryState,
    ) -> None:
        if payload.kind == "alert":
            state.pending_alert = payload
        await self._write_payload(client, payload, ack_tracker, state)
        if payload.kind == "alert":
            from .delivery import accepted_alert
            accepted_alert(payload, state)
        if state.pending_alert is payload:
            state.pending_alert = None

    async def _start_notify(self, client: Any, uuid: str, callback: Any) -> None:
        try:
            await asyncio.wait_for(
                client.start_notify(uuid, callback),
                timeout=self.notify_timeout_sec,
            )
        except asyncio.TimeoutError as exc:
            raise BleNotifyError(
                f"BLE notify {uuid} timed out after {self.notify_timeout_sec:.1f}s"
            ) from exc

    @staticmethod
    def _require_ack(payload: Payload, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BleAckError(f"BLE ACK for {payload.kind} was invalid: {text!r}") from exc
        if not isinstance(data, dict) or data.get("ack") is not True:
            raise BleAckError(f"BLE NACK for {payload.kind}: {text}")

    def _on_ack(
        self,
        _char: Any,
        data: bytearray,
        ack_tracker: BleAckTracker | None = None,
    ) -> None:
        if ack_tracker is not None:
            text = ack_tracker.notify(data)
        else:
            text = bytes(data).decode("utf-8", errors="replace")
        log.debug("BLE ack: %s", text)


class contextlib_suppress_bleak:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: BaseException | None, _tb: Any) -> bool:
        if exc is None:
            return False
        try:
            from bleak.exc import BleakError
        except Exception:
            BleakError = Exception  # type: ignore
        if isinstance(exc, (BleakError, ValueError)):
            log.debug("Optional BLE operation failed: %s", exc)
            return True
        return False
