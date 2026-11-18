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
            async with s.exclusive_delivery():
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
