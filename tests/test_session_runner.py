import asyncio
from types import SimpleNamespace

import pytest

from codexmeter.ble import BleTransport
from codexmeter.device_registry import DeviceConfig
from codexmeter.device_slot import DeviceSlot
from codexmeter.usb_worker import UsbDeviceWorker


@pytest.mark.parametrize('transport', ['usb', 'bluetooth'])
@pytest.mark.parametrize('stage', ['normal', 'open_failure', 'hook_failure', 'cancel'])
def test_adapter_lifecycle(monkeypatch, transport, stage):
    async def scenario():
        slot = DeviceSlot(DeviceConfig('codexmeter-000000000001'))
        stop = asyncio.Event()
        entered = asyncio.Event()
        observed = []
        identity = SimpleNamespace(device_id=slot.config.device_id, boot='a'*16)
        class Session:
            generation = 'generation'
            failure = None
            state = {'same_host': True}
            def __init__(self, peer, host):
                observed.append(host)
                self.identity = identity
                self.closed = False
            async def open(self):
                if stage == 'open_failure': raise RuntimeError('opening')
            async def close(self): self.closed = True
        sessions=[]
        def factory(peer, host):
            session=Session(peer,host);sessions.append(session);return session
        async def hook(state, session):
            assert state.connected and slot.queue.empty()
            entered.set()
            if stage == 'hook_failure': raise RuntimeError('policy')
            if stage == 'normal': stop.set()
        slot.queue.put_nowait(object())  # Stale queue entries must be reconciled first.
        if transport == 'usb':
            discovery=SimpleNamespace(active_ports=set(), find=lambda _:SimpleNamespace(
                candidate=SimpleNamespace(port='COM-test'),identity=identity,seen_at=1),
                invalidate=lambda port:observed.append(port))
            worker=UsbDeviceWorker(slot,discovery,'b'*32,session_factory=factory)
            worker.on_reconciled=hook
            task=asyncio.create_task(worker.run(stop))
        else:
            import codexmeter.ble_session as module
            monkeypatch.setattr(module,'BleSession',lambda client, ident, host:factory(client,host))
            worker=BleTransport(host_id_provider=lambda:'b'*32)
            worker.on_reconciled=hook
            task=asyncio.create_task(worker._negotiated(SimpleNamespace(is_connected=True),identity,
                                                       slot.queue,slot.state,stop))
        if stage == 'cancel':
            await asyncio.wait_for(entered.wait(),1)
            task.cancel()
        result=await asyncio.gather(task,return_exceptions=True)
        assert observed[0]=='b'*32
        assert sessions[0].closed and not slot.state.connected and worker.session is None
        if transport == 'usb': assert not discovery.active_ports and observed[-1]=='COM-test'
        if stage == 'cancel': assert isinstance(result[0],asyncio.CancelledError)
        elif stage != 'normal':
            assert slot.state.last_error if transport == 'usb' else isinstance(result[0],RuntimeError)
    asyncio.run(scenario())
