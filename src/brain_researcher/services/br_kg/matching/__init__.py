"""Node matching and entity resolution for BR-KG."""

from .gabriel_runtime_mapper import GabrielRuntimeMapper, RuntimeMappingResult
from .node_matcher import MatchResult, UnifiedNodeMatcher

__all__ = [
    "UnifiedNodeMatcher",
    "MatchResult",
    "GabrielRuntimeMapper",
    "RuntimeMappingResult",
]
