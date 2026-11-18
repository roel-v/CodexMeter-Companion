"""Shared provider fixtures."""
import datetime as dt
from codexmeter.limits import WINDOW_7D_MINS

RATE_LIMITS = {
    "rateLimitsByLimitId": {
        "codex": {
            "limitId": "codex",
            "primary": {
                "usedPercent": 3,
                "resetsAt": 1784234099,
                "windowDurationMins": WINDOW_7D_MINS,
            },
        }
    }
}

class FakeClient:
    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def initialize(self):
        return {}

    async def request(self, method, _params=None):
        if method == "account/read":
            return {"account": {"type": "chatgpt"}}
        if method == "account/rateLimits/read":
            return RATE_LIMITS
        # Token activity must never mix in account daily buckets.
        raise AssertionError(f"unexpected method: {method}")

class FakeLocalUsageReader:
    def read_daily_tokens(self, now):
        return {
            now.date() - dt.timedelta(days=i): 123 if i == 0 else 10
            for i in range(7)
        }
