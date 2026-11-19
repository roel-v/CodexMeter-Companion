import asyncio
import sys
from types import SimpleNamespace

import pytest

from codexmeter import screen_policy
from codexmeter.screen_policy import LockScreenPolicy, parse_ioreg_lock_state


def test_lock_policy_turns_off_after_timeout_once():
    policy = LockScreenPolicy(timeout_sec=300)

    first = policy.observe(True, now=1000.0, epoch_now=1)
    assert first.payloads == ()
    assert first.connect_control is None

    early = policy.observe(True, now=1299.0, epoch_now=2)
    assert early.payloads == ()

    due = policy.observe(True, now=1300.0, epoch_now=3)
    assert len(due.payloads) == 1
    assert due.payloads[0].data["on"] is False
    assert due.payloads[0].data["why"] == "lock"

    repeat = policy.observe(True, now=1600.0, epoch_now=4)
    assert repeat.payloads == ()


def test_lock_policy_turns_on_when_unlocked_and_allows_connect_wake():
    policy = LockScreenPolicy(timeout_sec=300)

    policy.observe(True, now=1000.0, epoch_now=1)
    result = policy.observe(False, now=1100.0, epoch_now=2)

    assert len(result.payloads) == 1
    assert result.payloads[0].data["on"] is True
    assert result.payloads[0].data["why"] == "unlock"
    assert result.connect_control is not None
    assert result.connect_control.data["on"] is True
    assert result.connect_control.data["why"] == "connection_restored"


def test_lock_policy_initial_unlocked_turns_on_and_sets_connect_wake():
    policy = LockScreenPolicy(timeout_sec=300)
    result = policy.observe(False, now=1000.0, epoch_now=1)

    assert len(result.payloads) == 1
    assert result.payloads[0].data["on"] is True
    assert result.payloads[0].data["why"] == "unlock"
    assert result.connect_control is not None
    assert result.connect_control.data["on"] is True


def test_parse_ioreg_lock_state():
    assert parse_ioreg_lock_state('"IOConsoleLocked" = Yes') is True
    assert parse_ioreg_lock_state('"IOConsoleLocked" = No') is False
    assert parse_ioreg_lock_state('"CGSSessionScreenIsLocked"=Yes') is True
    assert parse_ioreg_lock_state("no lock key") is None


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "cancel"])
def test_interrupted_mac_lock_query_reaps_its_process(monkeypatch, cancel):
    async def exercise():
        started = asyncio.get_running_loop().create_future()
        spawn = asyncio.create_subprocess_exec

        async def spawn_slow_query(*args, **kwargs):
            child = await spawn(sys.executable, "-c", "import time; time.sleep(30)", **kwargs)
            started.set_result(child)
            return child

        monkeypatch.setattr(screen_policy, "sys", SimpleNamespace(platform="darwin"))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn_slow_query)
        query = asyncio.create_task(screen_policy.MacLockDetector().is_locked())
        child = await asyncio.wait_for(started, 5)
        try:
            if cancel:
                query.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await query
            else:
                assert await asyncio.wait_for(query, 5) is None
            assert child.returncode is not None
            assert child.stdout.at_eof()
        finally:
            if child.returncode is None:
                child.kill()
            await child.communicate()

    asyncio.run(exercise())


def test_policy_loop_uses_shared_policy_and_manager_callback():
    from codexmeter.screen_policy import screen_policy_loop
    async def exercise():
        stop = asyncio.Event()
        received, connection = [], []
        policy = LockScreenPolicy(timeout_sec=1)
        class Detector:
            async def is_locked(self):
                return False
        async def sink(payload):
            received.append(payload)
            stop.set()
        await screen_policy_loop(sink, stop, detector=Detector(), policy=policy,
                                 connect_control_setter=connection.append)
        assert received[0].data["why"] == "unlock"
        assert connection[0].data["why"] == "connection_restored"
        assert policy.observe(False, now=10**9, epoch_now=1).payloads == ()
    asyncio.run(exercise())
