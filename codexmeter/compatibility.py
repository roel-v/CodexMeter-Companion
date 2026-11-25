"""Local, privacy-safe health observations. No network calls or transcript retention."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
import time
from .persistence import atomic_write_json

COMPONENTS = {
    "stream": ("Running and waiting chats", ["running", "waiting"], 90),
    "inventory": ("Chat inventory", ["running", "waiting", "done"], 20),
    "unread": ("Completed unread chats", ["done"], 20),
    "quota": ("Remaining quota", ["quota"], 120),
    "tokens": ("Token usage", ["tokens", "cost"], 120),
}
REASONS = {
    "wrapper_missing", "wrapper_inactive", "wrapper_listener", "wrapper_protocol",
    "starting", "ok", "closed", "missing", "locked", "corrupt", "connection",
    "authentication", "timeout", "schema", "unsupported_version", "structure",
    "ambiguous_account", "incomplete", "no_history", "expired", "reader_error",
}
FIELDS = {"version", "snapshot", "patch", "runtime_status", "active_flags", "inventory",
          "unread", "history", "quota", "tokens", "timestamp", "coverage"}
def safe_details(details):
    result = {}
    if isinstance(details, dict):
        if isinstance(details.get("field"), str) and details["field"] in FIELDS:
            result["field"] = details["field"]
        for key in ("observed_version", "supported_version"):
            if type(details.get(key)) is int and 0 <= details[key] < 100000:
                result[key] = details[key]
    return result

class SupersededObservation(RuntimeError):
    """A newer reader or connection owns this component now."""


class ContractError(ValueError):
    def __init__(self, reason="structure", field="coverage", *, definitive=False, version=None):
        super().__init__(reason)
        self.reason = reason if reason in REASONS else "structure"
        self.details = safe_details({"field": field, "observed_version": version})
        self.definitive = definitive

@dataclass
class Record:
    state: str = "checking"
    reason: str = "starting"
    details: dict = field(default_factory=dict)
    validated: float | None = None
    validated_utc: float | None = None
    first_utc: float | None = None
    incident: str | None = None
    incident_reason: str = ""
    incident_details: dict = field(default_factory=dict)
    successes: int = 0
    failures: int = 0
    elapsed: float = 0
    eligible: bool = True
    generation: int = 0

class CompatibilityMonitor:
    def __init__(self, path: Path | None = None, *, clock=time.monotonic, wall=time.time,
                 components=None):
        self.clock, self.wall, self.path = clock, wall, path
        self.records = {key: Record() for key in (components or COMPONENTS)}
        self.started = self.last_tick = clock()
        self.grace_until = self.started + 30
        self.suspended = False
        self.power_events_available = False
        self.host_running = None
        self.notified = {}
        self.versions = {}
        self.reader_contexts = {}
        self.pending_since = None
        self.storage_ok = True
        if path:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.notified = {k: v for k, v in raw.get("incidents", {}).items()
                                 if isinstance(k, str) and len(k) == 64 and
                                 all(c in "0123456789abcdef" for c in k) and
                                 isinstance(v, (float, int))}
                self.notified = dict(list(self.notified.items())[-32:])
                for key, saved in raw.get("unresolved", {}).items():
                    if key in self.records and isinstance(saved, dict) and saved.get("reason") in REASONS:
                        details = safe_details(saved.get("details"))
                        r = self.records[key]
                        r.reason, r.details = saved["reason"], details
                        r.incident = self._signature(key, r.reason, details)
                        r.incident_reason, r.incident_details = r.reason, details
            except (OSError, ValueError, TypeError, AttributeError):
                pass

    def _save(self):
        if self.path:
            try:
                atomic_write_json(self.path, {"incidents": self.notified, "unresolved": {
                    key: {"reason": r.incident_reason, "details": r.incident_details}
                    for key, r in self.records.items() if r.incident}})
                self.storage_ok = True
            except Exception:
                self.storage_ok = False

    def begin(self, component, *, reset=True):
        r = self.records[component]
        r.generation += 1
        if reset:
            r.validated = None
            r.successes = 0
            if r.state == "compatible":
                r.state, r.reason = "checking", "starting"
        return r.generation

    def reader(self, components, *, reset=True):
        return ReaderObservation(self, components, reset=reset)

    def observe(self, component, state="compatible", reason="ok", details=None, *,
                definitive=False, generation=None, eligible=True):
        r = self.records[component]
        if generation is not None and generation != r.generation:
            return
        self.tick()
        now = self.clock()
        reason = reason if reason in REASONS else "reader_error"
        details = safe_details(details)
        if not r.eligible and eligible:
            r.elapsed = 0
        r.eligible = eligible
        previous = (r.state, r.reason, r.incident)
        if state == "compatible":
            r.successes += 1
            r.failures = 0
            r.validated, r.validated_utc = now, self.wall()
            if r.successes >= 2 or (r.incident is None and r.reason == "starting"):
                # Successful recovery rearms only this component's incident/outage.
                for signature in (r.incident, self._signature(component, "outage", {})):
                    self.notified.pop(signature, None)
                recovered = bool(r.incident or r.elapsed)
                r.incident = None
                r.incident_reason, r.incident_details = "", {}
                r.first_utc = None
                r.elapsed = 0
                r.state, r.reason, r.details = state, "ok", {}
                if recovered:
                    self._save()
            # One observation after failure is not enough to clear the warning.
        else:
            r.successes = 0
            r.first_utc = r.first_utc or self.wall()
            r.failures = r.failures + 1 if r.reason == reason and r.details == details else 1
            if state == "incompatible" and (definitive or r.failures >= 2):
                r.incident = self._signature(component, reason, details)
                r.incident_reason, r.incident_details = reason, details
                r.state = "incompatible"
            else:
                r.state = "unavailable" if state == "incompatible" else state
            r.reason, r.details = reason, details
            if not eligible:
                r.elapsed = 0
        if previous != (r.state, r.reason, r.incident):
            logging.info("Compatibility %s state=%s reason=%s", component, r.state, r.reason)
            if r.incident:
                self._save()

    @staticmethod
    def _signature(component, reason, details):
        return hashlib.sha256(json.dumps([component, reason, details], sort_keys=True).encode()).hexdigest()

    def host_presence(self, running):
        if self.host_running is False and running is not False:
            self.grace_until = self.clock() + 30
        self.host_running = running
        if running is False:
            for r in self.records.values():
                r.elapsed = 0

    def power(self, suspended):
        self.tick()
        self.suspended = suspended
        self.last_tick = self.clock()
        if not suspended:
            self.grace_until = self.clock() + 30

    def tick(self):
        now = self.clock()
        delta = max(0, now - max(self.last_tick, self.grace_until))
        # A stopped event loop/sleep cannot charge hours to an outage timer.
        if not self.power_events_available and now - self.last_tick > 30:
            self.grace_until = now + 30
            delta = 0
        self.last_tick = now
        for key, r in self.records.items():
            if r.validated is not None and now - r.validated > COMPONENTS[key][2]:
                if r.state == "compatible":
                    r.state, r.reason, r.successes = "stale", "expired", 0
            if r.state == "checking" and now >= self.grace_until:
                r.state, r.reason = "unavailable", "starting"
            if not self.suspended and self.host_running is not False and r.eligible and r.state != "compatible":
                r.elapsed += delta

    def snapshot(self):
        self.tick()
        return {"schema": 1, "components": {
            key: {"label": COMPONENTS[key][0], "metrics": COMPONENTS[key][1],
                  "state": r.state, "reason": r.reason, "details": r.details.copy(),
                  "last_validated_utc": r.validated_utc, "first_failure_utc": r.first_utc,
                  "unresolved_incompatibility": r.incident is not None,
                  "incompatibility_reason": r.incident_reason,
                  "incompatibility_details": r.incident_details.copy(),
                  "outage_seconds": round(r.elapsed), "eligible": r.eligible}
            for key, r in self.records.items()},
            "versions": dict(self.versions), "persistence_available": self.storage_ok}

    def notifications(self):
        self.tick()
        pending = []
        for key, r in self.records.items():
            signature = r.incident
            kind = "incompatible"
            if signature is None and r.elapsed >= 300 and r.eligible and self.host_running is not False:
                signature = self._signature(key, "outage", {})
                kind = "outage"
            if signature and signature not in self.notified:
                pending.append((key, kind, signature))
        if not pending or self.suspended:
            self.pending_since = None
            return None
        if self.pending_since is None:
            self.pending_since = self.clock()
        if self.clock() - self.pending_since < 2:
            return None
        for _, _, signature in pending:
            self.notified[signature] = self.wall()
        self.notified = dict(sorted(self.notified.items(), key=lambda x: x[1])[-32:])
        self._save()
        self.pending_since = None
        return {"kind": "compatibility", "components": [key for key, _, _ in pending],
                "confirmed": any(kind == "incompatible" for _, kind, _ in pending)}

def report_error(monitor, component, exc, *, eligible=True):
    if monitor is None:
        return
    import sqlite3
    reason, state, definitive, details = "reader_error", "unavailable", False, {}
    if isinstance(exc, ContractError):
        state, reason, definitive, details = "incompatible", exc.reason, exc.definitive, exc.details
    elif isinstance(exc, FileNotFoundError):
        reason = "missing"
    elif isinstance(exc, (TimeoutError,)):
        reason = "timeout"
    elif isinstance(exc, sqlite3.Error):
        code = getattr(exc, "sqlite_errorcode", 0) & 255
        reason = "locked" if code in (5, 6) else "corrupt" if code in (11, 26) else "reader_error"
    elif isinstance(exc, (ConnectionError, OSError)):
        reason = "connection"
    monitor.observe(component, state, reason, details, definitive=definitive, eligible=eligible)


class ReaderObservation:
    """Lease captured before asynchronous work; health and payloads share the fence."""
    def __init__(self, monitor, components, *, reset=True):
        self.monitor = monitor
        self.generations = {key: monitor.begin(key, reset=reset) for key in components}
        self.records = monitor.records

    def check(self):
        if any(self.records[key].generation != value for key, value in self.generations.items()):
            raise SupersededObservation()

    def bind(self, component, context):
        self.check()
        previous = self.monitor.reader_contexts.get(component)
        if previous != context:
            self.monitor.reader_contexts[component] = context
            self.generations[component] = self.monitor.begin(component)

    def observe(self, component, *args, **kwargs):
        self.check()
        self.monitor.observe(component, *args, generation=self.generations[component], **kwargs)
