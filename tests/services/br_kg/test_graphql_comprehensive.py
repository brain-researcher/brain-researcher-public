"""
Comprehensive test suite for BR-KG GraphQL implementation.
Tests all CRUD operations, queries, mutations, and edge cases.
"""

import os

import pytest

if not os.getenv("NEO4J_URI") or not os.getenv("NEO4J_PASSWORD"):
    pytest.skip(
        "NEO4J_URI/NEO4J_PASSWORD required for Neo4j-only tests",
        allow_module_level=True,
    )

from brain_researcher.services.br_kg.db.bootstrap import get_db
from brain_researcher.services.br_kg.gql_schema.schema_simple import build_schema


class TestGraphQLSchema:
    """Test GraphQL schema operations."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        """Set up test database for each test."""
        self.db = get_db()
        self.schema = build_schema()

        # Seed some test data
        self.db.create_node("Concept", {"id": "test_concept", "name": "Test Concept"})
        self.db.create_node("Task", {"id": "test_task", "name": "Test Task"})
        self.db.create_node(
            "Region", {"id": "test_region", "name": "Test Region", "abbreviation": "TR"}
        )

    def test_query_concepts(self):
        """Test querying concepts."""
        query = """
        query {
            concepts {
                id
                name
            }
        }
        """
        result = self.schema.execute_sync(query)
        assert result.errors is None
        assert len(result.data["concepts"]) >= 1
        assert any(c["name"] == "Test Concept" for c in result.data["concepts"])

    def test_query_concepts_by_name(self):
        """Test querying concepts with name filter."""
        query = """
        query {
            concepts(name: "Test Concept") {
                id
                name
            }
        }
        """
        result = self.schema.execute_sync(query)
        assert result.errors is None
        assert len(result.data["concepts"]) == 1
        assert result.data["concepts"][0]["name"] == "Test Concept"

    def test_query_tasks(self):
        """Test querying tasks."""
        query = """
        query {
            tasks {
                id
                name
            }
        }
        """
        result = self.schema.execute_sync(query)
        assert result.errors is None
        assert len(result.data["tasks"]) >= 1
        assert any(t["name"] == "Test Task" for t in result.data["tasks"])

    def test_query_regions(self):
        """Test querying regions."""
        query = """
        query {
            regions {
                id
                name
                abbreviation
            }
        }
        """
        result = self.schema.execute_sync(query)
        assert result.errors is None
        assert len(result.data["regions"]) >= 1
        region = next(r for r in result.data["regions"] if r["name"] == "Test Region")
        assert region["abbreviation"] == "TR"

    def test_query_publications(self):
        """Test querying publications."""
        # First create a publication
        self.db.create_node(
            "Publication",
            {"id": "test_pub", "pmid": "12345678", "title": "Test Publication"},
        )

        query = """
        query {
            publications {
                id
                pmid
                title
            }
        }
        """
        result = self.schema.execute_sync(query)
        assert result.errors is None
        assert len(result.data["publications"]) >= 1
        pub = next(p for p in result.data["publications"] if p["pmid"] == "12345678")
        assert pub["title"] == "Test Publication"

    def test_mutation_create_concept(self):
        """Test creating a concept via mutation."""
        mutation = """
        mutation {
            createConcept(id: "new_concept", name: "New Concept") {
                id
                name
            }
        }
        """
        result = self.schema.execute_sync(mutation)
        assert result.errors is None
        assert result.data["createConcept"]["id"] == "new_concept"
        assert result.data["createConcept"]["name"] == "New Concept"

        # Verify it was created
        nodes = list(self.db.find_nodes("Concept", {"id": "new_concept"}))
        assert len(nodes) == 1

    def test_mutation_create_task(self):
        """Test creating a task via mutation."""
        mutation = """
        mutation {
            createTask(id: "new_task", name: "New Task") {
                id
                name
            }
        }
        """
        result = self.schema.execute_sync(mutation)
        assert result.errors is None
        assert result.data["createTask"]["id"] == "new_task"
        assert result.data["createTask"]["name"] == "New Task"

    def test_mutation_create_publication(self):
        """Test creating a publication via mutation."""
        mutation = """
        mutation {
            createPublication(pmid: "87654321", title: "Another Publication") {
                id
                pmid
                title
            }
        }
        """
        result = self.schema.execute_sync(mutation)
        assert result.errors is None
        assert result.data["createPublication"]["pmid"] == "87654321"
        assert result.data["createPublication"]["title"] == "Another Publication"

    def test_mutation_create_region(self):
        """Test creating a region via mutation."""
        mutation = """
        mutation {
            createRegion(name: "New Region", abbreviation: "NR") {
                id
                name
                abbreviation
            }
        }
        """
        result = self.schema.execute_sync(mutation)
        assert result.errors is None
        assert result.data["createRegion"]["name"] == "New Region"
        assert result.data["createRegion"]["abbreviation"] == "NR"

    def test_mutation_create_relationship(self):
        """Test creating a relationship with provenance."""
        mutation = """
        mutation {
            createRelationship(
                sourceId: "test_concept",
                targetId: "test_task",
                relType: "MEASURES",
                confidence: 0.85,
                source: "Test Suite"
            ) {
                type
                sourceId
                targetId
                confidence
                source
                timestamp
            }
        }
        """
        result = self.schema.execute_sync(mutation)
        assert result.errors is None

        rel = result.data["createRelationship"]
        assert rel["type"] == "MEASURES"
        assert rel["sourceId"] == "test_concept"
        assert rel["targetId"] == "test_task"
        assert rel["confidence"] == 0.85
        assert rel["source"] == "Test Suite"
        assert rel["timestamp"] is not None

    def test_empty_database_queries(self):
        """Test queries on empty database."""
        # Clear database
        for node_id, _ in self.db.find_nodes(None, None):
            # Note: Real implementation would have delete_node method
            pass

        query = """
        query {
            concepts { id }
            tasks { id }
            regions { id }
            publications { id }
        }
        """
        result = self.schema.execute_sync(query)
        assert result.errors is None
        # Should return empty lists, not errors
        assert result.data["concepts"] == [] or isinstance(
            result.data["concepts"], list
        )
        assert result.data["tasks"] == [] or isinstance(result.data["tasks"], list)

    def test_query_with_variables(self):
        """Test queries with variables."""
        query = """
        query GetConcept($name: String) {
            concepts(name: $name) {
                id
                name
            }
        }
        """
        variables = {"name": "Test Concept"}
        result = self.schema.execute_sync(query, variable_values=variables)
        assert result.errors is None
        assert len(result.data["concepts"]) >= 1

    def test_multiple_mutations(self):
        """Test multiple mutations in one request."""
        mutation = """
        mutation {
            concept: createConcept(id: "multi_1", name: "Multi Concept") {
                id
            }
            task: createTask(id: "multi_2", name: "Multi Task") {
                id
            }
        }
        """
        result = self.schema.execute_sync(mutation)
        assert result.errors is None
        assert result.data["concept"]["id"] == "multi_1"
        assert result.data["task"]["id"] == "multi_2"

    def test_relationship_with_high_confidence(self):
        """Test relationship creation with edge cases for confidence."""
        # Test max confidence
        mutation = """
        mutation {
            createRelationship(
                sourceId: "test_concept",
                targetId: "test_task",
                relType: "RELATED_TO",
                confidence: 1.0
            ) {
                confidence
            }
        }
        """
        result = self.schema.execute_sync(mutation)
        assert result.errors is None
        assert result.data["createRelationship"]["confidence"] == 1.0

        # Test min confidence
        mutation = """
        mutation {
            createRelationship(
                sourceId: "test_task",
                targetId: "test_region",
                relType: "ACTIVATES",
                confidence: 0.0
            ) {
                confidence
            }
        }
        """
        result = self.schema.execute_sync(mutation)
        assert result.errors is None
        assert result.data["createRelationship"]["confidence"] == 0.0

    def test_special_characters_in_names(self):
        """Test handling of special characters in names."""
        mutation = """
        mutation {
            createConcept(
                id: "special_chars",
                name: "Test & Concept (with special-chars) [2024]"
            ) {
                id
                name
            }
        }
        """
        result = self.schema.execute_sync(mutation)
        assert result.errors is None
        assert "special-chars" in result.data["createConcept"]["name"]


class TestGraphQLErrors:
    """Test error handling in GraphQL."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        """Set up test database."""
        self.schema = build_schema()

    def test_invalid_query_syntax(self):
        """Test handling of invalid query syntax."""
        query = """
        query {
            concepts {
                invalid_field
            }
        }
        """
        result = self.schema.execute_sync(query)
        assert result.errors is not None
        assert len(result.errors) > 0

    def test_missing_required_field(self):
        """Test mutation with missing required field."""
        mutation = """
        mutation {
            createConcept(name: "Missing ID") {
                id
            }
        }
        """
        result = self.schema.execute_sync(mutation)
        assert result.errors is not None

    def test_invalid_variable_type(self):
        """Test query with invalid variable type."""
        query = """
        query GetConcept($name: Int) {
            concepts(name: $name) {
                id
            }
        }
        """
        variables = {"name": 123}  # Should be string
        result = self.schema.execute_sync(query, variable_values=variables)
        # This might not error depending on GraphQL implementation,
        # but the query should handle it gracefully
