"""Negotiated ownership, correlation and delivery, independent of the wire backend."""
from __future__ import annotations
import asyncio
import contextlib
import secrets
import time
from typing import Callable
from .companion_protocol import (NegotiatedIdentity, ProtocolError, encode_control,
                                 encode_data, parse_reply, object_json, FULL_ID, UINT32)
from .transport_types import (DeliveryResult, Endpoint, WireChannel, TransportError, UnknownDelivery)
from .payloads import Payload


class IdentityIncompatible(ProtocolError):
    def __init__(self, reason, device_id):
        super().__init__(reason)
        self.device_id = device_id


async def read_identity(channel: WireChannel, timeout=1.0) -> NegotiatedIdentity:
    await channel.write(b"identity\n")
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        line = await channel.line(
            max(0.001, deadline - asyncio.get_running_loop().time())
        )
        if line.startswith(b"IDENTITY "):
            try:
                return NegotiatedIdentity.parse(line)
            except ProtocolError as exc:
                basic = object_json(line[9:])
                identity = basic.get("device_id")
                if isinstance(identity, str) and FULL_ID.fullmatch(identity):
                    raise IdentityIncompatible(str(exc), identity) from exc
                raise
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("Device identity timed out")


class CompanionSession:

    def __init__(
        self,
        identity: NegotiatedIdentity,
        host_id: str,
        *,
        endpoint: Endpoint,
        channel_factory: Callable[[], WireChannel],
        request_timeout=1.0,
        clock=time.monotonic,
    ):
        self.endpoint = endpoint
        self.transport = endpoint.transport
        self.host_id = host_id
        self.channel_factory = channel_factory
        self.timeout = request_timeout
        self.clock = clock
        self.generation = secrets.token_hex(16)
        self.token = self.generation
        self.identity = identity
        self.channel = None
        self._q = 0
        self._seq = 1
        self._waiters = {}
        self._reader = None
        self._heartbeat = None
        self._send_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._closing = False
        self._closed = False
        self._claimed = False
        self.state = {}
        self.failure = None
        self.last_ping = None

    async def open(self, *, maintenance=False):
        try:
            self.channel = self.channel_factory()
            await self.channel.open()
            identity = await read_identity(self.channel)
            if (
                identity.device_id != self.identity.device_id
                or identity.boot != self.identity.boot
            ):
                raise TransportError("Endpoint identity/boot changed; rediscovery required")
            self._reader = asyncio.create_task(self._read())
            reply = await self._control("maint" if maintenance else "claim", host=self.host_id, token=self.token)
            if reply["ok"] is not True:
                raise TransportError(reply["err"])
            if maintenance:
                return self
            self.state = self._valid_state(reply.get("state"))
            self._claimed = True
            self.last_ping = self.clock()
            self._heartbeat = asyncio.create_task(self._ping_loop())
            return self
        except BaseException:
            await self.close(release=False)
            raise

    @staticmethod
    def _valid_state(state):
        if not isinstance(state, dict):
            raise ProtocolError("state required")
        for key in (
            "same_host",
            "auto_rotation",
            "manual_on",
            "policy_on",
            "screen_on",
        ):
            if type(state.get(key)) is not bool:
                raise ProtocolError("invalid device state")
        for key, maximum in (("rev", UINT32), ("page", UINT32), ("brightness", 100)):
            if type(state.get(key)) is not int or not 0 <= state[key] <= maximum:
                raise ProtocolError("invalid device state")
        if (
            state["rev"] == 0
            or type(state.get("rotation")) is not int
            or state["rotation"] not in (0, 90, 180, 270)
        ):
            raise ProtocolError("invalid device state")
        return dict(state)

    def _fail(self, exc):
        self.failure = exc
        for future in list(self._waiters.values()):
            if not future.done():
                future.set_exception(exc)

    async def _read(self):
        try:
            while not self._closed:
                try:
                    line = await self.channel.line(0.1)
                except TimeoutError:
                    continue
                reply = parse_reply(line)
                if reply is None:
                    continue
                if reply["boot"] != self.identity.boot:
                    self._fail(TransportError("Session boot changed"))
                    return
                if reply.get("op") == "owner":
                    self._fail(TransportError(reply["err"]))
                    return
                key = ("seq", reply["seq"]) if "seq" in reply else ("q", reply["q"])
                future = self._waiters.get(key)
                if future is None or future.done():
                    continue
                if reply.get("token") != self.token:
                    continue
                future.set_result(reply)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)

    async def _exchange(self, key, frame, *, retry=False):
        if self._closed or self.failure:
            raise TransportError("Session unavailable") from self.failure
        future = asyncio.get_running_loop().create_future()
        if key in self._waiters:
            raise TransportError("duplicate Session waiter")
        self._waiters[key] = future
        try:
            for attempt in range(2 if retry else 1):
                await self.channel.write(frame)
                try:
                    return await asyncio.wait_for(asyncio.shield(future), self.timeout)
                except TimeoutError:
                    if not retry or attempt:
                        raise UnknownDelivery("Session reply deadline; outcome unknown")
        finally:
            self._waiters.pop(key, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def _control(self, op, **fields):
        self._q += 1
        if self._q > UINT32:
            raise TransportError("Session request IDs exhausted; reconnect")
        return await self._exchange(
            ("q", self._q), encode_control(op, self._q, self.identity.boot, **fields)
        )

    async def _ping_loop(self):
        due = self.clock() + 2
        misses = 0
        try:
            while not self._closed:
                await asyncio.sleep(max(0, due - self.clock()))
                due += 2
                try:
                    reply = await self._control("ping", token=self.token)
                    if not reply["ok"]:
                        raise TransportError(reply["err"])
                    misses = 0
                    self.last_ping = self.clock()
                except UnknownDelivery:
                    misses += 1
                    if misses >= 3:
                        raise TransportError("Session heartbeat lost")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)
            if self.channel:
                await self.channel.close()

    @contextlib.asynccontextmanager
    async def exclusive_delivery(self):
        """Fence new DATA writes while a caller quiesces and closes this session."""
        async with self._send_lock:
            yield

    @property
    def lifecycle(self):
        if self._closed:
            return "closed"
        if self._closing or self.failure:
            return "closing"
        return "ready" if self._claimed else "connecting"

    async def try_maintenance(self):
        """None means definitely unsent; exceptions after dispatch retain uncertainty.

        Lock order is DATA then lifecycle. Close never takes the DATA lock.
        The coordinator must fence only after these locks have been released.
        """
        async with self._send_lock:
            async with self._lifecycle_lock:
                if self.lifecycle != "ready":
                    return None
                return await self.maintenance()

    async def maintenance(self):
        reply = await self._control("maint", host=self.host_id, token=self.token)
        if not reply["ok"]:
            raise TransportError(reply["err"])
        self._claimed = False
        if self._heartbeat:
            self._heartbeat.cancel()
            await asyncio.gather(self._heartbeat, return_exceptions=True)
        return {"boot": self.identity.boot, "token": self.token, "port": self.endpoint.address}

    async def end_maintenance(self):
        reply = await self._control("maint_end", token=self.token)
        if not reply["ok"] and reply.get("err") != "stale_session":
            raise TransportError(reply["err"])

    async def read_state(self):
        reply = await self._control("state", token=self.token)
        if not reply["ok"]:
            raise TransportError(reply["err"])
        self.state = self._valid_state(reply.get("state"))
        return dict(self.state)

    async def send(
        self, payload: Payload, *, expected_boot=None, expected_revision=None, intent_deadline=None
    ) -> DeliveryResult:
        async with self._send_lock:
            if self._seq > UINT32:
                raise TransportError("Session sequence exhausted; reconnect")
            revision = None
            if payload.kind == "control":
                policy = payload.data.get("cmd") == "screen" and payload.data.get(
                    "why"
                ) in ("lock", "unlock")
                if not policy:
                    if intent_deadline is not None and self.clock() >= intent_deadline:
                        return DeliveryResult("rejected", self.transport, self.generation,
                                              None, "expired explicit intent")
                    if expected_boot != self.identity.boot or expected_revision is None:
                        return DeliveryResult(
                            "rejected",
                            self.transport,
                            self.generation,
                            None,
                            "stale explicit intent",
                        )
                    revision = expected_revision
            seq = self._seq
            frame = encode_data(
                self.identity.boot, self.token, seq, revision, payload.to_json_bytes()
            )
            try:
                reply = await self._exchange(("seq", seq), frame, retry=True)
            except UnknownDelivery as exc:
                self._fail(exc)
                await self.close(release=False)
                return DeliveryResult(
                    "unknown", self.transport, self.generation, seq, str(exc)
                )
            except asyncio.CancelledError:
                await self.close(release=False)
                raise
            if reply["ok"]:
                self._seq += 1
                return DeliveryResult("accepted", self.transport, self.generation, seq)
            error = reply["err"]
            if error in ("bad_request", "unsupported", "conflict"):
                self._seq += 1
            else:
                self._fail(TransportError(error))
            return DeliveryResult(
                "rejected", self.transport, self.generation, seq, error
            )

    async def close(self, *, release=True):
        self._closing = True
        async with self._lifecycle_lock:
            await self._close(release=release)

    async def _close(self, *, release=True):
        if self._closed:
            return
        try:
            if release and self._claimed and not self.failure:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(
                        self._control("release", token=self.token), 0.5
                    )
        finally:
            self._closed = True
            self._claimed = False
            self._fail(TransportError("Session closed"))
            current = asyncio.current_task()
            tasks = [
                t
                for t in (self._heartbeat, self._reader)
                if t is not None and t is not current
            ]
            for task in tasks:
                task.cancel()

            async def cleanup():
                if self.channel:
                    await self.channel.close()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            cleanup_task = asyncio.create_task(cleanup())
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await cleanup_task
                raise
