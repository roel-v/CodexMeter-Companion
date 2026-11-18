"""Fail if host and firmware bounds drift before hardware testing."""
from pathlib import Path
import re
from codexmeter.companion_protocol import MAX_APPLICATION, MAX_FRAME
from codexmeter.ble_session import BLE_ATT_VALUE_LIMIT


def test_wire_bounds_agree_with_firmware():
    header = (Path(__file__).parents[1] / "firmware/src/protocol_limits.h").read_text()
    values = {name: int(value) for name, value in re.findall(r"constexpr size_t (\w+) = (\d+);", header)}
    assert values == {"frame_limit": MAX_FRAME, "payload_limit": MAX_APPLICATION,
                      "ble_att_value_limit": BLE_ATT_VALUE_LIMIT}
