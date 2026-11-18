"""Shared ble session fixtures."""
import json
import struct
from codexmeter.ble_session import FragmentDecoder
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
