"""Data Deduplication System - implements INGEST-021.

This module provides data deduplication capabilities including fuzzy matching,
merge logic, conflict resolution, and deduplication reports.
"""

import difflib
import hashlib
import json
import logging
import re
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# Custom Exception Classes
class DeduplicationError(Exception):
    """Base exception for deduplication errors."""

    pass


class ValidationError(DeduplicationError):
    """Validation-related errors."""

    pass


class ConfigurationError(DeduplicationError):
    """Configuration-related errors."""

    pass


class MergeError(DeduplicationError):
    """Merge-related errors."""

    pass


class ComparisonError(DeduplicationError):
    """Comparison-related errors."""

    pass


class MatchType(Enum):
    """Types of matches."""

    EXACT = "exact"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"
    STRUCTURAL = "structural"


class MergeStrategy(Enum):
    """Merge strategies for duplicates."""

    KEEP_FIRST = "keep_first"
    KEEP_LAST = "keep_last"
    KEEP_HIGHEST_QUALITY = "keep_highest_quality"
    MERGE_ALL = "merge_all"
    MANUAL = "manual"


@dataclass
class DuplicateCandidate:
    """Represents a potential duplicate."""

    entity1_id: str
    entity2_id: str
    match_type: MatchType
    similarity_score: float
    matching_fields: List[str]
    conflicts: List[str] = field(default_factory=list)
    suggested_action: Optional[str] = None


@dataclass
class MergeDecision:
    """Represents a merge decision."""

    decision_id: str
    entities: List[str]
    strategy: MergeStrategy
    merged_entity: Dict[str, Any]
    conflicts_resolved: List[Dict[str, Any]]
    timestamp: datetime = field(default_factory=datetime.now)
    user: Optional[str] = None


@dataclass
class DeduplicationReport:
    """Report of deduplication results."""

    report_id: str
    total_entities: int
    duplicates_found: int
    duplicates_merged: int
    duplicates_skipped: int
    conflicts_encountered: int
    execution_time_ms: float
    timestamp: datetime = field(default_factory=datetime.now)
    details: List[Dict[str, Any]] = field(default_factory=list)


class DataDeduplication:
    """Data deduplication system."""

    def __init__(self, neo4j_driver=None, redis_client=None):
        """Initialize deduplication system.

        Args:
            neo4j_driver: Optional Neo4j driver
            redis_client: Optional Redis client for caching
        """
        self.driver = neo4j_driver
        self.redis = redis_client

        # Configuration with validation
        self.config = {
            "exact_match_fields": ["id", "doi", "pmid"],
            "fuzzy_match_fields": ["title", "name", "description"],
            "fuzzy_threshold": 0.85,
            "semantic_threshold": 0.9,
            "blocking_fields": ["type", "year", "category"],
            "quality_indicators": [
                "citation_count",
                "completeness",
                "source_reliability",
            ],
        }
        self._validate_config()

        # Caches with thread safety
        self.hash_cache = {}
        self.similarity_cache = {}
        self._cache_lock = threading.RLock()

        # LRU cache for similarity calculations
        self._similarity_lru_size = 10000

        # Statistics
        self.stats = {
            "total_comparisons": 0,
            "exact_matches": 0,
            "fuzzy_matches": 0,
            "semantic_matches": 0,
            "merges_performed": 0,
            "conflicts_resolved": 0,
        }

        # Thread pool for parallel processing
        self.executor = ThreadPoolExecutor(max_workers=4)

    def find_duplicates(
        self,
        entities: List[Dict[str, Any]],
        entity_type: str,
        match_types: Optional[List[MatchType]] = None,
    ) -> List[DuplicateCandidate]:
        """Find duplicate entities.

        Args:
            entities: List of entities to check
            entity_type: Type of entities
            match_types: Types of matching to perform

        Returns:
            List of duplicate candidates
        """
        if match_types is None:
            match_types = [MatchType.EXACT, MatchType.FUZZY]

        if not entities:
            return []

        # Validate input entities
        is_valid, validation_errors = self.validate_entities(entities)
        if not is_valid:
            raise ValidationError(f"Invalid entities: {validation_errors}")

        duplicates = []

        # Create blocks for efficient comparison
        blocks = self._create_blocks(entities, entity_type)

        # Compare within blocks
        for block_key, block_entities in blocks.items():
            if len(block_entities) < 2:
                continue

            # Compare each pair
            for i in range(len(block_entities)):
                for j in range(i + 1, len(block_entities)):
                    entity1 = block_entities[i]
                    entity2 = block_entities[j]

                    # Check for duplicates
                    candidate = self._compare_entities(
                        entity1, entity2, entity_type, match_types
                    )

                    if candidate:
                        duplicates.append(candidate)

        return duplicates

    def _create_blocks(
        self, entities: List[Dict[str, Any]], entity_type: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Create blocks for efficient duplicate detection.

        Args:
            entities: List of entities
            entity_type: Type of entities

        Returns:
            Blocked entities
        """
        blocks = defaultdict(list)

        for entity in entities:
            # Create block keys based on blocking fields
            block_parts = []

            for field in self.config["blocking_fields"]:
                if field in entity and entity[field]:
                    block_parts.append(f"{field}:{entity[field]}")

            if not block_parts:
                # Default block for entities without blocking fields
                block_keys = ["default"]
            else:
                block_keys = ["|".join(block_parts)]

            # Add to all applicable blocks
            for key in block_keys:
                blocks[key].append(entity)

        return blocks

    def _compare_entities(
        self,
        entity1: Dict[str, Any],
        entity2: Dict[str, Any],
        entity_type: str,
        match_types: List[MatchType],
    ) -> Optional[DuplicateCandidate]:
        """Compare two entities for duplication.

        Args:
            entity1: First entity
            entity2: Second entity
            entity_type: Type of entities
            match_types: Types of matching to perform

        Returns:
            Duplicate candidate if match found
        """
        self.stats["total_comparisons"] += 1

        # Track matching fields and conflicts
        matching_fields = []
        conflicts = []
        best_match_type = None
        best_score = 0

        # Exact matching
        if MatchType.EXACT in match_types:
            exact_match, exact_fields = self._exact_match(entity1, entity2)
            if exact_match:
                self.stats["exact_matches"] += 1
                return DuplicateCandidate(
                    entity1_id=entity1.get("id", str(entity1)),
                    entity2_id=entity2.get("id", str(entity2)),
                    match_type=MatchType.EXACT,
                    similarity_score=1.0,
                    matching_fields=exact_fields,
                    suggested_action="merge",
                )

        # Fuzzy matching
        if MatchType.FUZZY in match_types:
            fuzzy_score, fuzzy_fields = self._fuzzy_match(entity1, entity2)
            if fuzzy_score >= self.config["fuzzy_threshold"]:
                if fuzzy_score > best_score:
                    best_score = fuzzy_score
                    best_match_type = MatchType.FUZZY
                    matching_fields = fuzzy_fields
                    self.stats["fuzzy_matches"] += 1

        # Semantic matching (if embeddings available)
        if MatchType.SEMANTIC in match_types:
            semantic_score = self._semantic_match(entity1, entity2)
            if semantic_score >= self.config["semantic_threshold"]:
                if semantic_score > best_score:
                    best_score = semantic_score
                    best_match_type = MatchType.SEMANTIC
                    self.stats["semantic_matches"] += 1

        # Check for conflicts
        if best_match_type:
            conflicts = self._find_conflicts(entity1, entity2)

            return DuplicateCandidate(
                entity1_id=entity1.get("id", str(entity1)),
                entity2_id=entity2.get("id", str(entity2)),
                match_type=best_match_type,
                similarity_score=best_score,
                matching_fields=matching_fields,
                conflicts=conflicts,
                suggested_action="review" if conflicts else "merge",
            )

        return None

    def _exact_match(
        self, entity1: Dict[str, Any], entity2: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """Check for exact match.

        Args:
            entity1: First entity
            entity2: Second entity

        Returns:
            (is_match, matching_fields)
        """
        matching_fields = []

        for field in self.config["exact_match_fields"]:
            if field in entity1 and field in entity2:
                if entity1[field] and entity2[field]:
                    if str(entity1[field]).lower() == str(entity2[field]).lower():
                        matching_fields.append(field)
                        return True, [field]

        return False, matching_fields

    def _fuzzy_match(
        self, entity1: Dict[str, Any], entity2: Dict[str, Any]
    ) -> Tuple[float, List[str]]:
        """Perform fuzzy matching.

        Args:
            entity1: First entity
            entity2: Second entity

        Returns:
            (similarity_score, matching_fields)
        """
        scores = []
        matching_fields = []

        for field in self.config["fuzzy_match_fields"]:
            if field in entity1 and field in entity2:
                val1 = str(entity1[field]).lower()
                val2 = str(entity2[field]).lower()

                if val1 and val2:
                    # Use multiple similarity metrics
                    ratio = difflib.SequenceMatcher(None, val1, val2).ratio()

                    # Use cached similarity calculation
                    score = self._cached_similarity_score(val1, val2)

                    if score >= self.config["fuzzy_threshold"]:
                        matching_fields.append(field)
                        scores.append(score)

        if scores:
            return np.mean(scores), matching_fields
        return 0, []

    def _semantic_match(
        self, entity1: Dict[str, Any], entity2: Dict[str, Any]
    ) -> float:
        """Perform semantic matching using embeddings.

        Args:
            entity1: First entity
            entity2: Second entity

        Returns:
            Semantic similarity score
        """
        # Check if entities have embeddings
        if "embedding" not in entity1 or "embedding" not in entity2:
            return 0

        emb1 = np.array(entity1["embedding"])
        emb2 = np.array(entity2["embedding"])

        # Cosine similarity
        similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))

        return float(similarity)

    def _find_conflicts(
        self, entity1: Dict[str, Any], entity2: Dict[str, Any]
    ) -> List[str]:
        """Find conflicting fields between entities.

        Args:
            entity1: First entity
            entity2: Second entity

        Returns:
            List of conflicting fields
        """
        conflicts = []

        # Check all common fields
        common_fields = set(entity1.keys()) & set(entity2.keys())

        for field in common_fields:
            if field in ["id", "created_at", "updated_at"]:
                continue

            val1 = entity1[field]
            val2 = entity2[field]

            # Skip if both are None or empty
            if not val1 and not val2:
                continue

            # Check for conflicts
            if val1 != val2:
                if field == "year":
                    conflicts.append(field)
                    continue
                # Allow minor differences in numeric values
                if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                    # Fix division by zero
                    max_val = max(abs(val1), abs(val2), 1e-10)  # Avoid division by zero
                    if abs(val1 - val2) / max_val > 0.1:
                        conflicts.append(field)
                else:
                    conflicts.append(field)

        return conflicts

    def merge_entities(
        self,
        entities: List[Dict[str, Any]],
        strategy: MergeStrategy = MergeStrategy.MERGE_ALL,
        user: Optional[str] = None,
    ) -> MergeDecision:
        """Merge duplicate entities.

        Args:
            entities: Entities to merge
            strategy: Merge strategy
            user: User performing merge

        Returns:
            Merge decision
        """
        decision_id = f"merge-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        if strategy == MergeStrategy.KEEP_FIRST:
            merged = entities[0].copy()

        elif strategy == MergeStrategy.KEEP_LAST:
            merged = entities[-1].copy()

        elif strategy == MergeStrategy.KEEP_HIGHEST_QUALITY:
            merged = self._select_highest_quality(entities)

        elif strategy == MergeStrategy.MERGE_ALL:
            merged = self._merge_all_fields(entities)

        else:  # MANUAL
            raise NotImplementedError("Manual merge requires user interface")

        # Resolve conflicts
        conflicts_resolved = self._resolve_conflicts(entities, merged, strategy)

        # Create decision record
        decision = MergeDecision(
            decision_id=decision_id,
            entities=[e.get("id", str(e)) for e in entities],
            strategy=strategy,
            merged_entity=merged,
            conflicts_resolved=conflicts_resolved,
            user=user,
        )

        self.stats["merges_performed"] += 1
        self.stats["conflicts_resolved"] += len(conflicts_resolved)

        return decision

    def _select_highest_quality(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Select entity with highest quality.

        Args:
            entities: List of entities

        Returns:
            Highest quality entity
        """
        best_entity = None
        best_score = -1

        max_citations = max(
            (entity.get("citation_count", 0) or 0 for entity in entities),
            default=0,
        )

        for entity in entities:
            score = 0

            # Calculate quality score
            for indicator in self.config["quality_indicators"]:
                if indicator in entity:
                    if indicator == "completeness":
                        completeness_val = entity.get("completeness")
                        if isinstance(completeness_val, dict):
                            non_null = sum(
                                1 for v in completeness_val.values() if v is not None
                            )
                            completeness_score = (
                                non_null / len(completeness_val)
                                if completeness_val
                                else 0
                            )
                        elif isinstance(completeness_val, (int, float)):
                            completeness_score = float(completeness_val)
                        else:
                            completeness_score = 0.0
                        score += completeness_score
                    elif indicator == "citation_count":
                        citation_count = max(entity[indicator], 0)
                        if max_citations > 0:
                            score += citation_count / max_citations
                    elif indicator == "source_reliability":
                        score += entity[indicator]

            if score > best_score:
                best_score = score
                best_entity = entity

        return best_entity.copy()

    def _merge_all_fields(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge all fields from entities.

        Args:
            entities: List of entities

        Returns:
            Merged entity
        """
        merged = {}

        # Collect all fields
        all_fields = set()
        for entity in entities:
            all_fields.update(entity.keys())

        # Merge each field
        for field in all_fields:
            values = [
                e.get(field) for e in entities if field in e and e[field] is not None
            ]

            if not values:
                continue

            if len(values) == 1:
                merged[field] = values[0]
            else:
                # Merge strategy per field type
                if isinstance(values[0], (int, float)):
                    # Take average for numeric fields - handle edge cases
                    try:
                        merged[field] = float(np.mean(values))
                    except (ValueError, TypeError):
                        merged[field] = values[0]  # Fallback to first value
                elif isinstance(values[0], list):
                    # Combine lists
                    combined = []
                    for v in values:
                        combined.extend(v)
                    merged[field] = list(set(combined))  # Remove duplicates
                elif isinstance(values[0], dict):
                    # Merge dictionaries
                    merged_dict = {}
                    for v in values:
                        merged_dict.update(v)
                    merged[field] = merged_dict
                else:
                    # Take most common for other types
                    from collections import Counter

                    counter = Counter(values)
                    merged[field] = counter.most_common(1)[0][0]

        return merged

    def _resolve_conflicts(
        self,
        entities: List[Dict[str, Any]],
        merged: Dict[str, Any],
        strategy: MergeStrategy,
    ) -> List[Dict[str, Any]]:
        """Resolve conflicts in merge.

        Args:
            entities: Original entities
            merged: Merged entity
            strategy: Merge strategy used

        Returns:
            List of resolved conflicts
        """
        conflicts = []

        # Find fields with different values
        all_fields = set()
        for entity in entities:
            all_fields.update(entity.keys())

        for field in all_fields:
            values = [e.get(field) for e in entities if field in e]
            unique_values = set(str(v) for v in values if v is not None)

            if len(unique_values) > 1:
                conflicts.append(
                    {
                        "field": field,
                        "original_values": list(unique_values),
                        "merged_value": merged.get(field),
                        "resolution_method": strategy.value,
                    }
                )

        return conflicts

    def generate_report(
        self,
        duplicates: List[DuplicateCandidate],
        merges: List[MergeDecision],
        execution_time_ms: float,
        total_entities: int,
    ) -> DeduplicationReport:
        """Generate deduplication report.

        Args:
            duplicates: Found duplicates
            merges: Performed merges
            execution_time_ms: Execution time
            total_entities: Total entities processed

        Returns:
            Deduplication report
        """
        report_id = f"dedup-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Count statistics
        duplicates_merged = len(merges)
        duplicates_skipped = len(duplicates) - duplicates_merged
        conflicts = sum(len(m.conflicts_resolved) for m in merges)

        # Build details
        details = []

        # Add duplicate details
        for dup in duplicates[:100]:  # Limit to 100 for report
            details.append(
                {
                    "type": "duplicate_found",
                    "entity1": dup.entity1_id,
                    "entity2": dup.entity2_id,
                    "match_type": dup.match_type.value,
                    "similarity": dup.similarity_score,
                    "action": dup.suggested_action,
                }
            )

        # Add merge details
        for merge in merges[:50]:  # Limit to 50 for report
            details.append(
                {
                    "type": "merge_performed",
                    "entities": merge.entities,
                    "strategy": merge.strategy.value,
                    "conflicts": len(merge.conflicts_resolved),
                }
            )

        report = DeduplicationReport(
            report_id=report_id,
            total_entities=total_entities,
            duplicates_found=len(duplicates),
            duplicates_merged=duplicates_merged,
            duplicates_skipped=duplicates_skipped,
            conflicts_encountered=conflicts,
            execution_time_ms=execution_time_ms,
            details=details,
        )

        return report

    def hash_entity(self, entity: Dict[str, Any], fields: List[str]) -> str:
        """Generate hash for entity based on specified fields.

        Args:
            entity: Entity to hash
            fields: Fields to include in hash

        Returns:
            Hash string
        """
        # Create canonical representation
        values = []
        for field in sorted(fields):
            if field in entity:
                value = entity[field]
                if value is not None:
                    values.append(f"{field}:{value}")

        canonical = "|".join(values)

        # Generate hash
        return hashlib.sha256(canonical.encode()).hexdigest()

    def get_statistics(self) -> Dict[str, Any]:
        """Get deduplication statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "total_comparisons": self.stats["total_comparisons"],
            "exact_matches": self.stats["exact_matches"],
            "fuzzy_matches": self.stats["fuzzy_matches"],
            "semantic_matches": self.stats["semantic_matches"],
            "merges_performed": self.stats["merges_performed"],
            "conflicts_resolved": self.stats["conflicts_resolved"],
            "match_rates": {
                "exact": self.stats["exact_matches"]
                / max(1, self.stats["total_comparisons"]),
                "fuzzy": self.stats["fuzzy_matches"]
                / max(1, self.stats["total_comparisons"]),
                "semantic": self.stats["semantic_matches"]
                / max(1, self.stats["total_comparisons"]),
            },
        }

    def _validate_config(self):
        """Validate deduplication configuration."""
        try:
            # Validate threshold values
            if not 0 <= self.config["fuzzy_threshold"] <= 1:
                raise ConfigurationError("fuzzy_threshold must be between 0 and 1")

            if not 0 <= self.config["semantic_threshold"] <= 1:
                raise ConfigurationError("semantic_threshold must be between 0 and 1")

            # Validate field lists
            for field_list_name in [
                "exact_match_fields",
                "fuzzy_match_fields",
                "blocking_fields",
                "quality_indicators",
            ]:
                if not isinstance(self.config[field_list_name], list):
                    raise ConfigurationError(f"{field_list_name} must be a list")

                if not all(
                    isinstance(field, str) for field in self.config[field_list_name]
                ):
                    raise ConfigurationError(
                        f"All fields in {field_list_name} must be strings"
                    )

            logger.info("Deduplication configuration validated successfully")

        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            raise ConfigurationError(f"Invalid configuration: {e}")

    @lru_cache(maxsize=10000)
    def _cached_similarity_score(self, text1: str, text2: str) -> float:
        """Calculate similarity score with LRU caching.

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity score
        """
        try:
            # Use multiple similarity metrics
            ratio = difflib.SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

            # Token-based similarity
            tokens1 = set(text1.lower().split())
            tokens2 = set(text2.lower().split())

            if not tokens1 and not tokens2:
                return 1.0  # Both empty
            elif not tokens1 or not tokens2:
                return 0.0  # One empty

            jaccard = len(tokens1 & tokens2) / len(tokens1 | tokens2)

            return max(ratio, jaccard)

        except Exception as e:
            logger.error(f"Error calculating similarity: {e}")
            return 0.0

    def validate_entities(
        self, entities: List[Dict[str, Any]]
    ) -> Tuple[bool, List[str]]:
        """Validate entities before processing.

        Args:
            entities: Entities to validate

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        if not isinstance(entities, list):
            errors.append("entities must be a list")
            return False, errors

        if len(entities) == 0:
            errors.append("entities list cannot be empty")
            return False, errors

        for i, entity in enumerate(entities):
            if not isinstance(entity, dict):
                errors.append(f"Entity at index {i} must be a dictionary")
                continue

            # Check for required fields based on configuration
            if not any(
                field in entity
                for field in self.config["exact_match_fields"]
                + self.config["fuzzy_match_fields"]
            ):
                errors.append(f"Entity at index {i} missing all searchable fields")

        return len(errors) == 0, errors
