import os
import threading
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


def test_generate_docs_pdf_async_exports_one_page_under_its_address(client, monkeypatch):
    _patch_async_helpers(monkeypatch, docs_blueprint)
    started = []
    finished = threading.Event()

    def background(*args):
        started.append(args)
        finished.set()

    monkeypatch.setattr(docs_blueprint, '_background_docs_pdf', background)

    response = client.post('/api/docs/generate_pdf_async', json={
        'included_pages': ['exact_matching'],
        'include_cover': False,
        'selected_only': True,
    })

    assert response.status_code == 200
    assert finished.wait(5)
    _, _, included_sections, include_cover, included_pages, download_name = started[0]
    assert included_sections is None
    assert include_cover is False
    assert included_pages == ['engine/documentation/2.1 Exact matching.md']
    assert download_name == 'exact_matching.pdf'


def test_generate_docs_pdf_async_rejects_unknown_pages(client, monkeypatch):
    _patch_async_helpers(monkeypatch, docs_blueprint)
    monkeypatch.setattr(docs_blueprint, '_background_docs_pdf', lambda *args, **kwargs: None)

    response = client.post('/api/docs/generate_pdf_async', json={
        'included_pages': ['exact_matching', 'no_such_page'],
        'selected_only': True,
    })

    assert response.status_code == 400
    assert response.get_json()['error'] == 'Unknown documentation page: no_such_page'


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
    assert docs_blueprint._to_sections_list(['engine:1', 'nonsense']) == ['engine:1']
    assert docs_blueprint._to_sections_list(7) is None

    assert docs_blueprint._to_pages_list(' exact_matching , ') == ['exact_matching']
    assert docs_blueprint._to_pages_list('["glossary", ""]') == ['glossary']
    assert docs_blueprint._to_pages_list(None) is None

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
