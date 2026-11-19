"""Check transitions without changing the machine's power state."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from codexmeter.sleep_guard import CodexSleepGuard, observe_with_guard


def test_shared_request_lifetime():
    guard = CodexSleepGuard.__new__(CodexSleepGuard)
    guard.handle = None
    guard.create = Mock(return_value=42)
    guard.request = Mock(return_value=True)
    guard.clear = Mock(return_value=True)
    guard.close = Mock(return_value=True)

    for running in (2, 1, None, 1):
        guard.update(running)
    guard.create.assert_called_once()
    guard.request.assert_called_once_with(42, 1)
    guard.close.assert_not_called()

    guard.update(0)
    guard.update(0)
    guard.clear.assert_called_once_with(42, 1)
    guard.close.assert_called_once_with(42)
    assert guard.handle is None

    guard.update(1)
    guard.update(None, desktop_running=False)
    assert guard.handle is None

def test_silent_observer_releases_and_fresh_work_reacquires():
    async def run():
        released = asyncio.Event()
        guard = Mock(handle=None)
        def update(running, desktop_running=None):
            guard.handle = 42 if running else None
            if not running:
                released.set()
        guard.update.side_effect = update
        sink = AsyncMock()
        async def observe(publish, stop):
            await publish(SimpleNamespace(data={"run": 1}))
            await publish(SimpleNamespace(data={"run": None}))
            assert guard.handle == 42
            await asyncio.wait_for(released.wait(), 1)
            assert guard.handle is None
            await publish(SimpleNamespace(data={"run": 2}))
            assert guard.handle == 42
        chats = SimpleNamespace(run=observe, desktop_running=True)
        await observe_with_guard(chats, sink, asyncio.Event(), guard, stale_after=.01)
        assert guard.handle is None and sink.await_count == 3
    asyncio.run(run())
