from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import text

from backend.extensions import db
from backend.models import StopCall
from backend.services import gtfs_stop_id_sloid as service
from backend.services import transport_routes


def test_gtfs_map_limit_uses_one_combined_budget_and_supports_full_detail():
    assert service._resolve_map_limits(14, 1800) == (900, 900)
    assert service._resolve_map_limits(15, 'all') == (None, None)
    assert service._resolve_map_limits(10, None) == (
        service.GTFS_STOP_ID_SLOID_OVERVIEW_LIMIT,
        service.GTFS_STOP_ID_SLOID_OVERVIEW_LIMIT,
    )
    assert service._resolve_map_limits(16, None) == (
        service.GTFS_STOP_ID_SLOID_DETAIL_LIMIT,
        service.GTFS_STOP_ID_SLOID_DETAIL_LIMIT,
    )


def test_gtfs_popup_routes_union_direct_and_matched_sloid_routes(monkeypatch):
    monkeypatch.setattr(
        service,
        'get_atlas_routes_for_gtfs_stop_ids',
        lambda _stop_ids: {
            'gtfs-1': [
                {'route_id': 'route-b', 'direction_id': '1', 'route_name_short': None},
            ]
        },
    )
    monkeypatch.setattr(
        service,
        'get_atlas_routes_for_sloids',
        lambda _sloids: {
            'sloid-1': [
                {'route_id': 'route-a', 'direction_id': '0', 'route_name_short': 'A'},
                {'route_id': 'route-b', 'direction_id': '1', 'route_name_short': 'B'},
            ]
        },
    )

    routes, routes_by_sloid = service._build_gtfs_popup_route_context(
        'gtfs-1',
        ['sloid-1'],
    )

    assert [(route['route_id'], route['direction_id']) for route in routes] == [
        ('route-a', '0'),
        ('route-b', '1'),
    ]
    assert routes[1]['route_name_short'] == 'B'
    assert routes_by_sloid['sloid-1'][0]['route_id'] == 'route-a'


def test_typed_searches_also_find_exact_gtfs_stop_ids_with_recognized_syntax(app):
    """A GTFS stop_id may itself look like a SLOID or UIC."""
    with app.app_context():
        for statement in (
            '''
            CREATE TABLE gtfs_stops_raw (
                stop_id TEXT PRIMARY KEY,
                stop_name TEXT,
                stop_lat FLOAT NOT NULL,
                stop_lon FLOAT NOT NULL,
                uic_number TEXT NOT NULL,
                local_ref TEXT,
                normalized_local_ref TEXT
            )
            ''',
            '''
            CREATE TABLE atlas_stops (
                sloid TEXT PRIMARY KEY,
                uic_ref TEXT,
                atlas_designation TEXT,
                atlas_designation_official TEXT,
                atlas_business_org_abbr TEXT,
                duplicate_group_sloids TEXT
            )
            ''',
            '''
            CREATE TABLE stops_matched (
                id INTEGER PRIMARY KEY,
                sloid TEXT,
                stop_type TEXT,
                atlas_lat FLOAT,
                atlas_lon FLOAT
            )
            ''',
            '''
            CREATE TABLE gtfs_stop_identity_resolution (
                id INTEGER PRIMARY KEY,
                stop_id TEXT NOT NULL,
                resolved_sloid TEXT,
                resolution_method TEXT NOT NULL,
                distance_m FLOAT,
                gtfs_stop_lat FLOAT,
                gtfs_stop_lon FLOAT,
                atlas_lat FLOAT,
                atlas_lon FLOAT
            )
            ''',
        ):
            db.session.execute(text(statement))

        identifier = 'ch:1:sloid:10'
        db.session.execute(
            text('''
                INSERT INTO gtfs_stops_raw
                    (stop_id, stop_name, stop_lat, stop_lon, uic_number)
                VALUES (:stop_id, 'Basel parent', 47.55, 7.59, '8500010')
            '''),
            {'stop_id': identifier},
        )
        db.session.execute(text('''
            INSERT INTO gtfs_stops_raw
                (stop_id, stop_name, stop_lat, stop_lon, uic_number)
            VALUES ('8503000', 'Numeric stop id', 47.38, 8.54, '9999999')
        '''))
        db.session.commit()

        targets = service.find_gtfs_stop_id_sloid_targets('sloid', identifier)
        numeric_targets = service.find_gtfs_stop_id_sloid_targets('uic', '8503000')
        payload = service.build_gtfs_stop_id_sloid_map_payload(
            47.0,
            7.0,
            48.0,
            8.0,
            16,
            'sloid',
            identifier,
        )

        assert [(target['entity_type'], target['identifier']) for target in targets] == [
            ('gtfs', identifier),
        ]
        assert [(target['entity_type'], target['identifier']) for target in numeric_targets] == [
            ('gtfs', '8503000'),
        ]
        assert [stop['stop_id'] for stop in payload['gtfs_stops']] == [identifier]


def test_optional_route_lookup_rolls_back_before_returning_empty_routes(app, monkeypatch):
    session = SimpleNamespace(
        query=Mock(side_effect=RuntimeError('route table is unavailable')),
        rollback=Mock(),
    )
    monkeypatch.setattr(transport_routes, 'db', SimpleNamespace(session=session))

    with app.app_context():
        result = transport_routes._get_atlas_routes_for_stop_values(
            ['ch:1:sloid:1'],
            StopCall.source_sloid,
        )

    assert result == {'ch:1:sloid:1': []}
    session.rollback.assert_called_once_with()
