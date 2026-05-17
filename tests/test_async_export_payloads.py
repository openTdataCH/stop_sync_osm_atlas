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
        'included_sections': '1.,2.',
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
    assert docs_blueprint._to_sections_list('') is None

    assert docs_blueprint._to_bool('false') is False
    assert docs_blueprint._to_bool('true') is True
    assert docs_blueprint._to_bool(None, default=True) is True


def test_existing_docs_pdf_path_uses_canonical_output(monkeypatch):
    canonical_path = '/tmp/stop_sync_osm_atlas_documentation.pdf'

    monkeypatch.setattr(docs_blueprint, '_docs_pdf_path', lambda: canonical_path)
    monkeypatch.setattr(docs_blueprint.os.path, 'exists', lambda path: path == canonical_path)

    assert docs_blueprint._existing_docs_pdf_path() == canonical_path
