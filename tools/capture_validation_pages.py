"""Capture actual current frame/pages under same-host companion maintenance.

No demo rendering is used; caller supplies telemetry through the companion first.
Three local swipes return to the original page. Tokens remain private in memory.
"""
import argparse,time
from pathlib import Path
from maintenance import MaintenanceGuard
from serial_device import SerialSession

def run(args):
    args.output.mkdir(parents=True,exist_ok=True)
    with MaintenanceGuard(args.port, args.device_id):
        if args.c6:
            from capture_c6_screen import capture
            with SerialSession(args.port) as serial:
                on_details = False
                try:
                    capture(serial,args.output/'page-0.png')
                    serial.write_line('test_swipe');on_details = True;time.sleep(.3)
                    serial.write_line('test_tap_today');time.sleep(.3);capture(serial,args.output/'page-1.png')
                    serial.write_line('test_tap_week');time.sleep(.3);capture(serial,args.output/'page-2.png')
                finally:
                    if on_details:
                        # Also restore after a rejected/incomplete image transfer.
                        time.sleep(1)
                        serial.write_line('test_swipe');time.sleep(.3)

        else:
            from capture_screenshot import capture_rgb565le,rgb565le_to_png
            advances = 0
            try:
                for page in range(3):
                    if page:
                        with SerialSession(args.port) as serial:
                            serial.write_line('test_swipe')
                        advances += 1
                        time.sleep(.5)  # Allow the framebuffer redraw before reading it.
                    width,height,data=capture_rgb565le(args.port)
                    (args.output/f'page-{page}.png').write_bytes(rgb565le_to_png(width,height,data))
            finally:
                with SerialSession(args.port) as serial:
                    for _ in range((-advances) % 3):
                        serial.write_line('test_swipe');time.sleep(.5)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('port');p.add_argument('output',type=Path);p.add_argument('--c6',action='store_true');p.add_argument('--device-id');run(p.parse_args())
