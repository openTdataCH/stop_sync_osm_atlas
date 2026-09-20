"""Normalized records exchanged by adapters, predicates and result writers."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any


def _validate_position(lat: float, lon: float) -> None:
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f'Invalid WGS84 coordinates: {lat}, {lon}')


@dataclass(frozen=True)
class Reference:
    namespace: str
    value: str
    scope: str = 'stop'

    def __post_init__(self):
        if not self.namespace or not self.value or not self.scope:
            raise ValueError('References need a namespace, value and scope')


@dataclass(frozen=True)
class SourceStop:
    namespace: str
    source_id: str
    lat: float
    lon: float
    name: str = ''
    platform_code: str = ''
    station_ref: str = ''
    operator: str = ''
    operator_id: str = ''
    operator_name: str = ''
    references: tuple[Reference, ...] = ()
    parent_id: str | None = None
    stop_kind: str = 'platform'
    extensions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.namespace or ':' in self.namespace or not self.source_id:
            raise ValueError('Source stops require a non-empty namespace (without colons) and source ID')
        _validate_position(self.lat, self.lon)
        object.__setattr__(self, 'references', tuple(dict.fromkeys(self.references)))

    @property
    def key(self) -> str:
        return f'{self.namespace}:{self.source_id}'


@dataclass(frozen=True)
class OsmNode:
    node_id: str
    lat: float
    lon: float
    local_ref: str | None = None
    name: str | None = None
    uic_name: str | None = None
    uic_ref: str | None = None
    network: str = ''
    operator: str = ''
    public_transport: str | None = None
    railway: str | None = None
    amenity: str | None = None
    aerialway: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    element_type: str = 'node'
    station_reference: str | None = None

    def __post_init__(self):
        if not self.node_id:
            raise ValueError('OSM elements require an identity')
        _validate_position(self.lat, self.lon)
        if self.element_type not in ('node', 'way', 'relation'):
            raise ValueError('Unsupported OSM element type')
        if self.node_id.startswith('way_'):
            object.__setattr__(self, 'element_type', 'way')
        elif self.node_id.startswith('relation_'):
            object.__setattr__(self, 'element_type', 'relation')
        elif self.element_type != 'node':
            object.__setattr__(self, 'node_id', f'{self.element_type}_{self.node_id}')

    @property
    def key(self) -> str:
        element_id = self.node_id.removeprefix(f'{self.element_type}_')
        return f'osm:{self.element_type}:{element_id}'

    @property
    def station_ref(self) -> str | None:
        return self.station_reference if self.station_reference is not None else self.uic_ref

    @property
    def is_station(self) -> bool:
        if self.public_transport == 'stop_position' or self.aerialway == 'station':
            return False
        return self.public_transport == 'station' or self.railway == 'station'


class SourceEntity:
    def __init__(self, node: SourceStop, siblings=None, group_type=None):
        self.representative = node
        self._siblings = siblings or []
        self.group_type = group_type

    def __getattr__(self, name):
        return getattr(self.representative, name)

    def get_members(self):
        return [self.representative] + self._siblings

    @property
    def is_group(self):
        return bool(self._siblings)


class OsmEntity(SourceEntity):
    """An OSM representative and its explicitly related members."""


@dataclass
class MatchRecord:
    source_node: SourceStop
    osm_node: OsmNode
    match_type: str
    distance_m: float
    notes: str
    problems: list = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def evaluate_matched_problems(self, problem_ctx, predicates):
        self.problems = [problem for predicate in predicates for problem in predicate(problem_ctx, self)]


@dataclass
class PipelineResult:
    matched: list[MatchRecord]
    unmatched_source: list[SourceStop]
    unmatched_osm: list[OsmNode]


@dataclass(frozen=True)
class OsmStopMemberRecord:
    node_id: str
    member_role: str


@dataclass
class OsmStopUnitRecord:
    stop_kind: str
    group_kind: str | None
    representative_node_id: str
    members: list[OsmStopMemberRecord] = field(default_factory=list)


@dataclass(frozen=True)
class DetectedProblem:
    problem_id: str
    problem_type: str
    priority: int
    source_keys: tuple[str, ...] = ()
    osm_ids: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchingOutput:
    matched: list[MatchRecord]
    unmatched_source: list[SourceStop]
    unmatched_osm: list[OsmNode]
    duplicate_key_map: dict[str, list[str]]
    osm_stop_units: list[OsmStopUnitRecord] = field(default_factory=list)
    all_source_nodes: list[SourceStop] = field(default_factory=list)
    all_osm_nodes: list[OsmNode] = field(default_factory=list)
    source_route_evidence_by_key: dict[str, dict[str, list[Any]]] = field(default_factory=dict)
    osm_node_routes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    osm_name_dirs: dict[str, set[str]] = field(default_factory=dict)
    problems: list[DetectedProblem] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    source_isolated_keys: list[str] = field(default_factory=list)
    isolated_osm_ids: list[str] = field(default_factory=list)
    effectively_matched_osm_ids: list[str] = field(default_factory=list)
    duplicate_osm_group_map: dict[str, list[str]] = field(default_factory=dict)
    profile_id: str = ''
    extensions: dict[str, Any] = field(default_factory=dict)
    routes: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
