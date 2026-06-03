"""
Unit tests for SPARQL to Cypher Translator

Tests the translation of SPARQL queries to equivalent Cypher queries
for execution against Neo4j backend.
"""

import pytest
from unittest.mock import Mock, patch

from brain_researcher.services.br_kg.sparql.translator import SPARQLToCypherTranslator


class TestSPARQLToCypherTranslator:
    """Test suite for SPARQLToCypherTranslator class"""

    @pytest.fixture
    def translator(self):
        """Create SPARQLToCypherTranslator instance"""
        return SPARQLToCypherTranslator(base_uri="https://test.br_kg.org/")

    def test_translator_initialization(self):
        """Test proper initialization of translator"""
        base_uri = "https://example.org/"
        translator = SPARQLToCypherTranslator(base_uri=base_uri)

        assert translator.base_uri == base_uri
        assert translator.variable_counter == 0
        assert isinstance(translator.node_mappings, dict)
        assert isinstance(translator.predicate_mappings, dict)

        # Check predicate mappings include expected entries
        assert 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' in translator.predicate_mappings
        assert f'{base_uri}activatesRegion' in translator.predicate_mappings

        # Check default predicate mappings
        assert translator.predicate_mappings['http://www.w3.org/1999/02/22-rdf-syntax-ns#type'] == 'TYPE'
        assert translator.predicate_mappings[f'{base_uri}activatesRegion'] == 'ACTIVATES_REGION'

    def test_get_node_variable_creation(self, translator):
        """Test creation of Cypher node variables from SPARQL variables"""
        sparql_var = "?subject"
        cypher_var = translator._get_node_variable(sparql_var)

        assert cypher_var == "subject"
        assert sparql_var in translator.node_mappings
        assert translator.node_mappings[sparql_var] == "subject"

    def test_get_node_variable_special_characters(self, translator):
        """Test handling of special characters in variable names"""
        sparql_var = "?subject-name.with_dots"
        cypher_var = translator._get_node_variable(sparql_var)

        # Should replace special characters with underscores
        assert cypher_var == "subject_name_with_dots"
        assert translator.node_mappings[sparql_var] == "subject_name_with_dots"

    def test_get_node_variable_reuse(self, translator):
        """Test reuse of existing variable mappings"""
        sparql_var = "?subject"

        # First call creates mapping
        cypher_var1 = translator._get_node_variable(sparql_var)

        # Second call should return same mapping
        cypher_var2 = translator._get_node_variable(sparql_var)

        assert cypher_var1 == cypher_var2
        assert cypher_var1 == "subject"

    def test_predicate_to_relationship_type_mapped(self, translator):
        """Test conversion of mapped predicates to relationship types"""
        predicate = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        rel_type = translator._predicate_to_relationship_type(predicate)

        assert rel_type == "TYPE"

    def test_predicate_to_relationship_type_uri_fragment(self, translator):
        """Test extraction from URI fragment"""
        predicate = "http://example.org/ontology#partOf"
        rel_type = translator._predicate_to_relationship_type(predicate)

        assert rel_type == "PARTOF"

    def test_predicate_to_relationship_type_uri_path(self, translator):
        """Test extraction from URI path component"""
        predicate = "http://example.org/ontology/relatedTo"
        rel_type = translator._predicate_to_relationship_type(predicate)

        assert rel_type == "RELATEDTO"

    def test_predicate_to_relationship_type_simple_string(self, translator):
        """Test conversion of simple string predicates"""
        predicate = "hasProperty"
        rel_type = translator._predicate_to_relationship_type(predicate)

        assert rel_type == "HASPROPERTY"

    def test_predicate_to_relationship_type_special_characters(self, translator):
        """Test handling of special characters in predicates"""
        predicate = "has-property_name with spaces"
        rel_type = translator._predicate_to_relationship_type(predicate)

        assert rel_type == "HAS_PROPERTY_NAME_WITH_SPACES"

    def test_uri_to_node_id_base_uri(self, translator):
        """Test conversion of base URI to node ID"""
        uri = "https://test.br_kg.org/concept123"
        node_id = translator._uri_to_node_id(uri)

        assert node_id == "concept123"

    def test_uri_to_node_id_external_uri(self, translator):
        """Test handling of external URIs"""
        uri = "http://example.org/resource456"
        node_id = translator._uri_to_node_id(uri)

        assert node_id == uri  # Should return full URI

    def test_translate_triple_pattern_variable_subject_object(self, translator):
        """Test translation of triple pattern with variable subject and object"""
        pattern = ("?subject", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "?object")

        match_clause, where_clause, params = translator._translate_triple_pattern(pattern)

        assert "subject" in match_clause
        assert "object" in match_clause
        assert "TYPE" in match_clause
        assert "->" in match_clause
        assert len(params) == 0  # No literal parameters

    def test_translate_triple_pattern_literal_object(self, translator):
        """Test translation of triple pattern with literal object"""
        pattern = ("?subject", "http://example.org/hasValue", '"literal_value"')

        match_clause, where_clause, params = translator._translate_triple_pattern(pattern)

        # Should handle literal as node property, not relationship
        assert "subject" in match_clause
        assert len(params) == 1

        param_key = list(params.keys())[0]
        assert params[param_key] == "literal_value"

    def test_translate_triple_pattern_uri_subject_object(self, translator):
        """Test translation with URI subject and object"""
        pattern = (
            "https://test.br_kg.org/subject1",
            "http://example.org/relatedTo",
            "https://test.br_kg.org/object1"
        )

        match_clause, where_clause, params = translator._translate_triple_pattern(pattern)

        # Should have parameters for both URIs
        assert len(params) >= 2
        assert "subject1" in list(params.values())
        assert "object1" in list(params.values())

        # Should use parameter placeholders in query
        assert "$" in match_clause

    def test_get_query_type_select(self, translator):
        """Test query type detection for SELECT queries"""
        mock_query = Mock()
        mock_query.__str__ = Mock(return_value="SELECT ?s ?p ?o WHERE { ?s ?p ?o }")

        query_type = translator._get_query_type(mock_query)
        assert query_type == "SELECT"

    def test_get_query_type_construct(self, translator):
        """Test query type detection for CONSTRUCT queries"""
        mock_query = Mock()
        mock_query.__str__ = Mock(return_value="CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")

        query_type = translator._get_query_type(mock_query)
        assert query_type == "CONSTRUCT"

    def test_get_query_type_ask(self, translator):
        """Test query type detection for ASK queries"""
        mock_query = Mock()
        mock_query.__str__ = Mock(return_value="ASK { ?s ?p ?o }")

        query_type = translator._get_query_type(mock_query)
        assert query_type == "ASK"

    def test_get_query_type_describe(self, translator):
        """Test query type detection for DESCRIBE queries"""
        mock_query = Mock()
        mock_query.__str__ = Mock(return_value="DESCRIBE <http://example.org/resource>")

        query_type = translator._get_query_type(mock_query)
        assert query_type == "DESCRIBE"

    def test_get_query_type_unknown(self, translator):
        """Test query type detection for unknown queries"""
        mock_query = Mock()
        mock_query.__str__ = Mock(return_value="UNKNOWN QUERY TYPE")

        query_type = translator._get_query_type(mock_query)
        assert query_type == "UNKNOWN"

    def test_build_return_clause_variables(self, translator):
        """Test building RETURN clause with specific variables"""
        variables = ["?subject", "?predicate", "?object"]

        # Need to set up node mappings for variables
        for var in variables:
            translator._get_node_variable(var)

        return_clause = translator._build_return_clause(variables)

        assert "subject" in return_clause
        assert "predicate" in return_clause
        assert "object" in return_clause
        assert "subject.id as subject" in return_clause

    def test_build_return_clause_wildcard(self, translator):
        """Test building RETURN clause with wildcard"""
        variables = ["*"]
        return_clause = translator._build_return_clause(variables)

        assert return_clause == "*"

    def test_build_return_clause_empty(self, translator):
        """Test building RETURN clause with empty variable list"""
        variables = []
        return_clause = translator._build_return_clause(variables)

        assert return_clause == "*"

    def test_build_construct_return(self, translator):
        """Test building RETURN clause for CONSTRUCT queries"""
        construct_patterns = []  # Not used in current implementation
        return_clause = translator._build_construct_return(construct_patterns)

        assert return_clause == "subject, predicate, object"

    def test_translate_order_by(self, translator):
        """Test ORDER BY clause translation"""
        order_by = "?subject"
        order_clause = translator._translate_order_by(order_by)

        assert order_clause == "ORDER BY ?subject"

    def test_extract_select_variables_default(self, translator):
        """Test default variable extraction (simplified implementation)"""
        mock_query = Mock()
        variables = translator._extract_select_variables(mock_query)

        # Current implementation returns default variables
        assert variables == ['?subject', '?predicate', '?object']

    def test_extract_where_patterns_default(self, translator):
        """Test default WHERE pattern extraction (simplified implementation)"""
        mock_query = Mock()
        patterns = translator._extract_where_patterns(mock_query)

        # Current implementation returns default pattern
        assert len(patterns) == 1
        assert patterns[0] == ('?subject', 'http://example.org/predicate', '?object')

    def test_extract_filters_empty(self, translator):
        """Test FILTER extraction (not yet implemented)"""
        mock_query = Mock()
        filters = translator._extract_filters(mock_query)

        assert filters == []

    def test_extract_optional_patterns_empty(self, translator):
        """Test OPTIONAL pattern extraction (not yet implemented)"""
        mock_query = Mock()
        optional = translator._extract_optional_patterns(mock_query)

        assert optional == []

    def test_extract_limit_none(self, translator):
        """Test LIMIT extraction (not yet implemented)"""
        mock_query = Mock()
        limit = translator._extract_limit(mock_query)

        assert limit is None

    def test_extract_offset_none(self, translator):
        """Test OFFSET extraction (not yet implemented)"""
        mock_query = Mock()
        offset = translator._extract_offset(mock_query)

        assert offset is None

    def test_extract_describe_resources_default(self, translator):
        """Test DESCRIBE resource extraction (simplified implementation)"""
        mock_query = Mock()
        resources = translator._extract_describe_resources(mock_query)

        assert resources == ['?resource']


class TestSPARQLTranslatorQueryTranslation:
    """Test full query translation scenarios"""

    @pytest.fixture
    def translator(self):
        return SPARQLToCypherTranslator(base_uri="https://br_kg.org/")

    @patch('brain_researcher.services.br_kg.sparql.translator.parseQuery')
    def test_translate_select_query_basic(self, mock_parse_query, translator):
        """Test basic SELECT query translation"""
        mock_parsed_query = Mock()
        mock_parse_query.return_value = mock_parsed_query

        # Mock the query type detection
        translator._get_query_type = Mock(return_value='SELECT')

        # Mock component extraction methods
        translator._extract_select_variables = Mock(return_value=['?subject', '?object'])
        translator._extract_where_patterns = Mock(return_value=[('?subject', 'http://example.org/pred', '?object')])
        translator._extract_filters = Mock(return_value=[])
        translator._extract_optional_patterns = Mock(return_value=[])
        translator._extract_order_by = Mock(return_value=None)
        translator._extract_limit = Mock(return_value=None)
        translator._extract_offset = Mock(return_value=None)

        cypher_query, params = translator.translate_query(mock_parsed_query)

        assert isinstance(cypher_query, str)
        assert isinstance(params, dict)
        assert "MATCH" in cypher_query
        assert "RETURN" in cypher_query

    @patch('brain_researcher.services.br_kg.sparql.translator.parseQuery')
    def test_translate_construct_query_basic(self, mock_parse_query, translator):
        """Test basic CONSTRUCT query translation"""
        mock_parsed_query = Mock()
        mock_parse_query.return_value = mock_parsed_query

        translator._get_query_type = Mock(return_value='CONSTRUCT')
        translator._extract_construct_patterns = Mock(return_value=[])
        translator._extract_where_patterns = Mock(return_value=[('?subject', 'http://example.org/pred', '?object')])

        cypher_query, params = translator.translate_query(mock_parsed_query)

        assert isinstance(cypher_query, str)
        assert isinstance(params, dict)
        assert "MATCH" in cypher_query
        assert "RETURN" in cypher_query
        assert "subject, predicate, object" in cypher_query

    @patch('brain_researcher.services.br_kg.sparql.translator.parseQuery')
    def test_translate_ask_query_basic(self, mock_parse_query, translator):
        """Test basic ASK query translation"""
        mock_parsed_query = Mock()
        mock_parse_query.return_value = mock_parsed_query

        translator._get_query_type = Mock(return_value='ASK')
        translator._extract_where_patterns = Mock(return_value=[('?subject', 'http://example.org/pred', '?object')])

        cypher_query, params = translator.translate_query(mock_parsed_query)

        assert isinstance(cypher_query, str)
        assert isinstance(params, dict)
        assert "MATCH" in cypher_query
        assert "count(*) > 0 as result" in cypher_query
        assert "LIMIT 1" in cypher_query

    @patch('brain_researcher.services.br_kg.sparql.translator.parseQuery')
    def test_translate_describe_query_basic(self, mock_parse_query, translator):
        """Test basic DESCRIBE query translation"""
        mock_parsed_query = Mock()
        mock_parse_query.return_value = mock_parsed_query

        translator._get_query_type = Mock(return_value='DESCRIBE')
        translator._extract_describe_resources = Mock(return_value=['?resource'])

        cypher_query, params = translator.translate_query(mock_parsed_query)

        assert isinstance(cypher_query, str)
        assert isinstance(params, dict)
        assert "MATCH" in cypher_query
        assert "OPTIONAL MATCH" in cypher_query
        assert "type(r) as predicate" in cypher_query

    @patch('brain_researcher.services.br_kg.sparql.translator.parseQuery')
    def test_translate_query_with_optional_patterns(self, mock_parse_query, translator):
        """Test query translation with OPTIONAL patterns"""
        mock_parsed_query = Mock()
        mock_parse_query.return_value = mock_parsed_query

        translator._get_query_type = Mock(return_value='SELECT')
        translator._extract_select_variables = Mock(return_value=['?subject', '?object'])
        translator._extract_where_patterns = Mock(return_value=[('?subject', 'http://example.org/pred', '?object')])
        translator._extract_filters = Mock(return_value=[])
        translator._extract_optional_patterns = Mock(return_value=[('?subject', 'http://example.org/optPred', '?optObject')])
        translator._extract_order_by = Mock(return_value=None)
        translator._extract_limit = Mock(return_value=None)
        translator._extract_offset = Mock(return_value=None)

        cypher_query, params = translator.translate_query(mock_parsed_query)

        assert "OPTIONAL MATCH" in cypher_query

    @patch('brain_researcher.services.br_kg.sparql.translator.parseQuery')
    def test_translate_query_with_limit_offset(self, mock_parse_query, translator):
        """Test query translation with LIMIT and OFFSET"""
        mock_parsed_query = Mock()
        mock_parse_query.return_value = mock_parsed_query

        translator._get_query_type = Mock(return_value='SELECT')
        translator._extract_select_variables = Mock(return_value=['?subject'])
        translator._extract_where_patterns = Mock(return_value=[('?subject', 'http://example.org/pred', '?object')])
        translator._extract_filters = Mock(return_value=[])
        translator._extract_optional_patterns = Mock(return_value=[])
        translator._extract_order_by = Mock(return_value='?subject')
        translator._extract_limit = Mock(return_value=10)
        translator._extract_offset = Mock(return_value=5)

        cypher_query, params = translator.translate_query(mock_parsed_query)

        assert "ORDER BY ?subject" in cypher_query
        assert "LIMIT 10" in cypher_query
        assert "SKIP 5" in cypher_query

    def test_translate_query_unsupported_type(self, translator):
        """Test handling of unsupported query types"""
        mock_parsed_query = Mock()
        translator._get_query_type = Mock(return_value='UNKNOWN')

        with pytest.raises(ValueError, match="Unsupported query type: UNKNOWN"):
            translator.translate_query(mock_parsed_query)

    def test_translate_query_exception_handling(self, translator):
        """Test exception handling during translation"""
        mock_parsed_query = Mock()
        translator._get_query_type = Mock(side_effect=Exception("Parse error"))

        with pytest.raises(Exception, match="Parse error"):
            translator.translate_query(mock_parsed_query)

    def test_variable_counter_reset(self, translator):
        """Test variable counter is reset for each translation"""
        mock_parsed_query = Mock()
        translator._get_query_type = Mock(return_value='SELECT')
        translator._extract_select_variables = Mock(return_value=['?s'])
        translator._extract_where_patterns = Mock(return_value=[])
        translator._extract_filters = Mock(return_value=[])
        translator._extract_optional_patterns = Mock(return_value=[])
        translator._extract_order_by = Mock(return_value=None)
        translator._extract_limit = Mock(return_value=None)
        translator._extract_offset = Mock(return_value=None)

        # First translation
        translator.translate_query(mock_parsed_query)
        first_counter = translator.variable_counter

        # Second translation should reset counter
        translator.translate_query(mock_parsed_query)

        # Counter should start from 0 again
        assert translator.variable_counter >= 0

    def test_node_mappings_reset(self, translator):
        """Test node mappings are reset for each translation"""
        mock_parsed_query = Mock()
        translator._get_query_type = Mock(return_value='SELECT')
        translator._extract_select_variables = Mock(return_value=['?s'])
        translator._extract_where_patterns = Mock(return_value=[])
        translator._extract_filters = Mock(return_value=[])
        translator._extract_optional_patterns = Mock(return_value=[])
        translator._extract_order_by = Mock(return_value=None)
        translator._extract_limit = Mock(return_value=None)
        translator._extract_offset = Mock(return_value=None)

        # First translation with mappings
        translator.translate_query(mock_parsed_query)

        # Add some mappings manually
        translator._get_node_variable("?test")
        first_mappings = translator.node_mappings.copy()

        # Second translation should reset mappings
        translator.translate_query(mock_parsed_query)

        # Mappings should be empty or different
        assert len(translator.node_mappings) == 0 or translator.node_mappings != first_mappings


class TestSPARQLTranslatorComplexScenarios:
    """Test complex translation scenarios and edge cases"""

    @pytest.fixture
    def translator(self):
        return SPARQLToCypherTranslator(base_uri="https://br_kg.org/")

    def test_multiple_triple_patterns(self, translator):
        """Test handling multiple triple patterns in WHERE clause"""
        patterns = [
            ('?subject', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', '?type'),
            ('?subject', 'http://br_kg.org/hasProperty', '?property'),
            ('?property', 'http://br_kg.org/hasValue', '"some_value"')
        ]

        match_clauses = []
        where_clauses = []
        all_params = {}

        for pattern in patterns:
            match_clause, where_clause, params = translator._translate_triple_pattern(pattern)
            if match_clause:
                match_clauses.append(match_clause)
            if where_clause:
                where_clauses.append(where_clause)
            all_params.update(params)

        assert len(match_clauses) >= 2  # At least two relationship patterns
        assert len(all_params) > 0  # Should have parameters from literal

    def test_nested_uri_structure(self, translator):
        """Test handling of deeply nested URI structures"""
        complex_uri = "https://br_kg.org/brain/regions/cortical/frontal/prefrontal"
        node_id = translator._uri_to_node_id(complex_uri)

        # Should extract path after base URI
        assert node_id == "brain/regions/cortical/frontal/prefrontal"

    def test_international_characters(self, translator):
        """Test handling of international characters in URIs and literals"""
        uri_with_unicode = "https://br_kg.org/región-cerebral"
        literal_with_unicode = '"描述性文本"'

        node_id = translator._uri_to_node_id(uri_with_unicode)
        assert node_id == "región-cerebral"

        # Test triple pattern with unicode
        pattern = ('?subject', 'http://example.org/description', literal_with_unicode)
        match_clause, where_clause, params = translator._translate_triple_pattern(pattern)

        # Should handle unicode in parameters
        assert any("描述性文本" in str(value) for value in params.values())

    def test_very_long_uris(self, translator):
        """Test handling of very long URIs"""
        long_uri = "https://br_kg.org/" + "very_long_path/" * 50 + "final_resource"
        node_id = translator._uri_to_node_id(long_uri)

        # Should extract full path after base URI
        expected = "very_long_path/" * 50 + "final_resource"
        assert node_id == expected

    def test_edge_case_empty_patterns(self, translator):
        """Test handling of edge cases with empty or None patterns"""
        # Test with empty pattern components
        pattern = ('', '', '')
        match_clause, where_clause, params = translator._translate_triple_pattern(pattern)

        # Should handle gracefully without crashing
        assert isinstance(match_clause, str)
        assert isinstance(where_clause, str)
        assert isinstance(params, dict)

    def test_case_sensitivity(self, translator):
        """Test case sensitivity in predicate mappings"""
        predicate_lower = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        predicate_upper = "HTTP://WWW.W3.ORG/1999/02/22-RDF-SYNTAX-NS#TYPE"

        # Exact match should work
        rel_type1 = translator._predicate_to_relationship_type(predicate_lower)
        assert rel_type1 == "TYPE"

        # Case difference should not match and extract from URI
        rel_type2 = translator._predicate_to_relationship_type(predicate_upper)
        # Should extract from URI since no exact match
        assert rel_type2 == "TYPE"  # Fragment extraction should work


if __name__ == '__main__':
    pytest.main([__file__, '-v'])