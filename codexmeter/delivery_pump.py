"""Shared replay and delivery semantics for negotiated display sessions."""
import time
from .transport_types import TransportSession, TransportError
from .delivery import remember_accepted, should_send, accepted_alert, prune_alerts
from .payloads import Payload


class DeliveryPump:
    def __init__(self, state, session: TransportSession):
        self.state = state
        self.session = session

    async def deliver(self, payload):
        state = self.state
        if payload.kind in ("usage", "activity"):
            if (
                time.monotonic() - state.observed_at.get(payload.kind, float("-inf"))
                >= 300
            ):
                return
            if not should_send(payload, state):
                return
        if payload.kind == "alert":
            prune_alerts(state)
            if not any(
                p.data.get("id") == payload.data.get("id") for _, p in state.alerts
            ):
                return
        expected = state.explicit_intents.get(id(payload))
        data = payload.data
        if payload.kind == "control" and data.get("cmd") == "screen":
            why = data.get("why")
            if why == "connection_restored":
                return
        state.last_write_at = time.monotonic()
        result = await self.session.send(
            payload,
            expected_boot=expected[0] if expected else None,
            expected_revision=expected[1] if expected else None,
        )
        if result.outcome == "unknown":
            raise TransportError(result.reason)
        if result.outcome == "rejected":
            state.explicit_intents.pop(id(payload), None)
            state.explicit_payloads.pop(id(payload), None)
            state.last_error = result.reason
            if result.reason == "conflict":
                state.device_state = {
                    **await self.session.read_state(),
                    "boot": self.session.identity.boot,
                }
            return
        state.explicit_intents.pop(id(payload), None)
        state.explicit_payloads.pop(id(payload), None)
        remember_accepted(payload, state)
        if payload.kind == "alert":
            accepted_alert(payload, state)
        state.last_ack_at = time.monotonic()
        state.consecutive_failures = 0
        state.last_error = None
        if payload.kind == "control":
            state.device_state = {
                **await self.session.read_state(),
                "boot": self.session.identity.boot,
            }
