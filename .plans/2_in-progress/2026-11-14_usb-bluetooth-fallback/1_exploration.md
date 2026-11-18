# USB communication with automatic Bluetooth fallback

Status: planning only. Requested 2026-11-14; implementation, flashing and publication have not been requested here.

## Objective

The primary motivation is machines without Bluetooth hardware. USB must work as a complete standalone transport.
In Auto mode, use USB when a registered display has a working data connection to the companion PC; otherwise use Bluetooth
when Bluetooth is available. Its absence must never prevent startup, registration or USB communication.
Support Waveshare ESP32-C6-Touch-AMOLED-2.16 and the verified Spotpear ESP32-S3 Ball/BOX V2 independently,
including mixed transports and repeated models within one desktop instance.

## Evidence from investigation

Baseline: desktop 3.12.3.1, source a358579; existing firmware and completed Ball/multi-display feature.

- Both firmware targets enable ARDUINO_USB_MODE=1 and ARDUINO_USB_CDC_ON_BOOT=1.
- Windows currently enumerates the C6 on COM6 with Espressif VID 303A / PID 1001.
- Earlier Ball hardware evidence identifies COM9 and the same VID/PID. The Ball was not enumerated over USB
  during this investigation. Its live connection must be checked again; COM numbers are not device identities.
- firmware/src/main.cpp already accepts newline-delimited JSON via handle_serial(), using handle_json().
- All application acknowledgements currently call ble_service_ack/nack, regardless of message origin.
- handle_ble_screen_policy() requires BLE connectivity even when serial supplied valid data.
- Serial shares logs, identity/health commands, screenshot streams and other diagnostic commands.
- The serial input buffer is 520 bytes; BLE has a 513-byte buffer. Existing truncation behaviour is not a
  production USB framing contract. Bounds, overflow recovery and application payload size must be explicit.
- tools/serial_device.py provides identity queries and port handling that avoids intentional DTR/RTS resets.
- pyserial is already a Windows dependency. Runtime packaging and non-Windows dependency handling need review.
- codexmeter/multi_ble.py owns per-device workers; codexmeter/ble.py owns delivery/replay/ACK behaviour.
  These responsibilities must be separated before switching transports safely.
- The existing stable CodexMeter hardware ID can associate USB and BLE endpoints. The C6 currently advertises
  less capability metadata than the Ball, so new firmware needs explicit USB protocol capability discovery.

## Boundaries

Retain the existing pages, themes, controls, completion notifications, registration and pricing behaviour.
Do not add a new in-app firmware updater, installer, automatic app restarts or automatic release installation.
Existing USB flashing tools remain supported and must cooperate with serial-port ownership.
A PC data session is different from USB power: a wall charger cannot provide this transport. Losing the cable
can also remove power; failover cannot operate while the device is unpowered. PC sleep stops the companion
on both transports. Screen-off alone must not stop communications.

## Sources

- Existing feature: ../../3_done/2026-11-13_spotpear-ball-codexmeter/1_exploration.md and hardware-probe.md.
- https://docs.espressif.com/projects/esp-idf/en/v5.1.5/esp32c6/api-guides/usb-serial-jtag-console.html
- https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/usb-serial-jtag-console.html

Espressif documents native bidirectional serial and USB controller sleep/buffering limitations for both chips.
Hotplug and driver/control-line behaviour still require physical validation. Physical sleep/resume testing is
excluded by user decision; its behaviour remains unverified, with automated recovery coverage planned.
