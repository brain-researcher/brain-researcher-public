"""
Integration tests for Natural Language Generation System

Tests for:
- End-to-end NLG pipeline integration
- Multi-language workflow testing
- Real data explanation quality
- Cross-service NLG integration
- User adaptation over time
- Performance under load
"""

import pytest
import asyncio
from typing import Dict, List, Any
from unittest.mock import Mock, patch, AsyncMock
import json
import tempfile
from pathlib import Path

from brain_researcher.services.agent.nlg_enhancement import (
    EnhancedNLGEngine, ResponseType, AdaptationStrategy, UserProfile, ResponseContext
)
from brain_researcher.services.agent.language_templates import Language, ExplanationLevel
from brain_researcher.services.agent.explanation_generator import ExpertiseLevel


@pytest.mark.integration
class TestNLGSystemIntegration:
    """Integration tests for the complete NLG system"""
    
    @pytest.fixture
    def nlg_engine(self):
        """Create NLG engine for integration testing"""
        return EnhancedNLGEngine()
    
    @pytest.fixture
    def sample_user_profiles(self):
        """Sample user profiles for testing"""
        return {
            "neuroscientist": UserProfile(
                user_id="neuroscientist_001",
                expertise_level=ExpertiseLevel.EXPERT,
                preferred_language=Language.ENGLISH,
                preferred_explanation_level=ExplanationLevel.TECHNICAL,
                detailed_methodology=True,
                include_citations=True,
                statistical_details=True,
                domain_focus=["methods", "statistics", "theory"]
            ),
            "clinician": UserProfile(
                user_id="clinician_001", 
                expertise_level=ExpertiseLevel.INTERMEDIATE,
                preferred_language=Language.ENGLISH,
                preferred_explanation_level=ExplanationLevel.STRUCTURED,
                detailed_methodology=False,
                include_citations=True,
                statistical_details=False,
                domain_focus=["clinical", "implications", "diagnosis"]
            ),
            "student": UserProfile(
                user_id="student_001",
                expertise_level=ExpertiseLevel.BEGINNER,
                preferred_language=Language.ENGLISH,
                preferred_explanation_level=ExplanationLevel.LAYMAN,
                detailed_methodology=False,
                include_citations=False,
                statistical_details=False,
                domain_focus=["basic_concepts"]
            ),
            "spanish_researcher": UserProfile(
                user_id="researcher_es_001",
                expertise_level=ExpertiseLevel.INTERMEDIATE,
                preferred_language=Language.SPANISH,
                preferred_explanation_level=ExplanationLevel.STRUCTURED,
                detailed_methodology=True,
                include_citations=True
            )
        }
    
    @pytest.fixture
    def complex_fmri_results(self):
        """Complex fMRI analysis results for testing"""
        return {
            "study_info": {
                "title": "Working Memory Networks in Aging",
                "n_subjects": 45,
                "age_range": [65, 85],
                "scanner": "Siemens Prisma 3T",
                "task": "n-back working memory"
            },
            "preprocessing": {
                "software": "fMRIPrep v21.0.2",
                "space": "MNI152NLin2009cAsym",
                "smoothing_fwhm": 6.0,
                "motion_threshold": 0.5,
                "excluded_subjects": 3,
                "exclusion_reasons": ["excessive motion", "incomplete data"]
            },
            "first_level": {
                "model": "GLM",
                "design_matrix": "canonical_hrf",
                "contrasts": [
                    {"name": "2back_vs_0back", "description": "Working memory vs control"},
                    {"name": "parametric_load", "description": "Linear increase with load"}
                ],
                "autocorrelation_correction": "FAST"
            },
            "group_analysis": {
                "model": "mixed_effects",
                "covariates": ["age", "education", "sex"],
                "correction_method": "cluster_FWE",
                "cluster_threshold": 10,
                "significance_threshold": 0.05
            },
            "results": {
                "significant_clusters": [
                    {
                        "contrast": "2back_vs_0back",
                        "region": "left_dorsolateral_prefrontal_cortex",
                        "peak_coordinates": [-42, 22, 36],
                        "cluster_size": 234,
                        "peak_z": 4.67,
                        "peak_p": 0.0001,
                        "extent_p": 0.001
                    },
                    {
                        "contrast": "2back_vs_0back",
                        "region": "bilateral_posterior_parietal_cortex", 
                        "peak_coordinates": [38, -58, 44],
                        "cluster_size": 189,
                        "peak_z": 4.23,
                        "peak_p": 0.0005,
                        "extent_p": 0.003
                    },
                    {
                        "contrast": "parametric_load",
                        "region": "anterior_cingulate_cortex",
                        "peak_coordinates": [2, 18, 32],
                        "cluster_size": 156,
                        "peak_z": 3.89,
                        "peak_p": 0.002,
                        "extent_p": 0.008
                    }
                ],
                "behavioral_correlations": {
                    "accuracy_correlation": {
                        "region": "left_dorsolateral_prefrontal_cortex",
                        "r": 0.43,
                        "p": 0.003,
                        "interpretation": "Higher activation associated with better performance"
                    },
                    "age_correlation": {
                        "region": "anterior_cingulate_cortex", 
                        "r": -0.38,
                        "p": 0.01,
                        "interpretation": "Activation decreases with age"
                    }
                },
                "network_analysis": {
                    "identified_networks": ["frontoparietal", "cingulo_opercular"],
                    "within_network_connectivity": 0.72,
                    "between_network_connectivity": 0.31,
                    "network_efficiency": 0.84
                }
            },
            "quality_metrics": {
                "mean_fd": 0.18,
                "mean_dvars": 1.04,
                "temporal_snr": 42.3,
                "spatial_snr": 89.1,
                "artifact_detection": "minimal_artifacts"
            },
            "limitations": [
                "Cross-sectional design limits causal inference",
                "Older adult sample may not generalize to younger populations",
                "Single task paradigm",
                "No longitudinal follow-up"
            ],
            "clinical_relevance": {
                "implications": [
                    "Preserved frontoparietal network function in healthy aging",
                    "Compensatory mechanisms in anterior cingulate",
                    "Potential biomarker for cognitive decline"
                ],
                "related_conditions": ["mild_cognitive_impairment", "dementia", "executive_dysfunction"]
            }
        }
    
    @pytest.mark.asyncio
    async def test_end_to_end_explanation_generation(self, nlg_engine, sample_user_profiles, complex_fmri_results):
        """Test complete end-to-end explanation generation"""
        neuroscientist_profile = sample_user_profiles["neuroscientist"]
        
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=neuroscientist_profile,
            analysis_context=complex_fmri_results,
            session_context={
                "previous_analyses": ["resting_state", "structural"],
                "research_focus": "aging_neuroscience",
                "time_constraints": "detailed_review"
            }
        )
        
        response = await nlg_engine.generate_response_async(
            content=complex_fmri_results,
            context=context
        )
        
        # Should generate comprehensive response
        assert len(response.primary_text) > 500  # Substantial explanation
        assert response.confidence_score > 0.7  # High confidence with rich data
        assert response.explanation_level == ExplanationLevel.TECHNICAL
        
        # Should include technical details for expert user
        technical_terms = ["GLM", "cluster-FWE", "mixed-effects", "frontoparietal"]
        assert any(term in response.primary_text for term in technical_terms)
        
        # Should include structured components
        assert response.structured_explanation is not None
        assert len(response.citations) > 0
        assert len(response.follow_up_questions) > 0
    
    @pytest.mark.asyncio
    async def test_multi_user_explanation_adaptation(self, nlg_engine, sample_user_profiles, complex_fmri_results):
        """Test explanation adaptation for different user types"""
        responses = {}
        
        for user_type, profile in sample_user_profiles.items():
            context = ResponseContext(
                response_type=ResponseType.ANALYSIS_RESULT,
                user_profile=profile,
                analysis_context=complex_fmri_results
            )
            
            response = await nlg_engine.generate_response_async(
                content=complex_fmri_results,
                context=context
            )
            
            responses[user_type] = response
        
        # Expert should get most technical explanation
        expert_response = responses["neuroscientist"]
        student_response = responses["student"]
        
        assert expert_response.complexity_score > student_response.complexity_score
        assert len(expert_response.primary_text) >= len(student_response.primary_text)
        
        # Student explanation should avoid jargon
        student_text = student_response.primary_text.lower()
        jargon_terms = ["autocorrelation", "canonical_hrf", "cluster_fwe", "mixed_effects"]
        jargon_count = sum(1 for term in jargon_terms if term in student_text)
        assert jargon_count <= 1  # Minimal jargon for beginners
        
        # Clinician should focus on implications
        clinician_response = responses["clinician"]
        clinical_terms = ["clinical", "patient", "diagnosis", "biomarker", "implications"]
        clinical_count = sum(1 for term in clinical_terms if term in clinician_response.primary_text.lower())
        assert clinical_count >= 2
    
    @pytest.mark.asyncio
    async def test_multi_language_workflow(self, nlg_engine, sample_user_profiles, complex_fmri_results):
        """Test complete multi-language workflow"""
        spanish_profile = sample_user_profiles["spanish_researcher"]
        
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=spanish_profile,
            analysis_context=complex_fmri_results
        )
        
        # Generate response in Spanish
        spanish_response = await nlg_engine.generate_response_async(
            content=complex_fmri_results,
            context=context,
            language=Language.SPANISH
        )
        
        assert spanish_response.language == Language.SPANISH
        
        # Should preserve technical terms even in translation
        technical_terms = ["fMRIPrep", "GLM", "FWE", "MNI152"]
        terms_preserved = sum(1 for term in technical_terms if term in spanish_response.primary_text)
        assert terms_preserved >= 2
        
        # Generate same content in English for comparison
        english_context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=spanish_profile,
            analysis_context=complex_fmri_results
        )
        
        english_response = await nlg_engine.generate_response_async(
            content=complex_fmri_results,
            context=english_context,
            language=Language.ENGLISH
        )
        
        # Should have similar structure and length
        assert abs(len(spanish_response.primary_text) - len(english_response.primary_text)) / len(english_response.primary_text) < 0.3
    
    @pytest.mark.asyncio
    async def test_conversational_context_evolution(self, nlg_engine, sample_user_profiles, complex_fmri_results):
        """Test context evolution over multiple interactions"""
        user_profile = sample_user_profiles["clinician"]
        
        # First interaction - initial results
        context1 = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=complex_fmri_results
        )
        
        response1 = await nlg_engine.generate_response_async(
            content=complex_fmri_results,
            context=context1
        )
        
        # Second interaction - follow-up question
        follow_up_question = {
            "question": "What does this mean for early dementia detection?",
            "focus_area": "clinical_applications"
        }
        
        context2 = ResponseContext(
            response_type=ResponseType.METHODOLOGY_EXPLANATION,
            user_profile=user_profile,
            analysis_context=follow_up_question,
            session_context={
                "previous_analysis": complex_fmri_results,
                "previous_response": response1.primary_text,
                "user_interest": "dementia_detection"
            },
            previous_responses=[response1.primary_text]
        )
        
        response2 = await nlg_engine.generate_response_async(
            content=follow_up_question,
            context=context2
        )
        
        # Second response should reference previous context
        assert response2.adaptation_applied
        assert "dementia" in response2.primary_text.lower() or "cognitive decline" in response2.primary_text.lower()
        
        # Should build on previous explanation
        dementia_terms = ["biomarker", "early detection", "screening", "cognitive decline"]
        assert any(term in response2.primary_text.lower() for term in dementia_terms)
    
    @pytest.mark.asyncio
    async def test_error_handling_and_recovery(self, nlg_engine, sample_user_profiles):
        """Test NLG system error handling and recovery"""
        user_profile = sample_user_profiles["neuroscientist"]
        
        # Test with incomplete/malformed data
        incomplete_results = {
            "analysis_type": "GLM",
            "status": "failed",
            "error": "Convergence failure",
            "partial_results": {
                "completed_subjects": 20,
                "total_subjects": 45
            }
        }
        
        context = ResponseContext(
            response_type=ResponseType.ERROR_MESSAGE,
            user_profile=user_profile,
            analysis_context=incomplete_results
        )
        
        response = await nlg_engine.generate_response_async(
            content=incomplete_results,
            context=context
        )
        
        assert response.primary_text is not None
        assert len(response.primary_text) > 0
        assert "error" in response.primary_text.lower() or "failed" in response.primary_text.lower()
        assert len(response.clarification_options) > 0
        
        # Test with missing required fields
        minimal_data = {"analysis_type": "unknown"}
        
        context_minimal = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=minimal_data
        )
        
        response_minimal = await nlg_engine.generate_response_async(
            content=minimal_data,
            context=context_minimal
        )
        
        # Should still generate a response even with minimal data
        assert response_minimal.primary_text is not None
        assert response_minimal.confidence_score < 0.5  # Should reflect uncertainty
    
    @pytest.mark.asyncio
    async def test_cross_service_integration(self, nlg_engine, sample_user_profiles):
        """Test integration with other services (BR-KG, NICLIP, etc.)"""
        user_profile = sample_user_profiles["neuroscientist"]
        
        # Mock cross-service data
        cross_service_results = {
            "fmri_analysis": {
                "significant_regions": ["dorsolateral_prefrontal_cortex", "posterior_parietal_cortex"]
            },
            "neurokg_concepts": {
                "related_concepts": ["working memory", "executive function", "cognitive control"],
                "concept_definitions": {
                    "working_memory": "The cognitive system responsible for temporary storage and manipulation of information"
                }
            },
            "niclip_similarities": {
                "similar_studies": [
                    {"study_id": "study_001", "similarity": 0.87, "title": "Working memory in young adults"},
                    {"study_id": "study_002", "similarity": 0.82, "title": "Age-related changes in prefrontal function"}
                ]
            },
            "meta_analysis": {
                "coordinate_based": {
                    "ale_peaks": [{"x": -42, "y": 22, "z": 36, "ale_score": 0.024}],
                    "convergent_regions": ["left_dlpfc", "bilateral_ppc"]
                }
            }
        }
        
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=cross_service_results,
            session_context={
                "integration_services": ["neurokg", "niclip", "meta_analysis"],
                "cross_reference": True
            }
        )
        
        response = await nlg_engine.generate_response_async(
            content=cross_service_results,
            context=context
        )
        
        # Should integrate information from multiple services
        assert "working memory" in response.primary_text.lower()
        assert len(response.citations) > 0  # Should reference similar studies
        assert len(response.related_topics) > 0
        
        # Should mention convergent evidence
        convergence_terms = ["consistent", "convergent", "similar", "replicated"]
        assert any(term in response.primary_text.lower() for term in convergence_terms)
    
    @pytest.mark.asyncio
    async def test_real_time_adaptation(self, nlg_engine, sample_user_profiles, complex_fmri_results):
        """Test real-time adaptation based on user feedback"""
        user_profile = sample_user_profiles["clinician"].copy()
        user_profile.adaptation_strategy = AdaptationStrategy.ADAPTIVE
        
        # Initial response
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=complex_fmri_results
        )
        
        initial_response = await nlg_engine.generate_response_async(
            content=complex_fmri_results,
            context=context
        )
        
        initial_complexity = initial_response.complexity_score
        
        # Simulate negative feedback (too complex)
        user_profile.feedback_scores.extend([2.0, 2.5, 2.0])  # Low scores
        user_profile.confusion_patterns.extend(["statistics", "technical_terms"])
        
        # Updated context with feedback
        context.user_profile = user_profile
        context.user_engagement_level = 0.3  # Low engagement
        
        adapted_response = await nlg_engine.generate_response_async(
            content=complex_fmri_results,
            context=context
        )
        
        # Should adapt to be simpler
        assert adapted_response.complexity_score < initial_complexity
        assert adapted_response.adaptation_applied
        
        # Should include more clarification options
        assert len(adapted_response.clarification_options) >= len(initial_response.clarification_options)
    
    @pytest.mark.asyncio
    async def test_visualization_integration(self, nlg_engine, sample_user_profiles, complex_fmri_results):
        """Test integration with visualization generation"""
        user_profile = sample_user_profiles["clinician"]
        user_profile.visual_descriptions = True
        
        # Add visualization information
        visualization_context = complex_fmri_results.copy()
        visualization_context["visualizations"] = {
            "brain_maps": [
                {
                    "type": "activation_map",
                    "contrast": "2back_vs_0back",
                    "colormap": "hot",
                    "threshold": "p < 0.05 FWE",
                    "description": "Activation clusters overlaid on MNI template"
                },
                {
                    "type": "connectivity_matrix",
                    "network": "frontoparietal",
                    "measure": "correlation",
                    "description": "Functional connectivity between network nodes"
                }
            ],
            "statistical_plots": [
                {
                    "type": "bar_chart",
                    "data": "activation_by_region",
                    "description": "Mean activation levels across brain regions"
                }
            ]
        }
        
        context = ResponseContext(
            response_type=ResponseType.VISUALIZATION_DESCRIPTION,
            user_profile=user_profile,
            analysis_context=visualization_context
        )
        
        response = await nlg_engine.generate_response_async(
            content=visualization_context,
            context=context
        )
        
        # Should describe visualizations
        visual_terms = ["activation map", "connectivity", "overlay", "threshold", "colormap"]
        assert any(term in response.primary_text.lower() for term in visual_terms)
        
        # Should have visualization metadata
        assert len(response.visualizations) > 0
    
    @pytest.mark.asyncio 
    async def test_citation_and_reference_integration(self, nlg_engine, sample_user_profiles, complex_fmri_results):
        """Test citation and reference integration"""
        user_profile = sample_user_profiles["neuroscientist"]
        user_profile.include_citations = True
        
        # Add reference information
        referenced_results = complex_fmri_results.copy()
        referenced_results["references"] = {
            "methodology_papers": [
                {
                    "pmid": "12345678",
                    "title": "Best practices in fMRI preprocessing",
                    "authors": "Smith et al.",
                    "journal": "NeuroImage",
                    "year": 2023
                }
            ],
            "related_studies": [
                {
                    "pmid": "87654321", 
                    "title": "Working memory networks in healthy aging",
                    "authors": "Johnson et al.",
                    "journal": "Nature Neuroscience",
                    "year": 2022
                }
            ],
            "software_references": [
                {
                    "name": "fMRIPrep",
                    "version": "21.0.2",
                    "citation": "Esteban et al., 2019"
                }
            ]
        }
        
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=referenced_results
        )
        
        response = await nlg_engine.generate_response_async(
            content=referenced_results,
            context=context
        )
        
        # Should include citations
        assert len(response.citations) >= 2
        
        # Should reference methodology
        assert any("Smith" in citation or "fMRIPrep" in citation for citation in response.citations)
        
        # Should include reference to related work
        assert any("Johnson" in citation or "working memory" in citation.lower() for citation in response.citations)


@pytest.mark.integration
@pytest.mark.slow
class TestNLGPerformanceIntegration:
    """Performance integration tests for NLG system"""
    
    @pytest.mark.asyncio
    async def test_response_generation_performance(self, nlg_engine, sample_user_profiles, complex_fmri_results):
        """Test response generation performance with realistic data"""
        user_profile = sample_user_profiles["neuroscientist"]
        
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=complex_fmri_results
        )
        
        # Measure response time
        import time
        start_time = time.time()
        
        response = await nlg_engine.generate_response_async(
            content=complex_fmri_results,
            context=context
        )
        
        end_time = time.time()
        generation_time = end_time - start_time
        
        # Should generate response in reasonable time
        assert generation_time < 5.0  # Less than 5 seconds for complex response
        assert response.primary_text is not None
        assert len(response.primary_text) > 0
    
    @pytest.mark.asyncio
    async def test_concurrent_response_generation(self, nlg_engine, sample_user_profiles, complex_fmri_results):
        """Test concurrent response generation for multiple users"""
        # Create multiple concurrent requests
        tasks = []
        
        for i, (user_type, profile) in enumerate(sample_user_profiles.items()):
            context = ResponseContext(
                response_type=ResponseType.ANALYSIS_RESULT,
                user_profile=profile,
                analysis_context=complex_fmri_results,
                session_context={"request_id": f"req_{i}"}
            )
            
            task = nlg_engine.generate_response_async(
                content=complex_fmri_results,
                context=context
            )
            tasks.append(task)
        
        # Execute concurrently
        import time
        start_time = time.time()
        
        responses = await asyncio.gather(*tasks)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # All responses should be generated
        assert len(responses) == len(sample_user_profiles)
        assert all(response.primary_text is not None for response in responses)
        
        # Concurrent execution should be more efficient than sequential
        assert total_time < 15.0  # Reasonable time for 4 concurrent requests
    
    @pytest.mark.asyncio
    async def test_memory_usage_under_load(self, nlg_engine, sample_user_profiles):
        """Test memory usage under sustained load"""
        import psutil
        import gc
        
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Generate many responses
        for i in range(20):
            user_profile = list(sample_user_profiles.values())[i % len(sample_user_profiles)]
            
            test_data = {
                "analysis_type": f"test_analysis_{i}",
                "results": {"activation": f"region_{i}"},
                "iteration": i
            }
            
            context = ResponseContext(
                response_type=ResponseType.ANALYSIS_RESULT,
                user_profile=user_profile,
                analysis_context=test_data
            )
            
            response = await nlg_engine.generate_response_async(
                content=test_data,
                context=context
            )
            
            assert response.primary_text is not None
            
            # Periodic garbage collection
            if i % 5 == 0:
                gc.collect()
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Memory usage should not increase excessively
        assert memory_increase < 100  # Less than 100MB increase
    
    @pytest.mark.asyncio
    async def test_explanation_quality_consistency(self, nlg_engine, sample_user_profiles, complex_fmri_results):
        """Test consistency of explanation quality across multiple generations"""
        user_profile = sample_user_profiles["neuroscientist"]
        
        responses = []
        
        # Generate same explanation multiple times
        for i in range(5):
            context = ResponseContext(
                response_type=ResponseType.ANALYSIS_RESULT,
                user_profile=user_profile,
                analysis_context=complex_fmri_results,
                session_context={"generation": i}
            )
            
            response = await nlg_engine.generate_response_async(
                content=complex_fmri_results,
                context=context
            )
            
            responses.append(response)
        
        # Check consistency metrics
        confidence_scores = [r.confidence_score for r in responses]
        complexity_scores = [r.complexity_score for r in responses]
        
        # Scores should be consistent
        import statistics
        confidence_std = statistics.stdev(confidence_scores)
        complexity_std = statistics.stdev(complexity_scores)
        
        assert confidence_std < 0.1  # Low variation in confidence
        assert complexity_std < 0.1  # Low variation in complexity
        
        # Content should cover similar key points
        all_texts = [r.primary_text.lower() for r in responses]
        key_terms = ["working memory", "prefrontal", "parietal", "significant"]
        
        for term in key_terms:
            term_counts = [text.count(term) for text in all_texts]
            # Each key term should appear in most responses
            assert sum(1 for count in term_counts if count > 0) >= 3


@pytest.mark.integration
class TestNLGErrorHandlingIntegration:
    """Integration tests for NLG error handling"""
    
    @pytest.mark.asyncio
    async def test_malformed_input_handling(self, nlg_engine, sample_user_profiles):
        """Test handling of malformed input data"""
        user_profile = sample_user_profiles["clinician"]
        
        malformed_inputs = [
            None,
            {},
            {"invalid": "structure"},
            {"analysis_type": None, "results": []},
            {"nested": {"deeply": {"malformed": {"data": None}}}}
        ]
        
        for malformed_input in malformed_inputs:
            context = ResponseContext(
                response_type=ResponseType.ANALYSIS_RESULT,
                user_profile=user_profile,
                analysis_context=malformed_input
            )
            
            # Should not crash
            response = await nlg_engine.generate_response_async(
                content=malformed_input,
                context=context
            )
            
            assert response.primary_text is not None
            assert len(response.primary_text) > 0
            # Should indicate uncertainty/incompleteness
            assert response.confidence_score < 0.5
    
    @pytest.mark.asyncio
    async def test_service_dependency_failures(self, nlg_engine, sample_user_profiles, complex_fmri_results):
        """Test behavior when dependent services fail"""
        user_profile = sample_user_profiles["spanish_researcher"]
        
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=complex_fmri_results
        )
        
        # Mock translation service failure
        with patch.object(nlg_engine.translator, 'translate', side_effect=Exception("Translation service unavailable")):
            response = await nlg_engine.generate_response_async(
                content=complex_fmri_results,
                context=context,
                language=Language.SPANISH
            )
            
            # Should fall back to English
            assert response.language == Language.ENGLISH
            assert response.primary_text is not None
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, nlg_engine, sample_user_profiles, complex_fmri_results):
        """Test timeout handling for slow operations"""
        user_profile = sample_user_profiles["neuroscientist"]
        
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=complex_fmri_results,
            session_context={"timeout": 1.0}  # Very short timeout
        )
        
        # Mock slow operation
        with patch.object(nlg_engine.explanation_gen, 'generate_structured_explanation', 
                         side_effect=lambda *args: asyncio.sleep(2.0)):
            
            response = await nlg_engine.generate_response_async(
                content=complex_fmri_results,
                context=context
            )
            
            # Should still generate a response, possibly with reduced features
            assert response.primary_text is not None
            assert len(response.primary_text) > 0