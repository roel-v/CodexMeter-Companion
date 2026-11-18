import asyncio
import datetime as dt
import json
from unittest.mock import patch
import pytest
from codexmeter.usage_report import publish_report, report_lines
from codexmeter.provider import CodexUsageProvider
from tests.support.provider import FakeClient, FakeLocalUsageReader

NOW = dt.datetime(2026, 11, 18, 12, tzinfo=dt.timezone.utc)
PART = dict(total_tokens=10,tokens=[1,2,7],cost_micro_usd=[1,2,3],unpriced_tokens=0,unknown_tokens=0,models={})

@pytest.mark.parametrize('offset,stale', [(0,False),(301,True),(-1,True),(86400,True)])
def test_dated_report(tmp_path,offset,stale):
    path=tmp_path/'report.json'
    publish_report(path,dict(today=PART,week=PART),NOW)
    text='\n'.join(report_lines(json.loads(path.read_text()),NOW+dt.timedelta(seconds=offset)))
    assert ('STALE' in text)==stale
    assert ('Today' in text)!=stale
    assert 'Observed:' in text

def test_legacy_and_failure_never_label_old_data_today(tmp_path):
    assert 'Today' not in '\n'.join(report_lines(dict(today=PART,week=PART),NOW))
    path=tmp_path/'report.json'
    publish_report(path,dict(today=PART,week=PART),NOW)
    publish_report(path,None,NOW)
    text='\n'.join(report_lines(json.loads(path.read_text()),NOW))
    assert 'unavailable' in text and '10 tokens' not in text

@pytest.mark.parametrize('failure',['scan','breakdown','absent'])
def test_provider_invalidates_previous_report(tmp_path,failure):
    class Reader(FakeLocalUsageReader):
        def read_daily_tokens(self,now):
            if failure=='scan':raise OSError('offline')
            if failure=='absent':return None
            return super().read_daily_tokens(now)
        def read_breakdown(self,*args):raise OSError('prices unavailable')
    path=tmp_path/'report.json';publish_report(path,dict(today=PART,week=PART),NOW)
    with patch('codexmeter.provider.JsonRpcClient',FakeClient):
        result=asyncio.run(CodexUsageProvider(local_usage_reader=Reader(),report_path=path).fetch())
    assert json.loads(path.read_text())['state']=='unavailable'
    if failure=='breakdown':assert result.today_tokens==123 and result.token_details is None

def test_cli_usage_binds_provider_arguments_by_name(monkeypatch, capsys):
    from argparse import Namespace
    from codexmeter import cli
    from codexmeter.limits import UsageSnapshot
    received={}
    class Provider:
        def __init__(self,**kwargs):received.update(kwargs)
        async def fetch(self):return UsageSnapshot('codex',None,None,None,None,'stale',1)
    monkeypatch.setattr(cli,'CodexUsageProvider',Provider)
    assert asyncio.run(cli.run_once(Namespace(codex_bin='example',timeout=9,refresh_token=True)))==0
    assert received['timeout_sec']==9 and received['refresh_token'] is True
    assert 'monitor' not in received and received['report_path'].name=='usage-report.json'
