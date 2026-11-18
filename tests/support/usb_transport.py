"""Shared usb transport fixtures."""
import asyncio
import json
import time
from codexmeter.usb_transport import UsbDiscovered, UsbCandidate, UsbSession
from codexmeter.companion_protocol import NegotiatedIdentity

B = "0011223344556677"

ID = "codexmeter-001122334455"

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

IDENTITY = {
    "device_id": ID,
    "short_id": "001122",
    "name": "CodexMeter-001122",
    "usb": 1,
    "app": 1,
    "boot": B,
    "fw": "test",
    "model": "waveshare_c6_amoled_216",
    "capabilities": ["screen", "brightness", "rotation"],
}

def discovered(port="COMTEST"):
    identity = NegotiatedIdentity.parse(b"IDENTITY " + json.dumps(IDENTITY).encode())
    return UsbDiscovered(UsbCandidate(port, port), identity, time.monotonic())

class FakeChannel:
    def __init__(self, port):
        self.port = port
        self.lines = asyncio.Queue()
        self.writes = []
        self.closed = False
        self.drop = 0
        self.wrong = False
        self.rejected = None
        self.changed = False

    async def open(self):
        return self

    async def close(self):
        self.closed = True

    async def line(self, timeout=1):
        return await asyncio.wait_for(self.lines.get(), timeout)

    async def write(self, frame):
        self.writes.append(frame)
        if frame == b"identity\n":
            data = (
                {**IDENTITY, "device_id": "codexmeter-ffffffffffff"}
                if self.changed
                else IDENTITY
            )
            await self.lines.put(b"IDENTITY " + json.dumps(data).encode())
            return
        if frame.startswith(b"CM1 DATA "):
            _, _, boot, token, seq, rev, app = frame.split(b" ", 6)
            reply = {
                "boot": boot.decode(),
                "token": token.decode(),
                "seq": int(seq),
                "ok": self.rejected is None,
            }
            if self.rejected:
                reply["err"] = self.rejected
            if self.drop:
                self.drop -= 1
                return
            if self.wrong:
                await self.lines.put(
                    b"CM1 " + json.dumps({**reply, "seq": int(seq) + 1}).encode()
                )
                await self.lines.put(
                    b"CM1 " + json.dumps({**reply, "token": "c" * 32}).encode()
                )
        else:
            data = json.loads(frame[4:])
            reply = {"boot": B, "q": data["q"], "token": data["token"], "ok": True}
            if data["op"] in ("claim", "state"):
                reply["state"] = STATE
        await self.lines.put(b"CM1 " + json.dumps(reply).encode())
