import logging
from dataclasses import dataclass, field
from typing import Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from matching_and_import_db.problem_detection.context import ProblemContext
    from matching_and_import_db.problem_detection.result import ProblemResult


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AtlasNode:
    sloid: str
    lat: float
    lon: float
    uic_ref: str
    designation: str
    designation_official: str
    business_org_abbr: str


@dataclass(frozen=True)
class OsmNode:
    node_id: str
    lat: float
    lon: float
    local_ref: Optional[str]
    name: Optional[str]
    uic_name: Optional[str]
    uic_ref: Optional[str]
    network: str
    operator: str
    public_transport: Optional[str]
    railway: Optional[str]
    amenity: Optional[str]
    aerialway: Optional[str]
    tags: dict[str, str]

    @property
    def is_station(self) -> bool:
        """Helper mapped from utils.common.is_osm_station natively onto the model."""
        if self.aerialway == 'station':
            return False
        return (
            self.public_transport == 'station' or
            self.railway == 'station'
        )


@dataclass
class MatchRecord:
    atlas_node: AtlasNode
    osm_node: OsmNode
    match_type: str
    distance_m: float
    notes: str
    problems: list['ProblemResult'] = field(default_factory=list)

    def evaluate_problems(self, problem_ctx: 'ProblemContext', predicates: list) -> None:
        """
        Natively execute the problem heuristics on this match, directly returning ProblemResult
        objects without relying on the ORM or Importer logic.
        """
        self.problems.clear()
        
        for predicate in predicates:
            try:
                self.problems.extend(predicate(problem_ctx, self))
            except Exception:
                logger.warning(
                    f"Problem Predicate {predicate.__name__} failed for MatchRecord "
                    f"{self.atlas_node.sloid} <-> {self.osm_node.node_id}",
                    exc_info=True
                )


@dataclass
class PipelineResult:
    matched: list[MatchRecord]
    unmatched_atlas: list[AtlasNode]
    unmatched_osm: list[OsmNode]


@dataclass
class MatchingOutput:
    """Full output of run_matching(): pipeline results + pre-pipeline state."""
    matched: list[MatchRecord]
    unmatched_atlas: list[AtlasNode]
    unmatched_osm: list[OsmNode]
    duplicate_sloid_map: dict[str, list[str]]
    osm_groups: list[tuple[str, str, str]] = field(default_factory=list)  # [(node_id_1, node_id_2, group_type), ...]
    all_osm_nodes: list[OsmNode] = field(default_factory=list)
