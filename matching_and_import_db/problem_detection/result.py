"""ProblemResult — lightweight value object returned by predicates."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProblemResult:
    """Decoupled from the ORM ``Problem`` model so that detection logic
    has no dependency on SQLAlchemy / Flask."""
    problem_type: str        # 'distance', 'attributes', 'unmatched', 'duplicates'
    priority: int            # 1 = P1, 2 = P2, 3 = P3
    has_atlas_duplicate: bool = False
    has_osm_duplicate: bool = False
