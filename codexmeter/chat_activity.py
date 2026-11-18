"""Read-only observer of the Windows Codex desktop chat stream.

This private, versioned IPC is deliberately isolated here. It only initializes
an observer and follows chat state; it never owns a chat, marks it read, or sends
agent requests. Transcript values are skipped in bounded chunks before metadata is decoded.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from pathlib import Path
import struct
import time
import uuid

from .payloads import Payload, build_activity_payload
from .compatibility import ContractError, report_error, SupersededObservation
from .compatibility_readers import read_unread_snapshot
from .compatibility_readers import read_roots, validate_state

FIELDS = {"threadRuntimeStatus", "hasUnreadTurn", "parentThreadId", "source"}
from .ipc_projection import CHUNK, receive_metadata
WAIT_FLAGS = {"waitingOnApproval", "waitingOnUserInput"}
from .compatibility_readers import SUPPORTED_STREAM_VERSIONS


class UnsupportedStreamVersion(ContractError):
    """The private stream changed; do not interpret unknown state semantics."""


def apply_stream_change(states: dict, tid: str, version: int, change: dict) -> None:
    if type(version) is not int or version not in SUPPORTED_STREAM_VERSIONS:
        raise UnsupportedStreamVersion("unsupported_version", "version", definitive=True, version=version)
    try:
        apply_change(states, tid, change)
        validate_state(states[tid]["state"])
    except (KeyError, TypeError, IndexError):
        raise ContractError(field="patch") from None


def apply_change(states: dict, tid: str, change: dict) -> None:
    if change["type"] == "snapshot":
        raw = change["conversationState"]
        states[tid] = {"revision": change["revision"],
                       "state": {k: copy.deepcopy(raw[k]) for k in FIELDS if k in raw}}
        return
    if change["type"] != "patches" or tid not in states:
        raise ValueError("Chat stream needs a fresh snapshot")
    entry = states[tid]
    if entry["revision"] != change["baseRevision"]:
        raise ValueError("Chat stream revision gap")
    for patch in change["patches"]:
        path = patch["path"]
        if not path:
            raise ValueError("Unexpected root replacement")
        if path[0] not in FIELDS:
            continue
        target = entry["state"]
        for key in path[:-1]:
            target = target[key]
        key = path[-1]
        op = patch["op"]
        if op == "remove":
            if isinstance(target, list):
                target.pop(key)
            else:
                target.pop(key, None)
        elif op in ("add", "replace"):
            value = copy.deepcopy(patch["value"])
            if isinstance(target, list) and op == "add":
                target.insert(key, value)
            else:
                target[key] = value
        else:
            raise ValueError("Unsupported chat patch")
    entry["revision"] = change["revision"]


def coverage_complete(roots, states, coverage, now):
    return all(coverage.get(tid, (0, None))[0] > now and
               (coverage[tid][1] is None or states.get(tid, {}).get("owner") == coverage[tid][1])
               for tid in roots)


def count_chats(roots: set[str], completed_unread: set[str], states: dict) -> tuple[int, int, int]:
    running = waiting = 0
    done = set(completed_unread) & roots
    for tid, entry in states.items():
        if tid not in roots:
            continue
        state = entry["state"]
        if state.get("parentThreadId") or state.get("source") not in ("cli", "vscode"):
            done.discard(tid)
            continue
        status = state.get("threadRuntimeStatus") or {}
        if status.get("type") == "active":
            if WAIT_FLAGS.intersection(status.get("activeFlags", [])):
                waiting += 1
            else:
                running += 1
            done.discard(tid)
        elif state.get("hasUnreadTurn") is False:
            done.discard(tid)
    return running, waiting, len(done)


class ChatActivity:
    def __init__(self, home: Path | None = None, monitor=None):
        self.monitor = monitor
        self.desktop_running = None
        self.done_available = False
        self.home = home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        self.status = {"available": False, "scope": "local non-archived Codex chats",
                       "reason": "connecting"}
        self.payload = self._payload(False)

    def _payload(self, available: bool, counts=(0, 0, 0)) -> Payload:
        payload = build_activity_payload(counts[0])
        payload.data.update(wait=counts[1] if available else None,
                            done=counts[2] if available and self.done_available else None,
                            chats=available)
        payload.data["run"] = counts[0] if available else None
        if available:
            self.status["reason"] = None
        self.status.update(available=available, running=counts[0] if available else None,
                           waiting=counts[1] if available else None,
                           done=counts[2] if available and self.done_available else None)
        return payload

    async def run(self, sink, stop_event):
        last_failure = None
        last_logged = 0.0
        while not stop_event.is_set():
            observation = self.monitor.reader(("stream", "inventory", "unread")) if self.monitor else None
            try:
                await self._observe(sink, stop_event, observation)
            except SupersededObservation:
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if observation:
                    try:
                        observation.check()
                    except SupersededObservation:
                        return
                # An incompatible private protocol must never take down BLE,
                # quota sync, or the tray. Cancellation is handled above.
                # Record code locations only: exception messages/locals may contain chat text.
                import traceback
                locations = [(Path(f.filename).name, f.name, f.lineno)
                             for f in traceback.extract_tb(exc.__traceback__)]
                report_error(observation, "stream", exc, eligible=self.desktop_running is not False)
                if self.monitor and self.desktop_running is False:
                    for component in ("stream", "inventory", "unread"):
                        self.monitor.observe(component, "unavailable", "closed", eligible=False)
                reason = ("unsupported_stream_version" if isinstance(exc, UnsupportedStreamVersion)
                          else "observer_error")
                self.status["reason"] = reason
                failure = (type(exc).__name__, locations)
                now = time.monotonic()
                if failure != last_failure or now - last_logged >= 300:
                    logging.warning("Codex chat observer reconnecting: %s reason=%s locations=%s",
                                    type(exc).__name__, reason, locations)
                    last_failure, last_logged = failure, now
            self.payload = self._payload(False)
            await sink(self.payload)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5)
            except TimeoutError:
                pass

    async def _observe(self, sink, stop_event, observation=None):
        monitor = observation or (self.monitor.reader(("stream", "inventory", "unread")) if self.monitor else None)
        def check():
            if monitor:
                monitor.check()
        reader = asyncio.StreamReader(limit=CHUNK)
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await asyncio.get_running_loop().create_pipe_connection(
            lambda: protocol, r"\\.\pipe\codex-ipc")

        def send(message):
            raw = json.dumps(message, separators=(",", ":")).encode()
            transport.write(struct.pack("<I", len(raw)) + raw)

        async def receive():
            return await receive_metadata(reader)

        pending = None
        try:
            request = str(uuid.uuid4())
            send(dict(type="request", requestId=request, version=0, method="initialize",
                      params={"clientType": "codexmeter"}))
            async with asyncio.timeout(5):
                while True:
                    message = await receive()
                    check()
                    if message.get("requestId") == request:
                        client = message["result"]["clientId"]
                        break
            states = {}
            owners = set()
            subscribed = set()
            roots, done = set(), set()
            discoveries = {}
            coverage = {}
            evidence_changed = False
            next_inventory = 0
            ready_at = time.monotonic() + 3
            pending = asyncio.create_task(receive())
            while not stop_event.is_set():
                now = time.monotonic()
                if now >= next_inventory:
                    try:
                        roots = await asyncio.to_thread(read_roots, self.home)
                        check()
                        if monitor:
                            monitor.observe("inventory")
                            if not roots:
                                monitor.observe("stream")
                    except SupersededObservation:
                        raise
                    except Exception as exc:
                        check()
                        report_error(monitor, "inventory", exc)
                        raise
                    try:
                        done, context = await asyncio.to_thread(read_unread_snapshot, self.home, roots)
                        check()
                        if monitor:
                            monitor.bind("unread", context)
                        self.done_available = True
                        if monitor:
                            monitor.observe("unread")
                            self.done_available = monitor.records["unread"].state == "compatible"
                    except SupersededObservation:
                        raise
                    except Exception as exc:
                        check()
                        done = set()
                        self.done_available = False
                        if isinstance(exc, LookupError) and not isinstance(exc, ContractError):
                            if monitor:
                                monitor.observe("unread", "unavailable", "ambiguous_account")
                        else:
                            report_error(monitor, "unread", exc)
                    for tid in subscribed ^ roots:
                        send(dict(type="broadcast", method="thread-stream-following-changed",
                                  version=1, sourceClientId=client,
                                  params=dict(conversationId=tid, hostId="local", following=tid in roots)))
                    for tid in subscribed - roots:
                        states.pop(tid, None)
                    subscribed = roots
                    next_inventory = now + 5

                # Read-only owner discovery supplies explicit negative coverage for idle/unloaded chats.
                # Bounded concurrency; no transcript or thread-start/read request is sent.
                for rid, (tid, deadline) in list(discoveries.items()):
                    if now > deadline:
                        discoveries.pop(rid)
                        coverage.pop(tid, None)
                queued = {tid for tid, _ in discoveries.values()}
                for tid in roots:
                    if len(discoveries) >= 16:
                        break
                    if tid in queued or coverage.get(tid, (0, None))[0] > now + 10:
                        continue
                    rid = str(uuid.uuid4())
                    discoveries[rid] = (tid, now + 10)
                    send(dict(type="request", requestId=rid, sourceClientId=client, version=1,
                              method="thread-owner-discovery", timeoutMs=5000,
                              params=dict(hostId="local", conversationId=tid)))
                finished, _ = await asyncio.wait({pending}, timeout=1)
                check()
                discovery = None
                if finished:
                    message = pending.result()
                    pending = asyncio.create_task(receive())
                    method = message.get("method")
                    discovery = discoveries.pop(message.get("requestId"), None)
                    if discovery:
                        evidence_changed = True
                        tid, _ = discovery
                        if message.get("resultType") == "error" and message.get("error") == "no-client-found":
                            coverage[tid] = (now + 60, None)
                            states.pop(tid, None)
                        elif message.get("resultType") == "success" and isinstance(message.get("handledByClientId"), str):
                            coverage[tid] = (now + 60, message["handledByClientId"])
                        else:
                            raise ContractError(field="coverage")
                    if message.get("type") == "client-discovery-request":
                        send(dict(type="client-discovery-response", requestId=message["requestId"],
                                  response={"canHandle": False}))
                    elif method == "ipc-connection-reset":
                        raise ValueError("Codex owner connection reset")
                    elif method == "thread-stream-following-status-requested":
                        params = message["params"]
                        if params.get("hostId") == "local" and params.get("conversationId") in roots:
                            send(dict(type="broadcast", method="thread-stream-following-changed",
                                      version=1, sourceClientId=client,
                                      targetClientIds=[message["sourceClientId"]],
                                      params={**params, "following": True}))
                    elif method == "client-status-changed":
                        params = message["params"]
                        if params.get("status") == "disconnected" and params.get("clientId") in owners:
                            raise ValueError("Codex chat owner disconnected")
                    elif method == "thread-stream-state-changed":
                        params = message["params"]
                        tid = params["conversationId"]
                        if params.get("hostId") == "local" and tid in roots:
                            owner = message.get("sourceClientId")
                            if not isinstance(owner, str):
                                raise ContractError(field="coverage")
                            previous_owner = states.get(tid, {}).get("owner")
                            if previous_owner is not None and previous_owner != owner:
                                states.pop(tid, None)
                            if tid in coverage and coverage[tid][1] != owner:
                                coverage.pop(tid)
                            apply_stream_change(states, tid, message.get("version"), params["change"])
                            states[tid]["owner"] = owner
                            owners.add(message.get("sourceClientId"))
                            evidence_changed = True

                    # Drain queued patches before publishing; text deltas can be frequent.
                    if now < ready_at:
                        continue
                if now >= ready_at:
                    # Counts are complete only when every subscribed root has supplied metadata.
                    complete = coverage_complete(roots, states, coverage, now)
                    self.status["coverage"] = {"roots": len(roots), "snapshots": len(states),
                                               "verified": sum(tid in coverage for tid in roots)}
                    # Discovery is fresh source evidence, never a timer-generated success.
                    if monitor and complete and evidence_changed:
                        monitor.observe("stream")
                        evidence_changed = False
                    if monitor and not complete:
                        monitor.observe("stream", "unavailable", "incomplete")
                    stream_ok = complete and (monitor is None or
                        monitor.records["stream"].state == "compatible")
                    self.payload = self._payload(stream_ok, count_chats(roots, done, states))
                    await sink(self.payload)
                    ready_at = now + 2
        finally:
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            transport.close()
