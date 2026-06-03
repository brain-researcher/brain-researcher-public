"""
Unit tests for Natural Language Query agents
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from brain_researcher.services.br_kg.nl_query import (
    NaturalLanguageQueryOrchestrator,
    QueryParserAgent,
    SchemaMapperAgent,
    QueryBuilderAgent,
    ResultFormatterAgent,
    ParsedQuery,
    MappedQuery,
    ExecutableQuery,
    FormattedResult
)
from brain_researcher.services.br_kg.nl_query.agents import (
    QueryIntent,
    EntityType,
    ExtractedEntity,
    NodeType,
    RelationType,
    QueryType,
    VisualizationType
)


class TestQueryParserAgent:
    """Test the Query Parser Agent"""

    @pytest.fixture
    def parser(self):
        return QueryParserAgent()

    def test_parse_simple_query(self, parser):
        """Test parsing a simple search query"""
        query = "Find hippocampus activation"
        result = parser.parse(query)

        assert isinstance(result, ParsedQuery)
        assert result.intent == QueryIntent.SEARCH
        assert len(result.entities) == 1
        assert result.entities[0].type == EntityType.BRAIN_REGION
        assert result.entities[0].normalized_form == 'hippocampus'

    def test_parse_complex_query(self, parser):
        """Test parsing a complex query with multiple entities"""
        query = "Compare working memory activation in hippocampus vs amygdala"
        result = parser.parse(query)

        assert result.intent == QueryIntent.COMPARE
        assert len(result.entities) >= 3

        entity_types = {e.type for e in result.entities}
        assert EntityType.COGNITIVE_TASK in entity_types
        assert EntityType.BRAIN_REGION in entity_types

    def test_parse_query_with_constraints(self, parser):
        """Test parsing query with numeric constraints"""
        query = "Find studies with more than 100 subjects published after 2020"
        result = parser.parse(query)

        assert len(result.constraints) >= 2

        # Check for numeric constraint
        numeric_constraints = [c for c in result.constraints if c.type == 'numeric']
        assert len(numeric_constraints) > 0
        assert numeric_constraints[0].operator in ['gt', 'gte']
        assert numeric_constraints[0].value == 100

        # Check for temporal constraint
        temporal_constraints = [c for c in result.constraints if c.type == 'temporal']
        assert len(temporal_constraints) > 0

    def test_parse_aggregation_query(self, parser):
        """Test parsing aggregation query"""
        query = "How many brain regions are associated with Alzheimer's?"
        result = parser.parse(query)

        assert result.intent == QueryIntent.AGGREGATE
        assert any(e.type == EntityType.DISORDER for e in result.entities)
        assert any('alzheimer' in e.normalized_form for e in result.entities)

    def test_extract_modifiers(self, parser):
        """Test extraction of query modifiers"""
        query = "Show top 10 results sorted by p-value ascending"
        result = parser.parse(query)

        assert result.modifiers.get('limit') == 10
        assert result.modifiers.get('sort_by') == 'p-value'
        assert result.modifiers.get('sort_order') == 'asc'

    def test_detect_ambiguities(self, parser):
        """Test ambiguity detection"""
        query = "What about it?"
        result = parser.parse(query)

        assert len(result.ambiguities) > 0
        assert any('pronoun' in amb.lower() for amb in result.ambiguities)


class TestSchemaMapperAgent:
    """Test the Schema Mapper Agent"""

    @pytest.fixture
    def mapper(self):
        return SchemaMapperAgent()

    @pytest.fixture
    def parsed_query(self):
        return ParsedQuery(
            original_query="Find hippocampus activation in working memory",
            intent=QueryIntent.SEARCH,
            entities=[
                ExtractedEntity(
                    text="hippocampus",
                    type=EntityType.BRAIN_REGION,
                    normalized_form="hippocampus",
                    position=5,
                    confidence=0.9
                ),
                ExtractedEntity(
                    text="working memory",
                    type=EntityType.COGNITIVE_TASK,
                    normalized_form="working_memory",
                    position=20,
                    confidence=0.85
                )
            ],
            constraints=[],
            modifiers={},
            confidence_score=0.87
        )

    def test_map_to_schema(self, mapper, parsed_query):
        """Test mapping parsed query to graph schema"""
        result = mapper.map_to_schema(parsed_query)

        assert isinstance(result, MappedQuery)
        assert len(result.graph_patterns) > 0

        # Check for activation pattern
        pattern = result.graph_patterns[0]
        assert len(pattern.nodes) >= 2
        assert any(n['type'] == NodeType.BRAIN_REGION for n in pattern.nodes)
        assert any(n['type'] == NodeType.TASK for n in pattern.nodes)

    def test_generate_patterns(self, mapper, parsed_query):
        """Test pattern generation from entities"""
        node_mappings = mapper._map_entities_to_nodes(parsed_query.entities)
        patterns = mapper._generate_patterns(
            parsed_query.intent,
            node_mappings,
            parsed_query.entities
        )

        assert len(patterns) > 0
        assert patterns[0].pattern_string
        assert 'Task' in patterns[0].pattern_string
        assert 'BrainRegion' in patterns[0].pattern_string

    def test_map_constraints(self, mapper):
        """Test constraint mapping"""
        parsed_query = ParsedQuery(
            original_query="Find studies with p-value < 0.05",
            intent=QueryIntent.SEARCH,
            entities=[],
            constraints=[
                Mock(type='numeric', field='p_value', operator='lt', value=0.05, confidence=0.8)
            ],
            modifiers={},
            confidence_score=0.7
        )

        result = mapper.map_to_schema(parsed_query)

        assert len(result.constraints) == 1
        assert result.constraints[0]['operator'] == 'lt'
        assert result.constraints[0]['value'] == 0.05


class TestQueryBuilderAgent:
    """Test the Query Builder Agent"""

    @pytest.fixture
    def builder(self):
        return QueryBuilderAgent()

    @pytest.fixture
    def mapped_query(self):
        parsed_query = Mock(
            intent=QueryIntent.SEARCH,
            modifiers={'limit': 10},
            confidence_score=0.8
        )

        return MappedQuery(
            parsed_query=parsed_query,
            graph_patterns=[
                Mock(
                    pattern_string="(task:Task)-[:ACTIVATES]->(region:BrainRegion)",
                    nodes=[
                        {'id': 'n1', 'type': NodeType.TASK, 'alias': 'task'},
                        {'id': 'n2', 'type': NodeType.BRAIN_REGION, 'alias': 'region'}
                    ],
                    relationships=[],
                    confidence=0.9
                )
            ],
            node_filters={'n2': [{'property': 'name', 'operator': 'eq', 'value': 'hippocampus'}]},
            relationship_filters={},
            constraints=[],
            projections=['task', 'region'],
            confidence_score=0.85
        )

    def test_build_cypher_query(self, builder, mapped_query):
        """Test building a Cypher query"""
        result = builder.build_query(mapped_query)

        assert isinstance(result, ExecutableQuery)
        assert result.query_type == QueryType.CYPHER
        assert 'MATCH' in result.query_string
        assert 'RETURN' in result.query_string
        assert result.confidence_score > 0

    def test_build_query_with_filters(self, builder, mapped_query):
        """Test query building with filters"""
        query_string, parameters = builder._build_cypher_query(mapped_query)

        assert 'WHERE' in query_string
        assert 'hippocampus' in parameters.values()

    def test_query_optimization(self, builder, mapped_query):
        """Test query optimization"""
        initial_query = "MATCH (n:Node) WHERE n.prop = 'value' RETURN n"
        optimized_query, optimizations = builder._optimize_query(
            initial_query,
            QueryType.CYPHER,
            mapped_query
        )

        assert len(optimizations) > 0
        assert 'filter_reordering' in optimizations

    def test_fallback_query_generation(self, builder, mapped_query):
        """Test fallback query generation"""
        fallback = builder._generate_fallback_query(mapped_query)

        assert fallback is not None
        assert 'MATCH' in fallback
        assert 'LIMIT' in fallback


class TestResultFormatterAgent:
    """Test the Result Formatter Agent"""

    @pytest.fixture
    def formatter(self):
        return ResultFormatterAgent()

    @pytest.fixture
    def raw_results(self):
        return {
            'results': [
                {
                    'region': {
                        'labels': ['BrainRegion'],
                        'properties': {'name': 'hippocampus', 'volume': 3500},
                        'id': 1
                    },
                    'task': {
                        'labels': ['Task'],
                        'properties': {'name': 'working_memory', 'domain': 'cognitive'},
                        'id': 2
                    }
                }
            ],
            'count': 1
        }

    def test_format_results(self, formatter, raw_results):
        """Test result formatting"""
        result = formatter.format_results(raw_results)

        assert isinstance(result, FormattedResult)
        assert result.summary
        assert len(result.data) == 1
        assert result.confidence_score > 0

    def test_structure_cypher_results(self, formatter, raw_results):
        """Test structuring Cypher results"""
        structured = formatter._structure_results(raw_results)

        assert len(structured) == 1
        assert 'region' in structured[0]
        assert structured[0]['region']['type'] == 'node'
        assert structured[0]['region']['properties']['name'] == 'hippocampus'

    def test_generate_summary(self, formatter):
        """Test summary generation"""
        data = [
            {'entity': {'type': 'node', 'properties': {'name': 'hippocampus'}}}
        ]

        summary = formatter._generate_summary(data, None)

        assert 'Found' in summary
        assert isinstance(summary, str)

    def test_determine_visualization(self, formatter):
        """Test visualization determination"""
        # Test with coordinate data
        data = [
            {'coordinates': [10, 20, 30], 'activation': 3.5}
        ]

        viz_hints = formatter._determine_visualization(data, None)

        assert viz_hints['type'] == VisualizationType.BRAIN_MAP
        assert 'coordinate_field' in viz_hints['parameters']

    def test_generate_explanation(self, formatter):
        """Test explanation generation"""
        parsed_query = Mock(
            original_query="Find hippocampus",
            entities=[Mock(type=Mock(value='brain_region'), text='hippocampus')]
        )

        data = [{'region': 'hippocampus'}]

        explanation = formatter._generate_explanation(data, parsed_query)

        assert 'Searched for' in explanation
        assert 'hippocampus' in explanation


class TestNLQueryOrchestrator:
    """Test the Natural Language Query Orchestrator"""

    @pytest.fixture
    def orchestrator(self):
        parser = Mock(spec=QueryParserAgent)
        mapper = Mock(spec=SchemaMapperAgent)
        builder = Mock(spec=QueryBuilderAgent)
        formatter = Mock(spec=ResultFormatterAgent)

        return NaturalLanguageQueryOrchestrator(
            parser_agent=parser,
            mapper_agent=mapper,
            builder_agent=builder,
            formatter_agent=formatter
        )

    def test_process_query(self, orchestrator):
        """Test end-to-end query processing"""
        # Mock agent responses
        orchestrator.parser_agent.parse.return_value = Mock(
            intent=QueryIntent.SEARCH,
            entities=[],
            constraints=[],
            modifiers={},
            confidence_score=0.8
        )

        orchestrator.mapper_agent.map_to_schema.return_value = Mock(
            graph_patterns=[Mock()],
            node_filters={},
            relationship_filters={},
            constraints=[],
            projections=['*'],
            confidence_score=0.7
        )

        orchestrator.builder_agent.build_query.return_value = Mock(
            query_type=QueryType.CYPHER,
            query_string="MATCH (n) RETURN n",
            parameters={},
            confidence_score=0.75
        )

        orchestrator.formatter_agent.format_results.return_value = Mock(
            summary="Found results",
            data=[],
            visualization_hints={},
            confidence_score=0.8
        )

        # Process query
        result = orchestrator.process_query("Find hippocampus")

        assert result['success'] is True
        assert 'result' in result
        assert 'confidence' in result

    def test_query_caching(self, orchestrator):
        """Test query result caching"""
        query = "Find hippocampus"

        # Mock successful processing
        orchestrator.parser_agent.parse.return_value = Mock(
            intent=QueryIntent.SEARCH,
            entities=[],
            constraints=[],
            modifiers={},
            confidence_score=0.8
        )

        orchestrator.mapper_agent.map_to_schema.return_value = Mock(
            graph_patterns=[],
            node_filters={},
            relationship_filters={},
            constraints=[],
            projections=['*'],
            confidence_score=0.7
        )

        orchestrator.builder_agent.build_query.return_value = Mock(
            query_type=QueryType.CYPHER,
            query_string="MATCH (n) RETURN n",
            parameters={},
            fallback_query=None,
            confidence_score=0.75
        )

        orchestrator.formatter_agent.format_results.return_value = Mock(
            summary="Found results",
            data=[],
            visualization_hints={},
            confidence_score=0.8
        )

        # First call
        result1 = orchestrator.process_query(query)

        # Second call should use cache
        result2 = orchestrator.process_query(query)

        # Parser should only be called once if caching works
        assert orchestrator.parser_agent.parse.call_count == 1

    def test_error_handling(self, orchestrator):
        """Test error handling during query processing"""
        orchestrator.parser_agent.parse.side_effect = Exception("Parse error")

        result = orchestrator.process_query("Invalid query")

        assert result['success'] is False
        assert 'error' in result
        assert 'Parse error' in result['error']
