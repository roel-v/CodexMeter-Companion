import asyncio
import time
from codexmeter.delivery import DeliveryState, remember_desired, remember_accepted, should_send
from codexmeter.ble import BleTransport
from codexmeter.device_manager import DeviceManager
from codexmeter.device_registry import config_from_short_id
from codexmeter.payloads import Payload


def test_delivery_characterization_latest_and_pending_alert():
    state = DeliveryState()
    old = Payload("usage", {"k": "usage", "t": 1})
    new = Payload("usage", {"k": "usage", "t": 2})
    remember_desired(old, state)
    remember_desired(new, state)
    remember_accepted(old, state)
    assert state.last_usage is new
    assert state.last_payload is old
    assert not should_send(old, state)
    alert = Payload("alert", {"id": "a", "t": time.time()})
    state.pending_alert = alert
    assert should_send(alert, state)
    assert state.pending_alert is alert


def test_delivery_characterization_control_and_status():
    async def run():
        manager = DeviceManager(
            [config_from_short_id("A3F91C")],
            connect_timeout_sec=0.1,
            disconnect_timeout_sec=0.1,
            write_timeout_sec=0.1,
            ack_timeout_sec=0.1,
            notify_timeout_sec=0.1,
            healthcheck_interval_sec=1,
        )
        manager.slots[0].state.connected = True  # legacy connection has no revision state
        await manager.control_device(
            {
                "device_id": manager.slots[0].config.device_id,
                "command": "screen",
                "value": False,
            }
        )
        state = manager.slots[0].state
        assert state.desired_control.data["why"] == "manual"
        assert state.desired_control.data["v"] == 1
        assert manager.status()["devices"][0]["queue_depth"] == 1
        assert manager.status()["connected_count"] == 1

    asyncio.run(run())


def test_monotonic_alert_ledger_and_fresh_replay():
    from codexmeter.delivery import (
        DeliveryState,
        remember_desired,
        negotiated_replay,
        prune_alerts,
    )

    state = DeliveryState()
    for index in range(10):
        remember_desired(Payload("alert", {"id": str(index), "t": time.time()}), state)
    assert len(state.alerts) == 8 and state.alerts[0][1].data["id"] == "2"
    remember_desired(Payload("usage", {"k": "usage"}), state)
    now = time.monotonic()
    assert len(negotiated_replay(state, same_host=True, now=now)) == 9
    assert negotiated_replay(state, same_host=True, now=now + 301) == []
    assert not state.alerts


def test_explicit_replay_requires_original_boot_revision_and_same_host():
    from codexmeter.delivery import DeliveryState, remember_desired, remember_accepted, should_send, negotiated_replay

    state = DeliveryState()
    p = Payload("control", {"cmd": "brightness", "value": 50})
    now = time.monotonic()
    state.device_state = {"boot": "a", "rev": 4}
    state.explicit_intents[id(p)] = ("a", 4, now)
    state.explicit_payloads[id(p)] = p
    assert negotiated_replay(state, same_host=True, now=now) == [p]
    state.device_state["rev"] = 5
    assert negotiated_replay(state, same_host=True, now=now) == []
    state.explicit_intents[id(p)] = ("a", 5, now)
    state.explicit_payloads[id(p)] = p
    assert negotiated_replay(state, same_host=False, now=now) == []
    assert not state.explicit_intents and not state.explicit_payloads


def test_legacy_replay_never_refreshes_observation_time():
    from codexmeter.delivery import negotiated_replay

    state = DeliveryState()
    p = Payload("usage", {"k": "usage"})
    remember_desired(p, state)
    state.observed_at["usage"] = time.monotonic() - 301
    before = state.observed_at["usage"]
    # A legacy reconnect/ACK uses accepted-state bookkeeping, never producer observation.
    remember_accepted(p, state)
    assert state.observed_at["usage"] == before
    assert negotiated_replay(state, same_host=True) == []
