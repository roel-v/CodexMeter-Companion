"""Shared mixed displays fixtures."""
from codexmeter.device_metadata import DeviceMetadata
from codexmeter.device_registry import DeviceConfig
from codexmeter.device_manager import DeviceManager

def config(index=1, model='spotpear_ball_v2'):
    return DeviceConfig(f'codexmeter-aabbcc{index:06x}', short_id='AABBCC', name='CodexMeter-AABBCC',
                        metadata=DeviceMetadata(model=model,protocol=1,capabilities=('brightness','rotation','screen')))

def manager(configs):
    return DeviceManager(configs,connect_timeout_sec=.1,disconnect_timeout_sec=.1,write_timeout_sec=.1,
                         ack_timeout_sec=.1,notify_timeout_sec=.1,healthcheck_interval_sec=1)
