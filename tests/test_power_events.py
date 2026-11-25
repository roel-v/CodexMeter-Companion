import asyncio
import sys
import pytest
from codexmeter.compatibility import CompatibilityMonitor
from codexmeter.power_events import power_event_loop, WindowsPowerEvents
from tests.support.compatibility import Clock


@pytest.mark.parametrize("duration", [5, 3600])
def test_service_power_events_grace_cleanup_and_late_callbacks(duration):
    async def run():
        clock = Clock()
        monitor = CompatibilityMonitor(clock=clock, wall=clock, components=["quota"])
        monitor.observe("quota", "unavailable", "connection")
        class Source:
            closed = False
            def start(self, notify): self.notify = notify; return True
            def close(self): self.closed = True
        source = Source(); stop = asyncio.Event()
        resumes = []
        task = asyncio.create_task(power_event_loop(monitor, stop, source=source, on_resume=lambda: resumes.append(True)))
        await asyncio.sleep(0)
        clock.advance(monitor, 40)
        before = monitor.records["quota"].elapsed
        source.notify(True); await asyncio.sleep(0)
        clock.advance(monitor, duration)
        assert monitor.records["quota"].elapsed == before
        source.notify(False); await asyncio.sleep(0)
        grace = monitor.grace_until
        clock.advance(monitor, 10)
        source.notify(False); await asyncio.sleep(0)
        assert resumes == [True]
        assert monitor.grace_until == grace  # automatic/user resume pair is one resume
        clock.advance(monitor, 20)
        assert monitor.records["quota"].elapsed == before
        clock.advance(monitor, 1)
        assert monitor.records["quota"].elapsed == before + 1
        stop.set(); await task
        source.notify(True); await asyncio.sleep(0)
        assert source.closed and not monitor.suspended
    asyncio.run(run())


def test_unavailable_source_and_cancellation_do_not_break_service():
    async def run():
        class Source:
            closed = False
            def start(self, notify): raise OSError("unavailable")
            def close(self): self.closed = True
        source = Source(); monitor = CompatibilityMonitor()
        task = asyncio.create_task(power_event_loop(monitor, asyncio.Event(), source=source))
        await asyncio.sleep(0)
        assert not monitor.power_events_available
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert source.closed
    asyncio.run(run())


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows registration")
def test_native_registration_without_sleep():
    source = WindowsPowerEvents()
    try:
        assert source.start(lambda suspended: None)
        assert source.handle.value
    finally:
        source.close()
    assert not source.handle.value
