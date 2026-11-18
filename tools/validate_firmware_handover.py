#!/usr/bin/env python3
"""Physical Phase 2 USB/BLE fixtures. Stop the companion before invoking.

Uses full identity verification before application writes. BLE trains deliberately
use 15 logical bytes, the minimum-MTU payload; actual negotiated MTU is recorded.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import secrets
import time
from pathlib import Path

from serial_device import SerialSession

SERVICE='4c41555a-4465-7669-6365-000000000001'
RX='4c41555a-4465-7669-6365-000000000002'
TX='4c41555a-4465-7669-6365-000000000003'
IDENTITY='4c41555a-4465-7669-6365-000000000005'


async def run(args,report):
    from bleak import BleakClient,BleakScanner
    report['cases']=[]
    def check(name,condition,**evidence):
        report['cases'].append({'name':name,'passed':bool(condition),**evidence})
        if not condition:raise RuntimeError(name)
        print(json.dumps({'case':name,'passed':True}),flush=True)
    with SerialSession(args.port) as usb:
        usb.serial.timeout=.05;usb.serial.write_timeout=.5
        usb.write_line('identity')
        identity=None
        for _ in range(16):
            line=usb.read_line(1)
            if line.startswith(b'IDENTITY '):identity=json.loads(line[9:]);break
        check('usb_identity',identity and identity.get('device_id')==args.expected_id,identity=identity)
        boot=identity['boot'];host=secrets.token_hex(16);token=secrets.token_hex(16);q=0
        async def urequest(op,**fields):
            nonlocal q
            q+=1;value={'op':op,'q':q,'boot':boot,'token':token,**fields}
            usb.write_line('CM1 '+json.dumps(value,separators=(',',':')))
            for _ in range(16):
                line=await asyncio.to_thread(usb.read_line,1)
                if not line.startswith(b'CM1 '):continue
                result=json.loads(line[4:])
                if result.get('q')==q and result.get('token')==token and result.get('boot')==boot:return result
            raise RuntimeError('USB reply correlation')
        async def udata(seq,payload,rev='-'):
            usb.write_line(f'CM1 DATA {boot} {token} {seq} {rev} '+json.dumps(payload,separators=(',',':')))
            line=await asyncio.to_thread(usb.read_line,1)
            result=json.loads(line[4:]);check('usb_data_'+str(seq),result.get('ok') is True and result.get('seq')==seq,response=result)
            return result
        devices=await BleakScanner.discover(timeout=8,return_adv=True)
        selected=None
        # Read identity independently for candidates advertising this service.
        for device,adv in devices.values():
            if SERVICE not in [s.lower() for s in adv.service_uuids]:continue
            if device.name!=identity.get('name'):continue
            candidate=BleakClient(device,timeout=10)
            await candidate.connect()
            found=json.loads(bytes(await candidate.read_gatt_char(IDENTITY)))
            if found.get('device_id')==args.expected_id:selected=candidate;break
            await candidate.disconnect()
        if not selected:raise RuntimeError('verified BLE unit absent')
        client=selected
        baseline=None
        changed_power=False
        try:
            report['ble_mtu']=client.mtu_size
            report['ble_fragment_write_response']=not args.no_response
            check('ble_identity',found['boot']==boot and found.get('ble_owner')==1,identity=found)
            replies=asyncio.Queue(maxsize=8);assembly=bytearray();total=0
            def notify(_,raw):
                nonlocal total
                value=bytes(raw)
                if value[:1]==b'\x1e':
                    if len(value)<6:return
                    n=int.from_bytes(value[1:3],'big');offset=int.from_bytes(value[3:5],'big')
                    if offset==0:assembly.clear();total=n
                    if n!=total or offset!=len(assembly) or n>640:assembly.clear();return
                    assembly.extend(value[5:])
                    if len(assembly)!=total:return
                    value=bytes(assembly);assembly.clear()
                try:
                    parsed=json.loads(value[4:] if value.startswith(b'CM1 ') else value)
                    if not replies.full():replies.put_nowait(parsed)
                except (ValueError,UnicodeError):pass
            await client.start_notify(TX,notify)
            activity={'v':1,'k':'activity','src':'codex','run':1,'t':1784000000}
            await client.write_gatt_char(RX,json.dumps(activity,separators=(',',':')).encode(),response=True)
            check('legacy_ble_ack',(await asyncio.wait_for(replies.get(),2)).get('ack') is True)
            claim=await urequest('claim',host=host);check('usb_preempts_legacy',claim.get('ok') is True,response=claim)
            baseline=claim['state']
            while not replies.empty():replies.get_nowait()
            await udata(1,activity)
            try:
                unexpected=await asyncio.wait_for(replies.get(),.4)
                check('usb_ack_never_ble',False,response=unexpected)
            except asyncio.TimeoutError:check('usb_ack_never_ble',True)
            await client.write_gatt_char(RX,json.dumps(activity,separators=(',',':')).encode(),response=True)
            try:
                unexpected=await asyncio.wait_for(replies.get(),.4)
                check('legacy_blocked_during_usb',False,response=unexpected)
            except asyncio.TimeoutError:check('legacy_blocked_during_usb',True)
            alert_id=secrets.token_hex(6)
            alert={'v':1,'k':'alert','id':alert_id,'title':'Protocol test','body':'Transport handover fixture','t':1784000000}
            await udata(2,alert)
            check('usb_release',(await urequest('release')).get('ok') is True)
            # Negotiate BLE using a fresh long identity read and token.
            await client.read_gatt_char(IDENTITY)
            btoken=secrets.token_hex(16);bq=0
            async def bsend(text):
                logical=text.encode();started=time.monotonic()
                fragment_bytes=args.fragment_bytes or min(507,client.mtu_size-8)
                for offset in range(0,len(logical),fragment_bytes):
                    fragment=b'\x1e'+len(logical).to_bytes(2,'big')+offset.to_bytes(2,'big')+logical[offset:offset+fragment_bytes]
                    remaining=2-(time.monotonic()-started)
                    if remaining<=0:raise TimeoutError('whole BLE train exceeded2s')
                    await asyncio.wait_for(client.write_gatt_char(RX,fragment,response=not args.no_response),remaining)
                report.setdefault('ble_train_seconds',[]).append(round(time.monotonic()-started,3))
            async def brequest(op,**fields):
                nonlocal bq
                bq+=1
                await bsend('CM1 '+json.dumps({'op':op,'q':bq,'boot':boot,'token':btoken,**fields},separators=(',',':')))
                result=await asyncio.wait_for(replies.get(),2)
                check('ble_'+op,result.get('q')==bq and result.get('token')==btoken and result.get('ok') is True,response=result)
                return result
            await brequest('claim',host=host)
            maximum=json.dumps({'v':1,'k':'usage','src':'codex','h5':75,'h5r':1784001000,'d7':60,'d7r':1784090000,'td':123,'t7':456,'st':'ok','t':1784000000,'b0':[1,2,3,4,5,6,0,0],'b7':[7,8,9,10,11,12,0,0]},separators=(',',':'))
            maximum+=' '*(512-len(maximum))
            await bsend(f'CM1 DATA {boot} {btoken} 1 - '+maximum)
            result=await asyncio.wait_for(replies.get(),2)
            check('ble_512_minimum_fragment',result.get('ok') is True and result.get('seq')==1,response=result,application_bytes=len(maximum))
            await bsend(f'CM1 DATA {boot} {btoken} 2 - '+json.dumps(alert,separators=(',',':')))
            result=await asyncio.wait_for(replies.get(),2)
            check('alert_retry_across_transport',result.get('ok') is True and result.get('seq')==2,response=result)
            usb.write_line('logs 48')
            alert_log_count=0
            for _ in range(52):
                line=await asyncio.to_thread(usb.read_line,1)
                if b'alert id='+alert_id.encode() in line:alert_log_count+=1
                if line==b'LOGS_END':break
            check('alert_presented_once',alert_log_count==1,count=alert_log_count)
            # Cross-PC USB takeover preserves physical settings/manual intent.
            usb.write_line('identity');await asyncio.to_thread(usb.read_line,1)
            token=secrets.token_hex(16);host=secrets.token_hex(16)
            claim=await urequest('claim',host=host)
            check('usb_preempts_negotiated',claim.get('ok') is True and claim['state']['same_host'] is False,response=claim)
            notice=await asyncio.wait_for(replies.get(),2)
            check('ble_owner_busy_notice',notice.get('op')=='owner' and notice.get('err')=='busy_usb',response=notice)
            for key in ('page','brightness','rotation','auto_rotation','manual_on'):
                check('preserved_'+key,claim['state'][key]==baseline[key])
            rev=claim['state']['rev']
            changed_power=True
            await udata(1,{'v':1,'k':'control','cmd':'screen','on':False,'why':'mac_locked','t':1},str(rev))
            off=await urequest('state')
            check('manual_off',off['state']['manual_on'] is False and off['state']['screen_on'] is False,response=off)
            await udata(2,{'v':1,'k':'control','cmd':'screen','on':True,'why':'unlock','t':1})
            unlocked=await urequest('state')
            check('unlock_preserves_manual_off',unlocked['state']['screen_on'] is False and unlocked['state']['manual_on'] is False,response=unlocked)
            await udata(3,{'v':1,'k':'control','cmd':'screen','on':baseline['manual_on'],'why':'explicit','t':1},str(off['state']['rev']))
            await udata(4,{'v':1,'k':'control','cmd':'screen','on':baseline['policy_on'],'why':'unlock' if baseline['policy_on'] else 'lock','t':1})
            changed_power=False
            check('release_for_ble_reclaim',(await urequest('release')).get('ok') is True)
            await client.read_gatt_char(IDENTITY)
            btoken=secrets.token_hex(16);bq=0
            await brequest('claim',host=host)
            check('same_connection_ble_reclaim',True)
            usb.write_line('identity')
            for _ in range(16):
                if (await asyncio.to_thread(usb.read_line,1)).startswith(b'IDENTITY '):break
            token=secrets.token_hex(16)
            check('claim_for_lease_expiry',(await urequest('claim',host=host)).get('ok') is True)
            notice=await asyncio.wait_for(replies.get(),2)
            check('second_busy_notice',notice.get('err')=='busy_usb')
            # Silence without releasing: lease expiry must permit legacy BLE.
            await asyncio.sleep(7.2)
            await client.write_gatt_char(RX,json.dumps(activity,separators=(',',':')).encode(),response=True)
            check('legacy_after_usb_lease_expiry',(await asyncio.wait_for(replies.get(),2)).get('ack') is True)
            if args.freshness:
                usb.write_line('identity');await asyncio.to_thread(usb.read_line,1)
                token=secrets.token_hex(16)
                check('freshness_claim',(await urequest('claim',host=host)).get('ok') is True)
                await udata(1,activity)
                start=time.monotonic()
                while time.monotonic()-start<302:
                    await asyncio.sleep(2)
                    check('freshness_ping',(await urequest('ping')).get('ok') is True)
                usb.write_line('health')
                health=(await asyncio.to_thread(usb.read_line,1)).decode()
                check('heartbeat_does_not_refresh_data','waiting=1' in health,health=health)
                await urequest('release')
        finally:
            try:
                await urequest('release')
                if changed_power and baseline:
                    usb.write_line('identity')
                    for _ in range(16):
                        if (await asyncio.to_thread(usb.read_line,1)).startswith(b'IDENTITY '):break
                    token=secrets.token_hex(16)
                    cleanup=await urequest('claim',host=host)
                    if not cleanup.get('ok'):raise RuntimeError('cleanup claim denied')
                    await udata(1,{'v':1,'k':'control','cmd':'screen','on':baseline['policy_on'],'why':'unlock' if baseline['policy_on'] else 'lock','t':1})
                    await udata(2,{'v':1,'k':'control','cmd':'screen','on':baseline['manual_on'],'why':'explicit','t':1},str(cleanup['state']['rev']))
                    await urequest('release')
                    report['cleanup_power_restored']=True
            except Exception as cleanup_error:
                report['cleanup_error']=f'{type(cleanup_error).__name__}: {cleanup_error}'
            await client.disconnect()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True);parser.add_argument('--expected-id',required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--freshness',action='store_true')
    parser.add_argument('--fragment-bytes',type=int,default=0,help='Logical bytes per BLE fragment;0 uses negotiatedMTU')
    parser.add_argument('--no-response',action='store_true',default=True,help='Use boundedsequentialWNR; correlatedapplicationACKrequired(default)')
    parser.add_argument('--with-response',dest='no_response',action='store_false',help='Diagnosticregressiononly: acknowledgedATTwrites')
    args=parser.parse_args();report={'passed':False,'port':args.port,'expected_id':args.expected_id}
    try:asyncio.run(run(args,report));report['passed']=True
    except Exception as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'report':str(args.output),'error':report.get('error')}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
