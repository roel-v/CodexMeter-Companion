"""Check the standalone in a disposable D: profile without opening display transports."""
import argparse
import json
import os
import subprocess
from pathlib import Path
from validate_standalone import clean_environment


def run(binary, output, home):
    output.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    env=clean_environment()
    env['USERPROFILE']=str(home.resolve())
    env['TEMP']=env['TMP']=str(home/'tmp')
    Path(env['TEMP']).mkdir(exist_ok=True)
    report=output/'runtime-self-test.json'
    result=subprocess.run([str(binary),'--self-test',str(report)],env=env,cwd=home,
        capture_output=True,text=True,encoding='utf-8',timeout=150,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or not report.exists():
        raise RuntimeError(result.stderr or result.stdout or 'Missing self-test report')
    evidence=json.loads(report.read_text(encoding='utf-8'))
    assert evidence['ok'] and evidence['compiled'], evidence
    checks=[]
    for args,expected in [(['--daemon','--foreground','--help'],0),(['--cli','screen-on'],1),
                          (['--cli','screen-off','--reason','lock'],2)]:
        p=subprocess.run([str(binary),*args],env=env,cwd=home,capture_output=True,
            text=True,encoding='utf-8',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        assert p.returncode==expected, (args,p.returncode,p.stderr)
        if args==['--daemon','--foreground','--help']:assert '--validation-mode' in p.stdout
        checks.append(dict(args=args,exit_code=p.returncode))
    (output/'isolated-cli-checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print('Isolated packaged UI/runtime and CLI checks passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','output','home'):parser.add_argument(name,type=Path)
    args=parser.parse_args();run(args.binary.resolve(),args.output.resolve(),args.home.resolve())
