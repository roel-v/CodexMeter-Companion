import sys
import pytest


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Tk acceptance runs on Windows and in the onefile self-test')
def test_actual_display_dialog_command_outcomes():
    import tkinter as tk
    from codexmeter.device_dialog_diagnostics import check_device_commands
    root=tk.Tk();root.withdraw()
    try:
        assert all(check_device_commands(root).values())
    finally:root.destroy()
