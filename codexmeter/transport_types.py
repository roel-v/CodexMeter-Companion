"""Bounded transport contract; importing this module requires no hardware backend."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable
from .payloads import Payload
from .companion_protocol import NegotiatedIdentity


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
    generation: str
    identity: NegotiatedIdentity
    state: dict
    failure: Exception | None
    async def open(self, *, maintenance=False): ...
    async def send(self, payload: Payload, *, expected_boot=None,
                   expected_revision=None, intent_deadline=None, on_dispatch=None) -> DeliveryResult: ...
    async def read_state(self) -> dict: ...
    async def close(self, *, release=True) -> None: ...


class TransportError(RuntimeError):
    pass


class UnknownDelivery(TransportError):
    pass


class WireChannel(Protocol):
    async def open(self): ...
    async def line(self, timeout: float) -> bytes: ...
    async def write(self, frame: bytes): ...
    async def close(self): ...


class MaintenanceSession(Protocol):
    @property
    def lifecycle(self) -> str: ...
    async def try_maintenance(self) -> dict | None: ...


@runtime_checkable
class WorkerSession(MaintenanceSession, Protocol):
    """Coordinator/manager surface; excludes wire framing and delivery methods."""
    identity: NegotiatedIdentity
    failure: Exception | None
    async def read_state(self) -> dict: ...


@runtime_checkable
class ConnectionWorker(Protocol):
    @property
    def session(self) -> WorkerSession | None: ...
    async def run(self, stop) -> None: ...
