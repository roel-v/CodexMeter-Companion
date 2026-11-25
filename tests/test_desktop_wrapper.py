import asyncio
import json

import pytest

from codexmeter import desktop_wrapper as wrapper
from codexmeter.chat_activity import ChatActivity
from codexmeter.compatibility import ContractError


def test_sidebar_filters_hidden_helpers_and_archived_chats(tmp_path):
    (tmp_path / ".codex-global-state.json").write_text(json.dumps({
        "thread-project-assignments": {"project": "folder"}, "pinned-thread-ids": ["pin", "archived"],
        "projectless-thread-ids": ["plain", "pin"]}))
    assert wrapper.sidebar_roots(tmp_path, {"project", "pin", "plain", "helper"}) == {"project", "pin", "plain"}


@pytest.mark.parametrize("data", [{}, {"thread-project-assignments": []}, {"pinned-thread-ids": [1]}])
def test_changed_sidebar_contract_is_unknown(tmp_path, data):
    (tmp_path / ".codex-global-state.json").write_text(json.dumps(data))
    with pytest.raises(ContractError):
        wrapper.sidebar_roots(tmp_path, {"chat"})


@pytest.mark.parametrize("data", [{"health": "protocol"}, {"health": "ok"}, {"health": "ok", "states": {"x": "busy"}},
                                  {"health": "ok", "states": {"hidden": "running"}}])
def test_changed_protocol_never_becomes_zero(data):
    with pytest.raises(ContractError, match="wrapper_protocol"):
        wrapper.validate_snapshot(data, {"x"})


def test_verified_empty_and_disconnected_are_distinct():
    assert wrapper.validate_snapshot({"health": "ok", "states": {}}, set()) == ("ok", {})
    assert wrapper.validate_snapshot({"health": "inactive"}, set()) == ("wrapper_inactive", {})


@pytest.mark.parametrize("health,expected", [("ok", (1, 1, 1)), ("wrapper_inactive", (None, None, 2))])
def test_counts_and_independent_unread_fallback(monkeypatch, tmp_path, health, expected):
    from codexmeter import chat_activity
    monkeypatch.setattr(chat_activity, "read_roots", lambda _: {"a", "b", "c"})
    monkeypatch.setattr(chat_activity, "read_unread_snapshot", lambda *_: ({"a", "c"}, "test"))
    c = ChatActivity(tmp_path)
    asyncio.run(c._wrapper_sample(None, lambda *_: (health, {"a": "running", "b": "waiting"}),
                                  lambda _, roots: roots))
    assert tuple(c.payload.data[k] for k in ("run", "wait", "done")) == expected


def test_protocol_change_then_two_fresh_readings(monkeypatch, tmp_path):
    from codexmeter import chat_activity
    from codexmeter.compatibility import CompatibilityMonitor
    monitor = CompatibilityMonitor()
    lease = monitor.reader(("inventory", "unread", "stream"))
    tracker = ChatActivity(tmp_path, monitor)
    monkeypatch.setattr(chat_activity, "read_roots", lambda _: {"chat"})
    monkeypatch.setattr(chat_activity, "read_unread_snapshot", lambda *_: (set(), "account"))

    def sample(data):
        tracker.payload = tracker._payload(False)
        asyncio.run(tracker._wrapper_sample(lease, lambda _, ids: wrapper.validate_snapshot(data, ids),
                                            lambda _, ids: ids))

    sample({"health": "protocol"})
    assert tracker.payload.data["run"] is None
    assert monitor.records["stream"].reason == "wrapper_protocol"
    assert monitor.records["stream"].incident
    for _ in range(2):
        sample({"health": "ok", "states": {"chat": "running"}})
    assert monitor.records["stream"].incident is None
    assert tracker.payload.data["run"] == 1


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows registry opt-in")
def test_install_disable_and_conflict_are_scoped(monkeypatch, tmp_path):
    from contextlib import nullcontext
    import winreg
    registry = {}
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv(wrapper.VARIABLE, raising=False)
    monkeypatch.setattr(wrapper, "configured_cli", lambda: registry.get(wrapper.VARIABLE, ""))
    monkeypatch.setattr(wrapper, "bundled_binary", lambda: b"test helper")
    monkeypatch.setattr(winreg, "CreateKeyEx", lambda *args: nullcontext(registry))
    monkeypatch.setattr(winreg, "SetValueEx", lambda key, name, _, kind, value: key.update({name: value}))
    monkeypatch.setattr(winreg, "DeleteValue", lambda key, name: key.pop(name))
    monkeypatch.setattr(wrapper.ctypes.windll.user32, "SendMessageTimeoutW", lambda *args: 1)
    wrapper.configure(True)
    assert wrapper.enabled()
    assert wrapper.installed_path().read_bytes() == b"test helper"
    wrapper.configure(False)
    assert not wrapper.enabled()
    registry[wrapper.VARIABLE] = str(tmp_path / "another.exe")
    with pytest.raises(RuntimeError, match="preserved"):
        wrapper.configure(True)
    wrapper.configure(False)
    assert registry[wrapper.VARIABLE].endswith("another.exe")


def test_default_setup_and_remembered_opt_out(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(wrapper, "configure", calls.append)
    setup = wrapper.WrapperSetup(tmp_path)
    setup.reconcile()
    setup.reconcile()
    assert calls == [True]
    setup.preference.save(False)
    setup.reconcile()
    wrapper.WrapperSetup(tmp_path).reconcile()
    assert calls == [True, False, False]
    setup.preference.save(True)
    setup.reconcile()
    assert calls[-1] is True


def test_failed_upgrade_retries_after_unlock(tmp_path, monkeypatch):
    now = [0]
    calls = []
    def configure(enabled):
        calls.append(enabled)
        if len(calls) == 1:
            raise PermissionError("locked")
    monkeypatch.setattr(wrapper, "configure", configure)
    monkeypatch.setattr(wrapper.time, "monotonic", lambda: now[0])
    setup = wrapper.WrapperSetup(tmp_path)
    setup.reconcile()
    assert setup.error == "locked"
    setup.reconcile()
    assert calls == [True]
    now[0] = 61
    setup.reconcile()
    assert calls == [True, True] and not setup.error
