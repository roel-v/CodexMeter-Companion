import pytest
from codexmeter.companion_protocol import *

B = "0011223344556677"
T = "b" * 32


def test_stream_bounds_timeout_suffix_and_recovery():
    now = [0.0]
    d = LineDecoder(clock=lambda: now[0])
    assert d.feed(b"x" * 641 + b"CM1 {}\nclean\r\n") == [b"clean"]
    assert d.feed(b"CM1 ") == []
    now[0] = 1.1
    assert d.feed(b'{"ok":true}\nnext\n') == [b"next"]
    assert len(d.buffer) == 0


def test_fragmented_and_interleaved_logs():
    d = LineDecoder()
    result = []
    for byte in (
        b'log\nCM1 {"boot":"'
        + B.encode()
        + b'","q":1,"token":"'
        + T.encode()
        + b'","ok":true}\n'
    ):
        result.extend(d.feed(bytes([byte])))
    assert parse_reply(result[0]) is None
    assert parse_reply(result[1])["q"] == 1


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"x":NaN}',
        b'{"x":"\x00"}',
        b"{} {}",
        b'{"a":[[[[[]]]]]}',
        b"x" * 641,
    ],
)
def test_invalid_objects(raw):
    with pytest.raises(ProtocolError):
        object_json(raw)


@pytest.mark.parametrize(
    "fields",
    [
        {"q": 1, "seq": 1, "ok": True},
        {"q": 1, "ok": True, "err": "conflict"},
        {"q": True, "ok": True},
        {"q": 1, "ok": False, "err": "bogus"},
    ],
)
def test_protocol_shaped_invalid_reply(fields):
    with pytest.raises(ProtocolError):
        parse_reply(b"CM1 " + json.dumps({"boot": B, **fields}).encode())


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


@pytest.mark.parametrize(
    "change",
    [
        {"usb": 2},
        {"model": "unknown"},
        {"boot": "bad"},
        {"capabilities": [{}]},
        {"name": []},
        {"short_id": 4},
        {"fw": "x" * 25},
    ],
)
def test_incompatible_identity_is_never_legacy(change):
    with pytest.raises(ProtocolError):
        NegotiatedIdentity.parse(
            b"IDENTITY " + json.dumps({**identity_data(), **change}).encode()
        )


def test_maximum_application_keeps_exact_bytes():
    raw = b'{"v":1,"k":"usage","padding":"' + b"x" * 480 + b'"}'
    raw = raw.replace(b"x" * 480, b"x" * (512 - (len(raw) - 480)))
    assert len(raw) == 512
    frame = encode_data(B, T, 1, None, raw)
    assert frame.endswith(raw + b"\n") and len(frame) <= 641
    with pytest.raises(ProtocolError):
        encode_data(B, T, 1, None, raw + b" ")
