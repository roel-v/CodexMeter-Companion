from dataclasses import replace
import json
import pytest
from codexmeter import persistence
from codexmeter.device_registry import DeviceRegistry, DeviceConfig

@pytest.mark.parametrize('failure',['primary','backup','directory'])
def test_registry_commit_boundary(tmp_path,monkeypatch,failure):
    path=tmp_path/'devices.json';registry=DeviceRegistry(path)
    old=DeviceConfig('codexmeter-001122334455',connection_mode='auto')
    registry.save_device(old)
    new=replace(old,connection_mode='usb_only')
    actual=persistence.os.replace
    def replacing(src,dst):
        if (failure=='primary' and dst==path) or (failure=='backup' and dst==path.with_suffix('.json.bak')):
            raise PermissionError('injected replacement failure')
        return actual(src,dst)
    monkeypatch.setattr(persistence.os,'replace',replacing)
    if failure=='directory':
        def fail(_):raise OSError('injected directory flush failure')
        monkeypatch.setattr(persistence,'_fsync_directory',fail)
    if failure=='primary':
        with pytest.raises(PermissionError):registry.save_device(new)
        expected='auto'
    else:
        registry.save_device(new)
        expected='usb_only'
    assert registry.devices[0].connection_mode==expected
    assert DeviceRegistry.load(path).devices[0].connection_mode==expected
    backup=json.loads(path.with_suffix('.json.bak').read_text())['devices'][0]['connection_mode']
    assert backup==('auto' if failure in ('primary','backup') else 'usb_only')
    path.write_text('{broken',encoding='utf-8')
    assert DeviceRegistry.load(path).devices[0].connection_mode==backup
    assert not list(tmp_path.glob('.devices*'))
