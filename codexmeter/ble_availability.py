"""Optional Bluetooth adapter availability, with no recovery side effects."""
import asyncio

async def bluetooth_availability():
    """Optional adapter capability; no pairing or recovery side effects."""
    import sys
    if sys.platform != 'win32':
        try:
            import bleak
            return True, None
        except ImportError:
            return False, 'Bluetooth backend unavailable'
    try:
        from winrt.windows.devices.radios import Radio, RadioKind, RadioState
        radios = await asyncio.wait_for(Radio.get_radios_async(), 2)
        available = any(r.kind == RadioKind.BLUETOOTH and r.state == RadioState.ON for r in radios)
        return available, None if available else 'Bluetooth adapter absent or switched off'
    except Exception:
        return False, 'Bluetooth adapter inaccessible or unsupported'


