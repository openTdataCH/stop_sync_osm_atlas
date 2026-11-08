"""The Swiss matching rules in run order, with the match types each one writes.

Rule keys are the engine's profile rule names. A filter value is a rule key, which
selects every match type of that rule, or a single match type.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MatchingRule:
    key: str
    label: str
    match_types: tuple[tuple[str, str], ...]   # (match type, label)
    group: str                                  # 'identifier', 'route' or 'distance'


MATCHING_RULES = (
    MatchingRule('identifier', 'SLOID in OSM', (
        ('sloid_identifier', 'OSM ref:sloid names the platform'),
    ), 'identifier'),
    MatchingRule('two_sided_stop', 'UIC two-sided stop', (
        ('uic_two_sided_stop', 'UIC two-sided stop'),
    ), 'identifier'),
    MatchingRule('reference', 'UIC reference', (
        ('uic_reference_one_osm', 'One OSM element'),
        ('uic_reference_local_ref', 'Platform code = local_ref'),
        ('uic_reference_one_source', 'One ATLAS platform'),
    ), 'identifier'),
    MatchingRule('name', 'Name', (
        ('name_one_osm', 'One OSM element'),
        ('name_local_ref', 'Platform code = local_ref'),
    ), 'identifier'),
    MatchingRule('gtfs_route', 'GTFS route', (
        ('gtfs_shared_route', 'Shared GTFS route'),
        ('gtfs_shared_direction', 'Shared GTFS direction name'),
    ), 'route'),
    MatchingRule('group_distance', 'Group distance (50 m)', (
        ('uic_ref_group_distance', 'By uic_ref'),
        ('uic_name_group_distance', 'By uic_name'),
        ('name_group_distance', 'By name'),
    ), 'distance'),
    MatchingRule('group_long_distance', 'Group long distance (150 m)', (
        ('uic_ref_group_long_distance', 'By uic_ref'),
        ('uic_name_group_long_distance', 'By uic_name'),
        ('name_group_long_distance', 'By name'),
    ), 'distance'),
    MatchingRule('local_ref_distance', 'local_ref distance', (
        ('local_ref_distance', 'local_ref distance'),
    ), 'distance'),
    MatchingRule('distance_only_candidate', 'Only candidate', (
        ('distance_only_candidate', 'First pass'),
        ('distance_only_candidate_second_pass', 'Second pass'),
    ), 'distance'),
    MatchingRule('distance_ratio', 'Distance ratio', (
        ('distance_ratio', 'Distance ratio'),
    ), 'distance'),
)

PROPAGATION_MATCH_TYPES = (
    ('source_duplicate_propagation', 'ATLAS duplicate propagation'),
    ('osm_pair_propagation', 'OSM pair propagation'),
)

RULES_BY_KEY = {rule.key: rule for rule in MATCHING_RULES}
MATCH_TYPES = frozenset(match_type for rule in MATCHING_RULES for match_type, _ in rule.match_types)


def match_types_for_filter(value):
    """Return the match types a filter value selects: a rule's types, one type, or none."""
    if value in RULES_BY_KEY:
        return tuple(match_type for match_type, _ in RULES_BY_KEY[value].match_types)
    if value in MATCH_TYPES:
        return (value,)
    return ()
