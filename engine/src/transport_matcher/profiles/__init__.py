"""Explicit matching policies; profiles never read environment variables or files."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReferenceRule:
    namespace: str
    osm_tag: str
    scope: str = 'stop'
    source_namespace: str | None = None
    osm_scope_tag: str | None = None
    osm_scope_value: str | None = None

    def __post_init__(self):
        if not self.namespace or not self.osm_tag or not self.scope:
            raise ValueError('Reference rules require namespace, OSM tag and scope')
        if (self.osm_scope_tag is None) != (self.osm_scope_value is None):
            raise ValueError('OSM reference scope requires both a tag and value')

    def accepts(self, source, reference, osm):
        return (
            reference.namespace == self.namespace and reference.scope == self.scope
            and (self.source_namespace is None or source.namespace == self.source_namespace)
            and str(osm.tags.get(self.osm_tag, '')) == reference.value
            and (self.osm_scope_tag is None or osm.tags.get(self.osm_scope_tag) == self.osm_scope_value)
        )


@dataclass(frozen=True)
class GroupingPolicy:
    pair_distance: float = 12.0
    perfect_count_distance: float = 15.0
    trio_middle_distance: float = 15.0
    nearby_source_distance: float = 30.0
    strict_ratio: float = 1.5
    relaxed_ratio: float = 2.0


@dataclass(frozen=True)
class MatchingProfile:
    profile_id: str = 'generic'
    max_distance: float = 50.0
    long_distance: float = 150.0
    name_match_max_distance: float | None = 1000.0
    reference_rules: tuple[ReferenceRule, ...] = ()
    station_reference_matching: bool = False
    osm_station_ref_tag: str = 'uic_ref'
    problem_name_tags: tuple[str, ...] = ('name', 'uic_name')
    preserve_name_alias_multiplicity: bool = False
    osm_grouping: bool = False
    grouping: GroupingPolicy = field(default_factory=GroupingPolicy)
    predicate_names: tuple[str, ...] = (
        'trio', 'exact', 'name', 'route', 'group_proximity',
        'long_distance_group_proximity', 'local_ref', 'nearest_single',
        'nearest_ratio', 'nearest_second',
    )
    itinerary_min_stop_ratio: float = 0.8
    itinerary_require_direction: bool = False
    isolation_radius: float = 50.0
    distance_priorities: tuple[float, float, float] = (80.0, 25.0, 15.0)
    ratio_min_second_distance: float = 10.0
    ratio_factor: float = 4.0
    distance_priority_exempt_operators: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ('stops', 'problems')

    def allows_station_reference(self, stop):
        return self.station_reference_matching and any(
            rule.scope == 'station' and rule.osm_tag == self.osm_station_ref_tag
            and (rule.source_namespace is None or stop.namespace == rule.source_namespace)
            and any(ref.namespace == rule.namespace and ref.scope == rule.scope and ref.value == stop.station_ref for ref in stop.references)
            for rule in self.reference_rules
        )

    def station_references_compatible(self, stop, osm):
        members = osm.get_members() if hasattr(osm, 'get_members') else [osm]
        return self.allows_station_reference(stop) and any(
            rule.osm_tag == self.osm_station_ref_tag and rule.scope == 'station'
            and any(ref.value == stop.station_ref and rule.accepts(stop, ref, member)
                    for ref in stop.references for member in members)
            for rule in self.reference_rules
        )

    def __post_init__(self):
        if self.max_distance <= 0 or self.long_distance <= 0 or self.isolation_radius <= 0:
            raise ValueError('Distance thresholds must be positive')
        if not 0 < self.itinerary_min_stop_ratio <= 1:
            raise ValueError('Itinerary minimum stop ratio must be greater than zero and at most one')
        if self.ratio_factor <= 1:
            raise ValueError('Distance ratio must exceed one')


from .switzerland import SWITZERLAND
