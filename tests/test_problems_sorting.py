"""Duplicate problems on the Problems page: grouped by side, in priority order."""
from types import SimpleNamespace

from backend.blueprints.problems import duplicate_groups


def duplicate(priority, sloid=None, osm_node_id=None, uic_ref='8500', designation=None, local_ref=None, lat=47.0,
              group=None):
    stop = SimpleNamespace(
        sloid=sloid,
        osm_node_id=osm_node_id,
        atlas_stop_details=SimpleNamespace(
            uic_ref=uic_ref, atlas_designation=designation, duplicate_group_sloids=group) if sloid else None,
        osm_node_details=SimpleNamespace(osm_uic_ref=uic_ref, osm_local_ref=local_ref) if osm_node_id else None,
        atlas_lat=lat if sloid else None, atlas_lon=8.0 if sloid else None,
        osm_lat=lat if osm_node_id else None, osm_lon=8.0 if osm_node_id else None,
    )
    return SimpleNamespace(priority=priority, stop=stop)


def member_ids(problem):
    return problem.stop.sloid or problem.stop.osm_node_id


def test_atlas_groups_come_before_osm_groups_and_single_stops_form_none():
    pair = ['ch:1:sloid:8', 'ch:1:sloid:9']
    problems = [
        duplicate(3, osm_node_id='1', local_ref='B', lat=46.0),
        duplicate(3, osm_node_id='2', local_ref='b', lat=48.0),
        duplicate(2, sloid='ch:1:sloid:9', designation='A ', group=pair),
        duplicate(2, sloid='ch:1:sloid:8', designation='a', group=pair),
        # The same designation outside the engine's group is another platform.
        duplicate(2, sloid='ch:1:sloid:7', designation='A'),
        # An OSM element with an ATLAS-side priority belongs to no group.
        duplicate(2, osm_node_id='3', local_ref='b'),
    ]

    groups = duplicate_groups(problems, member_ids)

    assert [(group['id'], group['priority'], group['members']) for group in groups] == [
        ('dup_atlas_8500_a', 2, ['ch:1:sloid:9', 'ch:1:sloid:8']),
        ('dup_osm_8500_b', 3, ['1', '2']),
    ]
    assert groups[0]['sloid'] == 'ch:1:sloid:8'
    assert groups[1]['osm_local_ref'] == 'b'
    assert groups[1]['osm_lat'] == groups[1]['atlas_lat'] == 47.0


def test_an_atlas_group_lists_the_members_the_engine_did_not_flag():
    # Renens: the engine flags the member a rule matched, not the copy matched by propagation, which comes from
    # unlisted_group_members without a priority. Vevey: the matched OSM element is an OSM duplicate too, so both
    # ATLAS members carry the OSM duplicate (P3); they are still an ATLAS duplicate.
    renens, vevey = ['ch:1:sloid:3439', 'ch:1:sloid:2351'], ['ch:1:sloid:1724', 'ch:1:sloid:4']
    problems = [
        duplicate(2, sloid='ch:1:sloid:3439', uic_ref='8501118', designation='B', group=renens),
        duplicate(None, sloid='ch:1:sloid:2351', uic_ref='8501118', designation='B', group=renens),
        duplicate(3, sloid='ch:1:sloid:1724', osm_node_id='11', uic_ref='8501200', designation='4', local_ref='4',
                  group=vevey),
        duplicate(3, sloid='ch:1:sloid:4', osm_node_id='11', uic_ref='8501200', designation='4', local_ref='4',
                  group=vevey),
        duplicate(3, osm_node_id='12', uic_ref='8501200', local_ref='4'),
    ]

    groups = duplicate_groups(problems, lambda problem: problem.stop)

    def side_ids(group):
        return [getattr(stop, 'osm_node_id' if group['group_type'] == 'osm' else 'sloid') for stop in group['members']]

    assert [(group['id'], group['priority'], side_ids(group)) for group in groups] == [
        ('dup_atlas_8501118_b', 2, ['ch:1:sloid:3439', 'ch:1:sloid:2351']),
        ('dup_atlas_8501200_4', 2, ['ch:1:sloid:1724', 'ch:1:sloid:4']),
        ('dup_osm_8501200_4', 3, ['11', '12']),
    ]


def test_a_stop_matched_to_a_ptv2_pair_is_one_member():
    group = ['ch:1:sloid:1', 'ch:1:sloid:2']
    problems = [
        duplicate(2, sloid='ch:1:sloid:1', designation='A', group=group),
        duplicate(2, sloid='ch:1:sloid:1', designation='A', group=group),
    ]
    assert duplicate_groups(problems, member_ids) == []
    problems.append(duplicate(None, sloid='ch:1:sloid:2', designation='A', group=group))
    assert [group['members'] for group in duplicate_groups(problems, member_ids)] == [['ch:1:sloid:1', 'ch:1:sloid:2']]
