import asyncio
import time
import pytest
from codexmeter.events import EventServer
from codexmeter.payloads import Payload
from codexmeter.delivery import DeliveryState
from codexmeter.delivery_pump import DeliveryPump
from codexmeter.queueing import put_latest
from codexmeter.usb_transport import UsbSession
from tests.test_usb_transport import discovered, FakeChannel, H, B
from tests.test_mixed_displays import manager, config


def test_manual_screen_ipc_binds_each_device_and_reports_partial_admission():
    async def run():
        m = manager([config(1), config(2), config(3)])
        for index, slot in enumerate(m.slots[:2]):
            slot.state.connected = True
            slot.state.device_state = {'boot': B, 'rev': index + 1}
        server = EventServer(m.broadcast, device_controller=m.control_device)
        reply = await server._dispatch({'type':'screen','on':False,'reason':'manual'})
        assert not reply['ok'] and len(reply['results']) == 3
        assert [r['ok'] for r in reply['results']] == [True, True, False]
        for index, slot in enumerate(m.slots[:2]):
            p = slot.queue.get_nowait()
            assert slot.state.explicit_intents[id(p)][:2] == (B, index + 1)
        assert m.slots[2].queue.empty()
        with pytest.raises(ValueError):
            await server._dispatch({'type':'screen','on':False,'reason':'lock'})
    asyncio.run(run())


def test_screen_queue_keeps_manual_and_policy_separate():
    async def run():
        for reasons in [('manual','unlock'), ('lock','manual')]:
            q = asyncio.Queue(4)
            for reason in reasons:
                await put_latest(q, Payload('control',{'cmd':'screen','why':reason,'on':False}))
            assert q.qsize() == 2
    asyncio.run(run())


def test_explicit_control_expires_while_waiting_for_serialization():
    async def run():
        now = [10.0]
        s = UsbSession(discovered(), H, channel_factory=FakeChannel, clock=lambda:now[0])
        await s.open()
        try:
            state = DeliveryState()
            p = Payload('control',{'k':'control','cmd':'brightness','value':40})
            state.explicit_intents[id(p)] = (B, 1, 10.0)
            state.explicit_payloads[id(p)] = p
            async with s._send_lock:  # Hold the real dispatch lock to exercise final-send expiry.
                task = asyncio.create_task(DeliveryPump(state,s).deliver(p))
                await asyncio.sleep(0)
                now[0] = 70.0
            await task
            assert not any(b'DATA' in frame for frame in s.channel.writes)
            assert not state.explicit_intents and not state.explicit_payloads
            assert state.last_error == 'expired explicit intent'
        finally:
            await s.close(release=False)
    asyncio.run(run())

@pytest.mark.parametrize('age,accepted', [(59.999,True),(60,False),(120,False)])
def test_final_send_deadline_boundary(age, accepted):
    async def run():
        s=UsbSession(discovered(),H,channel_factory=FakeChannel,clock=lambda:age)
        await s.open()
        try:
            p=Payload('control',{'k':'control','cmd':'screen','on':False,'why':'manual'})
            result=await s.send(p,expected_boot=B,expected_revision=1,intent_deadline=60)
            assert (result.outcome=='accepted') is accepted
            assert any(b'DATA' in f for f in s.channel.writes) is accepted
        finally: await s.close(release=False)
    asyncio.run(run())


def test_queue_eviction_cannot_resurrect_manual_intent():
    async def run():
        m=manager([config()]);slot=m.slots[0]
        slot.state.connected=True;slot.state.device_state={'boot':B,'rev':1}
        slot.queue=asyncio.Queue(2)
        await m.control_device({'device_id':slot.config.device_id,'command':'screen','value':False})
        manual=slot.state.desired_control
        await m.broadcast(Payload('control',{'cmd':'screen','why':'unlock','on':True}))
        assert slot.queue.qsize()==2 and id(manual) in slot.state.explicit_intents
        await m.broadcast(Payload('activity',{'k':'activity','run':1}))
        assert id(manual) not in slot.state.explicit_intents
        assert slot.state.desired_control is None
    asyncio.run(run())


def test_cli_screen_routes_target_and_partial_exit(monkeypatch,capsys):
    from codexmeter.cli import run_screen
    from types import SimpleNamespace
    async def send(event):
        assert event=={'type':'screen','on':False,'reason':'manual','device_id':None}
        return {'ok':False,'results':[{'ok':True},{'ok':False,'error':'disconnected'}]}
    monkeypatch.setattr('codexmeter.cli.send_event',send)
    assert asyncio.run(run_screen(SimpleNamespace(on=False,reason='manual',device_id=None)))==1
    assert 'disconnected' in capsys.readouterr().out

@pytest.mark.parametrize('trigger',['reconnect','refresh','health'])
def test_legacy_consumers_do_not_refresh_expired_usage(trigger):
    from codexmeter.ble import BleTransport
    from codexmeter.delivery import remember_desired
    async def run():
        stop=asyncio.Event();writes=[]
        class Client:
            is_connected=False
            async def connect(self): self.is_connected=True
            async def disconnect(self): self.is_connected=False
            async def start_notify(self,char,callback):
                from codexmeter.settings import REQ_CHAR_UUID, TX_CHAR_UUID
                if char==TX_CHAR_UUID: self.ack=callback
                if trigger=='refresh' and char==REQ_CHAR_UUID: callback(None,b'R')
            async def write_gatt_char(self,char,data,**k):
                writes.append(data);self.ack(None,b'{"ack":true}')
        class Transport(BleTransport):
            def _create_client(self,target): return Client()
            async def _write_payload(self,client,payload,*args):
                # Keep the real filtering boundary, replace only actual GATT serialization below it.
                return await super()._write_payload(client,payload,*args)
        state=DeliveryState();p=Payload('usage',{'k':'usage'})
        remember_desired(p,state);state.observed_at['usage']=time.monotonic()-3600
        transport=Transport(healthcheck_interval_sec=.01)
        task=asyncio.create_task(transport.connect_and_write(object(),asyncio.Queue(),state,stop))
        await asyncio.sleep(.04)
        stop.set()
        await task
        assert writes==[]
    asyncio.run(run())


def test_maintenance_uses_fresh_endpoint_after_closed_session(monkeypatch):
    from types import SimpleNamespace
    from tests.test_device_coordinator import manager as make_manager
    from tests.test_usb_transport import ID
    from codexmeter.device_registry import DeviceConfig
    async def run():
        s=UsbSession(discovered(),H,channel_factory=FakeChannel)
        await s.open();await s.close(release=False)
        m=make_manager([DeviceConfig(ID)]);m._coordinators_init();c=m.coordinators[0]
        c.worker=SimpleNamespace(session=s);c.kind='usb'
        m.usb_discovery.devices['COMTEST']=discovered()
        async def inspect(port): return {'device_id':ID},False
        class Maintenance:
            identity=SimpleNamespace(boot=B)
            token='c'*32
            async def close(self,**kw): pass
        async def connect(*args):
            assert c.worker is None, 'old owner must be fenced before reopening USB'
            return Maintenance()
        monkeypatch.setattr('codexmeter.usb_transport.inspect_maintenance_identity',inspect)
        monkeypatch.setattr('codexmeter.usb_transport.maintenance_connection',connect)
        result=await m.device_operation({'type':'maintenance_acquire','device_id':ID,'tool':True})
        assert result['ready']
    asyncio.run(run())


def test_maintenance_waits_for_native_cleanup_before_unsent_result():
    async def run():
        entered=asyncio.Event();finish=asyncio.Event()
        class Channel(FakeChannel):
            async def close(self):
                entered.set();await finish.wait();await super().close()
        s=UsbSession(discovered(),H,channel_factory=Channel)
        await s.open()
        closing=asyncio.create_task(s.close(release=False));await entered.wait()
        attempt=asyncio.create_task(s.try_maintenance());await asyncio.sleep(0)
        assert not attempt.done()
        finish.set();await closing
        assert await attempt is None
        assert not any(b'"op":"maint"' in f for f in s.channel.writes)
    asyncio.run(run())


def test_maintenance_unknown_outcome_is_not_treated_as_unsent():
    from codexmeter.transport_types import UnknownDelivery
    async def run():
        class Channel(FakeChannel):
            async def write(self,frame):
                if b'"op":"maint"' in frame:
                    self.writes.append(frame);raise UnknownDelivery('injected uncertain write')
                await super().write(frame)
        s=UsbSession(discovered(),H,channel_factory=Channel)
        await s.open()
        try:
            with pytest.raises(UnknownDelivery): await s.try_maintenance()
        finally: await s.close(release=False)
    asyncio.run(run())


def test_usage_rejects_semantic_kind_mismatch():
    async def run():
        sent=[]
        async def sink(p): sent.append(p)
        server=EventServer(sink)
        for payload in ({'v':1,'k':'activity','run':2},{'v':1,'k':'control'},{'v':2,'k':'usage'}):
            with pytest.raises(ValueError): await server._dispatch({'type':'usage','payload':payload})
        assert sent==[]
    asyncio.run(run())


def test_validation_input_is_opt_in_and_preserves_both_kinds():
    async def run():
        sent=[]
        async def sink(p): sent.append(p)
        event={'type':'validation_payload','payload':{'v':1,'k':'activity','run':2}}
        with pytest.raises(ValueError): await EventServer(sink)._dispatch(event)
        server=EventServer(sink,validation_mode=True)
        await server._dispatch(event)
        await server._dispatch({'type':'validation_payload','payload':{'v':1,'k':'usage','td':42}})
        assert [p.kind for p in sent]==['activity','usage']
        with pytest.raises(ValueError): await server._dispatch({'type':'activity','count':99})
        assert server.background_tasks(asyncio.Event())==[]
    asyncio.run(run())
