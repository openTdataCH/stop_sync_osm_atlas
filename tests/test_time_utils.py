def test_format_zurich_display_timestamp_formats_iso_strings():
    from backend.services.time_utils import format_zurich_display_timestamp

    assert format_zurich_display_timestamp("2026-05-10T11:14:40.367792+02:00") == "2026-05-10 11:14"
    assert format_zurich_display_timestamp("2026-05-10T09:14:40Z") == "2026-05-10 11:14"
