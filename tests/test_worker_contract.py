import asyncio
import json
from types import SimpleNamespace
import pytest
from codexmeter.transport_types import WorkerSession, ConnectionWorker
from codexmeter.ble_worker import DeviceWorker
from codexmeter.usb_worker import UsbDeviceWorker
from codexmeter.ble_session import BleSession
from codexmeter.device_identity import DeviceIdentity
from tests.support.usb_transport import UsbSession,discovered,FakeChannel,H
from tests.support.ble_session import Peer,RAW

@pytest.mark.parametrize('kind',['usb','bluetooth'])
def test_actual_sessions_satisfy_management_contract(kind):
    async def scenario():
        if kind=='usb':
            session=UsbSession(discovered(),H,channel_factory=FakeChannel)
            worker=UsbDeviceWorker(None,None,H)
            worker.session=session
        else:
            session=BleSession(Peer(),DeviceIdentity.from_bytes(json.dumps(RAW).encode()),H)
            worker=DeviceWorker(None,None,SimpleNamespace(session=session))
        assert isinstance(worker,ConnectionWorker)
        assert isinstance(worker.session,WorkerSession)
        try:
            await session.open()
            state=await worker.session.read_state()
            assert state['rev']==1 and worker.session.identity.device_id=='codexmeter-001122334455'
            assert worker.session.failure is None
            assert worker.session.lifecycle=='ready'
        finally:await session.close()
    asyncio.run(scenario())

def test_old_maintenance_only_surface_is_insufficient():
    class OldSurface:
        lifecycle='claimed'
        async def try_maintenance(self):return None
    assert not isinstance(OldSurface(),WorkerSession)
