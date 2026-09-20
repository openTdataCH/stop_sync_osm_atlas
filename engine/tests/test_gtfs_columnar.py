import csv
from pathlib import Path

import pandas as pd
import pytest

from transport_matcher.adapters.gtfs_columnar import load_gtfs_columnar, iter_trip_patterns, write_cache, read_cache
from transport_matcher.adapters.get_atlas_gtfs import load_gtfs_data_streaming
from transport_matcher.swiss import _map_gtfs_products


def write(path, rows):
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def feed(tmp_path):
    root = tmp_path / 'feed'
    root.mkdir()
    write(root / 'stops.txt', [dict(stop_id=key, stop_name=name, stop_lat='47', stop_lon='8',
                                  original_stop_id=ref, platform_code=platform)
        for key, name, ref, platform in [('001', 'Alpha', '8500001:1', '1'),
                                        ('002', 'Beta', '8500002:1', '1'),
                                        ('003', 'Alpha alternate', '8500001:2', '2'),
                                        ('foreign', 'Foreign terminus', '8000000', '')]])
    write(root / 'routes.txt', [dict(route_id='001', route_short_name='01', route_long_name='Line')])
    write(root / 'trips.txt', [dict(trip_id=key, route_id='001', direction_id=direction,
                                  trip_headsign=headsign, trip_short_name=short)
        for key, direction, headsign, short in [('t1', '0', 'Beta', '1'), ('t2', '0', 'Beta', '2'),
                                               ('t3', '0', 'Beta', '3'), ('t4', '', '', 'Night')]])
    rows = []
    for trip, stops in [('t1', ['foreign', '001', '002', '001']),
                        ('t2', ['foreign', '001', '002', '001']),
                        ('t3', ['foreign', '003', '002', '003']), ('t4', ['002', '001'])]:
        rows.extend(dict(trip_id=trip, stop_id=stop, stop_sequence=sequence * 10)
                    for sequence, stop in reversed(list(enumerate(stops, 1))))
    write(root / 'stop_times.txt', rows)
    return root


def selector(stops):
    return stops[stops['stop_id'] != 'foreign'].copy()


def atlas():
    return pd.DataFrame([dict(sloid='ch:1:sloid:A', number='8500001', designation='1',
                              designationOfficial='Alpha', wgs84North='47', wgs84East='8'),
                         dict(sloid='ch:1:sloid:B', number='8500002', designation='1',
                              designationOfficial='Beta', wgs84North='47', wgs84East='8')])


def canonical(frame):
    return frame.sort_values(list(frame.columns)).reset_index(drop=True)


def test_columnar_matches_legacy_products_and_preserves_loops_and_foreign_termini(feed, tmp_path):
    legacy_dir = tmp_path / 'legacy'
    legacy_dir.mkdir()
    old = load_gtfs_data_streaming(str(feed), stop_selector=selector, stage_dir=str(legacy_dir))
    new = load_gtfs_columnar(feed, stop_selector=selector, stage_dir=tmp_path / 'native')
    assert new['trip_stop_times_row_count'] == old['trip_stop_times_row_count'] == 11
    assert len(list(iter_trip_patterns(new['trip_patterns_path']))) == 3
    assert sorted(weight for _, _, weight in iter_trip_patterns(new['trip_patterns_path'])) == [1, 1, 2]
    assert any('Foreign terminus' in label for label in new['route_directions']['direction'])
    assert new['routes']['route_id'].tolist() == ['001']
    for name in ('stops', 'trips', 'routes', 'stop_route_unique', 'route_directions'):
        pd.testing.assert_frame_equal(canonical(old[name]), canonical(new[name]), check_dtype=False)
    old_products, *old_identity = _map_gtfs_products(old, atlas())
    new_products, *new_identity = _map_gtfs_products(new, atlas())
    for key in old_products:
        pd.testing.assert_frame_equal(canonical(old_products[key]), canonical(new_products[key]), check_dtype=False)
    assert old_identity == new_identity
    calls = new_products['atlas_itinerary_stop_calls']
    assert calls['stop_sequence'].max() >= 3  # repeated Alpha call has survived


def test_interleaved_trips_have_complete_ordered_patterns(feed, tmp_path):
    original = load_gtfs_columnar(feed, stop_selector=selector, stage_dir=tmp_path / 'original')
    rows = list(csv.DictReader((feed / 'stop_times.txt').open()))
    rows.sort(key=lambda row: (int(row['stop_sequence']), row['trip_id']), reverse=True)
    write(feed / 'stop_times.txt', rows)
    interleaved = load_gtfs_columnar(feed, stop_selector=selector, stage_dir=tmp_path / 'interleaved')
    def patterns(data):
        return sorted((tuple(calls['stop_id']), count) for _, calls, count in iter_trip_patterns(data['trip_patterns_path']))
    assert patterns(interleaved) == patterns(original)
    # Cache round-trip preserves nullable dtypes as well as nested patterns.
    write_cache(interleaved, tmp_path / 'cache')
    cached = read_cache(tmp_path / 'cache')
    assert patterns(cached) == patterns(original)
    for key in ('stops', 'trips', 'routes', 'stop_route_unique', 'route_directions'):
        def normalized(frame):
            return frame.astype(object).where(frame.notna(), None).reset_index(drop=True)
        pd.testing.assert_frame_equal(normalized(cached[key]), normalized(interleaved[key]))


def test_empty_selection_is_supported(feed, tmp_path):
    data = load_gtfs_columnar(feed, stop_selector=lambda frame: frame.iloc[:0], stage_dir=tmp_path / 'empty')
    assert data['trip_stop_times_row_count'] == 0
    assert list(iter_trip_patterns(data['trip_patterns_path'])) == []
