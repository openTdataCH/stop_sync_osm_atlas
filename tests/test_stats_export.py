from backend.services.stats_export import (
    _build_source_download_stats,
    load_stats_from_file,
    save_stats_to_file,
    refresh_stats_metadata,
)


def test_source_download_stats_exposes_generic_downloaded_at_alias():
    stats = _build_source_download_stats({
        "preprocessing_sources": {
            "atlas": {
                "atlas_downloaded_at": "2026-05-20T14:45:05+02:00",
                "etag": '"atlas-etag"',
            },
            "gtfs": {
                "gtfs_downloaded_at": "2026-05-20T14:46:05+02:00",
                "download_filename": "gtfs.zip",
            },
        },
    })

    assert stats["atlas"]["downloaded_at"] == "2026-05-20T14:45:05+02:00"
    assert stats["atlas"]["atlas_downloaded_at"] == "2026-05-20T14:45:05+02:00"
    assert stats["gtfs"]["downloaded_at"] == "2026-05-20T14:46:05+02:00"
    assert stats["gtfs"]["gtfs_downloaded_at"] == "2026-05-20T14:46:05+02:00"


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
    data_meta.update_data_meta(preprocessing_sources={'atlas': {'downloaded_at': '2026-01-01'}},
                              last_overpass_query_at='2026-01-01')
    meta = data_meta.record_bundle_metadata(dict(run_id='generic', metadata={}))
    assert meta['last_overpass_query_at'] is None
    assert _build_source_download_stats(meta) is None


def test_cache_checks_and_remote_updates_are_not_download_dates():
    stats = _build_source_download_stats({'acquisition': {'acquired_at': '2026-09-27', 'sources': {
        'gtfs': {'last_modified': 'Thu, 24 Sep 2026 07:01:04 GMT', 'etag': 'v1'}
    }}})
    assert stats['gtfs']['downloaded_at'] is None
    assert _build_source_download_stats({'preprocessing_sources': {'preprocessing_completed_at': '2026-09-27'}}) is None


def test_load_stats_from_file_tolerates_malformed_json(tmp_path):
    stats_path = tmp_path / "stats.json"
    stats_path.write_text('{"summary":', encoding="utf-8")

    assert load_stats_from_file(str(stats_path)) is None


def test_save_stats_to_file_writes_readable_json(tmp_path):
    stats_path = tmp_path / "stats.json"

    save_stats_to_file({"summary": {"matched_pairs": 3}}, str(stats_path))

    assert load_stats_from_file(str(stats_path)) == {"summary": {"matched_pairs": 3}}
