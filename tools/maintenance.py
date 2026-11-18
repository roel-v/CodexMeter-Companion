"""Maintenance consumer: never starts a daemon; failures retain a recoverable pause."""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codexmeter.events import send_event
from codexmeter.host_identity import load_host_id
from codexmeter.usb_transport import maintenance_connection, inspect_maintenance_identity


async def acquire(port, device_id=None):
    try:
        status = await send_event({'type': 'ping'})
    except OSError:
        status = None
    rows = status.get('devices', {}).get('devices', []) if status else []
    matches = [d for d in rows if d.get('last_discovered_address') == port and d.get('last_discovery_source') == 'usb']
    raw, legacy = None, False
    if device_id and any(d['device_id'] == device_id for d in rows):
        # The daemon owns discovery and verifies the live identity after pausing it.
        # Opening the port here races its probe while this display is on BLE.
        pass
    elif len(matches) == 1:
        resolved = matches[0]['device_id']
        if device_id and resolved != device_id:
            raise RuntimeError('Maintenance device identity mismatch')
        device_id = resolved
    else:
        raw, legacy = await inspect_maintenance_identity(port)
        if device_id and raw['device_id'] != device_id:
            raise RuntimeError('Maintenance device identity mismatch')
        device_id = raw['device_id']
    if status is not None and any(d['device_id'] == device_id for d in rows):
        result = await send_event({'type':'maintenance_acquire', 'device_id':device_id,
                                  'port':port, 'tool':True})
        if not result.get('ok') or not result.get('ready'):
            raise RuntimeError(result.get('error', 'Companion could not pause device; use Displays/Resume after recovery'))
        if result.get('port') != port:
            raise RuntimeError('USB port changed during maintenance; pause retained. Resume and retry with the current port')
        return {**result, 'via':'daemon'}
    if legacy:
        return {'via':'legacy', 'device_id':device_id, 'port':port, 'ready':True,
                'quiescence':'unsupported_legacy'}
    session = await maintenance_connection(port, load_host_id(), expected_id=device_id)
    try:
        return {'via':'direct', 'device_id':session.identity.device_id, 'port':port,
                'boot':session.identity.boot, 'token':session.token, 'ready':True}
    finally:
        await session.close(release=False)


async def _release_once(lease):
    if lease['via'] == 'daemon':
        result = await send_event({'type':'maintenance_release', 'device_id':lease['device_id'], 'token':lease['token']})
        if not result.get('ok'):
            raise RuntimeError(result.get('error', 'Maintenance pause retained; Resume after closing the tool'))
    elif lease['via'] != 'legacy':
        # An app-only rollback can replace updated firmware with legacy firmware.
        # The reboot cleared the old device lease. Positively re-identify this exact
        # board before ending locally; never send CM1 to confirmed legacy firmware.
        raw, legacy = await inspect_maintenance_identity(lease['port'])
        if raw['device_id'] != lease['device_id']:
            raise RuntimeError('Maintenance release device identity mismatch')
        if legacy:
            return {'quiescence': 'unsupported_legacy'}
        session = await maintenance_connection(lease['port'], load_host_id(), lease['token'], lease['device_id'])
        try:
            await session.end_maintenance()
        finally:
            await session.close(release=False)


async def release(lease):
    # Firmware may be cold just after an application update. Retrying release is read-only/lease-only.
    # If the companion/tool remains busy, retain its durable pause and report recovery explicitly.
    for attempt in range(3):
        try:
            return await _release_once(lease)
        except (RuntimeError, OSError, TimeoutError):
            if attempt == 2:
                raise
            await asyncio.sleep(1)


class MaintenanceGuard:
    def __init__(self, port, device_id=None):
        self.port, self.device_id = port, device_id
        self.lease = None
        self.renewed = 0
        self.q = 0

    def __enter__(self):
        self.lease = asyncio.run(acquire(self.port, self.device_id))
        self.renewed = time.monotonic()
        return self

    def renew(self, serial):
        """Follow-mode renewals use the existing exclusive serial handle."""
        if self.lease.get('quiescence') == 'unsupported_legacy' or time.monotonic() - self.renewed < 60:
            return
        from codexmeter.companion_protocol import encode_control
        self.q += 1
        serial.write_command(encode_control('maint', self.q, self.lease['boot'],
            host=load_host_id(), token=self.lease['token']))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            line = serial.read_line(max(.01, deadline-time.monotonic()))
            if line.startswith(b'CM1 '):
                reply = json.loads(line[4:])
                if reply.get('boot') == self.lease['boot'] and reply.get('token') == self.lease['token'] and reply.get('q') == self.q and reply.get('ok') is True:
                    self.renewed = time.monotonic()
                    return
        raise RuntimeError('Maintenance renewal not acknowledged; pause retained')

    def __exit__(self, *exc):
        if self.lease:
            asyncio.run(release(self.lease))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('acquire', 'release'))
    parser.add_argument('--port')
    parser.add_argument('--device-id')
    args = parser.parse_args()
    if args.operation == 'acquire':
        if not args.port:
            parser.error('--port required')
        result = asyncio.run(acquire(args.port, args.device_id))
        print(json.dumps(result, separators=(',', ':')))
    else:
        asyncio.run(release(json.load(sys.stdin)))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
