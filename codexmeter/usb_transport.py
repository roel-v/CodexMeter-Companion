"""USB candidate discovery and bounded, generation-scoped serial sessions.

The sole reader is a managed thread. It posts only into its own loop/session;
close fences callbacks before closing the handle and joins within one second.
"""

from __future__ import annotations
import asyncio
import contextlib
import threading
import queue
import time
from dataclasses import dataclass
from .serial_backend import open_serial
from .companion_protocol import (
    LineDecoder,
    NegotiatedIdentity,
    ProtocolError,
    object_json,
    FULL_ID,
)
from .transport_types import Endpoint
from .companion_session import CompanionSession, read_identity, IdentityIncompatible
from .transport_types import TransportError, UnknownDelivery


@dataclass(frozen=True)
class UsbCandidate:
    port: str
    instance_id: str


# Known unrelated instances may be supplied by deployment configuration/tests.
# Denylisting always wins over VID/PID eligibility.
def candidate_from_port(port, denylist=()) -> UsbCandidate | None:
    instance = str(getattr(port, "hwid", ""))
    upper = instance.upper()
    if any(str(denied).upper() in upper for denied in denylist):
        return None
    if getattr(port, "vid", None) != 0x303A or getattr(port, "pid", None) != 0x1001:
        return None
    if "BTHENUM" in upper or "ACPI" in upper:
        return None
    # pyserial exposes interface 00 as MI_00 in Windows hardware ID, or LOCATION x.0.
    interface = str(getattr(port, "interface", "") or "").upper()
    if "MI_" in upper and "MI_00" not in upper:
        return None
    if "MI_" not in upper and interface not in (
        "0",
        "00",
        "USB JTAG/SERIAL DEBUG UNIT",
    ):
        return None
    return UsbCandidate(str(port.device), instance or str(port.device))


def list_candidates(denylist=()) -> list[UsbCandidate]:
    import sys

    if sys.platform != "win32":
        return []
    import winreg

    # usbser + Ports class + interface 00 are checked against the PnP registry,
    # because pyserial deliberately drops MI/service metadata from its hwid.
    base = r"SYSTEM\CurrentControlSet\Enum\USB"
    from serial.tools import list_ports

    present = {p.device for p in list_ports.comports()}
    result = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as usb:
        for index in range(winreg.QueryInfoKey(usb)[0]):
            hardware = winreg.EnumKey(usb, index)
            if hardware.upper() != "VID_303A&PID_1001&MI_00":
                continue
            with winreg.OpenKey(usb, hardware) as interfaces:
                for child in range(winreg.QueryInfoKey(interfaces)[0]):
                    serial = winreg.EnumKey(interfaces, child)
                    instance = "USB\\" + hardware + "\\" + serial
                    if any(str(d).upper() in instance.upper() for d in denylist):
                        continue
                    try:
                        with winreg.OpenKey(interfaces, serial) as device:
                            service = winreg.QueryValueEx(device, "Service")[0]
                            class_guid = winreg.QueryValueEx(device, "ClassGUID")[0]
                            if (
                                service.lower() != "usbser"
                                or class_guid.lower()
                                != "{4d36e978-e325-11ce-bfc1-08002be10318}"
                            ):
                                continue
                            with winreg.OpenKey(device, "Device Parameters") as params:
                                port = winreg.QueryValueEx(params, "PortName")[0]
                        if port in present:
                            result.append(UsbCandidate(port, instance))
                    except OSError:
                        continue
    return result


_OPEN_SLOTS = threading.BoundedSemaphore(2)
_OPEN_PORTS = set()
_OPEN_LOCK = threading.Lock()

_OPERATION_SLOTS = threading.BoundedSemaphore(8)
_OPERATION_KEYS = set()
_OPERATION_LOCK = threading.Lock()


async def _bounded_call(function, timeout, *, late_cleanup=None, operation_key=None):
    # Every native operation holds one of eight slots until both execution and
    # any late cleanup finish. No native close ever runs on the event loop.
    with _OPERATION_LOCK:
        if operation_key is not None and operation_key in _OPERATION_KEYS:
            raise TransportError("serial operation already pending")
        if not _OPERATION_SLOTS.acquire(blocking=False):
            raise TransportError("serial operation capacity busy")
        if operation_key is not None:
            _OPERATION_KEYS.add(operation_key)
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    returned = threading.Event()
    claimed = threading.Event()
    released = threading.Event()

    def release_slot():
        with _OPERATION_LOCK:
            if released.is_set():
                return
            released.set()
            _OPERATION_KEYS.discard(operation_key)
            _OPERATION_SLOTS.release()

    def complete(value, error):
        if future.done():
            return
        if error is None:
            future.set_result(value)
        else:
            future.set_exception(error)

    def run():
        try:
            try:
                value, error = function(), None
            except BaseException as exc:
                value, error = None, exc
            if not loop.is_closed():
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(complete, value, error)
            returned.wait()
            if not claimed.is_set() and error is None and late_cleanup:
                with contextlib.suppress(Exception):
                    late_cleanup(value)
        finally:
            release_slot()

    threading.Thread(
        target=run, name="CodexMeter serial operation", daemon=True
    ).start()
    try:
        value = await asyncio.wait_for(asyncio.shield(future), timeout)
        claimed.set()
        return value
    finally:
        if not future.done():
            future.cancel()
        elif not future.cancelled():
            future.exception()
        if claimed.is_set():
            release_slot()
        returned.set()


class SerialChannel:
    def __init__(self, port: str, *, factory=None):
        self.port = port
        self.factory = factory
        self.handle = None
        self.thread = None
        self.closed = True
        self.lines = queue.Queue(maxsize=16)
        self.error = None
        self._write_lock = asyncio.Lock()
        self._closing = threading.Event()

    async def open(self):
        with _OPEN_LOCK:
            if self.port in _OPEN_PORTS:
                raise TransportError("serial open already pending")
            if not _OPEN_SLOTS.acquire(blocking=False):
                raise TransportError("serial open capacity busy")
            _OPEN_PORTS.add(self.port)

        def opening():
            try:
                handle = open_serial(self.port, factory=self.factory)
                if self._closing.is_set():
                    handle.close()
                    raise TransportError("serial open cancelled")
                return handle
            finally:
                with _OPEN_LOCK:
                    _OPEN_PORTS.discard(self.port)
                _OPEN_SLOTS.release()

        try:
            self.handle = await _bounded_call(
                opening,
                0.5,
                late_cleanup=lambda handle: handle.close(),
                operation_key=("io", self.port),
            )
        except BaseException as exc:
            self._closing.set()
            # A refused native dispatch has no worker to return its admission slot.
            if isinstance(exc, TransportError) and str(exc) in (
                "serial operation already pending",
                "serial operation capacity busy",
            ):
                with _OPEN_LOCK:
                    if self.port in _OPEN_PORTS:
                        _OPEN_PORTS.discard(self.port)
                        _OPEN_SLOTS.release()
            raise
        self.closed = False
        self.thread = threading.Thread(
            target=self._read, name=f"CodexMeter USB {self.port}", daemon=True
        )
        self.thread.start()
        return self

    def _read(self):
        decoder = LineDecoder()
        try:
            while not self._closing.is_set():
                chunk = self.handle.read(128)
                for line in decoder.feed(chunk):
                    if not line.startswith((b"CM1 ", b"IDENTITY ")):
                        continue
                    if self._closing.is_set():
                        return
                    try:
                        self.lines.put_nowait(line)
                    except queue.Full:
                        self.error = TransportError("serial reply queue overflow")
                        return
        except Exception:
            if not self._closing.is_set():
                self.error = TransportError("serial read failed")

    async def line(self, timeout=1.0):
        deadline = time.monotonic() + timeout
        while True:
            if self.closed:
                raise TransportError("serial channel closed")
            if self.error:
                raise self.error
            try:
                return self.lines.get_nowait()
            except queue.Empty:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("serial read deadline")
            await asyncio.sleep(min(0.01, max(0, deadline - time.monotonic())))

    async def write(self, frame):
        async with self._write_lock:
            if self.closed:
                raise TransportError("serial channel closed")

            def writing():
                offset = 0
                deadline = time.monotonic() + 0.5
                while offset < len(frame):
                    if self._closing.is_set() or time.monotonic() >= deadline:
                        raise UnknownDelivery("serial write deadline")
                    count = self.handle.write(frame[offset:])
                    if not count:
                        raise UnknownDelivery("serial write incomplete")
                    offset += count

            try:
                await _bounded_call(writing, 0.5, operation_key=("io", self.port))
            except asyncio.CancelledError:
                await self.close()
                raise
            except Exception as exc:
                await self.close()
                raise UnknownDelivery(
                    "serial write failed; outcome unknown"
                ) from exc

    async def close(self):
        if self._closing.is_set() and self.closed:
            return
        self.closed = True
        self._closing.set()

        def closing():
            if self.handle is not None:
                with contextlib.suppress(Exception):
                    cancel = getattr(self.handle, "cancel_read", None)
                    if cancel:
                        cancel()
                with contextlib.suppress(Exception):
                    self.handle.close()
            if self.thread is not None:
                self.thread.join(0.8)
                if self.thread.is_alive():
                    raise TransportError("serial reader failed to stop")

        await _bounded_call(closing, 1.0, operation_key=("close", self.port))


@dataclass(frozen=True)
class UsbDiscovered:
    candidate: UsbCandidate
    identity: NegotiatedIdentity
    seen_at: float

    @property
    def endpoint(self):
        return Endpoint(
            "usb", self.identity.device_id, self.candidate.port, self.identity.boot
        )

    def status(self, now=None):
        return {
            "transport": "usb",
            "address": self.candidate.port,
            "port": self.candidate.port,
            "device_id": self.identity.device_id,
            "short_id": self.identity.short_id,
            "name": self.identity.name,
            "source": "usb",
            "boot": self.identity.boot,
            **self.identity.metadata.to_json(),
            "last_seen_age_sec": round(
                max(0, (time.monotonic() if now is None else now) - self.seen_at), 1
            ),
        }


class UsbDiscovery:
    def __init__(
        self,
        *,
        candidates=list_candidates,
        channel_factory=SerialChannel,
        clock=time.monotonic,
    ):
        self.candidates = candidates
        self.channel_factory = channel_factory
        self.clock = clock
        self.devices = {}
        self.stability = {}
        self.paused_ids = set()
        self.paused_ports = set()
        self.paused_instances = set()
        self._probe_tasks = {}
        self.errors = {}
        self.unsupported = {}
        self.active_ports = set()
        self._retry = {}
        self._semaphore = asyncio.Semaphore(2)
        self._probing = set()
        self._changed = asyncio.Event()
        self._last_candidates = set()
        self.last_error = None
        self.initial_scan = asyncio.Event()

    def _paused(self, candidate):
        known = self.devices.get(candidate.port)
        return (candidate.port in self.paused_ports or candidate.instance_id in self.paused_instances
                or bool(known and known.identity.device_id in self.paused_ids))

    def instance_for_port(self, port):
        return next((instance for candidate_port, instance in self._last_candidates
                     if candidate_port == port), None)

    def restore_pause(self, port, device_id, instance_id=None):
        self.paused_ids.add(device_id)
        if port:
            self.paused_ports.add(port)
        if instance_id:
            self.paused_instances.add(instance_id)

    def resume(self, port, device_id, instance_id=None):
        self.paused_ids.discard(device_id)
        self.paused_ports.discard(port)
        self.paused_instances.discard(instance_id)
        self.invalidate(port)

    def invalidate(self, port):
        self.devices.pop(port, None)
        self.stability.pop(port, None)

    async def pause(self, port, device_id, instance_id=None):
        self.restore_pause(port, device_id, instance_id)
        tasks = [task for key, task in self._probe_tasks.items() if key == port]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            # Cancelling the coroutine does not cancel a native open/close.
            # Its admission key stays held until late handle cleanup finishes.
            deadline = asyncio.get_running_loop().time() + 1.5
            while True:
                with _OPERATION_LOCK:
                    pending = any((kind, port) in _OPERATION_KEYS for kind in ("io", "close"))
                if not pending:
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise TransportError("USB probe cleanup pending; maintenance pause retained")
                await asyncio.sleep(.01)

    async def _probe(self, candidate):
        key = candidate.instance_id
        if self._paused(candidate):
            return
        if key in self._probing or candidate.port in self.active_ports:
            return
        if self.clock() < self._retry.get(key, (0, 0))[0]:
            return
        self._probing.add(key)
        self._probe_tasks[candidate.port] = asyncio.current_task()
        try:
            async with self._semaphore:
                if self._paused(candidate):
                    return
                channel = self.channel_factory(candidate.port)
                try:
                    await channel.open()
                    if self._paused(candidate):
                        return
                    identity = await read_identity(channel)
                    if self._paused(candidate):
                        return
                    previous = self.devices.get(candidate.port)
                    now = self.clock()
                    stable = self.stability.get(candidate.port)
                    if previous is None or previous.identity.boot != identity.boot or previous.identity.device_id != identity.device_id:
                        self.stability[candidate.port] = (identity.boot, now, False)
                    elif stable and now - stable[1] >= 2:
                        self.stability[candidate.port] = (identity.boot, stable[1], True)
                    self.devices[candidate.port] = UsbDiscovered(
                        candidate, identity, self.clock()
                    )
                    self.errors.pop(candidate.port, None)
                    self.unsupported.pop(candidate.port, None)
                    self._retry.pop(key, None)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.devices.pop(candidate.port, None)
                    self.stability.pop(candidate.port, None)
                    if isinstance(exc, IdentityIncompatible):
                        self.unsupported[candidate.port] = {
                            "device_id": exc.device_id,
                            "port": candidate.port,
                            "address": candidate.port,
                            "transport": "usb",
                            "compatibility": "incompatible",
                            "reason": str(exc),
                            "instance_id": candidate.instance_id,
                        }
                    else:
                        self.unsupported.pop(candidate.port, None)
                    self.errors[candidate.port] = str(exc) or type(exc).__name__
                    count = self._retry.get(key, (0, 0))[1] + 1
                    delay = (
                        60
                        if isinstance(exc, ProtocolError)
                        else min(16, 2 ** min(count - 1, 4))
                    )
                    self._retry[key] = (self.clock() + delay, count)
                finally:
                    await channel.close()
        finally:
            self._probing.discard(key)
            self._probe_tasks.pop(candidate.port, None)
            self._changed.set()

    async def scan_once(self):
        try:
            candidates = await _bounded_call(
                self.candidates, 0.5, operation_key=("enumeration",)
            )
            self.last_error = None
        except Exception as exc:
            self.last_error = str(exc)
            return
        topology = {(c.port, c.instance_id) for c in candidates}
        if topology != self._last_candidates:
            changed = {instance for port, instance in topology ^ self._last_candidates}
            for instance in changed:
                self._retry.pop(instance, None)
            self._last_candidates = topology
        ports = {c.port for c in candidates}
        current = {c.port: c.instance_id for c in candidates}
        self.errors = {p: e for p, e in self.errors.items() if p in ports}
        self.unsupported = {
            p: d
            for p, d in self.unsupported.items()
            if current.get(p) == d["instance_id"]
        }
        self.stability = {p: v for p, v in self.stability.items() if p in ports}
        self.devices = {
            p: d
            for p, d in self.devices.items()
            if current.get(p) == d.candidate.instance_id
        }
        # Skip active ports: opening them again would violate exclusive reader ownership.
        await asyncio.gather(*(self._probe(c) for c in candidates), return_exceptions=True)

    async def run(self, stop):
        while not stop.is_set():
            try:
                await self.scan_once()
            finally:
                self.initial_scan.set()
            try:
                await asyncio.wait_for(stop.wait(), 2)
            except TimeoutError:
                pass

    def find(self, config):
        matches = [
            d for d in self.devices.values() if d.identity.device_id == config.device_id
        ]
        return matches[0] if len(matches) == 1 else None

    def stable(self, config):
        found = self.find(config)
        return found if found and self.stability.get(found.candidate.port, (None, 0, False))[2] else None

    def unknown_devices(self, configs):
        ids = {c.device_id for c in configs}
        return [
            d.status() for d in self.devices.values() if d.identity.device_id not in ids
        ] + [dict(d) for d in self.unsupported.values() if d["device_id"] not in ids]

    def status(self, now=None):
        ids = [d.identity.device_id for d in self.devices.values()]
        return {
            "cached_count": len(self.devices),
            "last_error": self.last_error,
            "port_errors": dict(self.errors),
            "ambiguous_ids": sorted({i for i in ids if ids.count(i) > 1}),
        }


class UsbSession(CompanionSession):
    """Serial endpoint adapter for the common negotiated session."""
    def __init__(self, discovered, host_id, *, channel_factory=SerialChannel,
                 request_timeout=1.0, clock=time.monotonic):
        super().__init__(discovered.identity, host_id,
                         endpoint=Endpoint("usb", discovered.identity.device_id, discovered.candidate.port),
                         channel_factory=lambda: channel_factory(discovered.candidate.port),
                         request_timeout=request_timeout, clock=clock)


async def bluetooth_availability():
    """Optional adapter capability; no pairing or recovery side effects."""
    import sys
    if sys.platform != 'win32':
        try:
            import bleak
            return True, None
        except ImportError:
            return False, 'Bluetooth backend unavailable'
    try:
        from winrt.windows.devices.radios import Radio, RadioKind, RadioState
        radios = await asyncio.wait_for(Radio.get_radios_async(), 2)
        available = any(r.kind == RadioKind.BLUETOOTH and r.state == RadioState.ON for r in radios)
        return available, None if available else 'Bluetooth adapter absent or switched off'
    except Exception:
        return False, 'Bluetooth adapter inaccessible or unsupported'


async def maintenance_connection(port, host_id, token=None, expected_id=None):
    """Exclusive verified connection; the caller closes it without app release."""
    channel = SerialChannel(port)
    try:
        await channel.open()
        identity = await read_identity(channel)
    finally:
        await channel.close()
    if expected_id and identity.device_id != expected_id:
        raise TransportError('Maintenance device identity mismatch')
    found = UsbDiscovered(UsbCandidate(port, port), identity, time.monotonic())
    session = UsbSession(found, host_id)
    if token:
        session.token = token
    await session.open(maintenance=True)
    return session


async def inspect_maintenance_identity(port):
    """Read-only full identity, including positively identified pre-USB firmware."""
    channel = SerialChannel(port)
    try:
        await channel.open()
        await channel.write(b'identity\n')
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            line = await channel.line(max(.001, deadline-time.monotonic()))
            if line.startswith(b'IDENTITY '):
                raw = object_json(line[9:])
                if not isinstance(raw.get('device_id'), str) or not FULL_ID.fullmatch(raw['device_id']):
                    raise TransportError('Maintenance full identity required')
                if 'usb' not in raw:
                    short_id = raw.get('short_id')
                    if not isinstance(short_id, str) or not short_id or raw.get('name') != 'CodexMeter-' + short_id:
                        raise TransportError('Legacy maintenance identity incomplete')
                    return raw, True
                NegotiatedIdentity.parse(line)  # Malformed/unsupported updated firmware is never legacy.
                return raw, False
        raise TransportError('Maintenance identity unavailable')
    finally:
        await channel.close()
