import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services import quality_report


CODE_MAP = {'schema_version': 1, 'modules': [], 'contracts': [], 'files': [], 'links': [], 'interface': {}}


def _example_report():
    return {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(), 'completeness': 'partial',
            'fingerprints': {'app': 'current', 'engine': 'before'}, 'revision': {'app': 'sha', 'engine': 'sha'},
            'modules': {'app.test': {
                'criticality': 'high', 'tests': {'status': 'pass'}, 'coverage': {'status': 'measured', 'branches': 99},
                'mutation': {'status': 'not_measured'}, 'duplication': {'status': 'pass'}, 'dead_code': {'status': 'pass'},
                'docs': {'status': 'pass', 'satisfied': 4, 'required': 4}, 'architecture': {'status': 'pass'}}}}


def _publish(root, report, fingerprint=None, engine='sha'):
    """Write a published report as `make deploy-report` does, matching the code under ``root`` by default."""
    (root / 'engine.ref').write_text(engine + '\n')
    (root / 'backend').mkdir(exist_ok=True)
    (root / 'backend/app.py').write_text('app = 1\n')
    published = root / quality_report.PUBLISHED
    published.mkdir(parents=True, exist_ok=True)
    if fingerprint is None:
        fingerprint = quality_report.shipped_fingerprint(quality_report.shipped_files(root))
    (published / 'latest.json').write_text(json.dumps(report))
    (published / 'code-map.json').write_text(json.dumps(CODE_MAP))
    (published / 'publication.json').write_text(json.dumps({
        'app_revision': 'sha', 'run_url': 'https://github.com/example/actions/runs/1', 'shipped_fingerprint': fingerprint}))


def _render(root):
    return quality_report.replace_quality_placeholder('{{CODE_QUALITY_REPORT}}', root)


def test_missing_and_invalid_report_are_explicit(tmp_path):
    assert 'unavailable' in _render(tmp_path)
    _publish(tmp_path, _example_report())
    (tmp_path / quality_report.PUBLISHED / 'latest.json').write_text('not JSON')
    assert 'unavailable' in _render(tmp_path)
    _publish(tmp_path, _example_report())
    (tmp_path / quality_report.PUBLISHED / 'publication.json').unlink()
    assert 'unavailable' in _render(tmp_path)


@pytest.mark.parametrize('field,value', [('tools', []), ('checks', [None]), ('artifacts', [False]),
                                        ('modules', {'app.test': None}), ('modules', {'app.test': []})])
def test_malformed_artifact_shapes_render_unavailable(tmp_path, field, value):
    report = _example_report()
    report[field] = value
    _publish(tmp_path, report)
    assert 'unavailable' in _render(tmp_path)


@pytest.mark.parametrize('lane', ['coverage', 'docs', 'tests', 'mutation'])
def test_malformed_measurement_does_not_crash_documentation(tmp_path, lane):
    report = deepcopy(_example_report())
    report['modules']['app.test'][lane] = None
    _publish(tmp_path, report)
    assert 'unavailable' in _render(tmp_path)


def test_report_for_the_running_code_shows_results_and_links_the_ci_run(tmp_path):
    report = _example_report()
    report['checks'] = [{'name': 'app-python-tests', 'status': 'pass'}]
    _publish(tmp_path, report)
    text = _render(tmp_path)
    assert '[!WARNING]' not in text
    assert '99%' in text
    assert '**app-python-tests**: pass' in text
    assert '[CI run](https://github.com/example/actions/runs/1)' in text


def test_report_for_previous_code_warns_and_cannot_display_pass(tmp_path):
    report = _example_report()
    report['checks'] = [{'name': 'app-python-tests', 'status': 'pass'}]
    _publish(tmp_path, report)
    (tmp_path / 'backend/app.py').write_text('app = 2\n')
    text = _render(tmp_path)
    assert text.startswith('> [!WARNING]')
    assert 'measured on app commit `sha`' in text and 'the application code' in text
    assert '**stale**' in text
    assert '99%' not in text
    assert '| pass |' not in text
    assert '**app-python-tests**: stale' in text


def test_report_for_another_engine_pin_warns(tmp_path):
    _publish(tmp_path, _example_report(), engine='newer')
    text = _render(tmp_path)
    assert 'the pinned engine' in text and 'the application code' not in text


def test_shipped_fingerprint_ignores_the_report_tests_generated_and_local_only_files(tmp_path):
    _publish(tmp_path, _example_report())
    for name in ('quality/published/report.md', 'tests/test_new.py', 'backend/__pycache__/app.cpython-313.pyc',
                 'static/.DS_Store', 'documentation/generated/docs.pdf', 'documentation/Documentation style guide.md'):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text('generated')
    assert '[!WARNING]' not in _render(tmp_path)


def test_export_can_list_artifacts_without_creating_broken_local_links():
    report = _example_report()
    report['artifacts'] = ['raw/checks.json']
    text = quality_report.render_report(report, None)
    assert '- `raw/checks.json`' in text
    assert '](' not in text.split('Raw evidence:')[1]


def test_ordinary_document_does_not_read_artifacts(monkeypatch):
    monkeypatch.setattr(quality_report, 'shipped_files', lambda root: (_ for _ in ()).throw(AssertionError('should not run')))
    assert quality_report.replace_quality_placeholder('Ordinary documentation', '.') == 'Ordinary documentation'


def test_pdf_export_expands_quality_evidence(tmp_path, monkeypatch):
    from documentation.pdf_generator import build_docs_pdf

    document = build_docs_pdf.DOCS_DIR / '4.3 Code Quality.md'
    # Read the evidence from an empty folder; the rest of the bundle uses the real checkout.
    monkeypatch.setattr(build_docs_pdf, 'replace_quality_placeholder',
                        lambda text, root: quality_report.replace_quality_placeholder(text, tmp_path))
    markdown = build_docs_pdf._prepare_document([document], include_cover=False)
    assert '{{CODE_QUALITY_REPORT}}' not in markdown
    assert 'Quality evidence unavailable' in markdown


@pytest.mark.parametrize('dependency', ['quality/published/publication.json', 'backend/services/quality_report.py'])
def test_pdf_cache_refreshes_when_quality_evidence_or_renderer_changes(tmp_path, monkeypatch, dependency):
    from backend.blueprints import docs

    for name in ('documentation/generated/stop_sync_osm_atlas_documentation.pdf',
                 'documentation/pdf_generator/build_docs_pdf.py', dependency):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
        os.utime(path, (100, 100))
    monkeypatch.setattr(docs, '_repo_root', lambda: str(tmp_path))
    monkeypatch.setattr(docs, '_get_docs_dir', lambda: str(tmp_path / 'documentation'))
    monkeypatch.setattr(docs, '_get_docs_dirs', lambda: {'app': str(tmp_path / 'documentation')})
    generated = []

    def generate(command, **kwargs):
        generated.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(docs.subprocess, 'run', generate)
    assert docs.ensure_docs_pdf_generated()
    assert generated == []
    os.utime(tmp_path / dependency, (200, 200))
    assert docs.ensure_docs_pdf_generated()
    assert len(generated) == 1
