import pytest
import pandas as pd

from matching_and_import_db.downloader import get_atlas_gtfs as gtfs_mod
from matching_and_import_db.downloader.get_atlas_gtfs import parse_gtfs_stop_ids


def test_parse_gtfs_stop_ids_uses_didok_for_sloid_stop_ids():
    parsed = parse_gtfs_stop_ids(pd.DataFrame([
        {
            'stop_id': 'ch:1:sloid:10:1:1',
            'original_stop_id': 'ch:1:sloid:10:1:1',
            'didok': '8500010',
            'platform_code': '1',
            'stop_code': None,
        }
    ]))

    assert parsed.loc[0, 'uic_number'] == '8500010'
    assert parsed.loc[0, 'normalized_local_ref'] == '1'


def test_parse_gtfs_stop_ids_handles_empty_frame():
    parsed = parse_gtfs_stop_ids(pd.DataFrame(columns=[
        'stop_id',
        'original_stop_id',
        'didok',
        'platform_code',
        'stop_code',
    ]))

    assert parsed.empty
    assert 'uic_number' in parsed.columns


def test_select_swiss_gtfs_stops_accepts_didok_for_sloid_stop_ids(monkeypatch):
    monkeypatch.setattr(gtfs_mod, 'filter_points_in_switzerland', lambda df, **_kwargs: df)

    selected = gtfs_mod._select_swiss_gtfs_stops(pd.DataFrame([
        {
            'stop_id': 'ch:1:sloid:10',
            'original_stop_id': 'ch:1:sloid:10',
            'didok': '8500010',
            'stop_lat': 47.5474,
            'stop_lon': 7.5896,
        },
        {
            'stop_id': '8002140',
            'original_stop_id': '8002140',
            'didok': '8002140',
            'stop_lat': 48.3654,
            'stop_lon': 10.8856,
        },
    ]))

    assert selected['stop_id'].tolist() == ['ch:1:sloid:10']


def test_select_swiss_gtfs_stops_fails_clearly_when_no_swiss_identifiers(monkeypatch):
    monkeypatch.setattr(gtfs_mod, 'filter_points_in_switzerland', lambda df, **_kwargs: df)

    with pytest.raises(RuntimeError, match='GTFS Swiss stop filter produced 0 stops'):
        gtfs_mod._select_swiss_gtfs_stops(pd.DataFrame([
            {
                'stop_id': 'ch:1:sloid:10',
                'original_stop_id': 'ch:1:sloid:10',
                'didok': '',
                'stop_lat': 47.5474,
                'stop_lon': 7.5896,
            }
        ]))
