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


def test_ball_capture_waits_for_redraw_and_restores_after_failure(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools"))
    import capture_validation_pages as pages
    import capture_screenshot as ball

    events = []
    serial = SimpleNamespace(write_line=lambda command: events.append(command))
    monkeypatch.setattr(pages, "MaintenanceGuard", lambda *args: nullcontext())
    monkeypatch.setattr(pages, "SerialSession", lambda *args: nullcontext(serial))
    monkeypatch.setattr(pages.time, "sleep", lambda _: events.append("redraw"))

    def capture(_port):
        if events:
            assert events[-2:] == ["test_swipe", "redraw"]
            raise RuntimeError("capture failed")
        return 1, 1, b"pixels"

    monkeypatch.setattr(ball, "capture_rgb565le", capture)
    monkeypatch.setattr(ball, "rgb565le_to_png", lambda *args: b"png")
    with pytest.raises(RuntimeError, match="capture failed"):
        pages.run(SimpleNamespace(port="test", device_id="expected", c6=False, output=tmp_path))
    assert events.count("test_swipe") == 3


def test_c6_rejects_bad_crc_and_preserves_diagnostic_tile(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools"))
    import capture_c6_screen as c6

    lines = iter([b"TILED_SCREENSHOT_START 480 480", b"TILE 0 0 1 1 2 0"])
    serial = SimpleNamespace(write_line=lambda _: None,
                             read_line=lambda _: next(lines),
                             read_exact=lambda size, timeout: b"ab")
    output = tmp_path / "rejected.png"
    with pytest.raises(AssertionError, match="CRC mismatch"):
        c6.capture(serial, output)
    assert not output.exists()
    assert output.with_suffix(".failed-tile.bin").read_bytes() == b"ab"
