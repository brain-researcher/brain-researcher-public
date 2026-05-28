"""
Unit tests for Explanation Generator

Tests for:
- Technical vs layman explanation generation
- Structured explanation formatting
- Context-aware explanation adaptation
- Expertise level handling
- Domain-specific terminology management
- Explanation quality assessment
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List, Any

# Skip the module if optional explanation helpers are absent
exp_mod = pytest.importorskip(
    "brain_researcher.services.agent.explanation_generator",
    reason="explanation generator optional/legacy components not available",
)
if not all(
    hasattr(exp_mod, name)
    for name in (
        "MethodologyExplainer",
        "StatisticalInterpreter",
        "ClinicalImplicationsGenerator",
    )
):
    pytest.skip(
        "explanation generator helpers not available in this environment",
        allow_module_level=True,
    )

from brain_researcher.services.agent.explanation_generator import (
    ExplanationGenerator,
    ExpertiseLevel,
    ExplanationContext,
    StructuredExplanation,
    ExplanationResult,
    MethodologyExplainer,
    StatisticalInterpreter,
    ClinicalImplicationsGenerator,
)


class TestExplanationGenerator:
    """Test suite for ExplanationGenerator"""
    
    @pytest.fixture
    def explanation_generator(self):
        """Create explanation generator with mocked dependencies"""
        generator = ExplanationGenerator()
        generator.methodology_explainer = Mock()
        generator.statistical_interpreter = Mock()
        generator.clinical_implications = Mock()
        return generator
    
    @pytest.fixture
    def fmri_analysis_result(self):
        """Sample fMRI analysis result"""
        return {
            "analysis_type": "GLM",
            "method": "first_level_analysis",
            "significant_clusters": [
                {
                    "region": "superior temporal gyrus",
                    "hemisphere": "left",
                    "peak_coordinates": [42, -58, 32],
                    "z_score": 4.2,
                    "cluster_size": 128,
                    "p_value": 0.001,
                    "correction_method": "FWE"
                },
                {
                    "region": "inferior frontal gyrus", 
                    "hemisphere": "right",
                    "peak_coordinates": [-38, 22, 8],
                    "z_score": 3.8,
                    "cluster_size": 96,
                    "p_value": 0.005,
                    "correction_method": "FWE"
                }
            ],
            "contrast": "working_memory_vs_rest",
            "n_subjects": 24,
            "preprocessing": {
                "software": "fMRIPrep",
                "smoothing_fwhm": 6.0,
                "motion_correction": True,
                "slice_timing": True
            },
            "statistical_model": {
                "design_matrix": "blocked_design",
                "hrf_model": "canonical_hrf",
                "high_pass_filter": 128,
                "autocorrelation_correction": "AR(1)"
            }
        }
    
    @pytest.fixture
    def connectivity_analysis_result(self):
        """Sample connectivity analysis result"""
        return {
            "analysis_type": "functional_connectivity",
            "method": "seed_based_correlation",
            "seed_region": "posterior_cingulate_cortex",
            "significant_connections": [
                {
                    "target_region": "medial_prefrontal_cortex",
                    "correlation": 0.68,
                    "p_value": 0.0001,
                    "network": "default_mode_network"
                },
                {
                    "target_region": "angular_gyrus",
                    "correlation": 0.54,
                    "p_value": 0.002,
                    "network": "default_mode_network"
                }
            ],
            "network_properties": {
                "modularity": 0.42,
                "clustering_coefficient": 0.38,
                "path_length": 2.1,
                "small_world_coefficient": 1.8
            }
        }
    
    @pytest.mark.unit
    def test_technical_explanation_generation(self, explanation_generator, fmri_analysis_result):
        """Test generation of technical explanations"""
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.EXPERT,
            domain_focus=["methods", "statistics"],
            include_methodology=True,
            include_statistics=True
        )
        
        explanation = explanation_generator.generate_technical_explanation(
            fmri_analysis_result, context
        )
        
        assert isinstance(explanation, str)
        assert len(explanation) > 0
        
        # Should include technical terms
        technical_terms = ["GLM", "FWE", "z-score", "coordinates", "cluster"]
        assert any(term in explanation for term in technical_terms)
        
        # Should include statistical details
        statistical_terms = ["p < 0.05", "correction", "significance"]
        assert any(term in explanation.lower() for term in statistical_terms)
    
    @pytest.mark.unit
    def test_layman_explanation_generation(self, explanation_generator, fmri_analysis_result):
        """Test generation of layman-friendly explanations"""
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.BEGINNER,
            domain_focus=["implications"],
            include_methodology=False,
            include_statistics=False,
            use_analogies=True
        )
        
        explanation = explanation_generator.generate_layman_explanation(
            fmri_analysis_result, context
        )
        
        assert isinstance(explanation, str)
        assert len(explanation) > 0
        
        # Should avoid technical jargon
        jargon_terms = ["GLM", "FWE", "autocorrelation", "canonical_hrf"]
        assert not any(term in explanation for term in jargon_terms)
        
        # Should include plain language terms
        plain_terms = ["brain", "activity", "region", "significant"]
        assert any(term in explanation.lower() for term in plain_terms)
    
    @pytest.mark.unit
    def test_structured_explanation_generation(self, explanation_generator, fmri_analysis_result):
        """Test generation of structured explanations"""
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            structured_format=True
        )
        
        structured = explanation_generator.generate_structured_explanation(fmri_analysis_result, context)
        
        assert isinstance(structured, dict)
        
        # Should contain all required sections
        required_sections = ["summary", "methodology", "findings", "implications", "confidence", "limitations"]
        for section in required_sections:
            assert section in structured
            assert isinstance(structured[section], str)
            assert len(structured[section]) > 0
    
    @pytest.mark.unit
    def test_expertise_level_adaptation(self, explanation_generator, fmri_analysis_result):
        """Test adaptation based on expertise level"""
        # Beginner context
        beginner_context = ExplanationContext(
            expertise_level=ExpertiseLevel.BEGINNER,
            simplify_terminology=True
        )
        
        beginner_explanation = explanation_generator.generate_explanation(
            fmri_analysis_result, beginner_context
        )
        
        # Expert context
        expert_context = ExplanationContext(
            expertise_level=ExpertiseLevel.EXPERT,
            include_advanced_statistics=True,
            include_methodology_details=True
        )
        
        expert_explanation = explanation_generator.generate_explanation(
            fmri_analysis_result, expert_context
        )
        
        # Expert explanation should be more detailed
        assert len(expert_explanation.explanation) >= len(beginner_explanation.explanation)
        assert expert_explanation.complexity_score > beginner_explanation.complexity_score
    
    @pytest.mark.unit
    def test_connectivity_analysis_explanation(self, explanation_generator, connectivity_analysis_result):
        """Test explanation of connectivity analysis results"""
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            domain_focus=["connectivity", "networks"]
        )
        
        explanation = explanation_generator.generate_technical_explanation(
            connectivity_analysis_result, context
        )
        
        # Should include connectivity-specific terms
        connectivity_terms = ["correlation", "connectivity", "network", "seed", "default mode"]
        assert any(term in explanation.lower() for term in connectivity_terms)
        
        # Should mention network properties
        network_terms = ["modularity", "clustering", "small world"]
        assert any(term in explanation.lower() for term in network_terms)
    
    @pytest.mark.unit
    def test_domain_specific_terminology(self, explanation_generator, fmri_analysis_result):
        """Test handling of domain-specific terminology"""
        # Cognitive neuroscience focus
        cognitive_context = ExplanationContext(
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            domain_focus=["cognitive", "behavioral"]
        )
        
        cognitive_explanation = explanation_generator.generate_explanation(
            fmri_analysis_result, cognitive_context
        )
        
        # Should include cognitive terms
        cognitive_terms = ["working memory", "cognition", "task", "behavior"]
        assert any(term in cognitive_explanation.explanation.lower() for term in cognitive_terms)
        
        # Clinical focus
        clinical_context = ExplanationContext(
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            domain_focus=["clinical", "diagnostic"]
        )
        
        clinical_explanation = explanation_generator.generate_explanation(
            fmri_analysis_result, clinical_context
        )
        
        # Different terminology for clinical context
        assert cognitive_explanation.explanation != clinical_explanation.explanation
    
    @pytest.mark.unit
    def test_confidence_assessment(self, explanation_generator, fmri_analysis_result):
        """Test confidence assessment in explanations"""
        # High confidence scenario
        high_conf_result = fmri_analysis_result.copy()
        high_conf_result["n_subjects"] = 50
        high_conf_result["significant_clusters"][0]["p_value"] = 0.0001
        high_conf_result["replication_studies"] = 10
        
        # Low confidence scenario
        low_conf_result = fmri_analysis_result.copy()
        low_conf_result["n_subjects"] = 12
        low_conf_result["significant_clusters"][0]["p_value"] = 0.04
        low_conf_result["replication_studies"] = 0
        
        context = ExplanationContext(expertise_level=ExpertiseLevel.INTERMEDIATE)
        
        high_conf_explanation = explanation_generator.generate_explanation(high_conf_result, context)
        low_conf_explanation = explanation_generator.generate_explanation(low_conf_result, context)
        
        assert high_conf_explanation.confidence_score > low_conf_explanation.confidence_score
        
        # High confidence explanation should mention strength
        high_conf_indicators = ["strong", "robust", "reliable", "consistent"]
        assert any(indicator in high_conf_explanation.explanation.lower() 
                  for indicator in high_conf_indicators)
        
        # Low confidence explanation should mention limitations
        low_conf_indicators = ["preliminary", "limited", "cautious", "small sample"]
        assert any(indicator in low_conf_explanation.explanation.lower()
                  for indicator in low_conf_indicators)
    
    @pytest.mark.unit
    def test_methodology_explanation_integration(self, explanation_generator, fmri_analysis_result):
        """Test integration with methodology explainer"""
        explanation_generator.methodology_explainer.explain_preprocessing.return_value = "Preprocessing explanation"
        explanation_generator.methodology_explainer.explain_statistical_model.return_value = "Statistical model explanation"
        
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            include_methodology=True
        )
        
        explanation = explanation_generator.generate_explanation(fmri_analysis_result, context)
        
        explanation_generator.methodology_explainer.explain_preprocessing.assert_called()
        explanation_generator.methodology_explainer.explain_statistical_model.assert_called()
        
        # Should include methodology in explanation
        assert "preprocessing" in explanation.explanation.lower() or "statistical model" in explanation.explanation.lower()
    
    @pytest.mark.unit
    def test_statistical_interpretation_integration(self, explanation_generator, fmri_analysis_result):
        """Test integration with statistical interpreter"""
        explanation_generator.statistical_interpreter.interpret_p_values.return_value = "P-value interpretation"
        explanation_generator.statistical_interpreter.interpret_effect_sizes.return_value = "Effect size interpretation"
        explanation_generator.statistical_interpreter.interpret_multiple_comparisons.return_value = "Multiple comparisons interpretation"
        
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            include_statistics=True
        )
        
        explanation = explanation_generator.generate_explanation(fmri_analysis_result, context)
        
        explanation_generator.statistical_interpreter.interpret_p_values.assert_called()
        explanation_generator.statistical_interpreter.interpret_multiple_comparisons.assert_called()
    
    @pytest.mark.unit
    def test_clinical_implications_integration(self, explanation_generator, fmri_analysis_result):
        """Test integration with clinical implications generator"""
        explanation_generator.clinical_implications.generate_implications.return_value = "Clinical implications"
        
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            domain_focus=["clinical"],
            include_implications=True
        )
        
        explanation = explanation_generator.generate_explanation(fmri_analysis_result, context)
        
        explanation_generator.clinical_implications.generate_implications.assert_called()
    
    @pytest.mark.unit
    def test_analogy_generation(self, explanation_generator, fmri_analysis_result):
        """Test generation of analogies for complex concepts"""
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.BEGINNER,
            use_analogies=True,
            analogy_domains=["everyday_objects", "mechanical_systems"]
        )
        
        explanation = explanation_generator.generate_layman_explanation(
            fmri_analysis_result, context
        )
        
        # Should include analogies
        analogy_indicators = ["like", "similar to", "imagine", "think of", "as if"]
        assert any(indicator in explanation.lower() for indicator in analogy_indicators)
    
    @pytest.mark.unit
    def test_visual_description_generation(self, explanation_generator, fmri_analysis_result):
        """Test generation of visual descriptions"""
        visual_context = {
            "brain_maps": ["activation_map.nii.gz", "statistical_map.nii.gz"],
            "plots": ["design_matrix.png", "motion_parameters.png"],
            "overlays": "MNI152_template"
        }
        
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            include_visual_descriptions=True,
            visual_context=visual_context
        )
        
        explanation = explanation_generator.generate_explanation(fmri_analysis_result, context)
        
        # Should include visual descriptions
        visual_terms = ["map", "overlay", "visualization", "plot", "image"]
        assert any(term in explanation.explanation.lower() for term in visual_terms)
    
    @pytest.mark.unit
    def test_limitation_identification(self, explanation_generator, fmri_analysis_result):
        """Test identification and explanation of study limitations"""
        # Add some limitations to the result
        limited_result = fmri_analysis_result.copy()
        limited_result.update({
            "sample_size_issues": True,
            "motion_artifacts": "moderate",
            "scanner_issues": ["signal_dropout_in_orbitofrontal"],
            "design_limitations": ["short_task_duration", "no_control_condition"]
        })
        
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            include_limitations=True
        )
        
        explanation = explanation_generator.generate_explanation(limited_result, context)
        
        # Should mention limitations
        limitation_terms = ["limitation", "caution", "artifact", "dropout", "small sample"]
        assert any(term in explanation.explanation.lower() for term in limitation_terms)
        
        # Structured explanation should have limitations section
        structured = explanation_generator.generate_structured_explanation(limited_result, context)
        assert "limitations" in structured
        assert len(structured["limitations"]) > 0
    
    @pytest.mark.unit
    def test_next_steps_recommendations(self, explanation_generator, fmri_analysis_result):
        """Test generation of next steps recommendations"""
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            include_recommendations=True,
            research_context="exploratory_study"
        )
        
        explanation = explanation_generator.generate_explanation(fmri_analysis_result, context)
        
        # Should include recommendations
        recommendation_terms = ["next", "future", "recommend", "suggest", "follow-up"]
        assert any(term in explanation.explanation.lower() for term in recommendation_terms)
        
        # Structured explanation should have next_steps section
        structured = explanation_generator.generate_structured_explanation(fmri_analysis_result, context)
        assert "next_steps" in structured
        assert len(structured["next_steps"]) > 0
    
    @pytest.mark.unit
    def test_error_explanation_handling(self, explanation_generator):
        """Test handling of analysis errors in explanations"""
        error_result = {
            "analysis_type": "GLM",
            "status": "failed",
            "error_type": "ConvergenceError",
            "error_message": "Model failed to converge after 1000 iterations",
            "partial_results": {
                "completed_subjects": 15,
                "total_subjects": 24
            },
            "suggested_solutions": [
                "Increase iteration limit",
                "Check design matrix",
                "Remove problematic subjects"
            ]
        }
        
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            error_handling=True
        )
        
        explanation = explanation_generator.generate_error_explanation(error_result, context)
        
        assert isinstance(explanation, str)
        assert len(explanation) > 0
        
        # Should explain the error
        assert "convergence" in explanation.lower()
        assert "failed" in explanation.lower()
        
        # Should include suggestions
        assert any(solution.lower() in explanation.lower() 
                  for solution in error_result["suggested_solutions"])


class TestMethodologyExplainer:
    """Test suite for MethodologyExplainer"""
    
    @pytest.fixture
    def methodology_explainer(self):
        return MethodologyExplainer()
    
    @pytest.mark.unit
    def test_preprocessing_explanation(self, methodology_explainer):
        """Test explanation of preprocessing steps"""
        preprocessing_info = {
            "software": "fMRIPrep",
            "steps": ["skull_stripping", "motion_correction", "slice_timing", "normalization"],
            "parameters": {"smoothing_fwhm": 6.0, "high_pass_filter": 128}
        }
        
        explanation = methodology_explainer.explain_preprocessing(
            preprocessing_info, ExpertiseLevel.INTERMEDIATE
        )
        
        assert isinstance(explanation, str)
        assert len(explanation) > 0
        assert "fMRIPrep" in explanation
        assert any(step in explanation.lower() for step in preprocessing_info["steps"])
    
    @pytest.mark.unit
    def test_statistical_model_explanation(self, methodology_explainer):
        """Test explanation of statistical models"""
        model_info = {
            "type": "GLM",
            "design_matrix": "blocked_design",
            "hrf_model": "canonical_hrf",
            "contrasts": ["task_vs_baseline", "parametric_modulation"]
        }
        
        explanation = methodology_explainer.explain_statistical_model(
            model_info, ExpertiseLevel.INTERMEDIATE
        )
        
        assert isinstance(explanation, str)
        assert "GLM" in explanation
        assert "design" in explanation.lower()
        assert "HRF" in explanation or "hemodynamic" in explanation.lower()


class TestStatisticalInterpreter:
    """Test suite for StatisticalInterpreter"""
    
    @pytest.fixture
    def statistical_interpreter(self):
        return StatisticalInterpreter()
    
    @pytest.mark.unit
    def test_p_value_interpretation(self, statistical_interpreter):
        """Test interpretation of p-values"""
        # Highly significant p-value
        high_sig_interpretation = statistical_interpreter.interpret_p_values(
            0.0001, ExpertiseLevel.INTERMEDIATE
        )
        
        assert isinstance(high_sig_interpretation, str)
        assert "significant" in high_sig_interpretation.lower()
        assert "strong" in high_sig_interpretation.lower() or "highly" in high_sig_interpretation.lower()
        
        # Marginally significant p-value
        marginal_interpretation = statistical_interpreter.interpret_p_values(
            0.048, ExpertiseLevel.INTERMEDIATE
        )
        
        assert "significant" in marginal_interpretation.lower()
        assert "marginal" in marginal_interpretation.lower() or "borderline" in marginal_interpretation.lower()
    
    @pytest.mark.unit
    def test_effect_size_interpretation(self, statistical_interpreter):
        """Test interpretation of effect sizes"""
        # Large effect size
        large_effect = statistical_interpreter.interpret_effect_sizes(
            {"cohens_d": 0.8, "z_score": 4.2}, ExpertiseLevel.INTERMEDIATE
        )
        
        assert "large" in large_effect.lower() or "strong" in large_effect.lower()
        
        # Small effect size
        small_effect = statistical_interpreter.interpret_effect_sizes(
            {"cohens_d": 0.2, "z_score": 2.1}, ExpertiseLevel.INTERMEDIATE
        )
        
        assert "small" in small_effect.lower() or "modest" in small_effect.lower()
    
    @pytest.mark.unit
    def test_multiple_comparisons_explanation(self, statistical_interpreter):
        """Test explanation of multiple comparisons correction"""
        correction_info = {
            "method": "FWE",
            "n_comparisons": 100000,
            "alpha_corrected": 0.00000005
        }
        
        explanation = statistical_interpreter.interpret_multiple_comparisons(
            correction_info, ExpertiseLevel.BEGINNER
        )
        
        assert isinstance(explanation, str)
        assert "correction" in explanation.lower()
        assert "multiple" in explanation.lower()


class TestClinicalImplicationsGenerator:
    """Test suite for ClinicalImplicationsGenerator"""
    
    @pytest.fixture
    def clinical_implications(self):
        return ClinicalImplicationsGenerator()
    
    @pytest.mark.unit
    def test_implications_generation(self, clinical_implications, fmri_analysis_result):
        """Test generation of clinical implications"""
        implications = clinical_implications.generate_implications(
            fmri_analysis_result, ExpertiseLevel.INTERMEDIATE
        )
        
        assert isinstance(implications, str)
        assert len(implications) > 0
        
        # Should mention clinical relevance
        clinical_terms = ["clinical", "patient", "treatment", "diagnosis", "therapeutic"]
        assert any(term in implications.lower() for term in clinical_terms)


class TestExplanationContext:
    """Test suite for ExplanationContext"""
    
    @pytest.mark.unit
    def test_context_creation(self):
        """Test explanation context creation"""
        context = ExplanationContext(
            expertise_level=ExpertiseLevel.INTERMEDIATE,
            domain_focus=["cognitive", "methods"],
            include_methodology=True,
            include_statistics=True,
            use_analogies=False
        )
        
        assert context.expertise_level == ExpertiseLevel.INTERMEDIATE
        assert "cognitive" in context.domain_focus
        assert "methods" in context.domain_focus
        assert context.include_methodology is True
        assert context.include_statistics is True
        assert context.use_analogies is False
    
    @pytest.mark.unit
    def test_context_defaults(self):
        """Test default values in explanation context"""
        context = ExplanationContext(expertise_level=ExpertiseLevel.INTERMEDIATE)
        
        # Should have sensible defaults
        assert isinstance(context.domain_focus, list)
        assert isinstance(context.include_methodology, bool)
        assert isinstance(context.include_statistics, bool)


# Integration tests
@pytest.mark.integration
class TestExplanationGeneratorIntegration:
    """Integration tests for explanation generator"""
    
    def test_full_explanation_pipeline(self):
        """Test complete explanation generation pipeline"""
        # Would test the full pipeline with real data
        pass
    
    def test_cross_domain_explanations(self):
        """Test explanations across different domains"""
        # Would test explanations for different types of analyses
        pass
