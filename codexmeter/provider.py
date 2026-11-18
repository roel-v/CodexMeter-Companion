"""Quota providers."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass, field, replace

from .app_server import JsonRpcClient
from .limits import (
    UsageSnapshot,
    usage_snapshot_from_rate_limits,
)
from .local_usage import LocalTokenUsageReader


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodexUsageProvider:
    """Fetch Codex subscription limits through the local Codex App Server."""

    codex_bin: str = "codex"
    monitor: object | None = field(default=None, compare=False, repr=False)
    timeout_sec: float = 15.0
    refresh_token: bool = False
    local_usage_reader: LocalTokenUsageReader | None = field(
        default_factory=LocalTokenUsageReader,
        compare=False,
        repr=False,
    )
    _usage_diagnostics: dict[str, object] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )

    async def fetch(self) -> UsageSnapshot:
        from .compatibility import report_error
        from .compatibility_readers import validate_quota
        import time
        monitor = self.monitor
        # Independent tasks: quota failure cannot prevent local usage collection.
        async def quotas():
            try:
                async with JsonRpcClient(self.codex_bin, self.timeout_sec) as client:
                    await client.initialize()
                    account = await client.request("account/read", {"refreshToken": self.refresh_token})
                    if isinstance(account, dict) and account.get("account", True) is None:
                        if monitor:
                            monitor.observe("quota", "unavailable", "authentication")
                        return None
                    rate_limits = await client.request("account/rateLimits/read")
                validate_quota(rate_limits)
                result = usage_snapshot_from_rate_limits(rate_limits)
                if monitor:
                    monitor.observe("quota")
                    if monitor.records["quota"].state != "compatible":
                        return None
                return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                report_error(monitor, "quota", exc)
                LOGGER.warning("Quota unavailable (%s)", type(exc).__name__)
                return None

        async def local():
            if self.local_usage_reader is None:
                return None
            try:
                now = dt.datetime.now().astimezone()
                daily = await asyncio.to_thread(self.local_usage_reader.read_daily_tokens, now)
                if daily is None:
                    if monitor:
                        monitor.observe("tokens", "unavailable", "no_history")
                    return None
                details = None
                self._log_local_usage_change(daily)
                if hasattr(self.local_usage_reader, "read_breakdown"):
                    try:
                        from .pricing import PricingStore, PRICING_DIR
                        from .persistence import atomic_write_json
                        details = await asyncio.to_thread(self.local_usage_reader.read_breakdown, daily, PricingStore())
                        await asyncio.to_thread(atomic_write_json, PRICING_DIR / "usage-report.json", details)
                    except Exception:
                        LOGGER.warning("Token pricing unavailable; totals retained")
                if monitor:
                    monitor.observe("tokens")
                    if monitor.records["tokens"].state != "compatible":
                        return None
                return daily[now.date()], sum(daily.values()), details
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                report_error(monitor, "tokens", exc)
                LOGGER.warning("Local token activity unavailable (%s)", type(exc).__name__)
                return None

        snapshot, usage = await asyncio.gather(quotas(), local())
        if snapshot is None:
            snapshot = UsageSnapshot("codex", None, None, None, None, "stale", int(time.time()))
        if usage is not None:
            snapshot = replace(snapshot, today_tokens=usage[0], last_7d_tokens=usage[1], token_details=usage[2])
        return snapshot

    def _log_local_usage_change(self, daily: dict[dt.date, int]) -> None:
        signature = tuple(sorted(daily.items()))
        if self._usage_diagnostics.get("daily") == signature:
            return
        self._usage_diagnostics["daily"] = signature
        LOGGER.info(
            "Codex local token activity source=local_sessions first_date=%s "
            "last_date=%s today=%s last_7d=%s daily=%s",
            signature[0][0],
            signature[-1][0],
            signature[-1][1],
            sum(daily.values()),
            ",".join(f"{day}:{tokens}" for day, tokens in signature),
        )
