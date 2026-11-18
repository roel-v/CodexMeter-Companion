import asyncio
import json
import pytest
from codexmeter.companion_protocol import NegotiatedIdentity, ProtocolError
from codexmeter.companion_session import read_identity, IdentityIncompatible
from codexmeter.device_policy import SUPPORTED_MODELS, require_supported, is_busy
from tests.test_usb_protocol import identity_data


@pytest.mark.parametrize('transport',['usb','bluetooth'])
@pytest.mark.parametrize('model',sorted(SUPPORTED_MODELS))
@pytest.mark.parametrize('caps',[[],['screen'],['brightness','rotation','screen']])
def test_reviewed_devices_do_not_require_unrelated_controls(transport,model,caps):
    raw={**identity_data(),'model':model,'capabilities':caps,'ble_owner':1}
    identity=NegotiatedIdentity.parse(b'IDENTITY '+json.dumps(raw).encode())
    assert require_supported(identity,transport) is identity
    assert identity.metadata.supports('rotation') == ('rotation' in caps)


@pytest.mark.parametrize('transport',['usb','bluetooth'])
@pytest.mark.parametrize('change',[{'model':'future_model'},{'usb':2},{'app':2}])
def test_structural_identity_is_not_support_or_permission_to_claim(transport,change):
    raw={**identity_data(),'ble_owner':1,**change}
    line=b'IDENTITY '+json.dumps(raw).encode()
    assert NegotiatedIdentity.parse(line).raw == raw
    class Channel:
        writes=[]
        async def write(self,data):self.writes.append(data)
        async def line(self,timeout):return line
    channel=Channel()
    with pytest.raises(IdentityIncompatible):
        asyncio.run(read_identity(channel,transport=transport))
    assert channel.writes==[b'identity\n']


@pytest.mark.parametrize('caps',[None,{},[{}]])
def test_malformed_capability_declaration_is_not_legacy(caps):
    with pytest.raises(ProtocolError):
        NegotiatedIdentity.parse(b'IDENTITY '+json.dumps({**identity_data(),'capabilities':caps}).encode())


def test_busy_policy():
    assert all(is_busy('TransportError: '+reason) for reason in ('busy_usb','busy_ble','busy_maintenance'))
    assert not is_busy(None) and not is_busy('timeout')

