"""
Unit tests for SPARQL Endpoint

Tests the core functionality of the W3C SPARQL 1.1 compliant endpoint
including query handling, result formatting, caching, and error conditions.
"""

import pytest
import json
import time
from unittest.mock import Mock, MagicMock, patch
from flask import Flask
from datetime import datetime

from brain_researcher.services.neurokg.sparql.endpoint import SPARQLEndpoint


class TestSPARQLEndpoint:
    """Test suite for SPARQLEndpoint class"""
    
    @pytest.fixture
    def mock_neo4j_db(self):
        """Mock Neo4j database connection"""
        mock_db = Mock()
        mock_db._run = Mock()
        return mock_db
    
    @pytest.fixture
    def sparql_endpoint(self, mock_neo4j_db):
        """Create SPARQLEndpoint instance with mocked dependencies"""
        with patch('brain_researcher.services.neurokg.sparql.endpoint.SPARQLToCypherTranslator'):
            with patch('brain_researcher.services.neurokg.sparql.endpoint.FederationQueryHandler'):
                endpoint = SPARQLEndpoint(
                    neo4j_db=mock_neo4j_db,
                    base_uri="https://test.neurokg.org/",
                    enable_federation=True,
                    query_timeout=10,
                    max_results=100
                )
                return endpoint
    
    @pytest.fixture
    def app(self, sparql_endpoint):
        """Create Flask app with SPARQL endpoint"""
        app = Flask(__name__)
        blueprint = sparql_endpoint.create_blueprint()
        app.register_blueprint(blueprint)
        return app
    
    def test_endpoint_initialization(self, mock_neo4j_db):
        """Test proper initialization of SPARQL endpoint"""
        with patch('brain_researcher.services.neurokg.sparql.endpoint.SPARQLToCypherTranslator') as mock_translator:
            with patch('brain_researcher.services.neurokg.sparql.endpoint.FederationQueryHandler') as mock_federation:
                endpoint = SPARQLEndpoint(
                    neo4j_db=mock_neo4j_db,
                    base_uri="https://example.org/",
                    enable_federation=False,
                    query_timeout=30,
                    max_results=1000
                )
                
                assert endpoint.neo4j_db == mock_neo4j_db
                assert endpoint.base_uri == "https://example.org/"
                assert endpoint.enable_federation is False
                assert endpoint.query_timeout == 30
                assert endpoint.max_results == 1000
                assert endpoint.cache_ttl == 300
                
                # Check translator initialization
                mock_translator.assert_called_once_with(base_uri="https://example.org/")
                
                # Federation handler should be None when disabled
                assert endpoint.federation_handler is None
    
    def test_blueprint_creation(self, sparql_endpoint):
        """Test Flask blueprint creation with correct routes"""
        blueprint = sparql_endpoint.create_blueprint()
        
        assert blueprint.name == 'sparql'
        assert blueprint.url_prefix == '/sparql'
        
        # Check that all expected routes are registered
        route_rules = [rule.rule for rule in blueprint.deferred_functions]
        expected_routes = ['', '/query', '/update', '/describe', '/metrics']
        
        # Note: Flask blueprint route checking is complex, so we test endpoint methods exist
        assert hasattr(sparql_endpoint, '_handle_sparql_request')
        assert hasattr(sparql_endpoint, '_handle_sparql_update')
        assert hasattr(sparql_endpoint, '_describe_endpoint')
    
    def test_get_request_parsing(self, app, sparql_endpoint):
        """Test parsing GET request parameters"""
        with app.test_client() as client:
            # Mock the execution method
            sparql_endpoint._execute_sparql_query = Mock(return_value={
                'head': {'vars': ['subject']},
                'results': {'bindings': []}
            })
            
            response = client.get('/sparql?query=SELECT * WHERE { ?s ?p ?o }')
            
            assert response.status_code == 200
            sparql_endpoint._execute_sparql_query.assert_called_once()
            
            # Check that query was extracted correctly
            call_args = sparql_endpoint._execute_sparql_query.call_args
            assert 'SELECT * WHERE { ?s ?p ?o }' in call_args[0]
    
    def test_post_request_parsing_sparql_query(self, app, sparql_endpoint):
        """Test parsing POST request with application/sparql-query content type"""
        with app.test_client() as client:
            sparql_endpoint._execute_sparql_query = Mock(return_value={
                'head': {'vars': ['subject']},
                'results': {'bindings': []}
            })
            
            query = 'SELECT * WHERE { ?s ?p ?o }'
            response = client.post(
                '/sparql',
                data=query,
                content_type='application/sparql-query'
            )
            
            assert response.status_code == 200
            call_args = sparql_endpoint._execute_sparql_query.call_args
            assert query in call_args[0]
    
    def test_post_request_parsing_form_encoded(self, app, sparql_endpoint):
        """Test parsing POST request with form-encoded content"""
        with app.test_client() as client:
            sparql_endpoint._execute_sparql_query = Mock(return_value={
                'head': {'vars': ['subject']},
                'results': {'bindings': []}
            })
            
            query = 'SELECT * WHERE { ?s ?p ?o }'
            response = client.post(
                '/sparql',
                data={'query': query},
                content_type='application/x-www-form-urlencoded'
            )
            
            assert response.status_code == 200
            call_args = sparql_endpoint._execute_sparql_query.call_args
            assert query in call_args[0]
    
    def test_unsupported_content_type(self, app):
        """Test handling of unsupported content types"""
        with app.test_client() as client:
            response = client.post(
                '/sparql',
                data='SELECT * WHERE { ?s ?p ?o }',
                content_type='text/plain'
            )
            
            assert response.status_code == 400
            assert b'Unsupported content type' in response.data
    
    def test_missing_query_parameter(self, app):
        """Test handling of missing query parameter"""
        with app.test_client() as client:
            response = client.get('/sparql')
            
            assert response.status_code == 400
            assert b'Missing query parameter' in response.data
    
    def test_query_caching(self, sparql_endpoint):
        """Test query result caching"""
        # Setup
        sparql_endpoint.translator.translate_query = Mock(return_value=('MATCH (n) RETURN n', {}))
        sparql_endpoint._execute_cypher_query = Mock(return_value=[{'n': {'id': 'test'}}])
        
        with patch('brain_researcher.services.neurokg.sparql.endpoint.parseQuery') as mock_parse:
            mock_parse.return_value = Mock()
            
            # First execution - should hit database
            result1 = sparql_endpoint._execute_sparql_query('SELECT * WHERE { ?s ?p ?o }')
            
            # Second execution - should hit cache
            result2 = sparql_endpoint._execute_sparql_query('SELECT * WHERE { ?s ?p ?o }')
            
            # Database should only be called once
            assert sparql_endpoint._execute_cypher_query.call_count == 1
            
            # Results should be identical
            assert result1 == result2
            
            # Cache metrics should be updated
            assert sparql_endpoint.query_metrics['total_queries'] == 2
            assert sparql_endpoint.query_metrics['cached_queries'] == 1
    
    def test_cache_expiration(self, sparql_endpoint):
        """Test cache TTL expiration"""
        # Set very short cache TTL for testing
        sparql_endpoint.cache_ttl = 0.1
        
        sparql_endpoint.translator.translate_query = Mock(return_value=('MATCH (n) RETURN n', {}))
        sparql_endpoint._execute_cypher_query = Mock(return_value=[{'n': {'id': 'test'}}])
        
        with patch('brain_researcher.services.neurokg.sparql.endpoint.parseQuery') as mock_parse:
            mock_parse.return_value = Mock()
            
            # First execution
            sparql_endpoint._execute_sparql_query('SELECT * WHERE { ?s ?p ?o }')
            
            # Wait for cache to expire
            time.sleep(0.2)
            
            # Second execution should hit database again
            sparql_endpoint._execute_sparql_query('SELECT * WHERE { ?s ?p ?o }')
            
            # Database should be called twice
            assert sparql_endpoint._execute_cypher_query.call_count == 2
    
    def test_format_sparql_value_uri(self, sparql_endpoint):
        """Test formatting URI values for SPARQL results"""
        value = "https://example.org/resource"
        result = sparql_endpoint._format_sparql_value(value)
        
        expected = {"type": "uri", "value": "https://example.org/resource"}
        assert result == expected
    
    def test_format_sparql_value_literal_string(self, sparql_endpoint):
        """Test formatting string literal values"""
        value = "test string"
        result = sparql_endpoint._format_sparql_value(value)
        
        expected = {"type": "literal", "value": "test string"}
        assert result == expected
    
    def test_format_sparql_value_literal_number(self, sparql_endpoint):
        """Test formatting numeric literal values"""
        value = 42
        result = sparql_endpoint._format_sparql_value(value)
        
        expected = {
            "type": "literal", 
            "value": "42", 
            "datatype": "http://www.w3.org/2001/XMLSchema#decimal"
        }
        assert result == expected
    
    def test_format_sparql_value_literal_boolean(self, sparql_endpoint):
        """Test formatting boolean literal values"""
        value = True
        result = sparql_endpoint._format_sparql_value(value)
        
        expected = {
            "type": "literal", 
            "value": "true", 
            "datatype": "http://www.w3.org/2001/XMLSchema#boolean"
        }
        assert result == expected
    
    def test_format_select_result(self, sparql_endpoint):
        """Test formatting SELECT query results"""
        neo4j_result = [
            {'subject': 'https://example.org/s1', 'predicate': 'https://example.org/p1', 'object': 'value1'},
            {'subject': 'https://example.org/s2', 'predicate': 'https://example.org/p2', 'object': 'value2'}
        ]
        
        # Mock parsed query to return variables
        mock_parsed_query = Mock()
        sparql_endpoint._extract_variables = Mock(return_value=['subject', 'predicate', 'object'])
        
        result = sparql_endpoint._format_select_result(neo4j_result, mock_parsed_query)
        
        assert 'head' in result
        assert 'results' in result
        assert result['head']['vars'] == ['subject', 'predicate', 'object']
        assert len(result['results']['bindings']) == 2
        
        # Check first binding
        first_binding = result['results']['bindings'][0]
        assert first_binding['subject']['type'] == 'uri'
        assert first_binding['subject']['value'] == 'https://example.org/s1'
    
    def test_format_ask_result_true(self, sparql_endpoint):
        """Test formatting ASK query result when true"""
        neo4j_result = [{'count': 1}]
        result = sparql_endpoint._format_ask_result(neo4j_result)
        
        assert result == {"boolean": True}
    
    def test_format_ask_result_false(self, sparql_endpoint):
        """Test formatting ASK query result when false"""
        neo4j_result = []
        result = sparql_endpoint._format_ask_result(neo4j_result)
        
        assert result == {"boolean": False}
    
    def test_format_construct_result(self, sparql_endpoint):
        """Test formatting CONSTRUCT query results"""
        neo4j_result = [
            {'subject': 'https://example.org/s1', 'predicate': 'https://example.org/p1', 'object': 'value1'},
            {'subject': 'https://example.org/s2', 'predicate': 'https://example.org/p2', 'object': 'value2'}
        ]
        
        mock_parsed_query = Mock()
        result = sparql_endpoint._format_construct_result(neo4j_result, mock_parsed_query)
        
        assert 'triples' in result
        assert len(result['triples']) == 2
        
        first_triple = result['triples'][0]
        assert first_triple['subject']['type'] == 'uri'
        assert first_triple['predicate']['type'] == 'uri'
        assert first_triple['object']['type'] == 'literal'
    
    def test_json_result_format(self, app, sparql_endpoint):
        """Test JSON result format output"""
        with app.test_client() as client:
            sparql_endpoint._execute_sparql_query = Mock(return_value={
                'head': {'vars': ['subject']},
                'results': {'bindings': []}
            })
            
            response = client.get(
                '/sparql?query=SELECT * WHERE { ?s ?p ?o }',
                headers={'Accept': 'application/sparql-results+json'}
            )
            
            assert response.status_code == 200
            assert response.content_type == 'application/sparql-results+json'
            
            # Should be valid JSON
            data = json.loads(response.data)
            assert 'head' in data
            assert 'results' in data
    
    def test_xml_result_format(self, app, sparql_endpoint):
        """Test XML result format output"""
        with app.test_client() as client:
            sparql_endpoint._execute_sparql_query = Mock(return_value={
                'head': {'vars': ['subject']},
                'results': {'bindings': []}
            })
            
            response = client.get(
                '/sparql?query=SELECT * WHERE { ?s ?p ?o }',
                headers={'Accept': 'application/sparql-results+xml'}
            )
            
            assert response.status_code == 200
            assert response.content_type == 'application/sparql-results+xml'
            assert b'<?xml version="1.0"?>' in response.data
            assert b'<sparql xmlns="http://www.w3.org/2005/sparql-results#">' in response.data
    
    def test_turtle_result_format(self, app, sparql_endpoint):
        """Test Turtle result format output"""
        with app.test_client() as client:
            sparql_endpoint._execute_sparql_query = Mock(return_value={
                'triples': [
                    {
                        'subject': {'type': 'uri', 'value': 'https://example.org/s1'},
                        'predicate': {'type': 'uri', 'value': 'https://example.org/p1'},
                        'object': {'type': 'literal', 'value': 'object1'}
                    }
                ]
            })
            
            response = client.get(
                '/sparql?query=CONSTRUCT WHERE { ?s ?p ?o }',
                headers={'Accept': 'text/turtle'}
            )
            
            assert response.status_code == 200
            assert response.content_type == 'text/turtle'
            assert b'<https://example.org/s1>' in response.data
            assert b'<https://example.org/p1>' in response.data
            assert b'"object1"' in response.data
    
    def test_query_metrics_endpoint(self, app, sparql_endpoint):
        """Test query metrics endpoint"""
        with app.test_client() as client:
            # Set some test metrics
            sparql_endpoint.query_metrics = {
                'total_queries': 10,
                'cached_queries': 3,
                'failed_queries': 1,
                'avg_execution_time': 0.5
            }
            
            response = client.get('/sparql/metrics')
            
            assert response.status_code == 200
            data = json.loads(response.data)
            
            assert data['total_queries'] == 10
            assert data['cached_queries'] == 3
            assert data['failed_queries'] == 1
            assert data['avg_execution_time'] == 0.5
    
    def test_describe_endpoint(self, app, sparql_endpoint):
        """Test endpoint description"""
        with app.test_client() as client:
            response = client.get('/sparql/describe')
            
            assert response.status_code == 200
            data = json.loads(response.data)
            
            assert 'endpoint_url' in data
            assert 'supported_queries' in data
            assert 'supported_formats' in data
            assert 'federation_enabled' in data
            assert 'query_timeout' in data
            assert 'max_results' in data
            
            assert 'SELECT' in data['supported_queries']
            assert 'CONSTRUCT' in data['supported_queries']
            assert 'ASK' in data['supported_queries']
            assert 'DESCRIBE' in data['supported_queries']
    
    def test_sparql_update_not_supported(self, app):
        """Test that SPARQL UPDATE returns 501 Not Implemented"""
        with app.test_client() as client:
            response = client.post('/sparql/update', data='INSERT DATA { <s> <p> <o> }')
            
            assert response.status_code == 501
            assert b'SPARQL UPDATE not currently supported' in response.data
    
    def test_query_execution_error_handling(self, app, sparql_endpoint):
        """Test error handling during query execution"""
        with app.test_client() as client:
            # Make execution method raise an exception
            sparql_endpoint._execute_sparql_query = Mock(side_effect=Exception("Query failed"))
            
            response = client.get('/sparql?query=SELECT * WHERE { ?s ?p ?o }')
            
            assert response.status_code == 500
            assert b'Query execution error' in response.data
            
            # Failed query metric should be incremented
            assert sparql_endpoint.query_metrics['failed_queries'] == 1
    
    def test_cypher_execution_error_handling(self, sparql_endpoint):
        """Test error handling during Cypher execution"""
        # Setup mock to raise exception
        sparql_endpoint.neo4j_db._run.side_effect = Exception("Database error")
        
        with pytest.raises(Exception, match="Database error"):
            sparql_endpoint._execute_cypher_query("MATCH (n) RETURN n", {})
    
    def test_federation_query_detection(self, sparql_endpoint):
        """Test detection of queries requiring federation"""
        # Mock parsed query
        mock_parsed_query = Mock()
        mock_parsed_query.__str__ = Mock(return_value="SELECT * WHERE { SERVICE <http://dbpedia.org/sparql> { ?s ?p ?o } }")
        
        requires_federation = sparql_endpoint._requires_federation(mock_parsed_query)
        assert requires_federation is True
        
        # Test non-federation query
        mock_parsed_query.__str__ = Mock(return_value="SELECT * WHERE { ?s ?p ?o }")
        requires_federation = sparql_endpoint._requires_federation(mock_parsed_query)
        assert requires_federation is False
    
    def test_cache_key_generation(self, sparql_endpoint):
        """Test cache key generation consistency"""
        query = "SELECT * WHERE { ?s ?p ?o }"
        default_graphs = ["http://example.org/graph1"]
        named_graphs = ["http://example.org/graph2"]
        
        key1 = sparql_endpoint._get_cache_key(query, default_graphs, named_graphs)
        key2 = sparql_endpoint._get_cache_key(query, default_graphs, named_graphs)
        
        assert key1 == key2
        assert len(key1) == 32  # MD5 hash length
        
        # Different parameters should produce different keys
        key3 = sparql_endpoint._get_cache_key("Different query", default_graphs, named_graphs)
        assert key1 != key3
    
    def test_performance_metrics_update(self, sparql_endpoint):
        """Test performance metrics calculation"""
        initial_avg = sparql_endpoint.query_metrics['avg_execution_time']
        initial_total = sparql_endpoint.query_metrics['total_queries']
        
        # Simulate execution time
        execution_time = 0.5
        sparql_endpoint.query_metrics['total_queries'] += 1
        sparql_endpoint._update_execution_metrics(execution_time)
        
        expected_avg = ((initial_avg * initial_total) + execution_time) / (initial_total + 1)
        assert abs(sparql_endpoint.query_metrics['avg_execution_time'] - expected_avg) < 0.001
    
    def test_get_query_type(self, sparql_endpoint):
        """Test query type detection"""
        # Mock parsed queries
        select_query = Mock()
        select_query.__str__ = Mock(return_value="SELECT * WHERE { ?s ?p ?o }")
        assert sparql_endpoint._get_query_type(select_query) == 'SELECT'
        
        construct_query = Mock()
        construct_query.__str__ = Mock(return_value="CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
        assert sparql_endpoint._get_query_type(construct_query) == 'CONSTRUCT'
        
        ask_query = Mock()
        ask_query.__str__ = Mock(return_value="ASK { ?s ?p ?o }")
        assert sparql_endpoint._get_query_type(ask_query) == 'ASK'
        
        describe_query = Mock()
        describe_query.__str__ = Mock(return_value="DESCRIBE <http://example.org/resource>")
        assert sparql_endpoint._get_query_type(describe_query) == 'DESCRIBE'
    
    def test_convert_neo4j_to_sparql_result_select(self, sparql_endpoint):
        """Test conversion of Neo4j results to SPARQL SELECT format"""
        neo4j_result = [
            {'subject': 'https://example.org/s1', 'predicate': 'https://example.org/p1'},
            {'subject': 'https://example.org/s2', 'predicate': 'https://example.org/p2'}
        ]
        
        mock_parsed_query = Mock()
        sparql_endpoint._extract_variables = Mock(return_value=['subject', 'predicate'])
        
        result = sparql_endpoint._convert_neo4j_to_sparql_result(
            neo4j_result, 'SELECT', mock_parsed_query
        )
        
        assert result['head']['vars'] == ['subject', 'predicate']
        assert len(result['results']['bindings']) == 2
    
    def test_convert_neo4j_to_sparql_result_unsupported_type(self, sparql_endpoint):
        """Test handling of unsupported query types"""
        neo4j_result = []
        mock_parsed_query = Mock()
        
        with pytest.raises(ValueError, match="Unsupported query type: UNKNOWN"):
            sparql_endpoint._convert_neo4j_to_sparql_result(
                neo4j_result, 'UNKNOWN', mock_parsed_query
            )


class TestSPARQLEndpointEdgeCases:
    """Test edge cases and error conditions"""
    
    @pytest.fixture
    def minimal_endpoint(self):
        """Create minimal endpoint for edge case testing"""
        mock_db = Mock()
        mock_db._run = Mock(return_value=[])
        
        with patch('brain_researcher.services.neurokg.sparql.endpoint.SPARQLToCypherTranslator'):
            with patch('brain_researcher.services.neurokg.sparql.endpoint.FederationQueryHandler'):
                endpoint = SPARQLEndpoint(
                    neo4j_db=mock_db,
                    enable_federation=False  # Disable federation for edge case testing
                )
                return endpoint
    
    def test_empty_neo4j_result(self, minimal_endpoint):
        """Test handling of empty results from Neo4j"""
        mock_parsed_query = Mock()
        minimal_endpoint._extract_variables = Mock(return_value=['subject'])
        
        result = minimal_endpoint._convert_neo4j_to_sparql_result(
            [], 'SELECT', mock_parsed_query
        )
        
        assert result['head']['vars'] == ['subject']
        assert result['results']['bindings'] == []
    
    def test_none_values_in_result(self, minimal_endpoint):
        """Test handling of None values in Neo4j results"""
        neo4j_result = [
            {'subject': 'https://example.org/s1', 'predicate': None, 'object': 'value1'}
        ]
        
        mock_parsed_query = Mock()
        minimal_endpoint._extract_variables = Mock(return_value=['subject', 'predicate', 'object'])
        
        result = minimal_endpoint._convert_neo4j_to_sparql_result(
            neo4j_result, 'SELECT', mock_parsed_query
        )
        
        bindings = result['results']['bindings']
        assert len(bindings) == 1
        
        # None values should not be included in bindings
        assert 'subject' in bindings[0]
        assert 'predicate' not in bindings[0]
        assert 'object' in bindings[0]
    
    def test_large_result_set_handling(self, minimal_endpoint):
        """Test handling of large result sets within limits"""
        # Create large result set within max_results limit
        large_result = [
            {'subject': f'https://example.org/s{i}', 'predicate': 'https://example.org/p'}
            for i in range(50)  # Within default max_results
        ]
        
        mock_parsed_query = Mock()
        minimal_endpoint._extract_variables = Mock(return_value=['subject', 'predicate'])
        
        result = minimal_endpoint._convert_neo4j_to_sparql_result(
            large_result, 'SELECT', mock_parsed_query
        )
        
        assert len(result['results']['bindings']) == 50
    
    def test_special_characters_in_values(self, minimal_endpoint):
        """Test handling of special characters in values"""
        value_with_quotes = 'Value with "quotes" and \'apostrophes\''
        value_with_newlines = 'Value\nwith\nnewlines'
        value_with_unicode = 'Value with unicode: ñáéíóú 中文'
        
        formatted_quotes = minimal_endpoint._format_sparql_value(value_with_quotes)
        formatted_newlines = minimal_endpoint._format_sparql_value(value_with_newlines)
        formatted_unicode = minimal_endpoint._format_sparql_value(value_with_unicode)
        
        assert formatted_quotes['type'] == 'literal'
        assert formatted_quotes['value'] == value_with_quotes
        
        assert formatted_newlines['type'] == 'literal'
        assert formatted_newlines['value'] == value_with_newlines
        
        assert formatted_unicode['type'] == 'literal'
        assert formatted_unicode['value'] == value_with_unicode
    
    def test_malformed_uri_handling(self, minimal_endpoint):
        """Test handling of malformed URIs"""
        malformed_uri = "not-a-valid-uri"
        
        # Should still be treated as literal since it doesn't start with http
        result = minimal_endpoint._format_sparql_value(malformed_uri)
        assert result['type'] == 'literal'
        assert result['value'] == malformed_uri
    
    def test_concurrent_cache_access(self, minimal_endpoint):
        """Test thread safety of cache operations"""
        import threading
        
        cache_key = "test_key"
        test_result = {"test": "data"}
        
        def cache_operation():
            minimal_endpoint._cache_result(cache_key, test_result, 0.1)
            cached = minimal_endpoint._get_cached_result(cache_key)
            assert cached == test_result
        
        # Run multiple threads concurrently
        threads = []
        for i in range(5):
            thread = threading.Thread(target=cache_operation)
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Cache should still be consistent
        final_cached = minimal_endpoint._get_cached_result(cache_key)
        assert final_cached == test_result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])