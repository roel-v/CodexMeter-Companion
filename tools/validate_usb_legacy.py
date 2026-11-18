"""One-board physical legacy-firmware compatibility, with app-only usb.5 restoration.

Private rollback application stays on D:. No image is copied into a public bundle.
"""
import argparse,json,subprocess,time
from pathlib import Path
from validate_usb_package import Fixture,IDS

def run(args):
 f=Fixture(args);out=args.output;out.mkdir(parents=True,exist_ok=True);flashed=False
 backup='E:/DeviceBackups/Waveshare-C6-206EF116E200/2026-11-18-usb-phase2-before/recovery.json'
 def flash(image,label):
  command=['pwsh','-NoProfile','-File',str(Path(__file__).resolve().parent/'update_firmware_app.ps1'),'-Port','COM6','-ExpectedDeviceId',IDS[0],'-Chip','esp32c6','-Firmware',str(image),'-BackupMetadata',backup,'-Log',str(out/f'{label}-flash.log')]
  result=subprocess.run(command,capture_output=True,text=True,timeout=180);(out/f'{label}-wrapper.log').write_text(result.stdout+'\n'+result.stderr);assert result.returncode==0,result.stderr
 def start_legacy():
  f.log=(out/'candidate-daemon.log').open('a');f.proc=subprocess.Popen([str(f.binary),'--daemon','--foreground','--codex-bin',str(f.home/'no-codex.exe'),'--poll-interval','3600','--scan-timeout','3','--scan-interval','2'],env=f.env,cwd=f.home,stdout=f.log,stderr=f.log,creationflags=subprocess.CREATE_NO_WINDOW)
  deadline=time.monotonic()+25
  while time.monotonic()<deadline:
   try:f.status();return
   except (OSError,ValueError):time.sleep(.3)
  raise RuntimeError('Candidate IPC not ready')
 try:
  f.record('original_baseline',status=f.event({'type':'ping'},original=True));f.event({'type':'shutdown'},original=True);time.sleep(8)
  flashed=True;flash(Path('D:/build/CodexMeter/tmp/phase5-private-legacy/c6-pre-usb-app.bin'),'legacy')
  for identity in IDS:f.cli('devices','mode',identity,'auto')
  start_legacy();elapsed,rows=f.wait({IDS[0]:'bluetooth',IDS[1]:'usb'},90);f.record('legacy_auto_ble',elapsed=elapsed,status=rows)
  f.mode(0,'usb_only');time.sleep(15);rows=f.devices();c6=next(d for d in rows if d['device_id']==IDS[0]);ball=next(d for d in rows if d['device_id']==IDS[1]);reason=str(c6.get('fallback_reason'))+' '+str(c6.get('last_error'));f.record('legacy_usb_only_no_fallback',not c6['connected'] and ball['connected'] and ball['transport']=='usb',status=rows)
  f.record('legacy_usb_upgrade_notice',any(word in reason.lower() for word in ('upgrade','firmware','unsupported','incompatible')),reason=reason)
  f.mode(0,'bluetooth_only');elapsed,rows=f.wait({IDS[0]:'bluetooth',IDS[1]:'usb'},60);f.record('legacy_forced_ble',elapsed=elapsed,status=rows)
 finally:
  f.stop()
  try:
   if flashed:flash(Path('D:/build/CodexMeter/usb-phase5-build/waveshare_c6_amoled_216/firmware.bin'),'restore-usb5')
   # Leave the same isolated registrations in Auto, outside production user config.
   for identity in IDS:f.cli('devices','mode',identity,'auto')
   f.start();f.baseline=f.devices();f.record('restored_usb5_both_usb',status=f.baseline)
   f.stop()
  finally:
   f.stop();subprocess.Popen([str(args.original.resolve()),'--daemon'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
  deadline=time.monotonic()+90
  while time.monotonic()<deadline:
   try:
    status=f.event({'type':'ping'},original=True);rows=status['devices']['devices']
    if len(rows)>=2 and all(d['connected'] and d.get('last_ack_age_sec') is not None and d['last_ack_age_sec']<10 for d in rows):break
   except (OSError,ValueError):pass
   time.sleep(1)
  f.record('original_restored',all(d['connected'] for d in rows),status=status)
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('output',type=Path);p.add_argument('home',type=Path);p.add_argument('--original',type=Path,required=True);run(p.parse_args())
