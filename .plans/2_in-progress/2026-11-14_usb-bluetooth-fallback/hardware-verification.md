# Phase 1 hardware verification

Observed on 2026-11-17 in the E: CodexMeter-Companion checkout at
`a358579882d5c88b953131056383728530e8a1c9`.

| Target | Current USB evidence | Result |
| --- | --- | --- |
| Waveshare C6 AMOLED 2.16 | usbser COM6, `USB\VID_303A&PID_1001&MI_00`, identity `codexmeter-00e216f16e20` / `00E216` | Safe read-only open/close observed on this Windows PC |
| Spotpear Ball V2 | No second eligible present port. Historical USB serial `90:70:69:F4:67:68` and COM9 are from the retained Ball probe. Historical registered app ID `codexmeter-6867f4697090` is from retained registry evidence and requires live confirmation | Blocked until the intended Ball is connected with a USB data cable |

The elevated read-only `pnputil /enum-devices /connected /class Ports` and SERIALCOMM inventory showed COM1 (ACPI)
and COM3/COM4 (Bluetooth SPP) in addition to COM6. None of those three ports was opened. Historic firmware
3.12.3.0 was documented on the Ball release. The C6's current identity response has no version field and its loaded
version cannot be verified from the identity query. No release binary, firmware or settings were changed.

On Windows, `tools/serial_device.py:SerialSession` sets DTR and RTS false before pyserial opens the handle
and uses 115200 baud. Three separate `--identify COM6` processes succeeded in 230, 218 and 205 ms (includes
Python startup). Three inline identity round trips took 16 ms each. A further three inline opens measured
15, 31 and 15 ms from immediately before writing `identity\n` to complete receipt. Immediately before and after
those three opens, two read-only `logs 2` queries returned the same last two volatile ring markers:

| Observation | Sequence and milliseconds since boot |
| --- | --- |
| Before | 276215 / 306540205, 276216 / 306540269 |
| After | 276215 / 306540205, 276216 / 306540269 |

The same high-uptime markers survived all five handles in that run, which is evidence the C6 did not reset during
those opens/closes. An earlier before/after log-ring check also retained 48 entries with no captured startup/reset
marker. This checks one Windows usbser configuration and existing firmware. It does not certify control-line
transients on other drivers, hubs or the Ball, nor any future v1 latency. Only identity and read-only log queries ran
during production BLE operation. This file retains the observations without raw log text.

## Pinned core

`firmware/platformio.ini` pins pioarduino platform 55.03.38-1 for both targets. Local
`D:\build\CodexMeter\platformio\packages\framework-arduinoespressif32\package.json` reports Arduino 3.3.8.
The inspected `cores/esp32/HWCDC.cpp` applies to both because their flags select HWCDC and CDC-on-boot.

- The driver uses 64-byte FIFO transfers, default 256-byte RX queue and 256-byte TX ring; RX ISR drops bytes when
  the queue is full. The byte and buffered read methods dequeue with zero wait.
- HWCDC's connection flag uses interrupts, bus reset and FIFO behaviour. It has no app ownership concept or reliable
  user-mode COM-close event. No DTR/RTS event or 1200 baud reset touch exists in this HWCDC class; host control-line
  settings still matter for opening safely.
- `availableForWrite` and `write` acquire a mutex using the TX timeout, 100 ms by default. Connected writes
  larger than current capacity can wait for progress and return partially; disconnected writes can buffer and
  evict older entries. A bounded application TX path, no flush, and lease timeout are required.
- Espressif's native USB hardware depends on controller/clock availability across chip sleep. The product preserves
  communication when only the screen is off. Physical sleep/resume is excluded; later phases cover host cold
  re-enumeration and cancellation in automated tests. The wire timers are provisional design inputs to Phase 5.

## Historical gate on 2026-11-17 (resolved below)

Connect the intended Spotpear Ball V2 to this Windows PC with a USB data cable, leaving the C6 connected.
Verify that a second eligible interface appears, identify that unit, and repeat the non-resetting open/close check
before treating Phase 1 as passed. No firmware flash or reset is needed for this check. No-adapter operation,
switch counts/latency, and mixed-transport controls are later acceptance checks. Optional endurance testing has
not run.

## Live recheck — 2026-11-18

Both boards enumerated simultaneously after the user connected the Ball data cable. Only eligible Espressif
USB interfaces were opened. COM1 (ACPI) and COM3/COM4 (Bluetooth SPP) were again excluded.

| Target | Live identity / firmware | Five identity round trips | Volatile log markers before and after |
| --- | --- | --- | --- |
| C6 COM6, USB serial 20:6E:F1:16:E2:00 | codexmeter-00e216f16e20, short 00E216; version absent in identity | 15, 15, 16, 16, 16 ms | 301557 / 391126333 ms and 301558 / 391132040 ms |
| Ball COM9, USB serial 90:70:69:F4:67:68 | codexmeter-6867f4697090, short 6867F4; model spotpear_ball_v2; firmware 3.12.3.0-usb.1, app protocol 1 | 16, 15, 15, 15, 16 ms | 86325 / 170938758 ms and 86326 / 170940787 ms |

The two volatile log markers per board were identical before and after each five-open test, establishing
continuity of the current firmware's RAM log ring and high device uptime. Every serial open used the reviewed
SerialSession with DTR/RTS disabled before opening. Only identity and read-only diagnostic requests ran.
The initial Ball logs 2 request timed out at 2 seconds. A subsequent diagnostic retry succeeded and the complete
before/five-opens/after test passed. This transient is retained as an observation; steady identity timings do not
establish hotplug/promotion timing or claim that every request always returns within 1 second.

Ball identity advertises brightness, rotation, touch and screen. Its existing app protocol 1 and firmware suffix
do not advertise the proposed USB wire-v1 capability and do not constitute acceptance of the new contract.
Both target configurations were rechecked to inherit pioarduino platform 55.03.38-1 and to define
ARDUINO_USB_MODE=1 and ARDUINO_USB_CDC_ON_BOOT=1. No firmware changes, resets or flashes were performed.

The Phase 1 physical identity/non-resetting-open blocker is resolved. Contract timings, minimum-MTU fragmented
BLE interoperability, lease arbitration and new-protocol latency remain design inputs for implementation and
subsequent validation. No-adapter-PC and physical switch tests remain later-phase acceptance work.
