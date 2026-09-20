import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from transport_matcher.core.pipeline import MatchingContext


logger = logging.getLogger(__name__)


class BasePredicate(ABC):
    """
    Strict contract for matching heuristics in the data-first pipeline.
    
    Each subclass must implement `run(ctx: MatchingContext)`, which
    utilizes the `ctx.commit(...)` transactional API instead of returning loose dictionaries.
    """

    def __init__(self, name: Optional[str] = None, max_distance: float = 50.0):
        self._name = name or self.__class__.__name__
        self.max_distance = max_distance

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    def run(self, ctx: 'MatchingContext') -> None:
        """
        Executes the heuristic algorithm.
        
        This method must interface with the Context's transactional API, 
        e.g., calling `ctx.commit(source_node, osm_node, match_type='...', distance_m=..., notes='...')`.
        It should not return anything.
        """
        pass
