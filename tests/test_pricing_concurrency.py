import datetime as dt
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from codexmeter import pricing
from tests.test_pricing import SOURCE, NOW


def test_check_publication_waits_for_acceptance(tmp_path, monkeypatch):
    first = pricing.PricingStore(tmp_path)
    second = pricing.PricingStore(tmp_path)
    initial = first.check(fetch=lambda: SOURCE, now=NOW)
    saved, fetched, release = threading.Event(), threading.Event(), threading.Event()
    write = pricing.atomic_write_json
    def pause(path, data, **kwargs):
        write(path, data, **kwargs)
        if path.name.startswith('revision-'):
            saved.set()
            assert release.wait(5)
    monkeypatch.setattr(pricing, 'atomic_write_json', pause)
    def fetch():
        fetched.set()
        return SOURCE + '\nNew candidate B.'
    with ThreadPoolExecutor(2) as pool:
        accepted = pool.submit(first.accept_pending, initial['source_sha256'], NOW)
        assert saved.wait(5)
        checked = pool.submit(second.check, force=True, fetch=fetch, now=NOW+dt.timedelta(seconds=1))
        release.set()
        accepted.result(5)
        assert checked.result(5)['state'] == 'changed'
    assert first.status()['source_sha256'] == pricing.fingerprint(SOURCE+'\nNew candidate B.')
    assert len(first.revisions()) == 2


def test_slow_check_cannot_replace_newer_check_or_block_acceptance(tmp_path):
    store = pricing.PricingStore(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def slow():
        entered.set()
        assert release.wait(5)
        return SOURCE+'\nOld response.'
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(store.check, force=True, fetch=slow, now=NOW)
        assert entered.wait(5)
        newer = pricing.PricingStore(tmp_path).check(force=True, fetch=lambda:SOURCE+'\nNew response.', now=NOW)
        store.accept_pending(newer['source_sha256'], NOW)
        release.set()
        assert pending.result(5)['state'] == 'current'
    assert store.revisions()[-1]['source_sha256'] == newer['source_sha256']


def test_accept_rejects_superseded_review(tmp_path):
    store = pricing.PricingStore(tmp_path)
    old = store.check(fetch=lambda:SOURCE, now=NOW)
    newer = store.check(force=True, fetch=lambda:SOURCE+'\nB', now=NOW)
    with pytest.raises(ValueError):
        store.accept_pending(old['source_sha256'], NOW)
    assert store.status()['source_sha256'] == newer['source_sha256']
    assert store.status()['state'] == 'changed'
    assert len(store.revisions()) == 1

