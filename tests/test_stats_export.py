from backend.services.stats_export import _build_source_download_stats


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
