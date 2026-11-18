"""Exact-package cleanup acceptance on the two attached displays.

Uses an isolated profile and synthetic telemetry. Production is stopped gracefully and
restored in finally; device settings are restored through identity-checked maintenance.
"""
import argparse
import hashlib
import json
import os
import sys
import subprocess
import threading
import time
from pathlib import Path
from validate_usb_package import Fixture, IDS, PORTS, ROOT

class CleanupFixture(Fixture):
    validation_mode = True
    def control(self, index, command, value):
        result = self.event({'type':'device_control','device_id':IDS[index],'command':command,'value':value})
        assert result['ok'], result
        key = 'manual_on' if command == 'screen' else command
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = next(d['device_state'] for d in self.devices() if d['device_id'] == IDS[index])
            if state[key] == value:
                return
            time.sleep(.2)
        raise AssertionError(f'Control did not apply: {index} {command}={value}')

    def feed_capture(self, label, payloads, pages=False):
        from validation_capture import expected_model
        from codexmeter.payloads import Payload
        payloads = [dict(data, t=int(time.time())) for data in payloads]
        expected = expected_model(payloads)
        expected_path = self.out/f'{label}-expected.json'
        expected_path.write_text(json.dumps(expected, indent=2), encoding='utf-8')
        hashes = {data['k']: hashlib.sha256(Payload(data['k'],data).to_json_bytes()).hexdigest() for data in payloads}
        stop = threading.Event()
        errors = []
        def feed():
            while not stop.is_set():
                try:
                    for data in payloads:
                        response=self.event({'type':'validation_payload', 'payload':data})
                        if not response.get('ok'):raise ValueError(response)
                except Exception as exc:
                    errors.append(type(exc).__name__)
                    return
                stop.wait(.5)
        worker = threading.Thread(target=feed)
        worker.start()
        try:
            for index in range(2):
                self.wait(dict.fromkeys(IDS,self.capture_transport))
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    row=next(d for d in self.devices() if d['device_id']==IDS[index])
                    if row.get('accepted_hashes')==hashes:break
                    if errors:raise RuntimeError(errors)
                    time.sleep(.1)
                else:raise TimeoutError('Missing independent fixture acknowledgements')
                env=dict(self.env);env['PYTHONPATH']=str(ROOT)
                args=[sys.executable,str(ROOT/'tools/capture_validation_pages.py'),PORTS[index],str(self.out/f'{label}-{index}'),'--device-id',IDS[index],'--expected',str(expected_path)]
                if index==0:args.append('--c6')
                if not pages:args.append('--overview-only')
                result=subprocess.run(args,env=env,cwd=self.home,capture_output=True,text=True,timeout=100,creationflags=subprocess.CREATE_NO_WINDOW)
                self.record(f'page_files_{label}_{index}',result.returncode==0,stderr=result.stderr,
                            device_id=IDS[index],transport=self.capture_transport,accepted_hashes=hashes,expected=expected,
                            visual_review='pending')
            assert not errors,errors
        finally:
            stop.set();worker.join(15)
            if worker.is_alive():raise RuntimeError('Fixture publisher failed to finish')

    def run(self):
        self.record('production_baseline',status=self.event({'type':'ping'},original=True))
        try:
            self.event({'type':'shutdown'},original=True);time.sleep(5)
            self.record('fresh_scan',scan=self.cli('devices','scan','--usb-only','--timeout','4'))
            for i,identity in enumerate(IDS):self.cli('devices','adopt',identity,'--alias',f'Cleanup-{i}','--connection-mode','usb_only')
            self.start();self.baseline=self.devices();self.record('baseline',status=self.baseline)
            reference={d['device_id']:{k:d.get(k) for k in ('model','firmware','protocol','width','height','capabilities')} for d in self.baseline}
            now=int(time.time())
            usage={'v':1,'k':'usage','src':'codex','h5':None,'d7':73,'d7r':now+183840,'td':18600000,'t7':236000000,'st':'ok'}
            activity={'v':1,'k':'activity','src':'codex','run':2,'wait':3,'done':4,'chats':True}
            for mode,transport in ([('usb_only','usb')] if self.args.partial_only else [] if self.args.controls_only else [('bluetooth_only','bluetooth')] if self.args.bluetooth_pass else [('usb_only','usb'),('bluetooth_only','bluetooth')]):
                for i in range(2):self.mode(i,mode)
                _,rows=self.wait(dict.fromkeys(IDS,transport))
                self.capture_transport=transport
                current={d['device_id']:{k:d.get(k) for k in ('model','firmware','protocol','width','height','capabilities')} for d in rows}
                self.record('identity_'+transport,current==reference,metadata=current)
                for label,counts,chats in ([] if self.args.details_only else [('known',(2,3,4),True),('unknown',(None,None,None),False),('partial',(2,None,None),False),('unknown-running',(None,3,4),True),('unknown-waiting',(2,None,4),True),('unknown-done',(2,3,None),True)]):
                    if self.args.partial_only and label != 'partial':
                        continue
                    data=dict(activity,run=counts[0],wait=counts[1],done=counts[2],chats=chats)
                    self.feed_capture(f'{transport}-{label}',[usage,data])
                if self.args.partial_only:
                    return
                if not self.args.skip_totals:
                    self.feed_capture(f'{transport}-totals-only',[usage,activity],pages=True)
                detailed=dict(usage,b0=[10000000,8000000,600000,100,200,300,1,0],b7=[100000000,130000000,6000000,1000,2000,3000,0,1])
                self.feed_capture(f'{transport}-partial-cost',[detailed,activity],pages=True)
            # Every mixed topology and return to automatic USB selection.
            for modes,wanted in [(('usb_only','bluetooth_only'),('usb','bluetooth')),(('bluetooth_only','usb_only'),('bluetooth','usb')),(('auto','auto'),('usb','usb'))]:
                for i,mode in enumerate(modes):self.mode(i,mode)
                _,rows=self.wait(dict(zip(IDS,wanted)));self.record('mixed_'+'_'.join(wanted),status=rows)
            for i in range(2):
                for command,value in [('brightness',80),('rotation',90),('screen',False)]:
                    self.control(i, command, value)
                self.mode(i,'bluetooth_only');self.wait({IDS[i]:'bluetooth'})
                self.mode(i,'auto');_,rows=self.wait({IDS[i]:'usb'})
                state=next(d['device_state'] for d in rows if d['device_id']==IDS[i])
                self.record(f'manual_controls_survive_handover_{i}',state['brightness']==80 and state['rotation']==90 and not state['manual_on'] and not state['screen_on'],state=state)
                self.control(i, 'screen', True)
                self.control(i, 'rotation', 0)
            self.cli('demo-alert','Cleanup acceptance');time.sleep(.5)
            for i in range(2):self.capture('completion-alert',i)
            self.stop();time.sleep(8)
            for i in range(2):self.capture('waiting',i)
            self.start();self.record('restart_and_modes_persisted',status=self.devices())
            self.capture_transport='usb'
            self.feed_capture('recovered',[usage,activity])
        finally:
            restoration_error = None
            try:
                if self.proc:self.restore_settings()
            except Exception as exc:
                restoration_error = exc
                # Preserve failure while still checking the restored production process.
            finally:
                self.stop()
                subprocess.Popen([str(self.args.original.resolve()),'--daemon'],cwd=self.args.original.resolve().parent,env=os.environ.copy(),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                try:
                    rows=self.event({'type':'ping'},original=True)['devices']['devices']
                    if all(d['connected'] and d.get('last_ack_age_sec') is not None for d in rows):
                        self.record('production_restored',status=rows);break
                except (OSError,ValueError):pass
                time.sleep(1)
            else:raise RuntimeError('Production did not reconnect after acceptance')
            if restoration_error is not None:
                self.record('settings_restoration_failed',False,error=str(restoration_error))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bluetooth-pass',action='store_true');p.add_argument('--details-only',action='store_true');p.add_argument('--skip-totals',action='store_true');p.add_argument('--controls-only',action='store_true');p.add_argument('--partial-only',action='store_true');p.add_argument('binary',type=Path);p.add_argument('output',type=Path);p.add_argument('home',type=Path);p.add_argument('--original',type=Path,required=True)
    CleanupFixture(p.parse_args()).run()
