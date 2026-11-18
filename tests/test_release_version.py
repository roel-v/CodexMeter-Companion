from pathlib import Path
import importlib.util
import pytest
from codexmeter import __version__

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("release_version", ROOT / "scripts/release_version.py")
version_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version_module)


def test_generated_version_matches_package_and_rebuilds_only_when_changed(tmp_path):
    header = version_module.firmware_header(ROOT, tmp_path)
    assert f'"{__version__}"' in header.read_text()
    stamp = header.stat().st_mtime_ns
    version_module.firmware_header(ROOT, tmp_path)
    assert header.stat().st_mtime_ns == stamp


@pytest.mark.parametrize("source", ["", '__version__ = "1.2.3"',
    '__version__ = "1.2.3.65536"', '__version__ = "01.2.3.4"',
    '__version__ = str(1234)', '__version__ = "1.2.3.4"\n__version__ = "2.3.4.5"'])
def test_invalid_release_metadata_fails_before_packaging(tmp_path, source):
    (tmp_path / "codexmeter").mkdir()
    (tmp_path / "codexmeter/__init__.py").write_text(source)
    with pytest.raises(ValueError):
        version_module.firmware_header(tmp_path, tmp_path / "generated")
    assert not (tmp_path / "generated/release_version.h").exists()


def test_update_dialog_uses_canonical_application_version():
    from codexmeter.update_dialog import APP_VERSION
    assert APP_VERSION == __version__
