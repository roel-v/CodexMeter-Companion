"""Exercise real display-panel widgets with an isolated IPC fixture, including in onefile builds."""
import time
from .device_dialog import show_devices


def check_device_commands(root):
    first, second = 'codexmeter-000000000001', 'codexmeter-000000000002'
    state = {'rev': 2, 'boot': 'a'*16, 'brightness': 40, 'rotation': 0, 'page': 1, 'screen_on': True}
    requests=[]; outcome={'status':'queued'}; connected=[True]; legacy=[False]
    async def sender(event):
        if event['type']=='ping':
            return {'ok':True,'devices':{'devices':[
                {'device_id':key,'connected':connected[0],'device_state':state,
                 'capabilities':['brightness','rotation','screen']} for key in (first,second)]}}
        if event['type']=='device_control':
            requests.append(event)
            return {'ok':True,'queued':event['command'],**({} if legacy[0] else {'command_id':f'{len(requests):032x}'})}
        if event['type']=='command_result':
            return {'ok':True,'result':dict(outcome)}
        if event['type']=='device_state_refresh':
            return {'ok':True,'state':state}
        raise AssertionError(event)
    window=show_devices(root,sender=sender);window.withdraw()
    tree=window.nametowidget('displays');controls=window.nametowidget('controls')
    label=window.nametowidget('command_status')
    def text():return str(label.cget('text'))
    def until(predicate):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            root.update()
            if predicate():return
            time.sleep(.01)
        raise AssertionError('Display panel condition timed out: '+text())
    try:
        until(lambda:len(tree.get_children())==2)
        tree.selection_set(first);root.update()
        controls.nametowidget('brightness').invoke()
        until(lambda:text()=='Queued.')
        outcome.update(status='rejected',reason='conflict',readback=state)
        until(lambda:'Settings changed' in text())
        assert str(controls.nametowidget('retry').cget('state'))=='normal'
        tree.selection_set(second);root.update();assert 'Settings changed' not in text()
        tree.selection_set(first);root.update();assert 'Settings changed' in text()
        outcome.clear();outcome.update(status='applied',readback_pending=True)
        controls.nametowidget('retry').invoke()
        until(lambda:'Applied (display acknowledged).' in text())
        outcome.update(readback_pending=False,readback_error='unavailable')
        until(lambda:'readback unavailable' in text())
        assert len(requests)==2 and 'readback unavailable' in text()
        outcome.clear();outcome.update(status='unknown')
        controls.nametowidget('brightness').invoke()
        until(lambda:'Outcome unknown' in text())
        assert str(controls.nametowidget('retry').cget('state'))=='disabled'
        controls.nametowidget('check_settings').invoke()
        until(lambda:str(controls.nametowidget('retry').cget('state'))=='normal')
        connected[0]=False
        until(lambda:str(controls.nametowidget('retry').cget('state'))=='disabled')
        assert len(requests)==3  # Checking settings never sends another command.
        connected[0]=True
        until(lambda:str(controls.nametowidget('brightness').cget('state'))=='normal')
        legacy[0]=True
        controls.nametowidget('brightness').invoke()
        until(lambda:'Queued; confirmation unavailable' in text())
        window.destroy();root.update()
        return {'queued_conflict_retry':True,'ack_readback_failure':True,'unknown_check':True,
                'selection_fenced':True,'disconnected_retry_disabled':True,'older_daemon':True}
    finally:
        if window.winfo_exists():window.destroy()
