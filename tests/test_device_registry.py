from codexmeter.device_registry import (
    DeviceRegistry,
    config_from_short_id,
    name_from_short_id,
    parse_short_id_from_name,
)


def test_parse_short_id_from_ble_name():
    assert parse_short_id_from_name("CodexMeter-A3F91C") == "A3F91C"
    assert parse_short_id_from_name("CodexMeter") is None
    assert parse_short_id_from_name("Other-A3F91C") is None


def test_config_from_short_id_uses_stable_name():
    config = config_from_short_id("a3:f9-1c", alias="Home")

    assert config.short_id == "A3F91C"
    assert config.name == "CodexMeter-A3F91C"
    assert config.alias == "Home"
    assert config.matches(short_id="A3F91C")
    assert config.matches(name=name_from_short_id("A3F91C"))


def test_registry_round_trips_devices(tmp_path):
    path = tmp_path / "devices.json"
    registry = DeviceRegistry(path)
    registry.upsert(config_from_short_id("A3F91C", alias="Home"))
    registry.save()

    loaded = DeviceRegistry.load(path)

    assert len(loaded.devices) == 1
    assert loaded.devices[0].short_id == "A3F91C"
    assert loaded.devices[0].alias == "Home"


def test_registry_recovers_from_atomic_backup(tmp_path):
    path = tmp_path / "devices.json"
    registry = DeviceRegistry(path)
    registry.upsert(config_from_short_id("A3F91C", alias="Home"))
    registry.save()
    path.write_text("{broken", encoding="utf-8")

    loaded = DeviceRegistry.load(path)

    assert loaded.devices[0].short_id == "A3F91C"


def test_registry_rejects_corruption_without_backup(tmp_path):
    path = tmp_path / "devices.json"
    path.write_text("{broken", encoding="utf-8")

    try:
        DeviceRegistry.load(path)
    except ValueError:
        return
    raise AssertionError("expected corrupt registry to fail closed")

def test_connection_mode_roundtrip_and_legacy_reader_rollback(tmp_path):
    import json
    import pytest
    from codexmeter.device_registry import DeviceConfig, DeviceRegistry
    path=tmp_path/'devices.json'
    registry=DeviceRegistry(path)
    registry.upsert(DeviceConfig('codexmeter-001122334455',alias='USB desk',connection_mode='usb_only'))
    registry.save()
    loaded=DeviceRegistry.load(path).devices[0]
    assert loaded.alias=='USB desk' and loaded.connection_mode=='usb_only' and loaded.macos_uuid is None
    raw=json.loads(path.read_text())
    # Previous v1 reader ignores unknown fields, retains a valid address-free record.
    old_reader={k:v for k,v in raw['devices'][0].items() if k!='connection_mode'}
    assert DeviceConfig.from_json(old_reader).device_id==loaded.device_id
    assert DeviceConfig.from_json(old_reader).connection_mode=='auto'
    with pytest.raises(ValueError,match='connection_mode'): DeviceConfig.from_json({**old_reader,'connection_mode':'typo'})


def test_full_ids_do_not_merge_same_name_short_id():
    from codexmeter.device_registry import DeviceConfig, DeviceRegistry
    r=DeviceRegistry()
    r.upsert(DeviceConfig('codexmeter-001122334455',short_id='001122',name='same',alias='first'))
    r.upsert(DeviceConfig('codexmeter-001122ffffff',short_id='001122',name='same',alias='second'))
    assert len(r.devices)==2

def test_host_identity_atomic_concurrent_creation(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from codexmeter.host_identity import load_host_id
    path=tmp_path/'host.json'
    with ThreadPoolExecutor(max_workers=8) as pool:
        values=list(pool.map(lambda _:load_host_id(path),range(32)))
    assert len(set(values))==1 and load_host_id(path)==values[0]
    assert not list(tmp_path.glob('.host-identity.*'))

def test_usb_registration_requires_verified_full_id_without_bluetooth(tmp_path,monkeypatch,capsys):
    import asyncio
    import builtins
    from types import SimpleNamespace
    from codexmeter import cli
    from codexmeter.device_registry import DeviceRegistry
    from codexmeter.usb_protocol import UsbIdentity
    import codexmeter.usb_transport as usb
    import json
    path=tmp_path/'devices.json';registry=DeviceRegistry(path)
    monkeypatch.setattr(cli.DeviceRegistry,'load',lambda:registry)
    async def offline(event): raise FileNotFoundError('isolated test: no daemon')
    monkeypatch.setattr(cli, 'send_event', offline)
    identity=UsbIdentity.parse(b'IDENTITY '+json.dumps({'device_id':'codexmeter-001122334455',
        'short_id':'001122','name':'CodexMeter-001122','usb':1,'app':1,'boot':'0011223344556677',
        'model':'waveshare_c6_amoled_216','fw':'test','capabilities':['screen','brightness','rotation']}).encode())
    class Discovery:
        devices={'COMfake':SimpleNamespace(identity=identity)}
        async def scan_once(self):pass
    monkeypatch.setattr(usb,'UsbDiscovery',Discovery)
    original=builtins.__import__
    def no_ble(name,*args,**kwargs):
        if name.startswith('bleak'):raise ImportError('unavailable')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',no_ble)
    args=cli.parse_args(['devices','adopt',identity.device_id,'--alias','First USB'])
    assert asyncio.run(args.func(args))==0
    loaded=DeviceRegistry._load_path(path,registry_path=path).devices[0]
    assert loaded.device_id==identity.device_id and loaded.alias=='First USB'
    assert loaded.connection_mode=='auto' and loaded.macos_uuid is None
