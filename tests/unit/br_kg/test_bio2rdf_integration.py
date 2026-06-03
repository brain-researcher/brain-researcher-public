"""
Unit tests for Bio2RDF integration
"""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from brain_researcher.services.br_kg.bio2rdf import (
    Bio2RDFClient,
    ConceptMapping,
    EnrichedEntity,
    LinkEnrichmentEngine,
    OntologyMapper,
    OntologyNamespace,
)


class TestBio2RDFClient:
    """Test Bio2RDF client functionality"""

    @pytest.fixture
    def client(self):
        return Bio2RDFClient(timeout=5, max_retries=1)

    def test_client_initialization(self, client):
        """Test client initializes with correct defaults"""
        assert client.timeout == 5
        assert client.max_retries == 1
        assert client.default_endpoint == Bio2RDFClient.BIO2RDF_ENDPOINTS["main"]

    @patch("brain_researcher.services.br_kg.bio2rdf.bio2rdf_client.SPARQLWrapper")
    def test_query_execution(self, mock_sparql, client):
        """Test SPARQL query execution"""
        # Mock SPARQL response
        mock_wrapper = MagicMock()
        mock_sparql.return_value = mock_wrapper
        mock_wrapper.query.return_value.convert.return_value = {
            "results": {
                "bindings": [{"gene": {"value": "http://bio2rdf.org/gene:BDNF"}}]
            }
        }

        result = client.query("SELECT ?gene WHERE { ?gene rdfs:label 'BDNF' }")

        assert "results" in result
        assert len(result["results"]["bindings"]) == 1
        mock_sparql.assert_called_once()

    def test_query_caching(self, client):
        """Test query result caching"""
        query = "SELECT * WHERE { ?s ?p ?o } LIMIT 1"

        # First call
        with patch.object(client, "query") as mock_query:
            mock_query.return_value = {"results": {"bindings": []}}
            client.query(query)

        # Second call should use cache
        client._cache[f"{client.default_endpoint}:{query}"] = {"cached": True}
        client._cache_timestamps[f"{client.default_endpoint}:{query}"] = 9999999999

        result2 = client.query(query)
        assert result2 == {"cached": True}

    @patch("brain_researcher.services.br_kg.bio2rdf.bio2rdf_client.SPARQLWrapper")
    def test_get_gene_info(self, mock_sparql, client):
        """Test gene information retrieval"""
        mock_wrapper = MagicMock()
        mock_sparql.return_value = mock_wrapper
        mock_wrapper.query.return_value.convert.return_value = {
            "results": {
                "bindings": [
                    {
                        "gene": {"value": "http://bio2rdf.org/gene:BDNF"},
                        "label": {"value": "Brain-derived neurotrophic factor"},
                        "go_term": {"value": "http://bio2rdf.org/go:0007399"},
                    }
                ]
            }
        }

        result = client.get_gene_info("BDNF")

        assert "results" in result
        assert (
            result["results"]["bindings"][0]["label"]["value"]
            == "Brain-derived neurotrophic factor"
        )

    @patch("brain_researcher.services.br_kg.bio2rdf.bio2rdf_client.SPARQLWrapper")
    def test_get_drug_target_interactions(self, mock_sparql, client):
        """Test drug-target interaction retrieval"""
        mock_wrapper = MagicMock()
        mock_sparql.return_value = mock_wrapper
        mock_wrapper.query.return_value.convert.return_value = {
            "results": {
                "bindings": [
                    {
                        "drug": {"value": "http://bio2rdf.org/drugbank:DB00001"},
                        "drug_name": {"value": "Lepirudin"},
                        "target": {"value": "http://bio2rdf.org/uniprot:P00734"},
                        "target_name": {"value": "Prothrombin"},
                    }
                ]
            }
        }

        result = client.get_drug_target_interactions("Lepirudin")

        assert "results" in result
        assert result["results"]["bindings"][0]["target_name"]["value"] == "Prothrombin"

    @patch("requests.get")
    def test_federated_search(self, mock_get, client):
        """Test federated search across endpoints"""
        with patch.object(client, "query") as mock_query:
            mock_query.return_value = {"results": {"bindings": []}}

            results = client.federated_search(
                "dopamine", endpoints=["drugbank", "uniprot"]
            )

            assert "drugbank" in results
            assert "uniprot" in results


class TestOntologyMapper:
    """Test ontology mapping functionality"""

    @pytest.fixture
    def mapper(self):
        return OntologyMapper()

    def test_mapper_initialization(self, mapper):
        """Test mapper initializes with correct mappings"""
        assert "brain_region" in mapper.all_mappings
        assert "cognitive_task" in mapper.all_mappings
        assert "neurochemical" in mapper.all_mappings
        assert "disorder" in mapper.all_mappings

    def test_exact_mapping(self, mapper):
        """Test exact concept mapping"""
        mappings = mapper.map_concept("hippocampus", "brain_region", fuzzy=False)

        assert len(mappings) > 0
        assert mappings[0].br_kg_label == "hippocampus"
        assert mappings[0].mapping_type == "exact"
        assert mappings[0].confidence_score == 1.0
        assert "mesh:D006624" in mappings[0].bio2rdf_uri

    def test_fuzzy_mapping(self, mapper):
        """Test fuzzy concept mapping"""
        mappings = mapper.map_concept("hippocamp", "brain_region", fuzzy=True)

        assert len(mappings) > 0
        # Should find hippocampus through fuzzy matching
        assert any("hippocampus" in m.bio2rdf_label.lower() for m in mappings)

    def test_cognitive_task_mapping(self, mapper):
        """Test cognitive task mapping"""
        mappings = mapper.map_concept("working_memory", "cognitive_task")

        assert len(mappings) > 0
        assert any("memory" in m.bio2rdf_label.lower() for m in mappings)

    def test_neurochemical_mapping(self, mapper):
        """Test neurochemical mapping"""
        mappings = mapper.map_concept("dopamine", "neurochemical")

        assert len(mappings) > 0
        assert mappings[0].bio2rdf_namespace in [
            OntologyNamespace.DRUGBANK,
            OntologyNamespace.CHEBI,
            OntologyNamespace.MESH,
        ]

    def test_disorder_mapping(self, mapper):
        """Test disorder mapping"""
        mappings = mapper.map_concept("alzheimer", "disorder")

        assert len(mappings) > 0
        assert any("Alzheimer" in m.bio2rdf_label for m in mappings)

    def test_namespace_extraction(self, mapper):
        """Test namespace extraction from URI"""
        namespace = mapper._extract_namespace("http://bio2rdf.org/mesh:D006624")
        assert namespace == OntologyNamespace.MESH

        namespace = mapper._extract_namespace("http://bio2rdf.org/go:0007399")
        assert namespace == OntologyNamespace.GO

    def test_string_similarity(self, mapper):
        """Test string similarity calculation"""
        similarity = mapper._string_similarity("hippocampus", "hippocampus")
        assert similarity == 1.0

        similarity = mapper._string_similarity("hippo", "hippocampus")
        assert 0 < similarity < 1.0

        similarity = mapper._string_similarity("xyz", "abc")
        assert similarity < 0.5

    def test_generate_mapping_sparql(self, mapper):
        """Test SPARQL generation for mappings"""
        mappings = [
            ConceptMapping(
                br_kg_id="br_kg:hippocampus",
                br_kg_label="hippocampus",
                br_kg_type="brain_region",
                bio2rdf_uri="http://bio2rdf.org/mesh:D006624",
                bio2rdf_namespace=OntologyNamespace.MESH,
                bio2rdf_label="Hippocampus",
                confidence_score=1.0,
                mapping_type="exact",
            )
        ]

        sparql = mapper.generate_mapping_sparql(mappings)

        assert "CONSTRUCT" in sparql
        assert "owl:sameAs" in sparql
        assert "skos:exactMatch" in sparql
        assert "br_kg:hippocampus" in sparql


class TestLinkEnrichmentEngine:
    """Test link enrichment functionality"""

    @pytest.fixture
    def engine(self):
        mock_client = Mock(spec=Bio2RDFClient)
        mock_mapper = Mock(spec=OntologyMapper)
        return LinkEnrichmentEngine(mock_client, mock_mapper)

    def test_engine_initialization(self, engine):
        """Test engine initializes correctly"""
        assert engine.bio2rdf_client is not None
        assert engine.ontology_mapper is not None
        assert engine._enrichment_cache == {}

    def test_enrich_brain_region(self, engine):
        """Test brain region enrichment"""
        # Mock mapper response
        engine.ontology_mapper.map_concept.return_value = [
            ConceptMapping(
                br_kg_id="br_kg:hippocampus",
                br_kg_label="hippocampus",
                br_kg_type="brain_region",
                bio2rdf_uri="http://bio2rdf.org/mesh:D006624",
                bio2rdf_namespace=OntologyNamespace.MESH,
                bio2rdf_label="Hippocampus",
                confidence_score=1.0,
                mapping_type="exact",
            )
        ]

        # Mock Bio2RDF client responses
        engine.bio2rdf_client.query.return_value = {"results": {"bindings": []}}
        engine.bio2rdf_client.get_gene_info.return_value = {
            "results": {
                "bindings": [
                    {
                        "gene": {"value": "http://bio2rdf.org/gene:BDNF"},
                        "label": {"value": "BDNF"},
                    }
                ]
            }
        }

        enriched = engine.enrich_entity(
            "br_kg:hippocampus", "brain_region", "hippocampus"
        )

        assert enriched.entity_id == "br_kg:hippocampus"
        assert enriched.entity_type == "brain_region"
        assert len(enriched.bio2rdf_mappings) == 1
        assert len(enriched.related_genes) == 1
        assert enriched.confidence_score == 1.0

    def test_enrich_cognitive_task(self, engine):
        """Test cognitive task enrichment"""
        engine.ontology_mapper.map_concept.return_value = [
            ConceptMapping(
                br_kg_id="br_kg:working_memory",
                br_kg_label="working_memory",
                br_kg_type="cognitive_task",
                bio2rdf_uri="http://bio2rdf.org/go:0007613",
                bio2rdf_namespace=OntologyNamespace.GO,
                bio2rdf_label="memory",
                confidence_score=0.8,
                mapping_type="broad",
            )
        ]

        engine.bio2rdf_client.query.return_value = {
            "results": {
                "bindings": [
                    {
                        "process": {"value": "http://bio2rdf.org/go:0007613"},
                        "label": {"value": "memory"},
                    }
                ]
            }
        }

        enriched = engine.enrich_entity(
            "br_kg:working_memory", "cognitive_task", "working memory"
        )

        assert enriched.entity_type == "cognitive_task"
        assert "go_processes" in enriched.biological_annotations

    def test_batch_enrichment(self, engine):
        """Test batch enrichment of multiple entities"""
        entities = [
            ("br_kg:hippocampus", "brain_region", "hippocampus"),
            ("br_kg:dopamine", "neurochemical", "dopamine"),
        ]

        engine.ontology_mapper.map_concept.return_value = []
        engine.bio2rdf_client.query.return_value = {"results": {"bindings": []}}

        enriched_list = engine.batch_enrich(entities, max_workers=2)

        assert len(enriched_list) == 2
        assert all(isinstance(e, EnrichedEntity) for e in enriched_list)

    def test_export_enrichment_graph_json(self, engine):
        """Test exporting enrichment as JSON-LD"""
        enriched_entity = EnrichedEntity(
            entity_id="br_kg:hippocampus",
            entity_type="brain_region",
            entity_label="hippocampus",
            bio2rdf_mappings=[],
            biological_annotations={},
            related_genes=[],
            related_drugs=[],
            pathways=[],
            literature_refs=[],
            confidence_score=1.0,
        )

        json_output = engine.export_enrichment_graph([enriched_entity], format="json")
        data = json.loads(json_output)

        assert "@context" in data
        assert "@graph" in data
        assert len(data["@graph"]) == 1
        assert data["@graph"][0]["@id"] == "br_kg:hippocampus"

    def test_caching(self, engine):
        """Test enrichment caching"""
        engine.ontology_mapper.map_concept.return_value = []

        # First call
        enriched1 = engine.enrich_entity("id1", "brain_region", "test")

        # Second call should use cache
        enriched2 = engine.enrich_entity("id1", "brain_region", "test")

        assert enriched1 is enriched2  # Same object from cache
        engine.ontology_mapper.map_concept.assert_called_once()  # Only called once
