"""Additional exact-package physical cases; original app restored in finally."""
import argparse,json,subprocess,time,sqlite3
from pathlib import Path
from validate_usb_package import Fixture,IDS,PORTS
from serial_device import SerialSession

def run(args):
 f=Fixture(args)
 try:
  f.record('production_baseline',status=f.event({'type':'ping'},original=True))
  f.event({'type':'shutdown'},original=True);time.sleep(8)
  for identity in IDS:f.cli('devices','mode',identity,'usb_only')
  codex=f.home/'.codex';codex.mkdir(exist_ok=True)
  with sqlite3.connect(codex/'state_5.sqlite') as db:
   db.executescript('CREATE TABLE IF NOT EXISTS threads(id,archived,source); CREATE TABLE IF NOT EXISTS thread_spawn_edges(child_thread_id); DELETE FROM threads;')
   db.execute('INSERT INTO threads VALUES(?,?,?)',('phase5-synthetic-done',0,'vscode'))
  with sqlite3.connect(codex/'thread_history_1.sqlite') as db:
   db.execute('CREATE TABLE IF NOT EXISTS thread_turns(thread_id,status,rollout_ordinal)');db.execute('DELETE FROM thread_turns');db.execute('INSERT INTO thread_turns VALUES(?,?,?)',('phase5-synthetic-done','completed',1))
  (codex/'.codex-global-state.json').write_text(json.dumps({'electron-thread-read-state-v1':{'unreadByIdentity':{'phase5-synthetic-account':{'local:fixture':['phase5-synthetic-done']}}}}))
  f.start();f.baseline=next(x['status'] for x in json.loads((args.output.parent/'package-physical-usb5/package-results.json').read_text()) if x['case']=='usb_usb_baseline');f.record('usb_only_no_ble_startup',status=f.status())
  deadline=time.monotonic()+25
  while time.monotonic()<deadline:
   chats=f.status().get('chat_activity',{})
   if chats.get('available') and (chats.get('running'),chats.get('waiting'),chats.get('done'))==(0,0,1):break
   time.sleep(.5)
  f.record('synthetic_chat_inventory_counts',chats.get('available') and (chats.get('running'),chats.get('waiting'),chats.get('done'))==(0,0,1),chat_activity=chats)
  for i in range(2):f.wait(dict.fromkeys(IDS,'usb'));f.capture('available-tasks-0-0-1',i)
  for i in range(2):
   peer=1-i
   f.cli('devices','disable',IDS[peer]);_,rows=f.wait({IDS[i]:'usb'});f.record(f'single_usb_only_{i}',status=rows)
   f.cli('devices','enable',IDS[peer]);f.wait(dict.fromkeys(IDS,'usb'))
  for i in range(2):
   # Explicit off remains off over BLE and USB reclaims, independent of fresh policy.
   f.event({'type':'device_control','device_id':IDS[i],'command':'screen','value':False});time.sleep(1)
   for mode,kind in [('bluetooth_only','bluetooth'),('usb_only','usb')]:
    f.mode(i,mode);_,rows=f.wait({IDS[i]:kind});state=next(d['device_state'] for d in rows if d['device_id']==IDS[i]);f.record(f'manual_off_{i}_{kind}',state['manual_on'] is False and state['screen_on'] is False,state=state)
   f.event({'type':'device_control','device_id':IDS[i],'command':'screen','value':True});time.sleep(1)
   f.mode(i,'bluetooth_only');f.wait({IDS[i]:'bluetooth'});f.mode(i,'auto');_,rows=f.wait({IDS[i]:'usb'});state=next(d['device_state'] for d in rows if d['device_id']==IDS[i]);f.record(f'explicit_on_{i}',state['manual_on'] is True and state['screen_on'] is True,state=state)
   # A genuine exclusive external COM holder remains alive while Auto falls back.
   f.cli('devices','disable',IDS[i]);time.sleep(1)
   with SerialSession(PORTS[i]) as holder:
    f.cli('devices','mode',IDS[i],'auto');f.cli('devices','enable',IDS[i]);elapsed,rows=f.wait({IDS[i]:'bluetooth',IDS[1-i]:'usb'});f.record(f'external_busy_port_{i}',holder.serial.is_open,elapsed=elapsed,status=rows)
   elapsed,rows=f.wait(dict.fromkeys(IDS,'usb'));f.record(f'external_port_released_{i}',elapsed=elapsed,status=rows)
 finally:
  restore_error=None
  try:f.restore_settings()
  except Exception as exc:restore_error=str(exc)
  f.stop()
  subprocess.Popen([str(args.original.resolve()),'--daemon'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
  deadline=time.monotonic()+90;restored=None
  while time.monotonic()<deadline:
   try:
    restored=f.event({'type':'ping'},original=True);rows=restored['ble']['devices']
    if len(rows)>=2 and all(d['connected'] and d.get('last_ack_age_sec') is not None and d['last_ack_age_sec']<10 for d in rows):break
   except (OSError,ValueError):pass
   time.sleep(1)
  f.record('original_restored',restored is not None and all(d['connected'] for d in restored['ble']['devices']),status=restored)
  if restore_error:f.record('settings_restore_error',False,error=restore_error)
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('output',type=Path);p.add_argument('home',type=Path);p.add_argument('--original',type=Path,required=True);run(p.parse_args())
