"""Duplicate problems on the Problems page: grouped by side, in priority order."""
from types import SimpleNamespace

from backend.blueprints.problems import duplicate_groups


def duplicate(priority, sloid=None, osm_node_id=None, uic_ref='8500', designation=None, local_ref=None, lat=47.0):
    stop = SimpleNamespace(
        sloid=sloid,
        osm_node_id=osm_node_id,
        atlas_stop_details=SimpleNamespace(uic_ref=uic_ref, atlas_designation=designation) if sloid else None,
        osm_node_details=SimpleNamespace(osm_uic_ref=uic_ref, osm_local_ref=local_ref) if osm_node_id else None,
        atlas_lat=lat if sloid else None, atlas_lon=8.0 if sloid else None,
        osm_lat=lat if osm_node_id else None, osm_lon=8.0 if osm_node_id else None,
    )
    return SimpleNamespace(priority=priority, stop=stop)


def test_atlas_groups_come_before_osm_groups_and_single_stops_form_none():
    problems = [
        duplicate(3, osm_node_id='1', local_ref='B', lat=46.0),
        duplicate(3, osm_node_id='2', local_ref='b', lat=48.0),
        duplicate(2, sloid='ch:1:sloid:9', designation='A '),
        duplicate(2, sloid='ch:1:sloid:8', designation='a'),
        duplicate(2, sloid='ch:1:sloid:7', designation='C'),
        # An OSM element with an ATLAS-side priority belongs to no group.
        duplicate(2, osm_node_id='3', local_ref='b'),
    ]

    groups = duplicate_groups(problems, lambda problem: problem.stop.sloid or problem.stop.osm_node_id)

    assert [(group['id'], group['priority'], group['members']) for group in groups] == [
        ('dup_atlas_8500_a', 2, ['ch:1:sloid:9', 'ch:1:sloid:8']),
        ('dup_osm_8500_b', 3, ['1', '2']),
    ]
    assert groups[0]['sloid'] == 'ch:1:sloid:8'
    assert groups[1]['osm_local_ref'] == 'b'
    assert groups[1]['osm_lat'] == groups[1]['atlas_lat'] == 47.0
