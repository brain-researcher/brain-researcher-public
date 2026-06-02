"""
Unit tests for External Graph Federation

Tests federation connectors for Wikidata, DBpedia, and result merging
for enhanced knowledge retrieval in BR-KG.
"""

import json
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from brain_researcher.services.br_kg.federation.wikidata import WikidataConnector


class TestWikidataConnector:
    """Test suite for WikidataConnector class"""

    @pytest.fixture
    def connector(self):
        """Create WikidataConnector instance"""
        return WikidataConnector(cache_ttl=300, max_results=100)

    def test_connector_initialization(self):
        """Test proper initialization of Wikidata connector"""
        connector = WikidataConnector(cache_ttl=600, max_results=500)

        assert connector.endpoint_url == "https://query.wikidata.org/sparql"
        assert connector.cache_ttl == 600
        assert connector.max_results == 500
        assert isinstance(connector.query_cache, dict)
        assert connector.min_request_interval == 1.0

        # Check prefixes are set up
        assert "PREFIX wd:" in connector.prefixes
        assert "PREFIX wdt:" in connector.prefixes

        # Check neuroimaging entity mappings
        assert "brain" in connector.neuro_entities
        assert "fmri" in connector.neuro_entities
        assert "neuroimaging" in connector.neuro_entities
        assert connector.neuro_entities["brain"] == "Q1073"
        assert connector.neuro_entities["fmri"] == "Q207921"

    @patch("brain_researcher.services.br_kg.federation.wikidata.SPARQLWrapper")
    def test_execute_query_success(self, mock_sparql_wrapper, connector):
        """Test successful SPARQL query execution"""
        # Mock SPARQLWrapper
        mock_sparql = Mock()
        mock_result = Mock()
        mock_result.convert.return_value = {
            "results": {
                "bindings": [
                    {
                        "item": {
                            "type": "uri",
                            "value": "http://www.wikidata.org/entity/Q1073",
                        },
                        "itemLabel": {"type": "literal", "value": "brain"},
                    }
                ]
            }
        }
        mock_sparql.query.return_value = mock_result
        mock_sparql_wrapper.return_value = mock_sparql

        query = "SELECT ?item ?itemLabel WHERE { ?item wdt:P31 wd:Q1073 }"
        result = connector._execute_query(query, "test_cache_key")

        assert isinstance(result, list)
        assert len(result) == 1
        assert "item" in result[0]
        assert result[0]["item"]["type"] == "entity"
        assert result[0]["item"]["id"] == "Q1073"

        # Verify SPARQLWrapper was configured correctly
        mock_sparql.setQuery.assert_called_once_with(query)
        mock_sparql.setReturnFormat.assert_called_once()
        mock_sparql.setTimeout.assert_called_once_with(30)
        mock_sparql.addCustomHttpHeader.assert_called_once()

    @patch("brain_researcher.services.br_kg.federation.wikidata.SPARQLWrapper")
    def test_execute_query_with_caching(self, mock_sparql_wrapper, connector):
        """Test query execution with result caching"""
        # Mock successful query
        mock_sparql = Mock()
        mock_result = Mock()
        mock_result.convert.return_value = {"results": {"bindings": []}}
        mock_sparql.query.return_value = mock_result
        mock_sparql_wrapper.return_value = mock_sparql

        query = "SELECT ?item WHERE { ?item wdt:P31 wd:Q1073 }"
        cache_key = "test_cache"

        # First execution - should hit external service
        result1 = connector._execute_query(query, cache_key)

        # Second execution - should hit cache
        result2 = connector._execute_query(query, cache_key)

        # External service should only be called once
        assert mock_sparql.query.call_count == 1

        # Results should be identical
        assert result1 == result2

    @patch("brain_researcher.services.br_kg.federation.wikidata.SPARQLWrapper")
    def test_execute_query_exception_handling(self, mock_sparql_wrapper, connector):
        """Test exception handling in query execution"""
        # Mock SPARQLWrapper to raise exception
        mock_sparql = Mock()
        mock_sparql.query.side_effect = Exception("Network error")
        mock_sparql_wrapper.return_value = mock_sparql

        query = "SELECT ?item WHERE { ?item wdt:P31 wd:Q1073 }"
        result = connector._execute_query(query, "test_cache")

        # Should return empty list on error
        assert result == []

    def test_rate_limiting(self, connector):
        """Test rate limiting between requests"""
        # Set short interval for testing
        connector.min_request_interval = 0.1
        connector.last_request_time = time.time()

        start_time = time.time()
        connector._enforce_rate_limit()
        end_time = time.time()

        # Should have waited at least the minimum interval
        elapsed = end_time - start_time
        assert elapsed >= 0.09  # Allow small margin for timing

    def test_cache_key_generation(self, connector):
        """Test cache key generation from query"""
        query1 = "SELECT ?item WHERE { ?item wdt:P31 wd:Q1073 }"
        query2 = "SELECT ?item WHERE { ?item wdt:P31 wd:Q1073 }"
        query3 = "SELECT ?item WHERE { ?item wdt:P31 wd:Q9281 }"

        key1 = connector._get_cache_key(query1)
        key2 = connector._get_cache_key(query2)
        key3 = connector._get_cache_key(query3)

        # Same queries should produce same keys
        assert key1 == key2

        # Different queries should produce different keys
        assert key1 != key3

        # Keys should be MD5 hash length
        assert len(key1) == 32
        assert len(key3) == 32

    def test_cache_result_and_retrieval(self, connector):
        """Test caching and retrieving results"""
        cache_key = "test_cache_key"
        test_results = [{"item": {"type": "uri", "value": "test"}}]

        # Cache the results
        connector._cache_result(cache_key, test_results)

        # Retrieve cached results
        cached_results = connector._get_cached_result(cache_key)

        assert cached_results == test_results

    def test_cache_expiration(self, connector):
        """Test cache TTL expiration"""
        # Set very short TTL
        connector.cache_ttl = 0.1

        cache_key = "test_expiring_cache"
        test_results = [{"item": "test"}]

        # Cache results
        connector._cache_result(cache_key, test_results)

        # Should be available immediately
        cached = connector._get_cached_result(cache_key)
        assert cached == test_results

        # Wait for expiration
        time.sleep(0.2)

        # Should be expired now
        cached_expired = connector._get_cached_result(cache_key)
        assert cached_expired is None

        # Should be removed from cache
        assert cache_key not in connector.query_cache

    def test_process_wikidata_results_uris(self, connector):
        """Test processing of Wikidata URI results"""
        bindings = [
            {
                "item": {
                    "type": "uri",
                    "value": "http://www.wikidata.org/entity/Q1073",
                },
                "itemLabel": {"type": "literal", "value": "brain"},
                "property": {"type": "uri", "value": "http://example.org/property"},
            }
        ]

        processed = connector._process_wikidata_results(bindings)

        assert len(processed) == 1
        result = processed[0]

        # Wikidata entity URI should be processed to extract ID
        assert result["item"]["type"] == "entity"
        assert result["item"]["id"] == "Q1073"
        assert result["item"]["uri"] == "http://www.wikidata.org/entity/Q1073"

        # Literal should be processed correctly
        assert result["itemLabel"]["type"] == "literal"
        assert result["itemLabel"]["value"] == "brain"

        # External URI should be processed as URI
        assert result["property"]["type"] == "uri"
        assert result["property"]["uri"] == "http://example.org/property"

    def test_process_wikidata_results_literals(self, connector):
        """Test processing of literal values with datatypes"""
        bindings = [
            {
                "count": {
                    "type": "literal",
                    "value": "42",
                    "datatype": "http://www.w3.org/2001/XMLSchema#integer",
                },
                "description": {"type": "literal", "value": "Test description"},
            }
        ]

        processed = connector._process_wikidata_results(bindings)

        assert len(processed) == 1
        result = processed[0]

        # Integer literal with datatype
        assert result["count"]["type"] == "literal"
        assert result["count"]["value"] == "42"
        assert result["count"]["datatype"] == "http://www.w3.org/2001/XMLSchema#integer"

        # String literal without explicit datatype
        assert result["description"]["type"] == "literal"
        assert result["description"]["value"] == "Test description"
        assert result["description"]["datatype"] == "string"

    @patch(
        "brain_researcher.services.br_kg.federation.wikidata.WikidataConnector._execute_query"
    )
    def test_search_brain_regions(self, mock_execute, connector):
        """Test brain regions search functionality"""
        # Mock query results
        mock_execute.return_value = [
            {
                "item": {
                    "type": "entity",
                    "id": "Q1073",
                    "uri": "http://www.wikidata.org/entity/Q1073",
                },
                "itemLabel": {"type": "literal", "value": "brain"},
                "description": {
                    "type": "literal",
                    "value": "organ of central nervous system",
                },
            }
        ]

        results = connector.search_brain_regions(
            "brain", limit=10, include_anatomy=True
        )

        assert len(results) == 1
        assert results[0]["item"]["id"] == "Q1073"

        # Verify query construction
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        query = call_args[0][0]  # First argument is the query

        assert "wd:Q864805" in query  # Brain region entity
        assert 'CONTAINS(LCASE(?label), LCASE("brain"))' in query
        assert "LIMIT 10" in query
        assert "wdt:P1995" in query  # Anatomy property included

    @patch(
        "brain_researcher.services.br_kg.federation.wikidata.WikidataConnector._execute_query"
    )
    def test_search_brain_regions_no_anatomy(self, mock_execute, connector):
        """Test brain regions search without anatomy"""
        mock_execute.return_value = []

        connector.search_brain_regions("cortex", limit=20, include_anatomy=False)

        call_args = mock_execute.call_args
        query = call_args[0][0]

        assert "LIMIT 20" in query
        assert "wdt:P1995" not in query  # Anatomy property excluded

    @patch(
        "brain_researcher.services.br_kg.federation.wikidata.WikidataConnector._execute_query"
    )
    def test_search_neurological_conditions(self, mock_execute, connector):
        """Test neurological conditions search"""
        mock_execute.return_value = [
            {
                "item": {
                    "type": "entity",
                    "id": "Q8007",
                    "uri": "http://www.wikidata.org/entity/Q8007",
                },
                "itemLabel": {"type": "literal", "value": "Alzheimer's disease"},
                "icd10": {"type": "literal", "value": "F00"},
                "description": {
                    "type": "literal",
                    "value": "neurodegenerative disease",
                },
            }
        ]

        results = connector.search_neurological_conditions("alzheimer", limit=25)

        assert len(results) == 1
        assert results[0]["item"]["id"] == "Q8007"

        # Verify query construction
        call_args = mock_execute.call_args
        query = call_args[0][0]

        assert "wd:Q10737" in query  # Neurological disorder
        assert "wd:Q12136" in query  # Disease
        assert 'CONTAINS(LCASE(?label), LCASE("alzheimer"))' in query
        assert "LIMIT 25" in query
        assert "wdt:P494" in query  # ICD-10 code
        assert "wdt:P780" in query  # Symptoms
        assert "wdt:P2176" in query  # Medical treatment

    @patch(
        "brain_researcher.services.br_kg.federation.wikidata.WikidataConnector._execute_query"
    )
    def test_search_neuroimaging_methods(self, mock_execute, connector):
        """Test neuroimaging methods search"""
        mock_execute.return_value = [
            {
                "item": {"type": "entity", "id": "Q207921"},
                "itemLabel": {
                    "type": "literal",
                    "value": "functional magnetic resonance imaging",
                },
                "inventor": {"type": "entity", "id": "Q123456"},
                "inventorLabel": {"type": "literal", "value": "Seiji Ogawa"},
                "year": {"type": "literal", "value": "1990"},
            }
        ]

        results = connector.search_neuroimaging_methods("fMRI", limit=15)

        assert len(results) == 1
        assert results[0]["item"]["id"] == "Q207921"

        # Verify query construction
        call_args = mock_execute.call_args
        query = call_args[0][0]

        assert "wd:Q1575726" in query  # Neuroimaging technique
        assert "wd:Q3910275" in query  # Medical imaging
        assert 'CONTAINS(LCASE(?label), LCASE("fMRI"))' in query
        assert "LIMIT 15" in query
        assert "wdt:P61" in query  # Inventor
        assert "wdt:P571" in query  # Inception year
        assert "ORDER BY ?year" in query

    @patch(
        "brain_researcher.services.br_kg.federation.wikidata.WikidataConnector._execute_query"
    )
    def test_search_neuroscientists(self, mock_execute, connector):
        """Test neuroscientists search"""
        mock_execute.return_value = [
            {
                "item": {"type": "entity", "id": "Q44448"},
                "itemLabel": {"type": "literal", "value": "Santiago Ramón y Cajal"},
                "birthDate": {"type": "literal", "value": "1852-05-01"},
                "deathDate": {"type": "literal", "value": "1934-10-17"},
                "affiliation": {"type": "entity", "id": "Q12345"},
                "affiliationLabel": {
                    "type": "literal",
                    "value": "Universidad Complutense Madrid",
                },
            }
        ]

        results = connector.search_neuroscientists("Cajal", limit=20)

        assert len(results) == 1
        assert results[0]["item"]["id"] == "Q44448"

        call_args = mock_execute.call_args
        query = call_args[0][0]

        assert "wd:Q5" in query  # Human
        assert "wd:Q3126128" in query  # Neuroscientist
        assert "wd:Q901" in query  # Scientist
        assert "wd:Q9281" in query  # Neuroscience field
        assert 'CONTAINS(LCASE(?label), LCASE("Cajal"))' in query
        assert "LIMIT 20" in query
        assert "wdt:P569" in query  # Birth date
        assert "wdt:P570" in query  # Death date
        assert "wdt:P1416" in query  # Affiliation
        assert "ORDER BY DESC(?birthDate)" in query

    @patch(
        "brain_researcher.services.br_kg.federation.wikidata.WikidataConnector._execute_query"
    )
    def test_get_brain_region_hierarchy(self, mock_execute, connector):
        """Test brain region hierarchy retrieval"""
        mock_execute.return_value = [
            {
                "item": {"type": "entity", "id": "Q1073"},
                "itemLabel": {"type": "literal", "value": "brain"},
                "level": {"type": "literal", "value": "0"},
                "parent": {"type": "entity", "id": "Q23413"},
                "parentLabel": {"type": "literal", "value": "central nervous system"},
            },
            {
                "item": {"type": "entity", "id": "Q5713"},
                "itemLabel": {"type": "literal", "value": "cerebral cortex"},
                "level": {"type": "literal", "value": "-1"},
                "parent": {"type": "entity", "id": "Q1073"},
                "parentLabel": {"type": "literal", "value": "brain"},
            },
        ]

        hierarchy = connector.get_brain_region_hierarchy("Q1073", max_depth=2)

        assert isinstance(hierarchy, dict)
        assert "levels" in hierarchy
        assert "children" in hierarchy
        assert "parents" in hierarchy

        # Verify hierarchy structure was built
        assert "Q1073" in hierarchy["levels"]
        assert "Q5713" in hierarchy["levels"]

        call_args = mock_execute.call_args
        query = call_args[0][0]

        assert "wd:Q1073" in query
        assert "wdt:P361" in query  # Part of
        assert "wdt:P527" in query  # Has parts
        assert "ORDER BY ?level" in query

    def test_build_hierarchy_structure(self, connector):
        """Test building hierarchical structure from results"""
        results = [
            {
                "item": {"type": "entity", "id": "Q1073"},
                "itemLabel": {"type": "literal", "value": "brain"},
                "level": {"type": "literal", "value": "0"},
                "parent": {"type": "entity", "id": "Q23413"},
                "parentLabel": {"type": "literal", "value": "central nervous system"},
            },
            {
                "item": {"type": "entity", "id": "Q5713"},
                "itemLabel": {"type": "literal", "value": "cerebral cortex"},
                "level": {"type": "literal", "value": "-1"},
                "parent": {"type": "entity", "id": "Q1073"},
                "parentLabel": {"type": "literal", "value": "brain"},
            },
        ]

        hierarchy = connector._build_hierarchy_structure(results)

        assert "Q1073" in hierarchy["levels"]
        assert "Q5713" in hierarchy["levels"]
        assert hierarchy["levels"]["Q1073"]["level"] == 0
        assert hierarchy["levels"]["Q5713"]["level"] == -1

        # Check parent-child relationships
        assert hierarchy["parents"]["Q1073"] == "Q23413"
        assert hierarchy["parents"]["Q5713"] == "Q1073"
        assert "Q1073" in hierarchy["children"]["Q23413"]

    @patch(
        "brain_researcher.services.br_kg.federation.wikidata.WikidataConnector._execute_query"
    )
    def test_find_related_concepts(self, mock_execute, connector):
        """Test finding related concepts"""
        mock_execute.return_value = [
            {
                "related": {"type": "entity", "id": "Q5713"},
                "relatedLabel": {"type": "literal", "value": "cerebral cortex"},
                "relation": {
                    "type": "uri",
                    "value": "http://www.wikidata.org/prop/direct/P527",
                },
                "relationLabel": {"type": "literal", "value": "has part"},
            }
        ]

        results = connector.find_related_concepts(
            "Q1073", relation_types=["P527"], limit=30
        )

        assert len(results) == 1
        assert results[0]["related"]["id"] == "Q5713"

        call_args = mock_execute.call_args
        query = call_args[0][0]

        assert "wd:Q1073" in query
        assert "wdt:P527" in query
        assert "LIMIT 30" in query
        # Check that relevant entity types are filtered
        assert "wd:Q864805" in query  # Brain regions
        assert "wd:Q1575726" in query  # Neuroimaging

    @patch(
        "brain_researcher.services.br_kg.federation.wikidata.WikidataConnector._execute_query"
    )
    def test_search_publications(self, mock_execute, connector):
        """Test publications search"""
        mock_execute.return_value = [
            {
                "item": {"type": "entity", "id": "Q123456"},
                "itemLabel": {"type": "literal", "value": "Functional brain networks"},
                "journal": {"type": "entity", "id": "Q567890"},
                "journalLabel": {"type": "literal", "value": "Nature Neuroscience"},
                "year": {"type": "literal", "value": "2020"},
                "doi": {"type": "literal", "value": "10.1038/nn.2020.123"},
            }
        ]

        results = connector.search_publications(
            "brain networks", publication_type="scientific_article", limit=25
        )

        assert len(results) == 1
        assert results[0]["item"]["id"] == "Q123456"

        call_args = mock_execute.call_args
        query = call_args[0][0]

        assert "wd:Q13442814" in query  # Scientific article type
        assert "wd:Q9281" in query  # Neuroscience subject
        assert "wd:Q1575726" in query  # Neuroimaging subject
        assert 'CONTAINS(LCASE(?label), LCASE("brain networks"))' in query
        assert 'CONTAINS(LCASE(?title), LCASE("brain networks"))' in query
        assert "LIMIT 25" in query
        assert "wdt:P50" in query  # Authors
        assert "wdt:P1433" in query  # Published in
        assert "wdt:P577" in query  # Publication date
        assert "wdt:P356" in query  # DOI
        assert "ORDER BY DESC(?year)" in query

    def test_search_publications_different_types(self, connector):
        """Test publications search with different publication types"""
        with patch.object(connector, "_execute_query") as mock_execute:
            mock_execute.return_value = []

            # Test review article
            connector.search_publications("test", publication_type="review")
            call_args = mock_execute.call_args[0][0]
            assert "wd:Q7318358" in call_args  # Review article type

            # Test book
            connector.search_publications("test", publication_type="book")
            call_args = mock_execute.call_args[0][0]
            assert "wd:Q571" in call_args  # Book type

            # Test thesis
            connector.search_publications("test", publication_type="thesis")
            call_args = mock_execute.call_args[0][0]
            assert "wd:Q1266946" in call_args  # Thesis type

    @patch(
        "brain_researcher.services.br_kg.federation.wikidata.WikidataConnector._execute_query"
    )
    def test_get_entity_details(self, mock_execute, connector):
        """Test getting detailed entity information"""
        mock_execute.return_value = [
            {
                "property": {
                    "type": "uri",
                    "value": "http://www.wikidata.org/prop/direct/P31",
                },
                "propertyLabel": {"type": "literal", "value": "instance of"},
                "value": {"type": "entity", "id": "Q864805"},
                "valueLabel": {"type": "literal", "value": "brain region"},
            },
            {
                "property": {
                    "type": "uri",
                    "value": "http://www.wikidata.org/prop/direct/P361",
                },
                "propertyLabel": {"type": "literal", "value": "part of"},
                "value": {"type": "entity", "id": "Q1073"},
                "valueLabel": {"type": "literal", "value": "brain"},
            },
        ]

        details = connector.get_entity_details("Q5713")

        assert isinstance(details, dict)
        assert "properties" in details
        assert "classifications" in details
        assert "relationships" in details

        call_args = mock_execute.call_args
        query = call_args[0][0]

        assert "wd:Q5713" in query
        assert "wdt:P31" in query  # Instance of
        assert "wdt:P279" in query  # Subclass of
        assert "wdt:P361" in query  # Part of
        assert "wdt:P527" in query  # Has parts

    def test_structure_entity_details(self, connector):
        """Test structuring entity details into organized format"""
        results = [
            {
                "property": {
                    "type": "uri",
                    "value": "http://www.wikidata.org/prop/direct/P31",
                },
                "value": {"type": "entity", "id": "Q864805"},
            },
            {
                "property": {
                    "type": "uri",
                    "value": "http://www.wikidata.org/prop/direct/P361",
                },
                "value": {"type": "entity", "id": "Q1073"},
            },
            {
                "property": {
                    "type": "uri",
                    "value": "http://www.wikidata.org/prop/direct/P571",
                },
                "value": {"type": "literal", "value": "1990"},
            },
        ]

        structured = connector._structure_entity_details(results)

        # P31 should be in classifications
        assert len(structured["classifications"]) == 1
        assert structured["classifications"][0]["property"] == "P31"

        # P361 should be in relationships/structure
        assert "structure" in structured["relationships"]
        assert len(structured["relationships"]["structure"]) == 1
        assert structured["relationships"]["structure"][0]["property"] == "P361"

        # P571 should be in properties
        assert "P571" in structured["properties"]
        assert len(structured["properties"]["P571"]) == 1

    def test_cache_size_limit(self, connector):
        """Test cache size limitation"""
        # Fill cache beyond limit
        for i in range(1100):  # Exceeds default limit of 1000
            cache_key = f"test_key_{i}"
            connector._cache_result(cache_key, [{"test": f"data_{i}"}])

        # Cache should be limited
        assert len(connector.query_cache) <= 1000

        # Older entries should have been removed
        assert "test_key_0" not in connector.query_cache
        assert "test_key_99" not in connector.query_cache

    def test_query_limit_enforcement(self, connector):
        """Test enforcement of max_results limit"""
        # Set low limit for testing
        connector.max_results = 5

        with patch.object(connector, "_execute_query") as mock_execute:
            connector.search_brain_regions("test", limit=10)

            call_args = mock_execute.call_args[0][0]
            # Should enforce connector's max_results limit
            assert "LIMIT 5" in call_args


class TestWikidataConnectorEdgeCases:
    """Test edge cases and error conditions"""

    @pytest.fixture
    def connector(self):
        return WikidataConnector(cache_ttl=300, max_results=100)

    def test_empty_search_query(self, connector):
        """Test handling of empty search queries"""
        with patch.object(connector, "_execute_query") as mock_execute:
            mock_execute.return_value = []

            results = connector.search_brain_regions("", limit=10)

            assert results == []
            # Should still execute query (empty string is valid for CONTAINS)
            mock_execute.assert_called_once()

    def test_special_characters_in_query(self, connector):
        """Test handling of special characters in search queries"""
        with patch.object(connector, "_execute_query") as mock_execute:
            mock_execute.return_value = []

            # Query with quotes and special characters
            connector.search_brain_regions('brain "cortex" & region', limit=10)

            call_args = mock_execute.call_args[0][0]
            # Special characters should be included in SPARQL query
            assert 'brain "cortex" & region' in call_args

    def test_unicode_query_handling(self, connector):
        """Test handling of Unicode characters in queries"""
        with patch.object(connector, "_execute_query") as mock_execute:
            mock_execute.return_value = []

            # Unicode query
            connector.search_brain_regions("大脑皮层", limit=10)

            call_args = mock_execute.call_args[0][0]
            assert "大脑皮层" in call_args

    def test_malformed_wikidata_results(self, connector):
        """Test handling of malformed results from Wikidata"""
        bindings = [
            # Missing required fields
            {"item": {"type": "uri"}},  # Missing 'value'
            # Invalid URI format
            {"item": {"type": "uri", "value": "not-a-valid-uri"}},
            # Unknown type
            {"item": {"type": "unknown", "value": "test"}},
        ]

        # Should not crash on malformed data
        processed = connector._process_wikidata_results(bindings)

        # Should process what it can
        assert isinstance(processed, list)
        assert len(processed) == 3

    def test_cache_key_collision_handling(self, connector):
        """Test handling of potential cache key collisions"""
        # Create two similar but different queries
        query1 = "SELECT ?item WHERE { ?item rdfs:label ?label }"
        query2 = "SELECT ?item WHERE { ?item rdfs:label ?label} "  # Extra space

        key1 = connector._get_cache_key(query1)
        key2 = connector._get_cache_key(query2)

        # Keys should be different due to whitespace difference
        assert key1 != key2

    def test_zero_results_limit(self, connector):
        """Test handling of zero results limit"""
        with patch.object(connector, "_execute_query") as mock_execute:
            mock_execute.return_value = []

            connector.search_brain_regions("test", limit=0)

            call_args = mock_execute.call_args[0][0]
            # Should enforce minimum of 0 (though not very useful)
            assert "LIMIT 0" in call_args

    def test_negative_limit_handling(self, connector):
        """Test handling of negative limit values"""
        with patch.object(connector, "_execute_query") as mock_execute:
            mock_execute.return_value = []

            connector.search_brain_regions("test", limit=-5)

            call_args = mock_execute.call_args[0][0]
            # Should use max_results when negative
            assert f"LIMIT {connector.max_results}" in call_args

    def test_very_large_limit(self, connector):
        """Test handling of very large limit values"""
        with patch.object(connector, "_execute_query") as mock_execute:
            mock_execute.return_value = []

            connector.search_brain_regions("test", limit=999999)

            call_args = mock_execute.call_args[0][0]
            # Should cap at max_results
            assert f"LIMIT {connector.max_results}" in call_args


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
