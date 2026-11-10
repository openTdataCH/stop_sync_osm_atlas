from backend.services.stats_export import (
    _build_source_download_stats,
    compute_summary_from_db,
    load_stats_from_file,
    save_stats_to_file,
    refresh_stats_metadata,
)


def test_source_download_stats_come_from_the_bundle_acquisition():
    stats = _build_source_download_stats({"acquisition": {"sources": {
        "atlas": {"downloaded_at": "2026-05-20T12:45:05Z", "etag": '"atlas-etag"'},
        "gtfs": {"downloaded_at": "2026-05-20T12:46:05Z", "download_filename": "gtfs.zip"},
    }}})

    assert stats["atlas"] == {"downloaded_at": "2026-05-20T12:45:05Z", "etag": '"atlas-etag"',
                              "last_modified": None, "download_filename": None, "final_url": None}
    assert stats["gtfs"]["downloaded_at"] == "2026-05-20T12:46:05Z"
    assert stats["gtfs"]["download_filename"] == "gtfs.zip"


def test_bundle_provenance_and_completion_refresh_stats(monkeypatch, tmp_path):
    from backend.services import data_meta

    monkeypatch.setattr(data_meta, 'DATA_META_PATH', str(tmp_path / 'data_meta.json'))
    acquisition = dict(sources={
        'atlas': {'downloaded_at': '2026-09-20T12:00:05Z'},
        'gtfs': {'downloaded_at': '2026-09-21T13:00:06Z'},
    }, last_overpass_query_at='2026-09-27T12:55:49Z')
    meta = data_meta.record_bundle_metadata(dict(run_id='published', metadata={'acquisition': acquisition}))
    path = str(tmp_path / 'stats.json')
    save_stats_to_file(dict(active_run_id='published', summary={'matched_pairs': 3}), path)
    meta = data_meta.update_data_meta(last_pipeline_data_import_ended_at='2026-09-27T15:04:05+02:00')
    assert refresh_stats_metadata(meta, path)
    stats = load_stats_from_file(path)
    assert stats['summary'] == {'matched_pairs': 3}
    assert stats['last_pipeline_data_import_ended_at'] == meta['last_pipeline_data_import_ended_at']
    assert stats['last_overpass_query_at'] == acquisition['last_overpass_query_at']
    assert stats['source_downloads']['atlas']['downloaded_at'] == acquisition['sources']['atlas']['downloaded_at']
    assert stats['source_downloads']['gtfs']['downloaded_at'] == acquisition['sources']['gtfs']['downloaded_at']
    assert not refresh_stats_metadata(dict(meta, active_run_id='other'), path)
    assert load_stats_from_file(path) == stats


def test_import_without_acquisition_clears_previous_source_dates(monkeypatch, tmp_path):
    from backend.services import data_meta

    monkeypatch.setattr(data_meta, 'DATA_META_PATH', str(tmp_path / 'data_meta.json'))
    data_meta.update_data_meta(acquisition={'sources': {'atlas': {'downloaded_at': '2026-01-01'}}},
                              last_overpass_query_at='2026-01-01')
    meta = data_meta.record_bundle_metadata(dict(run_id='generic', metadata={}))
    assert meta['last_overpass_query_at'] is None
    assert _build_source_download_stats(meta) is None


def test_cache_checks_and_remote_updates_are_not_download_dates():
    stats = _build_source_download_stats({'acquisition': {'acquired_at': '2026-09-27', 'sources': {
        'gtfs': {'last_modified': 'Thu, 24 Sep 2026 07:01:04 GMT', 'etag': 'v1'}
    }}})
    assert stats['gtfs']['downloaded_at'] is None
    assert _build_source_download_stats({'acquisition': {'acquired_at': '2026-09-27'}}) is None


def test_load_stats_from_file_tolerates_malformed_json(tmp_path):
    stats_path = tmp_path / "stats.json"
    stats_path.write_text('{"summary":', encoding="utf-8")

    assert load_stats_from_file(str(stats_path)) is None


def test_save_stats_to_file_writes_readable_json(tmp_path):
    stats_path = tmp_path / "stats.json"

    save_stats_to_file({"summary": {"matched_pairs": 3}}, str(stats_path))

    assert load_stats_from_file(str(stats_path)) == {"summary": {"matched_pairs": 3}}


def test_summary_counts_an_effectively_matched_middle_as_a_matched_pair(sqlite_tables):
    from backend.models import OsmNode, OsmStop, OsmStopMember, StopsMatched

    session = sqlite_tables(OsmNode, OsmStop, OsmStopMember, StopsMatched)
    # A two-sided stop whose sides match two platforms, and an unmatched single
    # stop. Its middle is unmatched in the bundle but counts as matched.
    session.add_all([
        OsmNode(osm_node_id='side_a'), OsmNode(osm_node_id='middle'), OsmNode(osm_node_id='side_b'),
        OsmNode(osm_node_id='lone'),
        OsmStop(id=1, stop_kind='two_sided_stop', representative_node_id='middle'),
        OsmStop(id=2, stop_kind='single', representative_node_id='lone'),
        OsmStopMember(osm_stop_id=1, node_id='side_a', member_role='side'),
        OsmStopMember(osm_stop_id=1, node_id='middle', member_role='middle'),
        OsmStopMember(osm_stop_id=1, node_id='side_b', member_role='side'),
        OsmStopMember(osm_stop_id=2, node_id='lone', member_role='single'),
        StopsMatched(id=1, sloid='a', stop_type='matched', match_type='uic_two_sided_stop', osm_node_id='side_a'),
        StopsMatched(id=2, sloid='b', stop_type='matched', match_type='uic_two_sided_stop', osm_node_id='side_b'),
        StopsMatched(id=3, stop_type='effectively_matched', osm_node_id='middle'),
        StopsMatched(id=4, stop_type='osm_unmatched', osm_node_id='lone'),
        StopsMatched(id=5, sloid='c', stop_type='atlas_unmatched', match_type='no_nearby_counterpart'),
    ])
    session.commit()

    summary = compute_summary_from_db(session)

    assert summary['matched_pairs'] == 3
    assert (summary['atlas_platforms'], summary['distinct_matched_atlas'], summary['unmatched_atlas']) == (3, 2, 1)
    assert (summary['osm_stops'], summary['matched_osm_stops'], summary['unmatched_osm']) == (2, 1, 1)
    assert summary['osm_nodes'] == 4
    assert summary['match_rate_percent'] == 66.7
    # The isolated platform is left out of the rate among platforms with OSM nearby.
    assert summary['atlas_with_osm_within_50m'] == 2
    assert summary['matched_atlas_with_osm_within_50m_percent'] == 100.0
