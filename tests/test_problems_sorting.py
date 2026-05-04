from backend.blueprints.problems import (
    DEFAULT_PROBLEM_SORT_BY,
    DEFAULT_PROBLEM_SORT_ORDER,
    sort_duplicate_groups,
)


def test_problem_sort_defaults_to_priority_first():
    assert DEFAULT_PROBLEM_SORT_BY == 'priority'
    assert DEFAULT_PROBLEM_SORT_ORDER == 'asc'


def test_sort_duplicate_groups_uses_priority_ascending_by_default():
    groups = [
        {'id': 'dup_p3', 'group_type': 'osm', 'priority': 3, 'uic_ref': '8500', 'osm_local_ref': 'b'},
        {'id': 'dup_p2', 'group_type': 'atlas', 'priority': 2, 'uic_ref': '8500', 'atlas_designation': 'a'},
    ]

    ordered = sort_duplicate_groups(groups, 'priority', 'asc')

    assert [group['id'] for group in ordered] == ['dup_p2', 'dup_p3']


def test_sort_duplicate_groups_supports_priority_descending():
    groups = [
        {'id': 'dup_p2', 'group_type': 'atlas', 'priority': 2, 'uic_ref': '8500', 'atlas_designation': 'a'},
        {'id': 'dup_p3', 'group_type': 'osm', 'priority': 3, 'uic_ref': '8500', 'osm_local_ref': 'b'},
    ]

    ordered = sort_duplicate_groups(groups, 'priority', 'desc')

    assert [group['id'] for group in ordered] == ['dup_p3', 'dup_p2']