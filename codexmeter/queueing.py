"""Payload queue helpers shared by daemon and device workers."""

from __future__ import annotations

import asyncio

from .payloads import Payload

COALESCED_PAYLOAD_KINDS = {"usage", "activity", "control"}


def coalescing_key(payload):
    if payload.kind != "control":
        return (payload.kind,)
    command = payload.data.get("cmd")
    policy = command == "screen" and payload.data.get("why") in ("lock", "unlock", "connection_restored")
    return ("control", command, "policy" if policy else "manual")


async def put_latest(queue: "asyncio.Queue[Payload]", payload: Payload) -> list[Payload]:
    removed = []
    if payload.kind in COALESCED_PAYLOAD_KINDS:
        kept: list[Payload] = []
        while True:
            try:
                existing = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if coalescing_key(existing) != coalescing_key(payload):
                kept.append(existing)
            else:
                removed.append(existing)
        for existing in kept:
            await queue.put(existing)

    if queue.full():
        removed.extend(await _drop_oldest_replaceable(queue))
    await queue.put(payload)
    return removed


async def _drop_oldest_replaceable(queue: "asyncio.Queue[Payload]") -> list[Payload]:
    removed = []
    kept: list[Payload] = []
    dropped = False
    while not queue.empty():
        existing = queue.get_nowait()
        if not dropped and existing.kind != "alert":
            dropped = True
            removed.append(existing)
            continue
        kept.append(existing)
    if not dropped and kept:
        removed.append(kept.pop(0))
    for existing in kept:
        await queue.put(existing)
    return removed
