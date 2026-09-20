import os
from types import SimpleNamespace

import backend.blueprints.docs as docs_blueprint
import backend.blueprints.reports as reports_blueprint


def _patch_async_helpers(monkeypatch, module):
    monkeypatch.setattr(module, 'start_cleanup_thread', lambda: None)
    monkeypatch.setattr(module, 'cleanup_stale_tasks', lambda: 0)


def test_generate_report_async_accepts_form_payload(client, monkeypatch):
    _patch_async_helpers(monkeypatch, reports_blueprint)
    monkeypatch.setattr(reports_blueprint, 'background_report_generation', lambda *args, **kwargs: None)

    response = client.post('/api/generate_report_async', data={
        'report_type': 'summary',
        'format': 'pdf',
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload
    assert 'task_id' in payload


def test_generate_report_async_accepts_raw_json_body(client, monkeypatch):
    _patch_async_helpers(monkeypatch, reports_blueprint)
    monkeypatch.setattr(reports_blueprint, 'background_report_generation', lambda *args, **kwargs: None)

    response = client.post(
        '/api/generate_report_async',
        data='{"report_type":"summary","format":"pdf"}',
        content_type='text/plain',
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload
    assert 'task_id' in payload


def test_generate_report_async_ignores_non_dict_raw_json(client, monkeypatch):
    _patch_async_helpers(monkeypatch, reports_blueprint)

    response = client.post(
        '/api/generate_report_async',
        data='["not", "an", "object"]',
        content_type='text/plain',
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload
    assert payload.get('error') == 'No data provided'


def test_generate_report_async_empty_payload_returns_400(client, monkeypatch):
    _patch_async_helpers(monkeypatch, reports_blueprint)

    response = client.post('/api/generate_report_async')

    assert response.status_code == 400
    payload = response.get_json()
    assert payload
    assert payload.get('error') == 'No data provided'


def test_generate_report_async_invalid_type_returns_400(client, monkeypatch):
    _patch_async_helpers(monkeypatch, reports_blueprint)

    response = client.post('/api/generate_report_async', json={
        'report_type': 'invalid_type',
        'format': 'pdf',
    })

    assert response.status_code == 400
    payload = response.get_json()
    assert payload
    assert payload.get('error') == 'Invalid report_type provided'


def test_generate_report_async_summary_rejects_non_pdf(client, monkeypatch):
    _patch_async_helpers(monkeypatch, reports_blueprint)

    response = client.post('/api/generate_report_async', json={
        'report_type': 'summary',
        'format': 'csv',
    })

    assert response.status_code == 400
    payload = response.get_json()
    assert payload
    assert payload.get('error') == 'Summary report only supports PDF format'


def test_generate_report_sync_summary_rejects_non_pdf(client):
    response = client.get('/api/generate_report?report_type=summary&format=csv')

    assert response.status_code == 400
    payload = response.get_json()
    assert payload
    assert payload.get('message') == 'Summary report only supports PDF format'


def test_generate_report_sync_summary_pdf_uses_summary_handler(client, monkeypatch):
    called = {}

    def _fake_send_summary_pdf_response(download_name='summary_operator_asc.pdf'):
        called['download_name'] = download_name
        return 'ok', 200

    monkeypatch.setattr(reports_blueprint, '_send_summary_pdf_response', _fake_send_summary_pdf_response)
    monkeypatch.setattr(
        reports_blueprint,
        'generate_report_data',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('generate_report_data should not run for summary PDF')),
    )

    response = client.get('/api/generate_report?report_type=summary&format=pdf&sort=operator_asc')

    assert response.status_code == 200
    assert response.get_data(as_text=True) == 'ok'
    assert called.get('download_name') == 'summary_operator_asc.pdf'


def test_generate_docs_pdf_async_accepts_form_payload(client, monkeypatch):
    _patch_async_helpers(monkeypatch, docs_blueprint)
    monkeypatch.setattr(docs_blueprint, '_background_docs_pdf', lambda *args, **kwargs: None)

    response = client.post('/api/docs/generate_pdf_async', data={
        'included_sections': 'engine:1,app:2',
        'include_cover': 'false',
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload
    assert 'task_id' in payload


def test_generate_docs_pdf_async_selected_only_requires_sections(client, monkeypatch):
    _patch_async_helpers(monkeypatch, docs_blueprint)

    response = client.post('/api/docs/generate_pdf_async', data={
        'selected_only': 'true',
        'included_sections': '',
        'include_cover': 'false',
    })

    assert response.status_code == 400
    payload = response.get_json()
    assert payload
    assert payload.get('error') == 'No sections selected for partial documentation export.'


def test_generate_docs_pdf_async_ignores_non_dict_raw_json(client, monkeypatch):
    _patch_async_helpers(monkeypatch, docs_blueprint)
    monkeypatch.setattr(docs_blueprint, '_background_docs_pdf', lambda *args, **kwargs: None)

    response = client.post(
        '/api/docs/generate_pdf_async',
        data='["not", "an", "object"]',
        content_type='text/plain',
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload
    assert 'task_id' in payload


def test_docs_payload_parsing_helpers():
    assert docs_blueprint._to_sections_list('1.,2.') == ['1', '2']
    assert docs_blueprint._to_sections_list('["3.", "4."]') == ['3', '4']
    assert docs_blueprint._to_sections_list('1.2,7.1') == ['1', '7']
    assert docs_blueprint._to_sections_list('engine:1,app:2') == ['engine:1', 'app:2']
    assert docs_blueprint._to_sections_list('app:extra-changelog') == ['app:extra-changelog']
    assert docs_blueprint._to_sections_list('') is None

    assert docs_blueprint._to_bool('false') is False
    assert docs_blueprint._to_bool('true') is True
    assert docs_blueprint._to_bool(None, default=True) is True


def test_existing_docs_pdf_path_uses_canonical_output(monkeypatch):
    canonical_path = '/tmp/stop_sync_osm_atlas_documentation.pdf'

    monkeypatch.setattr(docs_blueprint, '_docs_pdf_path', lambda: canonical_path)
    monkeypatch.setattr(docs_blueprint.os.path, 'exists', lambda path: path == canonical_path)

    assert docs_blueprint._existing_docs_pdf_path() == canonical_path


def test_docs_pdf_cache_invalidates_when_generator_changes(tmp_path, monkeypatch):
    docs_dir = tmp_path / 'documentation'
    engine_docs_dir = tmp_path / 'engine' / 'documentation'
    generator_dir = docs_dir / 'pdf_generator'
    generated_dir = docs_dir / 'generated'
    for directory in (engine_docs_dir, generator_dir, generated_dir):
        directory.mkdir(parents=True, exist_ok=True)

    pdf_path = generated_dir / 'stop_sync_osm_atlas_documentation.pdf'
    generator_path = generator_dir / 'build_docs_pdf.py'
    css_path = generator_dir / 'docs_print.css'
    mermaid_config_path = generator_dir / 'mermaid_render_config.json'
    markdown_path = docs_dir / '0. Intro.md'
    pdf_path.write_bytes(b'%PDF-placeholder')
    generator_path.write_text('# generator', encoding='utf-8')
    css_path.write_text('body {}', encoding='utf-8')
    mermaid_config_path.write_text('{"cacheVersion": "test"}', encoding='utf-8')
    markdown_path.write_text('# Intro', encoding='utf-8')

    os.utime(pdf_path, (100, 100))
    os.utime(css_path, (90, 90))
    os.utime(mermaid_config_path, (90, 90))
    os.utime(markdown_path, (90, 90))
    os.utime(generator_path, (110, 110))

    calls = []
    monkeypatch.setattr(docs_blueprint, '_repo_root', lambda: str(tmp_path))
    monkeypatch.setattr(docs_blueprint, '_get_docs_dir', lambda: str(docs_dir))
    monkeypatch.setattr(
        docs_blueprint,
        '_get_docs_dirs',
        lambda: {'app': str(docs_dir), 'engine': str(engine_docs_dir)},
    )
    monkeypatch.setattr(
        docs_blueprint.subprocess,
        'run',
        lambda *args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(
            returncode=0,
            stderr='',
        ),
    )

    assert docs_blueprint.ensure_docs_pdf_generated() is True
    assert len(calls) == 1

    calls.clear()
    os.utime(pdf_path, (200, 200))
    os.utime(generator_path, (190, 190))
    os.utime(mermaid_config_path, (210, 210))

    assert docs_blueprint.ensure_docs_pdf_generated() is True
    assert len(calls) == 1
