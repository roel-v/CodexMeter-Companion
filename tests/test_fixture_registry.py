import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from codexmeter.device_registry import DeviceRegistry, DeviceConfig
from fixture_registry import isolated_registry
import validate_usb_autofailure as fixture

@pytest.mark.parametrize('fails',[False,True])
def test_fault_fixture_preserves_input_and_cleans_working_registry(tmp_path,monkeypatch,fails):
    source=tmp_path/'original.json';registry=DeviceRegistry(source)
    registry.save_device(DeviceConfig('codexmeter-001122334455'))
    baseline={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    scratch=tmp_path/'scratch';original=fixture.usb.open_serial
    async def simulated(args,working):
        assert working.path!=source
        working.save_device(replace(working.devices[0],maintenance={'token':'fixture'}))
        fixture.usb.open_serial=object()
        if fails:raise RuntimeError('injected fixture failure')
    monkeypatch.setattr(fixture,'run_registry',simulated)
    args=SimpleNamespace(registry=source,output=tmp_path/'results'/'case.json',scratch_root=scratch)
    if fails:
        with pytest.raises(RuntimeError):asyncio.run(fixture.run(args))
    else:asyncio.run(fixture.run(args))
    assert fixture.usb.open_serial is original
    assert not list(scratch.iterdir())
    assert all((tmp_path/name).read_bytes()==data for name,data in baseline.items())

def test_paused_registry_rejected_before_hardware(tmp_path):
    source=tmp_path/'paused.json';registry=DeviceRegistry(source)
    registry.save_device(DeviceConfig('codexmeter-001122334455',maintenance={'ready':False}))
    with pytest.raises(ValueError,match='maintenance'):
        with isolated_registry(source,tmp_path/'scratch'):pytest.fail('must not enter fixture')
    assert not list((tmp_path/'scratch').iterdir())
