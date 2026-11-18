import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from validate_architecture_cleanup import conflict_index


def test_rapid_commands_may_legitimately_both_apply():
    assert conflict_index([{'status':'applied'},{'status':'applied'}]) is None
    assert conflict_index([{'status':'applied'},{'status':'rejected','reason':'conflict'}])==1

@pytest.mark.parametrize('outcome',[{'status':'unknown'}, {'status':'sending'},
                                    {'status':'rejected','reason':'unsupported'}])
def test_rapid_fixture_does_not_hide_other_failures(outcome):
    with pytest.raises(AssertionError):conflict_index([{'status':'applied'},outcome])
