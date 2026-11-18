"""Bounded standalone-panel acceptance using real Tk and asynchronous polling.

Synthetic ping replies only: no daemon, devices, accounts or network are changed.
"""
import time
from . import events


def check_panel(root, app):
    original = events.send_event
    healthy = {"schema": 1, "components": {"quota": {"label": "Quota", "state": "compatible"}}}
    cases = [(healthy, "Codex readings are available."),
             (OSError("controlled offline fixture"), "Checking Codex data compatibility…"),
             (healthy, "Codex readings are available.")]
    try:
        for snapshot, expected in cases:
            async def send(event):
                assert event == {"type": "ping"}
                if isinstance(snapshot, Exception):
                    raise snapshot
                return {"status": "running", "compatibility": snapshot}
            events.send_event = send
            # Drive the real scheduled poll; do not create a second timer chain.
            app.pricing_poll_count = 0
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                root.update()
                if app.pricing_poll_count > 1 and not app.compatibility_polling:
                    break
                time.sleep(.02)
            assert not app.compatibility_polling, "Standalone-panel health worker stalled"
            assert app.compatibility_text.get() == expected, app.compatibility_text.get()
        from .compatibility_dialog import show_compatibility
        dialog = show_compatibility(root, lambda: app.compatibility_snapshot)
        root.update()
        assert dialog.winfo_exists()
        dialog.destroy()
        return {"real_tk_worker": True, "top_level_ping": True,
                "daemon_absent": True, "recovery": True, "details_dialog": True}
    finally:
        events.send_event = original
