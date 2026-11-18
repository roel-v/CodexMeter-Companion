import asyncio
import importlib.util
from pathlib import Path
import sys
import pytest
from tests.support.usb_transport import ID, B

spec=importlib.util.spec_from_file_location('maintenance_tool',Path(__file__).parents[1]/'tools'/'maintenance.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_ble_active_registered_tool_without_explicit_id_uses_daemon_pause(monkeypatch):
    async def run():
        events=[]
        async def send(event):
            events.append(event)
            if event['type']=='ping':
                return {'ok':True,'devices':{'devices':[{'device_id':ID,'last_discovered_address':'BLE','last_discovery_source':'advertisement'}]}}
            return {'ok':True,'ready':True,'device_id':ID,'token':'b'*32,'boot':B,'port':'P'}
        async def identity(port): return {'device_id':ID,'usb':1},False
        async def forbidden(*args,**kwargs): raise AssertionError('direct bypass')
        monkeypatch.setattr(module,'send_event',send)
        monkeypatch.setattr(module,'inspect_maintenance_identity',identity)
        monkeypatch.setattr(module,'maintenance_connection',forbidden)
        result=await module.acquire('P')
        assert result['via']=='daemon' and events[-1]['device_id']==ID and events[-1]['type']=='maintenance_acquire'
    asyncio.run(run())


def test_running_legacy_daemon_unsupported_maintenance_never_bypassed(monkeypatch):
    async def run():
        async def send(event):
            if event['type']=='ping': return {'ok':True,'devices':{'devices':[{'device_id':ID}]}}
            return {'ok':False,'error':'unsupported maintenance'}
        async def identity(port):return {'device_id':ID,'usb':1},False
        monkeypatch.setattr(module,'send_event',send);monkeypatch.setattr(module,'inspect_maintenance_identity',identity)
        with pytest.raises(RuntimeError,match='unsupported maintenance'):await module.acquire('P')
    asyncio.run(run())


def test_direct_legacy_lease_has_explicit_limitation_and_no_cm1_end(monkeypatch):
    async def run():
        async def missing(event):raise FileNotFoundError()
        async def identity(port):return {'device_id':ID},True
        async def forbidden(*args,**kwargs):raise AssertionError('legacy CM1')
        monkeypatch.setattr(module,'send_event',missing);monkeypatch.setattr(module,'inspect_maintenance_identity',identity)
        monkeypatch.setattr(module,'maintenance_connection',forbidden)
        lease=await module.acquire('P',ID)
        assert lease['quiescence']=='unsupported_legacy' and lease['ready']
        await module.release(lease)
    asyncio.run(run())


def test_guard_releases_on_body_failure_and_keeps_original_pause_on_release_error(monkeypatch):
    events=[]
    async def acquire(*args):events.append('acquire');return {'via':'direct'}
    async def release(lease):events.append('release')
    monkeypatch.setattr(module,'acquire',acquire);monkeypatch.setattr(module,'release',release)
    with pytest.raises(ValueError):
        with module.MaintenanceGuard('P'):
            events.append('tool');raise ValueError('tool failed')
    assert events==['acquire','tool','release']


def test_follow_renewal_q_changes_and_delayed_old_reply_does_not_renew(monkeypatch):
    import json
    guard=module.MaintenanceGuard('P');guard.lease={'boot':B,'token':'b'*32}
    monkeypatch.setattr(module,'load_host_id',lambda:'a'*32)
    q=[]; reads=[]
    class Serial:
        def write_command(self,frame):q.append(json.loads(frame[4:])['q'])
        def read_line(self,timeout):
            reply_q = 1 if q[-1] == 2 and reads.count(2) == 0 else q[-1]
            reads.append(q[-1])
            return b'CM1 '+json.dumps({'boot':B,'token':'b'*32,'q':reply_q,'ok':True}).encode()
    guard.renew(Serial());guard.renewed=0;guard.renew(Serial())
    assert q==[1,2] and reads==[1,2,2]


def test_flashing_consumers_use_finally_and_maintenance_beside_identity_checks():
    root=Path(__file__).parents[1]
    for file in ('flash-windows.ps1','tools/update_firmware_app.ps1'):
        text=(root/file).read_text(encoding='utf-8')
        assert 'maintenance.py' in text and 'finally' in text and 'ExpectedDeviceId' in text
        assert ' release' in text and ' acquire ' in text


def test_daemon_selected_changed_port_is_not_opened_by_tool(monkeypatch):
    async def run():
        async def send(event):
            if event['type']=='ping':return {'ok':True,'devices':{'devices':[{'device_id':ID}]}}
            return {'ok':True,'ready':True,'device_id':ID,'port':'NEW','token':'b'*32}
        async def identity(port):return {'device_id':ID,'usb':1},False
        monkeypatch.setattr(module,'send_event',send);monkeypatch.setattr(module,'inspect_maintenance_identity',identity)
        with pytest.raises(RuntimeError,match='port changed'):await module.acquire('OLD')
    asyncio.run(run())


def test_direct_updated_lease_legacy_rollback_release_verifies_identity_and_never_sends_cm1(monkeypatch):
    async def run():
        inspected=[]
        async def identity(port):inspected.append(port);return {'device_id':ID},True
        async def forbidden(*args,**kwargs):raise AssertionError('legacy CM1 release')
        monkeypatch.setattr(module,'inspect_maintenance_identity',identity)
        monkeypatch.setattr(module,'maintenance_connection',forbidden)
        result=await module._release_once({'via':'direct','port':'P','device_id':ID,'boot':B,'token':'b'*32})
        assert inspected==['P'] and result['quiescence']=='unsupported_legacy'
    asyncio.run(run())


@pytest.mark.parametrize('legacy',[False,True])
def test_direct_release_changed_board_never_ends_another_boards_lease(monkeypatch,legacy):
    async def run():
        async def identity(port):return {'device_id':'codexmeter-ffffffffffff'},legacy
        async def forbidden(*args,**kwargs):raise AssertionError('wrong-board CM1')
        monkeypatch.setattr(module,'inspect_maintenance_identity',identity)
        monkeypatch.setattr(module,'maintenance_connection',forbidden)
        with pytest.raises(RuntimeError,match='identity mismatch'):
            await module._release_once({'via':'direct','port':'P','device_id':ID,'token':'b'*32})
    asyncio.run(run())


def test_direct_release_malformed_updated_identity_never_downgrades_to_legacy(monkeypatch):
    async def run():
        async def identity(port):raise RuntimeError('Malformed updated identity')
        async def forbidden(*args,**kwargs):raise AssertionError('invalid identity CM1')
        monkeypatch.setattr(module,'inspect_maintenance_identity',identity)
        monkeypatch.setattr(module,'maintenance_connection',forbidden)
        with pytest.raises(RuntimeError,match='Malformed updated identity'):
            await module._release_once({'via':'direct','port':'P','device_id':ID,'token':'b'*32})
    asyncio.run(run())


def test_known_registered_ble_identity_is_paused_before_any_port_probe(monkeypatch):
    async def run():
        events=[]
        async def send(event):
            events.append(event)
            if event['type']=='ping':
                return {'ok':True,'devices':{'devices':[{'device_id':ID,'transport':'bluetooth'}]}}
            assert event == {'type':'maintenance_acquire','device_id':ID,'port':'P','tool':True}
            return {'ok':True,'ready':True,'device_id':ID,'port':'P','token':'b'*32}
        async def forbidden(*args,**kwargs):
            raise AssertionError('Tool raced daemon discovery before maintenance')
        monkeypatch.setattr(module,'send_event',send)
        monkeypatch.setattr(module,'inspect_maintenance_identity',forbidden)
        monkeypatch.setattr(module,'maintenance_connection',forbidden)
        assert (await module.acquire('P',ID))['via']=='daemon'
        assert len(events)==2
    asyncio.run(run())
