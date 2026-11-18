"""Phase5 exact executable fixture. Synthetic data only; no installation or publishing.

The child-only USERPROFILE isolates APP_DIR. This harness uses source Python solely
as an authenticated IPC client/maintenance capture tool, never as the companion.
Mode cycles are real powered transport handovers, not cable failure simulation.
"""
from __future__ import annotations
import argparse, asyncio, hashlib, json, os, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from codexmeter.ipc import send
IDS=['codexmeter-00e216f16e20','codexmeter-6867f4697090']
PORTS=['COM6','COM9']
def redacted(value):
    if isinstance(value,dict):return {k:redacted(v) for k,v in value.items() if k not in ('generation','token','secret','host','session_generation')}
    if isinstance(value,list):return [redacted(x) for x in value]
    return value
class Fixture:
    def __init__(self,args):
        self.args=args;self.out=args.output.resolve();self.out.mkdir(parents=True,exist_ok=True)
        self.home=args.home.resolve();self.app=self.home/'.codexmeter';self.app.mkdir(parents=True,exist_ok=True)
        self.binary=args.binary.resolve();self.env=dict(os.environ)
        for key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','CONDA_PREFIX'):self.env.pop(key,None)
        self.env['USERPROFILE']=str(self.home)
        self.env['PATH']=os.pathsep.join([os.environ['SystemRoot']+'/System32',os.environ['SystemRoot']])
        self.env['TEMP']=self.env['TMP']=str(self.home/'tmp');Path(self.env['TEMP']).mkdir(exist_ok=True)
        self.results=[];self.proc=None;self.log=None;self.changed={};self.previous={};self.baseline=[]
    def record(self,case,passed=True,**data):
        item=redacted(dict(case=case,passed=passed,monotonic=time.monotonic(),**data));self.results.append(item)
        (self.out/'package-results.json').write_text(json.dumps(self.results,indent=2),encoding='utf-8')
        print(json.dumps({'case':case,'passed':passed}),flush=True)
        if not passed:raise AssertionError(case)
    def cli(self,*args):
        p=subprocess.run([str(self.binary),'--cli',*args],env=self.env,cwd=self.home,capture_output=True,text=True,encoding='utf-8',timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
        if p.returncode:raise RuntimeError(p.stderr or p.stdout)
        return json.loads(p.stdout)
    def event(self,event,original=False):
        path=(Path(os.environ['USERPROFILE'])/'.codexmeter' if original else self.app)/'events.sock'
        return asyncio.run(send(event,path))
    def status(self):return self.event({'type':'ping'})
    def devices(self):
        s=self.status();return s.get('devices',s.get('ble',{})).get('devices',[])
    def wait(self,wanted,timeout=65):
        start=time.monotonic();last=[]
        self.event({'type':'activity','count':2})
        while time.monotonic()-start<timeout:
            try:
                last=self.devices();found={d['device_id']:d for d in last}
                if all(i in found and found[i]['connected'] and found[i].get('transport')==kind and found[i].get('last_ack_age_sec') is not None and found[i]['last_ack_age_sec'] <= time.monotonic()-start+.15 and found[i].get('last_payload') in ('activity','usage') and (i not in self.previous or found[i].get('generation') != self.previous[i][0] or kind==self.previous[i][1]) for i,kind in wanted.items()):return time.monotonic()-start,last
            except (OSError,ValueError,KeyError):pass
            time.sleep(.35)
        self.record('transport_timeout',False,wanted=wanted,status=last)
    def mode(self,index,mode):
        before=next(d for d in self.devices() if d['device_id']==IDS[index]);self.previous[IDS[index]]=(before.get('generation'),before.get('transport'))
        response=self.event({'type':'device_mode','device_id':IDS[index],'connection_mode':mode})
        if response.get('ok') is not True:raise RuntimeError(response)
    def start(self):
        self.log=(self.out/'candidate-daemon.log').open('a',encoding='utf-8')
        self.proc=subprocess.Popen([str(self.binary),'--daemon','--foreground','--codex-bin',str(self.home/'no-codex.exe'),'--poll-interval','3600','--scan-timeout','3','--scan-interval','2'],env=self.env,cwd=self.home,stdout=self.log,stderr=self.log,creationflags=subprocess.CREATE_NO_WINDOW)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try:self.status();break
            except (OSError,ValueError):time.sleep(.3)
        self.wait({IDS[0]:'usb',IDS[1]:'usb'})
    def stop(self):
        if self.proc:
            try:self.event({'type':'shutdown'})
            except (OSError,ValueError):pass
            try:self.proc.wait(20)
            except subprocess.TimeoutExpired:raise RuntimeError('Candidate did not exit gracefully; inspect its known parent/child before restarting production')
            self.proc=None
        if self.log:self.log.close();self.log=None
    def capture(self,label,index):
        script='capture_c6_screen.py' if index==0 else 'capture_screenshot.py'
        output=self.out/f'{label}-{index}.png'
        args=[str(PORTS[index]),str(output)] if index==0 else [str(output),PORTS[index]]
        # Source tool is an IPC client; source companion never runs in this matrix.
        toolenv=dict(self.env);toolenv['PYTHONPATH']=str(ROOT)
        p=subprocess.run([sys.executable,str(ROOT/'tools'/script),*args],env=toolenv,cwd=self.home,capture_output=True,text=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
        self.record(f'capture_file_{label}_{index}',p.returncode==0,content_validation='requires independent pixel inspection',stdout=p.stdout,stderr=p.stderr,path=str(output))
    def restore_settings(self):
        if not self.baseline:return
        for index,row in enumerate(self.baseline):
            state=row['device_state']
            code="""import sys,time; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from maintenance import MaintenanceGuard; from serial_device import SerialSession
with MaintenanceGuard(sys.argv[2],sys.argv[3]), SerialSession(sys.argv[2]) as port:
 for command in sys.argv[4:]:port.write_line(command);time.sleep(.2)
"""
            commands=[f"brightness {state['brightness']}", 'rotate auto' if state['auto_rotation'] else f"rotate {state['rotation']}"]
            current=next(d['device_state'] for d in self.devices() if d['device_id']==IDS[index])
            if index==0:
                if bool(current['page'])!=bool(state['page']):commands.append('test_swipe')
                if state['page']:commands.append('test_tap_week' if state['page']==2 else 'test_tap_today')
            else:commands+=['test_swipe']*((state['page']-current['page'])%3)
            toolenv=dict(self.env);toolenv['PYTHONPATH']=str(ROOT)
            result=subprocess.run([sys.executable,'-c',code,str(ROOT/'tools'),PORTS[index],IDS[index],*commands],env=toolenv,cwd=self.home,capture_output=True,text=True,timeout=45)
            self.record(f'restore_settings_sent_{index}',result.returncode==0,stderr=result.stderr)
        for index in range(2):self.mode(index,'auto')
        _,rows=self.wait(dict.fromkeys(IDS,'usb'))
        for before in self.baseline:
            after=next(d['device_state'] for d in rows if d['device_id']==before['device_id'])
            keys=('brightness','rotation','auto_rotation','manual_on','page','boot')
            self.record('restore_settings_readback_'+before['device_id'],all(after[k]==before['device_state'][k] for k in keys),state=after)
    def run(self):
        # Actual production config is read-only throughout. Authenticated graceful shutdown.
        baseline=self.event({'type':'ping'},original=True)
        self.record('production_baseline',status=baseline,binary_sha256=hashlib.sha256(self.args.original.read_bytes()).hexdigest())
        try:
            self.event({'type':'shutdown'},original=True);time.sleep(8)
            scanned=self.cli('devices','scan','--usb-only','--timeout','4')
            self.record('fresh_usb_scan',scan=scanned)
            for i,identity in enumerate(IDS):
                result=self.cli('devices','adopt',identity,'--alias',f'Phase5-{i}','--connection-mode','usb_only')
                self.record(f'fresh_adopt_{i}',result=result)
            self.start();self.baseline=self.devices();self.record('usb_usb_baseline',status=self.baseline)
            for i in range(2):
                response=self.event({'type':'device_control','device_id':IDS[i],'command':'brightness','value':80})
                self.record(f'brightness_queued_{i}',response=response)
                time.sleep(1)
                response=self.event({'type':'device_control','device_id':IDS[i],'command':'rotation','value':90})
                self.record(f'rotation_queued_{i}',response=response)
                time.sleep(1)
                self.mode(i,'bluetooth_only');self.wait({IDS[i]:'bluetooth'})
                self.mode(i,'usb_only');_,rows=self.wait({IDS[i]:'usb'})
                actual=next(d['device_state'] for d in rows if d['device_id']==IDS[i])
                self.record(f'controls_readback_{i}',actual.get('brightness')==80 and actual.get('rotation')==90,device_state=actual)
                self.event({'type':'device_control','device_id':IDS[i],'command':'rotation','value':0});time.sleep(1)
            self.cli('demo-usage','--h5','61','--d7','73','--today-tokens','18600000','--week-tokens','236000000')
            now=int(time.time())
            self.event({'type':'usage','payload':{'v':1,'k':'usage','src':'codex','h5':61,'h5r':now+4380,'d7':73,'d7r':now+259200,'td':18600000,'t7':236000000,'st':'ok','t':now,'b0':[10000000,8000000,600000,100,200,300,0,0],'b7':[100000000,130000000,6000000,1000,2000,3000,0,0]}})
            self.cli('demo-activity','--count','2');time.sleep(2)
            for i in range(2):self.capture('usage',i)
            for i in range(2):
                self.wait(dict.fromkeys(IDS,'usb'))
                toolenv=dict(self.env);toolenv['PYTHONPATH']=str(ROOT)
                command=[sys.executable,str(ROOT/'tools/capture_validation_pages.py'),PORTS[i],str(self.out/f'cost-pages-{i}')]
                if i==0:command.append('--c6')
                result=subprocess.run(command,env=toolenv,cwd=self.home,capture_output=True,text=True,timeout=100)
                self.record(f'cost_page_files_{i}',result.returncode==0,stderr=result.stderr,content_validation='requires independent pixel inspection')
            self.wait(dict.fromkeys(IDS,'usb'))
            self.cli('demo-alert','Phase5 controlled completion');time.sleep(1)
            for i in range(2):self.capture('alert',i)
            for modes,wanted in [(('bluetooth_only','bluetooth_only'),('bluetooth','bluetooth')),(('usb_only','bluetooth_only'),('usb','bluetooth')),(('bluetooth_only','usb_only'),('bluetooth','usb')),(('auto','auto'),('usb','usb'))]:
                for i,mode in enumerate(modes):self.mode(i,mode)
                elapsed,state=self.wait(dict(zip(IDS,wanted)));self.record('matrix_'+'_'.join(wanted),elapsed=elapsed,status=state)
            # Both remain powered. These are explicit mode handovers, not auto cable-loss R20 tests.
            for index in range(2):
                peer=1-index
                for cycle in range(1,11):
                    self.mode(index,'bluetooth_only');ble_elapsed,state=self.wait({IDS[index]:'bluetooth',IDS[peer]:'usb'})
                    self.mode(index,'auto');usb_elapsed,state=self.wait({IDS[index]:'usb',IDS[peer]:'usb'})
                    self.record(f'powered_mode_cycle_{index}_{cycle}',ble_elapsed=ble_elapsed,usb_elapsed=usb_elapsed,status=state)
            self.stop();self.start();self.record('package_restart_persisted_auto',status=self.devices())
        finally:
            restore_error=None
            try:
                self.restore_settings()
            except Exception as exc:
                restore_error=str(exc)
            self.stop()
            subprocess.Popen([str(self.args.original.resolve()),'--daemon'],cwd=str(self.args.original.resolve().parent),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP,env=dict(os.environ))
            deadline=time.monotonic()+90
            restored=None
            while time.monotonic()<deadline:
                try:
                    restored=self.event({'type':'ping'},original=True)
                    ds=restored.get('ble',{}).get('devices',[])
                    if len(ds)>=2 and all(x.get('connected') and x.get('last_ack_age_sec') is not None for x in ds):break
                except (OSError,ValueError):pass
                time.sleep(2)
            if restore_error:self.record('restore_settings_error',False,error=restore_error)
            self.record('original_restored',bool(restored and len(restored.get('ble',{}).get('devices',[]))>=2 and all(x.get('connected') for x in restored['ble']['devices'])),status=restored)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('output',type=Path);p.add_argument('home',type=Path);p.add_argument('--original',type=Path,required=True)
    Fixture(p.parse_args()).run()
