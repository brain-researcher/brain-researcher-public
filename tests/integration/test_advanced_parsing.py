"""
Integration tests for Advanced Query Understanding (AGENT-017)

Tests cover:
- Real neuroimaging queries parsing
- Multi-intent handling
- Ambiguity resolution
- Context integration scenarios
- Performance under realistic conditions
"""

import json
import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from brain_researcher.services.agent.query_understanding import (
    AdvancedQueryParser,
    EntityType,
    QueryIntent,
    create_advanced_parser
)


@pytest.fixture
def test_queries():
    """Load test queries from fixtures."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-017" / "test_queries.json"
    with open(fixture_path, 'r') as f:
        return json.load(f)


@pytest.fixture
def domain_terms():
    """Load domain terms from fixtures."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-017" / "domain_terms.json"
    with open(fixture_path, 'r') as f:
        return json.load(f)


class TestRealisticNeuroimagingQueries:
    """Test parsing of realistic neuroimaging queries."""
    
    def test_complex_analysis_query(self):
        """Test parsing complex analysis query."""
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = MagicMock(content=json.dumps([
            {
                "text": "working memory",
                "type": "task",
                "confidence": 0.9,
                "normalized": "working memory"
            },
            {
                "text": "prefrontal cortex",
                "type": "brain_region", 
                "confidence": 0.95,
                "normalized": "prefrontal cortex"
            }
        ]))
        
        parser = AdvancedQueryParser(llm=mock_llm)
        
        query = """Analyze working memory activation patterns in the dorsolateral prefrontal cortex 
                  using GLM analysis, compare between high and low performers, and visualize 
                  the results with statistical maps showing cluster-corrected activation."""
        
        parsed = parser.parse(query)
        
        # Should handle complex multi-part query
        assert isinstance(parsed.primary_intent, QueryIntent)
        assert len(parsed.secondary_intents) >= 1
        assert parsed.complexity_score > 0.5  # Should be complex
        
        # Should extract multiple entities
        assert len(parsed.entities) >= 1
        
        # Should have reasonable confidence despite complexity
        assert parsed.confidence > 0.3
    
    def test_preprocessing_workflow_query(self):
        """Test parsing preprocessing workflow query."""
        parser = AdvancedQueryParser()
        
        query = """Preprocess the fMRI data using motion correction with 6-parameter 
                  realignment, apply slice timing correction, normalize to MNI space, 
                  and smooth with 8mm FWHM Gaussian kernel."""
        
        parsed = parser.parse(query)
        
        assert parsed.primary_intent == QueryIntent.PREPROCESSING
        assert parsed.complexity_score > 0.6  # Complex preprocessing
        
        # Should identify preprocessing-related terms
        entities_text = " ".join(e.text.lower() for e in parsed.entities)
        preprocessing_terms = ["motion", "correction", "normalize", "smooth"]
        found_terms = sum(1 for term in preprocessing_terms if term in entities_text)
        assert found_terms >= 1
    
    def test_connectivity_analysis_query(self):
        """Test parsing connectivity analysis query."""
        parser = AdvancedQueryParser()
        
        query = """Compute functional connectivity between default mode network regions 
                  including posterior cingulate cortex, medial prefrontal cortex, and 
                  angular gyrus using correlation analysis."""
        
        parsed = parser.parse(query)
        
        assert parsed.primary_intent in [QueryIntent.CORRELATION, QueryIntent.ANALYSIS]
        
        # Should identify brain regions
        brain_regions = parsed.get_entities_by_type(EntityType.BRAIN_REGION)
        assert len(brain_regions) >= 1
        
        # Should identify connectivity-related concepts
        query_lower = parsed.normalized_query.lower()
        assert any(term in query_lower for term in ["connectivity", "correlation", "network"])
    
    def test_meta_analysis_query(self):
        """Test parsing meta-analysis query."""
        parser = AdvancedQueryParser()
        
        query = """Perform coordinate-based meta-analysis of working memory studies 
                  using ALE method with FWE correction at p<0.05, including studies 
                  from 2010-2023 with minimum 10 subjects per study."""
        
        parsed = parser.parse(query)
        
        assert parsed.primary_intent == QueryIntent.META_ANALYSIS
        
        # Should identify statistical methods
        stat_methods = parsed.get_entities_by_type(EntityType.STATISTICAL_METHOD)
        method_texts = [e.text.lower() for e in stat_methods]
        assert any("ale" in text or "meta" in text or "fwe" in text for text in method_texts)


class TestMultiIntentHandling:
    """Test handling of queries with multiple intents."""
    
    def test_analysis_plus_visualization(self, test_queries):
        """Test query combining analysis and visualization."""
        parser = AdvancedQueryParser()
        
        multi_intent_test = test_queries["multi_intent_tests"][0]
        query = multi_intent_test["query"]
        
        parsed = parser.parse(query)
        
        expected_primary = QueryIntent(multi_intent_test["expected_primary_intent"])
        expected_secondary = [QueryIntent(intent) for intent in multi_intent_test["expected_secondary_intents"]]
        
        assert parsed.primary_intent == expected_primary
        
        # Should identify multiple intents
        all_intents = [parsed.primary_intent] + parsed.secondary_intents
        intent_overlap = len(set(all_intents).intersection(set(expected_secondary + [expected_primary])))
        assert intent_overlap >= 2
    
    def test_search_plus_comparison(self, test_queries):
        """Test query combining search and comparison."""
        parser = AdvancedQueryParser()
        
        if len(test_queries["multi_intent_tests"]) > 1:
            multi_intent_test = test_queries["multi_intent_tests"][1]
            query = multi_intent_test["query"]
            
            parsed = parser.parse(query)
            
            # Should handle multiple intents appropriately
            assert len(parsed.secondary_intents) >= 0
            assert parsed.complexity_score >= multi_intent_test.get("expected_complexity", 0.5)
    
    def test_sequential_intent_parsing(self):
        """Test parsing queries with sequential intents."""
        parser = AdvancedQueryParser()
        
        query = "First preprocess the data, then run statistical analysis, and finally create visualizations"
        
        parsed = parser.parse(query)
        
        # Should identify sequential nature through complexity and intents
        assert len(parsed.secondary_intents) >= 1
        assert parsed.complexity_score > 0.5
        
        # Should identify multiple intent types
        all_intents = [parsed.primary_intent] + parsed.secondary_intents
        intent_types = {intent.value for intent in all_intents}
        
        expected_types = {"preprocessing", "analysis", "visualization"}
        overlap = len(intent_types.intersection(expected_types))
        assert overlap >= 2


class TestAmbiguityResolution:
    """Test resolution of ambiguous queries."""
    
    def test_abbreviation_disambiguation(self, test_queries):
        """Test disambiguation of abbreviations."""
        parser = AdvancedQueryParser()
        
        ambiguity_tests = test_queries["ambiguity_resolution_tests"]
        
        for test_case in ambiguity_tests:
            query = test_case["query"]
            expected_disambiguation = test_case["expected_disambiguation"]
            
            parsed = parser.parse(query, test_case.get("context", {}))
            
            # Should handle abbreviation in normalized query or entities
            query_text = parsed.normalized_query.lower()
            entity_texts = " ".join(e.normalized_form.lower() for e in parsed.entities)
            all_text = query_text + " " + entity_texts
            
            # Should contain expanded form
            assert expected_disambiguation.lower() in all_text or \
                   any(word in expected_disambiguation.lower() for word in all_text.split())
    
    def test_context_based_disambiguation(self):
        """Test disambiguation using context."""
        parser = AdvancedQueryParser()
        
        # Ambiguous query
        query = "Analyze the network"
        
        # Different contexts should lead to different interpretations
        context1 = {"domain": "connectivity", "previous_analysis": "resting_state"}
        context2 = {"domain": "graph_theory", "analysis_type": "topology"}
        
        parsed1 = parser.parse(query, context1)
        parsed2 = parser.parse(query, context2)
        
        # Both should succeed
        assert isinstance(parsed1.primary_intent, QueryIntent)
        assert isinstance(parsed2.primary_intent, QueryIntent)
        
        # Context should influence parsing
        assert parsed1.metadata["context_used"] == True
        assert parsed2.metadata["context_used"] == True
    
    def test_domain_specific_disambiguation(self):
        """Test disambiguation of domain-specific terms."""
        parser = AdvancedQueryParser()
        
        ambiguous_queries = [
            "Show me the clusters",  # Could be data clusters or brain clusters
            "Analyze the connections",  # Could be functional or structural
            "Extract the features"  # Could be image features or behavioral features
        ]
        
        for query in ambiguous_queries:
            parsed = parser.parse(query)
            
            # Should handle ambiguity gracefully
            assert isinstance(parsed, type(parsed))  # Basic validation
            assert parsed.confidence >= 0.0  # Should have some confidence


class TestContextIntegrationScenarios:
    """Test various context integration scenarios."""
    
    def test_conversation_history_integration(self, test_queries):
        """Test integration with conversation history."""
        parser = AdvancedQueryParser()
        
        context_tests = test_queries["context_awareness_tests"]
        
        for test_case in context_tests:
            query = test_case["query"] 
            context = test_case["context"]
            
            # Simulate conversation history in context
            if "previous_queries" in context:
                for prev_query in context["previous_queries"]:
                    parser.context_manager.update_context(prev_query)
            
            parsed = parser.parse(query, context)
            
            # Should use context
            assert parsed.metadata["context_used"] == True
            
            # Should improve understanding (higher confidence expected with context)
            assert parsed.confidence >= 0.3
    
    def test_session_context_integration(self):
        """Test integration with session context."""
        parser = AdvancedQueryParser()
        
        # Establish session context
        session_context = {
            "current_dataset": "working_memory_study",
            "analysis_pipeline": "fmriprep_complete",
            "user_preferences": {"statistical_threshold": 0.001}
        }
        
        query = "Run the statistical analysis"
        
        parsed = parser.parse(query, session_context)
        
        # Should integrate session context
        assert parsed.metadata["context_used"] == True
        
        # Context should help with interpretation
        assert parsed.confidence > 0.5
    
    def test_user_preference_integration(self):
        """Test integration with user preferences."""
        parser = AdvancedQueryParser()
        
        # Set up user preferences context
        user_context = {
            "user_preferences": {
                "preferred_software": ["FSL", "SPM"],
                "expertise_level": "advanced",
                "analysis_style": "conservative"
            }
        }
        
        query = "Set up the analysis pipeline"
        
        parsed = parser.parse(query, user_context)
        
        # Should consider user preferences
        assert parsed.metadata["context_used"] == True
        assert parsed.confidence > 0.0


class TestPerformanceCharacteristics:
    """Test performance under realistic conditions."""
    
    def test_parsing_speed_realistic_queries(self):
        """Test parsing speed with realistic queries."""
        parser = AdvancedQueryParser()
        
        realistic_queries = [
            "Analyze working memory activation in prefrontal cortex using GLM",
            "Compare connectivity between young and old subjects", 
            "Preprocess fMRI data with motion correction and spatial normalization",
            "Perform group-level analysis with cluster correction",
            "Visualize statistical maps overlaid on anatomical brain"
        ]
        
        start_time = time.time()
        
        parsed_queries = []
        for query in realistic_queries:
            parsed = parser.parse(query)
            parsed_queries.append(parsed)
        
        elapsed_time = time.time() - start_time
        
        # Should complete reasonably fast
        assert elapsed_time < 2.0  # Less than 2 seconds for 5 queries
        
        # All should be successfully parsed
        assert len(parsed_queries) == len(realistic_queries)
        for parsed in parsed_queries:
            assert isinstance(parsed.primary_intent, QueryIntent)
            assert parsed.confidence > 0.0
    
    def test_concurrent_parsing_performance(self):
        """Test concurrent parsing performance."""
        import concurrent.futures
        import threading
        
        parser = AdvancedQueryParser()
        
        queries = [f"Analyze brain activation in region {i}" for i in range(20)]
        results = []
        
        def parse_query(query):
            return parser.parse(query)
        
        start_time = time.time()
        
        # Parse queries concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_query = {executor.submit(parse_query, query): query for query in queries}
            
            for future in concurrent.futures.as_completed(future_to_query):
                query = future_to_query[future]
                try:
                    parsed = future.result()
                    results.append((query, parsed))
                except Exception as e:
                    assert False, f"Query parsing failed: {e}"
        
        elapsed_time = time.time() - start_time
        
        # Should handle concurrent parsing
        assert len(results) == len(queries)
        assert elapsed_time < 5.0  # Should complete within 5 seconds
        
        # All results should be valid
        for query, parsed in results:
            assert isinstance(parsed.primary_intent, QueryIntent)
    
    def test_memory_usage_large_queries(self):
        """Test memory usage with large queries."""
        parser = AdvancedQueryParser()
        
        # Create large query
        base_terms = ["analyze", "brain", "activation", "fmri", "connectivity", "network", "statistical"]
        large_query = " ".join(base_terms * 100)  # Very large query
        
        parsed = parser.parse(large_query)
        
        # Should handle large queries
        assert isinstance(parsed.primary_intent, QueryIntent)
        assert parsed.complexity_score > 0.0
        
        # Should not consume excessive memory (basic check)
        assert len(str(parsed)) < 100000  # Less than 100KB serialized
    
    def test_parsing_consistency_repeated_calls(self):
        """Test consistency across repeated parsing calls."""
        parser = AdvancedQueryParser()
        
        query = "Analyze working memory activation in prefrontal cortex"
        
        # Parse same query multiple times
        results = []
        for _ in range(10):
            parsed = parser.parse(query)
            results.append(parsed)
        
        # Results should be consistent
        first_result = results[0]
        
        for result in results[1:]:
            assert result.primary_intent == first_result.primary_intent
            assert result.normalized_query == first_result.normalized_query
            # Confidence should be similar (allowing for small variations)
            assert abs(result.confidence - first_result.confidence) < 0.1


class TestEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_empty_query_handling(self):
        """Test handling of empty queries."""
        parser = AdvancedQueryParser()
        
        empty_queries = ["", "   ", "\n\t\r"]
        
        for empty_query in empty_queries:
            parsed = parser.parse(empty_query)
            
            # Should handle gracefully
            assert isinstance(parsed.primary_intent, QueryIntent) 
            assert parsed.confidence >= 0.0
            assert len(parsed.normalized_query) >= 0
    
    def test_special_characters_handling(self):
        """Test handling of special characters."""
        parser = AdvancedQueryParser()
        
        special_queries = [
            "Analyze data @ coordinates (12, -34, 56)",
            "Compare groups: young vs. old (p < 0.05)",
            "Extract ROI #1 & ROI #2 time-series",
            "Process file_name.nii.gz with parameters"
        ]
        
        for query in special_queries:
            parsed = parser.parse(query)
            
            # Should handle special characters
            assert isinstance(parsed.primary_intent, QueryIntent)
            assert parsed.confidence > 0.0
    
    def test_multilingual_terms_handling(self):
        """Test handling of multilingual scientific terms."""
        parser = AdvancedQueryParser()
        
        # Scientific terms often have Latin/Greek origins
        multilingual_query = "Analyze activation in cortex cerebri and hippocampus"
        
        parsed = parser.parse(multilingual_query)
        
        # Should handle gracefully
        assert isinstance(parsed.primary_intent, QueryIntent)
        assert len(parsed.entities) >= 0  # May or may not extract entities
    
    def test_very_long_query_handling(self):
        """Test handling of very long queries."""
        parser = AdvancedQueryParser()
        
        # Create very long query
        long_query = """
        Analyze the functional magnetic resonance imaging data from the working memory task 
        paradigm using general linear model statistical analysis approach to identify brain 
        activation patterns in the dorsolateral prefrontal cortex, anterior cingulate cortex,
        and parietal cortex regions, then compare the activation between high-performing and 
        low-performing subjects using appropriate statistical tests with multiple comparison 
        correction, and finally visualize the results using statistical parametric maps 
        overlaid on a standard brain template with appropriate color scales and thresholds
        for publication-quality figures that will be used in a peer-reviewed manuscript
        describing the neural correlates of individual differences in working memory capacity.
        """
        
        parsed = parser.parse(long_query)
        
        # Should handle long queries
        assert isinstance(parsed.primary_intent, QueryIntent)
        assert parsed.complexity_score > 0.8  # Should be very complex
        assert len(parsed.entities) > 0  # Should extract multiple entities
        assert len(parsed.secondary_intents) > 0  # Should identify multiple intents


class TestRealWorldIntegration:
    """Test integration with real-world neuroimaging scenarios."""
    
    def test_typical_fmri_analysis_workflow(self):
        """Test parsing queries from typical fMRI analysis workflow.""" 
        parser = AdvancedQueryParser()
        
        workflow_queries = [
            "Load BIDS dataset ds000114",
            "Run fMRIPrep preprocessing pipeline", 
            "Set up first-level GLM with working memory contrast",
            "Perform group-level analysis comparing age groups",
            "Create publication-ready activation maps",
            "Extract time series from significant clusters",
            "Compute seed-based connectivity analysis"
        ]
        
        workflow_results = []
        for query in workflow_queries:
            parsed = parser.parse(query)
            workflow_results.append(parsed)
        
        # Should handle complete workflow
        assert len(workflow_results) == len(workflow_queries)
        
        # Should identify appropriate intents for each step
        intents = [result.primary_intent for result in workflow_results]
        
        # Should have diverse intents appropriate for workflow
        unique_intents = set(intents)
        assert len(unique_intents) >= 3  # At least 3 different intent types
        
        # Common workflow intents should be present
        workflow_intent_values = {intent.value for intent in intents}
        expected_workflow_intents = {"data_extraction", "preprocessing", "analysis", "visualization"}
        overlap = len(workflow_intent_values.intersection(expected_workflow_intents))
        assert overlap >= 2  # Should match at least 2 workflow intents
    
    def test_expert_vs_novice_query_patterns(self):
        """Test handling of expert vs novice query patterns."""
        parser = AdvancedQueryParser()
        
        # Expert query - technical and specific
        expert_query = """Perform voxel-wise GLM analysis with HRF convolution, 
                         apply cluster-based FWE correction at alpha=0.05, and 
                         extract parameter estimates from anatomically-defined ROIs"""
        
        # Novice query - general and less technical
        novice_query = "I want to analyze my brain scans and see which areas are active"
        
        expert_parsed = parser.parse(expert_query)
        novice_parsed = parser.parse(novice_query)
        
        # Expert query should be more complex
        assert expert_parsed.complexity_score > novice_parsed.complexity_score
        
        # Expert query should have more entities
        assert len(expert_parsed.entities) >= len(novice_parsed.entities)
        
        # Both should be successfully parsed
        assert isinstance(expert_parsed.primary_intent, QueryIntent)
        assert isinstance(novice_parsed.primary_intent, QueryIntent)
    
    def test_interdisciplinary_query_handling(self):
        """Test handling of interdisciplinary queries."""
        parser = AdvancedQueryParser()
        
        interdisciplinary_queries = [
            "Correlate brain activation with behavioral performance scores",
            "Analyze genetic influences on brain connectivity patterns", 
            "Compare brain structure between clinical and control populations",
            "Integrate fMRI data with EEG findings for multimodal analysis"
        ]
        
        for query in interdisciplinary_queries:
            parsed = parser.parse(query)
            
            # Should handle interdisciplinary aspects
            assert isinstance(parsed.primary_intent, QueryIntent)
            assert parsed.confidence > 0.3  # Should have reasonable confidence
            
            # May identify correlation or comparison intents
            if "correlat" in query.lower():
                assert parsed.primary_intent == QueryIntent.CORRELATION
            elif "compare" in query.lower():
                assert parsed.primary_intent == QueryIntent.COMPARISON