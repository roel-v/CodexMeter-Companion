"""Content evidence for maintenance captures; a PNG/CRC alone is not acceptance."""
import hashlib
import json
import time
from pathlib import Path


def expected_model(payloads):
    records = {p['k']: p for p in payloads}
    if set(records) != {'usage', 'activity'}:
        raise ValueError('A case requires independent usage and activity records')
    u, a = records['usage'], records['activity']
    return dict(usage_t=u['t'], activity_t=a['t'], waiting=False,
        d7=u.get('d7') if u.get('d7') is not None else -1,
        run=a.get('run') if a.get('run') is not None else -1,
        wait=a.get('wait') if a.get('chats') and a.get('wait') is not None else -1,
        done=a.get('done') if a.get('chats') and a.get('done') is not None else -1,
        td=u.get('td'), t7=u.get('t7'), b0=u.get('b0'), b7=u.get('b7'))


def verify_model(actual, expected):
    differences = {k: {'expected': v, 'actual': actual.get(k)}
                   for k, v in expected.items() if k not in actual or actual[k] != v}
    if differences:
        raise ValueError('Rendered fixture mismatch: ' + json.dumps(differences, sort_keys=True))


def read_model(serial, expected):
    serial.write_line('validation_state')
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        line = serial.read_line(max(.01, deadline-time.monotonic()))
        if line.startswith(b'VALIDATION '):
            actual = json.loads(line[len(b'VALIDATION '):])
            verify_model(actual, expected)
            return actual
    raise TimeoutError('Missing rendered-model diagnostic')


def record_capture(path, actual, expected):
    evidence = dict(expected=expected, rendered=actual,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    visual_review='pending')
    path.with_suffix('.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')


def compare_crops(candidate, reviewed_reference, crops):
    """Compare explicit metric regions against a separately reviewed reference."""
    from PIL import Image, ImageChops
    with Image.open(candidate) as actual, Image.open(reviewed_reference) as reference:
        if actual.size != reference.size:
            raise ValueError('Capture dimensions differ from reviewed reference')
        if not crops:
            raise ValueError('At least one metric crop is required')
        for box in crops:
            if ImageChops.difference(actual.convert('RGB').crop(box),
                                     reference.convert('RGB').crop(box)).getbbox():
                raise ValueError(f'Pixel content differs in metric crop {box}')
