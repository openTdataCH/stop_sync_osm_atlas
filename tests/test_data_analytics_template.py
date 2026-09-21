from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def _minimal_empty_stats(source_downloads=None):
    return {
        "generated_at": "2026-05-25T10:00:00+02:00",
        "stats_computed_at": "2026-05-25T10:00:00+02:00",
        "last_pipeline_data_import_ended_at": None,
        "last_overpass_query_at": None,
        "source_downloads": source_downloads,
        "summary": {
            "atlas_platforms": 0,
            "osm_stops": 0,
            "osm_nodes": 0,
            "osm_stations": 0,
            "matched_pairs": 0,
            "match_rate_percent": 0,
            "atlas_with_osm_within_50m": 0,
            "matched_atlas_with_osm_within_50m_percent": 0,
            "osm_operator_wikidata": 0,
            "osm_network_wikidata": 0,
        },
        "matching_stages": {
            "exact": {"count": 0, "mto": 0},
            "name": {"count": 0, "mto": 0},
            "route": {
                "count": 0,
                "mto": 0,
                "breakdown": {"gtfs": 0, "gtfs_mto": 0},
            },
            "distance": {
                "count": 0,
                "mto": 0,
                "breakdown": {
                    "stage0_trio": 0,
                    "stage0_trio_mto": 0,
                    "stage1_group": 0,
                    "stage1_group_mto": 0,
                    "stage1_group_by_key": {},
                    "stage1b_long_group": 0,
                    "stage1b_long_group_mto": 0,
                    "stage1b_long_group_by_key": {},
                    "stage2_local_ref": 0,
                    "stage2_local_ref_mto": 0,
                    "stage3a_single": 0,
                    "stage3a_single_mto": 0,
                    "stage3a_single_pass1": 0,
                    "stage3a_single_pass1_mto": 0,
                    "stage3a_single_pass2": 0,
                    "stage3a_single_pass2_mto": 0,
                    "stage3b_relative": 0,
                    "stage3b_relative_mto": 0,
                },
            },
            "post_processing": {
                "duplicate_propagation": 0,
                "duplicate_propagation_mto": 0,
                "osm_group_propagation": 0,
                "osm_group_propagation_mto": 0,
            },
        },
        "unmatched_analysis": {
            "atlas": {
                "total": 0,
                "no_osm_within_50m": 0,
                "has_nearby_osm": 0,
            },
            "osm": {
                "total": 0,
                "no_atlas_within_50m": 0,
                "has_nearby_atlas": 0,
                "matrix": {},
            },
        },
        "duplicates": {
            "total_duplicate_sloids": 0,
            "matched_duplicates": 0,
            "unmatched_duplicates": 0,
        },
    }


def test_stats_data_template_handles_missing_source_downloads():
    env = Environment(loader=FileSystemLoader("templates"))
    env.globals["url_for"] = lambda endpoint, **values: "/static/"
    env.filters["format_zurich_display_timestamp"] = lambda value, include_seconds=False: value

    html = env.get_template("components/stats_data.html").render(
        stats=_minimal_empty_stats(source_downloads=None),
        problem_breakdown={},
    )

    assert "Last ATLAS Downloaded" in html
    assert "Last GTFS Downloaded" in html
    assert '<h2 id="sourceFreshnessTitle">Source freshness</h2>' not in html
    assert "Inputs used by this analytics snapshot" not in html
    assert "Unknown" in html
    assert 'class="stats-section-nav"' in html
    assert 'class="stats-section-nav__indicator"' in html
    assert 'id="pipelineRunCard"' in html
    assert 'id="pipelineStageDetails"' in html
    assert html.index('aria-label="Source freshness"') < html.index('class="stats-section-nav"')
    assert html.index('class="stats-section-nav"') < html.index('id="stops-matching"')
    assert "The analytics below reflect the latest published dataset." not in html
    assert html.count('data-pipeline-stage=') == 9
    assert 'data-pipeline-stage="stop_matching"' in html
    assert 'data-stage-label-full="Prepare timetable data"' in html
    assert 'id="stops-matching"' in html
    assert 'id="unmatched"' in html
    assert 'class="osm-overview-card"' in html
    assert 'class="osm-inventory-strip"' in html


def test_stats_data_template_handles_partial_stats_without_summary():
    env = Environment(loader=FileSystemLoader("templates"))
    env.filters["format_zurich_display_timestamp"] = lambda value, include_seconds=False: value

    html = env.get_template("components/stats_data.html").render(
        stats={"atlas_filtering": {"total_input": 10}},
        problem_breakdown={},
    )

    assert "No stats available" in html
    assert 'id="pipelineRunCard"' in html
    assert html.index('id="pipelineRunCard"') < html.index("No stats available")
    assert html.count('data-pipeline-stage=') == 9
    assert "Waiting for first pipeline run" in html


def test_stats_data_template_keeps_live_pipeline_visible_without_stats():
    env = Environment(loader=FileSystemLoader("templates"))
    env.filters["format_zurich_display_timestamp"] = lambda value, include_seconds=False: value

    html = env.get_template("components/stats_data.html").render(
        stats=None,
        problem_breakdown={},
        pipeline_status={
            "status": "running",
            "phase": "initializing",
            "message": "Initializing pipeline run",
            "started_at": "2026-09-21T12:00:00+00:00",
        },
    )

    assert 'class="pipeline-run-card is-running"' in html
    assert "Pipeline update in progress" in html
    assert "Initializing pipeline run" in html
    assert html.index('id="pipelineRunCard"') < html.index("No stats available")


def test_stats_data_template_renders_running_state_before_javascript_poll():
    env = Environment(loader=FileSystemLoader("templates"))
    env.globals["url_for"] = lambda endpoint, **values: "/static/"
    env.filters["format_zurich_display_timestamp"] = lambda value, include_seconds=False: value

    html = env.get_template("components/stats_data.html").render(
        stats=_minimal_empty_stats(),
        problem_breakdown={},
        pipeline_status={
            "status": "running",
            "phase": "matching",
            "message": "Matching sources",
        },
    )

    assert 'class="pipeline-run-card is-running"' in html
    assert "Pipeline update in progress" in html
    assert "Matching sources" in html
    assert '<span class="pipeline-run-card__dot"></span>Running' in html


def test_analytics_design_does_not_use_left_accent_borders():
    css = Path("static/css/pages/stats.css").read_text(encoding="utf-8")
    template = Path("templates/components/stats_data.html").read_text(encoding="utf-8")

    assert "border-left" not in css
    assert "inset 3px 0" not in css
    assert ".stats-page .stat-card--primary::after" not in css
    assert "--card-accent: var(--color-primary)" in css
    assert "#2563eb" not in css
    assert 'class="mapping-paths"' in template
    assert 'class="mapping-path__step"' in template
