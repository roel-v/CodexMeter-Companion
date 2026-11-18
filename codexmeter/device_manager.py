"""Transport-neutral manager facade. multi_ble remains a compatibility import."""

from .multi_ble import DeviceManager, DeviceSlot

__all__ = ["DeviceManager", "DeviceSlot"]
