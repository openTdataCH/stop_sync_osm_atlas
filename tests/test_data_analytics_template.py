from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from backend.services.stats_export import _matching_rule_stats


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
        },
        "matching_rules": _matching_rule_stats({}, {}),
        "propagation": [],
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
    }


def test_source_dates_render_in_zurich_with_seconds():
    from backend.services.time_utils import format_zurich_display_timestamp
    from backend.services.stats_export import _build_source_download_stats

    env = Environment(loader=FileSystemLoader('templates'))
    env.globals['url_for'] = lambda endpoint, **values: '/static/'
    env.filters['format_zurich_display_timestamp'] = format_zurich_display_timestamp
    stats = _minimal_empty_stats(_build_source_download_stats({'acquisition': {'sources': {
        'atlas': {'downloaded_at': '2026-09-20T12:34:56Z'},
        'gtfs': {'downloaded_at': '2026-09-21T13:45:57Z'},
    }}}))
    stats.update(last_pipeline_data_import_ended_at='2026-09-27T15:04:05+02:00',
                 last_overpass_query_at='2026-09-27T12:55:49Z')
    html = env.get_template('components/stats_data.html').render(stats=stats, problem_breakdown={})
    for label, value in [('Pipeline completed', '2026-09-27 15:04:05'),
                         ('Last ATLAS Downloaded', '2026-09-20 14:34:56'),
                         ('Last GTFS Downloaded', '2026-09-21 15:45:57'),
                         ('Overpass queried', '2026-09-27 14:55:49')]:
        assert f'<span>{label}</span><strong>{value}</strong>' in html


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
    assert html.index('class="stats-section-nav"') < html.index('id="pipelineRunCard"')
    assert html.index('id="pipelineRunCard"') < html.index('aria-label="Source freshness"')
    assert 'href="#pipelineRunCard" aria-current="location">Pipeline</a>' in html
    assert 'class="stats-section-nav-shell"' in html
    assert html.index('class="stats-section-nav"') < html.index('id="stops-matching"')
    assert "The analytics below reflect the latest published dataset." not in html
    assert html.count('data-pipeline-stage=') == 8
    assert 'data-pipeline-stage="stop_matching"' in html
    assert 'data-stage-label-full="Prepare source files"' in html
    assert 'id="stops-matching"' in html
    assert 'id="unmatched"' in html
    assert html.count('class="stats-figures"') >= 1
    # Sections without per-source statistics say so instead of failing.
    assert "OSM stop statistics are not available" in html
    assert "Route matching statistics are not available" in html


def test_matches_by_rule_lists_rules_in_run_order_with_their_branches():
    env = Environment(loader=FileSystemLoader("templates"))
    env.globals["url_for"] = lambda endpoint, **values: "/static/"
    env.filters["format_zurich_display_timestamp"] = lambda value, include_seconds=False: value
    stats = _minimal_empty_stats()
    stats["summary"]["matched_pairs"] = 10
    stats["matching_rules"] = _matching_rule_stats(
        {"uic_two_sided_stop": 2, "uic_reference_one_osm": 5, "uic_reference_local_ref": 3}, {})

    html = env.get_template("components/stats_data.html").render(stats=stats, problem_breakdown={})

    assert html.index("UIC two-sided stop") < html.index("UIC reference") < html.index("GTFS route")
    assert "<code>uic_reference_local_ref</code>" in html
    assert "<code>uic_reference_one_source</code>" not in html  # empty branches are left out
    assert "Name, GTFS route" in html  # rules without matches are named once below the table


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
    assert html.count('data-pipeline-stage=') == 8
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
    assert "#2563eb" not in css
    assert 'class="mapping-paths"' in template
    assert 'class="mapping-path__step"' in template


def test_problem_priorities_read_stored_breakdowns_and_list_every_type():
    env = Environment(loader=FileSystemLoader("templates"))
    env.globals["url_for"] = lambda endpoint, **values: "/static/"
    env.filters["format_zurich_display_timestamp"] = lambda value, include_seconds=False: value
    stats = _minimal_empty_stats()
    stats["problems"] = {
        "total_stops": 20, "clean_entries": 12, "stops_with_problems": 8, "multiple_problems": 1,
    }

    # stats.json stores the priorities as strings; the PDF passes them on unchanged.
    html = env.get_template("components/stats_data.html").render(
        stats=stats,
        problem_breakdown={"2": {"contradicts_route_matching": 5, "distance": 3}},
    )

    significant = html[html.index("Significant"):html.index("Minor")]
    assert "<td>8</td>" in significant
    assert "Route contradiction" in significant
    assert "<td>5</td>" in significant
    assert "No problems at this priority" not in significant


def test_sections_follow_the_navigation_and_name_their_units():
    import json

    env = Environment(loader=FileSystemLoader("templates"))
    env.globals["url_for"] = lambda endpoint, **values: "/static/"
    env.filters["format_zurich_display_timestamp"] = lambda value, include_seconds=False: value
    stats = _minimal_empty_stats()
    stats["summary"].update(atlas_platforms=10, distinct_matched_atlas=8, osm_stops=6, matched_osm_stops=3,
                            unmatched_osm=2)
    stats["unmatched_analysis"]["osm"].update(total=4)
    stats["route_links"] = {
        "line_links": 2,
        "gtfs_lines": {"total": 4, "linked": 2, "unlinked": {"no_osm_line": 2, "osm_line_already_linked": 0}},
        "osm_lines": {"total": 5, "public_transport": 4, "linked": 2, "unlinked": {
            "not_public_transport": 1, "non_gtfs": 0, "no_route_id": 1, "route_id_not_in_gtfs": 1,
            "gtfs_line_already_linked": 0}},
        "by_mode": [{"mode": "bus", "gtfs_lines": 4, "gtfs_linked": 2, "osm_lines": 4, "osm_linked": 2}],
        "by_match_method": {"exact_gtfs_route_id": 2},
        "itineraries": {"links": 1, "gtfs_in_linked_lines": 4, "gtfs_linked": 1, "osm_in_linked_lines": 2,
                        "osm_linked": 1, "osm_in_linked_lines_without_direction": 0},
        "itineraries_per_line": {"gtfs": {"mean": 2, "median": 2}, "osm": {"mean": 1, "median": 1}},
        "linked_line_itinerary_gap": {"mean": 1, "median": 1, "gtfs_has_more": 2, "same": 0, "osm_has_more": 0},
    }

    html = env.get_template("components/stats_data.html").render(stats=stats, problem_breakdown={})

    anchors = ["stops-matching", "unmatched", "route-matching", "problems", "atlas", "gtfs", "osm-stops", "osm-routes"]
    for anchor in anchors:
        assert f'href="#{anchor}"' in html
    positions = [html.index(f'id="{anchor}"') for anchor in anchors]
    assert positions == sorted(positions)
    assert "4 unmatched elements" in html
    assert "2 stop units have no matched element." in html
    # One-to-one links: the link count appears once as a figure, coverage per side next to it.
    assert html.count(">Linked line pairs<") == 1
    assert "2 / 4 public transport lines" in html
    assert "Route problems" not in html
    json.dumps(stats)
