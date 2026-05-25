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
    assert "Unknown" in html
