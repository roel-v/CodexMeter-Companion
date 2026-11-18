"""Logical-device delivery state, independent of connection lifetime."""

from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from .payloads import Payload


TELEMETRY_REPLAY_TTL_SEC = 300
ALERT_TTL_SEC = 60
PENDING_ALERT_CAPACITY = 8  # Host backlog; firmware deduplicates across reconnects.
EXPLICIT_INTENT_TTL_SEC = 60


@dataclass
class DeliveryState:
    observed_at: dict[str, float] = field(default_factory=dict)
    alerts: list[tuple[float, Payload]] = field(default_factory=list)
    explicit_intents: dict[int, tuple[str, int, float]] = field(default_factory=dict)
    explicit_payloads: dict[int, Payload] = field(default_factory=dict)
    connection_state: str = "disconnected"
    fallback_reason: str | None = None
    transport: str | None = None
    generation: str | None = None
    device_state: dict = field(default_factory=dict)
    last_usage: Payload | None = None
    last_activity: Payload | None = None
    last_payload: Payload | None = None
    connect_control: Payload | None = None
    desired_control: Payload | None = None
    desired_policy: Payload | None = None
    desired_settings: dict[str, Payload] = field(default_factory=dict)
    pending_alert: Payload | None = None
    observed_device_id: str | None = None
    connected: bool = False
    last_discovered_at: float | None = None
    last_discovery_source: str | None = None
    last_discovered_address: str | None = None
    last_connected_at: float | None = None
    last_disconnected_at: float | None = None
    last_write_at: float | None = None
    last_ack_at: float | None = None
    consecutive_failures: int = 0
    ble_failures: int = 0
    last_error: str | None = None

    def status(self, queue_depth: int = 0, now: float | None = None) -> dict[str, Any]:
        now = asyncio.get_running_loop().time() if now is None else now

        def age(value: float | None) -> float | None:
            if value is None:
                return None
            return round(max(0.0, now - value), 1)

        return {
            "connected": self.connected,
            "connection_state": self.connection_state,
            "fallback_reason": self.fallback_reason,
            "transport": self.transport,
            "generation": self.generation,
            "device_state": dict(self.device_state),
            "queue_depth": queue_depth,
            "last_discovered_age_sec": age(self.last_discovered_at),
            "last_discovery_source": self.last_discovery_source,
            "last_discovered_address": self.last_discovered_address,
            "last_connected_age_sec": age(self.last_connected_at),
            "last_disconnected_age_sec": age(self.last_disconnected_at),
            "last_write_age_sec": age(self.last_write_at),
            "last_ack_age_sec": age(self.last_ack_at),
            "consecutive_failures": self.consecutive_failures,
            "ble_failures": self.ble_failures,
            "last_error": self.last_error,
            "last_payload": self.last_payload.kind if self.last_payload else None,
            "pending_alert": (
                self.pending_alert.data.get("id") if self.pending_alert else None
            ),
            "observed_device_id": self.observed_device_id,
        }


def remember_accepted(payload: Payload, state: DeliveryState) -> None:
    state.last_payload = payload
    if payload.kind == "usage" and state.last_usage is None:
        state.last_usage = payload
    elif payload.kind == "activity" and state.last_activity is None:
        state.last_activity = payload
    elif payload.kind == "control":
        if payload.data.get("cmd") in ("brightness", "rotation"):
            state.desired_settings.setdefault(str(payload.data["cmd"]), payload)
        elif payload.data.get("why") in ("lock", "unlock", "connection_restored"):
            if state.desired_policy is None:
                state.desired_policy = payload
        elif state.desired_control is None:
            state.desired_control = payload


def remember_desired(payload: Payload, state: DeliveryState) -> None:
    state.observed_at[payload.kind] = time.monotonic()
    if payload.kind == "alert":
        prune_alerts(state)
        if not any(p.data.get("id") == payload.data.get("id") for _, p in state.alerts):
            state.alerts.append((time.monotonic(), payload))
            del state.alerts[:-PENDING_ALERT_CAPACITY]
    if payload.kind == "usage":
        state.last_usage = payload
    elif payload.kind == "activity":
        state.last_activity = payload
    elif payload.kind == "control":
        if payload.data.get("cmd") in ("brightness", "rotation"):
            state.desired_settings[str(payload.data["cmd"])] = payload
        elif payload.data.get("why") in ("lock", "unlock", "connection_restored"):
            state.desired_policy = payload
        else:
            state.desired_control = payload


def should_send(payload: Payload, state: DeliveryState) -> bool:
    if payload.kind == "alert":
        timestamp = payload.data.get("t")
        return type(timestamp) in (int, float) and 0 <= time.time() - timestamp <= ALERT_TTL_SEC
    latest = (
        state.last_usage
        if payload.kind == "usage"
        else state.last_activity if payload.kind == "activity" else None
    )
    if latest is not None and latest is not payload:
        return False
    if payload.kind == "control" and payload.data.get("cmd") in (
        "brightness",
        "rotation",
    ):
        desired = state.desired_settings.get(payload.data["cmd"])
        return desired is None or desired is payload
    if payload.kind != "control":
        return True
    if payload.data.get("cmd") != "screen":
        return True
    if (payload.data.get("on") is True and state.connect_control is None
            and payload.data.get("why") != "manual"):
        return False
    return True


def prune_alerts(state: DeliveryState, *, now=None):
    now = time.monotonic() if now is None else now
    state.alerts[:] = [
        (created, p) for created, p in state.alerts if now - created < ALERT_TTL_SEC
    ]


def accepted_alert(payload: Payload, state: DeliveryState):
    state.alerts[:] = [
        (created, p)
        for created, p in state.alerts
        if p.data.get("id") != payload.data.get("id")
    ]
    if state.pending_alert is payload:
        state.pending_alert = None


def negotiated_replay(state: DeliveryState, *, same_host: bool, now=None):
    now = time.monotonic() if now is None else now
    prune_alerts(state, now=now)
    if not same_host:
        state.alerts.clear()
        state.pending_alert = None
        state.explicit_intents.clear()
        state.explicit_payloads.clear()
        state.desired_settings.clear()
        state.desired_control = None
    result = []
    for kind, payload in (
        ("usage", state.last_usage),
        ("activity", state.last_activity),
    ):
        if (
            payload is not None
            and now - state.observed_at.get(kind, float("-inf")) < TELEMETRY_REPLAY_TTL_SEC
        ):
            result.append(payload)
    if same_host:
        current = state.device_state
        for key, (boot, revision, created) in list(state.explicit_intents.items()):
            if (
                now - created >= EXPLICIT_INTENT_TTL_SEC
                or boot != current.get("boot")
                or revision != current.get("rev")
            ):
                state.explicit_intents.pop(key, None)
                state.explicit_payloads.pop(key, None)
            elif key in state.explicit_payloads:
                result.append(state.explicit_payloads[key])
        result.extend(p for _, p in state.alerts)
    return result


def discard_intents(state: DeliveryState, payloads):
    """Eviction is final: never replay an explicit request removed from the queue."""
    for payload in payloads:
        state.explicit_intents.pop(id(payload), None)
        state.explicit_payloads.pop(id(payload), None)
        if state.desired_control is payload:
            state.desired_control = None
        if state.desired_policy is payload:
            state.desired_policy = None
        command = payload.data.get("cmd")
        if state.desired_settings.get(command) is payload:
            state.desired_settings.pop(command, None)
