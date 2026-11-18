"""Bounded transport contract; importing this module requires no hardware backend."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Protocol
from .payloads import Payload


@dataclass(frozen=True)
class Endpoint:
    transport: Literal["usb", "bluetooth"]
    device_id: str
    address: str
    boot: str | None = None


@dataclass(frozen=True)
class DeliveryResult:
    outcome: Literal["accepted", "rejected", "unknown"]
    transport: str
    generation: str
    message_id: int | None = None
    reason: str | None = None


class TransportSession(Protocol):
    async def send(self, payload: Payload) -> DeliveryResult: ...
    async def read_state(self) -> dict: ...
    async def close(self) -> None: ...
