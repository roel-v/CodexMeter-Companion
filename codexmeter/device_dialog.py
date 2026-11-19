"""Per-display status and capability-aware controls over authenticated local IPC."""
from __future__ import annotations
import asyncio
import queue
import threading


def device_row(device):
    state = "Connected" if device.get("connected") else "Disconnected"
    state = {"maintenance":"Maintenance", "owned_elsewhere":"In use elsewhere", "probing":"Probing", "switching":"Switching"}.get(device.get("connection_state"), state)
    if device.get("compatibility") == "incompatible":
        state = "Incompatible protocol"
    if not device.get("enabled", True):
        state = "Auto-connect off"
    return (device.get("label") or device["device_id"], device.get("model") or "Legacy / unknown",
            device.get("firmware") or "Unknown", state,
            device.get("last_error") or device.get("metric_validity_note") or (f"ACK {device['last_ack_age_sec']}s ago" if device.get("last_ack_age_sec") is not None else "No acknowledgement yet"), device.get("transport") or "—",
            device.get("connection_mode", "auto"), (device.get("fallback_reason") or "—") if device.get("enabled", True) else "—")


def show_devices(parent, *, sender=None):
    import tkinter as tk
    from tkinter import ttk
    from .events import send_event
    from .command_results import TERMINAL
    sender = sender or send_event
    window = tk.Toplevel(parent)
    window.title('CodexMeter — Displays')
    window.geometry('1250x470')
    ttk.Label(window, text='Select a display to control it. Other displays keep their own settings.').pack(pady=10)
    columns=('name','model','firmware','state','detail','transport','mode','owner')
    tree=ttk.Treeview(window,name='displays',columns=columns,show='headings',height=7,selectmode='browse')
    for key,title in zip(columns,('Display','Model','Firmware','Connection','Last ACK / result','Transport','Mode','Owner / reason')):
        tree.heading(key,text=title);tree.column(key,width=170)
    tree.pack(fill='both',expand=True,padx=10)
    status=tk.StringVar(value='Loading…')
    row=ttk.Frame(window,name='controls');row.pack(fill='x',padx=10,pady=8)
    brightness=tk.IntVar(value=70);rotation=tk.StringVar(value='0')
    ttk.Spinbox(row,from_=10,to=100,textvariable=brightness,width=5).pack(side='left')
    results=queue.Queue();devices={};commands={};closed=False;refreshing=False;sequence=0
    buttons={};after_ids=set();pending=set()
    def settings_text(state):
        return (f"brightness {state.get('brightness', '?')}%, rotation {state.get('rotation', '?')}°, "
                f"page {state.get('page', 0)+1}, screen {'on' if state.get('screen_on') else 'off'}")
    def later(delay,callback):
        handle=None
        def invoke():
            after_ids.discard(handle)
            if not closed:callback()
        handle=window.after(delay,invoke);after_ids.add(handle)
    def launch(event,tag):
        def work():
            try:result=asyncio.run(sender(event))
            except Exception as exc:result={'ok':False,'error':str(exc)}
            results.put((tag,result))
        threading.Thread(target=work,daemon=True).start()
    def selected_id():
        selection=tree.selection()
        return selection[0] if selection else None
    def render():
        key=selected_id();device=devices.get(key,{});record=commands.get(key)
        connected=bool(device.get('connected') and device.get('enabled',True) and not device.get('maintenance')
                       and device.get('compatibility')!='incompatible')
        auto_button.configure(text='Disable auto-connect' if device.get('enabled', True) else 'Enable auto-connect',
                              state='normal' if device else 'disabled')
        caps=device.get('capabilities')
        for name,button in buttons.items():
            cap='screen' if name in ('on','off') else name
            allowed=connected and ((caps is None and cap=='screen') or caps is not None and cap in caps)
            button.configure(state='normal' if allowed else 'disabled')
        retry_allowed=False
        if record:
            result=record.get('result') or {};state=result.get('status')
            retry_allowed=connected and state in ('rejected','expired','cancelled','unknown') and bool(
                record.get('checked') or result.get('readback'))
            status.set(record['message'])
        else:
            status.set('Settings apply only to the selected display.' if devices else 'No displays registered.')
        retry_button.configure(state='normal' if retry_allowed else 'disabled')
        check_button.configure(state='normal' if connected and device.get('device_state') else 'disabled')
    def submit(event):
        nonlocal sequence
        sequence+=1;key=event['device_id']
        commands[key]={'seq':sequence,'event':event,'id':None,'message':'Submitting…'}
        launch(event,('control',key,sequence));render()
    def control(command,value):
        key=selected_id()
        if not key:return
        try:chosen=value()
        except (ValueError,tk.TclError):status.set('Enter a valid value.');return
        submit({'type':'device_control','device_id':key,'command':command,'value':chosen})
    for name,command,getter in (('brightness','brightness',brightness.get),('rotation','rotation',lambda:int(rotation.get())),
                               ('on','screen',lambda:True),('off','screen',lambda:False)):
        if name=='rotation':ttk.Combobox(row,textvariable=rotation,values=('0','90','180','270'),state='readonly',width=5).pack(side='left')
        buttons[name]=ttk.Button(row,name=name,text={'on':'Screen on','off':'Screen off'}.get(name,'Set '+name),
                                 command=lambda c=command,v=getter:control(c,v))
        buttons[name].pack(side='left',padx=5)
    def retry():
        key=selected_id();record=commands.get(key)
        if record and str(retry_button.cget('state'))!='disabled':submit(dict(record['event']))
    def check():
        key=selected_id();record=commands.get(key)
        if record:launch({'type':'device_state_refresh','device_id':key},('check',key,record['seq']))
    check_button=ttk.Button(row,name='check_settings',text='Check settings',command=check)
    check_button.pack(side='left',padx=5)
    retry_button=ttk.Button(row,name='retry',text='Retry command',command=retry)
    retry_button.pack(side='left',padx=5)
    connection=ttk.Frame(window);connection.pack(fill='x',padx=10,pady=5)
    mode=tk.StringVar(value='auto')
    ttk.Combobox(connection,name='connection_mode',textvariable=mode,values=('auto','usb_only','bluetooth_only'),
                 state='readonly',width=18).pack(side='left')
    def operation(kind,**values):
        key=selected_id()
        if key:launch({'type':kind,'device_id':key,**values},('operation',key))
    for name,text,callback in (
        ('apply_mode','Apply connection mode',lambda:operation('device_mode',connection_mode=mode.get())),
        ('maintenance_pause','Pause for maintenance',lambda:operation('maintenance_acquire')),
        ('maintenance_resume','Resume',lambda:operation('maintenance_resume'))):
        ttk.Button(connection,name=name,text=text,command=callback).pack(side='left',padx=5)
    def toggle_auto_connect():
        device = devices.get(selected_id())
        if device:
            operation('device_registry_update', action='enabled', enabled=not device.get('enabled', True))
    auto_button = ttk.Button(connection, name='auto_connect', command=toggle_auto_connect)
    auto_button.pack(side='left', padx=5)
    def selected(_event=None):
        device=devices.get(selected_id(),{})
        mode.set(device.get('connection_mode','auto'))
        state=device.get('device_state',{})
        if state:
            brightness.set(state.get('brightness',70));rotation.set(str(state.get('rotation',0)))
        render()
    tree.bind('<<TreeviewSelect>>',selected)
    ttk.Label(window,name='command_status',textvariable=status,wraplength=1150).pack(padx=10,pady=5)
    def refresh():
        nonlocal refreshing
        if not closed and not refreshing:
            refreshing=True;launch({'type':'ping'},('status',))
    def query(key,record):
        tag=('result',key,record['seq'],record['id'])
        outcome = record.get('result') or {}
        if record['id'] and tag not in pending and (outcome.get('status') not in TERMINAL or outcome.get('readback_pending')):
            pending.add(tag);launch({'type':'command_result','device_id':key,'command_id':record['id']},tag)
    def poll():
        nonlocal refreshing
        if closed:return
        try:
            while True:
                tag,result=results.get_nowait();kind=tag[0];pending.discard(tag)
                if kind=='status':
                    refreshing=False
                    if result.get('ok'):
                        new={d['device_id']:d for d in result.get('devices',{}).get('devices',[])}
                        devices.clear();devices.update(new)
                        for item in tree.get_children():
                            if item not in new:tree.delete(item)
                        for key,device in new.items():
                            if tree.exists(key):tree.item(key,values=device_row(device))
                            else:tree.insert('','end',iid=key,values=device_row(device))
                        render()
                    elif not commands.get(selected_id()):status.set(result.get('error','Companion unavailable'))
                    else:
                        devices.clear();render()
                    continue
                if kind=='operation':
                    if selected_id()==tag[1]:status.set('Operation completed.' if result.get('ok') else result.get('error','Operation failed'))
                    refresh();continue
                key=tag[1];record=commands.get(key)
                if not record or record['seq']!=tag[2]:continue
                if kind=='control':
                    if result.get('ok'):
                        record['id']=result.get('command_id')
                        record['message']='Queued.' if record['id'] else 'Queued; confirmation unavailable with this companion.'
                        query(key,record)
                    else:record['message']=result.get('error','Command rejected before admission')
                elif kind=='check':
                    record['checked']=bool(result.get('ok'))
                    if result.get('ok'):
                        state=result['state'];record['message']+=' Current settings: '+settings_text(state)+'. Retry sends a new command.'
                    else:record['message']=result.get('error','Settings unavailable')
                elif kind=='result' and record['id']==tag[3]:
                    if not result.get('ok'):
                        record['message']='Result unavailable; reconnecting to companion. No success confirmed.'
                    elif result.get('result') is None:
                        record['message']='Result unavailable (expired or companion restarted). No success confirmed.'
                        record['id']=None
                    else:
                        outcome=result['result'];record['result']=outcome
                        state=outcome['status']
                        record['message']={'queued':'Queued.','sending':'Sending…','applied':'Applied (display acknowledged).',
                            'unknown':'Outcome unknown. Check settings before retrying.','expired':'Expired before sending.',
                            'superseded':'Superseded by another command.','cancelled':'Cancelled before sending.',
                            'rejected':'Rejected: '+outcome.get('reason','')}.get(state,state)
                        if outcome.get('reason')=='conflict':record['message']='Settings changed on the display. Review current settings, then Retry if wanted.'
                        if outcome.get('readback'):record['message']+=' Current settings: '+settings_text(outcome['readback'])
                        if outcome.get('readback_error'):record['message']+=' Settings readback unavailable.'
                render()
        except queue.Empty:pass
        later(100,poll)
    def timer():
        if not closed:
            refresh()
            for key,record in commands.items():query(key,record)
            later(1000,timer)
    def cancel_callbacks():
        for handle in tuple(after_ids):
            try:window.after_cancel(handle)
            except tk.TclError:pass
        after_ids.clear()
    def close():
        nonlocal closed
        closed=True;cancel_callbacks();window.destroy()
    def destroyed(event):
        nonlocal closed
        if event.widget is window:closed=True;cancel_callbacks()
    window.protocol('WM_DELETE_WINDOW',close);window.bind('<Destroy>',destroyed)
    render();timer();poll()
    return window
