import asyncio
import json
import sqlite3
from unittest.mock import patch
import pytest
from codexmeter.compatibility import CompatibilityMonitor, ContractError
from codexmeter.compatibility_readers import read_roots, read_unread, validate_quota, validate_usage_line, validate_state
from codexmeter.compatibility_dialog import diagnostic_report, summary
from codexmeter.provider import CodexUsageProvider
from tests.support.provider import FakeClient, FakeLocalUsageReader, RATE_LIMITS

def test_quotas_fail_tokens_continue_and_recover():
    class Broken(FakeClient):
        async def request(self, method, params=None):
            if method == "account/rateLimits/read":
                raise ConnectionError("PRIVATE")
            return await super().request(method, params)
    m = CompatibilityMonitor(components=["quota", "tokens"])
    provider = CodexUsageProvider(monitor=m, local_usage_reader=FakeLocalUsageReader())
    with patch("codexmeter.provider.JsonRpcClient", Broken):
        result = asyncio.run(provider.fetch())
    assert result.today_tokens == 123 and result.d7_remaining_percent is None
    assert m.records["tokens"].state == "compatible"
    with patch("codexmeter.provider.JsonRpcClient", FakeClient):
        assert asyncio.run(provider.fetch()).d7_remaining_percent is None
        assert asyncio.run(provider.fetch()).d7_remaining_percent == 97
    assert "PRIVATE" not in diagnostic_report(m.snapshot())

def test_unread_independent_of_roots(tmp_path):
    with sqlite3.connect(tmp_path / "state_5.sqlite") as db:
        db.executescript("CREATE TABLE threads(id,archived,source); CREATE TABLE thread_spawn_edges(child_thread_id);"
                         "INSERT INTO threads VALUES('a',0,'cli')")
    assert read_roots(tmp_path) == {"a"}
    with pytest.raises(FileNotFoundError):
        read_unread(tmp_path, {"a"})
    assert read_roots(tmp_path) == {"a"}

def test_missing_schema_is_definitive_but_missing_file_is_not(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_roots(tmp_path)
    with sqlite3.connect(tmp_path / "state_5.sqlite") as db:
        db.execute("CREATE TABLE harmless(extra)")
    with pytest.raises(ContractError) as exc:
        read_roots(tmp_path)
    assert exc.value.definitive and exc.value.reason == "schema"

@pytest.mark.parametrize("value", [True, float("nan"), -1, 101, "50"])
def test_quota_invalid_number(value):
    raw = json.loads(json.dumps(RATE_LIMITS))
    raw["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = value
    with pytest.raises(ContractError):
        validate_quota(raw)

def test_extensions_allowed_unknown_runtime_not_assumed_idle():
    validate_quota({**RATE_LIMITS, "extra": "ignored"})
    state = {"threadRuntimeStatus": {"type":"idle"}, "hasUnreadTurn":False, "source":"cli", "extra":123}
    validate_state(state)
    state["threadRuntimeStatus"] = {"type":"newStatus"}
    with pytest.raises(ContractError):
        validate_state(state)

def test_diagnostics_cannot_copy_arbitrary_upstream_strings():
    report = diagnostic_report({"versions":{"desktop":"C:/PRIVATE/user"},
        "components":{"stream":{"label":"PRIVATE","reason":"PRIVATE","state":"PRIVATE",
                                "details":{"field":"PRIVATE","secret":"PRIVATE"}}}})
    assert "PRIVATE" not in report

def test_dialog_open_is_local(monkeypatch):
    # Rendering helpers neither request releases nor inspect pricing websites.
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a,**k: pytest.fail("network"))
    m=CompatibilityMonitor(components=["stream"])
    m.observe("stream", "incompatible", "unsupported_version", {"observed_version":14}, definitive=True)
    assert "format" in summary(m.snapshot())
    assert '"observed_version": 14' in diagnostic_report(m.snapshot())

def test_usage_unrelated_and_empty_info_are_not_format_failures():
    validate_usage_line('{"type":"event_msg","payload":{"type":"other"}}')
    validate_usage_line('{"type":"event_msg","payload":{"type":"token_count","info":null}}')
    with pytest.raises(ContractError):
        validate_usage_line('{"type":"token_usage_record","payload":{"response_id":"a","usage":{"total_tokens":true}}}')

def test_activity_partial_unread_is_null():
    from codexmeter.chat_activity import ChatActivity
    c=ChatActivity()
    p=c._payload(True,(2,3,4)).data
    assert p["run"] == 2 and p["wait"] == 3 and p["done"] is None
    assert c._payload(False).data["run"] is None

def test_outage_unknown_five_minutes_deduplicates(tmp_path):
    from tests.support.compatibility import Clock
    c=Clock()
    m=CompatibilityMonitor(tmp_path/"health.json",clock=c,wall=c,components=["tokens"])
    m.observe("tokens","unavailable","connection")
    c.advance(m,330)
    assert m.notifications() is None
    c.advance(m,2)
    assert m.notifications()["confirmed"] is False
    c.advance(m,100)
    assert m.notifications() is None
    m.observe("tokens","incompatible","schema",definitive=True)
    assert m.notifications() is None
    c.advance(m,2)
    assert m.notifications()["confirmed"] is True



def test_owner_changes_invalidate_coverage():
    from codexmeter.chat_activity import coverage_complete
    assert coverage_complete({'a'}, {}, {'a':(60,None)}, 10)
    assert not coverage_complete({'a'}, {'a':{'owner':'old'}}, {'a':(60,'new')}, 10)
    assert coverage_complete({'a'}, {'a':{'owner':'new'}}, {'a':(60,'new')}, 10)
    assert not coverage_complete({'a'}, {'a':{'owner':'new'}}, {'a':(60,'new')}, 61)

def test_closed_host_suppresses_all_outages_but_preserves_incompatibility():
    from tests.support.compatibility import Clock
    c=Clock(); m=CompatibilityMonitor(clock=c,wall=c,components=['quota'])
    m.host_presence(False)
    m.observe('quota','unavailable','connection')
    c.advance(m,1000)
    assert m.records['quota'].elapsed == 0
    assert m.notifications() is None
    m.host_presence(True)
    c.advance(m,329)
    assert m.notifications() is None
    c.advance(m,1); m.notifications(); c.advance(m,2)
    assert m.notifications()

def test_unresolved_evidence_survives_closed_restart(tmp_path):
    from tests.support.compatibility import Clock
    c=Clock(); path=tmp_path/'health.json'
    m=CompatibilityMonitor(path,clock=c,wall=c,components=['stream'])
    m.observe('stream','incompatible','unsupported_version',{'observed_version':14},definitive=True)
    m.observe('stream','unavailable','closed',eligible=False)
    n=CompatibilityMonitor(path,clock=c,wall=c,components=['stream'])
    assert n.records['stream'].incident_details == {'observed_version':14}
    n.observe('stream'); n.observe('stream')
    assert not CompatibilityMonitor(path,clock=c,wall=c,components=['stream']).records['stream'].incident


def test_empty_inventory_recovery_requires_fresh_reads(monkeypatch):
    from codexmeter import chat_activity as activity
    from tests.support.compatibility import Clock
    async def run():
        clock = Clock(); stop = asyncio.Event()
        monitor = CompatibilityMonitor(clock=clock, wall=clock)
        monitor.observe("stream", "incompatible", "structure", definitive=True)
        class Transport:
            def write(self, raw): self.request = json.loads(raw[4:])["requestId"]
            def close(self): pass
        transport = Transport()
        async def connect(*args): return transport, None
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "create_pipe_connection", connect, raising=False)
        received = False
        async def receive(reader):
            nonlocal received
            if not received:
                received = True
                return {"requestId": transport.request, "result": {"clientId": "test"}}
            await asyncio.Future()
        monkeypatch.setattr(activity, "receive_metadata", receive)
        monkeypatch.setattr(activity.time, "monotonic", clock)
        reads = []
        def roots(home): reads.append(clock.now); return set()
        monkeypatch.setattr(activity, "read_roots", roots)
        monkeypatch.setattr(activity, "read_unread_snapshot", lambda *args: (set(), "test"))
        async def wait(tasks, timeout):
            clock.now += 1
            await asyncio.sleep(0)
            return set(), tasks
        monkeypatch.setattr(activity.asyncio, "wait", wait)
        publications = []
        async def sink(payload):
            publications.append((len(reads), monitor.records["stream"].successes,
                                 bool(monitor.records["stream"].incident)))
            if clock.now >= 7: stop.set()
        await activity.ChatActivity(monitor=monitor)._observe(sink, stop)
        assert publications[0] == (1, 1, True)
        assert publications[-1] == (2, 2, False)
    asyncio.run(run())


@pytest.mark.parametrize("failure", [False, True])
def test_obsolete_provider_completion_cannot_change_new_health_or_payload(failure):
    from codexmeter.compatibility import SupersededObservation
    async def run():
        entered = asyncio.Event(); release = asyncio.Event()
        class Delayed(FakeClient):
            first = True
            async def request(self, method, params=None):
                if method == "account/rateLimits/read" and Delayed.first:
                    Delayed.first = False
                    entered.set(); await release.wait()
                    if failure: raise ConnectionError("obsolete")
                return await super().request(method, params)
        monitor = CompatibilityMonitor()
        provider = CodexUsageProvider(monitor=monitor, local_usage_reader=FakeLocalUsageReader())
        with patch("codexmeter.provider.JsonRpcClient", Delayed):
            old = asyncio.create_task(provider.fetch())
            await entered.wait()
            latest = await provider.fetch()
            before = monitor.snapshot()
            release.set()
            with pytest.raises(SupersededObservation): await old
            assert latest.d7_remaining_percent == 97
            assert monitor.snapshot() == before
    asyncio.run(run())


def test_account_rebind_requires_new_successes():
    async def run():
        class AccountClient(FakeClient):
            account = "a"
            async def request(self, method, params=None):
                if method == "account/read": return {"account": {"id": self.account}}
                return await super().request(method, params)
        monitor = CompatibilityMonitor()
        provider = CodexUsageProvider(monitor=monitor, local_usage_reader=FakeLocalUsageReader())
        with patch("codexmeter.provider.JsonRpcClient", AccountClient):
            await provider.fetch()
            monitor.observe("quota", "incompatible", "schema", definitive=True)
            await provider.fetch()
            assert monitor.records["quota"].successes == 1
            AccountClient.account = "b"
            await provider.fetch()
            assert monitor.records["quota"].incident
            assert monitor.records["quota"].successes == 1
            await provider.fetch()
            assert not monitor.records["quota"].incident
    asyncio.run(run())
