"""Command-line helpers for development and installation checks."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import replace

from .device_registry import (
    DeviceRegistry,
    DeviceConfig,
    CONNECTION_MODES,
    is_full_device_id,
    config_from_short_id,
    normalize_short_id,
)
from .events import send_event
from .ble_discovery import scan_codexmeter_devices
from .payloads import build_usage_payload
from .provider import CodexUsageProvider


async def run_once(args: argparse.Namespace) -> int:
    from .pricing import PRICING_DIR
    provider = CodexUsageProvider(codex_bin=args.codex_bin, timeout_sec=args.timeout,
                                  refresh_token=args.refresh_token, report_path=PRICING_DIR / "usage-report.json")
    snapshot = await provider.fetch()
    payload = build_usage_payload(snapshot)
    print(json.dumps(payload.data, ensure_ascii=False, indent=2))
    return 0


async def run_status(_args: argparse.Namespace) -> int:
    result = await send_event({"type": "ping", "include_activity_tasks": True})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


async def run_demo_alert(args: argparse.Namespace) -> int:
    result = await send_event(
        {"type": "alert", "title": "Task complete!", "body": args.message}
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


async def run_demo_usage(args: argparse.Namespace) -> int:
    now = int(time.time())
    result = await send_event(
        {
            "type": "usage",
            "payload": {
                "v": 1,
                "k": "usage",
                "src": "codex",
                "h5": None if args.no_h5 else args.h5,
                "h5r": None if args.no_h5 else now + 73 * 60,
                "d7": args.d7,
                "d7r": now + 3 * 24 * 60 * 60,
                "td": args.today_tokens,
                "t7": args.week_tokens,
                "st": "ok",
                "t": now,
            },
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


async def run_demo_activity(args: argparse.Namespace) -> int:
    result = await send_event({"type": "activity", "count": args.count})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


async def run_screen(args: argparse.Namespace) -> int:
    result = await send_event(
        {"type": "screen", "on": args.on, "reason": args.reason,
         "device_id": getattr(args, "device_id", None)}
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


async def run_devices_scan(args: argparse.Namespace) -> int:
    from .usb_transport import UsbDiscovery
    usb=UsbDiscovery()
    await usb.scan_once()
    results=[d.status() for d in usb.devices.values()]
    if not getattr(args,'usb_only',False):
        try:
            results.extend({'transport':'bluetooth','name':d.name,'short_id':d.short_id,
                            'address':d.address} for d in await scan_codexmeter_devices(timeout=args.timeout))
        except Exception as exc:
            print('Bluetooth unavailable: '+str(exc),file=sys.stderr)
    print(json.dumps(results,ensure_ascii=False,indent=2))
    return 0


async def run_devices_list(_args: argparse.Namespace) -> int:
    registry = DeviceRegistry.load()
    print(
        json.dumps(
            [device.to_json() for device in registry.devices],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


async def run_devices_adopt(args: argparse.Namespace) -> int:
    registry = DeviceRegistry.load()
    mode=getattr(args,'connection_mode','auto')
    if is_full_device_id(args.short_id) and mode=='bluetooth_only':
        short_id=args.short_id.removeprefix('codexmeter-')[:6].upper()
        previous=registry.find(args.short_id)
        device=replace(previous,connection_mode=mode,alias=args.alias or previous.alias) if previous else DeviceConfig(
            args.short_id,short_id=short_id,name=f'CodexMeter-{short_id}',alias=args.alias,connection_mode=mode)
    elif is_full_device_id(args.short_id):
        from .usb_transport import UsbDiscovery
        discovery=UsbDiscovery()
        await discovery.scan_once()
        matches=[d for d in discovery.devices.values() if d.identity.device_id==args.short_id]
        if len(matches)!=1: raise ValueError('Connect exactly one compatible USB display with this full ID')
        identity=matches[0].identity
        previous=registry.find(identity.device_id)
        device=replace(previous,connection_mode=mode,alias=args.alias or previous.alias,
            metadata=identity.metadata) if previous else DeviceConfig(identity.device_id,
            short_id=identity.short_id,name=identity.name,alias=args.alias,
            metadata=identity.metadata,connection_mode=mode)
    else:
        if mode=='usb_only': raise ValueError('USB-only registration requires a verified full hardware ID')
        device=replace(config_from_short_id(args.short_id,alias=args.alias),connection_mode=mode)
    result = await _update_running_registry({'type':'device_registry_update', 'action':'adopt',
        'device_id':device.device_id, 'config':device.to_json()})
    if result is None:
        registry.upsert(device)
        registry.save()
    print(json.dumps(device.to_json(), ensure_ascii=False, indent=2))
    return 0


async def run_devices_rename(args: argparse.Namespace) -> int:
    registry = DeviceRegistry.load()
    device = registry.find(args.device)
    if device is None:
        print(f"Error: unknown device {args.device}", file=sys.stderr)
        return 1
    updated = replace(device, alias=args.alias)
    result = await _update_running_registry({'type':'device_registry_update', 'action':'rename',
        'device_id':device.device_id, 'alias':updated.alias})
    if result is None:
        registry.upsert(updated)
        registry.save()
    print(json.dumps(updated.to_json(), ensure_ascii=False, indent=2))
    return 0


async def run_devices_enabled(args: argparse.Namespace) -> int:
    registry = DeviceRegistry.load()
    device = registry.find(args.device)
    if device is None:
        print(f"Error: unknown device {args.device}", file=sys.stderr)
        return 1
    updated = replace(device, enabled=args.enabled)
    result = await _update_running_registry({'type':'device_registry_update', 'action':'enabled',
        'device_id':device.device_id, 'enabled':updated.enabled})
    if result is None:
        registry.upsert(updated)
        registry.save()
    print(json.dumps(updated.to_json(), ensure_ascii=False, indent=2))
    return 0


async def _update_running_registry(event):
    try:
        result = await send_event(event)
    except OSError:
        return None
    if not result.get('ok'):
        raise ValueError(result.get('error', 'Running companion cannot update the registry'))
    return result


async def run_devices_mode(args):
    registry = DeviceRegistry.load()
    device = registry.find(args.device)
    if device is None:
        raise ValueError('Unknown registered display')
    try:
        result = await send_event({'type':'device_mode', 'device_id':device.device_id,
                                   'connection_mode':args.connection_mode})
    except (OSError, TimeoutError):
        updated = replace(device, connection_mode=args.connection_mode)
        registry.upsert(updated)
        registry.save()
        result = {'ok':True, **updated.to_json()}
    print(json.dumps(result, indent=2))
    return 0 if result.get('ok') else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CodexMeter helper CLI.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    once = sub.add_parser("once", help="Fetch Codex usage once and print BLE JSON.")
    once.add_argument("--codex-bin", default="codex")
    once.add_argument("--timeout", type=float, default=15.0)
    once.add_argument("--refresh-token", action="store_true")
    once.set_defaults(func=run_once)

    status = sub.add_parser("status", help="Ping the local daemon event socket.")
    status.set_defaults(func=run_status)

    alert = sub.add_parser("demo-alert", help="Queue a demo task-complete alert.")
    alert.add_argument("message", nargs="?", default="Codex completed a test task")
    alert.set_defaults(func=run_demo_alert)

    usage = sub.add_parser("demo-usage", help="Queue a demo usage payload.")
    usage.add_argument("--h5", type=int, default=72)
    usage.add_argument("--d7", type=int, default=84)
    usage.add_argument(
        "--no-h5",
        action="store_true",
        help="Hide the 5h window and preview the token-activity layout.",
    )
    usage.add_argument("--today-tokens", type=int, default=18_600_000)
    usage.add_argument("--week-tokens", type=int, default=236_000_000)
    usage.set_defaults(func=run_demo_usage)

    activity = sub.add_parser("demo-activity", help="Queue a demo running-task count.")
    activity.add_argument("--count", type=int, default=1)
    activity.set_defaults(func=run_demo_activity)

    screen_on = sub.add_parser("screen-on", help="Queue a screen-on control payload.")
    screen_on.add_argument("--reason", choices=["manual"], default="manual")
    screen_on.add_argument("--device-id", help="Full device ID; omitted broadcasts to registered displays")
    screen_on.set_defaults(func=run_screen, on=True)

    screen_off = sub.add_parser("screen-off", help="Queue a screen-off control payload.")
    screen_off.add_argument("--reason", choices=["manual"], default="manual")
    screen_off.add_argument("--device-id", help="Full device ID; omitted broadcasts to registered displays")
    screen_off.set_defaults(func=run_screen, on=False)

    devices = sub.add_parser("devices", help="Manage registered CodexMeter devices.")
    device_sub = devices.add_subparsers(dest="device_cmd", required=True)

    devices_scan = device_sub.add_parser("scan", help="Scan nearby CodexMeter BLE devices.")
    devices_scan.add_argument("--timeout", type=float, default=4.0)
    devices_scan.add_argument("--usb-only", action="store_true")
    devices_scan.set_defaults(func=run_devices_scan)

    devices_list = device_sub.add_parser("list", help="List registered devices.")
    devices_list.set_defaults(func=run_devices_list)

    devices_adopt = device_sub.add_parser("adopt", help="Register a nearby device short id.")
    devices_adopt.add_argument("short_id")
    devices_adopt.add_argument("--alias")
    devices_adopt.add_argument("--connection-mode", choices=CONNECTION_MODES, default="auto")
    devices_adopt.set_defaults(func=run_devices_adopt)

    devices_rename = device_sub.add_parser("rename", help="Set a local alias for a device.")
    devices_rename.add_argument("device")
    devices_rename.add_argument("alias")
    devices_rename.set_defaults(func=run_devices_rename)

    devices_enable = device_sub.add_parser("enable", help="Enable auto-connect for a device.")
    devices_enable.add_argument("device")
    devices_enable.set_defaults(func=run_devices_enabled, enabled=True)

    devices_disable = device_sub.add_parser("disable", help="Disable auto-connect for a device.")
    devices_disable.add_argument("device")
    devices_disable.set_defaults(func=run_devices_enabled, enabled=False)

    mode=device_sub.add_parser('mode',help='Set connection mode (restart bridge to apply).')
    mode.add_argument('device')
    mode.add_argument('connection_mode',choices=CONNECTION_MODES)
    mode.set_defaults(func=run_devices_mode)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return asyncio.run(args.func(args))
    except (OSError, TimeoutError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
