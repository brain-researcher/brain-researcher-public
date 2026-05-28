"""
Integration tests for all BR-KG features working together.
"""

import json
import os
from datetime import datetime

import pytest

if not os.getenv("NEO4J_URI") or not os.getenv("NEO4J_PASSWORD"):
    pytest.skip(
        "NEO4J_URI/NEO4J_PASSWORD required for Neo4j-only tests",
        allow_module_level=True,
    )

from brain_researcher.services.neurokg.bulk_loader import LoaderConfig, NDJSONBulkLoader
from brain_researcher.services.neurokg.db.bootstrap import get_db
from brain_researcher.services.neurokg.gql_schema.schema_simple import build_schema
from brain_researcher.services.neurokg.persisted_queries import (
    PersistedQueryExecutor,
)


class TestFullIntegration:
    """Test all components working together."""
    
    @pytest.fixture
    def setup_complete(self, tmp_path, monkeypatch):
        """Complete setup with all components."""
        # Set up database
        db = get_db()
        schema = build_schema()
        executor = PersistedQueryExecutor(schema)
        
        # Create NDJSON test data
        test_file = tmp_path / "test_data.ndjson"
        test_data = [
            # Concepts
            {"type": "Concept", "id": "c_memory", "name": "memory", "definition": "Cognitive process"},
            {"type": "Concept", "id": "c_attention", "name": "attention", "definition": "Focus process"},
            {"type": "Concept", "id": "c_executive", "name": "executive function", "definition": "Control process"},
            
            # Tasks
            {"type": "Task", "id": "t_nback", "name": "n-back", "description": "Working memory task"},
            {"type": "Task", "id": "t_stroop", "name": "Stroop", "description": "Interference task"},
            {"type": "Task", "id": "t_gonogo", "name": "Go/No-Go", "description": "Inhibition task"},
            
            # Regions
            {"type": "Region", "id": "r_pfc", "name": "prefrontal cortex", "abbreviation": "PFC"},
            {"type": "Region", "id": "r_acc", "name": "anterior cingulate", "abbreviation": "ACC"},
            {"type": "Region", "id": "r_dlpfc", "name": "dorsolateral PFC", "abbreviation": "DLPFC"},
            
            # Publications
            {"type": "Publication", "id": "p_001", "pmid": "12345678", "title": "Memory networks", "year": 2023},
            {"type": "Publication", "id": "p_002", "pmid": "87654321", "title": "Attention systems", "year": 2025},
            
            # Datasets
            {"type": "Dataset", "id": "d_001", "name": "Memory Study", "accession": "ds000001", "subject_count": 30},
            {"type": "Dataset", "id": "d_002", "name": "Attention Study", "accession": "ds000002", "subject_count": 25},
            
            # Relationships
            {"type": "MEASURES", "source_id": "c_memory", "target_id": "t_nback", "confidence": 0.95, "source": "CogAtlas", "method": "assertion"},
            {"type": "MEASURES", "source_id": "c_attention", "target_id": "t_stroop", "confidence": 0.90, "source": "CogAtlas", "method": "assertion"},
            {"type": "MEASURES", "source_id": "c_executive", "target_id": "t_gonogo", "confidence": 0.85, "source": "Manual", "method": "manual_annotation"},
            {"type": "ACTIVATES", "source_id": "t_nback", "target_id": "r_pfc", "confidence": 0.8, "source": "PubMed"},
            {"type": "ACTIVATES", "source_id": "t_stroop", "target_id": "r_acc", "confidence": 0.75, "source": "PubMed"},
            {"type": "RELATED_TO", "source_id": "c_memory", "target_id": "c_executive", "confidence": 0.7},
            {"type": "USES_TASK", "source_id": "d_001", "target_id": "t_nback", "source": "OpenNeuro"},
            {"type": "DERIVED_FROM", "source_id": "p_001", "target_id": "d_001", "source": "Manual"},
        ]
        
        with open(test_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')
        
        return {
            "db": db,
            "schema": schema,
            "executor": executor,
            "test_file": test_file,
            "tmp_path": tmp_path
        }
    
    def test_bulk_load_then_query(self, setup_complete):
        """Test bulk loading followed by GraphQL queries."""
        db = setup_complete["db"]
        schema = setup_complete["schema"]
        test_file = setup_complete["test_file"]
        
        # Step 1: Bulk load data
        config = LoaderConfig(batch_size=10, validate=True)
        loader = NDJSONBulkLoader(db, config)
        stats = loader.load_file(test_file)
        
        # Verify load statistics
        assert stats.successful_nodes >= 11  # At least our test nodes
        assert stats.successful_relationships >= 8  # At least our test relationships
        assert stats.failed_lines == 0
        
        # Step 2: Query loaded data via GraphQL
        query = """
        query {
            concepts {
                id
                name
            }
            tasks {
                id
                name
            }
        }
        """
        result = schema.execute_sync(query)
        assert result.errors is None
        
        # Verify data was loaded
        concepts = result.data["concepts"]
        assert len(concepts) >= 3
        concept_names = {c["name"] for c in concepts}
        assert "memory" in concept_names
        assert "attention" in concept_names
        
        tasks = result.data["tasks"]
        assert len(tasks) >= 3
        task_names = {t["name"] for t in tasks}
        assert "n-back" in task_names
        assert "Stroop" in task_names
    
    def test_create_via_graphql_then_query(self, setup_complete):
        """Test creating data via GraphQL mutations then querying."""
        schema = setup_complete["schema"]
        
        # Step 1: Create entities via mutations
        mutations = [
            """
            mutation {
                createConcept(id: "c_new", name: "new concept") {
                    id
                    name
                }
            }
            """,
            """
            mutation {
                createTask(id: "t_new", name: "new task") {
                    id
                    name
                }
            }
            """,
            """
            mutation {
                createRelationship(
                    sourceId: "c_new",
                    targetId: "t_new",
                    relType: "MEASURES",
                    confidence: 0.95,
                    source: "Test"
                ) {
                    type
                    confidence
                }
            }
            """
        ]
        
        for mutation in mutations:
            result = schema.execute_sync(mutation)
            assert result.errors is None
        
        # Step 2: Query created data
        query = """
        query {
            concepts(name: "new concept") {
                id
                name
            }
            tasks(name: "new task") {
                id
                name
            }
        }
        """
        result = schema.execute_sync(query)
        assert result.errors is None
        
        # Verify entities exist
        assert len(result.data["concepts"]) >= 1
        assert result.data["concepts"][0]["name"] == "new concept"
        assert len(result.data["tasks"]) >= 1
        assert result.data["tasks"][0]["name"] == "new task"
    
    def test_persisted_queries_with_loaded_data(self, setup_complete):
        """Test persisted queries work with bulk-loaded data."""
        db = setup_complete["db"]
        executor = setup_complete["executor"]
        test_file = setup_complete["test_file"]
        
        # Load data first
        loader = NDJSONBulkLoader(db, LoaderConfig())
        loader.load_file(test_file)
        
        # Test listing queries
        all_queries = executor.list_queries()
        assert len(all_queries) == 20
        
        # Test getting a specific query
        query = executor.get_query("Q1_TASK_TO_REGION")
        assert query is not None
        assert query.name == "Task to Brain Region"
    
    def test_end_to_end_workflow(self, setup_complete):
        """Test complete workflow: load -> query -> mutate -> query."""
        db = setup_complete["db"]
        schema = setup_complete["schema"]
        test_file = setup_complete["test_file"]
        
        # Step 1: Bulk load initial data
        loader = NDJSONBulkLoader(db, LoaderConfig())
        stats = loader.load_file(test_file)
        assert stats.successful_nodes > 0
        
        # Step 2: Query loaded data
        query1 = """
        query {
            concepts { id }
        }
        """
        result1 = schema.execute_sync(query1)
        initial_concept_count = len(result1.data["concepts"])
        
        # Step 3: Add new data via mutation
        mutation = """
        mutation {
            createConcept(id: "c_workflow", name: "workflow test") {
                id
            }
        }
        """
        result2 = schema.execute_sync(mutation)
        assert result2.errors is None
        
        # Step 4: Query again to verify
        result3 = schema.execute_sync(query1)
        new_concept_count = len(result3.data["concepts"])
        
        # Should have one more concept
        assert new_concept_count >= initial_concept_count + 1
        
        # Step 5: Create relationship
        rel_mutation = """
        mutation {
            createRelationship(
                sourceId: "c_workflow",
                targetId: "t_nback",
                relType: "RELATED_TO",
                confidence: 0.5,
                source: "Integration Test"
            ) {
                type
                confidence
                source
                timestamp
            }
        }
        """
        result4 = schema.execute_sync(rel_mutation)
        assert result4.errors is None
        
        rel = result4.data["createRelationship"]
        assert rel["type"] == "RELATED_TO"
        assert rel["confidence"] == 0.5
        assert rel["source"] == "Integration Test"
        assert rel["timestamp"] is not None
        
        # Verify timestamp is valid ISO format
        datetime.fromisoformat(rel["timestamp"])
    
    def test_performance_bulk_load(self, setup_complete):
        """Test performance of bulk loading."""
        db = setup_complete["db"]
        tmp_path = setup_complete["tmp_path"]
        
        # Create larger test file
        large_file = tmp_path / "large_test.ndjson"
        with open(large_file, 'w') as f:
            # Generate 1000 nodes
            for i in range(1000):
                node = {
                    "type": "Concept",
                    "id": f"perf_c_{i}",
                    "name": f"Concept {i}",
                    "definition": f"Definition {i}"
                }
                f.write(json.dumps(node) + '\n')
            
            # Generate 500 relationships
            for i in range(500):
                rel = {
                    "type": "RELATED_TO",
                    "source_id": f"perf_c_{i}",
                    "target_id": f"perf_c_{i+500}",
                    "confidence": 0.5 + (i % 50) / 100
                }
                f.write(json.dumps(rel) + '\n')
        
        # Load with performance tracking
        config = LoaderConfig(batch_size=100, validate=False)  # Skip validation for speed
        loader = NDJSONBulkLoader(db, config)
        
        stats = loader.load_file(large_file)
        
        # Check performance metrics
        assert stats.successful_nodes >= 1000
        assert stats.successful_relationships >= 500
        assert stats.throughput > 100  # Should process >100 entities/second
        
        print(f"Performance: {stats.throughput:.0f} entities/second")
        print(f"Duration: {stats.duration:.2f} seconds")
    
    def test_error_handling_integration(self, setup_complete):
        """Test error handling across components."""
        db = setup_complete["db"]
        schema = setup_complete["schema"]
        tmp_path = setup_complete["tmp_path"]
        
        # Create file with some invalid data
        mixed_file = tmp_path / "mixed.ndjson"
        with open(mixed_file, 'w') as f:
            # Valid
            f.write(json.dumps({"type": "Concept", "id": "valid", "name": "Valid"}) + '\n')
            # Invalid - missing required field
            f.write(json.dumps({"type": "Concept", "name": "Invalid"}) + '\n')
            # Invalid - bad JSON
            f.write("not json\n")
            # Valid
            f.write(json.dumps({"type": "Task", "id": "valid_task", "name": "Valid Task"}) + '\n')
        
        # Load with error handling
        config = LoaderConfig(validate=True, skip_errors=True)
        loader = NDJSONBulkLoader(db, config)
        stats = loader.load_file(mixed_file)
        
        # Should have some successes and some failures
        assert stats.successful_nodes >= 2  # At least the valid ones
        assert stats.failed_lines >= 1  # At least the invalid ones
        assert len(stats.errors) >= 1
        
        # GraphQL should still work with partial data
        query = """
        query {
            concepts(name: "Valid") {
                id
            }
        }
        """
        result = schema.execute_sync(query)
        assert result.errors is None
        assert len(result.data["concepts"]) >= 1
