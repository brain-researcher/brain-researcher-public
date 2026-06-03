"""Temporal graph features for time-aware analytics.

This module provides temporal graph capabilities including Neo4j temporal
extensions, temporal query language, and real-time evolution tracking.

Key Components:
- Neo4j Temporal: Native temporal database features
- Temporal Cypher: Time-aware query language extensions
- Evolution Tracker: Real-time change tracking and analysis
"""

from .neo4j_temporal import (
    TemporalNeo4jDB,
    TemporalNode,
    TemporalRelationship,
    TemporalQuery,
    TimeRange
)
from .temporal_cypher import (
    TemporalCypherBuilder,
    TemporalQueryType,
    TemporalOperator,
    TemporalFilter
)
from .evolution_tracker import (
    GraphEvolutionTracker,
    EvolutionEvent,
    EvolutionPattern,
    EvolutionAnalyzer
)

__all__ = [
    "TemporalNeo4jDB",
    "TemporalNode",
    "TemporalRelationship",
    "TemporalQuery",
    "TimeRange",
    "TemporalCypherBuilder",
    "TemporalQueryType",
    "TemporalOperator",
    "TemporalFilter",
    "GraphEvolutionTracker",
    "EvolutionEvent",
    "EvolutionPattern",
    "EvolutionAnalyzer"
]