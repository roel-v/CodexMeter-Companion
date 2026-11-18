"""Reviewed hardware and application support, separate from wire syntax."""
APPLICATION_VERSION = 1
WIRE_VERSION = 1
SUPPORTED_MODELS = frozenset(('waveshare_c6_amoled_216', 'spotpear_ball_v2', 'waveshare_amoled_216'))
BUSY_REASONS = ('busy_usb', 'busy_ble', 'busy_maintenance')


def application_supported(version):
    return version is None or version == APPLICATION_VERSION


def is_busy(reason):
    return any(value in (reason or '') for value in BUSY_REASONS)


def declares_negotiation(raw):
    return bool(raw) and any(key in raw for key in ('usb', 'boot', 'ble_owner'))


def require_supported(identity, transport):
    from .companion_protocol import ProtocolError
    if identity.raw['usb'] != WIRE_VERSION or not application_supported(identity.raw['app']):
        raise ProtocolError(f'{transport} firmware upgrade required (wire/app v1)')
    if identity.metadata.model not in SUPPORTED_MODELS:
        raise ProtocolError(f'unsupported {transport} display model')
    if transport == 'bluetooth' and (type(identity.raw.get('ble_owner')) is not int
                                     or identity.raw['ble_owner'] != WIRE_VERSION):
        raise ProtocolError('Bluetooth ownership protocol required')
    return identity
