"""Shared usb protocol fixtures."""


B = "0011223344556677"

def identity_data():
    return {
        "device_id": "codexmeter-001122334455",
        "short_id": "001122",
        "name": "CodexMeter-001122",
        "usb": 1,
        "app": 1,
        "boot": B,
        "fw": "test",
        "model": "waveshare_c6_amoled_216",
        "capabilities": ["brightness", "screen", "rotation"],
    }
