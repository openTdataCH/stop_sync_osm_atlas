from backend.extensions import db
from backend.models import RouteAtlasStops, RouteOsmStops, RoutesMatched
from backend.services.stats_export import compute_route_route_stats


def test_compute_route_route_stats_uses_route_tables(app):
    with app.app_context():
        engine = db.engine

        RouteAtlasStops.__table__.create(bind=engine, checkfirst=True)
        RouteOsmStops.__table__.create(bind=engine, checkfirst=True)
        RoutesMatched.__table__.create(bind=engine, checkfirst=True)

        db.session.add_all([
            RouteAtlasStops(atlas_route_id='A1', direction_id='0', sloid='s1', stop_sequence=0),
            RouteAtlasStops(atlas_route_id='A1', direction_id='1', sloid='s2', stop_sequence=1),
            RouteAtlasStops(atlas_route_id='A2', direction_id='0', sloid='s3', stop_sequence=0),
        ])
        db.session.add_all([
            RouteOsmStops(osm_route_id='O1', direction_id='0', osm_node_id='n1', stop_sequence=0),
            RouteOsmStops(osm_route_id='O1', direction_id='1', osm_node_id='n2', stop_sequence=1),
            RouteOsmStops(osm_route_id='O2', direction_id='0', osm_node_id='n3', stop_sequence=0),
            RouteOsmStops(osm_route_id='O3', direction_id='0', osm_node_id='n4', stop_sequence=0),
        ])
        db.session.add_all([
            RoutesMatched(atlas_route_id='A1', osm_route_id='O1', match_type='matched'),
            RoutesMatched(atlas_route_id='A2', osm_route_id='O2', match_type='matched'),
        ])
        db.session.commit()

        stats = compute_route_route_stats(db.session)

        assert stats['total_links'] == 2
        assert stats['atlas_routes_linked'] == 2
        assert stats['osm_routes_linked'] == 2
        assert stats['atlas_route_ids_total'] == 2
        assert stats['osm_route_ids_total'] == 3
        assert stats['atlas_route_directions_total'] == 3
        assert stats['osm_route_directions_total'] == 4
        assert stats['atlas_routes_without_link'] == 0
        assert stats['osm_routes_without_link'] == 1
        assert stats['atlas_link_coverage_percent'] == 100.0
        assert stats['osm_link_coverage_percent'] == 66.7

        db.session.query(RoutesMatched).delete()
        db.session.query(RouteAtlasStops).delete()
        db.session.query(RouteOsmStops).delete()
        db.session.commit()
