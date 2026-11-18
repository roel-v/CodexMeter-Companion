import asyncio
import time
import pytest
from codexmeter.events import EventServer
from codexmeter.delivery_pump import DeliveryPump
from codexmeter.payloads import Payload
from tests.test_mixed_displays import manager, config
from tests.test_usb_transport import UsbSession, discovered, FakeChannel, H, B
from codexmeter.command_results import CommandResults
from codexmeter.delivery import negotiated_replay, sweep_commands
from codexmeter.transport_types import TransportError


def setup_manager():
    m=manager([config()]);state=m.slots[0].state
    state.connected=True;state.device_state={'boot':B,'rev':1}
    return m,state


async def admit(m, command='brightness', value=40):
    reply=await m.control_device({'device_id':config().device_id,'command':command,'value':value})
    return reply['command_id'],m.slots[0].queue.get_nowait()


@pytest.mark.parametrize('error,expected', [(None,'applied'),('unsupported','rejected'),('conflict','rejected')])
def test_real_session_command_results(error,expected):
    async def run():
        m,state=setup_manager();key,p=await admit(m)
        c=FakeChannel('fake');c.rejected=error
        s=UsbSession(discovered(),H,channel_factory=lambda _:c)
        await s.open()
        try:
            await DeliveryPump(state,s).deliver(p)
            assert state.commands.get(key)['status']==expected
            assert p.command_id not in p.to_json_bytes().decode()
            assert not state.explicit_intents
        finally:await s.close(release=False)
    asyncio.run(run())


def test_ack_survives_readback_failure():
    async def run():
        m,state=setup_manager();key,p=await admit(m)
        s=UsbSession(discovered(),H,channel_factory=FakeChannel);await s.open()
        async def fail():raise TransportError('readback failed')
        s.read_state=fail
        try:
            with pytest.raises(TransportError):await DeliveryPump(state,s).deliver(p)
            result=state.commands.get(key)
            assert result['status']=='applied' and result['readback_error']
        finally:await s.close(release=False)
    asyncio.run(run())


def test_ack_is_visible_while_readback_is_pending():
    async def run():
        m,state=setup_manager();key,p=await admit(m)
        s=UsbSession(discovered(),H,channel_factory=FakeChannel);await s.open()
        entered=asyncio.Event();release=asyncio.Event()
        async def read():
            entered.set();await release.wait();raise TransportError('readback failed')
        s.read_state=read
        task=asyncio.create_task(DeliveryPump(state,s).deliver(p))
        try:
            await asyncio.wait_for(entered.wait(),1)
            result=state.commands.get(key)
            assert result['status']=='applied' and result['readback_pending']
            release.set()
            with pytest.raises(TransportError):await task
            result=state.commands.get(key)
            assert result['status']=='applied' and not result['readback_pending'] and result['readback_error']
        finally:
            release.set();await s.close(release=False)
    asyncio.run(run())


def test_unknown_cannot_replay():
    async def run():
        m,state=setup_manager();key,p=await admit(m)
        c=FakeChannel('fake');c.drop=2
        s=UsbSession(discovered(),H,channel_factory=lambda _:c);await s.open();s.timeout=.001
        with pytest.raises(TransportError):await DeliveryPump(state,s).deliver(p)
        assert state.commands.get(key)['status']=='unknown'
        assert p not in negotiated_replay(state,same_host=True)
        assert state.desired_settings=={}
        assert len([f for f in c.writes if f.startswith(b'CM1 DATA')])==2
    asyncio.run(run())


def test_superseded_command_waiting_for_send_lock_never_writes():
    async def run():
        m,state=setup_manager();key,p=await admit(m)
        s=UsbSession(discovered(),H,channel_factory=FakeChannel);await s.open()
        try:
            await s._send_lock.acquire()
            task=asyncio.create_task(DeliveryPump(state,s).deliver(p));await asyncio.sleep(0)
            other,_=await admit(m,value=50)
            s._send_lock.release();await task
            assert state.commands.get(key)['status']=='superseded'
            assert state.commands.get(other)['status']=='queued'
            assert not any(f.startswith(b'CM1 DATA') for f in s.channel.writes)
        finally:await s.close(release=False)
    asyncio.run(run())


@pytest.mark.parametrize('sent',[False,True])
def test_cancellation_preserves_unsent_but_marks_sent_unknown(sent):
    async def run():
        m,state=setup_manager();key,p=await admit(m)
        entered=asyncio.Event()
        class Channel(FakeChannel):
            async def write(self,frame):
                if frame.startswith(b'CM1 DATA'):
                    entered.set();await asyncio.Future()
                await super().write(frame)
        s=UsbSession(discovered(),H,channel_factory=Channel);await s.open()
        try:
            if not sent:await s._send_lock.acquire()
            task=asyncio.create_task(DeliveryPump(state,s).deliver(p))
            if sent:await entered.wait()
            else:await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            assert state.commands.get(key)['status']==('unknown' if sent else 'queued')
        finally:
            if s._send_lock.locked():s._send_lock.release()
            await s.close(release=False)
    asyncio.run(run())


def test_ledger_capacity_expiry_retention_and_generation_fence():
    now=[0.];ledger=CommandResults(clock=lambda:now[0])
    payloads=[Payload('control',{'cmd':'brightness','value':50},f'{i:032x}') for i in range(65)]
    for p in payloads[:64]:ledger.admit(p)
    with pytest.raises(ValueError):ledger.admit(payloads[64])
    p=payloads[0];assert ledger.start(p,'first')
    ledger.finish(p,'applied',generation='other')
    assert ledger.get(p.command_id)['status']=='sending'
    ledger.finish(p,'applied',generation='first')
    now[0]=60
    assert ledger.get(payloads[1].command_id)['status']=='expired'
    ledger.admit(payloads[64]);ledger.finish(payloads[64],'rejected')
    ledger.prune();assert len(ledger.records)==64
    now[0]=660;ledger.prune();assert not ledger.records


def test_expiry_and_owner_change_remove_replay_intent():
    async def run():
        m,state=setup_manager();now=[0.];state.commands=CommandResults(clock=lambda:now[0])
        key,p=await admit(m);now[0]=60;sweep_commands(state)
        assert state.commands.get(key)['status']=='expired' and not state.explicit_intents
        key,p=await admit(m);negotiated_replay(state,same_host=False)
        assert state.commands.get(key)['status']=='cancelled'
    asyncio.run(run())


@pytest.mark.parametrize('outcome',['ok','reject','timeout'])
def test_legacy_ack_command_outcomes(outcome):
    from codexmeter.ble import BleTransport, BleAckTracker
    async def run():
        m,state=setup_manager();state.device_state={};key,p=await admit(m)
        tracker=BleAckTracker()
        class Client:
            async def write_gatt_char(self,*args,**kwargs):
                if outcome!='timeout':tracker.notify(b'{"ack":true}' if outcome=='ok' else b'{"ack":false}')
        transport=BleTransport(ack_timeout_sec=.001)
        if outcome=='ok':await transport._write_payload(Client(),p,tracker,state)
        else:
            with pytest.raises(Exception):await transport._write_payload(Client(),p,tracker,state)
        assert state.commands.get(key)['status']=={'ok':'applied','reject':'rejected','timeout':'unknown'}[outcome]
        if outcome=='ok':assert state.desired_settings['brightness'].command_id is None
        else:assert not state.desired_settings
    asyncio.run(run())


def test_admission_and_conflict_have_durable_correlated_result():
    async def run():
        m=manager([config()]); state=m.slots[0].state
        state.connected=True; state.device_state={'boot':B,'rev':1}
        server=EventServer(m.broadcast,device_controller=m.control_device,device_operator=m.device_operation)
        reply=await server._dispatch({'type':'device_control','device_id':config().device_id,
                                     'command':'brightness','value':40})
        assert 'command_id' in reply
        channel=FakeChannel('fake');channel.rejected='conflict'
        session=UsbSession(discovered(),H,channel_factory=lambda _:channel)
        await session.open()
        try:
            await DeliveryPump(state,session).deliver(m.slots[0].queue.get_nowait())
            # A successful telemetry ACK must not erase the command failure.
            channel.rejected=None
            await m.broadcast(Payload('activity',{'k':'activity','run':2}))
            await DeliveryPump(state,session).deliver(m.slots[0].queue.get_nowait())
            result=await server._dispatch({'type':'command_result','device_id':config().device_id,
                                          'command_id':reply['command_id']})
            assert result['result']['status']=='rejected'
            assert result['result']['reason']=='conflict'
            assert result['result']['readback']['rev']==1
        finally:await session.close(release=False)
    asyncio.run(run())
