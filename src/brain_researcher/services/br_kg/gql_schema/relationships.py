"""
GraphQL schema for edge relationships with provenance tracking.
Implements KG-003: Edge Relationships Schema
"""

from enum import Enum
from typing import List, Optional

import strawberry


@strawberry.enum
class RelationshipType(str, Enum):
    """Types of relationships in the knowledge graph."""

    MEASURES = "MEASURES"
    ACTIVATES = "ACTIVATES"
    DERIVED_FROM = "DERIVED_FROM"
    RELATED_TO = "RELATED_TO"
    PART_OF = "PART_OF"
    SUBCLASS_OF = "SUBCLASS_OF"
    CITES = "CITES"
    CITED_BY = "CITED_BY"
    COACTIVATES_WITH = "COACTIVATES_WITH"
    SIMILAR_TO = "SIMILAR_TO"
    CONTRASTS_WITH = "CONTRASTS_WITH"
    USES_TASK = "USES_TASK"
    IN_REGION = "IN_REGION"
    HAS_COORDINATE = "HAS_COORDINATE"


@strawberry.enum
class ProvenanceSource(str, Enum):
    """Sources of provenance information."""

    PUBMED = "PUBMED"
    OPENNEURO = "OPENNEURO"
    NEUROVAULT = "NEUROVAULT"
    COGATLAS = "COGATLAS"
    MANUAL_CURATION = "MANUAL_CURATION"
    AUTOMATED_EXTRACTION = "AUTOMATED_EXTRACTION"
    MODEL_PREDICTION = "MODEL_PREDICTION"
    USER_SUBMISSION = "USER_SUBMISSION"


@strawberry.type
class Provenance:
    """Provenance information for relationships."""

    source: ProvenanceSource
    source_id: Optional[str] = None  # e.g., PMID, dataset ID
    timestamp: str  # ISO format
    method: Optional[str] = None  # extraction method
    agent: Optional[str] = None  # user or system that created it
    version: Optional[str] = None  # version of extraction tool


@strawberry.type
class EdgeProperties:
    """Properties associated with graph edges."""

    confidence: Optional[float] = None  # 0.0 to 1.0
    strength: Optional[float] = None  # relationship strength
    weight: Optional[float] = None  # edge weight for algorithms
    evidence_count: Optional[int] = None  # number of supporting evidences
    p_value: Optional[float] = None  # statistical significance
    effect_size: Optional[float] = None  # Cohen's d or similar
    frequency: Optional[int] = None  # observation frequency
    metadata: Optional[str] = None  # JSON string of additional metadata


@strawberry.type
class Relationship:
    """Complete relationship with provenance."""

    id: str
    type: str  # RelationshipType as string
    start_node_id: str
    end_node_id: str
    properties: Optional[EdgeProperties] = None
    provenance: List[Provenance]
    created_at: str
    updated_at: str
    is_bidirectional: bool = False


@strawberry.type
class RelationshipInput:
    """Input type for creating relationships."""

    type: str
    start_node_id: str
    end_node_id: str
    confidence: Optional[float] = None
    source: str
    source_id: Optional[str] = None
    method: Optional[str] = None
    metadata: Optional[str] = None


@strawberry.type
class RelationshipFilter:
    """Filter criteria for relationships."""

    type: Optional[str] = None
    min_confidence: Optional[float] = None
    max_confidence: Optional[float] = None
    source: Optional[str] = None
    start_node_type: Optional[str] = None
    end_node_type: Optional[str] = None
    created_after: Optional[str] = None
    created_before: Optional[str] = None


@strawberry.type
class RelationshipStatistics:
    """Statistics about relationships."""

    total_count: int
    by_type: List["TypeCount"]
    by_source: List["SourceCount"]
    avg_confidence: float
    confidence_distribution: List["ConfidenceRange"]


@strawberry.type
class TypeCount:
    """Count by relationship type."""

    type: str
    count: int


@strawberry.type
class SourceCount:
    """Count by provenance source."""

    source: str
    count: int


@strawberry.type
class ConfidenceRange:
    """Confidence score distribution."""

    range: str  # e.g., "0.0-0.2", "0.2-0.4"
    count: int
    percentage: float


@strawberry.type
class ConflictingRelationship:
    """Represents conflicting relationships."""

    relationship1: Relationship
    relationship2: Relationship
    conflict_type: str  # "contradictory", "duplicate", "inconsistent"
    resolution_strategy: Optional[str] = None
    resolved_relationship: Optional[Relationship] = None


# Extended relationship queries
@strawberry.type
class RelationshipQueries:
    """GraphQL queries for relationships."""

    @strawberry.field
    def relationship(self, id: str) -> Optional[Relationship]:
        """Get a specific relationship by ID."""
        from brain_researcher.services.br_kg.db.bootstrap import get_db

        db = get_db()

        # Implementation would fetch from database
        # This is a placeholder
        return None

    @strawberry.field
    def relationships(
        self,
        filter: Optional[RelationshipFilter] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Relationship]:
        """Query relationships with filters."""
        from brain_researcher.services.br_kg.db.bootstrap import get_db

        db = get_db()

        relationships = []
        # Implementation would apply filters and pagination
        return relationships

    @strawberry.field
    def relationship_statistics(
        self, node_id: Optional[str] = None, node_type: Optional[str] = None
    ) -> RelationshipStatistics:
        """Get statistics about relationships."""
        # Placeholder implementation
        return RelationshipStatistics(
            total_count=0,
            by_type=[],
            by_source=[],
            avg_confidence=0.0,
            confidence_distribution=[],
        )

    @strawberry.field
    def find_conflicts(
        self, node_id: Optional[str] = None, relationship_type: Optional[str] = None
    ) -> List[ConflictingRelationship]:
        """Find conflicting relationships."""
        # Placeholder implementation
        return []

    @strawberry.field
    def trace_provenance(self, relationship_id: str) -> List[Provenance]:
        """Trace complete provenance chain for a relationship."""
        # Placeholder implementation
        return []


# Extended relationship mutations
@strawberry.type
class RelationshipMutations:
    """GraphQL mutations for relationships."""

    @strawberry.mutation
    def create_relationship_with_provenance(
        self, input: RelationshipInput
    ) -> Relationship:
        """Create a new relationship with full provenance."""
        import uuid
        from datetime import datetime

        from brain_researcher.services.br_kg.db.bootstrap import get_db

        db = get_db()

        # Create the relationship
        rel_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()

        # Create provenance
        provenance = Provenance(
            source=ProvenanceSource[input.source],
            source_id=input.source_id,
            timestamp=timestamp,
            method=input.method,
            agent="GraphQL API",
            version="1.0",
        )

        # Create edge properties
        properties = EdgeProperties(
            confidence=input.confidence, metadata=input.metadata
        )

        # Create relationship in database
        db.create_relationship(
            input.start_node_id,
            input.end_node_id,
            input.type,
            {
                "confidence": input.confidence,
                "source": input.source,
                "source_id": input.source_id,
                "method": input.method,
                "metadata": input.metadata,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )

        return Relationship(
            id=rel_id,
            type=input.type,
            start_node_id=input.start_node_id,
            end_node_id=input.end_node_id,
            properties=properties,
            provenance=[provenance],
            created_at=timestamp,
            updated_at=timestamp,
            is_bidirectional=False,
        )

    @strawberry.mutation
    def update_relationship_confidence(
        self, relationship_id: str, new_confidence: float, reason: str
    ) -> Relationship:
        """Update confidence score with audit trail."""
        # Placeholder implementation
        from datetime import datetime

        timestamp = datetime.now().isoformat()

        # Would update in database and add audit entry
        return Relationship(
            id=relationship_id,
            type="UPDATED",
            start_node_id="",
            end_node_id="",
            provenance=[],
            created_at=timestamp,
            updated_at=timestamp,
        )

    @strawberry.mutation
    def add_provenance(
        self,
        relationship_id: str,
        source: str,
        source_id: Optional[str] = None,
        method: Optional[str] = None,
    ) -> Provenance:
        """Add additional provenance to existing relationship."""
        from datetime import datetime

        timestamp = datetime.now().isoformat()

        return Provenance(
            source=ProvenanceSource[source],
            source_id=source_id,
            timestamp=timestamp,
            method=method,
            agent="GraphQL API",
            version="1.0",
        )

    @strawberry.mutation
    def resolve_conflict(
        self,
        relationship_id1: str,
        relationship_id2: str,
        resolution_strategy: str,
        keep_relationship_id: Optional[str] = None,
    ) -> ConflictingRelationship:
        """Resolve conflicting relationships."""
        # Placeholder implementation
        return ConflictingRelationship(
            relationship1=None,  # Would fetch from DB
            relationship2=None,  # Would fetch from DB
            conflict_type="resolved",
            resolution_strategy=resolution_strategy,
            resolved_relationship=None,
        )
