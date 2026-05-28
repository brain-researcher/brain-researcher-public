"""Comprehensive unit tests for INGEST-021 Data Deduplication.

This test suite covers:
- Duplicate detection (exact, fuzzy, semantic matching)
- Entity blocking and comparison strategies  
- Merge strategies and conflict resolution
- Report generation and statistics
- Hash generation and performance
- Edge cases and error handling
"""

import hashlib
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, project_root)

from brain_researcher.core.ingestion.deduplication.data_deduplication import (
    DataDeduplication,
    DeduplicationReport,
    DuplicateCandidate,
    MatchType,
    MergeDecision,
    MergeStrategy,
)


class MockNeo4jDriver:
    """Mock Neo4j driver for testing."""
    
    def __init__(self):
        self.session_calls = []
        
    def session(self):
        """Mock session method."""
        return MockNeo4jSession()


class MockNeo4jSession:
    """Mock Neo4j session for testing."""
    
    def __init__(self):
        self.queries = []
        
    def run(self, query, parameters=None):
        """Mock run method."""
        self.queries.append({"query": query, "params": parameters})
        return MockResult()
        
    def close(self):
        """Mock close method."""
        pass


class MockResult:
    """Mock Neo4j result for testing."""
    
    def data(self):
        """Mock data method."""
        return []


class MockRedis:
    """Mock Redis client for testing."""
    
    def __init__(self):
        self.data = {}
        
    async def get(self, key):
        """Mock get method."""
        return self.data.get(key)
        
    async def set(self, key, value):
        """Mock set method."""
        self.data[key] = value


@pytest.fixture
def mock_neo4j_driver():
    """Create a mock Neo4j driver."""
    return MockNeo4jDriver()


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    return MockRedis()


@pytest.fixture
def deduplication_system(mock_neo4j_driver, mock_redis):
    """Create a deduplication system instance."""
    return DataDeduplication(
        neo4j_driver=mock_neo4j_driver,
        redis_client=mock_redis
    )


@pytest.fixture
def sample_entities():
    """Create sample entities for testing."""
    return [
        {
            "id": "1",
            "title": "Functional connectivity during rest",
            "type": "Study",
            "year": 2020,
            "citation_count": 150,
            "doi": "10.1000/test1"
        },
        {
            "id": "2", 
            "title": "Functional connectivity at rest",
            "type": "Study",
            "year": 2020,
            "citation_count": 145,
            "doi": "10.1000/test2"
        },
        {
            "id": "3",
            "title": "Working memory and attention",
            "type": "Study", 
            "year": 2019,
            "citation_count": 200,
            "pmid": "12345678"
        },
        {
            "id": "4",
            "title": "Completely different study",
            "type": "Analysis",
            "year": 2021,
            "citation_count": 50
        }
    ]


@pytest.fixture
def entities_with_embeddings():
    """Create entities with embedding vectors."""
    return [
        {
            "id": "1",
            "title": "Neural networks in cognition",
            "embedding": [0.1, 0.2, 0.3, 0.4, 0.5]
        },
        {
            "id": "2",
            "title": "Cognitive neural networks",
            "embedding": [0.12, 0.18, 0.32, 0.38, 0.52]  # Similar to first
        },
        {
            "id": "3", 
            "title": "Molecular biology methods",
            "embedding": [0.9, 0.8, 0.7, 0.6, 0.5]  # Very different
        }
    ]


class TestDataDeduplication:
    """Test cases for DataDeduplication class."""
    
    def test_initialization(self):
        """Test deduplication system initialization."""
        system = DataDeduplication()
        
        assert system.driver is None
        assert system.redis is None
        assert "exact_match_fields" in system.config
        assert "fuzzy_match_fields" in system.config
        assert system.config["fuzzy_threshold"] == 0.85
        assert system.stats["total_comparisons"] == 0
        
    def test_initialization_with_clients(self, mock_neo4j_driver, mock_redis):
        """Test initialization with Neo4j and Redis clients."""
        system = DataDeduplication(mock_neo4j_driver, mock_redis)
        
        assert system.driver == mock_neo4j_driver
        assert system.redis == mock_redis
        
    def test_find_duplicates_empty_list(self, deduplication_system):
        """Test duplicate detection with empty entity list."""
        duplicates = deduplication_system.find_duplicates([], "Study")
        
        assert len(duplicates) == 0
        
    def test_find_duplicates_single_entity(self, deduplication_system):
        """Test duplicate detection with single entity."""
        entities = [{"id": "1", "title": "Single Study", "type": "Study"}]
        duplicates = deduplication_system.find_duplicates(entities, "Study")
        
        assert len(duplicates) == 0
        
    def test_create_blocks(self, deduplication_system, sample_entities):
        """Test entity blocking for efficient comparison."""
        blocks = deduplication_system._create_blocks(sample_entities, "Study")
        
        # Should have blocks based on type and year
        assert len(blocks) > 0
        
        # Check that entities are properly distributed
        study_2020_entities = []
        for block_key, entities in blocks.items():
            if "type:Study" in block_key and "year:2020" in block_key:
                study_2020_entities.extend(entities)
                
        # Should have the two similar studies from 2020
        assert len(study_2020_entities) >= 2
        
    def test_exact_match_by_doi(self, deduplication_system):
        """Test exact matching by DOI."""
        entity1 = {"id": "1", "doi": "10.1000/test123", "title": "Study A"}
        entity2 = {"id": "2", "doi": "10.1000/test123", "title": "Study B"}
        
        is_match, fields = deduplication_system._exact_match(entity1, entity2)
        
        assert is_match is True
        assert "doi" in fields
        
    def test_exact_match_by_pmid(self, deduplication_system):
        """Test exact matching by PMID."""
        entity1 = {"id": "1", "pmid": "12345678", "title": "Study A"}
        entity2 = {"id": "2", "pmid": "12345678", "title": "Study B"}
        
        is_match, fields = deduplication_system._exact_match(entity1, entity2)
        
        assert is_match is True
        assert "pmid" in fields
        
    def test_exact_match_case_insensitive(self, deduplication_system):
        """Test case-insensitive exact matching."""
        entity1 = {"id": "1", "doi": "10.1000/TEST123", "title": "Study A"}
        entity2 = {"id": "2", "doi": "10.1000/test123", "title": "Study B"}
        
        is_match, fields = deduplication_system._exact_match(entity1, entity2)
        
        assert is_match is True
        
    def test_exact_match_no_match(self, deduplication_system):
        """Test exact matching with different identifiers."""
        entity1 = {"id": "1", "doi": "10.1000/test123", "title": "Study A"}
        entity2 = {"id": "2", "doi": "10.1000/test456", "title": "Study B"}
        
        is_match, fields = deduplication_system._exact_match(entity1, entity2)
        
        assert is_match is False
        assert len(fields) == 0
        
    def test_fuzzy_match_high_similarity(self, deduplication_system):
        """Test fuzzy matching with high similarity."""
        entity1 = {"id": "1", "title": "Functional connectivity during rest"}
        entity2 = {"id": "2", "title": "Functional connectivity at rest"}
        
        score, fields = deduplication_system._fuzzy_match(entity1, entity2)
        
        assert score > 0.8
        assert "title" in fields
        
    def test_fuzzy_match_low_similarity(self, deduplication_system):
        """Test fuzzy matching with low similarity."""
        entity1 = {"id": "1", "title": "Functional connectivity during rest"}
        entity2 = {"id": "2", "title": "Molecular biology methods"}
        
        score, fields = deduplication_system._fuzzy_match(entity1, entity2)
        
        assert score < 0.5
        assert len(fields) == 0
        
    def test_fuzzy_match_empty_fields(self, deduplication_system):
        """Test fuzzy matching with empty fields."""
        entity1 = {"id": "1", "title": ""}
        entity2 = {"id": "2", "title": ""}
        
        score, fields = deduplication_system._fuzzy_match(entity1, entity2)
        
        assert score == 0
        assert len(fields) == 0
        
    def test_semantic_match_with_embeddings(self, deduplication_system):
        """Test semantic matching using embeddings."""
        entity1 = {"id": "1", "embedding": [1.0, 0.0, 0.0]}
        entity2 = {"id": "2", "embedding": [0.9, 0.1, 0.0]}  # Similar
        
        score = deduplication_system._semantic_match(entity1, entity2)
        
        assert score > 0.8  # Should be high similarity
        
    def test_semantic_match_orthogonal_vectors(self, deduplication_system):
        """Test semantic matching with orthogonal vectors."""
        entity1 = {"id": "1", "embedding": [1.0, 0.0, 0.0]}
        entity2 = {"id": "2", "embedding": [0.0, 1.0, 0.0]}  # Orthogonal
        
        score = deduplication_system._semantic_match(entity1, entity2)
        
        assert abs(score) < 0.1  # Should be near zero
        
    def test_semantic_match_no_embeddings(self, deduplication_system):
        """Test semantic matching without embeddings."""
        entity1 = {"id": "1", "title": "Study A"}
        entity2 = {"id": "2", "title": "Study B"}
        
        score = deduplication_system._semantic_match(entity1, entity2)
        
        assert score == 0
        
    def test_find_conflicts(self, deduplication_system):
        """Test conflict detection between entities."""
        entity1 = {
            "id": "1",
            "title": "Study A",
            "year": 2020,
            "score": 100,
            "status": "published"
        }
        entity2 = {
            "id": "2", 
            "title": "Study A",
            "year": 2021,  # Different year
            "score": 95,   # Different score (within tolerance)
            "status": "draft"  # Different status
        }
        
        conflicts = deduplication_system._find_conflicts(entity1, entity2)
        
        assert "year" in conflicts
        assert "status" in conflicts
        # score difference is within 10% tolerance, so shouldn't be a conflict
        
    def test_find_conflicts_numeric_tolerance(self, deduplication_system):
        """Test numeric conflict detection with tolerance."""
        entity1 = {"id": "1", "score": 100.0}
        entity2 = {"id": "2", "score": 105.0}  # 5% difference, within tolerance
        
        conflicts = deduplication_system._find_conflicts(entity1, entity2)
        
        assert "score" not in conflicts
        
        entity3 = {"id": "3", "score": 120.0}  # 20% difference, above tolerance
        conflicts2 = deduplication_system._find_conflicts(entity1, entity3)
        
        assert "score" in conflicts2
        
    def test_compare_entities_exact_match(self, deduplication_system, sample_entities):
        """Test entity comparison with exact match."""
        # Create entities with same DOI
        entity1 = sample_entities[0].copy()
        entity2 = sample_entities[1].copy()
        entity2["doi"] = entity1["doi"]  # Make DOIs match
        
        candidate = deduplication_system._compare_entities(
            entity1, entity2, "Study", [MatchType.EXACT, MatchType.FUZZY]
        )
        
        assert candidate is not None
        assert candidate.match_type == MatchType.EXACT
        assert candidate.similarity_score == 1.0
        assert candidate.suggested_action == "merge"
        
    def test_compare_entities_fuzzy_match(self, deduplication_system, sample_entities):
        """Test entity comparison with fuzzy match."""
        entity1 = sample_entities[0]  # "Functional connectivity during rest"
        entity2 = sample_entities[1]  # "Functional connectivity at rest"
        
        candidate = deduplication_system._compare_entities(
            entity1, entity2, "Study", [MatchType.FUZZY]
        )
        
        assert candidate is not None
        assert candidate.match_type == MatchType.FUZZY
        assert candidate.similarity_score > 0.85
        
    def test_compare_entities_no_match(self, deduplication_system, sample_entities):
        """Test entity comparison with no match."""
        entity1 = sample_entities[0]  # Study about connectivity
        entity2 = sample_entities[3]  # Completely different study
        
        candidate = deduplication_system._compare_entities(
            entity1, entity2, "Study", [MatchType.EXACT, MatchType.FUZZY]
        )
        
        assert candidate is None
        
    def test_find_duplicates_integration(self, deduplication_system, sample_entities):
        """Test complete duplicate finding process."""
        duplicates = deduplication_system.find_duplicates(
            sample_entities, "Study", [MatchType.EXACT, MatchType.FUZZY]
        )
        
        # Should find the two similar connectivity studies
        assert len(duplicates) >= 1
        
        # Find the duplicate pair
        connectivity_duplicate = None
        for dup in duplicates:
            if ("1" in [dup.entity1_id, dup.entity2_id] and 
                "2" in [dup.entity1_id, dup.entity2_id]):
                connectivity_duplicate = dup
                break
                
        assert connectivity_duplicate is not None
        assert connectivity_duplicate.match_type in [MatchType.EXACT, MatchType.FUZZY]
        
    def test_merge_keep_first_strategy(self, deduplication_system, sample_entities):
        """Test merging with KEEP_FIRST strategy."""
        entities_to_merge = sample_entities[:2]
        
        decision = deduplication_system.merge_entities(
            entities_to_merge, MergeStrategy.KEEP_FIRST
        )
        
        assert decision.strategy == MergeStrategy.KEEP_FIRST
        assert decision.merged_entity["id"] == entities_to_merge[0]["id"]
        assert len(decision.entities) == 2
        
    def test_merge_keep_last_strategy(self, deduplication_system, sample_entities):
        """Test merging with KEEP_LAST strategy."""
        entities_to_merge = sample_entities[:2]
        
        decision = deduplication_system.merge_entities(
            entities_to_merge, MergeStrategy.KEEP_LAST
        )
        
        assert decision.strategy == MergeStrategy.KEEP_LAST
        assert decision.merged_entity["id"] == entities_to_merge[-1]["id"]
        
    def test_merge_highest_quality_strategy(self, deduplication_system, sample_entities):
        """Test merging with KEEP_HIGHEST_QUALITY strategy."""
        entities_to_merge = sample_entities[:3]  # Include entity with highest citation count
        
        decision = deduplication_system.merge_entities(
            entities_to_merge, MergeStrategy.KEEP_HIGHEST_QUALITY
        )
        
        assert decision.strategy == MergeStrategy.KEEP_HIGHEST_QUALITY
        # Should pick entity with ID "3" (highest citation count: 200)
        assert decision.merged_entity["citation_count"] == 200
        
    def test_merge_all_fields_strategy(self, deduplication_system):
        """Test merging with MERGE_ALL strategy."""
        entities = [
            {
                "id": "1",
                "title": "Study A",
                "score": 10,
                "tags": ["a", "b"],
                "metadata": {"source": "db1"}
            },
            {
                "id": "2",
                "title": "Study A", 
                "score": 20,
                "tags": ["b", "c"],
                "metadata": {"version": "1.0"}
            }
        ]
        
        decision = deduplication_system.merge_entities(
            entities, MergeStrategy.MERGE_ALL
        )
        
        merged = decision.merged_entity
        
        assert decision.strategy == MergeStrategy.MERGE_ALL
        assert merged["title"] == "Study A"  # Same in both
        assert merged["score"] == 15  # Average of 10 and 20
        assert set(merged["tags"]) == {"a", "b", "c"}  # Union of tags
        assert "source" in merged["metadata"]
        assert "version" in merged["metadata"]
        
    def test_merge_manual_strategy_not_implemented(self, deduplication_system, sample_entities):
        """Test that MANUAL strategy raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            deduplication_system.merge_entities(
                sample_entities[:2], MergeStrategy.MANUAL
            )
            
    def test_select_highest_quality(self, deduplication_system):
        """Test highest quality entity selection."""
        entities = [
            {
                "id": "1",
                "citation_count": 100,
                "completeness": {"field1": 1, "field2": None},  # 50% complete
                "source_reliability": 0.8
            },
            {
                "id": "2", 
                "citation_count": 50,
                "completeness": {"field1": 1, "field2": 1, "field3": 1},  # 100% complete
                "source_reliability": 0.9
            }
        ]
        
        # Add completeness calculation
        for entity in entities:
            if "completeness" in entity:
                non_null = sum(1 for v in entity["completeness"].values() if v is not None)
                entity["completeness"] = non_null / len(entity["completeness"])
        
        best = deduplication_system._select_highest_quality(entities)
        
        # Second entity should win due to higher completeness and reliability
        assert best["id"] == "2"
        
    def test_merge_all_fields_complex_types(self, deduplication_system):
        """Test merging with complex data types."""
        entities = [
            {
                "id": "1",
                "numbers": [1, 2, 3],
                "nested": {"a": 1, "b": 2}
            },
            {
                "id": "2",
                "numbers": [3, 4, 5], 
                "nested": {"b": 3, "c": 4}
            }
        ]
        
        merged = deduplication_system._merge_all_fields(entities)
        
        # Lists should be combined and deduplicated
        assert set(merged["numbers"]) == {1, 2, 3, 4, 5}
        
        # Dictionaries should be merged
        assert merged["nested"]["a"] == 1
        assert merged["nested"]["b"] == 3  # Second value overwrites
        assert merged["nested"]["c"] == 4
        
    def test_resolve_conflicts(self, deduplication_system):
        """Test conflict resolution tracking."""
        entities = [
            {"id": "1", "title": "A", "year": 2020, "score": 10},
            {"id": "2", "title": "A", "year": 2021, "score": 15}
        ]
        
        merged = {"id": "merged", "title": "A", "year": 2020, "score": 12.5}
        
        conflicts = deduplication_system._resolve_conflicts(
            entities, merged, MergeStrategy.MERGE_ALL
        )
        
        # Should detect year and score conflicts
        year_conflict = next((c for c in conflicts if c["field"] == "year"), None)
        score_conflict = next((c for c in conflicts if c["field"] == "score"), None)
        
        assert year_conflict is not None
        assert set(year_conflict["original_values"]) == {"2020", "2021"}
        assert year_conflict["merged_value"] == 2020
        
        assert score_conflict is not None
        assert score_conflict["merged_value"] == 12.5
        
    def test_hash_entity(self, deduplication_system):
        """Test entity hashing."""
        entity = {
            "id": "1",
            "title": "Test Study",
            "year": 2020,
            "extra_field": "ignored"
        }
        
        hash1 = deduplication_system.hash_entity(entity, ["id", "title", "year"])
        hash2 = deduplication_system.hash_entity(entity, ["id", "title", "year"])
        
        # Same entity, same fields -> same hash
        assert hash1 == hash2
        
        # Different field order should produce same hash (sorted)
        hash3 = deduplication_system.hash_entity(entity, ["year", "title", "id"])
        assert hash1 == hash3
        
        # Different fields -> different hash
        hash4 = deduplication_system.hash_entity(entity, ["id", "title"])
        assert hash1 != hash4
        
    def test_hash_entity_missing_fields(self, deduplication_system):
        """Test hashing with missing fields."""
        entity = {"id": "1", "title": "Test"}
        
        hash_result = deduplication_system.hash_entity(
            entity, ["id", "title", "missing_field"]
        )
        
        # Should not include missing field in hash
        expected_canonical = "id:1|title:Test"
        expected_hash = hashlib.sha256(expected_canonical.encode()).hexdigest()
        
        assert hash_result == expected_hash
        
    def test_generate_report(self, deduplication_system):
        """Test deduplication report generation."""
        # Create sample duplicates and merges
        duplicates = [
            DuplicateCandidate(
                entity1_id="1",
                entity2_id="2",
                match_type=MatchType.FUZZY,
                similarity_score=0.9,
                matching_fields=["title"],
                suggested_action="merge"
            ),
            DuplicateCandidate(
                entity1_id="3",
                entity2_id="4", 
                match_type=MatchType.EXACT,
                similarity_score=1.0,
                matching_fields=["doi"],
                suggested_action="merge"
            )
        ]
        
        merges = [
            MergeDecision(
                decision_id="merge_1",
                entities=["1", "2"],
                strategy=MergeStrategy.MERGE_ALL,
                merged_entity={"id": "merged_1"},
                conflicts_resolved=[{"field": "year"}]
            )
        ]
        
        report = deduplication_system.generate_report(
            duplicates, merges, 1500.0, 1000
        )
        
        assert report.total_entities == 1000
        assert report.duplicates_found == 2
        assert report.duplicates_merged == 1
        assert report.duplicates_skipped == 1
        assert report.conflicts_encountered == 1
        assert report.execution_time_ms == 1500.0
        
        # Check details
        assert len(report.details) <= 150  # Limited to 150 total
        duplicate_details = [d for d in report.details if d["type"] == "duplicate_found"]
        merge_details = [d for d in report.details if d["type"] == "merge_performed"]
        
        assert len(duplicate_details) == 2
        assert len(merge_details) == 1
        
    def test_get_statistics(self, deduplication_system):
        """Test statistics collection."""
        # Set up test statistics
        deduplication_system.stats["total_comparisons"] = 1000
        deduplication_system.stats["exact_matches"] = 50
        deduplication_system.stats["fuzzy_matches"] = 30
        deduplication_system.stats["semantic_matches"] = 20
        deduplication_system.stats["merges_performed"] = 40
        deduplication_system.stats["conflicts_resolved"] = 15
        
        stats = deduplication_system.get_statistics()
        
        assert stats["total_comparisons"] == 1000
        assert stats["exact_matches"] == 50
        assert stats["fuzzy_matches"] == 30
        assert stats["semantic_matches"] == 20
        assert stats["merges_performed"] == 40
        assert stats["conflicts_resolved"] == 15
        
        # Check match rates
        assert stats["match_rates"]["exact"] == 50 / 1000
        assert stats["match_rates"]["fuzzy"] == 30 / 1000
        assert stats["match_rates"]["semantic"] == 20 / 1000
        
    def test_performance_large_dataset(self, deduplication_system):
        """Test performance with larger dataset."""
        # Generate larger dataset
        entities = []
        for i in range(100):
            entities.append({
                "id": str(i),
                "title": f"Study {i // 10}",  # Create groups of similar titles
                "type": "Study",
                "year": 2020 + (i % 3),
                "category": f"Category {i % 5}"
            })
            
        start_time = time.time()
        duplicates = deduplication_system.find_duplicates(entities, "Study")
        end_time = time.time()
        
        execution_time = end_time - start_time
        
        # Should complete in reasonable time (less than 5 seconds)
        assert execution_time < 5.0
        
        # Should find some duplicates due to similar titles
        assert len(duplicates) > 0
        
    def test_edge_case_empty_values(self, deduplication_system):
        """Test handling of empty/None values."""
        entities = [
            {
                "id": "1",
                "title": "",
                "description": None,
                "year": 2020
            },
            {
                "id": "2", 
                "title": None,
                "description": "",
                "year": 2020
            }
        ]
        
        duplicates = deduplication_system.find_duplicates(entities, "Study")
        
        # Should handle empty values gracefully without crashing
        # Should not match due to empty titles
        assert isinstance(duplicates, list)
        
    def test_edge_case_missing_required_fields(self, deduplication_system):
        """Test handling of entities missing required fields."""
        entities = [
            {"title": "Study without ID"},  # Missing ID
            {"id": "2"},  # Missing title
            {"id": "3", "title": "Complete study"}
        ]
        
        duplicates = deduplication_system.find_duplicates(entities, "Study")
        
        # Should handle missing fields gracefully
        assert isinstance(duplicates, list)
        
    def test_concurrent_duplicate_detection(self, deduplication_system):
        """Test thread safety of duplicate detection."""
        import threading
        
        entities = [
            {"id": f"{i}", "title": f"Study {i % 5}", "type": "Study"}
            for i in range(50)
        ]
        
        results = []
        
        def detect_duplicates():
            duplicates = deduplication_system.find_duplicates(entities, "Study")
            results.append(len(duplicates))
            
        threads = []
        for _ in range(3):
            thread = threading.Thread(target=detect_duplicates)
            threads.append(thread)
            thread.start()
            
        for thread in threads:
            thread.join()
            
        # All threads should complete successfully
        assert len(results) == 3
        
        # Results should be consistent
        assert all(r == results[0] for r in results)


class TestDuplicateCandidate:
    """Test cases for DuplicateCandidate dataclass."""
    
    def test_duplicate_candidate_creation(self):
        """Test DuplicateCandidate creation."""
        candidate = DuplicateCandidate(
            entity1_id="entity_1",
            entity2_id="entity_2", 
            match_type=MatchType.FUZZY,
            similarity_score=0.85,
            matching_fields=["title", "description"],
            conflicts=["year"],
            suggested_action="review"
        )
        
        assert candidate.entity1_id == "entity_1"
        assert candidate.entity2_id == "entity_2"
        assert candidate.match_type == MatchType.FUZZY
        assert candidate.similarity_score == 0.85
        assert candidate.matching_fields == ["title", "description"]
        assert candidate.conflicts == ["year"]
        assert candidate.suggested_action == "review"


class TestMergeDecision:
    """Test cases for MergeDecision dataclass."""
    
    def test_merge_decision_creation(self):
        """Test MergeDecision creation."""
        timestamp = datetime.now()
        
        decision = MergeDecision(
            decision_id="merge_123",
            entities=["entity_1", "entity_2", "entity_3"],
            strategy=MergeStrategy.MERGE_ALL,
            merged_entity={"id": "merged", "title": "Merged Study"},
            conflicts_resolved=[{"field": "year", "resolution": "average"}],
            timestamp=timestamp,
            user="test_user"
        )
        
        assert decision.decision_id == "merge_123"
        assert len(decision.entities) == 3
        assert decision.strategy == MergeStrategy.MERGE_ALL
        assert decision.merged_entity["id"] == "merged"
        assert len(decision.conflicts_resolved) == 1
        assert decision.timestamp == timestamp
        assert decision.user == "test_user"


class TestDeduplicationReport:
    """Test cases for DeduplicationReport dataclass."""
    
    def test_deduplication_report_creation(self):
        """Test DeduplicationReport creation."""
        timestamp = datetime.now()
        
        report = DeduplicationReport(
            report_id="report_456",
            total_entities=1000,
            duplicates_found=50,
            duplicates_merged=40,
            duplicates_skipped=10,
            conflicts_encountered=15,
            execution_time_ms=2500.0,
            timestamp=timestamp,
            details=[
                {"type": "duplicate_found", "entities": ["1", "2"]},
                {"type": "merge_performed", "result": "success"}
            ]
        )
        
        assert report.report_id == "report_456"
        assert report.total_entities == 1000
        assert report.duplicates_found == 50
        assert report.duplicates_merged == 40
        assert report.duplicates_skipped == 10
        assert report.conflicts_encountered == 15
        assert report.execution_time_ms == 2500.0
        assert report.timestamp == timestamp
        assert len(report.details) == 2