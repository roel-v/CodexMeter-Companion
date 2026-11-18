import asyncio
import json
import struct
import pytest
from codexmeter.ble_session import FragmentDecoder, BleSession
from codexmeter.ble import BleIdentity
from codexmeter.payloads import Payload
from codexmeter.device_metadata import DeviceMetadata
from codexmeter.settings import TX_CHAR_UUID

B = "0011223344556677"
H = "a" * 32
STATE = {
    "same_host": True,
    "rev": 1,
    "page": 0,
    "brightness": 50,
    "rotation": 0,
    "auto_rotation": False,
    "manual_on": True,
    "policy_on": True,
    "screen_on": True,
}
RAW = {
    "device_id": "codexmeter-001122334455",
    "short_id": "001122",
    "name": "CodexMeter-001122",
    "usb": 1,
    "app": 1,
    "ble_owner": 1,
    "boot": B,
    "fw": "test",
    "model": "waveshare_c6_amoled_216",
    "capabilities": ["screen", "rotation", "brightness"],
}


class Peer:
    mtu_size = 23
    address = "ble-test"

    def __init__(self):
        self.callback = None
        self.decoder = FragmentDecoder()
        self.frames = []
        self.fragments = []
        self.drop = 0

    async def start_notify(self, uuid, callback):
        assert uuid == TX_CHAR_UUID
        self.callback = callback

    async def write_gatt_char(self, uuid, fragment, response):
        assert response is False and len(fragment) <= 20
        self.fragments.append(fragment)
        frame = self.decoder.feed(fragment)
        if frame is None:
            return
        self.frames.append(frame)
        if frame.startswith(b"CM1 DATA "):
            fields = frame.split(b" ", 6)
            reply = {
                "boot": B,
                "token": fields[3].decode(),
                "seq": int(fields[4]),
                "ok": True,
            }
            if self.drop:
                self.drop -= 1
                return
        else:
            data = json.loads(frame[4:])
            reply = {"boot": B, "q": data["q"], "token": data["token"], "ok": True}
            if data["op"] in ("claim", "state"):
                reply["state"] = STATE
        encoded = b"CM1 " + json.dumps(reply, separators=(",", ":")).encode()
        for offset in range(0, len(encoded), 15):
            self.callback(
                None,
                b"\x1e"
                + struct.pack(">HH", len(encoded), offset)
                + encoded[offset : offset + 15],
            )


def test_ble_minimum_mtu_full_payload_requires_matching_ack():
    async def run():
        peer = Peer()
        identity = BleIdentity(
            RAW["device_id"], RAW["short_id"], RAW["name"], DeviceMetadata(), RAW
        )
        session = BleSession(peer, identity, H)
        await session.open()
        session.timeout = 0.08
        payload = {"v": 1, "k": "usage", "padding": ""}
        payload["padding"] = "x" * (
            512 - len(json.dumps(payload, separators=(",", ":")).encode())
        )
        item = Payload("usage", payload)
        assert len(item.to_json_bytes()) == 512
        peer.drop = 1
        result = await session.send(item)
        assert result.transport == "bluetooth" and result.outcome == "accepted"
        frames = [f for f in peer.frames if f.startswith(b"CM1 DATA")]
        assert len(frames) == 2 and frames[0] == frames[1]
        assert frames[0].endswith(item.to_json_bytes())
        await session.close()
        old_count = session.channel.lines.qsize()
        session.channel._notify(None, b"\x1e\x00\x01\x00\x00x")
        assert session.channel.lines.qsize() == old_count

    asyncio.run(run())


def test_fragment_gap_timeout_and_new_zero_recovery():
    now = [0]
    d = FragmentDecoder(clock=lambda: now[0])
    assert d.feed(b"\x1e\x00\x04\x00\x00ab") is None
    assert d.feed(b"\x1e\x00\x04\x00\x03cd") is None
    assert d.feed(b"\x1e\x00\x04\x00\x02cd") is None
    assert d.feed(b"\x1e\x00\x04\x00\x00ab") is None
    now[0] = 2.1
    assert d.feed(b"\x1e\x00\x04\x00\x02cd") is None
    assert d.feed(b"\x1e\x00\x02\x00\x00ok") == b"ok"


def test_ble_queued_writes_alone_are_not_delivery():
    async def run():
        peer = Peer()
        s = BleSession(
            peer,
            BleIdentity(RAW["device_id"], RAW["short_id"], RAW["name"], raw=RAW),
            H,
        )
        await s.open()
        s.timeout = 0.08
        peer.drop = 2
        result = await s.send(Payload("activity", {"v": 1, "k": "activity", "run": 0}))
        assert result.outcome == "unknown" and s.channel.closed
        assert not s._waiters

    asyncio.run(run())


def test_tokenless_owner_notice_is_connection_scoped_and_old_callback_fenced():
    async def run():
        peer = Peer()
        identity = BleIdentity(RAW["device_id"], RAW["short_id"], RAW["name"], raw=RAW)
        first = BleSession(peer, identity, H)
        await first.open()
        old_callback = peer.callback
        await first.close()
        second = BleSession(peer, identity, H)
        await second.open()
        notice = (
            b"CM1 "
            + json.dumps(
                {"op": "owner", "boot": B, "err": "busy_usb"}, separators=(",", ":")
            ).encode()
        )

        def emit(callback):
            for offset in range(0, len(notice), 15):
                callback(
                    None,
                    b"\x1e"
                    + struct.pack(">HH", len(notice), offset)
                    + notice[offset : offset + 15],
                )

        emit(old_callback)
        await asyncio.sleep(0.03)
        assert second.failure is None
        emit(peer.callback)
        for _ in range(100):
            if second.failure:
                break
            await asyncio.sleep(0.01)
        assert str(second.failure) == "busy_usb"
        await second.close()

    asyncio.run(run())
