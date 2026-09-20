"""Bounded GTFS reduction: native CSV scan, partitioned Parquet, unique trip patterns.

Only feed-derived products live here. ATLAS identity resolution runs afterwards.
Identifiers remain strings; repeated stop visits and foreign termini are retained.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import duckdb
import pandas as pd

from transport_matcher.timing import stage
from .get_atlas_gtfs import _load_gtfs_metadata

CACHE_VERSION = 1
PARTITIONS = 256
TABLES = ('stops', 'trips', 'routes', 'stop_route_unique', 'route_directions')


def connect(path=':memory:'):
    return duckdb.connect(str(path), config={
        'threads': int(os.getenv('GTFS_THREADS', '2')),
        'memory_limit': os.getenv('GTFS_MEMORY_LIMIT', '768MB'),
        'preserve_insertion_order': True,
    })


def _quote(path):
    return "'" + str(path).replace("'", "''") + "'"


def write_cache(data, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        for name in TABLES:
            con.register('frame', data[name])
            con.execute(f'COPY frame TO {_quote(destination / (name + ".parquet"))} (FORMAT PARQUET)')
            con.unregister('frame')
    pattern_source = data.get('trip_patterns_path')
    stage_source = pattern_source or data.get('trip_stop_times_path')
    stage_name = 'trip_patterns.parquet' if pattern_source else 'trip_stop_times.csv'
    target = destination / stage_name
    if stage_source and Path(stage_source).resolve() != target.resolve():
        shutil.copyfile(stage_source, target)
    (destination / 'metadata.json').write_text(json.dumps({
        'version': CACHE_VERSION, 'stage_name': stage_name if stage_source else None,
        'dtypes': {name: {column: str(dtype) for column, dtype in data[name].dtypes.items()} for name in TABLES},
        'trip_stop_times_row_count': data['trip_stop_times_row_count'],
    }) + '\n')


def read_cache(path):
    path = Path(path)
    metadata = json.loads((path / 'metadata.json').read_text())
    if metadata['version'] != CACHE_VERSION:
        raise ValueError('Unsupported GTFS preprocessing cache version')
    with connect() as con:
        result = {name: con.execute('SELECT * FROM read_parquet(?)', [str(path / (name + '.parquet'))]).df()
                  for name in TABLES}
    for name, dtypes in metadata.get('dtypes', {}).items():
        result[name] = result[name].astype(dtypes)
    stage_name = metadata.get('stage_name')
    result.update(trip_patterns_path=str(path / stage_name) if stage_name == 'trip_patterns.parquet' else None,
                  trip_stop_times_path=str(path / stage_name) if stage_name == 'trip_stop_times.csv' else None,
                  trip_stop_times_row_count=metadata['trip_stop_times_row_count'])
    return result


def iter_trip_patterns(path):
    # Stream Python objects only for reduced patterns, never for every stop-time.
    with connect() as con:
        cursor = con.execute('SELECT trip_id, stop_ids, stop_sequences, trip_count FROM read_parquet(?) ORDER BY first_ordinal', [str(path)])
        while rows := cursor.fetchmany(1000):
            for trip_id, stop_ids, sequences, trip_count in rows:
                yield trip_id, {'stop_id': stop_ids, 'stop_sequence': sequences}, trip_count


def load_gtfs_columnar(gtfs_folder, *, stop_selector=None, stage_dir):
    folder, work = Path(gtfs_folder), Path(stage_dir)
    work.mkdir(parents=True, exist_ok=True)
    with stage('gtfs.metadata'):
        all_stops, stops, trips = _load_gtfs_metadata(str(folder), stop_selector)
        if trips['trip_id'].isna().any() or trips['trip_id'].duplicated().any():
            raise ValueError('GTFS trips.txt requires unique, nonempty trip_id values')
        routes = pd.read_csv(folder / 'routes.txt', dtype=str, usecols=lambda c: c in {
            'route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_desc', 'route_type'})
        for column in ('agency_id', 'route_short_name', 'route_long_name', 'route_desc', 'route_type'):
            if column not in routes:
                routes[column] = None
    database = work / 'processing.duckdb'
    partitions = work / 'calls'
    trip_partitions = work / 'trip_metadata'
    patterns_path = work / 'trip_patterns.parquet'
    try:
        with connect(database) as con:
            con.register('selected_stops', stops[['stop_id']])
            con.register('trip_metadata', trips)
            with stage('gtfs.scan', input_bytes=(folder / 'stop_times.txt').stat().st_size):
                con.execute('''CREATE TABLE raw AS
                    SELECT row_number() OVER () AS ordinal, trip_id, stop_id,
                           CAST(stop_sequence AS BIGINT) AS stop_sequence
                    FROM read_csv(?, header=true, all_varchar=true)''', [str(folder / 'stop_times.txt')])
                if con.execute('SELECT EXISTS(SELECT 1 FROM raw WHERE trip_id IS NULL OR stop_id IS NULL OR stop_sequence IS NULL)').fetchone()[0]:
                    raise ValueError('GTFS stop_times requires trip_id, stop_id and stop_sequence')
            # The explicit ordinal now carries deterministic input order. Native
            # operators can reorder/spill without changing representative choice.
            con.execute('SET preserve_insertion_order=false')
            with stage('gtfs.filter_and_termini'):
                con.execute('''CREATE TABLE selected AS SELECT r.* FROM raw r
                    SEMI JOIN selected_stops s ON r.stop_id=s.stop_id''')
                row_count = con.execute('SELECT count(*) FROM selected').fetchone()[0]
                relevant = con.execute('SELECT DISTINCT trip_id FROM selected').df()['trip_id']
                termini = con.execute('''SELECT trip_id,
                    arg_min(stop_id, struct_pack(seq := stop_sequence, pos := ordinal)) AS stop_id_first,
                    arg_min(stop_id, struct_pack(seq := -stop_sequence, pos := ordinal)) AS stop_id_last
                    FROM raw SEMI JOIN (SELECT DISTINCT trip_id FROM selected) USING(trip_id)
                    GROUP BY trip_id ORDER BY trip_id''').df()
                unique = con.execute('''SELECT s.stop_id, t.route_id, t.direction_id
                    FROM selected s JOIN trip_metadata t USING(trip_id)
                    WHERE t.route_id IS NOT NULL
                    GROUP BY s.stop_id, t.route_id, t.direction_id ORDER BY min(s.ordinal)''').df()
                con.execute('DROP TABLE raw')
            # Partition by trip hash so a whole trip stays together even when the
            # feed is interleaved. Each ordered-list aggregation sees 1/256 of rows.
            with stage('gtfs.partition', rows=row_count):
                con.execute(f'''COPY (SELECT *, hash(trip_id) % {PARTITIONS} AS bucket FROM selected)
                    TO {_quote(partitions)} (FORMAT PARQUET, PARTITION_BY (bucket))''')
                con.execute('DROP TABLE selected')
                con.execute(f'''COPY (SELECT trip_id, route_id, direction_id,
                    CAST(trip_headsign AS VARCHAR) AS trip_headsign,
                    CAST(trip_short_name AS VARCHAR) AS trip_short_name,
                    hash(trip_id) % {PARTITIONS} AS bucket FROM trip_metadata)
                    TO {_quote(trip_partitions)} (FORMAT PARQUET, PARTITION_BY (bucket))''')
            with stage('gtfs.reduce_patterns', rows=row_count):
                con.execute('''CREATE TABLE patterns (trip_id VARCHAR, stop_ids VARCHAR[],
                    stop_sequences BIGINT[], trip_count BIGINT, first_ordinal BIGINT,
                    route_id VARCHAR, direction_id BIGINT, trip_headsign VARCHAR, trip_short_name VARCHAR)''')
                for partition in sorted(partitions.glob('bucket=*')):
                    trip_partition = trip_partitions / partition.name
                    if not trip_partition.exists():
                        continue
                    con.execute('''INSERT INTO patterns
                        WITH ordered AS (
                            SELECT trip_id, list(stop_id ORDER BY stop_sequence, stop_id, ordinal) AS stop_ids,
                                   list(stop_sequence ORDER BY stop_sequence, stop_id, ordinal) AS stop_sequences,
                                   min(ordinal) AS first_ordinal
                            FROM read_parquet(?) GROUP BY trip_id
                        )
                        SELECT arg_min(o.trip_id, first_ordinal), o.stop_ids,
                               arg_min(o.stop_sequences, first_ordinal), count(*), min(first_ordinal),
                               t.route_id, t.direction_id, t.trip_headsign,
                               CASE WHEN nullif(trim(t.trip_headsign), '') IS NULL THEN t.trip_short_name ELSE NULL END AS effective_short_name
                        FROM ordered o JOIN read_parquet(?) t USING(trip_id)
                        GROUP BY o.stop_ids, t.route_id, t.direction_id, t.trip_headsign, effective_short_name''',
                        [str(partition / '*.parquet'), str(trip_partition / '*.parquet')])
                con.execute(f'''COPY (
                    SELECT arg_min(trip_id, first_ordinal) AS trip_id, stop_ids,
                           arg_min(stop_sequences, first_ordinal) AS stop_sequences,
                           sum(trip_count)::BIGINT AS trip_count, min(first_ordinal) AS first_ordinal
                    FROM patterns GROUP BY stop_ids, route_id, direction_id, trip_headsign, trip_short_name
                    ORDER BY first_ordinal
                ) TO {_quote(patterns_path)} (FORMAT PARQUET)''')
                pattern_count = con.execute('SELECT count(*) FROM read_parquet(?)', [str(patterns_path)]).fetchone()[0]
                print(json.dumps({'event': 'gtfs_reduced', 'stop_time_rows': row_count,
                                  'trips': len(relevant), 'patterns': pattern_count}), flush=True)
        trips = trips[trips['trip_id'].isin(relevant)].copy()
        termini = termini.merge(trips[['trip_id', 'route_id', 'direction_id']], on='trip_id').dropna(subset=['route_id'])
        names = all_stops.set_index('stop_id')['stop_name'].to_dict()
        termini['direction'] = (termini['stop_id_first'].map(names).fillna('Unknown') + ' → '
                                 + termini['stop_id_last'].map(names).fillna('Unknown'))
        return {'stops': stops, 'trips': trips,
                'routes': routes[routes['route_id'].isin(trips['route_id'])].copy(),
                'stop_route_unique': unique,
                'route_directions': termini[['route_id', 'direction_id', 'direction']].drop_duplicates(),
                'trip_stop_times_path': None, 'trip_patterns_path': str(patterns_path),
                'trip_stop_times_row_count': row_count}
    finally:
        shutil.rmtree(partitions, ignore_errors=True)
        shutil.rmtree(trip_partitions, ignore_errors=True)
        database.unlink(missing_ok=True)
        Path(str(database) + '.wal').unlink(missing_ok=True)
