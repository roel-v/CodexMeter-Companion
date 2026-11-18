import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_contributor_runner_forwards_fixtures_parameters_and_failure(tmp_path):
    fixture = tmp_path / 'test_probe.py'
    fixture.write_text('import pytest\n@pytest.mark.parametrize("value", [1,2])\ndef test_probe(tmp_path, monkeypatch, value):\n    assert value == 1\n', encoding='utf-8')
    result = subprocess.run([sys.executable, str(ROOT/'tests/run_tests.py'), '-q', '-p', 'no:cacheprovider',
                             str(fixture), '--basetemp', str(tmp_path/'scratch')],
                            cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 1
    assert '1 failed, 1 passed' in result.stdout, result.stdout + result.stderr
