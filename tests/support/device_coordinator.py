"""Shared device coordinator fixtures."""
from codexmeter.device_manager import DeviceManager
from tests.support.usb_transport import ID, H

def manager(configs, **extra):
    return DeviceManager(configs,host_id=H,connect_timeout_sec=.1,disconnect_timeout_sec=.1,
        write_timeout_sec=.1,ack_timeout_sec=.1,notify_timeout_sec=.1,healthcheck_interval_sec=1,**extra)
