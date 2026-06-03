"""
Automated Entity Resolution System

Identifies and resolves duplicate entities across different data sources
using machine learning and rule-based approaches.
"""

import re
import hashlib
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from fuzzywuzzy import fuzz
import pandas as pd
from collections import defaultdict
import json
import pickle
from pathlib import Path


class EntityType(Enum):
    """Types of entities to resolve"""
    RESEARCHER = "researcher"
    INSTITUTION = "institution"
    PUBLICATION = "publication"
    DATASET = "dataset"
    BRAIN_REGION = "brain_region"
    COGNITIVE_CONCEPT = "cognitive_concept"
    EXPERIMENTAL_PARADIGM = "experimental_paradigm"


class MatchConfidence(Enum):
    """Confidence levels for entity matches"""
    EXACT = 1.0
    HIGH = 0.9
    MEDIUM = 0.7
    LOW = 0.5
    NO_MATCH = 0.0


@dataclass
class Entity:
    """Represents an entity to be resolved"""
    entity_id: str
    entity_type: EntityType
    name: str
    source: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)
    external_ids: Dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def get_feature_vector(self) -> str:
        """Generate feature vector for matching"""
        features = [self.name.lower()]
        features.extend([a.lower() for a in self.aliases])
        features.extend(self.external_ids.values())

        # Add key attributes
        for key in ["email", "orcid", "doi", "pmid", "url"]:
            if key in self.attributes:
                features.append(str(self.attributes[key]))

        return " ".join(features)


@dataclass
class EntityMatch:
    """Represents a match between two entities"""
    entity1_id: str
    entity2_id: str
    confidence: float
    match_reasons: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)

    @property
    def is_confident_match(self) -> bool:
        return self.confidence >= MatchConfidence.HIGH.value


@dataclass
class ResolvedEntity:
    """Represents a resolved (merged) entity"""
    resolved_id: str
    entity_type: EntityType
    canonical_name: str
    source_entities: List[str]  # Original entity IDs
    all_names: Set[str]
    all_attributes: Dict[str, Any]
    all_external_ids: Dict[str, str]
    confidence: float
    resolution_timestamp: datetime = field(default_factory=datetime.now)


class EntityResolver:
    """Automated entity resolution system"""

    def __init__(
        self,
        similarity_threshold: float = 0.7,
        blocking_enabled: bool = True,
        ml_enabled: bool = True,
        rules_path: Optional[Path] = None
    ):
        """
        Initialize entity resolver

        Args:
            similarity_threshold: Minimum similarity for potential match
            blocking_enabled: Use blocking for efficiency
            ml_enabled: Use ML-based matching
            rules_path: Path to custom matching rules
        """
        self.similarity_threshold = similarity_threshold
        self.blocking_enabled = blocking_enabled
        self.ml_enabled = ml_enabled

        # Entity storage
        self.entities: Dict[str, Entity] = {}
        self.resolved_entities: Dict[str, ResolvedEntity] = {}
        self.matches: List[EntityMatch] = []

        # Indexes for efficient matching
        self.name_index: Dict[str, Set[str]] = defaultdict(set)
        self.attribute_index: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
        self.external_id_index: Dict[Tuple[str, str], str] = {}

        # ML components
        self.vectorizer = TfidfVectorizer(
            analyzer='char_wb',
            ngram_range=(2, 4),
            max_features=1000
        )
        self.feature_vectors = None

        # Load custom rules
        self.matching_rules = self._load_matching_rules(rules_path)

    def add_entity(self, entity: Entity) -> str:
        """
        Add entity for resolution

        Returns:
            Entity ID
        """
        self.entities[entity.entity_id] = entity

        # Update indexes
        self._index_entity(entity)

        return entity.entity_id

    def resolve_entities(
        self,
        entity_type: Optional[EntityType] = None,
        batch_size: int = 1000
    ) -> List[ResolvedEntity]:
        """
        Resolve entities of given type

        Args:
            entity_type: Type of entities to resolve (None for all)
            batch_size: Batch size for processing

        Returns:
            List of resolved entities
        """
        # Filter entities by type
        entities_to_resolve = [
            e for e in self.entities.values()
            if entity_type is None or e.entity_type == entity_type
        ]

        if not entities_to_resolve:
            return []

        # Find matches
        matches = self._find_all_matches(entities_to_resolve, batch_size)

        # Cluster matches
        clusters = self._cluster_matches(matches)

        # Resolve clusters into merged entities
        resolved = []
        for cluster in clusters:
            resolved_entity = self._merge_cluster(cluster)
            self.resolved_entities[resolved_entity.resolved_id] = resolved_entity
            resolved.append(resolved_entity)

        return resolved

    def find_duplicates(
        self,
        entity: Entity,
        limit: int = 10
    ) -> List[Tuple[Entity, float]]:
        """
        Find potential duplicates for an entity

        Args:
            entity: Entity to find duplicates for
            limit: Maximum number of duplicates to return

        Returns:
            List of (entity, confidence) tuples
        """
        candidates = self._get_candidates(entity)

        matches = []
        for candidate in candidates:
            if candidate.entity_id == entity.entity_id:
                continue

            confidence = self._calculate_similarity(entity, candidate)
            if confidence >= self.similarity_threshold:
                matches.append((candidate, confidence))

        # Sort by confidence
        matches.sort(key=lambda x: x[1], reverse=True)

        return matches[:limit]

    def resolve_pair(
        self,
        entity1_id: str,
        entity2_id: str,
        force: bool = False
    ) -> Optional[ResolvedEntity]:
        """
        Resolve two specific entities

        Args:
            entity1_id: First entity ID
            entity2_id: Second entity ID
            force: Force resolution even if low confidence

        Returns:
            Resolved entity if successful
        """
        if entity1_id not in self.entities or entity2_id not in self.entities:
            raise ValueError("Entity not found")

        entity1 = self.entities[entity1_id]
        entity2 = self.entities[entity2_id]

        # Check if they can be matched
        match = self._match_entities(entity1, entity2)

        if not force and not match.is_confident_match:
            return None

        # Merge entities
        return self._merge_entities([entity1, entity2], match.confidence)

    def _find_all_matches(
        self,
        entities: List[Entity],
        batch_size: int
    ) -> List[EntityMatch]:
        """Find all matches between entities"""
        matches = []

        # Process in batches for memory efficiency
        for i in range(0, len(entities), batch_size):
            batch = entities[i:i + batch_size]

            if self.blocking_enabled:
                # Use blocking to reduce comparisons
                blocks = self._create_blocks(batch)
                for block in blocks.values():
                    if len(block) > 1:
                        matches.extend(self._match_within_block(block))
            else:
                # Compare all pairs (expensive)
                for j, entity1 in enumerate(batch):
                    for entity2 in batch[j + 1:]:
                        match = self._match_entities(entity1, entity2)
                        if match.is_confident_match:
                            matches.append(match)

        return matches

    def _create_blocks(self, entities: List[Entity]) -> Dict[str, List[Entity]]:
        """Create blocks for efficient matching"""
        blocks = defaultdict(list)

        for entity in entities:
            # Block by first 3 characters of name
            if len(entity.name) >= 3:
                block_key = entity.name[:3].lower()
                blocks[block_key].append(entity)

            # Block by external IDs
            for id_type, id_value in entity.external_ids.items():
                block_key = f"{id_type}:{id_value}"
                blocks[block_key].append(entity)

            # Block by key attributes
            for attr in ["email", "doi", "orcid"]:
                if attr in entity.attributes:
                    block_key = f"{attr}:{entity.attributes[attr]}"
                    blocks[block_key].append(entity)

        return blocks

    def _match_within_block(self, block: List[Entity]) -> List[EntityMatch]:
        """Match entities within a block"""
        matches = []

        for i, entity1 in enumerate(block):
            for entity2 in block[i + 1:]:
                match = self._match_entities(entity1, entity2)
                if match.is_confident_match:
                    matches.append(match)

        return matches

    def _match_entities(self, entity1: Entity, entity2: Entity) -> EntityMatch:
        """Match two entities"""
        match = EntityMatch(
            entity1_id=entity1.entity_id,
            entity2_id=entity2.entity_id,
            confidence=0.0
        )

        # Check exact matches first
        if self._check_exact_match(entity1, entity2, match):
            match.confidence = MatchConfidence.EXACT.value
            return match

        # Check rule-based matches
        rule_confidence = self._apply_matching_rules(entity1, entity2, match)

        # Calculate similarity-based confidence
        similarity_confidence = self._calculate_similarity(entity1, entity2)

        # Combine confidences
        if self.ml_enabled and similarity_confidence > 0:
            match.confidence = (rule_confidence + similarity_confidence) / 2
        else:
            match.confidence = rule_confidence

        return match

    def _check_exact_match(
        self,
        entity1: Entity,
        entity2: Entity,
        match: EntityMatch
    ) -> bool:
        """Check for exact matches"""
        # Check external IDs
        for id_type in entity1.external_ids:
            if id_type in entity2.external_ids:
                if entity1.external_ids[id_type] == entity2.external_ids[id_type]:
                    match.match_reasons.append(f"Exact {id_type} match")
                    return True

        # Check unique attributes
        for attr in ["doi", "pmid", "orcid", "email"]:
            if attr in entity1.attributes and attr in entity2.attributes:
                if entity1.attributes[attr] == entity2.attributes[attr]:
                    match.match_reasons.append(f"Exact {attr} match")
                    return True

        return False

    def _apply_matching_rules(
        self,
        entity1: Entity,
        entity2: Entity,
        match: EntityMatch
    ) -> float:
        """Apply rule-based matching"""
        confidence = 0.0

        # Name similarity
        name_sim = fuzz.ratio(entity1.name, entity2.name) / 100.0
        if name_sim > 0.9:
            match.match_reasons.append(f"High name similarity ({name_sim:.2f})")
            confidence = max(confidence, name_sim)

        # Check aliases
        for alias1 in entity1.aliases:
            if alias1 in entity2.aliases or fuzz.ratio(alias1, entity2.name) > 90:
                match.match_reasons.append(f"Alias match: {alias1}")
                confidence = max(confidence, 0.8)

        # Type-specific rules
        if entity1.entity_type == EntityType.RESEARCHER:
            confidence = max(confidence, self._match_researchers(entity1, entity2, match))
        elif entity1.entity_type == EntityType.PUBLICATION:
            confidence = max(confidence, self._match_publications(entity1, entity2, match))

        return confidence

    def _match_researchers(
        self,
        entity1: Entity,
        entity2: Entity,
        match: EntityMatch
    ) -> float:
        """Apply researcher-specific matching rules"""
        confidence = 0.0

        # Check institution
        if "institution" in entity1.attributes and "institution" in entity2.attributes:
            inst_sim = fuzz.ratio(
                entity1.attributes["institution"],
                entity2.attributes["institution"]
            ) / 100.0
            if inst_sim > 0.8:
                match.match_reasons.append("Same institution")
                confidence = max(confidence, 0.7)

        # Check co-authors
        if "coauthors" in entity1.attributes and "coauthors" in entity2.attributes:
            coauthors1 = set(entity1.attributes["coauthors"])
            coauthors2 = set(entity2.attributes["coauthors"])
            overlap = len(coauthors1 & coauthors2)
            if overlap > 3:
                match.match_reasons.append(f"Share {overlap} co-authors")
                confidence = max(confidence, 0.8)

        return confidence

    def _match_publications(
        self,
        entity1: Entity,
        entity2: Entity,
        match: EntityMatch
    ) -> float:
        """Apply publication-specific matching rules"""
        confidence = 0.0

        # Check title similarity
        if "title" in entity1.attributes and "title" in entity2.attributes:
            title_sim = fuzz.ratio(
                entity1.attributes["title"],
                entity2.attributes["title"]
            ) / 100.0
            if title_sim > 0.95:
                match.match_reasons.append("Nearly identical titles")
                confidence = max(confidence, 0.95)

        # Check year and authors
        same_year = entity1.attributes.get("year") == entity2.attributes.get("year")
        if same_year and "authors" in entity1.attributes and "authors" in entity2.attributes:
            authors1 = set(entity1.attributes["authors"])
            authors2 = set(entity2.attributes["authors"])
            if len(authors1 & authors2) > len(authors1) * 0.7:
                match.match_reasons.append("Same year and similar authors")
                confidence = max(confidence, 0.9)

        return confidence

    def _calculate_similarity(self, entity1: Entity, entity2: Entity) -> float:
        """Calculate ML-based similarity"""
        if not self.ml_enabled:
            return 0.0

        # Generate feature vectors
        features = [entity1.get_feature_vector(), entity2.get_feature_vector()]

        try:
            # Vectorize
            vectors = self.vectorizer.fit_transform(features)

            # Calculate cosine similarity
            similarity = cosine_similarity(vectors[0:1], vectors[1:2])[0, 0]

            return float(similarity)
        except Exception:
            return 0.0

    def _cluster_matches(self, matches: List[EntityMatch]) -> List[Set[str]]:
        """Cluster matches into connected components"""
        # Build graph of matches
        graph = defaultdict(set)
        for match in matches:
            graph[match.entity1_id].add(match.entity2_id)
            graph[match.entity2_id].add(match.entity1_id)

        # Find connected components
        clusters = []
        visited = set()

        for entity_id in graph:
            if entity_id not in visited:
                cluster = set()
                self._dfs_cluster(entity_id, graph, visited, cluster)
                clusters.append(cluster)

        return clusters

    def _dfs_cluster(
        self,
        entity_id: str,
        graph: Dict[str, Set[str]],
        visited: Set[str],
        cluster: Set[str]
    ):
        """DFS to find connected component"""
        visited.add(entity_id)
        cluster.add(entity_id)

        for neighbor in graph[entity_id]:
            if neighbor not in visited:
                self._dfs_cluster(neighbor, graph, visited, cluster)

    def _merge_cluster(self, cluster: Set[str]) -> ResolvedEntity:
        """Merge a cluster of entities"""
        entities = [self.entities[eid] for eid in cluster if eid in self.entities]

        # Calculate average confidence
        total_confidence = 0
        match_count = 0
        for match in self.matches:
            if match.entity1_id in cluster and match.entity2_id in cluster:
                total_confidence += match.confidence
                match_count += 1

        avg_confidence = total_confidence / match_count if match_count > 0 else 1.0

        return self._merge_entities(entities, avg_confidence)

    def _merge_entities(
        self,
        entities: List[Entity],
        confidence: float
    ) -> ResolvedEntity:
        """Merge multiple entities into one"""
        # Select canonical name (most common or longest)
        name_counts = defaultdict(int)
        for entity in entities:
            name_counts[entity.name] += 1

        canonical_name = max(name_counts.keys(), key=lambda k: (name_counts[k], len(k)))

        # Merge attributes
        all_names = set()
        all_attributes = {}
        all_external_ids = {}

        for entity in entities:
            all_names.add(entity.name)
            all_names.update(entity.aliases)

            # Merge attributes (keep all values)
            for key, value in entity.attributes.items():
                if key not in all_attributes:
                    all_attributes[key] = value
                elif isinstance(all_attributes[key], list):
                    if value not in all_attributes[key]:
                        all_attributes[key].append(value)
                elif all_attributes[key] != value:
                    all_attributes[key] = [all_attributes[key], value]

            # Merge external IDs
            all_external_ids.update(entity.external_ids)

        return ResolvedEntity(
            resolved_id=hashlib.md5(
                "".join(sorted([e.entity_id for e in entities])).encode()
            ).hexdigest(),
            entity_type=entities[0].entity_type,
            canonical_name=canonical_name,
            source_entities=[e.entity_id for e in entities],
            all_names=all_names,
            all_attributes=all_attributes,
            all_external_ids=all_external_ids,
            confidence=confidence
        )

    def _get_candidates(self, entity: Entity) -> List[Entity]:
        """Get candidate entities for matching"""
        candidates = set()

        # Get by name similarity
        for name in self.name_index:
            if fuzz.ratio(entity.name, name) > 70:
                candidates.update(self.name_index[name])

        # Get by external IDs
        for id_type, id_value in entity.external_ids.items():
            key = (id_type, id_value)
            if key in self.external_id_index:
                candidate_id = self.external_id_index[key]
                if candidate_id in self.entities:
                    candidates.add(candidate_id)

        return [self.entities[cid] for cid in candidates]

    def _index_entity(self, entity: Entity):
        """Add entity to indexes"""
        # Name index
        self.name_index[entity.name.lower()].add(entity.entity_id)
        for alias in entity.aliases:
            self.name_index[alias.lower()].add(entity.entity_id)

        # Attribute index
        for key, value in entity.attributes.items():
            if isinstance(value, str):
                self.attribute_index[(key, value)].add(entity.entity_id)

        # External ID index
        for id_type, id_value in entity.external_ids.items():
            self.external_id_index[(id_type, id_value)] = entity.entity_id

    def _load_matching_rules(self, rules_path: Optional[Path]) -> Dict[str, Any]:
        """Load custom matching rules"""
        if not rules_path or not rules_path.exists():
            return {}

        try:
            with open(rules_path) as f:
                return json.load(f)
        except Exception:
            return {}

    def export_resolution_report(self) -> Dict[str, Any]:
        """Export resolution statistics and report"""
        return {
            "total_entities": len(self.entities),
            "resolved_entities": len(self.resolved_entities),
            "total_matches": len(self.matches),
            "resolution_rate": len(self.resolved_entities) / max(len(self.entities), 1),
            "confidence_distribution": self._get_confidence_distribution(),
            "entities_by_type": self._count_by_type(),
            "top_merged_entities": self._get_top_merged()
        }

    def _get_confidence_distribution(self) -> Dict[str, int]:
        """Get distribution of match confidences"""
        distribution = {
            "exact": 0,
            "high": 0,
            "medium": 0,
            "low": 0
        }

        for match in self.matches:
            if match.confidence >= MatchConfidence.EXACT.value:
                distribution["exact"] += 1
            elif match.confidence >= MatchConfidence.HIGH.value:
                distribution["high"] += 1
            elif match.confidence >= MatchConfidence.MEDIUM.value:
                distribution["medium"] += 1
            else:
                distribution["low"] += 1

        return distribution

    def _count_by_type(self) -> Dict[str, int]:
        """Count entities by type"""
        counts = defaultdict(int)
        for entity in self.entities.values():
            counts[entity.entity_type.value] += 1
        return dict(counts)

    def _get_top_merged(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top merged entities by source count"""
        merged = []
        for resolved in self.resolved_entities.values():
            merged.append({
                "canonical_name": resolved.canonical_name,
                "source_count": len(resolved.source_entities),
                "confidence": resolved.confidence,
                "type": resolved.entity_type.value
            })

        merged.sort(key=lambda x: x["source_count"], reverse=True)
        return merged[:limit]


# Custom exceptions
class EntityResolutionException(Exception):
    """Base exception for entity resolution errors"""
    pass

class EntityNotFoundException(EntityResolutionException):
    """Entity not found"""
    pass

class InvalidEntityTypeException(EntityResolutionException):
    """Invalid entity type"""
    pass

class ResolutionFailedException(EntityResolutionException):
    """Entity resolution failed"""
    pass

class InsufficientConfidenceException(EntityResolutionException):
    """Insufficient confidence for resolution"""
    pass