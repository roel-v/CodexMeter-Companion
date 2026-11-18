import asyncio
from dataclasses import replace
from types import SimpleNamespace
import pytest
from codexmeter.device_coordinator import DeviceCoordinator
from codexmeter.device_registry import DeviceConfig, DeviceRegistry
from codexmeter.multi_ble import DeviceSlot, DeviceManager
from codexmeter.usb_transport import UsbDiscovery, UsbCandidate
from tests.test_usb_transport import FakeChannel, ID, H, B, discovered


class Worker:
    def __init__(self, slot, kind, events):
        self.slot, self.kind, self.events = slot, kind, events
        self.discovery = SimpleNamespace(find=lambda config: object())
        self.fail = asyncio.Event()
        self.error = None
    async def run(self, stop):
        self.events.append(('start', self.kind))
        self.slot.state.connected = True
        self.slot.state.transport = self.kind
        try:
            await self.fail.wait()
            self.slot.state.last_error = self.error or 'lost ACK'
        finally:
            self.slot.state.connected = False
            self.events.append(('close', self.kind))


def coordinator(mode='auto'):
    slot = DeviceSlot(DeviceConfig(ID, connection_mode=mode))
    usb = SimpleNamespace(candidate=None)
    usb.stable = lambda config: usb.candidate
    events, now = [], [0.]
    ble = Worker(slot, 'bluetooth', events)
    workers = []
    def factory():
        worker = Worker(slot, 'usb', events)
        workers.append(worker)
        return worker
    c = DeviceCoordinator(slot, usb, ble, factory, clock=lambda:now[0])
    return c, usb, events, now, workers


def test_auto_promotion_fences_before_claim_and_falls_back_after_unknown():
    async def run():
        c, usb, events, now, workers = coordinator()
        stop = asyncio.Event()
        await c.step(stop); await asyncio.sleep(0)
        assert events == [('start','bluetooth')]
        usb.candidate = object()
        await c.step(stop); await asyncio.sleep(0)
        assert events == [('start','bluetooth'),('close','bluetooth'),('start','usb')]
        workers[0].fail.set(); await asyncio.sleep(0)
        await c.step(stop); await asyncio.sleep(0)
        assert c.kind == 'bluetooth' and c.retry_at['usb'] == 1
        assert events[-2:] == [('close','usb'),('start','bluetooth')]
        # Stable candidate cannot cause immediate oscillation while backoff applies.
        await c.step(stop)
        assert c.kind == 'bluetooth'
        now[0] = 1
        await c.step(stop); await asyncio.sleep(0)
        assert c.kind == 'usb' and len(workers) == 2
        await c.fence()
    asyncio.run(run())


@pytest.mark.parametrize('mode,expected', [('usb_only','usb'),('bluetooth_only','bluetooth')])
def test_forced_modes_never_start_disallowed_transport(mode,expected):
    async def run():
        c, usb, events, now, workers = coordinator(mode)
        usb.candidate = object()
        await c.step(asyncio.Event()); await asyncio.sleep(0)
        assert c.kind == expected
        c.slot.config = replace(c.slot.config, connection_mode='bluetooth_only' if mode=='usb_only' else 'usb_only')
        await c.step(asyncio.Event()); await asyncio.sleep(0)
        assert events[1] == ('close',expected)
        assert c.kind != expected
        await c.fence()
    asyncio.run(run())


def test_owner_busy_has_bounded_retry_and_no_generic_failure_promotion():
    async def run():
        c, usb, events, now, workers = coordinator('bluetooth_only')
        await c.step(asyncio.Event()); await asyncio.sleep(0)
        c.ble.error='busy_usb'; c.ble.fail.set(); await asyncio.sleep(0)
        await c.step(asyncio.Event())
        assert c.slot.state.connection_state == 'owned_elsewhere'
        assert c.retry_at['bluetooth'] == 2 and c.task is None
        now[0] = 1.9
        await c.step(asyncio.Event())
        assert c.task is None
    asyncio.run(run())


def test_stability_requires_second_same_boot_probe_and_pause_drains_open():
    async def run():
        now = [0.]
        channels=[]
        def factory(port):
            channel=FakeChannel(port); channels.append(channel); return channel
        d=UsbDiscovery(candidates=lambda:[UsbCandidate('P','I')],channel_factory=factory,clock=lambda:now[0])
        config=DeviceConfig(ID)
        await d.scan_once(); assert d.stable(config) is None
        now[0]=1.9; await d.scan_once(); assert d.stable(config) is None
        now[0]=2; await d.scan_once(); assert d.stable(config)
        await d.pause('P',ID,'I')
        count=len(channels)
        d.devices.clear(); d.active_ports.clear()
        await d.scan_once()
        assert len(channels)==count
        # Suppression follows the PnP instance even after a COM-number change.
        d.candidates=lambda:[UsbCandidate('NEW','I')]
        await d.scan_once(); assert len(channels)==count
    asyncio.run(run())


def test_pause_cancels_probe_waiting_for_semaphore_or_open():
    async def run():
        gate=asyncio.Event(); closed=[]
        class Channel(FakeChannel):
            async def open(self):
                await gate.wait()
            async def close(self):
                closed.append(self.port)
        d=UsbDiscovery(channel_factory=Channel)
        task=asyncio.create_task(d._probe(UsbCandidate('P','I')))
        await asyncio.sleep(0)
        await d.pause('P',ID,'I')
        assert task.done() and closed==['P'] and not d._probing
        d=UsbDiscovery(channel_factory=Channel)
        await d._semaphore.acquire(); await d._semaphore.acquire()
        task=asyncio.create_task(d._probe(UsbCandidate('P','I')))
        await asyncio.sleep(0)
        await d.pause('P',ID,'I')
        assert task.done() and not d._probing
    asyncio.run(run())


def manager(configs, **extra):
    return DeviceManager(configs,host_id=H,connect_timeout_sec=.1,disconnect_timeout_sec=.1,
        write_timeout_sec=.1,ack_timeout_sec=.1,notify_timeout_sec=.1,healthcheck_interval_sec=1,**extra)


def test_live_mode_atomic_persistence_alias_disabled_and_rollback(tmp_path,monkeypatch):
    async def run():
        registry=DeviceRegistry(tmp_path/'devices.json')
        config=DeviceConfig(ID,alias='Desk',enabled=False)
        registry.upsert(config); registry.save()
        m=manager([config],registry=registry)
        result=await m.device_operation({'type':'device_mode','device_id':ID,'connection_mode':'usb_only'})
        loaded=DeviceRegistry.load(registry.path).devices[0]
        assert result['ok'] and loaded.connection_mode=='usb_only' and loaded.alias=='Desk' and not loaded.enabled
        old=m.slots[0].config
        def fail(): raise OSError('read only')
        monkeypatch.setattr(registry,'save',fail)
        with pytest.raises(OSError):
            await m.device_operation({'type':'device_mode','device_id':ID,'connection_mode':'auto'})
        assert m.slots[0].config==old and registry.devices[0]==old
        for event in ({'device_id':ID,'connection_mode':'invalid'},{'device_id':'001122','connection_mode':'auto'}):
            with pytest.raises(ValueError): await m.device_operation({'type':'device_mode',**event})
    asyncio.run(run())


def test_local_pause_without_usb_survives_restart_and_does_not_affect_peer(tmp_path):
    async def run():
        registry=DeviceRegistry(tmp_path/'devices.json')
        configs=[DeviceConfig(ID),DeviceConfig('codexmeter-ffffffffffff')]
        registry.devices=configs;registry.save()
        m=manager(configs,registry=registry)
        result=await m.device_operation({'type':'maintenance_acquire','device_id':ID})
        assert result['local_pause'] and not result['ready']
        assert not m.slots[1].config.maintenance
        restarted=manager(DeviceRegistry.load(registry.path).devices)
        restarted._coordinators_init()
        assert restarted.slots[0].config.maintenance and ID in restarted.usb_discovery.paused_ids
        await restarted.device_operation({'type':'maintenance_resume','device_id':ID})
        assert restarted.slots[0].config.maintenance is None
    asyncio.run(run())


def test_fresh_policy_is_observed_after_reconciliation_and_never_manual_on():
    async def run():
        events=[]
        class Detector:
            async def is_locked(self):
                assert slot.state.device_state['manual_on'] is False
                events.append('OS now'); return False
        m=manager([DeviceConfig(ID)],policy_detector=Detector())
        slot=m.slots[0]; slot.state.device_state={'manual_on':False}
        class Session:
            async def send(self,payload):
                events.append(payload.data)
                return SimpleNamespace(outcome='accepted')
        await m._reconciled(slot,Session())
        assert events[0]=='OS now' and events[1]['why']=='unlock'
        assert slot.state.device_state['manual_on'] is False
    asyncio.run(run())


def test_recovery_view_excludes_usb_maintenance_busy_and_missing_adapter():
    async def run():
        m=manager([DeviceConfig(ID),DeviceConfig('codexmeter-ffffffffffff')])
        usb,ble=m.slots
        usb.state.connected=True;usb.state.transport='usb'
        ble.state.transport='bluetooth';ble.state.last_error='real BLE ACK failure';ble.state.ble_failures=1
        status=m.bluetooth_status()
        assert status['configured_count']==1 and not status['connected']
        ble.state.connection_state='owned_elsewhere';ble.state.last_error='busy_usb'
        assert m.bluetooth_status()['configured_count']==0
        ble.state.connection_state='disconnected';ble.state.last_error=None;m.ble_available=False
        assert m.bluetooth_status()['configured_count']==0
    asyncio.run(run())


def test_maintenance_updated_lease_persists_before_quiescence_and_resume_rediscovers(tmp_path,monkeypatch):
    async def run():
        import codexmeter.usb_transport as usb_module
        registry=DeviceRegistry(tmp_path/'devices.json')
        config=DeviceConfig(ID);registry.devices=[config];registry.save()
        d=UsbDiscovery(); item=discovered('OLD'); d.devices['OLD']=item
        m=manager([config],registry=registry,usb_discovery=d)
        events=[]
        async def inspect(port): return {'device_id':ID,'usb':1},False
        monkeypatch.setattr(usb_module,'inspect_maintenance_identity',inspect)
        class Session:
            identity=SimpleNamespace(boot=B)
            token='b'*32
            async def close(self,**kw): events.append(('close',kw))
            async def end_maintenance(self): events.append('end')
        async def connect(port,host,token=None,expected_id=None):
            assert DeviceRegistry.load(registry.path).devices[0].maintenance
            events.append(('open',port));return Session()
        monkeypatch.setattr(usb_module,'maintenance_connection',connect)
        acquired=await m.device_operation({'type':'maintenance_acquire','device_id':ID,'tool':True})
        assert acquired['ready'] and acquired['quiescence']=='device_maintenance'
        assert 'OLD' in d.paused_ports and d.find(config)
        restarted=manager(DeviceRegistry.load(registry.path).devices,registry=registry,usb_discovery=d)
        restarted._coordinators_init()
        with pytest.raises(ValueError,match='token'):
            await restarted.device_operation({'type':'maintenance_release','device_id':ID,'token':'bad'})
        # Port unavailable/busy cannot clear even an explicit manual Resume.
        async def scan(self): self.devices={}
        monkeypatch.setattr(usb_module.UsbDiscovery,'scan_once',scan)
        with pytest.raises(ValueError,match='pause retained'):
            await restarted.device_operation({'type':'maintenance_resume','device_id':ID})
        assert restarted.slots[0].config.maintenance
        async def moved(self): self.devices={'NEW':discovered('NEW')}
        monkeypatch.setattr(usb_module.UsbDiscovery,'scan_once',moved)
        await restarted.device_operation({'type':'maintenance_release','device_id':ID,'token':acquired['token']})
        assert ('open','NEW') in events and 'end' in events
        assert restarted.slots[0].config.maintenance is None
    asyncio.run(run())


def test_quiescence_failure_keeps_durable_pause_and_probes_suppressed(tmp_path,monkeypatch):
    async def run():
        import codexmeter.usb_transport as usb_module
        registry=DeviceRegistry(tmp_path/'devices.json');registry.devices=[DeviceConfig(ID)];registry.save()
        d=UsbDiscovery();d.devices['P']=discovered('P')
        m=manager(registry.devices,registry=registry,usb_discovery=d)
        async def fail(port): raise RuntimeError('busy_usb')
        monkeypatch.setattr(usb_module,'inspect_maintenance_identity',fail)
        with pytest.raises(RuntimeError,match='busy_usb'):
            await m.device_operation({'type':'maintenance_acquire','device_id':ID,'tool':True})
        record=DeviceRegistry.load(registry.path).devices[0].maintenance
        assert record and record['ready'] is False
        assert 'P' in d.paused_ports and ID in d.paused_ids
        assert m.slots[0].state.connection_state=='maintenance'
    asyncio.run(run())


def test_live_registry_adopt_mode_and_maintenance_do_not_overwrite_each_other(tmp_path):
    async def run():
        registry=DeviceRegistry(tmp_path/'devices.json');registry.devices=[DeviceConfig(ID)];registry.save()
        m=manager(registry.devices,registry=registry)
        state=m.slots[0].state
        new=DeviceConfig('codexmeter-ffffffffffff',alias='New',connection_mode='usb_only')
        await asyncio.gather(
            m.device_operation({'type':'device_registry_update','action':'adopt','device_id':new.device_id,'config':new.to_json()}),
            m.device_operation({'type':'device_mode','device_id':ID,'connection_mode':'usb_only'}),
            m.device_operation({'type':'maintenance_acquire','device_id':ID}))
        loaded=DeviceRegistry.load(registry.path)
        assert len(m.slots)==2 and len(loaded.devices)==2 and m.slots[0].state is state
        assert loaded.find(ID).maintenance and loaded.find(ID).connection_mode=='usb_only'
        assert loaded.find(new.device_id).alias=='New'
        await m.device_operation({'type':'devices_reload'})
        assert len(m.slots)==2 and m.slots[0].state is state
    asyncio.run(run())


def test_usb_failures_without_any_ble_evidence_never_enable_radio_recovery():
    async def run():
        m=manager([DeviceConfig(ID)])
        s=m.slots[0].state;s.transport='usb';s.consecutive_failures=200;s.last_error='USB heartbeat lost'
        m.ble_available=True
        assert m.bluetooth_status()['configured_count']==0
    asyncio.run(run())


def test_current_locked_policy_respects_timeout_after_fresh_os_read():
    async def run():
        import time
        class Detector:
            async def is_locked(self): return True
        m=manager([DeviceConfig(ID)],policy_detector=Detector(),screen_timeout_sec=60)
        sent=[]
        class Session:
            async def send(self,p): sent.append(p);return SimpleNamespace(outcome='accepted')
        await m._reconciled(m.slots[0],Session())
        assert sent[-1].data['on'] is True
        m.observe_lock(True,time.monotonic()-61)
        m._live_policy.locked_since=time.monotonic()-61
        await m._reconciled(m.slots[0],Session())
        assert sent[-1].data['on'] is False and sent[-1].data['why']=='lock'
    asyncio.run(run())


def test_discovery_survives_cancelled_child_probe_and_resumes_target():
    async def run():
        entered=asyncio.Event()
        class Channel(FakeChannel):
            async def open(self):
                if self.port=='TARGET':
                    entered.set();await asyncio.Event().wait()
        d=UsbDiscovery(candidates=lambda:[UsbCandidate('TARGET','T'),UsbCandidate('PEER','Q')],channel_factory=Channel)
        scan=asyncio.create_task(d.scan_once())
        await entered.wait();await d.pause('TARGET',ID,'T');await scan
        assert 'PEER' in d.devices
        d.paused_ports.clear();d.paused_instances.clear();d.paused_ids.clear();d.channel_factory=FakeChannel
        await d.scan_once()
        assert 'TARGET' in d.devices and 'PEER' in d.devices
    asyncio.run(run())


@pytest.mark.parametrize('old_quiescence', ['device_maintenance','unsupported_legacy'])
def test_resume_after_rollback_to_legacy_and_changed_com(old_quiescence,monkeypatch):
    async def run():
        import codexmeter.usb_transport as usb_module
        record={'port':'OLD','token':'b'*32,'quiescence':old_quiescence,'instance_id':'OLDI'}
        m=manager([DeviceConfig(ID,maintenance=record)])
        async def scan(self):self.unsupported={'NEW':{'port':'NEW','device_id':ID}}
        async def identity(port):assert port=='NEW';return {'device_id':ID},True
        async def forbidden(*args,**kwargs):raise AssertionError('No CM1 on legacy firmware')
        monkeypatch.setattr(usb_module.UsbDiscovery,'scan_once',scan)
        monkeypatch.setattr(usb_module,'inspect_maintenance_identity',identity)
        monkeypatch.setattr(usb_module,'maintenance_connection',forbidden)
        await m.device_operation({'type':'maintenance_resume','device_id':ID})
        assert m.slots[0].config.maintenance is None
    asyncio.run(run())


def test_verified_full_ids_do_not_merge_by_short_id(tmp_path):
    registry=DeviceRegistry(tmp_path/'devices.json')
    registry.upsert(DeviceConfig(ID,short_id='SAME'))
    registry.upsert(DeviceConfig('codexmeter-ffffffffffff',short_id='SAME'))
    assert len(registry.devices)==2


@pytest.mark.parametrize('command,arguments', [('rename',['Desk']),('disable',[]),('enable',[])])
def test_offline_cli_registry_mutation_preserves_maintenance(command,arguments,tmp_path,monkeypatch,capsys):
    from codexmeter import cli
    async def run():
        record={'port':'P','token':'b'*32,'kind':'tool','ready':True}
        registry=DeviceRegistry(tmp_path/'devices.json');registry.devices=[DeviceConfig(ID,maintenance=record)];registry.save()
        monkeypatch.setattr(cli.DeviceRegistry,'load',lambda:registry)
        async def offline(event):raise FileNotFoundError('isolated offline')
        monkeypatch.setattr(cli,'send_event',offline)
        args=cli.parse_args(['devices',command,ID,*arguments])
        assert await args.func(args)==0
        assert registry.devices[0].maintenance==record
        # Read the persisted file directly because DeviceRegistry.load is isolated above.
        import json
        assert json.loads(registry.path.read_text())['devices'][0]['maintenance']==record
    asyncio.run(run())


def test_registry_adoption_rejects_mismatched_event_and_config_id():
    async def run():
        m=manager([DeviceConfig(ID)])
        m.registry=DeviceRegistry()
        with pytest.raises(ValueError,match='ID mismatch'):
            await m.device_operation({'type':'device_registry_update','action':'adopt','device_id':ID,
                'config':DeviceConfig('codexmeter-ffffffffffff').to_json()})
        assert len(m.slots)==1 and m.slots[0].config.device_id==ID
    asyncio.run(run())
