from backend.services.stats_export import (
    _build_source_download_stats,
    load_stats_from_file,
    save_stats_to_file,
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

    assert stats["atlas"]["downloaded_at"] == "2026-05-20 14:45"
    assert stats["atlas"]["atlas_downloaded_at"] == "2026-05-20 14:45"
    assert stats["gtfs"]["downloaded_at"] == "2026-05-20 14:46"
    assert stats["gtfs"]["gtfs_downloaded_at"] == "2026-05-20 14:46"


def test_load_stats_from_file_tolerates_malformed_json(tmp_path):
    stats_path = tmp_path / "stats.json"
    stats_path.write_text('{"summary":', encoding="utf-8")

    assert load_stats_from_file(str(stats_path)) is None


def test_save_stats_to_file_writes_readable_json(tmp_path):
    stats_path = tmp_path / "stats.json"

    save_stats_to_file({"summary": {"matched_pairs": 3}}, str(stats_path))

    assert load_stats_from_file(str(stats_path)) == {"summary": {"matched_pairs": 3}}
