"""Pure, bounded USB wire-v1 codec. No serial or Bluetooth imports."""

from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass
from .device_metadata import DeviceMetadata

MAX_FRAME = 640
MAX_APPLICATION = 512
UINT32 = 0xFFFFFFFF
FULL_ID = re.compile(r"codexmeter-[0-9a-f]{12}\Z")
BOOT = re.compile(r"[0-9a-f]{16}\Z")
TOKEN = re.compile(r"[0-9a-f]{32}\Z")
ERRORS = {
    "bad_request",
    "bad_boot",
    "busy_usb",
    "busy_ble",
    "busy_maintenance",
    "stale_session",
    "out_of_order",
    "conflict",
    "unsupported",
}


class ProtocolError(ValueError):
    pass


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ProtocolError("duplicate protocol key")
        result[key] = value
    return result


def object_json(raw: bytes) -> dict:
    try:
        if len(raw) > MAX_FRAME:
            raise ProtocolError("protocol size limit")
        if any(b < 32 or b == 127 for b in raw):
            raise ProtocolError("raw control byte")
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ProtocolError("nonfinite JSON")
            ),
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProtocolError("invalid protocol JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("protocol object required")

    def depth(item, level=0):
        if level > 4:
            raise ProtocolError("protocol nesting limit")
        if isinstance(item, dict):
            for child in item.values():
                depth(child, level + 1)
        elif isinstance(item, list):
            for child in item:
                depth(child, level + 1)

    depth(value)
    return value


@dataclass(frozen=True)
class UsbIdentity:
    device_id: str
    short_id: str | None
    name: str | None
    boot: str
    metadata: DeviceMetadata
    raw: dict

    @classmethod
    def parse(cls, line: bytes):
        if len(line) > MAX_FRAME:
            raise ProtocolError("identity size limit")
        if not line.startswith(b"IDENTITY "):
            raise ProtocolError("identity prefix required")
        data = object_json(line[9:])
        if not isinstance(data.get("device_id"), str) or not FULL_ID.fullmatch(
            data["device_id"]
        ):
            raise ProtocolError("invalid full device identity")
        if (
            type(data.get("usb")) is not int
            or data["usb"] != 1
            or type(data.get("app")) is not int
            or data["app"] != 1
        ):
            raise ProtocolError("USB firmware upgrade required (wire/app v1)")
        if not isinstance(data.get("boot"), str) or not BOOT.fullmatch(data["boot"]):
            raise ProtocolError("invalid boot identity")
        if data.get("model") not in ("waveshare_c6_amoled_216", "spotpear_ball_v2"):
            raise ProtocolError("unsupported USB model")
        fw = data.get("fw")
        if (
            not isinstance(fw, str)
            or not 1 <= len(fw) <= 24
            or not fw.isascii()
            or any(ord(c) < 32 or ord(c) > 126 for c in fw)
        ):
            raise ProtocolError("invalid firmware version")
        caps = data.get("capabilities")
        if (
            not isinstance(caps, list)
            or any(not isinstance(c, str) for c in caps)
            or not {"brightness", "rotation", "screen"}.issubset(caps)
        ):
            raise ProtocolError("missing USB capabilities")
        for key in ("short_id", "name"):
            if key in data and (
                not isinstance(data[key], str) or not data[key] or len(data[key]) > 64
            ):
                raise ProtocolError("invalid identity label")
        metadata = DeviceMetadata.from_json(
            {**data, "firmware": fw, "protocol": data["app"]}
        )
        return cls(
            data["device_id"],
            data.get("short_id"),
            data.get("name"),
            data["boot"],
            metadata,
            data,
        )


def encode_control(op: str, q: int, boot: str, **fields) -> bytes:
    if type(q) is not int or not 1 <= q <= UINT32 or not BOOT.fullmatch(boot):
        raise ProtocolError("invalid request correlation")
    data = {"op": op, "q": q, "boot": boot, **fields}
    for key in ("host", "token"):
        if key in data and (
            not isinstance(data[key], str) or not TOKEN.fullmatch(data[key])
        ):
            raise ProtocolError("invalid ownership token")
    return _bound(
        b"CM1 "
        + json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def encode_data(
    boot: str, token: str, seq: int, revision: int | None, application: bytes
) -> bytes:
    if (
        not BOOT.fullmatch(boot)
        or not TOKEN.fullmatch(token)
        or type(seq) is not int
        or not 1 <= seq <= UINT32
    ):
        raise ProtocolError("invalid DATA correlation")
    if revision is not None and (
        type(revision) is not int or not 0 <= revision <= UINT32
    ):
        raise ProtocolError("invalid revision")
    if len(application) > MAX_APPLICATION:
        raise ProtocolError("application exceeds 512 bytes")
    object_json(application)
    rev = "-" if revision is None else str(revision)
    return _bound(f"CM1 DATA {boot} {token} {seq} {rev} ".encode("ascii") + application)


def _bound(raw):
    if len(raw) > MAX_FRAME:
        raise ProtocolError("frame exceeds 640 bytes")
    return raw + b"\n"


def parse_reply(line: bytes) -> dict | None:
    if len(line) > MAX_FRAME:
        raise ProtocolError("reply size limit")
    if not line.startswith(b"CM1 "):
        return None
    data = object_json(line[4:])
    if not isinstance(data.get("boot"), str) or not BOOT.fullmatch(data["boot"]):
        raise ProtocolError("invalid reply boot")
    if data.get("op") == "owner" and data.get("err") in (
        "busy_usb",
        "busy_maintenance",
    ):
        return data
    if type(data.get("ok")) is not bool:
        raise ProtocolError("missing reply outcome")
    if data["ok"] is False and data.get("err") not in ERRORS:
        raise ProtocolError("invalid reply rejection")
    if ("seq" in data) == ("q" in data):
        raise ProtocolError("ambiguous reply correlation")
    if data["ok"] and "err" in data:
        raise ProtocolError("contradictory reply outcome")
    correlation = "seq" if "seq" in data else "q"
    if type(data.get(correlation)) is not int or not 1 <= data[correlation] <= UINT32:
        raise ProtocolError("invalid reply correlation")
    if "token" in data and (
        not isinstance(data["token"], str) or not TOKEN.fullmatch(data["token"])
    ):
        raise ProtocolError("invalid reply token")
    return data


class LineDecoder:
    """One bounded line. Overflow/timeout discards through LF, including plausible suffixes."""

    def __init__(self, *, clock=time.monotonic, timeout=1.0):
        self.clock = clock
        self.timeout = timeout
        self.buffer = bytearray()
        self.started = None
        self.discard = False

    def feed(self, chunk: bytes) -> list[bytes]:
        now = self.clock()
        if self.started is not None and now - self.started >= self.timeout:
            self.buffer.clear()
            self.discard = True
            self.started = None
        lines = []
        for byte in chunk:
            if byte == 10:
                if not self.discard:
                    line = bytes(self.buffer)
                    if line.endswith(b"\r"):
                        line = line[:-1]
                    lines.append(line)
                self.buffer.clear()
                self.started = None
                self.discard = False
            elif not self.discard:
                if self.started is None:
                    self.started = now
                if len(self.buffer) >= MAX_FRAME:
                    self.buffer.clear()
                    self.discard = True
                    self.started = None
                else:
                    self.buffer.append(byte)
        return lines
