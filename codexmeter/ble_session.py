"""Negotiated BLE wire-v1 adapter. Legacy BLE stays on its characterized path."""

from __future__ import annotations
import asyncio
import struct
import time
from .companion_session import CompanionSession
from .transport_types import Endpoint, TransportError
from .companion_protocol import NegotiatedIdentity, ProtocolError
from .settings import RX_CHAR_UUID, TX_CHAR_UUID


class FragmentDecoder:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.buffer = bytearray()
        self.total = 0
        self.started = 0

    def feed(self, fragment):
        if not 6 <= len(fragment) <= 512 or fragment[0] != 0x1E:
            self.buffer.clear()
            self.total = 0
            return None
        total, offset = struct.unpack(">HH", fragment[1:5])
        data = bytes(fragment[5:])
        now = self.clock()
        if offset == 0:
            self.buffer.clear()
            self.total = total
            self.started = now
        if (
            not 1 <= total <= 640
            or total != self.total
            or offset != len(self.buffer)
            or now - self.started >= 2
            or offset + len(data) > total
        ):
            self.buffer.clear()
            self.total = 0
            return None
        self.buffer.extend(data)
        if len(self.buffer) == total:
            result = bytes(self.buffer)
            self.buffer.clear()
            self.total = 0
            return result
        return None


class BleWireChannel:
    def __init__(self, client, identity, *, write_timeout=2):
        self.client = client
        self.identity = identity
        self.write_timeout = min(2, write_timeout)
        self.lines = asyncio.Queue(maxsize=16)
        self.decoder = FragmentDecoder()
        self.closed = False
        self.lock = asyncio.Lock()
        self.failure = None

    async def open(self):
        await asyncio.wait_for(self.client.start_notify(TX_CHAR_UUID, self._notify), 2)
        return self

    def _notify(self, _char, data):
        if self.closed:
            return
        frame = self.decoder.feed(data)
        if frame is None:
            return
        if self.lines.full():
            self.failure = TransportError("BLE reply queue overflow")
            return
        self.lines.put_nowait(frame)

    async def line(self, timeout=1):
        if self.failure:
            raise self.failure
        return await asyncio.wait_for(self.lines.get(), timeout)

    async def write(self, frame):
        if self.closed:
            raise TransportError("BLE wire closed")
        if frame == b"identity\n":
            import json

            self.lines.put_nowait(
                b"IDENTITY "
                + json.dumps(self.identity.raw, separators=(",", ":")).encode()
            )
            return
        logical = frame.removesuffix(b"\n")
        if not 1 <= len(logical) <= 640:
            raise ProtocolError("BLE logical frame bounds")
        capacity = min(512, max(0, getattr(self.client, "mtu_size", 23) - 3)) - 5
        if capacity < 1:
            raise TransportError("BLE MTU cannot carry fragment")
        async with self.lock:

            async def train():
                for offset in range(0, len(logical), capacity):
                    fragment = (
                        b"\x1e"
                        + struct.pack(">HH", len(logical), offset)
                        + logical[offset : offset + capacity]
                    )
                    await self.client.write_gatt_char(
                        RX_CHAR_UUID, fragment, response=False
                    )

            await asyncio.wait_for(train(), self.write_timeout)

    async def close(self):
        self.closed = True
        self.decoder.buffer.clear()
        self.decoder.total = 0
        # The owning BleTransport disconnects. Late notifications are fenced here.


class BleSession(CompanionSession):
    transport = "bluetooth"

    def __init__(self, client, identity, host_id):
        parsed = NegotiatedIdentity.parse(
            b"IDENTITY "
            + __import__("json").dumps(identity.raw, separators=(",", ":")).encode()
        )
        super().__init__(
            parsed,
            host_id,
            endpoint=Endpoint("bluetooth", parsed.device_id, str(getattr(client, "address", "ble"))),
            channel_factory=lambda: BleWireChannel(client, parsed),
            request_timeout=2,
        )
