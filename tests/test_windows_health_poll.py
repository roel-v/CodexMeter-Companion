import queue
from types import SimpleNamespace
import pytest
from codexmeter.windows_app import MeterApp

class Value:
    def set(self, value): self.value = value
class ImmediateThread:
    def __init__(self, target, **kwargs): self.target = target
    def start(self): self.target()

def test_external_panel_health_poll_and_recovery(monkeypatch):
    import codexmeter.windows_app as ui
    import codexmeter.events as events
    import codexmeter.pricing as pricing
    monkeypatch.setattr(ui.threading, 'Thread', ImmediateThread)
    monkeypatch.setattr(pricing, 'PricingStore', lambda: SimpleNamespace(status=lambda: {'state':'current'}))
    app = SimpleNamespace(show_sleep_status=lambda activity: None, tray_managed=False, compatibility_polling=False,
        compatibility_results=queue.Queue(), compatibility_snapshot={},
        compatibility_text=Value(), pricing_status=Value(), results=queue.Queue(),
        pricing_review_button=SimpleNamespace(pack_forget=lambda:None),
        root=SimpleNamespace(after=lambda *args:None), poll=lambda:None)
    good={'schema':1,'components':{'quota':{'label':'Quota','state':'compatible'}}}
    for reply, expected in [({'status':'running','compatibility':good}, 'Codex readings are available.'),
                            ({'status':'running'}, 'Checking Codex data compatibility…'),
                            ({'compatibility':{'components':{'bad':None}}}, 'Checking Codex data compatibility…'),
                            (OSError('offline'), 'Checking Codex data compatibility…'),
                            ({'status':'running','compatibility':good}, 'Codex readings are available.')]:
        async def send(event):
            assert event == {'type':'ping'}
            if isinstance(reply, Exception): raise reply
            return reply
        monkeypatch.setattr(events,'send_event',send)
        app.pricing_poll_count=0
        MeterApp.poll(app)
        assert app.compatibility_text.value == expected
        assert not app.compatibility_polling
