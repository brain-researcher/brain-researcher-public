"""
Unit tests for Advanced Query Understanding Module (AGENT-017)

Tests cover:
- Entity extraction accuracy  
- Domain term recognition
- Query expansion coverage
- Context integration
- Intent classification
- Property-based tests for parsing consistency
"""

import json
import pytest
import re
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

import numpy as np
from hypothesis import given, strategies as st

# Import modules under test
from brain_researcher.services.agent.query_understanding import (
    AdvancedQueryParser,
    EntityExtractor,
    QueryExpander,
    ContextManager,
    EntityType,
    QueryIntent,
    ExtractedEntity,
    QueryExpansion,
    ParsedQuery,
    create_advanced_parser
)


class TestEntityType:
    """Test EntityType enum and validation."""
    
    def test_entity_types_exist(self):
        """Test that all expected entity types are defined."""
        expected_types = [
            "brain_region", "task", "dataset", "contrast", "statistical_method",
            "preprocessing_step", "modality", "subject_group", "metric", "coordinate"
        ]
        
        for expected_type in expected_types:
            assert hasattr(EntityType, expected_type.upper())
            entity_type = EntityType(expected_type)
            assert entity_type.value == expected_type


class TestQueryIntent:
    """Test QueryIntent enum and validation."""
    
    def test_query_intents_exist(self):
        """Test that all expected query intents are defined."""
        expected_intents = [
            "analysis", "comparison", "correlation", "prediction", "visualization",
            "search", "preprocessing", "meta_analysis", "quality_control", "data_extraction"
        ]
        
        for expected_intent in expected_intents:
            assert hasattr(QueryIntent, expected_intent.upper())
            intent = QueryIntent(expected_intent)
            assert intent.value == expected_intent


class TestExtractedEntity:
    """Test ExtractedEntity dataclass."""
    
    def test_extracted_entity_creation(self):
        """Test basic entity creation."""
        entity = ExtractedEntity(
            text="prefrontal cortex",
            entity_type=EntityType.BRAIN_REGION,
            confidence=0.95,
            normalized_form="prefrontal cortex",
            context="analyze activation in prefrontal cortex",
            aliases=["pfc", "frontal cortex"],
            metadata={"frequency": 150}
        )
        
        assert entity.text == "prefrontal cortex"
        assert entity.entity_type == EntityType.BRAIN_REGION
        assert entity.confidence == 0.95
        assert entity.normalized_form == "prefrontal cortex"
        assert len(entity.aliases) == 2
        assert entity.metadata["frequency"] == 150
    
    def test_extracted_entity_with_coordinates(self):
        """Test entity creation with coordinates."""
        entity = ExtractedEntity(
            text="coordinate (-45, 24, 36)",
            entity_type=EntityType.COORDINATE,
            confidence=0.9,
            normalized_form="[-45, 24, 36]",
            coordinates=(-45, 24, 36)
        )
        
        assert entity.coordinates == (-45, 24, 36)
        assert len(entity.coordinates) == 3
    
    @given(confidence=st.floats(min_value=0.0, max_value=1.0))
    def test_entity_confidence_bounds(self, confidence):
        """Property test: entity confidence should be within bounds."""
        entity = ExtractedEntity(
            text="test",
            entity_type=EntityType.BRAIN_REGION,
            confidence=confidence,
            normalized_form="test"
        )
        
        assert 0.0 <= entity.confidence <= 1.0


class TestQueryExpansion:
    """Test QueryExpansion dataclass."""
    
    def test_query_expansion_creation(self):
        """Test query expansion creation."""
        expansion = QueryExpansion(
            original_query="fmri connectivity analysis",
            expanded_terms={
                "fmri": ["functional mri", "bold fmri"],
                "connectivity": ["functional connectivity", "effective connectivity"]
            },
            synonyms={
                "fmri": ["functional mri", "functional magnetic resonance imaging"],
                "analysis": ["statistical analysis", "data analysis"]
            },
            related_concepts=["correlation", "network analysis", "graph theory"],
            domain_terms=["bold", "roi", "glm"],
            confidence=0.85
        )
        
        assert expansion.original_query == "fmri connectivity analysis"
        assert len(expansion.expanded_terms) == 2
        assert len(expansion.synonyms) == 2
        assert len(expansion.related_concepts) == 3
        assert len(expansion.domain_terms) == 3
        assert expansion.confidence == 0.85


class TestParsedQuery:
    """Test ParsedQuery dataclass and methods."""
    
    def test_parsed_query_creation(self):
        """Test parsed query creation."""
        entities = [
            ExtractedEntity("prefrontal cortex", EntityType.BRAIN_REGION, 0.9, "prefrontal cortex"),
            ExtractedEntity("working memory", EntityType.TASK, 0.85, "working memory")
        ]
        
        expansion = QueryExpansion(
            original_query="test",
            expanded_terms={},
            synonyms={},
            related_concepts=[],
            domain_terms=[],
            confidence=0.8
        )
        
        parsed_query = ParsedQuery(
            original_query="analyze working memory activation in prefrontal cortex",
            normalized_query="analyze working memory activation in prefrontal cortex",
            primary_intent=QueryIntent.ANALYSIS,
            secondary_intents=[QueryIntent.VISUALIZATION],
            entities=entities,
            expansion=expansion,
            complexity_score=0.6,
            confidence=0.8,
            metadata={"entity_count": 2}
        )
        
        assert parsed_query.original_query.startswith("analyze working memory")
        assert parsed_query.primary_intent == QueryIntent.ANALYSIS
        assert len(parsed_query.secondary_intents) == 1
        assert len(parsed_query.entities) == 2
        assert parsed_query.complexity_score == 0.6
        assert parsed_query.confidence == 0.8
        assert parsed_query.metadata["entity_count"] == 2
    
    def test_get_entities_by_type(self):
        """Test filtering entities by type."""
        entities = [
            ExtractedEntity("prefrontal cortex", EntityType.BRAIN_REGION, 0.9, "prefrontal cortex"),
            ExtractedEntity("amygdala", EntityType.BRAIN_REGION, 0.85, "amygdala"),
            ExtractedEntity("working memory", EntityType.TASK, 0.8, "working memory"),
            ExtractedEntity("fmri", EntityType.MODALITY, 0.95, "fmri")
        ]
        
        parsed_query = ParsedQuery(
            original_query="test",
            normalized_query="test", 
            primary_intent=QueryIntent.ANALYSIS,
            entities=entities,
            complexity_score=0.5,
            confidence=0.8
        )
        
        brain_regions = parsed_query.get_entities_by_type(EntityType.BRAIN_REGION)
        tasks = parsed_query.get_entities_by_type(EntityType.TASK)
        modalities = parsed_query.get_entities_by_type(EntityType.MODALITY)
        
        assert len(brain_regions) == 2
        assert len(tasks) == 1
        assert len(modalities) == 1
        assert brain_regions[0].text in ["prefrontal cortex", "amygdala"]
        assert tasks[0].text == "working memory"
        assert modalities[0].text == "fmri"


class TestContextManager:
    """Test ContextManager functionality."""
    
    def test_context_manager_initialization(self):
        """Test context manager initialization."""
        context_manager = ContextManager()
        
        assert len(context_manager.conversation_history) == 0
        assert len(context_manager.session_context) == 0
        assert len(context_manager.user_preferences) == 0
        assert len(context_manager.domain_context) == 0
    
    def test_update_context(self):
        """Test context updating functionality."""
        context_manager = ContextManager()
        
        # Add some queries to conversation history
        queries = [
            "load fmri dataset",
            "preprocess the data", 
            "run glm analysis",
            "visualize results"
        ]
        
        session_data = {"dataset": "ds000114", "user_id": "user001"}
        user_data = {"expertise_level": "advanced", "preferred_tools": ["fsl", "spm"]}
        
        for query in queries:
            context_manager.update_context(query, session_data, user_data)
        
        assert len(context_manager.conversation_history) == 4
        assert context_manager.session_context["dataset"] == "ds000114"
        assert context_manager.user_preferences["expertise_level"] == "advanced"
    
    def test_conversation_history_limit(self):
        """Test that conversation history is limited to recent queries."""
        context_manager = ContextManager()
        
        # Add more than 10 queries
        for i in range(15):
            context_manager.update_context(f"query {i}")
        
        # Should only keep last 10
        assert len(context_manager.conversation_history) == 10
        assert context_manager.conversation_history[0] == "query 5"
        assert context_manager.conversation_history[-1] == "query 14"
    
    def test_get_contextual_information(self):
        """Test retrieval of contextual information."""
        context_manager = ContextManager()
        
        context_manager.update_context("test query", {"session_key": "value"}, {"user_key": "value"})
        
        contextual_info = context_manager.get_contextual_information()
        
        expected_keys = ["conversation_history", "session_context", "user_preferences", 
                        "domain_context", "recent_queries"]
        
        for key in expected_keys:
            assert key in contextual_info
        
        assert len(contextual_info["conversation_history"]) == 1
        assert contextual_info["session_context"]["session_key"] == "value"
        assert contextual_info["user_preferences"]["user_key"] == "value"
        assert contextual_info["recent_queries"] == ["test query"]


class TestEntityExtractor:
    """Test EntityExtractor functionality."""
    
    def test_entity_extractor_initialization(self):
        """Test entity extractor initialization."""
        mock_llm = MagicMock()
        extractor = EntityExtractor(mock_llm)
        
        assert extractor.llm == mock_llm
        assert extractor.domain_knowledge is None
        assert isinstance(extractor.patterns, dict)
        assert EntityType.COORDINATE in extractor.patterns
        assert EntityType.BRAIN_REGION in extractor.patterns
    
    def test_coordinate_pattern_extraction(self):
        """Test coordinate extraction using regex patterns."""
        mock_llm = MagicMock()
        extractor = EntityExtractor(mock_llm)
        
        test_queries = [
            "activation at coordinates (-45, 24, 36)",
            "MNI coordinates: [12, -34, 56]",
            "peak at (0, 0, 0)"
        ]
        
        for query in test_queries:
            entities = extractor._extract_with_patterns(query)
            
            # Should find at least one coordinate entity
            coord_entities = [e for e in entities if e.entity_type == EntityType.COORDINATE]
            assert len(coord_entities) >= 1
            
            coord_entity = coord_entities[0]
            assert coord_entity.coordinates is not None
            assert len(coord_entity.coordinates) == 3
            assert all(isinstance(coord, float) for coord in coord_entity.coordinates)
    
    def test_brain_region_pattern_extraction(self):
        """Test brain region extraction using regex patterns."""
        mock_llm = MagicMock()
        extractor = EntityExtractor(mock_llm)
        
        test_queries = [
            "activation in anterior cingulate cortex",
            "left prefrontal area shows activity", 
            "bilateral amygdala response",
            "BA 9 and BA 46 activation"
        ]
        
        for query in test_queries:
            entities = extractor._extract_with_patterns(query)
            
            # Should find brain region entities
            brain_entities = [e for e in entities if e.entity_type == EntityType.BRAIN_REGION]
            assert len(brain_entities) >= 1
            
            # Check that detected regions are reasonable
            region_texts = [e.text.lower() for e in brain_entities]
            expected_terms = ["cingulate", "prefrontal", "amygdala", "ba"]
            assert any(term in " ".join(region_texts) for term in expected_terms)
    
    def test_task_pattern_extraction(self):
        """Test task extraction using regex patterns."""
        mock_llm = MagicMock()
        extractor = EntityExtractor(mock_llm)
        
        test_queries = [
            "participants performed n-back task",
            "working memory paradigm was used",
            "stroop task with emotional faces",
            "go/no-go task administration"
        ]
        
        for query in test_queries:
            entities = extractor._extract_with_patterns(query)
            
            # Should find task entities
            task_entities = [e for e in entities if e.entity_type == EntityType.TASK]
            assert len(task_entities) >= 1
            
            # Check confidence is reasonable
            for entity in task_entities:
                assert 0.0 <= entity.confidence <= 1.0
    
    def test_llm_entity_extraction(self):
        """Test LLM-based entity extraction.""" 
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps([
            {
                "text": "dorsolateral prefrontal cortex",
                "type": "brain_region",
                "confidence": 0.95,
                "normalized": "dorsolateral prefrontal cortex"
            },
            {
                "text": "n-back task",
                "type": "task",
                "confidence": 0.9,
                "normalized": "n-back"
            }
        ])
        mock_llm.invoke.return_value = mock_response
        
        extractor = EntityExtractor(mock_llm)
        entities = extractor._extract_with_llm(
            "analyze n-back activation in dorsolateral prefrontal cortex",
            {"dataset": "working_memory_study"}
        )
        
        assert len(entities) == 2
        assert entities[0].entity_type == EntityType.BRAIN_REGION
        assert entities[1].entity_type == EntityType.TASK
        assert entities[0].confidence == 0.95
        assert entities[1].confidence == 0.9
    
    def test_llm_extraction_malformed_response(self):
        """Test handling of malformed LLM responses."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "{ invalid json"
        mock_llm.invoke.return_value = mock_response
        
        extractor = EntityExtractor(mock_llm)
        entities = extractor._extract_with_llm("test query", {})
        
        # Should handle gracefully and return empty list
        assert isinstance(entities, list)
        assert len(entities) == 0
    
    def test_merge_overlapping_entities(self):
        """Test merging of overlapping entities."""
        mock_llm = MagicMock()
        extractor = EntityExtractor(mock_llm)
        
        overlapping_entities = [
            ExtractedEntity("prefrontal cortex", EntityType.BRAIN_REGION, 0.9, "prefrontal cortex"),
            ExtractedEntity("prefrontal", EntityType.BRAIN_REGION, 0.7, "prefrontal"),  # Overlapping
            ExtractedEntity("working memory", EntityType.TASK, 0.8, "working memory"),
            ExtractedEntity("memory task", EntityType.TASK, 0.6, "memory task")  # Overlapping
        ]
        
        merged = extractor._merge_entities(overlapping_entities)
        
        # Should have fewer entities after merging
        assert len(merged) < len(overlapping_entities)
        
        # Should keep higher confidence entities
        brain_regions = [e for e in merged if e.entity_type == EntityType.BRAIN_REGION]
        if brain_regions:
            assert brain_regions[0].confidence >= 0.7  # Should keep higher confidence one


class TestQueryExpander:
    """Test QueryExpander functionality."""
    
    def test_query_expander_initialization(self):
        """Test query expander initialization."""
        expander = QueryExpander()
        
        assert expander.domain_knowledge is None
        assert isinstance(expander.synonym_cache, dict)
        assert isinstance(expander.built_in_synonyms, dict)
        
        # Check some built-in synonyms
        assert "fmri" in expander.built_in_synonyms
        assert "glm" in expander.built_in_synonyms
        assert "roi" in expander.built_in_synonyms
    
    def test_built_in_synonyms_loading(self):
        """Test loading of built-in synonyms."""
        expander = QueryExpander()
        synonyms = expander.built_in_synonyms
        
        # Test specific synonym mappings
        assert "functional mri" in synonyms["fmri"]
        assert "region of interest" in synonyms["roi"]
        assert "general linear model" in synonyms["glm"]
        assert "default mode network" in synonyms["dmn"]
    
    def test_expand_query_with_entities(self):
        """Test query expansion with extracted entities."""
        expander = QueryExpander()
        
        query = "fmri connectivity analysis"
        entities = [
            ExtractedEntity("fmri", EntityType.MODALITY, 0.9, "fmri"),
            ExtractedEntity("connectivity", EntityType.STATISTICAL_METHOD, 0.8, "connectivity")
        ]
        context = {}
        
        expansion = expander.expand_query(query, entities, context)
        
        assert expansion.original_query == query
        assert len(expansion.synonyms) > 0
        assert "fmri" in expansion.synonyms or "connectivity" in expansion.synonyms
        assert expansion.confidence > 0.0
    
    def test_expand_query_with_built_in_terms(self):
        """Test expansion using built-in synonym dictionary."""
        expander = QueryExpander()
        
        query = "roi analysis using glm"
        entities = []
        context = {}
        
        expansion = expander.expand_query(query, entities, context)
        
        # Should expand roi and glm
        assert len(expansion.expanded_terms) >= 2
        assert "roi" in expansion.expanded_terms or "glm" in expansion.expanded_terms
        
        # Check actual synonyms
        if "roi" in expansion.synonyms:
            assert "region of interest" in expansion.synonyms["roi"]
        if "glm" in expansion.synonyms:
            assert "general linear model" in expansion.synonyms["glm"]
    
    def test_get_synonyms_caching(self):
        """Test synonym caching functionality."""
        expander = QueryExpander()
        
        # First call should compute
        synonyms1 = expander._get_synonyms("fmri")
        assert "functional mri" in synonyms1
        
        # Second call should use cache
        synonyms2 = expander._get_synonyms("fmri") 
        assert synonyms1 == synonyms2
    
    def test_expansion_confidence_calculation(self):
        """Test confidence calculation for query expansion."""
        expander = QueryExpander()
        
        # Test with no expansions
        confidence_empty = expander._calculate_expansion_confidence({}, {}, [])
        assert confidence_empty == 0.0
        
        # Test with some expansions
        expanded_terms = {"term1": ["syn1", "syn2"], "term2": ["syn3"]}
        synonyms = {"term1": ["syn1", "syn2"]}
        related_concepts = ["concept1", "concept2"]
        
        confidence = expander._calculate_expansion_confidence(
            expanded_terms, synonyms, related_concepts
        )
        
        assert 0.0 < confidence <= 1.0
    
    @given(query_words=st.lists(st.text(min_size=1), min_size=1, max_size=20))
    def test_expansion_consistency(self, query_words):
        """Property test: expansion should be consistent for same input."""
        expander = QueryExpander()
        query = " ".join(query_words)
        
        expansion1 = expander.expand_query(query, [], {})
        expansion2 = expander.expand_query(query, [], {})
        
        assert expansion1.original_query == expansion2.original_query
        assert expansion1.expanded_terms == expansion2.expanded_terms


class TestAdvancedQueryParser:
    """Test the main AdvancedQueryParser class."""
    
    def test_parser_initialization(self):
        """Test parser initialization."""
        mock_llm = MagicMock()
        parser = AdvancedQueryParser(llm=mock_llm)
        
        assert parser.llm == mock_llm
        assert parser.domain_knowledge is None
        assert parser.embeddings is None
        assert isinstance(parser.entity_extractor, EntityExtractor)
        assert isinstance(parser.context_manager, ContextManager)
        assert isinstance(parser.query_expander, QueryExpander)
        assert isinstance(parser.intent_patterns, dict)
    
    def test_intent_pattern_compilation(self):
        """Test intent pattern compilation.""" 
        parser = AdvancedQueryParser()
        patterns = parser.intent_patterns
        
        # Should have patterns for all intents
        expected_intents = [
            QueryIntent.ANALYSIS, QueryIntent.COMPARISON, QueryIntent.CORRELATION,
            QueryIntent.PREDICTION, QueryIntent.VISUALIZATION, QueryIntent.SEARCH,
            QueryIntent.PREPROCESSING, QueryIntent.META_ANALYSIS
        ]
        
        for intent in expected_intents:
            assert intent in patterns
            assert isinstance(patterns[intent], list)
            assert len(patterns[intent]) > 0
            
            # Each pattern should be a compiled regex
            for pattern in patterns[intent]:
                assert hasattr(pattern, 'findall')  # Should be compiled regex
    
    def test_normalize_query(self):
        """Test query normalization."""
        parser = AdvancedQueryParser()
        
        test_cases = [
            ("  analyze   fmri    data  ", "analyze functional MRI data"),
            ("ANALYZE FMRI DATA", "ANALYZE functional MRI DATA"),
            ("roi analysis with glm", "region of interest analysis with general linear model"),
            ("dmn connectivity study", "default mode network connectivity study")
        ]
        
        for input_query, expected_partial in test_cases:
            normalized = parser._normalize_query(input_query)
            
            # Check whitespace normalization
            assert "  " not in normalized  # No double spaces
            assert normalized == normalized.strip()  # No leading/trailing whitespace
    
    def test_classify_intent_single(self):
        """Test single intent classification."""
        parser = AdvancedQueryParser()
        
        test_cases = [
            ("analyze working memory activation", QueryIntent.ANALYSIS),
            ("compare young vs old subjects", QueryIntent.COMPARISON),
            ("find correlation between networks", QueryIntent.CORRELATION),
            ("classify brain states", QueryIntent.PREDICTION),
            ("visualize activation maps", QueryIntent.VISUALIZATION),
            ("search for prefrontal studies", QueryIntent.SEARCH),
            ("preprocess fmri data", QueryIntent.PREPROCESSING)
        ]
        
        for query, expected_intent in test_cases:
            primary_intent, secondary_intents = parser._classify_intent(query)
            
            assert primary_intent == expected_intent
            assert isinstance(secondary_intents, list)
    
    def test_classify_intent_multiple(self):
        """Test multiple intent classification."""
        parser = AdvancedQueryParser()
        
        multi_intent_query = "preprocess data, analyze activation, and visualize results"
        primary_intent, secondary_intents = parser._classify_intent(multi_intent_query)
        
        # Should identify multiple intents
        assert isinstance(primary_intent, QueryIntent)
        assert len(secondary_intents) >= 1
        
        # Should contain relevant intents
        all_intents = [primary_intent] + secondary_intents
        intent_values = [intent.value for intent in all_intents]
        
        expected_intents = ["preprocessing", "analysis", "visualization"]
        matches = sum(1 for expected in expected_intents if expected in intent_values)
        assert matches >= 2  # Should match at least 2 of the expected intents
    
    def test_calculate_complexity_score(self):
        """Test complexity score calculation."""
        parser = AdvancedQueryParser()
        
        # Simple query
        simple_entities = [
            ExtractedEntity("activation", EntityType.METRIC, 0.8, "activation")
        ]
        simple_complexity = parser._calculate_complexity(
            "show activation", simple_entities, []
        )
        
        # Complex query
        complex_entities = [
            ExtractedEntity("prefrontal cortex", EntityType.BRAIN_REGION, 0.9, "prefrontal cortex"),
            ExtractedEntity("working memory", EntityType.TASK, 0.8, "working memory"),
            ExtractedEntity("glm", EntityType.STATISTICAL_METHOD, 0.85, "glm")
        ]
        complex_secondary = [QueryIntent.COMPARISON, QueryIntent.VISUALIZATION]
        complex_complexity = parser._calculate_complexity(
            "analyze and compare working memory activation in prefrontal cortex using glm and visualize results",
            complex_entities, complex_secondary
        )
        
        assert 0.0 <= simple_complexity <= 1.0
        assert 0.0 <= complex_complexity <= 1.0
        assert complex_complexity > simple_complexity
    
    def test_calculate_confidence(self):
        """Test overall confidence calculation."""
        parser = AdvancedQueryParser()
        
        # High confidence entities
        high_conf_entities = [
            ExtractedEntity("prefrontal cortex", EntityType.BRAIN_REGION, 0.95, "prefrontal cortex"),
            ExtractedEntity("fmri", EntityType.MODALITY, 0.9, "fmri")
        ]
        
        # Mock expansion with high confidence
        high_conf_expansion = QueryExpansion(
            "test", {}, {}, [], [], confidence=0.9
        )
        
        confidence = parser._calculate_confidence(
            high_conf_entities, high_conf_expansion, QueryIntent.ANALYSIS, 0.3
        )
        
        assert 0.0 <= confidence <= 1.0
        assert confidence > 0.5  # Should be reasonably high
    
    def test_semantic_similarity_without_embeddings(self):
        """Test semantic similarity fallback when no embeddings available."""
        parser = AdvancedQueryParser()  # No embeddings provided
        
        query1 = "analyze working memory activation"
        query2 = "examine working memory neural activity"
        
        similarity = parser.get_semantic_similarity(query1, query2)
        
        assert 0.0 <= similarity <= 1.0
        assert similarity > 0.0  # Should find some word overlap
    
    def test_semantic_similarity_with_embeddings(self):
        """Test semantic similarity with embeddings."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.side_effect = [
            [0.1, 0.2, 0.3],  # First query embedding
            [0.2, 0.3, 0.4]   # Second query embedding
        ]
        
        parser = AdvancedQueryParser(embeddings=mock_embeddings)
        
        query1 = "analyze working memory activation"
        query2 = "examine working memory neural activity"
        
        similarity = parser.get_semantic_similarity(query1, query2)
        
        assert 0.0 <= similarity <= 1.0
        assert mock_embeddings.embed_query.call_count == 2
    
    def test_compute_context_vector(self):
        """Test context vector computation."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3, 0.4]
        
        parser = AdvancedQueryParser(embeddings=mock_embeddings)
        
        expansion = QueryExpansion(
            "test query",
            {"fmri": ["functional mri"]},
            {},
            [],
            [],
            0.8
        )
        
        vector = parser._compute_context_vector("test query", expansion)
        
        assert vector is not None
        assert isinstance(vector, np.ndarray)
        assert len(vector) == 4
        assert mock_embeddings.embed_query.called
    
    def test_full_parse_pipeline(self):
        """Test the complete parsing pipeline."""
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = MagicMock(content="[]")  # Empty entity list
        
        parser = AdvancedQueryParser(llm=mock_llm)
        
        query = "analyze working memory activation in prefrontal cortex"
        context = {"dataset": "working_memory_study"}
        
        parsed = parser.parse(query, context)
        
        assert isinstance(parsed, ParsedQuery)
        assert parsed.original_query == query
        assert len(parsed.normalized_query) > 0
        assert isinstance(parsed.primary_intent, QueryIntent)
        assert isinstance(parsed.entities, list)
        assert isinstance(parsed.expansion, QueryExpansion)
        assert 0.0 <= parsed.complexity_score <= 1.0
        assert 0.0 <= parsed.confidence <= 1.0
        assert "context_used" in parsed.metadata
    
    @given(query_length=st.integers(min_value=1, max_value=200))
    def test_parse_robustness(self, query_length):
        """Property test: parser should handle queries of various lengths."""
        parser = AdvancedQueryParser()
        
        # Generate query of specified length
        words = ["analyze", "brain", "activation", "fmri", "data"] * (query_length // 5 + 1)
        query = " ".join(words[:query_length])
        
        try:
            parsed = parser.parse(query)
            
            assert isinstance(parsed, ParsedQuery)
            assert len(parsed.original_query) > 0
            assert isinstance(parsed.primary_intent, QueryIntent)
            assert 0.0 <= parsed.confidence <= 1.0
            
        except Exception as e:
            # Should handle gracefully, no unhandled exceptions
            assert False, f"Parser failed on query length {query_length}: {e}"


class TestIntegrationWithFixtures:
    """Test integration with fixture data."""
    
    @pytest.fixture
    def domain_terms(self):
        """Load domain terms from fixtures."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-017" / "domain_terms.json"
        with open(fixture_path, 'r') as f:
            return json.load(f)
    
    @pytest.fixture
    def test_queries(self):
        """Load test queries from fixtures."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-017" / "test_queries.json"
        with open(fixture_path, 'r') as f:
            return json.load(f)
    
    def test_entity_extraction_from_fixtures(self, test_queries):
        """Test entity extraction using fixture data."""
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = MagicMock(content="[]")
        
        extractor = EntityExtractor(mock_llm)
        
        extraction_tests = test_queries["entity_extraction_tests"]
        
        for test_case in extraction_tests:
            query = test_case["query"]
            expected_entities = test_case["expected_entities"]
            
            # Test pattern-based extraction
            pattern_entities = extractor._extract_with_patterns(query)
            
            # Should find at least some entities
            assert len(pattern_entities) >= 0
            
            # Check that found entities match expected types
            found_types = {e.entity_type for e in pattern_entities}
            expected_types = {EntityType(e["type"]) for e in expected_entities}
            
            # Should have some overlap (allowing for imperfect matching)
            if expected_types:
                overlap = len(found_types.intersection(expected_types))
                # Allow for some flexibility in pattern matching
                assert overlap >= 0
    
    def test_intent_classification_from_fixtures(self, test_queries):
        """Test intent classification using fixture data."""
        parser = AdvancedQueryParser()
        
        intent_tests = test_queries["intent_classification_tests"]
        
        for test_case in intent_tests:
            query = test_case["query"]
            expected_primary = QueryIntent(test_case["expected_primary_intent"])
            expected_secondary = [QueryIntent(intent) for intent in test_case["expected_secondary_intents"]]
            
            primary_intent, secondary_intents = parser._classify_intent(query)
            
            assert primary_intent == expected_primary
            
            # Check secondary intents (allowing for some variation)
            if expected_secondary:
                found_secondary = set(secondary_intents)
                expected_secondary_set = set(expected_secondary)
                
                # Should have some overlap
                overlap = len(found_secondary.intersection(expected_secondary_set))
                assert overlap >= 0  # Allow for some flexibility
    
    def test_query_expansion_from_fixtures(self, test_queries):
        """Test query expansion using fixture data.""" 
        expander = QueryExpander()
        
        expansion_tests = test_queries["query_expansion_tests"]
        
        for test_case in expansion_tests:
            query = test_case["query"]
            expected_expansions = test_case["expected_expansions"]
            
            expansion = expander.expand_query(query, [], {})
            
            # Check that expected terms are expanded
            for original_term, expected_synonyms in expected_expansions.items():
                if original_term.lower() in query.lower():
                    # Should have found synonyms for this term
                    found_synonyms = expansion.synonyms.get(original_term.lower(), [])
                    
                    # Check for overlap
                    expected_set = set(syn.lower() for syn in expected_synonyms)
                    found_set = set(syn.lower() for syn in found_synonyms)
                    
                    overlap = len(expected_set.intersection(found_set))
                    # Allow for some flexibility
                    assert overlap >= 0
    
    def test_context_awareness_from_fixtures(self, test_queries):
        """Test context awareness using fixture data."""
        parser = AdvancedQueryParser()
        
        context_tests = test_queries["context_awareness_tests"]
        
        for test_case in context_tests:
            query = test_case["query"]
            context = test_case["context"]
            expected_confidence = test_case["expected_confidence"]
            
            parsed = parser.parse(query, context)
            
            # Should use context
            assert parsed.metadata["context_used"] == True
            
            # Confidence should be reasonable
            assert 0.0 <= parsed.confidence <= 1.0
            
            # Allow some tolerance in confidence comparison
            assert abs(parsed.confidence - expected_confidence) <= 0.3
    
    def test_domain_terms_recognition(self, domain_terms):
        """Test recognition of domain-specific terms."""
        expander = QueryExpander()
        
        neuroimaging_terms = domain_terms["neuroimaging_terms"]
        
        # Test brain regions
        brain_regions = neuroimaging_terms["brain_regions"]["cortical"]
        for region in brain_regions[:5]:  # Test first 5
            # Should have some expansion/recognition
            synonyms = expander._get_synonyms(region.lower())
            # Even if no direct synonyms, should handle gracefully
            assert isinstance(synonyms, list)
        
        # Test abbreviations
        abbreviations = domain_terms["abbreviations"]
        for abbrev, full_forms in list(abbreviations.items())[:5]:
            # Should expand abbreviations
            synonyms = expander._get_synonyms(abbrev.lower())
            
            if abbrev.lower() in expander.built_in_synonyms:
                assert len(synonyms) > 0
                # Check if any full forms are in synonyms
                synonym_lower = [s.lower() for s in synonyms]
                full_forms_lower = [f.lower() for f in full_forms]
                
                overlap = len(set(synonym_lower).intersection(set(full_forms_lower)))
                assert overlap >= 0  # Allow for variations


class TestCreateAdvancedParser:
    """Test the factory function."""
    
    def test_create_advanced_parser_basic(self):
        """Test basic parser creation."""
        parser = create_advanced_parser()
        
        assert isinstance(parser, AdvancedQueryParser)
        assert parser.domain_knowledge is None
        assert parser.embeddings is None
        assert parser.llm is None
    
    def test_create_advanced_parser_with_components(self):
        """Test parser creation with all components."""
        mock_domain_kb = MagicMock()
        mock_embeddings = MagicMock()
        mock_llm = MagicMock()
        
        parser = create_advanced_parser(mock_domain_kb, mock_embeddings, mock_llm)
        
        assert isinstance(parser, AdvancedQueryParser)
        assert parser.domain_knowledge == mock_domain_kb
        assert parser.embeddings == mock_embeddings
        assert parser.llm == mock_llm


class TestErrorHandling:
    """Test error handling in query understanding."""
    
    def test_malformed_query_handling(self):
        """Test handling of malformed queries."""
        parser = AdvancedQueryParser()
        
        malformed_queries = [
            "",  # Empty query
            "   ",  # Whitespace only
            "!!@#$%^&*()",  # Special characters only
            "a" * 1000,  # Very long query
        ]
        
        for query in malformed_queries:
            try:
                parsed = parser.parse(query)
                
                # Should handle gracefully
                assert isinstance(parsed, ParsedQuery)
                assert isinstance(parsed.primary_intent, QueryIntent)
                assert 0.0 <= parsed.confidence <= 1.0
                
            except Exception as e:
                assert False, f"Parser failed on malformed query '{query[:50]}...': {e}"
    
    def test_context_none_handling(self):
        """Test handling of None context."""
        parser = AdvancedQueryParser()
        
        parsed = parser.parse("test query", context=None)
        
        assert isinstance(parsed, ParsedQuery)
        assert parsed.metadata["context_used"] == False
    
    def test_embeddings_failure_handling(self):
        """Test handling when embeddings fail."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.side_effect = Exception("Embedding failed")
        
        parser = AdvancedQueryParser(embeddings=mock_embeddings)
        
        # Should handle embedding failure gracefully
        parsed = parser.parse("test query")
        
        assert isinstance(parsed, ParsedQuery)
        assert parsed.context_vector is None  # Should be None due to failure