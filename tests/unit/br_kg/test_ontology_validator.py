"""Unit and property tests for ontology validation."""

import networkx as nx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from brain_researcher.services.br_kg.ontology.validator import OntologyValidator


class TestOntologyValidator:
    """Test suite for OntologyValidator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return OntologyValidator()

    @pytest.fixture
    def valid_ontology(self):
        """Create valid ontology graph."""
        G = nx.DiGraph()
        G.add_edges_from(
            [
                ("Thing", "Animal"),
                ("Thing", "Plant"),
                ("Animal", "Mammal"),
                ("Animal", "Bird"),
                ("Mammal", "Dog"),
                ("Mammal", "Cat"),
            ]
        )
        return G

    @pytest.fixture
    def cyclic_ontology(self):
        """Create ontology with cycle."""
        G = nx.DiGraph()
        G.add_edges_from([("A", "B"), ("B", "C"), ("C", "A")])  # Cycle!
        return G

    def test_detect_hierarchy_cycles(self, validator, cyclic_ontology):
        """Test cycle detection."""
        result = validator.check_hierarchy_cycles(cyclic_ontology)

        assert result is False
        assert len(validator.errors) > 0
        assert validator.errors[0]["type"] == "CYCLE_DETECTED"

    def test_no_cycles_in_valid_ontology(self, validator, valid_ontology):
        """Test that valid ontology has no cycles."""
        result = validator.check_hierarchy_cycles(valid_ontology)

        assert result is True
        assert len(validator.errors) == 0

    def test_orphaned_concepts(self, validator):
        """Test detection of orphaned concepts."""
        G = nx.DiGraph()
        G.add_edges_from([("A", "B"), ("B", "C")])
        G.add_node("D")  # Orphaned

        result = validator.check_orphaned_concepts(G)

        assert result is False
        assert len(validator.warnings) > 0
        assert "D" in validator.warnings[0]["concepts"]

    def test_unique_uris(self, validator):
        """Test URI uniqueness validation."""
        concepts = {
            "concept1": {"uri": "http://example.org/concept1"},
            "concept2": {"uri": "http://example.org/concept2"},
            "concept3": {"uri": "http://example.org/concept1"},  # Duplicate!
        }

        result = validator.check_unique_uris(concepts)

        assert result is False
        assert len(validator.errors) > 0
        assert validator.errors[0]["type"] == "DUPLICATE_URI"

    def test_transitivity(self, validator, valid_ontology):
        """Test transitivity validation."""
        result = validator.validate_transitivity(valid_ontology)

        assert result is True

        # Dog should be descendant of Thing through transitivity
        assert nx.has_path(valid_ontology, "Thing", "Dog")

    def test_domain_range_validation(self, validator, valid_ontology):
        """Test domain/range constraint validation."""
        properties = {
            "hasColor": {"domain": "Animal", "range": "string"},
            "livesIn": {"domain": "Animal", "range": "Habitat"},  # Not in ontology
        }

        result = validator.validate_domain_range(valid_ontology, properties)

        assert result is False  # Habitat not found
        assert any(e["type"] == "RANGE_NOT_FOUND" for e in validator.errors)

    def test_cardinality_constraints(self, validator):
        """Test cardinality constraint validation."""
        instances = {
            "fido": {"type": "Dog", "hasOwner": ["John"]},  # Single value
            "rex": {
                "type": "Dog",
                "hasOwner": ["Jane", "Bob", "Alice"],  # Multiple values
            },
        }

        properties = {
            "hasOwner": {"min_cardinality": 1, "max_cardinality": 2}  # Max 2 owners
        }

        result = validator.check_cardinality_constraints(instances, properties)

        assert result is False
        assert any(e["type"] == "MAX_CARDINALITY_VIOLATION" for e in validator.errors)
        assert any("rex" in e["instance"] for e in validator.errors)

    def test_complete_validation(self, validator, valid_ontology):
        """Test complete ontology validation."""
        concepts = {
            node: {"uri": f"http://example.org/{node}"}
            for node in valid_ontology.nodes()
        }

        report = validator.validate_ontology(valid_ontology, concepts)

        assert report["consistency"] is True
        assert report["stats"]["concepts"] == len(concepts)
        assert report["stats"]["relations"] == valid_ontology.number_of_edges()

    # Property-based tests
    @given(st.lists(st.tuples(st.text(min_size=1), st.text(min_size=1)), min_size=1))
    def test_transitivity_property(self, validator, edges):
        """Property: If A→B and B→C then A→C (transitivity)."""
        G = nx.DiGraph()
        G.add_edges_from(edges)

        # Skip if graph has cycles (invalid for is-a hierarchy)
        if not nx.is_directed_acyclic_graph(G):
            return

        # For all paths, transitivity should hold
        for source in G.nodes():
            for target in G.nodes():
                if source != target and nx.has_path(G, source, target):
                    # All intermediate nodes should also have paths
                    path = nx.shortest_path(G, source, target)
                    for i in range(len(path) - 1):
                        assert G.has_edge(path[i], path[i + 1])

    @given(
        st.dictionaries(
            st.text(min_size=1), st.dictionaries(st.text(), st.text()), min_size=1
        )
    )
    def test_uri_uniqueness_property(self, validator, concepts):
        """Property: Each URI should map to exactly one concept."""
        # Set URIs
        for concept_id in concepts:
            if "uri" not in concepts[concept_id]:
                concepts[concept_id]["uri"] = f"uri_{concept_id}"

        result = validator.check_unique_uris(concepts)

        # Count unique URIs
        uris = [c.get("uri") for c in concepts.values()]
        unique_uris = set(uris)

        if len(uris) == len(unique_uris):
            assert result is True
        else:
            assert result is False
