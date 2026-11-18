import asyncio
import datetime as dt
from unittest.mock import patch

from codexmeter.limits import WINDOW_7D_MINS
from codexmeter.provider import CodexUsageProvider
from tests.support.provider import RATE_LIMITS, FakeClient, FakeLocalUsageReader


def test_provider_uses_same_local_scope_for_today_and_week():
    with patch("codexmeter.provider.JsonRpcClient", FakeClient):
        snapshot = asyncio.run(
            CodexUsageProvider(local_usage_reader=FakeLocalUsageReader()).fetch()
        )
    assert snapshot.h5_remaining_percent is None
    assert snapshot.d7_remaining_percent == 97
    assert snapshot.today_tokens == 123
    assert snapshot.last_7d_tokens == 183


def test_provider_preserves_quotas_without_local_logs():
    class UnavailableReader:
        def read_daily_tokens(self, now):
            return None

    with patch("codexmeter.provider.JsonRpcClient", FakeClient):
        snapshot = asyncio.run(
            CodexUsageProvider(local_usage_reader=UnavailableReader()).fetch()
        )
    assert snapshot.d7_remaining_percent == 97
    assert snapshot.today_tokens is None
    assert snapshot.last_7d_tokens is None


def test_provider_preserves_quotas_when_local_scan_fails():
    class FailingReader:
        def read_daily_tokens(self, now):
            raise OSError("unavailable")

    with (
        patch("codexmeter.provider.JsonRpcClient", FakeClient),
        patch("codexmeter.provider.LOGGER.warning") as warning,
    ):
        snapshot = asyncio.run(
            CodexUsageProvider(local_usage_reader=FailingReader()).fetch()
        )
    assert snapshot.d7_remaining_percent == 97
    assert snapshot.today_tokens is None
    assert snapshot.last_7d_tokens is None
    warning.assert_called_once()


def test_provider_midnight_zero_does_not_reuse_yesterdays_tokens():
    class MidnightReader:
        def read_daily_tokens(self, now):
            return {now.date(): 0, now.date() - dt.timedelta(days=1): 500}

    with patch("codexmeter.provider.JsonRpcClient", FakeClient):
        snapshot = asyncio.run(
            CodexUsageProvider(local_usage_reader=MidnightReader()).fetch()
        )
    assert snapshot.today_tokens == 0
    assert snapshot.last_7d_tokens == 500


def test_provider_logs_daily_diagnostics_only_when_totals_change():
    provider = CodexUsageProvider(local_usage_reader=FakeLocalUsageReader())
    with (
        patch("codexmeter.provider.JsonRpcClient", FakeClient),
        patch("codexmeter.provider.LOGGER.info") as info,
    ):
        asyncio.run(provider.fetch())
        asyncio.run(provider.fetch())
    info.assert_called_once()
    assert "source=local_sessions" in info.call_args.args[0]
