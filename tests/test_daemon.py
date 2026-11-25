import asyncio

from codexmeter.daemon import (
    DaemonAlreadyRunning,
    DaemonLock,
    build_stale_usage_payload,
    build_file_handler,
    load_cached_usage_snapshot,
    parse_args,
    put_latest,
    save_cached_usage_snapshot,
)
from codexmeter.limits import UsageSnapshot
from codexmeter.payloads import Payload, build_screen_control_payload


def test_put_latest_keeps_only_latest_control_payload():
    async def scenario():
        queue: asyncio.Queue[Payload] = asyncio.Queue(maxsize=8)
        await put_latest(queue, Payload("usage", {"k": "usage", "v": 1}))
        await put_latest(queue, build_screen_control_payload(False, "mac_locked", now=1))
        await put_latest(queue, Payload("activity", {"k": "activity", "v": 1}))
        await put_latest(queue, build_screen_control_payload(True, "mac_unlocked", now=2))

        items = []
        while not queue.empty():
            items.append(queue.get_nowait())

        assert [item.kind for item in items] == ["usage", "activity", "control"]
        assert items[-1].data["on"] is True
        assert items[-1].data["why"] == "mac_unlocked"

    asyncio.run(scenario())


def test_put_latest_keeps_only_latest_usage_and_activity_payloads():
    async def scenario():
        queue: asyncio.Queue[Payload] = asyncio.Queue(maxsize=8)
        await put_latest(queue, Payload("usage", {"k": "usage", "h5": 1}))
        await put_latest(queue, Payload("alert", {"k": "alert", "id": "a"}))
        await put_latest(queue, Payload("usage", {"k": "usage", "h5": 2}))
        await put_latest(queue, Payload("activity", {"k": "activity", "run": 1}))
        await put_latest(queue, Payload("activity", {"k": "activity", "run": 2}))

        items = []
        while not queue.empty():
            items.append(queue.get_nowait())

        assert [item.kind for item in items] == ["alert", "usage", "activity"]
        assert items[1].data["h5"] == 2
        assert items[2].data["run"] == 2

    asyncio.run(scenario())


def test_build_stale_usage_payload_preserves_values_and_updates_status():
    payload = Payload(
        "usage",
        {
            "k": "usage",
            "h5": 88,
            "d7": 64,
            "st": "ok",
            "t": 1,
        },
    )

    stale = build_stale_usage_payload(payload, now=42)

    assert stale.kind == "usage"
    assert stale.data["h5"] == 88
    assert stale.data["d7"] == 64
    assert stale.data["st"] == "stale"
    assert stale.data["t"] == 42
    assert payload.data["st"] == "ok"


def test_usage_cache_round_trips_snapshot(tmp_path):
    path = tmp_path / "usage.json"
    snapshot = UsageSnapshot(
        source="codex",
        h5_remaining_percent=89,
        h5_resets_at=1783499130,
        d7_remaining_percent=36,
        d7_resets_at=1783526386,
        status="ok",
        generated_at=1783483642,
        today_tokens=18_600_000,
        last_7d_tokens=236_000_000,
    )

    save_cached_usage_snapshot(snapshot, path)
    loaded = load_cached_usage_snapshot(path)

    assert loaded == snapshot


def test_usage_cache_ignores_suspicious_empty_d7_snapshot(tmp_path):
    path = tmp_path / "usage.json"
    snapshot = UsageSnapshot(
        source="codex",
        h5_remaining_percent=97,
        h5_resets_at=1783499154,
        d7_remaining_percent=100,
        d7_resets_at=1784085954,
        status="ok",
        generated_at=1783483796,
    )

    save_cached_usage_snapshot(snapshot, path)

    assert load_cached_usage_snapshot(path) is None


def test_quota_outage_resume_and_restart(monkeypatch, tmp_path):
    from dataclasses import replace
    from unittest.mock import AsyncMock
    from codexmeter import daemon

    path = tmp_path / "quota.json"
    monkeypatch.setattr(daemon, "load_cached_usage_snapshot", lambda: load_cached_usage_snapshot(path))
    monkeypatch.setattr(daemon, "save_cached_usage_snapshot", lambda s: save_cached_usage_snapshot(s, path))
    live = UsageSnapshot("codex", None, None, 74, 20000, "ok", 1000, 101, 500)
    outage = UsageSnapshot("codex", None, None, None, None, "stale", 1100, 106, 505)
    recovered = replace(live, d7_remaining_percent=73, generated_at=1200)

    async def poll(readings, count, wake_after_first=False):
        sent = []
        stop, resume = asyncio.Event(), asyncio.Event()
        provider = AsyncMock()
        provider.fetch.side_effect = readings
        async def sink(payload):
            sent.append(payload.data)
            if wake_after_first and len(sent) == 1:
                resume.set()
            if len(sent) == count:
                stop.set()
        await asyncio.wait_for(daemon.quota_loop(provider, sink, stop, 0, resume), 2)
        return sent

    sent = asyncio.run(poll([live, outage, TimeoutError()], 4, wake_after_first=True))
    assert [p["st"] for p in sent] == ["ok", "stale", "stale", "stale"]
    assert all((p["d7"], p["d7r"], p["h5"]) == (74, 20000, None) for p in sent)
    assert sent[2]["td"] == 106 and sent[2]["t7"] == 505
    assert load_cached_usage_snapshot(path) == live

    sent = asyncio.run(poll([outage, recovered], 3))
    assert [(p["st"], p["d7"]) for p in sent] == [("stale", 74), ("stale", 74), ("ok", 73)]
    assert load_cached_usage_snapshot(path) == recovered

    save_cached_usage_snapshot(outage, path)  # Cache from an older version.
    sent = asyncio.run(poll([outage, recovered], 2))
    assert [(p["st"], p["d7"]) for p in sent] == [("stale", None), ("ok", 73)]


def test_daemon_lock_rejects_second_instance(tmp_path):
    path = tmp_path / "daemon.lock"
    with DaemonLock(path):
        try:
            with DaemonLock(path):
                pass
        except DaemonAlreadyRunning:
            return
    raise AssertionError("expected second daemon lock to fail")


def test_log_handler_keeps_current_and_backup_within_total_limit(tmp_path):
    handler = build_file_handler(tmp_path / "daemon.log", total_bytes=100_000)
    try:
        assert handler.maxBytes == 50_000
        assert handler.backupCount == 1
    finally:
        handler.close()


def test_activity_ttl_defaults_and_can_be_disabled():
    defaults = parse_args([])
    disabled = parse_args(["--activity-ttl", "0"])

    assert defaults.activity_ttl == 3600
    assert defaults.activity_sweep_interval == 30
    assert disabled.activity_ttl == 0
