"""Shared ble fixtures."""
import asyncio
from codexmeter.ble import BleTransport

class FakeLifecycleClient:
    def __init__(
        self,
        *,
        connect_delay_sec: float = 0.0,
        disconnect_delay_sec: float = 0.0,
    ) -> None:
        self.connect_delay_sec = connect_delay_sec
        self.disconnect_delay_sec = disconnect_delay_sec
        self.disconnect_calls = 0
        self.is_connected = False

    async def connect(self) -> None:
        await asyncio.sleep(self.connect_delay_sec)
        self.is_connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        await asyncio.sleep(self.disconnect_delay_sec)
        self.is_connected = False

class FakeClientTransport(BleTransport):
    def __init__(self, client: FakeLifecycleClient, **kwargs) -> None:
        super().__init__(**kwargs)
        self.client = client

    def _create_client(self, _target):
        return self.client
