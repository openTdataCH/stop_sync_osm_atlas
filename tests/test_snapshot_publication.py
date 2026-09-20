"""Real PostGIS transaction tests, enabled with TEST_POSTGRES_URI.

Use a disposable database: this fixture resets its public schema.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.extensions import db
from backend.importing.bundle import read_bundle
from backend.importing.projection import project_bundle
from backend.importing.importer import build_fast_insert_payloads, _write_rows
from backend.importing.publication import publish_snapshot
import backend.models


@pytest.fixture
def postgres():
    uri = os.getenv('TEST_POSTGRES_URI')
    if not uri:
        pytest.skip('TEST_POSTGRES_URI must identify a disposable PostGIS database')
    engine = create_engine(uri)
    with engine.begin() as connection:
        database = connection.execute(text('SELECT current_database()')).scalar()
        if not database.endswith('_test') and database != 'transport_test':
            pytest.fail('Database name must end in _test to permit resetting the test schema')
        connection.execute(text('DROP SCHEMA public CASCADE'))
        connection.execute(text('CREATE SCHEMA public'))
        connection.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
        db.Model.metadata.create_all(connection)
    yield engine
    engine.dispose()


def _example():
    bundle = read_bundle(Path(__file__).resolve().parents[1] / 'tests/fixtures/result-v1')
    result, problems, routes = project_bundle(bundle)
    return build_fast_insert_payloads(result, problems, routes), bundle['manifest']


def _count(engine):
    with engine.connect() as connection:
        return connection.execute(text('SELECT count(*) FROM stops_matched')).scalar()


def test_publication_and_failed_staging_preserve_active_snapshot(postgres):
    payload, manifest = _example()
    publish_snapshot(postgres, payload, _write_rows, manifest=manifest)
    assert _count(postgres) == 3
    with postgres.connect() as connection:
        assert connection.execute(text('SELECT run_id FROM dataset_publication')).scalar() == manifest['run_id']
        assert connection.execute(text('SELECT count(*) FROM problems')).scalar() == 2
        assert connection.execute(text('SELECT ST_SRID(geom) FROM stops_matched LIMIT 1')).scalar() == 4326

    def fail_after_rows(session, payload):
        _write_rows(session, payload)
        raise RuntimeError('simulated load failure')

    with pytest.raises(RuntimeError, match='simulated load'):
        publish_snapshot(postgres, payload, fail_after_rows, manifest={'run_id': 'failed'})
    assert _count(postgres) == 3
    with postgres.connect() as connection:
        assert connection.execute(text('SELECT run_id FROM dataset_publication')).scalar() == manifest['run_id']
        assert not connection.execute(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'import_%' OR nspname LIKE 'previous_%'")).all()


def test_readers_see_previous_snapshot_while_new_one_is_staged(postgres):
    payload, manifest = _example()
    publish_snapshot(postgres, payload, _write_rows, manifest=manifest)
    seen = []

    def observe_while_staging(session, data):
        _write_rows(session, data)
        seen.append(_count(postgres))

    publish_snapshot(postgres, payload, observe_while_staging, manifest={**manifest, 'run_id': 'second'})
    assert seen == [3]
    assert _count(postgres) == 3


def test_publication_lock_timeout_keeps_old_run(postgres):
    payload, manifest = _example()
    publish_snapshot(postgres, payload, _write_rows, manifest=manifest)
    with postgres.connect() as reader, reader.begin():
        reader.execute(text('SELECT count(*) FROM stops_matched')).scalar()
        with pytest.raises(Exception) as error:
            publish_snapshot(postgres, payload, _write_rows, manifest={**manifest, 'run_id': 'blocked'})
        assert getattr(getattr(error.value, 'orig', None), 'sqlstate', None) == '55P03'
    assert _count(postgres) == 3
    with postgres.connect() as connection:
        assert connection.execute(text('SELECT run_id FROM dataset_publication')).scalar() == manifest['run_id']


def test_long_source_identifiers_survive_migration_and_atomic_import_with_foreign_keys(postgres):
    import importlib
    import json
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from backend.importing.bundle import validate_records

    migration = importlib.import_module('migrations.versions.20260911_000006_external_source_identifiers')
    with postgres.begin() as connection:
        # Execute the additive migration against the previous column types.
        # The empty snapshot can safely be downgraded without shortening data.
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
        for table, columns in migration.COLUMNS.items():
            types = dict(connection.execute(text('''
                SELECT column_name, data_type FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table
            '''), {'table': table}).all())
            assert all(types[column] == 'text' for column in columns)

    bundle = read_bundle(Path(__file__).resolve().parents[1] / 'tests/fixtures/result-v1')
    old_key = bundle['source_stops'][0]['key']
    raw_stop_id = 'https://transit.example/stops/' + 'platform-segment/' * 28
    source_key = 'demo:' + raw_stop_id
    route_id = 'https://transit.example/routes/' + 'route-segment/' * 28
    agency_id = 'https://transit.example/agencies/' + 'agency-segment/' * 30
    station_ref = 'https://transit.example/stations/' + 'station-segment/' * 20
    assert len(raw_stop_id) > 255 and len(route_id) > 255
    bundle['source_stops'][0].update(source_id=raw_stop_id, key=source_key, station_ref=station_ref)
    for match in bundle['matches']:
        if match['source_key'] == old_key:
            match['source_key'] = source_key
    bundle['groups'].append({'side': 'source', 'key': source_key, 'kind': 'duplicate',
                             'members': [source_key, 'demo:b']})
    route_payload = {
        'atlas_line_families': [{'atlas_line_id': route_id, 'route_id_normalized': route_id, 'agency_id': agency_id}],
        'line_families': [{'id': 1, 'source': 'atlas', 'source_family_id': route_id,
                           'atlas_line_id': route_id, 'gtfs_route_id': route_id,
                           'display_route_id': route_id, 'normalized_route_id': route_id,
                           'public_name': route_id, 'operator': agency_id}],
        'itineraries': [{'id': 1, 'source': 'atlas', 'line_family_id': 1,
                        'source_itinerary_id': route_id + '/trip', 'display_name': route_id + '/trip'}],
        'stop_calls': [{'id': 1, 'itinerary_id': 1, 'stop_sequence': 1, 'source_stop_id': raw_stop_id,
                        'source_sloid': source_key, 'canonical_stop_key': source_key, 'uic_ref': station_ref,
                        'source_sloid_variants': json.dumps([source_key]), 'stop_label': raw_stop_id}],
    }
    bundle['routes'] = [{'kind': kind, 'value': value} for kind, value in route_payload.items()]
    bundle['extensions'].extend([
        {'kind': 'gtfs_stops', 'value': [{'stop_id': raw_stop_id, 'original_stop_id': raw_stop_id,
                                        'parent_station': raw_stop_id, 'stop_lat': 47.0, 'stop_lon': 8.0, 'uic_number': '123'}]},
        {'kind': 'gtfs_atlas_state', 'value': [{'stop_id': raw_stop_id, 'resolved_sloid': source_key,
                                              'resolution_method': 'original_stop_id', 'confidence': 1.0}]},
    ])
    validate_records(bundle)
    payload = build_fast_insert_payloads(*project_bundle(bundle))
    publish_snapshot(postgres, payload, _write_rows, manifest=bundle['manifest'])

    with postgres.connect() as connection:
        row = connection.execute(text('''
            SELECT a.sloid, a.uic_ref, m.sloid, g.stop_id, g.resolved_sloid,
                   c.source_stop_id, c.source_sloid, c.canonical_stop_key, c.uic_ref,
                   l.atlas_line_id, l.source_family_id, i.source_itinerary_id,
                   l.public_name, l.operator, i.display_name, c.stop_label
            FROM atlas_stops a JOIN stops_matched m ON m.sloid = a.sloid
            JOIN gtfs_stop_identity_resolution g ON g.resolved_sloid = a.sloid
            JOIN stop_calls c ON c.source_sloid = a.sloid
            JOIN itineraries i ON i.id = c.itinerary_id
            JOIN line_families l ON l.id = i.line_family_id
            WHERE a.sloid = :key
        '''), {'key': source_key}).one()
        assert tuple(row) == (source_key, station_ref, source_key, raw_stop_id, source_key,
                              raw_stop_id, source_key, source_key, station_ref,
                              route_id, route_id, route_id + '/trip',
                              route_id, agency_id, route_id + '/trip', raw_stop_id)
        assert connection.execute(text("SELECT representative_sloid FROM atlas_stops WHERE sloid = 'demo:b'")).scalar() == source_key
        assert connection.execute(text('SELECT original_stop_id FROM gtfs_stops_raw')).scalar() == raw_stop_id

    with postgres.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        with pytest.raises(RuntimeError, match='Cannot downgrade'):
            migration.downgrade()


def test_copy_matches_insert_json_geometry_defaults_indexes_and_sequences(postgres, monkeypatch):
    payload, manifest = _example()
    payload['osm_nodes'][0]['duplicate_group_node_ids'] = ['quote"', 'tab\t', 'line\nbreak', 'back\\slash', 'é']
    payload['stops_matched'][0]['matching_notes'] = 'quote"\tline\nbreak\\é'
    payload['stops_matched'][1]['geom'] = None
    snapshots = []
    for method in ('insert', 'copy'):
        monkeypatch.setenv('DB_IMPORT_METHOD', method)
        publish_snapshot(postgres, payload, _write_rows, manifest=manifest)
        with postgres.connect() as connection:
            snapshots.append({table.name: connection.execute(text(
                f'SELECT row_to_json(t)::text FROM "{table.name}" t ORDER BY row_to_json(t)::text')).scalars().all()
                for table in db.Model.metadata.sorted_tables})
            for table in db.Model.metadata.sorted_tables:
                expected = {index.name for index in table.indexes}
                actual = set(connection.execute(text('SELECT indexname FROM pg_indexes WHERE schemaname=\'public\' AND tablename=:name'),
                                                {'name': table.name}).scalars())
                assert expected <= actual
            assert connection.execute(text('SELECT ST_SRID(geom) FROM stops_matched WHERE geom IS NOT NULL LIMIT 1')).scalar() == 4326
            maximum = connection.execute(text('SELECT max(id) FROM stops_matched')).scalar()
            following = connection.execute(text("SELECT nextval(pg_get_serial_sequence('stops_matched', 'id'))")).scalar()
            assert following == maximum + 1
    assert snapshots[0] == snapshots[1]


def test_failed_secondary_index_keeps_previous_snapshot(postgres, monkeypatch):
    from sqlalchemy import Index
    payload, manifest = _example()
    publish_snapshot(postgres, payload, _write_rows, manifest=manifest)
    monkeypatch.setattr(Index, 'create', lambda *args, **kw: (_ for _ in ()).throw(RuntimeError('index failed')))
    with pytest.raises(RuntimeError, match='index failed'):
        publish_snapshot(postgres, payload, _write_rows, manifest={**manifest, 'run_id': 'failed-index'})
    assert _count(postgres) == 3
    with postgres.connect() as connection:
        assert connection.execute(text('SELECT run_id FROM dataset_publication')).scalar() == manifest['run_id']
        assert not connection.execute(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'import_%' OR nspname LIKE 'previous_%'")).all()
