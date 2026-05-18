from backend.extensions import db
from backend.models import Itinerary, ItineraryMatch, LineFamily, LineFamilyMatch
from backend.services.stats_export import compute_route_route_stats


def test_compute_route_route_stats_uses_line_family_tables(app):
    with app.app_context():
        engine = db.engine

        LineFamily.__table__.create(bind=engine, checkfirst=True)
        Itinerary.__table__.create(bind=engine, checkfirst=True)
        LineFamilyMatch.__table__.create(bind=engine, checkfirst=True)
        ItineraryMatch.__table__.create(bind=engine, checkfirst=True)

        db.session.add_all([
            LineFamily(id=1, source='atlas', source_family_id='A1', display_route_id='A1', gtfs_route_id='A1'),
            LineFamily(id=2, source='atlas', source_family_id='A2', display_route_id='A2', gtfs_route_id='A2'),
            LineFamily(id=10, source='osm', source_family_id='O1', display_route_id='O1', representative_relation_id='rel-1'),
            LineFamily(id=11, source='osm', source_family_id='O2', display_route_id='O2', representative_relation_id='rel-2'),
            LineFamily(id=12, source='osm', source_family_id='O3', display_route_id='O3', representative_relation_id='rel-3'),
        ])
        db.session.add_all([
            Itinerary(id=100, source='atlas', line_family_id=1, source_itinerary_id='A1:0', direction_id='0', trip_count=20),
            Itinerary(id=101, source='atlas', line_family_id=1, source_itinerary_id='A1:1', direction_id='1', trip_count=10),
            Itinerary(id=102, source='atlas', line_family_id=2, source_itinerary_id='A2:0', direction_id='0', trip_count=5),
            Itinerary(id=200, source='osm', line_family_id=10, source_itinerary_id='O1:0', direction_id='0', trip_count=1),
            Itinerary(id=201, source='osm', line_family_id=10, source_itinerary_id='O1:1', direction_id='1', trip_count=1),
            Itinerary(id=202, source='osm', line_family_id=11, source_itinerary_id='O2:0', direction_id='0', trip_count=1),
            Itinerary(id=203, source='osm', line_family_id=12, source_itinerary_id='O3:0', direction_id='0', trip_count=1),
        ])
        db.session.add_all([
            LineFamilyMatch(id=1000, atlas_line_family_id=1, osm_line_family_id=10),
            LineFamilyMatch(id=1001, atlas_line_family_id=2, osm_line_family_id=11),
        ])
        db.session.add_all([
            ItineraryMatch(id=2000, line_family_match_id=1000, atlas_itinerary_id=100, osm_itinerary_id=200),
            ItineraryMatch(id=2001, line_family_match_id=1001, atlas_itinerary_id=102, osm_itinerary_id=202),
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
        assert stats['atlas_itineraries_total'] == 3
        assert stats['osm_itineraries_total'] == 4
        assert stats['itinerary_links_total'] == 2
        assert stats['atlas_routes_without_link'] == 0
        assert stats['osm_routes_without_link'] == 1
        assert stats['atlas_link_coverage_percent'] == 100.0
        assert stats['osm_link_coverage_percent'] == 66.7
        assert stats['atlas_itineraries_linked'] == 2
        assert stats['osm_itineraries_linked'] == 2
        assert stats['atlas_itinerary_link_coverage_percent'] == 66.7
        assert stats['osm_itinerary_link_coverage_percent'] == 50.0
        assert stats['variant_density']['atlas_itineraries_per_family'] == {'mean': 1.5, 'median': 1.5}
        assert stats['variant_density']['osm_itineraries_per_family'] == {'mean': 1.33, 'median': 1.0}
        assert stats['variant_density']['atlas_trip_count_per_itinerary'] == {'mean': 11.67, 'median': 10.0}
        assert stats['matched_family_variant_gap'] == {
            'mean': 0.0,
            'median': 0.0,
            'atlas_has_more_count': 0,
            'same_count': 2,
            'osm_has_more_count': 0,
        }

        db.session.query(ItineraryMatch).delete()
        db.session.query(LineFamilyMatch).delete()
        db.session.query(Itinerary).delete()
        db.session.query(LineFamily).delete()
        db.session.commit()
