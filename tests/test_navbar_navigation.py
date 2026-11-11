import re


def test_routes_subpages_use_page_tabs_and_keep_mobile_version(client):
    response = client.get('/routes/gtfs-stop-id-sloid')

    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert '<nav class="c-page-tabs" aria-label="Routes pages" style="--page-tabs-count: 3">' in html
    assert html.count('c-page-tabs__tab') == 3
    assert 'SLOID <span aria-hidden="true">↔</span> GTFS stop_id' in html
    assert 'c-page-tabs__tab is-active' in html
    assert 'aria-current="page"' in html
    assert 'navbar-section__toggle' not in html
    assert 'routesNavbarMenu' not in html
    assert 'class="navbar-version navbar-version--brand"' in html
    assert 'class="nav-item navbar-mobile-version d-lg-none"' in html
    assert html.index('>Docs</a>') < html.index('navbar-mobile-version') < html.index('navbarDataUpdated')


def test_data_subpages_use_page_tabs_without_navbar_dropdown(client):
    response = client.get('/data/export')

    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert '<nav class="c-page-tabs c-page-tabs--sticky" aria-label="Data pages" style="--page-tabs-count: 2">' in html
    assert html.count('c-page-tabs__tab') == 2
    assert 'c-page-tabs__tab is-active' in html
    assert 'aria-current="page"' in html
    assert 'navbar-section__toggle' not in html
    assert 'dataNavbarMenu' not in html


def test_navbar_renders_next_run_metadata(client, monkeypatch):
    from backend.services import pipeline_status, stats_export

    monkeypatch.setattr(
        stats_export,
        "load_stats_from_file",
        lambda: {"last_pipeline_data_import_ended_at": "2026-05-02T09:15:00+02:00"},
    )
    monkeypatch.setattr(
        pipeline_status,
        "get_status",
        lambda: {
            "last_pipeline_data_import_ended_at": "2026-05-02T19:31:00+02:00",
            "next_run_at": "2026-05-03T08:00:00+00:00",
        },
    )

    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="navbarDataUpdated"' in html
    assert 'id="navbarDataUpdatedText"' in html
    assert 'data-data-updated-at="2026-05-02T19:31:00+02:00"' in html
    assert 'data-pipeline-next-run-at="2026-05-03T08:00:00+00:00"' in html
    assert 'data-running-label="Pipeline running in the background"' in html
    assert 'id="navbarNextRunInfo"' in html
    assert 'data-bs-toggle="tooltip"' in html
    assert 'title="Next pipeline run: 2026-05-03 10:00"' in html
    navbar_fragment = re.search(r'<span[^>]*id="navbarDataUpdated"[\s\S]*?<\/span>\s*<\/li>', html)
    assert navbar_fragment is not None
    assert 'far fa-clock' not in navbar_fragment.group(0)
    assert re.search(r'<span[^>]*id="navbarDataUpdated"[^>]*title=', html) is None


def test_navbar_renders_next_run_without_import_timestamp(client, monkeypatch):
    from backend.services import pipeline_status, stats_export

    monkeypatch.setattr(stats_export, "load_stats_from_file", lambda: {})
    monkeypatch.setattr(
        pipeline_status,
        "get_status",
        lambda: {
            "last_pipeline_data_import_ended_at": None,
            "next_run_at": "2026-05-03T08:00:00+00:00",
        },
    )

    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="navbarDataUpdated"' in html
    assert 'data-data-updated-at=""' in html
    assert 'data-pipeline-next-run-at="2026-05-03T08:00:00+00:00"' in html
    assert "Data not imported yet" in html
    assert 'title="Next pipeline run: 2026-05-03 10:00"' in html


def test_running_pipeline_is_present_in_server_rendered_navbar_and_bootstrap_state(client, monkeypatch):
    from backend.services import pipeline_status, stats_export

    monkeypatch.setattr(stats_export, "load_stats_from_file", lambda: {})
    monkeypatch.setattr(
        pipeline_status,
        "get_status",
        lambda: {
            "status": "running",
            "phase": "matching",
            "message": "Matching sources",
            "last_pipeline_data_import_ended_at": "2026-05-02T19:31:00+02:00",
            "next_run_at": "2026-05-03T08:00:00+00:00",
        },
    )

    html = client.get("/").get_data(as_text=True)

    assert '<span id="navbarDataUpdatedText">Pipeline running in the background</span>' in html
    assert 'window.initialPipelineStatus = {' in html
    assert '"phase": "matching"' in html
    assert '"status": "running"' in html
