#!/usr/bin/env python3
"""Preserve a private full-flash rollback after checking exact live identity."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
from serial_device import SerialSession


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True)
    parser.add_argument('--expected-id',required=True)
    parser.add_argument('--chip',choices=['esp32c6','esp32s3'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--esptool',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise RuntimeError('refusing to overwrite any existing backup directory')
    if args.output.drive.upper()!='E:':
        raise RuntimeError('retained private backup must be on E:')
    with SerialSession(args.port) as session:
        session.write_line('identity')
        identity=None
        for _ in range(32):
            line=session.read_line(1)
            if line.startswith(b'IDENTITY '):
                identity=json.loads(line[9:]);break
        if not identity or identity.get('device_id')!=args.expected_id:
            raise RuntimeError('live identity mismatch; no bootloader operation issued')
    args.output.mkdir(parents=True)
    image=args.output/'current-full-16MiB.bin'
    command=[str(args.esptool),'--chip',args.chip,'--port',args.port,'--baud','460800','read-flash','0','0x1000000',str(image)]
    metadata={'created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'identity_before_bootloader':identity,'port':args.port,'chip':args.chip,'command':command,'size':None,'sha256':None,'private':True,'purpose':'pre-USB-phase2 exact current rollback; includes NVS and artwork; never publish'}
    (args.output/'recovery.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    with (args.output/'read-flash.log').open('wb') as log:
        result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=600)
    if result.returncode:
        raise RuntimeError('flash backup failed; see private read-flash.log')
    if image.stat().st_size!=0x1000000:
        raise RuntimeError('full-flash backup size mismatch')
    metadata['size']=image.stat().st_size
    metadata['sha256']=hashlib.sha256(image.read_bytes()).hexdigest()
    metadata['restore_command']=[str(args.esptool),'--chip',args.chip,'--port',args.port,'--baud','460800','write-flash','0',str(image)]
    metadata['restore_warning']='Recovery-only full restore overwrites NVS/artwork. Normal upgrades write application only.'
    (args.output/'recovery.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'backup':str(image),'bytes':metadata['size'],'sha256':metadata['sha256'],'identity':args.expected_id}))


if __name__=='__main__':
    main()
