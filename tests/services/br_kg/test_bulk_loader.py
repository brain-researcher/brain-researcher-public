"""
Tests for NDJSON bulk loader.
"""

import json
import tempfile
from pathlib import Path

import pytest

from brain_researcher.services.br_kg.bulk_loader import (
    EntityValidator,
    LoaderConfig,
    NDJSONBulkLoader,
)


def test_entity_validator():
    """Test entity validation."""
    # Valid node
    node = {"type": "Concept", "id": "test", "name": "Test Concept"}
    valid, error = EntityValidator.validate_node(node)
    assert valid
    assert error is None

    # Claim-spine node should validate
    node = {"type": "Assumption", "id": "assumption:test", "text": "Tasks are stable"}
    valid, error = EntityValidator.validate_node(node)
    assert valid
    assert error is None

    # Invalid node - missing required field
    node = {"type": "Concept", "name": "Test"}
    valid, error = EntityValidator.validate_node(node)
    assert not valid
    assert "Missing required fields" in error

    # Valid relationship
    rel = {
        "type": "MEASURES",
        "source_id": "concept1",
        "target_id": "task1",
        "confidence": 0.8,
        "source": "unit_test",
        "method": "assertion",
    }
    valid, error = EntityValidator.validate_relationship(rel)
    assert valid
    assert error is None

    # Richer claim-first relationship type should validate
    rel = {
        "type": "CHALLENGES_ASSUMPTION",
        "source_id": "claim:1",
        "target_id": "assumption:1",
        "confidence": 0.76,
    }
    valid, error = EntityValidator.validate_relationship(rel)
    assert valid
    assert error is None

    # Invalid relationship - bad confidence
    rel = {
        "type": "MEASURES",
        "source_id": "concept1",
        "target_id": "task1",
        "confidence": 1.5,
        "source": "unit_test",
        "method": "assertion",
    }
    valid, error = EntityValidator.validate_relationship(rel)
    assert not valid
    assert "Confidence must be between 0 and 1" in error

    # New GABRIEL relationship type should validate
    rel = {
        "type": "MENTIONS",
        "source_id": "pmid:1",
        "target_id": "concept:memory",
        "confidence": 0.92,
    }
    valid, error = EntityValidator.validate_relationship(rel)
    assert valid
    assert error is None

    # GWAS metadata nodes should validate
    for node in [
        {
            "type": "Study",
            "id": "study:pgc_mdd_001",
            "title": "PGC Major Depressive Disorder GWAS",
            "doi": "10.1234/pgc.mdd.001",
        },
        {
            "type": "DiseaseTrait",
            "id": "trait:mdd",
            "name": "Major depressive disorder",
            "phenotype_id": "MONDO:0001234",
            "category": "psychiatric",
        },
        {
            "type": "Population",
            "id": "population:eur",
            "name": "European ancestry",
            "ancestry": "EUR",
        },
        {
            "type": "Gene",
            "id": "gene:drd2",
            "symbol": "DRD2",
        },
        {
            "type": "RiskLocus",
            "id": "locus:rs123",
            "rsid": "rs123",
            "chromosome": "11",
            "position": 113000,
            "p_value": 1e-9,
        },
    ]:
        valid, error = EntityValidator.validate_node(node)
        assert valid
        assert error is None

    # GWAS metadata relationships should validate
    for rel in [
        {
            "type": "STUDIES",
            "source_id": "study:pgc_mdd_001",
            "target_id": "trait:mdd",
            "confidence": 0.97,
        },
        {
            "type": "HAS_POPULATION",
            "source_id": "study:pgc_mdd_001",
            "target_id": "population:eur",
            "confidence": 0.96,
        },
        {
            "type": "HAS_LEAD_LOCUS",
            "source_id": "study:pgc_mdd_001",
            "target_id": "locus:rs123",
            "confidence": 0.95,
        },
        {
            "type": "IMPLICATES_GENE",
            "source_id": "locus:rs123",
            "target_id": "gene:drd2",
            "confidence": 0.93,
        },
        {
            "type": "ASSOCIATED_WITH",
            "source_id": "locus:rs123",
            "target_id": "trait:mdd",
            "confidence": 0.94,
        },
    ]:
        valid, error = EntityValidator.validate_relationship(rel)
        assert valid
        assert error is None


def test_bulk_loader_basic(tmp_path, monkeypatch):
    """Test basic bulk loading."""
    # Create test NDJSON file
    test_file = tmp_path / "test.ndjson"

    entities = [
        {"type": "Concept", "id": "c1", "name": "Memory"},
        {"type": "Task", "id": "t1", "name": "N-back"},
        {
            "type": "MEASURES",
            "source_id": "c1",
            "target_id": "t1",
            "confidence": 0.9,
            "source": "ndjson",
            "method": "assertion",
        },
    ]

    with open(test_file, "w") as f:
        for entity in entities:
            f.write(json.dumps(entity) + "\n")

    # Mock database
    class MockDB:
        def __init__(self):
            self.nodes = []
            self.relationships = []

        def create_node(self, node_type, properties):
            self.nodes.append({"type": node_type, **properties})
            return len(self.nodes)

        def create_relationship(self, source, target, rel_type, properties):
            self.relationships.append(
                {"source": source, "target": target, "type": rel_type, **properties}
            )
            return len(self.relationships)

    db = MockDB()
    config = LoaderConfig(batch_size=2)
    loader = NDJSONBulkLoader(db, config)

    # Load file
    stats = loader.load_file(test_file)

    # Check results
    assert stats.successful_nodes == 2
    assert stats.successful_relationships == 1
    assert stats.failed_lines == 0
    assert len(db.nodes) == 2
    assert len(db.relationships) == 1


def test_bulk_loader_validation(tmp_path):
    """Test validation in bulk loader."""
    test_file = tmp_path / "invalid.ndjson"

    entities = [
        {"type": "InvalidType", "id": "x1"},  # Invalid node type
        {"type": "Concept"},  # Missing id
        {"type": "INVALID_REL", "source_id": "a", "target_id": "b"},  # Invalid rel type
    ]

    with open(test_file, "w") as f:
        for entity in entities:
            f.write(json.dumps(entity) + "\n")

    class MockDB:
        def create_node(self, *args):
            return 1

        def create_relationship(self, *args):
            return 1

    db = MockDB()
    config = LoaderConfig(validate=True, skip_errors=True)
    loader = NDJSONBulkLoader(db, config)

    stats = loader.load_file(test_file)

    # All should fail validation
    assert stats.successful_nodes == 0
    assert stats.successful_relationships == 0
    assert stats.failed_lines == 3
    assert len(stats.errors) == 3


def test_bulk_loader_deduplication(tmp_path):
    """Test deduplication in bulk loader."""
    test_file = tmp_path / "duplicates.ndjson"

    # Create file with duplicates
    entities = [
        {"type": "Concept", "id": "c1", "name": "Memory"},
        {"type": "Concept", "id": "c1", "name": "Memory"},  # Duplicate
        {"type": "Task", "id": "t1", "name": "N-back"},
        {
            "type": "MEASURES",
            "source_id": "c1",
            "target_id": "t1",
            "source": "ndjson",
            "method": "assertion",
        },
        {
            "type": "MEASURES",
            "source_id": "c1",
            "target_id": "t1",
            "source": "ndjson",
            "method": "assertion",
        },  # Duplicate
    ]

    with open(test_file, "w") as f:
        for entity in entities:
            f.write(json.dumps(entity) + "\n")

    class MockDB:
        def __init__(self):
            self.created = []

        def create_node(self, node_type, properties):
            self.created.append(("node", node_type, properties))
            return 1

        def create_relationship(self, source, target, rel_type, properties):
            self.created.append(("rel", source, target, rel_type))
            return 1

    db = MockDB()
    config = LoaderConfig(deduplicate=True)
    loader = NDJSONBulkLoader(db, config)

    stats = loader.load_file(test_file)

    # Should skip duplicates
    assert stats.successful_nodes == 2  # Only unique nodes
    assert stats.successful_relationships == 1  # Only unique relationship
    assert stats.skipped_duplicates == 2


def test_bulk_loader_large_batch():
    """Test loading with large batches."""
    import io

    # Create in-memory NDJSON
    entities = []
    for i in range(10000):
        entities.append(
            {"type": "Concept", "id": f"concept_{i}", "name": f"Concept {i}"}
        )

    # Mock database
    class MockDB:
        def __init__(self):
            self.batch_sizes = []

        def create_node(self, node_type, properties):
            return 1

    db = MockDB()
    config = LoaderConfig(batch_size=1000, validate=False)
    loader = NDJSONBulkLoader(db, config)

    # Test batching logic
    batch = []
    for entity in entities[:2500]:
        batch.append(entity)
        if len(batch) >= config.batch_size:
            count = loader._process_node_batch(batch)
            assert count == len(batch)
            batch = []

    # Process remaining
    if batch:
        count = loader._process_node_batch(batch)
        assert count == len(batch)
