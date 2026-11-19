import asyncio
import json
import queue
import threading
import time
import builtins
import pytest
from codexmeter.usb_transport import *
from codexmeter.companion_protocol import NegotiatedIdentity
from codexmeter.payloads import Payload
from tests.support.usb_transport import B, ID, H, STATE, IDENTITY, discovered, FakeChannel


class UnknownLockState:
    async def is_locked(self):
        return None


def test_session_correlates_retry_and_explicit_rejection():
    async def run():
        c = FakeChannel("x")
        s = UsbSession(discovered(), H, channel_factory=lambda _: c, request_timeout=1)
        await s.open()
        s.timeout = 0.08
        c.drop = 1
        c.wrong = True
        p = Payload("activity", {"v": 1, "k": "activity", "run": 1})
        result = await s.send(p)
        assert result.outcome == "accepted"
        data = [f for f in c.writes if f.startswith(b"CM1 DATA")]
        assert len(data) == 2 and data[0] == data[1]
        c.rejected = "unsupported"
        assert (await s.send(p)).outcome == "rejected"
        assert (
            await s.send(
                Payload(
                    "control",
                    {"v": 1, "k": "control", "cmd": "brightness", "value": 50},
                )
            )
        ).reason == "stale explicit intent"
        await s.close()
        assert c.closed and not s._waiters
        assert s._reader.done() and s._heartbeat.done()

    asyncio.run(run())


def test_unknown_fences_and_cancellation_cleans_waiters():
    async def run():
        for cancel in (False, True):
            c = FakeChannel("x")
            s = UsbSession(
                discovered(), H, channel_factory=lambda _: c, request_timeout=1
            )
            await s.open()
            s.timeout = 0.08
            c.drop = 10
            task = asyncio.create_task(
                s.send(Payload("activity", {"v": 1, "k": "activity", "run": 1}))
            )
            if cancel:
                await asyncio.sleep(0.01)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                assert (await task).outcome == "unknown"
            assert (
                c.closed and not s._waiters and s._reader.done() and s._heartbeat.done()
            )

    asyncio.run(run())


def test_com_reuse_rejected_before_claim():
    async def run():
        c = FakeChannel("x")
        c.changed = True
        s = UsbSession(discovered(), H, channel_factory=lambda _: c)
        with pytest.raises(TransportError, match="identity/boot changed"):
            await s.open()
        assert c.writes == [b"identity\n"] and c.closed

    asyncio.run(run())


class FakeSerial:
    def __init__(self):
        self.data = queue.Queue()
        self.closed = False
        self.opened = False

    def open(self):
        self.opened = True

    def read(self, n):
        try:
            return self.data.get(timeout=0.02)
        except queue.Empty:
            return b""

    def write(self, data):
        return len(data)

    def cancel_read(self):
        self.data.put(b"")

    def close(self):
        self.closed = True
        self.data.put(b"")


def test_close_waiting_reader_and_open_flags():
    async def run():
        fake = FakeSerial()
        c = SerialChannel("reader", factory=lambda: fake)
        await c.open()
        assert (
            not fake.dtr
            and not fake.rts
            and fake.timeout <= 0.1
            and fake.write_timeout <= 0.5
        )
        await c.close()
        assert fake.closed and not c.thread.is_alive()

    asyncio.run(run())


def test_hanging_open_is_bounded_and_late_handle_disposed():
    released = threading.Event()
    fake = FakeSerial()

    def opening():
        released.wait()
        fake.opened = True

    fake.open = opening
    start = time.monotonic()

    async def run():
        stalled = SerialChannel("hung-open", factory=lambda: fake)
        task = asyncio.create_task(stalled.open())
        peer = SerialChannel("healthy-peer", factory=FakeSerial)
        await peer.open()
        await peer.close()
        with pytest.raises(TimeoutError):
            await task
        await stalled.close()
        assert not fake.closed

    try:
        asyncio.run(run())
        assert time.monotonic() - start < 1.5
    finally:
        released.set()
    for _ in range(100):
        if fake.closed:
            break
        time.sleep(0.01)
    assert fake.closed


def test_discovery_isolated_unregistered_and_ambiguous():
    async def run():
        channels = []

        def factory(port):
            c = FakeChannel(port)
            channels.append(c)
            if port == "hung":

                async def no_open():
                    raise TimeoutError("busy")

                c.open = no_open
            return c

        d = UsbDiscovery(
            candidates=lambda: [
                UsbCandidate(p, p) for p in ["one", "two", "three", "hung"]
            ],
            channel_factory=factory,
        )
        await d.scan_once()
        assert len(d.devices) == 3 and "hung" in d.errors
        from codexmeter.device_registry import DeviceConfig

        assert d.find(DeviceConfig(ID)) is None
        assert len(d.unknown_devices([])) == 3
        assert all(not any(w.startswith(b"CM1") for w in c.writes) for c in channels)
        assert all(c.closed for c in channels)

    asyncio.run(run())


def test_usb_worker_with_every_bluetooth_import_unavailable(monkeypatch):
    original = builtins.__import__

    def importing(name, *args, **kwargs):
        if name.startswith(("bleak", "CoreBluetooth", "winrt")):
            raise ImportError("no Bluetooth")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)

    async def run():
        from codexmeter.device_registry import DeviceConfig
        from codexmeter.device_manager import DeviceManager

        channels = []

        def factory(port):
            c = FakeChannel(port)
            channels.append(c)
            return c

        d = UsbDiscovery(
            candidates=lambda: [UsbCandidate("usb", "usb")], channel_factory=factory
        )
        m = DeviceManager(
            [DeviceConfig(ID)],
            usb_discovery=d,
            policy_detector=UnknownLockState(),
            host_id=H,
            connect_timeout_sec=0.1,
            disconnect_timeout_sec=0.1,
            write_timeout_sec=0.1,
            ack_timeout_sec=0.1,
            notify_timeout_sec=0.1,
            healthcheck_interval_sec=1,
        )
        # Default session factory is replaced at the worker boundary, never a BLE mock success.
        import codexmeter.usb_worker as module

        real = module.UsbDeviceWorker

        class Worker(real):
            def __init__(self, *args, **kwargs):
                super().__init__(
                    *args,
                    session_factory=lambda item, host: UsbSession(
                        item, host, channel_factory=factory
                    ),
                    **kwargs,
                )

        monkeypatch.setattr(module, "UsbDeviceWorker", Worker)
        stop = asyncio.Event()
        task = asyncio.create_task(m.run(stop))
        for _ in range(500):
            if m.slots[0].state.connected:
                break
            await asyncio.sleep(0.01)
        assert m.slots[0].state.transport == "usb" and m.slots[0].state.connected
        await m.broadcast(Payload("activity", {"v": 1, "k": "activity", "run": 1}))
        for _ in range(100):
            if m.slots[0].state.last_ack_at:
                break
            await asyncio.sleep(0.01)
        assert m.slots[0].state.last_ack_at
        assert m.discovery.status()["last_scan_age_sec"] is None
        stop.set()
        await task
        assert all(c.closed for c in channels)

    asyncio.run(run())


def test_hung_native_cleanup_and_repeated_open_do_not_starve_peer():
    released = threading.Event()
    cleanup_released = threading.Event()
    fake = FakeSerial()

    def opening():
        released.wait()

    def closing():
        cleanup_released.wait()
        fake.closed = True

    fake.open = opening
    fake.close = closing

    async def run():
        task = asyncio.create_task(
            SerialChannel("repeat-hung", factory=lambda: fake).open()
        )
        with pytest.raises(TimeoutError):
            await task
        for _ in range(12):
            with pytest.raises(TransportError):
                await SerialChannel("repeat-hung", factory=FakeSerial).open()
        released.set()
        await asyncio.sleep(0.03)
        # Late native close remains blocked off-loop and holds a single port slot.
        peer = SerialChannel("unrelated-healthy", factory=FakeSerial)
        await peer.open()
        await peer.close()
        assert not fake.closed

    try:
        asyncio.run(run())
    finally:
        released.set()
        cleanup_released.set()
    for _ in range(100):
        if fake.closed:
            break
        time.sleep(0.01)
    assert fake.closed


def test_enumeration_single_flight_does_not_accumulate_workers():
    released = threading.Event()
    calls = []

    def candidates():
        calls.append(1)
        released.wait()
        return []

    async def run():
        d = UsbDiscovery(candidates=candidates)
        await d.scan_once()
        for _ in range(12):
            await d.scan_once()
        assert len(calls) == 1
        peer = SerialChannel("enumeration-healthy", factory=FakeSerial)
        await peer.open()
        await peer.close()

    try:
        asyncio.run(run())
    finally:
        released.set()


def test_upgrade_required_retains_basic_identity_never_claims():
    async def run():
        channels = []

        class Old(FakeChannel):
            async def write(self, frame):
                self.writes.append(frame)
                data = {
                    **IDENTITY,
                    "device_id": (
                        ID if self.port == "old" else "codexmeter-ffffffffffff"
                    ),
                }
                if self.port == "old":
                    data.pop("usb")
                else:
                    data["usb"] = 2
                await self.lines.put(b"IDENTITY " + json.dumps(data).encode())

        def factory(port):
            c = Old(port)
            channels.append(c)
            return c

        d = UsbDiscovery(
            candidates=lambda: [
                UsbCandidate("old", "old"),
                UsbCandidate("future", "future"),
            ],
            channel_factory=factory,
        )
        await d.scan_once()
        assert not d.devices and len(d.unsupported) == 2
        assert {item["device_id"] for item in d.unsupported.values()} == {
            ID,
            "codexmeter-ffffffffffff",
        }
        assert all(c.writes == [b"identity\n"] for c in channels)
        from codexmeter.device_manager import DeviceManager
        from codexmeter.device_registry import DeviceConfig

        m = DeviceManager(
            [DeviceConfig(ID, connection_mode="usb_only")],
            usb_discovery=d,
            host_id=H,
            connect_timeout_sec=0.1,
            disconnect_timeout_sec=0.1,
            write_timeout_sec=0.1,
            ack_timeout_sec=0.1,
            notify_timeout_sec=0.1,
            healthcheck_interval_sec=1,
        )
        assert "upgrade required" in m.status()["devices"][0]["last_error"]

    asyncio.run(run())


def test_initial_auto_retries_usb_after_first_identity_timeout(monkeypatch):
    async def run():
        from codexmeter.device_manager import DeviceManager
        from codexmeter.device_registry import DeviceConfig
        import codexmeter.usb_worker as module

        count = [0]

        def factory(port):
            c = FakeChannel(port)
            count[0] += 1
            if count[0] == 1:

                async def fail(frame):
                    raise TimeoutError("cold first query")

                c.write = fail
            return c

        d = UsbDiscovery(
            candidates=lambda: [UsbCandidate("late-usb", "late-usb")],
            channel_factory=factory,
        )
        m = DeviceManager(
            [DeviceConfig(ID)],
            usb_discovery=d,
            policy_detector=UnknownLockState(),
            host_id=H,
            connect_timeout_sec=0.1,
            disconnect_timeout_sec=0.1,
            write_timeout_sec=0.1,
            ack_timeout_sec=0.1,
            notify_timeout_sec=0.1,
            healthcheck_interval_sec=1,
        )

        async def no_radio(_):
            raise ImportError("no adapter/backend")

        m.discovery._scanner = no_radio
        real = module.UsbDeviceWorker

        class Worker(real):
            def __init__(self, *args, **kwargs):
                super().__init__(
                    *args,
                    session_factory=lambda item, host: UsbSession(
                        item, host, channel_factory=factory
                    ),
                    **kwargs,
                )

        monkeypatch.setattr(module, "UsbDeviceWorker", Worker)
        stop = asyncio.Event()
        task = asyncio.create_task(m.run(stop))
        for _ in range(650):
            if m.slots[0].state.connected:
                break
            await asyncio.sleep(0.01)
        assert m.slots[0].state.connected and m.slots[0].state.transport == "usb"
        stop.set()
        await task

    asyncio.run(run())


def test_four_device_workers_one_unanswered_ack_does_not_block_peers(monkeypatch):
    async def run():
        from dataclasses import replace
        from codexmeter.device_manager import DeviceManager
        from codexmeter.device_registry import DeviceConfig
        import codexmeter.usb_worker as module

        ids = {str(i): f"codexmeter-{i:012x}" for i in range(1, 5)}

        unanswered = asyncio.Event()

        class Channel(FakeChannel):
            async def write(self, frame):
                if frame == b"identity\n":
                    self.writes.append(frame)
                    await self.lines.put(
                        b"IDENTITY "
                        + json.dumps({**IDENTITY, "device_id": ids[self.port]}).encode()
                    )
                else:
                    await super().write(frame)
                    if self.port == "4" and frame.startswith(b"CM1 DATA "):
                        unanswered.set()

        channels = []

        def factory(port):
            c = Channel(port)
            channels.append(c)
            if port == "4":
                c.drop = 100
            return c

        d = UsbDiscovery(
            candidates=lambda: [UsbCandidate(p, p) for p in ids],
            channel_factory=factory,
        )
        m = DeviceManager(
            [DeviceConfig(i, connection_mode="usb_only") for i in ids.values()],
            usb_discovery=d,
            policy_detector=UnknownLockState(),
            host_id=H,
            connect_timeout_sec=0.1,
            disconnect_timeout_sec=0.1,
            write_timeout_sec=0.1,
            ack_timeout_sec=0.1,
            notify_timeout_sec=0.1,
            healthcheck_interval_sec=1,
        )
        real = module.UsbDeviceWorker

        class Worker(real):
            def __init__(self, *args, **kwargs):
                super().__init__(
                    *args,
                    session_factory=lambda item, host: UsbSession(
                        item, host, channel_factory=factory
                    ),
                    **kwargs,
                )

        monkeypatch.setattr(module, "UsbDeviceWorker", Worker)
        stop = asyncio.Event()
        task = asyncio.create_task(m.run(stop))
        for _ in range(500):
            if all(s.state.connected for s in m.slots):
                break
            await asyncio.sleep(0.01)
        assert all(s.state.connected for s in m.slots)
        await m.broadcast(Payload("activity", {"v": 1, "k": "activity", "run": 1}))
        for _ in range(100):
            if all(s.state.last_ack_at for s in m.slots[:3]):
                break
            await asyncio.sleep(0.01)
        assert all(s.state.last_ack_at for s in m.slots[:3])
        await asyncio.wait_for(unanswered.wait(), timeout=1)
        assert m.slots[3].state.last_ack_at is None
        started = time.monotonic()
        stop.set()
        await task
        assert time.monotonic() - started < 2 and all(c.closed for c in channels)

    asyncio.run(run())


def test_maintenance_pause_waits_for_cancelled_native_probe_cleanup():
    started, release = threading.Event(), threading.Event()
    fake = FakeSerial()

    def opening():
        started.set()
        release.wait(2)
        fake.opened = True

    fake.open = opening

    async def run():
        discovery = UsbDiscovery(channel_factory=lambda port: SerialChannel(port, factory=lambda: fake))
        probe = asyncio.create_task(discovery._probe(UsbCandidate("pause-native", "instance")))
        while not started.is_set():
            await asyncio.sleep(.01)
        pause = asyncio.create_task(discovery.pause("pause-native", ID, "instance"))
        await asyncio.sleep(.03)
        assert not pause.done()
        release.set()
        await asyncio.wait_for(pause, 1)
        assert probe.done() and fake.closed
        # The port can immediately be reopened after the pause grant.
        peer = SerialChannel("pause-native", factory=FakeSerial)
        await peer.open()
        await peer.close()

    try:
        asyncio.run(run())
    finally:
        release.set()
