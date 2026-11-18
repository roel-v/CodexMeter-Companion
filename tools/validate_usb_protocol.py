#!/usr/bin/env python3
"""Isolated, identity-checked firmware fixture; never run beside an app owner.

The reader, writer, frame storage and total test duration are bounded. Serial
control lines remain disabled; no reset/download-mode requests are issued.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--expected-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exercise", action="store_true", help="Claim USB and run bounded application fixtures")
    parser.add_argument("--backpressure", action="store_true", help="Bounded ping flood without reads, then require correlated recovery")
    parser.add_argument("--maintenance", action="store_true", help="Verify maintenance claim/renew/diagnostics/fencing after app release")
    parser.add_argument("--timeout", type=float, default=1.0)
    args = parser.parse_args()
    if not re.fullmatch(r"codexmeter-[0-9a-f]{12}", args.expected_id):
        parser.error("expected-id must be the full lowercase hardware identity")
    if not 0.1 <= args.timeout <= 2:
        parser.error("timeout must be between 0.1 and 2 seconds")

    import serial
    from serial.tools import list_ports

    report: dict = {"port": args.port, "expected_id": args.expected_id, "cases": [], "passed": False}
    started = time.monotonic()
    port = serial.Serial()
    port.port = args.port
    port.baudrate = 115200
    port.timeout = 0.05
    port.write_timeout = 0.5
    port.dtr = False
    port.rts = False
    port.xonxoff = port.rtscts = port.dsrdtr = False
    buffer = bytearray()
    token = secrets.token_hex(16)
    boot = ""
    q = 0
    claimed = False
    maintenance = False

    def write(data: bytes) -> None:
        if len(data) > 1024:
            raise RuntimeError("fixture write exceeds bounded capacity")
        if port.write(data) != len(data):
            raise RuntimeError("partial fixture write")

    def read(prefix: bytes, *, timeout: float | None = None, raw: bool = False) -> dict:
        deadline = time.monotonic() + (args.timeout if timeout is None else timeout)
        while time.monotonic() < deadline:
            if time.monotonic() - started > 45:
                raise RuntimeError("fixture exceeded total duration")
            while b"\n" in buffer:
                line, _, tail = buffer.partition(b"\n")
                buffer[:] = tail
                if line.startswith(prefix):
                    if raw:return {"line":line.decode("utf-8",errors="replace")}
                    try:
                        value = json.loads(line[len(prefix):].decode("utf-8"))
                    except (ValueError, UnicodeError):
                        continue
                    if not isinstance(value, dict):
                        raise RuntimeError("reply must be object")
                    return value
            buffer.extend(port.read(min(128, max(1, port.in_waiting))))
            if len(buffer) > 1280:
                raise RuntimeError("fixture receive overflow")
        raise TimeoutError("bounded reply timeout")

    def control(op: str, *, wait: float | None = None, **fields) -> dict:
        nonlocal q
        q += 1
        value = {"op": op, "q": q, "boot": boot, "token": token, **fields}
        write(b"CM1 " + json.dumps(value, separators=(",", ":")).encode() + b"\n")
        deadline=time.monotonic()+(args.timeout if wait is None else wait)
        for _ in range(256):
            result = read(b"CM1 ", timeout=max(.001,deadline-time.monotonic()))
            if result.get("boot") == boot and result.get("q") == q and result.get("token") == token:
                return result
        raise RuntimeError("control correlation limit exceeded")

    def data(seq: int, payload: str, revision: str = "-", *, split: bool = False) -> dict:
        frame = f"CM1 DATA {boot} {token} {seq} {revision} {payload}\n".encode("utf-8")
        if split:
            for offset in range(0, len(frame), 17):
                write(frame[offset:offset+17])
                time.sleep(0.002)
        else:
            write(frame)
        result = read(b"CM1 ")
        if result.get("boot") != boot or result.get("token") != token or result.get("seq") != seq:
            raise RuntimeError("DATA correlation mismatch")
        return result

    def case(name: str, result: dict, error: str | None = None) -> None:
        passed = result.get("ok") is (error is None) and (error is None or result.get("err") == error)
        report["cases"].append({"name": name, "passed": passed, "response": result})
        if not passed:
            raise RuntimeError(f"case failed: {name}")

    try:
        matches = [p for p in list_ports.comports() if p.device.lower() == args.port.lower()]
        if len(matches) != 1 or (matches[0].vid, matches[0].pid) != (0x303A, 0x1001):
            raise RuntimeError("explicit port is absent, ambiguous or outside approved USB VID/PID")
        if sys.platform != "win32":
            raise RuntimeError("this acceptance fixture is Windows-only")
        import winreg
        verified = []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Enum\USB") as usb:
            for index in range(winreg.QueryInfoKey(usb)[0]):
                name = winreg.EnumKey(usb, index)
                if name.upper() != "VID_303A&PID_1001&MI_00":
                    continue
                with winreg.OpenKey(usb, name) as interface:
                    for child_index in range(winreg.QueryInfoKey(interface)[0]):
                        child = winreg.EnumKey(interface, child_index)
                        with winreg.OpenKey(interface, child) as instance:
                            try:
                                service = winreg.QueryValueEx(instance, "Service")[0]
                                with winreg.OpenKey(instance, "Device Parameters") as parameters:
                                    com = winreg.QueryValueEx(parameters, "PortName")[0]
                                if service.lower() == "usbser" and com.lower() == args.port.lower():
                                    verified.append(name + "\\" + child)
                            except FileNotFoundError:
                                continue
        if len(verified) != 1:
            raise RuntimeError("explicit port does not resolve uniquely to interface00 with usbser")
        report["pnp_instance"] = verified[0]
        serial_number = matches[0].serial_number
        if serial_number and sum(p.serial_number == serial_number for p in list_ports.comports()) != 1:
            raise RuntimeError("duplicate serial endpoints are ambiguous")
        port.open()
        write(b"identity\n")
        identity = read(b"IDENTITY ")
        if identity.get("device_id") != args.expected_id:
            raise RuntimeError("full hardware identity mismatch")
        report["identity"] = identity
        boot = identity.get("boot", "")
        if not re.fullmatch(r"[0-9a-f]{16}", boot) or identity.get("usb") != 1 or identity.get("app") != 1:
            raise RuntimeError("firmware does not advertise compatible USB wire protocol")
        if args.exercise:
            case("claim", control("claim", host="a" * 32))
            claimed = True
            baseline = report["cases"][-1]["response"]["state"]
            case("ping", control("ping"))
            activity = '{"v":1,"k":"activity","src":"codex","run":0,"t":1784000000}'
            case("split_activity", data(1, activity, split=True))
            case("identical_retry", data(1, activity))
            case("changed_retry", data(1, activity.replace('"run":0', '"run":1')), "conflict")
            case("skip_sequence", data(3, activity), "out_of_order")
            case("invalid_application", data(2, '{"v":2,"k":"activity","src":"codex","run":0,"t":1}'), "bad_request")
            maximum = activity + " " * (512 - len(activity))
            case("maximum_512_bytes", data(3, maximum))
            brightness = json.dumps({"v": 1, "k": "control", "cmd": "brightness", "value": baseline["brightness"], "t": 1784000000}, separators=(",", ":"))
            case("revision_conflict", data(4, brightness, str((baseline["rev"] + 1) & 0xFFFFFFFF)), "conflict")
            state = control("state")
            case("state", state)
            for key in ("page", "brightness", "rotation", "auto_rotation", "manual_on", "policy_on"):
                if state["state"][key] != baseline[key]:
                    raise RuntimeError(f"physical state changed unexpectedly: {key}")
            # Oversized frame must discard the complete line and recover on ping.
            write(b"x" * 641 + b"\n")
            case("overflow_recovery", control("ping"))
            if args.backpressure:
                port.set_buffer_size(rx_size=128,tx_size=1024)
                for _ in range(64):
                    q+=1
                    value={"op":"ping","q":q,"boot":boot,"token":token}
                    write(b"CM1 "+json.dumps(value,separators=(",",":")).encode()+b"\n")
                    time.sleep(.025)
                time.sleep(.8)
                case("backpressure_recovery",control("ping",wait=3))
            case("release", control("release"))
            claimed = False
            write(b"health\n")
            report["health_after"]=read(b"HEALTH ",raw=True)
            if args.maintenance:
                write(b"identity\n")
                refreshed=read(b"IDENTITY ")
                if refreshed.get("device_id")!=args.expected_id or refreshed.get("boot")!=boot:
                    raise RuntimeError("identity changed before maintenance")
                token=secrets.token_hex(16)
                case("maintenance_claim",control("maint",host="a"*32))
                maintenance=True
                case("maintenance_renew",control("maint",host="a"*32))
                case("maintenance_blocks_data",data(1,activity),"busy_maintenance")
            write(b"heap\nlogs 1\n")
            report["heap_after"]=read(b"LOG ",raw=True)
            if maintenance:
                case("maintenance_end",control("maint_end"))
                maintenance=False
                case("maintenance_fenced_token",control("maint",host="a"*32),"stale_session")
        report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if maintenance and port.is_open:
            try:
                control("maint_end")
            except Exception:
                report["maintenance_cleanup"]="unconfirmed; maintenance expires within120seconds"
        if claimed and port.is_open:
            try:
                control("release")
            except Exception:
                report["cleanup"] = "release unconfirmed; firmware lease expires within 7 seconds"
        if port.is_open:
            port.close()
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "report": str(args.output), "cases": len(report["cases"]), "error": report.get("error")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
