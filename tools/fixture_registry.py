"""Disposable mutable registries for hardware fixtures; inputs are read-only."""
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
from codexmeter.device_registry import DeviceRegistry


@contextmanager
def isolated_registry(source, scratch_root=None):
    if scratch_root is None and sys.platform=='win32':
        scratch_root=Path('D:/build/CodexMeter/tmp')
    if scratch_root is not None:
        scratch_root=Path(scratch_root).resolve()
        if sys.platform=='win32' and scratch_root.drive.upper()!='D:':
            raise ValueError('Hardware fixture scratch must be on D:')
        scratch_root.mkdir(parents=True,exist_ok=True)
    raw=Path(source).read_bytes()
    with tempfile.TemporaryDirectory(prefix='codexmeter-fixture-',dir=scratch_root) as work:
        path=Path(work)/'devices.json'
        path.write_bytes(raw)
        registry=DeviceRegistry.load(path)
        if any(device.maintenance for device in registry.devices):
            raise ValueError('Input registry contains maintenance state; use a clean snapshot after tools close')
        yield registry
