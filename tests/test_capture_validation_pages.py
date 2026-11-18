"""Capture failures must not leave a physical display on a different page."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_c6_capture_crc_failure_restores_overview(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools"))
    import capture_validation_pages as pages
    import capture_c6_screen as c6

    commands = []
    serial = SimpleNamespace(write_line=commands.append)
    monkeypatch.setattr(pages, "MaintenanceGuard", lambda *args: nullcontext())
    monkeypatch.setattr(pages, "SerialSession", lambda *args: nullcontext(serial))
    monkeypatch.setattr(pages.time, "sleep", lambda _: None)

    def capture(_serial, output):
        if output.name == "page-2.png":
            raise AssertionError("Serial image CRC mismatch")

    monkeypatch.setattr(c6, "capture", capture)
    with pytest.raises(AssertionError, match="CRC"):
        pages.run(SimpleNamespace(port="test", device_id="expected", c6=True, output=tmp_path))
    assert commands == ["test_swipe", "test_tap_today", "test_tap_week", "test_swipe"]
