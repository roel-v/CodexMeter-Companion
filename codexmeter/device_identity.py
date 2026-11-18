"""Transport-independent display identity and validation."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from .device_metadata import DeviceMetadata, MAX_IDENTITY_BYTES
from .settings import DEVICE_NAME


class DeviceIdentityError(RuntimeError):
    """Raised when a connected peripheral has an invalid or unexpected identity."""


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    short_id: str
    name: str
    metadata: DeviceMetadata = DeviceMetadata()
    raw: dict | None = field(default=None, compare=False)

    @classmethod
    def from_bytes(cls, raw: bytes | bytearray) -> "DeviceIdentity":
        if len(raw) > MAX_IDENTITY_BYTES:
            raise DeviceIdentityError("Device identity exceeds 512 bytes")
        try:
            data = json.loads(bytes(raw).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise DeviceIdentityError("Device identity is not valid JSON") from exc
        if not isinstance(data, dict):
            raise DeviceIdentityError("Device identity must be a JSON object")
        device_id = data.get("device_id")
        short_id = data.get("short_id")
        name = data.get("name")
        if not all(isinstance(value, str) and value for value in (device_id, short_id, name)):
            raise DeviceIdentityError("Device identity is missing required fields")
        normalized_device_id = str(device_id).lower()
        normalized_short_id = str(short_id).upper()
        normalized_name = str(name)
        if not re.fullmatch(r"codexmeter-[0-9a-f]{12}", normalized_device_id):
            raise DeviceIdentityError("Device identity device id has an invalid format")
        if not re.fullmatch(r"[0-9A-F]{6}", normalized_short_id):
            raise DeviceIdentityError("Device identity short id has an invalid format")
        device_short_id = normalized_device_id.removeprefix("codexmeter-")[:6].upper()
        if device_short_id != normalized_short_id:
            raise DeviceIdentityError("Device identity device id does not match its short id")
        if normalized_name != f"{DEVICE_NAME}-{normalized_short_id}":
            raise DeviceIdentityError("Device identity name does not match its short id")
        try:
            metadata = DeviceMetadata.from_json(data)
        except ValueError as exc:
            raise DeviceIdentityError(str(exc)) from exc
        return cls(normalized_device_id, normalized_short_id, normalized_name, metadata, data)
