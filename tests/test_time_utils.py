def test_format_zurich_display_timestamp_formats_iso_strings():
    from backend.services.time_utils import format_zurich_display_timestamp

    assert format_zurich_display_timestamp("2026-05-10T11:14:40.367792+02:00") == "2026-05-10 11:14"
    assert format_zurich_display_timestamp("2026-05-10T09:14:40Z") == "2026-05-10 11:14"


def test_parse_utc_timestamp_reads_stored_timestamps_as_utc():
    from datetime import datetime, timezone

    from backend.services.time_utils import parse_utc_timestamp

    expected = datetime(2026, 11, 11, 9, 32, 15, tzinfo=timezone.utc)
    assert parse_utc_timestamp("2026-11-11T10:32:15+01:00") == expected
    assert parse_utc_timestamp("2026-11-11T09:32:15") == expected  # no zone: UTC
    assert parse_utc_timestamp("Wed, 11 Nov 2026 09:32:15 GMT") == expected
    assert parse_utc_timestamp(datetime(2026, 11, 11, 9, 32, 15)) == expected
    for unreadable in (None, "", "not a date", 0):
        assert parse_utc_timestamp(unreadable) is None
