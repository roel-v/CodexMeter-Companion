"""Acceptance must fail on missing records and wrong model/pixels, even with valid PNGs."""
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from validation_capture import expected_model, verify_model, compare_crops, record_capture


def cases():
    return [{'v':1,'k':'usage','d7':73,'td':42,'t7':99,'t':123},
            {'v':1,'k':'activity','run':2,'wait':3,'done':4,'chats':True,'t':123}]


def test_missing_activity_cannot_pass_acceptance():
    with pytest.raises(ValueError, match='independent'):
        expected_model(cases()[:1])


@pytest.mark.parametrize('changed', [{'run':0}, {'activity_t':122}, {'page':2}, {'waiting':True}])
def test_wrong_rendered_value_or_page_fails(changed):
    expected=dict(expected_model(cases()),page=0)
    with pytest.raises(ValueError, match='mismatch'):
        verify_model(dict(expected,**changed),expected)


def test_unknown_and_partial_metrics_remain_independent():
    data=cases();data[1].update(run=2,wait=None,done=None,chats=False)
    model=expected_model(data)
    assert (model['run'],model['wait'],model['done'])==(2,-1,-1)
    assert model['b0'] is None and model['b7'] is None


def test_valid_png_with_wrong_metric_pixels_fails(tmp_path):
    from PIL import Image
    baseline=tmp_path/'reviewed.png';candidate=tmp_path/'candidate.png'
    image=Image.new('RGB',(240,240),'black');image.save(baseline)
    image.putpixel((100,100),(255,255,255));image.save(candidate)
    with pytest.raises(ValueError,match='Pixel content'):
        compare_crops(candidate,baseline,[(90,90,120,120)])
    compare_crops(baseline,baseline,[(90,90,120,120)])
    record_capture(candidate,{'run':2},{'run':2})
    assert json.loads(candidate.with_suffix('.json').read_text())['visual_review']=='pending'


def test_validation_daemon_requires_disposable_profile(tmp_path,monkeypatch):
    import asyncio
    from codexmeter import daemon
    monkeypatch.setattr(daemon,'APP_DIR',tmp_path)
    args=daemon.parse_args(['--validation-mode'])
    with pytest.raises(ValueError,match='disposable'):
        asyncio.run(daemon.run_daemon(args))
    assert not daemon.parse_args([]).validation_mode
