"""The gate runner must retain failures and never endorse previous-run evidence."""
import json
import sys
from types import SimpleNamespace

import pytest

from scripts import run_quality


def test_full_run_discards_old_evidence_and_preserves_failed_gates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / 'quality' / 'raw'
    raw.mkdir(parents=True)
    stale = raw / 'app-python-coverage.json'
    stale.write_text('{"old": true}')
    monkeypatch.setattr(run_quality, 'ROOT', tmp_path)
    monkeypatch.setattr(run_quality, 'RAW', raw)
    monkeypatch.setattr(run_quality, 'preflight', lambda *args: None)
    monkeypatch.setattr(run_quality, 'revision', lambda root: 'commit')
    monkeypatch.setattr(sys, 'argv', ['run_quality.py', 'full', '--engine-root', str(tmp_path / 'engine')])
    fingerprint = ['before']
    monkeypatch.setitem(sys.modules, 'quality', SimpleNamespace(repository_fingerprint=lambda root: fingerprint[0]))
    monkeypatch.setattr(run_quality.subprocess, 'check_output', lambda *args, **kwargs: 'v22.13.0')
    report_observations = []

    def execute(command, **kwargs):
        fingerprint[0] = 'after'
        if 'report' in command:
            report_observations.append((stale.exists(), json.loads((raw / 'checks.json').read_text())))
        return SimpleNamespace(returncode=1 if 'lint:js' in command else 0)

    monkeypatch.setattr(run_quality.subprocess, 'run', execute)
    assert run_quality.main() == 1
    assert not stale.exists()
    old_file_exists, report_manifest = report_observations[0]
    assert old_file_exists is False
    assert report_manifest['fingerprints'] == {'app': 'before', 'engine': 'before'}
    assert any(check['name'] == 'javascript-lint' and check['status'] == 'fail' for check in report_manifest['checks'])
    assert any(check['name'] == 'producer-consumer-contract' for check in report_manifest['checks'])


@pytest.fixture
def supported_checkout(tmp_path, monkeypatch):
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality' / 'modules.yml').write_text('{}')
    (tmp_path / 'node_modules' / '.bin').mkdir(parents=True)
    (tmp_path / 'node_modules' / '.bin' / 'eslint').touch()
    monkeypatch.setattr(run_quality, 'ROOT', tmp_path)
    monkeypatch.setattr(run_quality.sys, 'version_info', (3, 13, 0))
    monkeypatch.setattr(run_quality.subprocess, 'check_output', lambda *args, **kwargs: 'v22.13.0')
    return tmp_path


def test_full_run_requires_postgis_and_app_engine_isolation(supported_checkout, monkeypatch):
    monkeypatch.delenv('TEST_POSTGRES_URI', raising=False)
    with pytest.raises(RuntimeError, match='disposable TEST_POSTGRES_URI'):
        run_quality.preflight(True, supported_checkout, 'engine-python')
    monkeypatch.setenv('TEST_POSTGRES_URI', 'postgresql://test/transport_test')
    monkeypatch.setattr(run_quality.importlib.util, 'find_spec', lambda name: object())
    with pytest.raises(RuntimeError, match='must not have transport_matcher installed'):
        run_quality.preflight(True, supported_checkout, 'engine-python')


def test_quality_rejects_image_with_outdated_requirement(supported_checkout, monkeypatch):
    for name in ('base', 'web', 'scheduler', 'test', 'quality'):
        (supported_checkout / f'requirements-{name}.txt').write_text('')
    (supported_checkout / 'requirements-web.txt').write_text('weasyprint>=70.0,<71.0\n')
    monkeypatch.setattr(run_quality, 'version', lambda package: '68.1')
    with pytest.raises(RuntimeError, match='weasyprint==68.1 does not satisfy'):
        run_quality.preflight(False, supported_checkout, 'engine-python')
