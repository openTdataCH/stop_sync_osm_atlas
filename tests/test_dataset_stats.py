from backend.models import (
    AtlasStop, GtfsStopIdentityResolution, Itinerary, ItineraryMatch, LineFamily, LineFamilyMatch,
    OsmNode, OsmRouteRelation, OsmStop, OsmStopMember, StopCall, StopsMatched,
)
from backend.services.dataset_stats import (
    compute_atlas_stop_stats, compute_gtfs_stats, compute_osm_route_stats, compute_osm_stop_stats,
    compute_route_link_stats, gtfs_route_mode, osm_route_mode,
)


def test_modes_fold_trolleybus_into_bus_and_flag_non_public_transport():
    assert gtfs_route_mode('700') == gtfs_route_mode(3) == osm_route_mode('trolleybus') == 'bus'
    assert gtfs_route_mode('1300') == osm_route_mode('aerialway') == 'aerialway'
    assert osm_route_mode('light_rail') == gtfs_route_mode(900) == 'tram'
    assert osm_route_mode('piste') == 'not_public_transport'
    assert osm_route_mode('') == gtfs_route_mode(None) == 'other'


def test_route_links_report_coverage_and_why_lines_stay_unlinked(sqlite_tables):
    session = sqlite_tables(LineFamily, Itinerary, LineFamilyMatch, ItineraryMatch)
    session.add_all([
        LineFamily(id=1, source='gtfs', source_family_id='A1', route_type='700', gtfs_route_id='r1'),
        LineFamily(id=2, source='gtfs', source_family_id='A2', route_type='700', gtfs_route_id='r2'),
        LineFamily(id=3, source='gtfs', source_family_id='A3', route_type='106', gtfs_route_id='r3'),
        LineFamily(id=4, source='gtfs', source_family_id='A4', route_type='700', gtfs_route_id='r4-new',
                   normalized_route_id='r4'),
        LineFamily(id=5, source='gtfs', source_family_id='A5', route_type='700', gtfs_route_id='r5'),
        LineFamily(id=10, source='osm', source_family_id='O1', route_type='bus', gtfs_route_id='r1'),
        LineFamily(id=11, source='osm', source_family_id='O2', route_type='trolleybus', gtfs_route_id='r2'),
        LineFamily(id=12, source='osm', source_family_id='O3', route_type='bus', gtfs_route_id='r1'),
        LineFamily(id=13, source='osm', source_family_id='O4', route_type='bus', gtfs_route_id='old'),
        LineFamily(id=14, source='osm', source_family_id='O5', route_type='bus', normalized_route_id='5'),
        LineFamily(id=17, source='osm', source_family_id='O8', route_type='bus', gtfs_route_id='r8;r9'),
        LineFamily(id=15, source='osm', source_family_id='O6', route_type='bus', is_non_gtfs=True),
        LineFamily(id=16, source='osm', source_family_id='O7', route_type='piste'),
        # The engine refused this ID of another year: its line has another number or no shared stop.
        LineFamily(id=18, source='osm', source_family_id='O9', route_type='bus', gtfs_route_id='r4-old',
                   normalized_route_id='r4'),
        LineFamily(id=19, source='osm', source_family_id='O10', route_type='bus', normalized_route_id='7'),
    ])
    session.add_all([
        Itinerary(id=100, source='gtfs', line_family_id=1, source_itinerary_id='a', direction_id='0', trip_count=20),
        Itinerary(id=101, source='gtfs', line_family_id=1, source_itinerary_id='b', direction_id='1', trip_count=10),
        Itinerary(id=102, source='gtfs', line_family_id=2, source_itinerary_id='c', direction_id='0', trip_count=5),
        Itinerary(id=200, source='osm', line_family_id=10, source_itinerary_id='1', direction_id='0'),
        Itinerary(id=201, source='osm', line_family_id=10, source_itinerary_id='2'),
        Itinerary(id=202, source='osm', line_family_id=11, source_itinerary_id='3', direction_id='0'),
    ])
    session.add_all([
        LineFamilyMatch(id=1000, gtfs_line_family_id=1, osm_line_family_id=10, match_method='exact_gtfs_route_id'),
        LineFamilyMatch(id=1001, gtfs_line_family_id=2, osm_line_family_id=11, match_method='normalized_gtfs_route_id'),
        LineFamilyMatch(id=1002, gtfs_line_family_id=5, osm_line_family_id=19, match_method='line_number_and_stops'),
        # A line can have several links: GTFS line 5 has two OSM lines, OSM line 10 two GTFS lines.
        LineFamilyMatch(id=1003, gtfs_line_family_id=5, osm_line_family_id=10, match_method='line_number_and_stops'),
        ItineraryMatch(id=2000, line_family_match_id=1000, gtfs_itinerary_id=100, osm_itinerary_id=200),
    ])
    session.commit()

    stats = compute_route_link_stats(session)

    assert stats['line_links'] == 4
    assert stats['gtfs_lines'] == {'total': 5, 'linked': 3, 'with_several_links': 1, 'unlinked': {
        'no_osm_line': 1, 'osm_line_not_confirmed': 1}}
    assert stats['osm_lines']['public_transport'] == 9
    assert (stats['osm_lines']['linked'], stats['osm_lines']['with_several_links']) == (3, 1)
    # A normalized ID taken from the ref alone does not count as a route ID.
    assert stats['osm_lines']['unlinked'] == {
        'not_public_transport': 1, 'non_gtfs': 1, 'no_route_id': 1, 'several_route_ids': 1,
        'route_id_not_in_gtfs': 1, 'gtfs_line_already_linked': 1, 'route_id_not_confirmed': 1,
    }
    bus = next(row for row in stats['by_mode'] if row['mode'] == 'bus')
    assert bus == {'mode': 'bus', 'gtfs_lines': 4, 'gtfs_linked': 3, 'osm_lines': 9, 'osm_linked': 3}
    assert stats['by_match_method'] == {
        'line_number_and_stops': 2, 'exact_gtfs_route_id': 1, 'normalized_gtfs_route_id': 1}
    assert stats['itineraries'] == {
        'links': 1, 'gtfs_in_linked_lines': 3, 'gtfs_linked': 1,
        'osm_in_linked_lines': 3, 'osm_linked': 1, 'osm_in_linked_lines_without_direction': 1,
    }
    # One gap per link: GTFS line 5 has no itinerary, OSM line 10 has two.
    assert stats['linked_line_itinerary_gap'] == {
        'mean': -0.5, 'median': 0.0, 'gtfs_has_more': 0, 'same': 3, 'osm_has_more': 1,
    }


def test_osm_stop_stats_count_elements_units_groups_tags_and_route_service(sqlite_tables):
    session = sqlite_tables(OsmNode, OsmStop, OsmStopMember, StopsMatched, OsmRouteRelation,
                            LineFamily, Itinerary, StopCall)
    session.add_all([
        OsmNode(osm_node_id='1', osm_node_type='platform', osm_tags={'name': 'A', 'shelter': 'yes', 'ref:sloid': 's1'}),
        OsmNode(osm_node_id='2', osm_node_type='stop_position', osm_tags={'name': 'A', 'uic_ref': '85'}),
        OsmNode(osm_node_id='way_3', osm_node_type='platform', osm_tags={'name': ''}),
        OsmNode(osm_node_id='4', osm_node_type='stop_position', osm_lifecycle='disused', osm_tags={}),
        OsmStop(id=1, stop_kind='pair', group_kind='ptv2_pair_uic_ref', representative_node_id='1'),
        OsmStop(id=2, stop_kind='single', representative_node_id='way_3'),
        OsmStopMember(osm_stop_id=1, node_id='1', member_role='pair_a'),
        OsmStopMember(osm_stop_id=1, node_id='2', member_role='pair_b'),
        OsmStopMember(osm_stop_id=2, node_id='way_3', member_role='single'),
        StopsMatched(id=1, sloid='s1', stop_type='matched', osm_node_id='1', match_type='sloid_identifier'),
        StopsMatched(id=2, sloid='s1', stop_type='matched', osm_node_id='2'),
        StopsMatched(id=3, stop_type='osm_unmatched', osm_node_id='way_3'),
        OsmRouteRelation(relation_id='r1', route='bus'),
        OsmRouteRelation(relation_id='r2', route='piste'),
        LineFamily(id=1, source='osm', source_family_id='f'),
        Itinerary(id=1, source='osm', line_family_id=1, source_itinerary_id='r1'),
        Itinerary(id=2, source='osm', line_family_id=1, source_itinerary_id='r2'),
        StopCall(id=1, itinerary_id=1, stop_sequence=0, source_node_id='2'),
        StopCall(id=2, itinerary_id=2, stop_sequence=0, source_node_id='way_3'),
    ])
    session.commit()

    stats = compute_osm_stop_stats(session)

    elements = stats['elements']
    assert (elements['total'], elements['ways'], elements['matched']) == (3, 1, 2)
    assert elements['retired'] == {'total': 1, 'by_lifecycle': {'disused': 1}}
    platform = next(row for row in elements['by_type'] if row['type'] == 'platform')
    assert platform == {'type': 'platform', 'elements': 2, 'ways': 1, 'matched': 1}
    # Only the bus relation counts as route service; the piste one does not.
    assert stats['stop_units'] == {
        'total': 2, 'matched': 1, 'served_by_routes': 1,
        'by_kind': {'single': {'units': 1, 'elements': 1, 'matched': 0},
                    'pair': {'units': 1, 'elements': 2, 'matched': 1},
                    'two_sided_stop': {'units': 0, 'elements': 0, 'matched': 0}},
    }
    assert stats['groups']['by_kind'] == [{'group_kind': 'ptv2_pair_uic_ref', 'units': 1, 'all_matched': 1,
                                           'partly_matched': 0, 'none_matched': 0}]
    keys = {row['key']: row for group in stats['tags']['groups'] for row in group['keys']}
    assert keys['name'] == {'key': 'name', 'elements': 2, 'platforms': 1, 'stop_positions': 1}
    assert keys['shelter']['platforms'] == 1
    # One element names its platform by SLOID and is linked by it; the matched
    # stop position does not carry one yet.
    assert stats['identifiers'] == {'elements': 1, 'ways': 0, 'linked_elements': 1,
                                    'linked_platforms': 1, 'matched_without': 1}


def test_osm_route_stats_leave_non_public_transport_out(sqlite_tables):
    session = sqlite_tables(OsmRouteRelation, LineFamily, Itinerary, StopCall)
    session.add_all([
        OsmRouteRelation(relation_id='r1', route='bus', route_master_id='m', public_transport_version='2',
                         gtfs_route_id='g1', ref='1'),
        OsmRouteRelation(relation_id='r2', route='bus', ref=''),
        OsmRouteRelation(relation_id='r3', route='mtb', ref='x'),
        # No route tag: the relation takes the value of its route master.
        OsmRouteRelation(relation_id='r4', route_master_id='m'),
        LineFamily(id=1, source='osm', source_family_id='m', family_origin='route_master', route_type='bus',
                   route_master_id='m'),
        LineFamily(id=2, source='osm', source_family_id='k', family_origin='synthetic_ref_operator', route_type='mtb'),
        Itinerary(id=1, source='osm', line_family_id=1, source_itinerary_id='r1', direction_id='0'),
        Itinerary(id=2, source='osm', line_family_id=1, source_itinerary_id='r2'),
        Itinerary(id=3, source='osm', line_family_id=2, source_itinerary_id='r3', direction_id='1'),
        StopCall(id=1, itinerary_id=1, stop_sequence=0, source_sloid='s1'),
        StopCall(id=2, itinerary_id=1, stop_sequence=1),
        StopCall(id=3, itinerary_id=3, stop_sequence=0, source_sloid='s2'),
    ])
    session.commit()

    stats = compute_osm_route_stats(session)

    relations = stats['relations']
    assert (relations['total'], relations['public_transport'], relations['in_route_master'], relations['ptv2']) == (4, 3, 2, 1)
    assert relations['by_mode'] == {'bus': 3, 'not_public_transport': 1}
    assert relations['not_public_transport_by_route'] == {'mtb': 1}
    tags = {row['key']: row['count'] for row in relations['tags']}
    assert tags['ref'] == 1 and tags['gtfs:route_id'] == 1
    assert stats['lines']['public_transport'] == 1
    assert stats['lines']['relations_by_origin'] == {'route_master': 2, 'synthetic_ref_operator': 1}
    assert stats['itineraries'] == {'total': 2, 'with_direction': 1, 'stop_calls': 2, 'resolved_stop_calls': 1}


def test_atlas_duplicates_and_gtfs_stats_count_sloids_and_used_stop_ids(sqlite_tables):
    session = sqlite_tables(AtlasStop, StopsMatched, GtfsStopIdentityResolution, LineFamily, Itinerary, StopCall)
    session.add_all([
        AtlasStop(sloid='s1', duplicate_group_sloids=['s1', 's2']),
        AtlasStop(sloid='s2', duplicate_group_sloids=['s1', 's2']),
        AtlasStop(sloid='s3', duplicate_group_sloids=None),
        # One platform matched twice must count once.
        StopsMatched(id=1, sloid='s1', stop_type='matched', osm_node_id='1'),
        StopsMatched(id=2, sloid='s1', stop_type='matched', osm_node_id='2'),
        StopsMatched(id=3, sloid='s2', stop_type='atlas_unmatched'),
        GtfsStopIdentityResolution(id=1, stop_id='p1', identity_level='platform', resolved_sloid='s1',
                                   resolution_method='original_stop_id'),
        GtfsStopIdentityResolution(id=2, stop_id='c1', identity_level='child_stop', resolution_method='unmatched'),
        GtfsStopIdentityResolution(id=3, stop_id='st', identity_level='station', resolved_sloid='s3',
                                   resolution_method='unique_number'),
        LineFamily(id=1, source='gtfs', source_family_id='r', route_type='700'),
        Itinerary(id=1, source='gtfs', line_family_id=1, source_itinerary_id='i', direction_id='0', trip_count=4),
        StopCall(id=1, itinerary_id=1, stop_sequence=0, source_stop_id='p1', source_sloid='s1'),
        StopCall(id=2, itinerary_id=1, stop_sequence=1, source_stop_id='c1'),
    ])
    session.commit()

    atlas = compute_atlas_stop_stats(session)
    assert atlas == {'platforms': 3, 'matched': 1, 'duplicates': {
        'groups': 1, 'sloids': 2, 'matched_sloids': 1, 'unmatched_sloids': 1}}

    gtfs = compute_gtfs_stats(session)
    stops = gtfs['stops']
    assert (stops['total'], stops['resolved'], stops['used'], stops['used_resolved']) == (3, 2, 2, 1)
    assert [row['level'] for row in stops['by_level']] == ['platform', 'child_stop', 'station']
    assert gtfs['atlas_platforms'] == {'total': 3, 'referenced': 2}
    assert gtfs['routes']['by_mode'] == {'bus': 1}
    assert (gtfs['routes']['stop_calls'], gtfs['routes']['resolved_stop_calls']) == (2, 1)
