"""Validators for the metadata contracts consumed by CodexMeter."""
import datetime as dt
import json
import math
import sqlite3
from .compatibility import ContractError

SUPPORTED_STREAM_VERSIONS = frozenset({11, 13})

def schema(db, tables, field):
    for table, required in tables.items():
        columns = {row[1] for row in db.execute('PRAGMA table_info("' + table + '")')}
        if not set(required) <= columns:
            raise ContractError("schema", field, definitive=True)

def open_database(path):
    if not path.is_file():
        raise FileNotFoundError()
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)

def read_roots(home):
    with open_database(home / "state_5.sqlite") as db:
        schema(db, {"threads": ["id", "archived", "source"],
                    "thread_spawn_edges": ["child_thread_id"]}, "inventory")
        roots = {r[0] for r in db.execute(
            "SELECT id FROM threads WHERE archived=0 AND source IN ('cli','vscode') "
            "AND id NOT IN (SELECT child_thread_id FROM thread_spawn_edges)")}
    if not all(isinstance(t, str) and t for t in roots):
        raise ContractError(field="inventory")
    return roots

def read_unread(home, roots):
    return read_unread_snapshot(home, roots)[0]


def read_unread_snapshot(home, roots):
    try:
        raw = json.loads((home / ".codex-global-state.json").read_text(encoding="utf-8"))
        identities = raw["electron-thread-read-state-v1"]["unreadByIdentity"]
        if not isinstance(identities, dict):
            raise TypeError()
        if len(identities) != 1:
            # Ambiguous identity is unavailable, not a schema failure.
            raise LookupError("ambiguous_account")
        identity = next(iter(identities))
        hosts = identities[identity]
        if not isinstance(hosts, dict):
            raise TypeError()
        unread = set()
        for host, ids in hosts.items():
            if host.startswith("local:"):
                if not isinstance(ids, list) or not all(isinstance(t, str) for t in ids):
                    raise TypeError()
                unread.update(ids)
    except (KeyError, TypeError, ValueError):
        raise ContractError(field="unread") from None
    completed = set()
    with open_database(home / "thread_history_1.sqlite") as db:
        schema(db, {"thread_turns": ["thread_id", "status", "rollout_ordinal"]}, "history")
        for tid in roots & unread:
            row = db.execute("SELECT status FROM thread_turns WHERE thread_id=? "
                             "ORDER BY rollout_ordinal DESC LIMIT 1", (tid,)).fetchone()
            if row:
                if row[0] not in {"completed", "inProgress", "interrupted", "failed"}:
                    raise ContractError(field="history")
                if row[0] == "completed":
                    completed.add(tid)
    # The account may change while SQLite is being read. Reject that mixed sample.
    try:
        current = json.loads((home / ".codex-global-state.json").read_text(encoding="utf-8"))
        current = current["electron-thread-read-state-v1"]["unreadByIdentity"]
        if not isinstance(current, dict) or list(current) != [identity]:
            raise LookupError("ambiguous_account")
    except (KeyError, TypeError, ValueError):
        raise ContractError(field="unread") from None
    import hashlib
    return completed, hashlib.sha256(identity.encode()).hexdigest()

def validate_state(state):
    if not isinstance(state, dict):
        raise ContractError(field="snapshot")
    status = state.get("threadRuntimeStatus")
    if not isinstance(status, dict) or status.get("type") not in {"active", "idle"}:
        raise ContractError(field="runtime_status")
    flags = status.get("activeFlags", [])
    if not isinstance(flags, list) or not all(
        isinstance(f, str) and f in {"waitingOnApproval", "waitingOnUserInput"} for f in flags
    ):
        raise ContractError(field="active_flags")
    if type(state.get("hasUnreadTurn")) is not bool or not isinstance(state.get("source"), str):
        raise ContractError(field="snapshot")

def validate_quota(response):
    from .limits import _candidate_snapshots
    if not isinstance(response, dict):
        raise ContractError(field="quota")
    candidates = _candidate_snapshots(response)
    if not candidates:
        raise ContractError(field="quota")
    found = False
    for candidate in candidates:
        for bucket in ("primary", "secondary"):
            window = candidate.get(bucket)
            if window is None:
                continue
            if not isinstance(window, dict):
                raise ContractError(field="quota")
            used = window.get("usedPercent")
            reset = window.get("resetsAt")
            duration = window.get("windowDurationMins")
            if (type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used <= 100
                or type(reset) is not int or reset < 0
                or (duration is not None and (type(duration) is not int or duration not in (300, 10080)))):
                raise ContractError(field="quota")
            found = True
    if not found:
        raise ContractError(field="quota")

def validate_usage_line(line):
    # Only candidate usage records are decoded; unrelated transcript lines are not retained.
    if '"token_usage_record"' not in line and '"token_count"' not in line:
        return
    try:
        row = json.loads(line)
        if not isinstance(row, dict):
            return
        payload = row.get("payload")
        if row.get("type") == "token_usage_record":
            if not isinstance(payload, dict) or not isinstance(payload.get("response_id"), str):
                raise ValueError()
            usage = payload.get("usage")
        elif row.get("type") == "event_msg" and isinstance(payload, dict) and payload.get("type") == "token_count":
            # Empty info is a known rate-limit-only notification.
            info = payload.get("info")
            if info is None:
                return
            usage = info.get("total_token_usage")
        else:
            return
        total = usage.get("total_tokens")
        if type(total) is not int or total < 0:
            raise ValueError()
        timestamp = dt.datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ContractError(field="tokens") from None
