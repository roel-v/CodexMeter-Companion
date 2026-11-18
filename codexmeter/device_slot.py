"""Logical display configuration, queue and delivery state."""
import asyncio
from dataclasses import dataclass, field
from .device_registry import DeviceConfig
from .delivery import DeliveryState
from .payloads import Payload


@dataclass
class DeviceSlot:
    config: DeviceConfig
    queue: "asyncio.Queue[Payload]" = field(
        default_factory=lambda: asyncio.Queue(maxsize=32)
    )
    state: DeliveryState = field(default_factory=DeliveryState)

    def status(self, now: float | None = None) -> dict[str, object]:
        data = self.state.status(queue_depth=self.queue.qsize(), now=now)
        data.update(
            {
                "device_id": self.config.device_id,
                "short_id": self.config.short_id,
                "alias": self.config.alias,
                "label": self.config.label,
                "enabled": self.config.enabled,
                "connection_mode": self.config.connection_mode,
                "maintenance": bool(self.config.maintenance),
                "maintenance_recovery": "Resume after verifying the tool has closed" if self.config.maintenance else None,
            }
        )
        data.update(self.config.metadata.to_json())
        data["compatibility"] = self.config.metadata.compatibility
        return data
