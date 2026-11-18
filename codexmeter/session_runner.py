"""Negotiated delivery lifecycle shared by physical transport adapters."""
import asyncio
import time

from .delivery import negotiated_replay
from .delivery_pump import DeliveryPump


async def run_session(session, state, queue, stop, *, transport,
                      on_open=None, on_reconciled=None, available=lambda: True):
    try:
        await session.open()
        if on_open:
            on_open()
        state.connected = True
        state.transport = transport
        state.generation = session.generation
        state.observed_device_id = session.identity.device_id
        state.last_connected_at = time.monotonic()
        state.last_error = None
        state.device_state = {**session.state, "boot": session.identity.boot}
        while not queue.empty():
            queue.get_nowait()
        replay = negotiated_replay(state, same_host=session.state['same_host'])
        if on_reconciled:
            await on_reconciled(state, session)
        delivery = DeliveryPump(state, session)
        for payload in replay:
            await delivery.deliver(payload)
        while available() and not stop.is_set() and not session.failure:
            try:
                payload = await asyncio.wait_for(queue.get(), .1)
            except TimeoutError:
                continue
            if not stop.is_set():
                await delivery.deliver(payload)
        if session.failure:
            raise session.failure
    finally:
        state.connected = False
        state.last_disconnected_at = time.monotonic()
        await session.close()
