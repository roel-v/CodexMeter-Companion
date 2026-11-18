"""Shared replay and delivery semantics for negotiated display sessions."""
import time
from .transport_types import TransportSession, TransportError
from .delivery import EXPLICIT_INTENT_TTL_SEC, telemetry_fresh, remember_accepted, should_send, accepted_alert, prune_alerts, sweep_commands
from .payloads import Payload


class DeliveryPump:
    def __init__(self, state, session: TransportSession):
        self.state = state
        self.session = session

    async def deliver(self, payload):
        state = self.state
        sweep_commands(state)
        if payload.command_id and not state.commands.queued(payload):
            return
        if payload.kind in ("usage", "activity"):
            if not telemetry_fresh(payload, state):
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
        deadline = {"intent_deadline": expected[2] + EXPLICIT_INTENT_TTL_SEC} if expected else {}
        if payload.command_id:
            deadline['on_dispatch'] = lambda: state.commands.start(payload, self.session.generation)
        try:
            result = await self.session.send(
                payload, **deadline,
                expected_boot=expected[0] if expected else None,
                expected_revision=expected[1] if expected else None,
            )
        except BaseException:
            record = state.commands.records.get(payload.command_id)
            if record and record.status == 'sending':
                state.commands.finish(payload, 'unknown', 'Connection ended before acknowledgement',
                                      generation=self.session.generation)
                sweep_commands(state)
            raise
        if result.outcome == "unknown":
            state.commands.finish(payload, 'unknown', result.reason, generation=self.session.generation)
            sweep_commands(state)
            raise TransportError(result.reason)
        if result.outcome == "rejected":
            state.commands.finish(payload, 'expired' if result.reason == 'expired explicit intent' else 'rejected',
                                  result.reason, generation=self.session.generation)
            state.explicit_intents.pop(id(payload), None)
            state.explicit_payloads.pop(id(payload), None)
            state.last_error = result.reason
            if result.reason == "conflict":
                await self._readback(payload)
            sweep_commands(state)
            return
        state.commands.finish(payload, 'applied', generation=self.session.generation)
        state.explicit_intents.pop(id(payload), None)
        state.explicit_payloads.pop(id(payload), None)
        remember_accepted(payload, state)
        if payload.kind == "alert":
            accepted_alert(payload, state)
        state.last_ack_at = time.monotonic()
        state.consecutive_failures = 0
        state.last_error = None
        if payload.kind == "control":
            await self._readback(payload)
        sweep_commands(state)

    async def _readback(self, payload):
        record = self.state.commands.records.get(payload.command_id)
        if record:
            record.readback_pending = True
        try:
            self.state.device_state = {
                **await self.session.read_state(),
                "boot": self.session.identity.boot,
            }
            self.state.commands.readback(payload, self.state.device_state)
        except BaseException:
            self.state.commands.readback(payload, error='Settings readback unavailable')
            raise
