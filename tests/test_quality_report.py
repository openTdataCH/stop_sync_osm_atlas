import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services import quality_report


def _example_report():
    return {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(), 'completeness': 'partial',
            'fingerprints': {'app': 'current', 'engine': 'before'}, 'revision': {'app': 'sha', 'engine': 'sha'},
            'modules': {'app.test': {
                'criticality': 'high', 'tests': {'status': 'pass'}, 'coverage': {'status': 'measured', 'branches': 99},
                'mutation': {'status': 'not_measured'}, 'duplication': {'status': 'pass'}, 'dead_code': {'status': 'pass'},
                'docs': {'status': 'pass', 'satisfied': 4, 'required': 4}, 'architecture': {'status': 'pass'}}}}


def test_missing_and_invalid_report_are_explicit(tmp_path):
    assert 'unavailable' in quality_report.replace_quality_placeholder('{{CODE_QUALITY_REPORT}}', tmp_path)
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality/latest.json').write_text('not JSON')
    assert 'unavailable' in quality_report.replace_quality_placeholder('{{CODE_QUALITY_REPORT}}', tmp_path)


@pytest.mark.parametrize('field,value', [('tools', []), ('checks', [None]), ('artifacts', [False]),
                                        ('modules', {'app.test': None}), ('modules', {'app.test': []})])
def test_malformed_artifact_shapes_render_unavailable(tmp_path, field, value):
    report = _example_report()
    report[field] = value
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality/latest.json').write_text(json.dumps(report))
    assert 'unavailable' in quality_report.replace_quality_placeholder('{{CODE_QUALITY_REPORT}}', tmp_path)


@pytest.mark.parametrize('lane', ['coverage', 'docs', 'tests', 'mutation'])
def test_malformed_measurement_does_not_crash_documentation(tmp_path, lane):
    report = deepcopy(_example_report())
    report['modules']['app.test'][lane] = None
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality/latest.json').write_text(json.dumps(report))
    assert 'unavailable' in quality_report.replace_quality_placeholder('{{CODE_QUALITY_REPORT}}', tmp_path)


def test_relative_engine_directory_is_resolved_from_repository_not_process_cwd(tmp_path, monkeypatch):
    root = tmp_path / 'app'
    engine = root / 'custom/engine'
    engine.mkdir(parents=True)
    (engine / 'pyproject.toml').write_text('')
    (root / 'quality').mkdir()
    (root / 'quality/latest.json').write_text(json.dumps(_example_report()))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('ENGINE_DIR', 'custom/engine')
    monkeypatch.setattr(quality_report, 'source_fingerprint', lambda path: 'current' if path == root else 'after')
    text = quality_report.replace_quality_placeholder('{{CODE_QUALITY_REPORT}}', root)
    assert '**stale**' in text
    assert '99%' not in text


def test_export_can_list_artifacts_without_creating_broken_local_links(tmp_path, monkeypatch):
    report = _example_report()
    report['artifacts'] = ['raw/checks.json']
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality/latest.json').write_text(json.dumps(report))
    monkeypatch.setattr(quality_report, 'source_fingerprint', lambda path: 'current')
    text = quality_report.replace_quality_placeholder('{{CODE_QUALITY_REPORT}}', tmp_path, artifact_prefix=None)
    assert '- `raw/checks.json`' in text
    assert '/docs/quality-artifacts/' not in text


def test_report_for_previous_source_cannot_display_pass(tmp_path, monkeypatch):
    report = {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(), 'completeness': 'partial',
              'fingerprints': {'app': 'old'}, 'revision': {'app': 'sha', 'engine': 'sha'}, 'modules': {'app.test': {
                  'criticality': 'high', 'tests': {'status': 'pass'}, 'coverage': {'status': 'measured', 'branches': 99},
                  'mutation': {'status': 'not_measured'}, 'duplication': {'status': 'pass'}, 'dead_code': {'status': 'pass'},
                  'docs': {'status': 'pass', 'satisfied': 4, 'required': 4}, 'architecture': {'status': 'pass'}, 'trend': {'status': 'not_measured'}}}}
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality/latest.json').write_text(json.dumps(report))
    monkeypatch.setattr(quality_report, 'source_fingerprint', lambda root: 'new')
    text = quality_report.replace_quality_placeholder('{{CODE_QUALITY_REPORT}}', tmp_path)
    assert '**stale**' in text
    assert '99%' not in text
    assert '| pass |' not in text


def test_ordinary_document_does_not_read_artifacts(monkeypatch):
    monkeypatch.setattr(quality_report, 'source_fingerprint', lambda root: (_ for _ in ()).throw(AssertionError('should not run')))
    assert quality_report.replace_quality_placeholder('Ordinary documentation', '.') == 'Ordinary documentation'


def test_pdf_export_expands_quality_evidence(tmp_path, monkeypatch):
    from documentation.pdf_generator import build_docs_pdf

    document = build_docs_pdf.DOCS_DIR / '4.3 Code Quality.md'
    monkeypatch.setattr(build_docs_pdf, 'REPO_ROOT', tmp_path)
    markdown = build_docs_pdf._prepare_document([document], include_cover=False)
    assert '{{CODE_QUALITY_REPORT}}' not in markdown
    assert 'Quality evidence unavailable' in markdown


@pytest.mark.parametrize('dependency', ['quality/latest.json', 'backend/services/quality_report.py'])
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


def test_quality_artifact_route_rejects_manual_and_hidden_files(client):
    assert client.get('/docs/quality-artifacts/modules.yml').status_code == 404
    assert client.get('/docs/quality-artifacts/raw/../modules.yml').status_code == 404
    assert client.get('/docs/quality-artifacts/raw/.secret.json').status_code == 404
