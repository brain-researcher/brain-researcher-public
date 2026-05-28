"""
Unit tests for Enhanced Natural Language Generation

Tests for:
- Context-aware response generation
- Multi-language support
- Explanation level adaptation
- User profile management
- Template selection and processing
- Confidence scoring
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from typing import Dict, List, Any

from brain_researcher.services.agent.nlg_enhancement import (
    EnhancedNLGEngine, ResponseType, AdaptationStrategy, UserProfile, 
    ResponseContext, NLGResponse, MultiLanguageTranslator
)
from brain_researcher.services.agent.language_templates import Language, ExplanationLevel
from brain_researcher.services.agent.explanation_generator import ExpertiseLevel


class TestEnhancedNLGEngine:
    """Test suite for EnhancedNLGEngine"""
    
    @pytest.fixture
    def mock_templates(self):
        """Mock language templates"""
        templates = Mock()
        templates.get_template.return_value = "Analysis completed using {method}. Results: {results}"
        templates.supported_languages = [Language.ENGLISH, Language.SPANISH, Language.FRENCH]
        return templates
    
    @pytest.fixture
    def mock_explanation_generator(self):
        """Mock explanation generator"""
        generator = Mock()
        generator.generate_technical_explanation.return_value = "Technical explanation with statistics and methodology."
        generator.generate_layman_explanation.return_value = "Simple explanation for general audience."
        generator.generate_structured_explanation.return_value = {
            "summary": "Brief overview",
            "methodology": "How we did it", 
            "findings": "What we found",
            "implications": "What it means"
        }
        return generator
    
    @pytest.fixture
    def mock_translator(self):
        """Mock multi-language translator"""
        translator = Mock()
        translator.translate.return_value = "Translated text"
        translator.supported_languages = [Language.ENGLISH, Language.SPANISH, Language.FRENCH, Language.GERMAN, Language.CHINESE]
        return translator
    
    @pytest.fixture
    def nlg_engine(self, mock_templates, mock_explanation_generator, mock_translator):
        """NLG engine with mocked dependencies"""
        engine = EnhancedNLGEngine()
        engine.templates = mock_templates
        engine.explanation_gen = mock_explanation_generator
        engine.translator = mock_translator
        return engine
    
    @pytest.fixture
    def user_profile(self):
        """Sample user profile"""
        return UserProfile(
            user_id="test_user",
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            preferred_language=Language.ENGLISH,
            preferred_explanation_level=ExplanationLevel.STRUCTURED,
            detailed_methodology=True,
            include_citations=True
        )
    
    @pytest.fixture
    def analysis_result(self):
        """Sample analysis result"""
        return {
            "method": "GLM",
            "significant_clusters": 15,
            "max_z_score": 4.2,
            "peak_coordinates": [42, -58, 32],
            "brain_region": "superior temporal gyrus",
            "p_value": 0.001,
            "cluster_size": 128,
            "correction_method": "FWE"
        }
    
    @pytest.mark.unit
    def test_basic_response_generation(self, nlg_engine, user_profile, analysis_result):
        """Test basic response generation"""
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=analysis_result
        )
        
        response = nlg_engine.generate_response(
            content=analysis_result,
            context=context,
            explanation_level=ExplanationLevel.TECHNICAL,
            language=Language.ENGLISH
        )
        
        assert isinstance(response, NLGResponse)
        assert response.primary_text is not None
        assert response.language == Language.ENGLISH
        assert response.explanation_level == ExplanationLevel.TECHNICAL
        assert response.confidence_score >= 0.0
        assert response.confidence_score <= 1.0
    
    @pytest.mark.unit
    def test_explanation_level_adaptation(self, nlg_engine, user_profile, analysis_result):
        """Test adaptation based on explanation level"""
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=analysis_result
        )
        
        # Technical explanation
        technical_response = nlg_engine.generate_response(
            content=analysis_result,
            context=context,
            explanation_level=ExplanationLevel.TECHNICAL
        )
        
        # Layman explanation
        layman_response = nlg_engine.generate_response(
            content=analysis_result,
            context=context,
            explanation_level=ExplanationLevel.LAYMAN
        )
        
        # Should call different explanation generators
        nlg_engine.explanation_gen.generate_technical_explanation.assert_called()
        nlg_engine.explanation_gen.generate_layman_explanation.assert_called()
        
        # Responses should be different
        assert technical_response.explanation_level == ExplanationLevel.TECHNICAL
        assert layman_response.explanation_level == ExplanationLevel.LAYMAN
    
    @pytest.mark.unit
    def test_multi_language_support(self, nlg_engine, user_profile, analysis_result):
        """Test multi-language response generation"""
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=analysis_result
        )
        
        # Generate response in Spanish
        spanish_response = nlg_engine.generate_response(
            content=analysis_result,
            context=context,
            language=Language.SPANISH
        )
        
        assert spanish_response.language == Language.SPANISH
        nlg_engine.translator.translate.assert_called_with(
            spanish_response.primary_text,
            Language.SPANISH,
            preserve_technical_terms=True
        )
    
    @pytest.mark.unit
    def test_user_profile_adaptation(self, nlg_engine, analysis_result):
        """Test adaptation based on user profile"""
        # Expert user profile
        expert_profile = UserProfile(
            user_id="expert_user",
            expertise_level=ExpertiseLevel.EXPERT,
            statistical_details=True,
            detailed_methodology=True
        )
        
        # Beginner user profile
        beginner_profile = UserProfile(
            user_id="beginner_user", 
            expertise_level=ExpertiseLevel.BEGINNER,
            statistical_details=False,
            detailed_methodology=False
        )
        
        expert_context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=expert_profile
        )
        
        beginner_context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=beginner_profile
        )
        
        expert_response = nlg_engine.generate_response(
            content=analysis_result,
            context=expert_context
        )
        
        beginner_response = nlg_engine.generate_response(
            content=analysis_result,
            context=beginner_context
        )
        
        # Expert response should be more detailed
        assert expert_response.complexity_score >= beginner_response.complexity_score
    
    @pytest.mark.unit
    def test_context_awareness(self, nlg_engine, user_profile, analysis_result):
        """Test context-aware response generation"""
        # Context with previous interactions
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=analysis_result,
            session_context={
                "previous_analyses": ["resting_state", "task_based"],
                "current_focus": "connectivity",
                "user_questions": ["What does this region do?", "Is this significant?"]
            },
            previous_responses=["Previous analysis showed activation in visual cortex."]
        )
        
        response = nlg_engine.generate_response(
            content=analysis_result,
            context=context
        )
        
        # Should incorporate context
        assert response.adaptation_applied
        assert len(response.follow_up_questions) > 0
        assert len(response.related_topics) > 0
    
    @pytest.mark.unit
    def test_confidence_scoring(self, nlg_engine, user_profile):
        """Test confidence scoring in responses"""
        # High confidence scenario
        high_confidence_result = {
            "p_value": 0.0001,
            "z_score": 5.2,
            "cluster_size": 256,
            "replication_studies": 15
        }
        
        # Low confidence scenario  
        low_confidence_result = {
            "p_value": 0.049,
            "z_score": 2.1,
            "cluster_size": 12,
            "replication_studies": 1
        }
        
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile
        )
        
        high_conf_response = nlg_engine.generate_response(
            content=high_confidence_result,
            context=context
        )
        
        low_conf_response = nlg_engine.generate_response(
            content=low_confidence_result,
            context=context
        )
        
        assert high_conf_response.confidence_score > low_conf_response.confidence_score
    
    @pytest.mark.unit
    def test_structured_explanation_generation(self, nlg_engine, user_profile, analysis_result):
        """Test structured explanation generation"""
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile
        )
        
        response = nlg_engine.generate_response(
            content=analysis_result,
            context=context,
            explanation_level=ExplanationLevel.STRUCTURED
        )
        
        assert response.structured_explanation is not None
        structured = response.structured_explanation
        assert "summary" in structured
        assert "methodology" in structured
        assert "findings" in structured
        assert "implications" in structured
    
    @pytest.mark.unit
    def test_citation_integration(self, nlg_engine, user_profile, analysis_result):
        """Test citation integration in responses"""
        # Add citation information to analysis result
        analysis_with_citations = analysis_result.copy()
        analysis_with_citations.update({
            "related_studies": [
                {"pmid": "12345678", "title": "Study on temporal lobe"},
                {"pmid": "87654321", "title": "GLM analysis methods"}
            ],
            "methodological_papers": [
                {"pmid": "11111111", "title": "fMRI preprocessing best practices"}
            ]
        })
        
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile
        )
        
        response = nlg_engine.generate_response(
            content=analysis_with_citations,
            context=context
        )
        
        assert len(response.citations) > 0
        assert any("12345678" in citation for citation in response.citations)
    
    @pytest.mark.unit
    def test_error_message_generation(self, nlg_engine, user_profile):
        """Test error message generation"""
        error_context = {
            "error_type": "TimeoutError",
            "error_message": "Processing timeout after 3600 seconds",
            "suggested_solutions": ["Reduce data size", "Use more powerful hardware"]
        }
        
        context = ResponseContext(
            response_type=ResponseType.ERROR_MESSAGE,
            user_profile=user_profile,
            analysis_context=error_context
        )
        
        response = nlg_engine.generate_response(
            content=error_context,
            context=context
        )
        
        assert response.response_type == ResponseType.ERROR_MESSAGE
        assert "timeout" in response.primary_text.lower()
        assert len(response.clarification_options) > 0
    
    @pytest.mark.unit
    def test_progress_update_generation(self, nlg_engine, user_profile):
        """Test progress update message generation"""
        progress_context = {
            "stage": "preprocessing",
            "progress_percentage": 65,
            "current_step": "motion correction",
            "estimated_remaining_time": "15 minutes",
            "completed_subjects": 13,
            "total_subjects": 20
        }
        
        context = ResponseContext(
            response_type=ResponseType.PROGRESS_UPDATE,
            user_profile=user_profile,
            analysis_context=progress_context
        )
        
        response = nlg_engine.generate_response(
            content=progress_context,
            context=context
        )
        
        assert "65%" in response.primary_text or "65 percent" in response.primary_text
        assert "motion correction" in response.primary_text.lower()
        assert response.estimated_reading_time > 0
    
    @pytest.mark.unit
    def test_alternative_text_generation(self, nlg_engine, user_profile, analysis_result):
        """Test generation of alternative explanations"""
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile
        )
        
        response = nlg_engine.generate_response(
            content=analysis_result,
            context=context,
            generate_alternatives=True
        )
        
        assert len(response.alternative_texts) > 0
        # Alternative texts should be different from primary
        for alt_text in response.alternative_texts:
            assert alt_text != response.primary_text
    
    @pytest.mark.unit
    def test_visualization_description(self, nlg_engine, user_profile):
        """Test description generation for visualizations"""
        visualization_context = {
            "plot_type": "brain_activation_map",
            "colormap": "hot",
            "threshold": "p < 0.05 FWE corrected",
            "overlay": "MNI152 template",
            "significant_regions": ["superior temporal gyrus", "inferior frontal gyrus"],
            "max_activation": {"coordinates": [42, -58, 32], "z_score": 4.2}
        }
        
        context = ResponseContext(
            response_type=ResponseType.VISUALIZATION_DESCRIPTION,
            user_profile=user_profile,
            analysis_context=visualization_context
        )
        
        response = nlg_engine.generate_response(
            content=visualization_context,
            context=context
        )
        
        assert "brain activation" in response.primary_text.lower()
        assert "temporal gyrus" in response.primary_text.lower()
        assert len(response.visualizations) > 0
    
    @pytest.mark.unit
    def test_adaptive_complexity_adjustment(self, nlg_engine, user_profile, analysis_result):
        """Test adaptive complexity adjustment based on user feedback"""
        # Simulate user feedback indicating confusion
        user_profile.confusion_patterns = ["statistical significance", "multiple comparisons"]
        user_profile.feedback_scores = [2.0, 2.5, 3.0]  # Low scores indicating confusion
        
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            analysis_context=analysis_result
        )
        
        response = nlg_engine.generate_response(
            content=analysis_result,
            context=context
        )
        
        # Should adapt to be simpler due to low feedback scores
        assert response.adaptation_applied
        assert response.complexity_score < 0.7  # Should be simplified


class TestMultiLanguageTranslator:
    """Test suite for MultiLanguageTranslator"""
    
    @pytest.fixture
    def translator(self):
        return MultiLanguageTranslator()
    
    @pytest.mark.unit
    def test_supported_languages(self, translator):
        """Test supported languages list"""
        assert Language.ENGLISH in translator.supported_languages
        assert Language.SPANISH in translator.supported_languages
        assert Language.FRENCH in translator.supported_languages
        assert Language.GERMAN in translator.supported_languages
        assert Language.CHINESE in translator.supported_languages
    
    @pytest.mark.unit
    def test_technical_term_preservation(self, translator):
        """Test preservation of technical terms during translation"""
        text = "The GLM analysis showed significant activation (p < 0.05, FWE corrected) in the superior temporal gyrus."
        
        with patch.object(translator, '_perform_translation', return_value="Translated text with GLM and p < 0.05"):
            translated = translator.translate(text, Language.SPANISH, preserve_technical_terms=True)
            
            # Should preserve technical terms
            assert "GLM" in translated
            assert "p < 0.05" in translated
    
    @pytest.mark.unit
    def test_technical_term_extraction(self, translator):
        """Test extraction of technical terms"""
        text = "The fMRI analysis used GLM with FWE correction (p < 0.001). BOLD signal in temporal cortex showed t = 4.2."
        
        terms = translator._extract_technical_terms(text)
        
        # Should extract various types of technical terms
        technical_term_found = any(
            term for term in terms 
            if any(keyword in term.lower() for keyword in ['fmri', 'glm', 'fwe', 'p <', 't =', 'bold'])
        )
        assert technical_term_found
    
    @pytest.mark.unit
    def test_domain_terminology_loading(self, translator):
        """Test domain-specific terminology loading"""
        domain_terms = translator._load_domain_terminology()
        
        assert Language.SPANISH in domain_terms
        assert Language.FRENCH in domain_terms
        assert Language.GERMAN in domain_terms
        assert Language.CHINESE in domain_terms
        
        # Should have neuroimaging-specific terms
        spanish_terms = domain_terms[Language.SPANISH]
        assert "activation" in spanish_terms
        assert "connectivity" in spanish_terms
        assert "preprocessing" in spanish_terms
    
    @pytest.mark.unit
    def test_fallback_to_english(self, translator):
        """Test fallback to English for unsupported languages"""
        text = "Test text for translation"
        
        # Should return original English text
        result = translator.translate(text, Language.ENGLISH)
        assert result == text
    
    @pytest.mark.unit  
    def test_translation_quality_metrics(self, translator):
        """Test translation quality assessment"""
        # This would test translation quality metrics
        # In practice, would integrate with translation quality APIs
        pass


class TestResponseContext:
    """Test suite for ResponseContext"""
    
    @pytest.mark.unit
    def test_context_creation(self):
        """Test response context creation"""
        user_profile = UserProfile(user_id="test")
        
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile,
            session_context={"current_analysis": "resting_state"},
            analysis_context={"method": "ICA"},
            temporal_context={"time_of_day": "morning"}
        )
        
        assert context.response_type == ResponseType.ANALYSIS_RESULT
        assert context.user_profile.user_id == "test"
        assert context.session_context["current_analysis"] == "resting_state"
        assert context.analysis_context["method"] == "ICA"
        assert context.temporal_context["time_of_day"] == "morning"
    
    @pytest.mark.unit
    def test_context_evolution(self):
        """Test context evolution during conversation"""
        user_profile = UserProfile(user_id="test")
        
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=user_profile
        )
        
        # Simulate conversation progression
        context.previous_responses.append("First response")
        context.current_complexity_level = 0.7
        context.user_engagement_level = 0.8
        
        assert len(context.previous_responses) == 1
        assert context.current_complexity_level == 0.7
        assert context.user_engagement_level == 0.8


class TestNLGResponse:
    """Test suite for NLGResponse"""
    
    @pytest.mark.unit
    def test_response_creation(self):
        """Test NLG response creation"""
        response = NLGResponse(
            primary_text="Analysis completed successfully.",
            confidence_score=0.85,
            explanation_level=ExplanationLevel.TECHNICAL,
            language=Language.ENGLISH
        )
        
        assert response.primary_text == "Analysis completed successfully."
        assert response.confidence_score == 0.85
        assert response.explanation_level == ExplanationLevel.TECHNICAL
        assert response.language == Language.ENGLISH
        assert isinstance(response.generation_time, datetime)
    
    @pytest.mark.unit
    def test_response_with_structured_explanation(self):
        """Test response with structured explanation"""
        structured_explanation = {
            "summary": "Brief overview",
            "methodology": "How analysis was performed",
            "findings": "Key results",
            "implications": "What results mean"
        }
        
        response = NLGResponse(
            primary_text="Main response text",
            structured_explanation=structured_explanation
        )
        
        assert response.structured_explanation == structured_explanation
    
    @pytest.mark.unit
    def test_response_metadata(self):
        """Test response metadata fields"""
        response = NLGResponse(
            primary_text="Test response",
            estimated_reading_time=45,
            complexity_score=0.6,
            adaptation_applied=True
        )
        
        assert response.estimated_reading_time == 45
        assert response.complexity_score == 0.6
        assert response.adaptation_applied is True
    
    @pytest.mark.unit
    def test_interactive_elements(self):
        """Test interactive response elements"""
        response = NLGResponse(
            primary_text="Analysis results",
            follow_up_questions=["What does this region do?", "Are these results significant?"],
            clarification_options=["Explain statistics", "Show methodology"],
            related_topics=["Temporal lobe function", "Statistical significance"]
        )
        
        assert len(response.follow_up_questions) == 2
        assert len(response.clarification_options) == 2
        assert len(response.related_topics) == 2
        assert "What does this region do?" in response.follow_up_questions


# Integration-style unit tests
class TestNLGIntegration:
    """Integration-style tests for NLG components"""
    
    @pytest.mark.unit
    def test_end_to_end_response_generation(self):
        """Test complete end-to-end response generation"""
        # This would test the full pipeline from input to final response
        pass
    
    @pytest.mark.unit
    def test_user_adaptation_learning(self):
        """Test user adaptation learning over time"""
        # This would test how the system learns from user interactions
        pass
    
    @pytest.mark.unit
    def test_cross_language_consistency(self):
        """Test consistency across different languages"""
        # This would test that translations maintain semantic consistency
        pass


# Performance tests
@pytest.mark.performance
class TestNLGPerformance:
    """Performance tests for NLG system"""
    
    def test_response_generation_speed(self):
        """Test response generation performance"""
        # Would test response generation times
        pass
    
    def test_memory_usage_during_translation(self):
        """Test memory usage during translation"""
        # Would test memory efficiency
        pass