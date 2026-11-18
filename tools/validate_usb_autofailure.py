"""Actual-board Auto failure fixture; NOT the compiled companion or a cable unplug.

Only this process's serial data boundary is interrupted. Both displays retain
power, actual USB/BLE sessions and firmware ACKs; no ACK or identity is fabricated.
"""
import argparse,asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from codexmeter import usb_transport as usb
from fixture_registry import isolated_registry
from codexmeter.device_manager import DeviceManager
from codexmeter.payloads import build_activity_payload
def fixture_activity():
 p=build_activity_payload(2);p.data.update(wait=3,done=4,chats=True);return p
sys.path.insert(0,str(Path(__file__).resolve().parent))
IDS=['codexmeter-00e216f16e20','codexmeter-6867f4697090'];PORTS=['COM6','COM9']
async def run(args):
    # Never persist maintenance markers into a deployment snapshot or real profile.
    with isolated_registry(args.registry, getattr(args, 'scratch_root', None)) as registry:
        original = usb.open_serial
        args.output.parent.mkdir(parents=True, exist_ok=True)
        try:
            await run_registry(args, registry)
        finally:
            usb.open_serial = original


async def run_registry(args, registry):
    blocked=set();original=usb.open_serial;records=[]
    class Boundary:
        def __init__(self,handle,port):self.handle,self.port=handle,port
        def __getattr__(self,name):return getattr(self.handle,name)
        def read(self,*args):
            if self.port in blocked:time.sleep(.05);return b''
            return self.handle.read(*args)
        def write(self,data):
            if self.port in blocked:return len(data) # host OS accepted; wire deliberately drops bytes
            return self.handle.write(data)
    def opening(port,**kwargs):return Boundary(original(port,**kwargs),port)
    usb.open_serial=opening
    configs=registry.devices
    manager=DeviceManager(configs,connect_timeout_sec=5,disconnect_timeout_sec=.5,write_timeout_sec=2,ack_timeout_sec=2,notify_timeout_sec=2,healthcheck_interval_sec=45,scan_timeout_sec=3,scan_interval_sec=2,host_id='e'*32,registry=registry)
    stop=asyncio.Event();task=asyncio.create_task(manager.run(stop))
    async def producer():
        while not stop.is_set():
            await manager.broadcast(fixture_activity());await asyncio.sleep(.5)
    producing=asyncio.create_task(producer())
    def snap():return manager.status()['devices']
    async def wait(index,transport,after,timeout):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            await manager.broadcast(fixture_activity());await asyncio.sleep(.3)
            rows=snap();d=next(x for x in rows if x['device_id']==IDS[index])
            if d.get('connected') and d.get('transport')==transport and d.get('last_ack_age_sec') is not None and d['last_ack_age_sec']<=time.monotonic()-after+.1 and d.get('last_payload')=='activity':return time.monotonic(),rows
        raise RuntimeError(f'{IDS[index]} did not reach acknowledged {transport}: '+str(snap()))
    async def capture_counts(index):
        lease=await manager.device_operation({'type':'maintenance_acquire','device_id':IDS[index],'port':PORTS[index],'tool':True})
        if not lease.get('ok') or not lease.get('ready'):raise RuntimeError('Source fixture maintenance not ready')
        def capture():
            output=args.output.parent/f'source-counts-2-3-4-{index}.png'
            if index==0:
                from capture_c6_screen import capture
                from serial_device import SerialSession
                with SerialSession(PORTS[index]) as serial:capture(serial,output)
            else:
                from capture_screenshot import capture_rgb565le,rgb565le_to_png
                w,h,data=capture_rgb565le(PORTS[index]);output.write_bytes(rgb565le_to_png(w,h,data))
        try:await asyncio.to_thread(capture)
        finally:await manager.device_operation({'type':'maintenance_release','device_id':IDS[index],'token':lease['token']})
    try:
        for i in range(2):await wait(i,'usb',time.monotonic(),65)
        for i in range(2):
            await capture_counts(i);await wait(i,'usb',time.monotonic(),30)
        for i in range(2):
            initial=next(x['device_state'] for x in snap() if x['device_id']==IDS[i]);cut=time.monotonic();blocked.add(PORTS[i]);detected=None
            while time.monotonic()-cut<12:
                d=next(x for x in snap() if x['device_id']==IDS[i])
                if not d['connected'] or d['transport']!='usb':detected=time.monotonic();break
                await asyncio.sleep(.1)
            if detected is None:raise RuntimeError('USB failure not detected within 12s')
            restored,rows=await wait(i,'bluetooth',detected,35)
            recovered=time.monotonic();blocked.remove(PORTS[i]);adopted,rows=await wait(i,'usb',recovered,35)
            final=next(x['device_state'] for x in rows if x['device_id']==IDS[i]);peer=next(x for x in rows if x['device_id']!=IDS[i])
            record={'device_id':IDS[i],'kind':'source_real_serial_data_boundary','failure_detection_sec':detected-cut,'ble_ack_after_detection_sec':restored-detected,'usb_ack_after_boundary_restore_sec':adopted-recovered,'same_boot':initial['boot']==final['boot'],'peer_ack_age_sec':peer['last_ack_age_sec'],'state_preserved':all(initial[k]==final[k] for k in ('page','brightness','rotation','auto_rotation','manual_on'))}
            record['passed']=record['failure_detection_sec']<=10 and record['ble_ack_after_detection_sec']<=30 and record['same_boot'] and record['state_preserved'] and record['peer_ack_age_sec']<=2
            records.append(record);args.output.write_text(json.dumps(records,indent=2));print(json.dumps(record),flush=True)
            assert record['passed'],record
    finally:
        blocked.clear();stop.set()
        try:
            await asyncio.wait_for(task,20)
        finally:
            producing.cancel();await asyncio.gather(producing,return_exceptions=True);usb.open_serial=original
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('registry',type=Path);p.add_argument('output',type=Path);p.add_argument('--scratch-root',type=Path);asyncio.run(run(p.parse_args()))
