"""Bounded, process-local outcomes of admitted manual commands. No wire changes."""
from dataclasses import dataclass
import time

INTENT_TTL_SEC = 60
RESULT_TTL_SEC = 600
RESULT_CAPACITY = 64
TERMINAL = frozenset({'applied', 'rejected', 'expired', 'superseded', 'cancelled', 'unknown'})


@dataclass
class CommandRecord:
    payload: object
    created: float
    status: str = 'queued'
    generation: str | None = None
    finished: float | None = None
    reason: str = ''
    readback: dict | None = None
    readback_error: str | None = None
    readback_pending: bool = False


class CommandResults:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.records = {}

    def prune(self):
        now = self.clock()
        for record in self.records.values():
            if record.status == 'queued' and now - record.created >= INTENT_TTL_SEC:
                record.status, record.reason, record.finished = 'expired', 'Command expired before sending', now
        terminal = sorted(((key, r) for key, r in self.records.items() if r.finished is not None),
                          key=lambda pair: pair[1].finished)
        for index, (key, record) in enumerate(terminal):
            if now - record.finished >= RESULT_TTL_SEC or index < len(terminal) - RESULT_CAPACITY:
                self.records.pop(key, None)

    def admit(self, payload):
        self.prune()
        if sum(r.status not in TERMINAL for r in self.records.values()) >= RESULT_CAPACITY:
            raise ValueError('Too many pending display commands')
        self.records[payload.command_id] = CommandRecord(payload, self.clock())

    def queued(self, payload):
        self.prune()
        record = self.records.get(payload.command_id)
        return record is not None and record.status == 'queued'

    def start(self, payload, generation):
        if not self.queued(payload):
            return False
        record = self.records[payload.command_id]
        record.status, record.generation = 'sending', generation
        return True

    def finish(self, payload, status, reason='', *, generation=None):
        record = self.records.get(payload.command_id)
        if record is None or record.status in TERMINAL:
            return
        if generation is not None and record.generation not in (None, generation):
            return
        if record.status == 'sending' and status in ('cancelled', 'superseded', 'expired'):
            return  # Only the active sender can establish this outcome.
        record.status, record.reason, record.finished = status, reason, self.clock()

    def cancel_queued(self, reason):
        for record in self.records.values():
            if record.status == 'queued':
                self.finish(record.payload, 'cancelled', reason)

    def readback(self, payload, state=None, error=None):
        record = self.records.get(payload.command_id)
        if record:
            record.readback_pending = False
            record.readback = dict(state) if state is not None else None
            record.readback_error = error

    def get(self, command_id):
        self.prune()
        record = self.records.get(command_id)
        if record is None:
            return None
        return {'command_id': command_id, 'command': record.payload.data['cmd'],
                'value': record.payload.data.get('value', record.payload.data.get('on')),
                'status': record.status, 'reason': record.reason,
                'readback': dict(record.readback) if record.readback is not None else None,
                'readback_pending': record.readback_pending,
                'readback_error': record.readback_error}
