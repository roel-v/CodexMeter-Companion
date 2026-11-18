from codexmeter.compatibility import CompatibilityMonitor, safe_details
from tests.support.compatibility import Clock


def test_incident_recovery_restart(tmp_path):
    c = Clock()
    p = tmp_path / "health.json"
    m = CompatibilityMonitor(p, clock=c, wall=c, components=["stream"])
    m.observe("stream", "incompatible", "unsupported_version", {"observed_version": 14}, definitive=True)
    assert m.notifications() is None
    c.advance(m, 2)
    assert m.notifications()["confirmed"]
    n = CompatibilityMonitor(p, clock=c, wall=c, components=["stream"])
    n.observe("stream", "incompatible", "unsupported_version", {"observed_version": 14}, definitive=True)
    c.advance(n, 3)
    assert n.notifications() is None
    n.observe("stream")
    assert n.snapshot()["components"]["stream"]["unresolved_incompatibility"]
    n.observe("stream")
    assert not n.snapshot()["components"]["stream"]["unresolved_incompatibility"]
    n.observe("stream", "incompatible", "unsupported_version", {"observed_version": 14}, definitive=True)
    assert n.notifications() is None
    c.advance(n, 2)
    assert n.notifications()

def test_outage_sleep_closed_grace():
    c = Clock()
    m = CompatibilityMonitor(clock=c, wall=c, components=["quota"])
    m.observe("quota", "unavailable", "connection")
    c.advance(m, 329)
    assert m.notifications() is None
    c.advance(m, 1)
    assert m.notifications() is None
    m.power(True)
    c.advance(m, 1000)
    assert m.notifications() is None
    m.power(False)
    c.advance(m, 30)
    assert m.notifications() is None
    c.advance(m, 2)
    assert m.notifications()["confirmed"] is False
    m.observe("quota", "unavailable", "closed", eligible=False)
    c.advance(m, 600)
    assert m.notifications() is None

def test_structural_confirmation_generation_and_privacy():
    c = Clock()
    m = CompatibilityMonitor(clock=c, wall=c, components=["stream", "unread"])
    old = m.begin("stream")
    m.begin("stream")
    m.observe("stream", generation=old)
    assert m.records["stream"].validated is None
    for _ in range(2):
        m.observe("stream", "incompatible", "structure", {"field": "runtime_status", "secret": "PRIVATE"})
    assert m.records["stream"].incident
    m.observe("unread")
    assert m.records["unread"].state == "compatible"
    assert "PRIVATE" not in str(m.snapshot())
    assert safe_details({"field": "PRIVATE", "observed_version": True}) == {}

def test_missing_persistence_does_not_break_monitor(tmp_path):
    c = Clock()
    parent = tmp_path / "file"
    parent.write_text("file")
    m = CompatibilityMonitor(parent / "health.json", clock=c, wall=c, components=["tokens"])
    m.observe("tokens", "incompatible", "schema", definitive=True)
    m.notifications()
    c.advance(m, 2)
    assert m.notifications()
    assert not m.snapshot()["persistence_available"]
