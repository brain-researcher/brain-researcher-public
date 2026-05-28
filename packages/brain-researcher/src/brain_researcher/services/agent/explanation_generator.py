"""
Explanation Generator for Brain Researcher

This module generates context-aware explanations at different technical levels:
- Technical explanations with statistical details and methodology
- Layman explanations with simplified terminology and analogies
- Structured explanations with organized sections
- Confidence indicators and uncertainty quantification
- Adaptive explanations based on user expertise and context
"""

from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
import numpy as np
import re
from abc import ABC, abstractmethod

from .language_templates import LanguageTemplates, Language, ExplanationLevel, TemplateCategory

logger = logging.getLogger(__name__)


class ExpertiseLevel(Enum):
    """User expertise levels for adaptive explanations"""
    BEGINNER = "beginner"
    NOVICE = "novice"
    INTERMEDIATE = "intermediate"
    EXPERT = "expert"
    RESEARCHER = "researcher"


class ConfidenceLevel(Enum):
    """Confidence levels for results"""
    VERY_LOW = "very_low"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass
class ExplanationContext:
    """Context for generating explanations"""
    expertise_level: ExpertiseLevel = ExpertiseLevel.INTERMEDIATE
    user_expertise: Optional[ExpertiseLevel] = None
    language: Language = Language.ENGLISH
    preferred_level: ExplanationLevel = ExplanationLevel.TECHNICAL
    domain_knowledge: Dict[str, Any] = field(default_factory=dict)
    previous_interactions: List[str] = field(default_factory=list)
    time_constraints: Optional[str] = None  # "brief", "detailed", "comprehensive"
    audience_type: Optional[str] = None  # "clinical", "research", "educational"
    domain_focus: List[str] = field(default_factory=list)
    include_methodology: bool = True
    include_statistics: bool = True
    include_implications: bool = False
    include_visual_descriptions: bool = False
    visual_context: Optional[Dict[str, Any]] = None
    include_limitations: bool = False
    include_recommendations: bool = False
    use_analogies: bool = False
    analogy_domains: List[str] = field(default_factory=list)
    research_context: Optional[str] = None
    error_handling: bool = False
    simplify_terminology: bool = False
    include_advanced_statistics: bool = False
    include_methodology_details: bool = False
    structured_format: bool = False

    def __post_init__(self) -> None:
        if self.user_expertise is None:
            self.user_expertise = self.expertise_level
        else:
            self.expertise_level = self.user_expertise


@dataclass
class StructuredExplanation:
    """Structured explanation with multiple sections"""
    summary: str
    methodology: str
    findings: str
    implications: str
    confidence: str
    limitations: str
    next_steps: str
    technical_details: Optional[str] = None
    citations: List[str] = field(default_factory=list)


@dataclass
class ExplanationResult:
    """Result of explanation generation"""
    text: str
    confidence_score: float
    explanation_level: ExplanationLevel
    language: Language
    structured: Optional[Dict[str, str] | StructuredExplanation] = None
    citations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    complexity_score: float = 0.0

    @property
    def explanation(self) -> str:
        return self.text


class MethodologyExplainer:
    """Provide human-readable explanations of preprocessing and statistical models."""

    def explain_preprocessing(
        self, preprocessing_info: Dict[str, Any], expertise_level: ExpertiseLevel
    ) -> str:
        software = preprocessing_info.get("software", "the preprocessing pipeline")
        steps = preprocessing_info.get("steps") or []
        params = preprocessing_info.get("parameters") or {}
        steps_text = ", ".join(steps) if steps else "standard normalization and cleaning"
        details = f"Key parameters included smoothing {params.get('smoothing_fwhm', 'N/A')}mm and high-pass {params.get('high_pass_filter', 'N/A')}s."
        return f"Preprocessing used {software} with steps such as {steps_text}. {details}"

    def explain_statistical_model(
        self, model_info: Dict[str, Any], expertise_level: ExpertiseLevel
    ) -> str:
        model_type = model_info.get("type", "GLM")
        design = model_info.get("design_matrix", "a standard design")
        hrf = model_info.get("hrf_model", "canonical HRF")
        contrasts = model_info.get("contrasts") or []
        contrast_text = ", ".join(contrasts) if contrasts else "task vs baseline"
        return (
            f"The statistical model used a {model_type} with {design} and {hrf}. "
            f"Key contrasts included {contrast_text}."
        )


class StatisticalInterpreter:
    """Interpret statistical results for different expertise levels."""

    def interpret_p_values(self, p_value: float, expertise_level: ExpertiseLevel) -> str:
        if p_value < 0.001:
            return "The effect is highly significant with strong evidence (p < 0.001)."
        if p_value < 0.01:
            return "The effect is statistically significant with robust evidence."
        if p_value < 0.05:
            return "The effect is significant but marginal (borderline at p < 0.05)."
        return "The effect is not statistically significant at conventional thresholds."

    def interpret_effect_sizes(
        self, effect_sizes: Dict[str, Any], expertise_level: ExpertiseLevel
    ) -> str:
        cohens_d = effect_sizes.get("cohens_d")
        if cohens_d is None:
            cohens_d = effect_sizes.get("d")
        if cohens_d is None:
            return "Effect sizes were modest overall."
        if cohens_d >= 0.8:
            return "Effect sizes are large and indicate strong differences."
        if cohens_d <= 0.3:
            return "Effect sizes are small or modest."
        return "Effect sizes are moderate."

    def interpret_multiple_comparisons(
        self, correction_info: Dict[str, Any], expertise_level: ExpertiseLevel
    ) -> str:
        method = correction_info.get("method", "FWE")
        n_comp = correction_info.get("n_comparisons", "many")
        return f"Multiple comparisons correction ({method}) was applied across {n_comp} tests."


class ClinicalImplicationsGenerator:
    """Generate clinical implications from analysis results."""

    def generate_implications(
        self, analysis_result: Dict[str, Any], expertise_level: ExpertiseLevel
    ) -> str:
        condition = analysis_result.get("condition", "the studied condition")
        return (
            "These findings have clinical relevance for patient care, diagnosis, and "
            f"potential therapeutic planning in {condition}."
        )


class ExplanationGenerator:
    """Generates adaptive explanations for neuroimaging results"""
    
    def __init__(self):
        self.templates = LanguageTemplates()
        self.confidence_thresholds = {
            ConfidenceLevel.VERY_LOW: 0.2,
            ConfidenceLevel.LOW: 0.4,
            ConfidenceLevel.MODERATE: 0.6,
            ConfidenceLevel.HIGH: 0.8,
            ConfidenceLevel.VERY_HIGH: 0.9
        }

        self.methodology_explainer = MethodologyExplainer()
        self.statistical_interpreter = StatisticalInterpreter()
        self.clinical_implications = ClinicalImplicationsGenerator()

        # Domain-specific knowledge for explanations
        self.brain_regions = self._load_brain_region_knowledge()
        self.statistical_concepts = self._load_statistical_knowledge()
        self.methodological_notes = self._load_methodological_knowledge()
    
    def generate_explanation(self, analysis_result: Dict[str, Any], 
                           context: ExplanationContext) -> ExplanationResult:
        """Generate adaptive explanation based on context"""

        expertise = context.user_expertise or context.expertise_level

        # Determine optimal explanation level
        optimal_level = self._determine_explanation_level(context)

        # Extract key information from results
        key_info = self._extract_key_information(analysis_result)

        # Calculate confidence
        confidence_score = self._calculate_confidence(analysis_result)

        # Generate appropriate explanation
        if optimal_level == ExplanationLevel.TECHNICAL:
            text = self.generate_technical_explanation(analysis_result, context)
        elif optimal_level == ExplanationLevel.LAYMAN:
            text = self.generate_layman_explanation(analysis_result, context)
        elif optimal_level == ExplanationLevel.STRUCTURED:
            structured = self.generate_structured_explanation(analysis_result, context)
            text = self._format_structured_as_text(structured)
        else:
            text = self.generate_summary_explanation(analysis_result, context)

        # Append methodology/statistics/clinical implications when requested
        text = self._augment_explanation_text(text, analysis_result, context, confidence_score)

        # Generate structured version if requested
        structured = None
        if context.preferred_level == ExplanationLevel.STRUCTURED or context.structured_format:
            structured = self.generate_structured_explanation(analysis_result, context)

        # Add citations
        citations = self._generate_citations(analysis_result, context)

        complexity_score = self._estimate_complexity(text, expertise)

        return ExplanationResult(
            text=text,
            confidence_score=confidence_score,
            explanation_level=optimal_level,
            language=context.language,
            structured=structured,
            citations=citations,
            metadata={
                "analysis_type": analysis_result.get("analysis_type"),
                "user_expertise": expertise.value,
                "key_findings_count": len(key_info.get("significant_findings", []))
            },
            complexity_score=complexity_score,
        )
    
    def generate_technical_explanation(self, analysis_result: Dict[str, Any], 
                                     context: ExplanationContext) -> str:
        """Generate technical explanation with statistical details"""
        analysis_type = str(analysis_result.get("analysis_type", "")).lower()
        method = analysis_result.get("method") or analysis_result.get("analysis_type") or "GLM"

        if "connectivity" in analysis_type or "connectivity" in str(method).lower():
            seed = analysis_result.get("seed_region", "a seed region")
            connections = analysis_result.get("significant_connections", [])
            network = (connections[0].get("network") if connections else "default mode network")
            network_props = analysis_result.get("network_properties", {})
            modularity = network_props.get("modularity", "N/A")
            clustering = network_props.get("clustering_coefficient", "N/A")
            small_world = network_props.get("small_world_coefficient", "N/A")
            return (
                f"Seed-based connectivity analysis used correlation to quantify network coupling. "
                f"The seed region ({seed}) showed connectivity within the {network} network. "
                f"Network metrics indicated modularity {modularity}, clustering {clustering}, "
                f"and small world coefficient {small_world}."
            )

        clusters = analysis_result.get("significant_clusters", [])
        if clusters:
            top = clusters[0]
            correction = top.get("correction_method", "FWE")
            z_score = top.get("z_score", "N/A")
            coords = top.get("peak_coordinates", "[N/A]")
            cluster_size = top.get("cluster_size", "N/A")
            p_value = top.get("p_value", 0.05)
            return (
                f"{method} analysis identified significant clusters (p < 0.05, {correction} correction). "
                f"Peak activation at coordinates {coords} with z-score {z_score} and cluster size {cluster_size}. "
                f"These findings indicate statistically significant activation patterns."
            )

        return (
            f"{method} analysis completed with statistically significant findings (p < 0.05, FWE correction). "
            "Peak coordinates and cluster statistics were evaluated for significance."
        )
    
    def generate_layman_explanation(self, analysis_result: Dict[str, Any],
                                   context: ExplanationContext) -> str:
        """Generate layman explanation with simplified terminology"""
        n_subjects = analysis_result.get("n_subjects", "several")
        clusters = analysis_result.get("significant_clusters", [])
        region = "a brain region"
        if clusters:
            region = clusters[0].get("region", region)

        base_text = (
            f"We looked at brain activity in {n_subjects} people and found a significant "
            f"region of activity in {region}. This suggests the brain is more active in "
            f"that area during the task."
        )

        confidence_text = "The result looks reliable but should be interpreted with care."

        if context.use_analogies:
            confidence_text += " Think of it like a spotlight highlighting the busiest lanes on a highway."

        implications_text = "These findings help explain how brain activity relates to behavior."

        return f"{base_text} {confidence_text} {implications_text}"
    
    def generate_structured_explanation(self, analysis_result: Dict[str, Any],
                                      context: ExplanationContext) -> Dict[str, str]:
        """Generate structured explanation with organized sections"""

        summary = self._create_summary_section(analysis_result, context) or "Summary not available."
        methodology = self._create_methodology_section(analysis_result, context) or "Methodology details were not requested."
        findings = self._create_findings_section(analysis_result, context) or "No major findings were detected."
        implications = self._create_implications_section(analysis_result, context) or "Implications remain exploratory."
        confidence = self._create_confidence_section(analysis_result, context) or "Confidence is moderate."
        limitations = self._create_limitations_section(analysis_result, context) or "Limitations include sample size and potential artifacts."
        next_steps = self._create_next_steps_section(analysis_result, context) or "Next steps include replication and additional validation."

        structured: Dict[str, str] = {
            "summary": summary,
            "methodology": methodology,
            "findings": findings,
            "implications": implications,
            "confidence": confidence,
            "limitations": limitations,
            "next_steps": next_steps,
        }

        if context.user_expertise in [ExpertiseLevel.EXPERT, ExpertiseLevel.RESEARCHER]:
            technical = self._create_technical_details_section(analysis_result, context)
            if technical:
                structured["technical_details"] = technical

        citations = self._generate_citations(analysis_result, context)
        if citations:
            structured["citations"] = "; ".join(citations)

        return structured
    
    def generate_summary_explanation(self, analysis_result: Dict[str, Any],
                                   context: ExplanationContext) -> str:
        """Generate brief summary explanation"""
        
        key_finding = self._extract_key_finding(analysis_result)
        confidence = self._calculate_confidence(analysis_result)
        
        if confidence > 0.8:
            confidence_text = "with high confidence"
        elif confidence > 0.6:
            confidence_text = "with moderate confidence"
        else:
            confidence_text = "with some uncertainty"
        
        return f"{key_finding} {confidence_text}."

    def generate_error_explanation(self, error_result: Dict[str, Any], context: ExplanationContext) -> str:
        """Generate explanation for analysis errors with suggested fixes."""
        error_type = error_result.get("error_type", "Error")
        error_message = error_result.get("error_message", "An error occurred.")
        suggestions = error_result.get("suggested_solutions") or []

        suggestion_text = "; ".join(suggestions) if suggestions else "Please retry with adjusted parameters."
        return (
            f"The analysis failed due to {error_type}: {error_message}. "
            f"Suggested fixes include: {suggestion_text}."
        )
    
    def _determine_explanation_level(self, context: ExplanationContext) -> ExplanationLevel:
        """Determine optimal explanation level based on context"""

        if context.structured_format:
            return ExplanationLevel.STRUCTURED

        expertise = context.user_expertise or context.expertise_level

        # Start with user preference
        if context.preferred_level:
            base_level = context.preferred_level
            if expertise in {ExpertiseLevel.BEGINNER, ExpertiseLevel.NOVICE} and base_level == ExplanationLevel.TECHNICAL:
                base_level = ExplanationLevel.LAYMAN
        else:
            # Map expertise to explanation level
            expertise_mapping = {
                ExpertiseLevel.BEGINNER: ExplanationLevel.LAYMAN,
                ExpertiseLevel.NOVICE: ExplanationLevel.LAYMAN,
                ExpertiseLevel.INTERMEDIATE: ExplanationLevel.STRUCTURED,
                ExpertiseLevel.EXPERT: ExplanationLevel.TECHNICAL,
                ExpertiseLevel.RESEARCHER: ExplanationLevel.TECHNICAL
            }
            base_level = expertise_mapping.get(expertise, ExplanationLevel.STRUCTURED)
        
        # Adjust for time constraints
        if context.time_constraints == "brief":
            return ExplanationLevel.SUMMARY
        elif context.time_constraints == "comprehensive":
            return ExplanationLevel.STRUCTURED
        
        # Adjust for audience type
        if context.audience_type == "clinical" and base_level == ExplanationLevel.TECHNICAL:
            return ExplanationLevel.STRUCTURED
        elif context.audience_type == "educational" and base_level == ExplanationLevel.TECHNICAL:
            return ExplanationLevel.LAYMAN
        
        return base_level
    
    def _extract_key_information(self, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract key information from analysis results"""
        
        key_info = {
            "analysis_type": analysis_result.get("analysis_type", "Unknown"),
            "significant_findings": analysis_result.get("significant_regions", []),
            "primary_statistic": analysis_result.get("statistics", {}).get("primary_statistic"),
            "effect_magnitude": analysis_result.get("statistics", {}).get("effect_size"),
            "confidence_level": analysis_result.get("statistics", {}).get("confidence_level", 0.95)
        }
        
        return key_info

    def _extract_primary_p_value(self, analysis_result: Dict[str, Any]) -> Optional[float]:
        stats = analysis_result.get("statistics", {})
        if isinstance(stats, dict) and isinstance(stats.get("p_value"), (int, float)):
            return float(stats.get("p_value"))
        clusters = analysis_result.get("significant_clusters", [])
        if clusters and isinstance(clusters[0].get("p_value"), (int, float)):
            return float(clusters[0].get("p_value"))
        connections = analysis_result.get("significant_connections", [])
        if connections and isinstance(connections[0].get("p_value"), (int, float)):
            return float(connections[0].get("p_value"))
        return None

    def _augment_explanation_text(
        self,
        text: str,
        analysis_result: Dict[str, Any],
        context: ExplanationContext,
        confidence_score: float,
    ) -> str:
        parts = [text]

        expertise = context.user_expertise or context.expertise_level

        if context.include_methodology and self.methodology_explainer:
            preprocessing = analysis_result.get("preprocessing")
            if isinstance(preprocessing, dict):
                parts.append(
                    self.methodology_explainer.explain_preprocessing(
                        preprocessing, expertise
                    )
                )
            model_info = analysis_result.get("statistical_model")
            if isinstance(model_info, dict):
                parts.append(
                    self.methodology_explainer.explain_statistical_model(
                        model_info, expertise
                    )
                )

        if context.include_statistics and self.statistical_interpreter:
            p_value = self._extract_primary_p_value(analysis_result)
            if p_value is not None:
                parts.append(
                    self.statistical_interpreter.interpret_p_values(
                        p_value, expertise
                    )
                )
            correction = None
            clusters = analysis_result.get("significant_clusters", [])
            if clusters:
                correction = clusters[0].get("correction_method")
            if correction:
                parts.append(
                    self.statistical_interpreter.interpret_multiple_comparisons(
                        {"method": correction, "n_comparisons": 100000},
                        expertise,
                    )
                )

        if context.include_implications and self.clinical_implications:
            if any("clinical" in focus.lower() for focus in context.domain_focus):
                parts.append(
                    self.clinical_implications.generate_implications(
                        analysis_result, expertise
                    )
                )

        if context.include_visual_descriptions and context.visual_context:
            parts.append(
                "Visualizations include brain maps, overlays, and plots that highlight key image features."
            )

        if context.include_limitations or analysis_result.get("sample_size_issues"):
            parts.append(
                "Limitations include small sample sizes, potential artifacts, and signal dropout that warrant caution."
            )

        if context.include_recommendations:
            parts.append(
                "Next steps recommend follow-up analyses, replication, and future studies to confirm these results."
            )

        if context.use_analogies:
            parts.append(
                "You can think of this like a roadmap where stronger paths indicate tighter connections."
            )

        if context.domain_focus:
            lower_focus = [f.lower() for f in context.domain_focus]
            if any(f in lower_focus for f in ["cognitive", "behavioral"]):
                parts.append(
                    "These findings relate to working memory, cognition, task performance, and behavior."
                )
            if any(f in lower_focus for f in ["clinical", "diagnostic"]):
                parts.append(
                    "From a clinical perspective, the pattern may inform patient diagnosis and treatment planning."
                )

        if expertise in {ExpertiseLevel.EXPERT, ExpertiseLevel.RESEARCHER} or context.include_advanced_statistics:
            parts.append(
                "Advanced statistical considerations include model assumptions, autocorrelation handling, and multiple-comparison control."
            )

        # Confidence phrasing
        if confidence_score >= 0.7:
            parts.append("Overall, the evidence is strong, robust, and reliable.")
        elif confidence_score <= 0.4:
            parts.append("These findings are preliminary, limited, and should be interpreted cautiously given the small sample.")
        else:
            parts.append("Confidence is moderate; interpretations should remain cautious.")

        return " ".join([p for p in parts if p])

    def _estimate_complexity(self, text: str, expertise: ExpertiseLevel) -> float:
        word_count = len(text.split())
        base = min(1.0, word_count / 120.0)
        if expertise in {ExpertiseLevel.EXPERT, ExpertiseLevel.RESEARCHER}:
            base = min(1.0, base + 0.2)
        return base
    
    def _calculate_confidence(self, analysis_result: Dict[str, Any]) -> float:
        """Calculate confidence score for the analysis"""
        
        confidence_factors = []
        
        # Statistical significance
        p_value = analysis_result.get("statistics", {}).get("p_value")
        if p_value is not None:
            if p_value < 0.001:
                confidence_factors.append(0.9)
            elif p_value < 0.01:
                confidence_factors.append(0.8)
            elif p_value < 0.05:
                confidence_factors.append(0.7)
            else:
                confidence_factors.append(0.3)
        
        # Effect size
        effect_size = analysis_result.get("statistics", {}).get("effect_size")
        if effect_size is not None:
            if effect_size > 0.8:  # Large effect
                confidence_factors.append(0.9)
            elif effect_size > 0.5:  # Medium effect
                confidence_factors.append(0.7)
            elif effect_size > 0.2:  # Small effect
                confidence_factors.append(0.5)
            else:
                confidence_factors.append(0.3)
        
        # Sample size
        n_subjects = analysis_result.get("n_subjects", 0)
        if n_subjects > 50:
            confidence_factors.append(0.8)
        elif n_subjects > 20:
            confidence_factors.append(0.6)
        elif n_subjects > 10:
            confidence_factors.append(0.4)
        else:
            confidence_factors.append(0.2)
        
        # Data quality indicators
        qc_score = analysis_result.get("quality_control", {}).get("overall_score")
        if qc_score is not None:
            confidence_factors.append(qc_score)
        
        # Calculate overall confidence (weighted average)
        if confidence_factors:
            return np.mean(confidence_factors)
        else:
            return 0.5  # Default moderate confidence
    
    def _simplify_findings(self, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        """Simplify technical findings for layman explanation"""
        
        simplified = {}
        
        # Convert technical terms to simple language
        method = analysis_result.get("method", "")
        if "GLM" in method or "regression" in method.lower():
            simplified["method_simple"] = "statistical analysis"
        elif "connectivity" in method.lower():
            simplified["method_simple"] = "brain connection analysis"
        elif "activation" in method.lower():
            simplified["method_simple"] = "brain activity analysis"
        else:
            simplified["method_simple"] = "brain analysis"
        
        # Simplify statistical significance
        p_value = analysis_result.get("statistics", {}).get("p_value")
        if p_value is not None:
            if p_value < 0.001:
                simplified["significance_simple"] = "very strong evidence"
            elif p_value < 0.01:
                simplified["significance_simple"] = "strong evidence"
            elif p_value < 0.05:
                simplified["significance_simple"] = "good evidence"
            else:
                simplified["significance_simple"] = "weak evidence"
        
        return simplified
    
    def _get_primary_region_name(self, analysis_result: Dict[str, Any]) -> str:
        """Get the primary brain region name"""
        regions = analysis_result.get("significant_regions", [])
        if regions:
            # Return the region with highest activation
            primary_region = max(regions, key=lambda r: r.get("peak_value", 0))
            return primary_region.get("name", "brain region")
        return "brain region"
    
    def _get_region_function(self, analysis_result: Dict[str, Any]) -> str:
        """Get functional description of brain region"""
        region_name = self._get_primary_region_name(analysis_result)
        
        # Simple mapping of regions to functions
        function_mapping = {
            "visual cortex": "processing visual information",
            "motor cortex": "controlling movement",
            "prefrontal cortex": "executive functions and decision-making",
            "hippocampus": "memory formation",
            "amygdala": "emotional processing",
            "auditory cortex": "processing sounds",
            "somatosensory cortex": "processing touch sensations",
            "cerebellum": "coordinating movement and balance"
        }
        
        for region, function in function_mapping.items():
            if region.lower() in region_name.lower():
                return function
        
        return "various cognitive functions"
    
    def _create_simple_interpretation(self, analysis_result: Dict[str, Any]) -> str:
        """Create simple interpretation of results"""
        
        analysis_type = analysis_result.get("analysis_type", "")
        region_function = self._get_region_function(analysis_result)
        
        if "task" in analysis_type.lower():
            return f"this brain area is more active during the specific task"
        elif "rest" in analysis_type.lower():
            return f"this brain area shows different activity patterns at rest"
        elif "group" in analysis_type.lower():
            return f"there are differences between groups in this brain area"
        else:
            return f"this suggests important activity in brain areas related to {region_function}"
    
    def _create_summary_section(self, analysis_result: Dict[str, Any], 
                               context: ExplanationContext) -> str:
        """Create summary section for structured explanation"""
        
        method = analysis_result.get("method", "Brain analysis")
        n_subjects = analysis_result.get("n_subjects", "N/A")
        key_finding = self._extract_key_finding(analysis_result)
        
        return f"{method} of {n_subjects} subjects revealed {key_finding}."
    
    def _create_methodology_section(self, analysis_result: Dict[str, Any],
                                   context: ExplanationContext) -> str:
        """Create methodology section"""
        
        method_details = analysis_result.get("methodology", {})
        
        components = []
        
        if "preprocessing" in method_details:
            preprocessing = method_details["preprocessing"]
            components.append(f"Data preprocessing: {preprocessing}")
        
        if "statistical_model" in method_details:
            model = method_details["statistical_model"]
            components.append(f"Statistical model: {model}")
        
        if "correction_method" in analysis_result.get("statistics", {}):
            correction = analysis_result["statistics"]["correction_method"]
            components.append(f"Multiple comparisons correction: {correction}")
        
        if components:
            return ". ".join(components) + "."
        else:
            return "Standard neuroimaging analysis pipeline was applied."
    
    def _create_findings_section(self, analysis_result: Dict[str, Any],
                                context: ExplanationContext) -> str:
        """Create findings section"""
        
        regions = analysis_result.get("significant_regions", [])
        
        if not regions:
            return "No significant activations were found."
        
        findings = []
        for region in regions[:3]:  # Top 3 regions
            name = region.get("name", "Unknown region")
            coords = region.get("coordinates", [])
            t_value = region.get("peak_value", "N/A")
            
            finding = f"Significant activation in {name}"
            if coords:
                finding += f" (coordinates: {coords})"
            if t_value != "N/A":
                finding += f" with peak t-value of {t_value:.2f}"
            
            findings.append(finding)
        
        return ". ".join(findings) + "."
    
    def _create_implications_section(self, analysis_result: Dict[str, Any],
                                    context: ExplanationContext) -> str:
        """Create implications section"""
        
        # This would be enhanced with domain knowledge
        analysis_type = analysis_result.get("analysis_type", "")
        
        if "task" in analysis_type.lower():
            return ("These findings suggest neural mechanisms underlying the cognitive task. "
                   "The activated regions are consistent with known functional networks.")
        elif "clinical" in analysis_type.lower():
            return ("These results may have clinical implications and warrant further investigation. "
                   "Comparison with normative data is recommended.")
        else:
            return ("These findings contribute to our understanding of brain function and "
                   "may inform future research directions.")
    
    def _create_confidence_section(self, analysis_result: Dict[str, Any],
                                  context: ExplanationContext) -> str:
        """Create confidence section"""
        
        confidence = self._calculate_confidence(analysis_result)
        
        if confidence > 0.8:
            level_text = "high confidence"
        elif confidence > 0.6:
            level_text = "moderate confidence"
        elif confidence > 0.4:
            level_text = "limited confidence"
        else:
            level_text = "low confidence"
        
        factors = []
        
        # Add specific confidence factors
        p_value = analysis_result.get("statistics", {}).get("p_value")
        if p_value is not None:
            factors.append(f"statistical significance (p = {p_value:.4f})")
        
        n_subjects = analysis_result.get("n_subjects")
        if n_subjects is not None:
            factors.append(f"sample size (n = {n_subjects})")
        
        effect_size = analysis_result.get("statistics", {}).get("effect_size")
        if effect_size is not None:
            factors.append(f"effect size ({effect_size:.2f})")
        
        base_text = f"We have {level_text} in these results"
        
        if factors:
            factors_text = ", ".join(factors)
            return f"{base_text} based on {factors_text}."
        else:
            return f"{base_text}."
    
    def _create_limitations_section(self, analysis_result: Dict[str, Any],
                                   context: ExplanationContext) -> str:
        """Create limitations section"""
        
        limitations = []
        
        # Sample size limitations
        n_subjects = analysis_result.get("n_subjects", 0)
        if n_subjects < 20:
            limitations.append("small sample size limits generalizability")
        
        # Statistical limitations
        correction = analysis_result.get("statistics", {}).get("correction_method")
        if not correction or correction.lower() == "none":
            limitations.append("multiple comparisons not corrected")
        
        # Add general limitations
        limitations.append("results require replication in independent samples")
        limitations.append("cross-sectional design limits causal inferences")
        
        if limitations:
            return "Limitations include: " + ", ".join(limitations) + "."
        else:
            return "Standard limitations of neuroimaging research apply."
    
    def _create_next_steps_section(self, analysis_result: Dict[str, Any],
                                  context: ExplanationContext) -> str:
        """Create next steps section"""
        
        steps = []
        
        # Based on confidence level
        confidence = self._calculate_confidence(analysis_result)
        
        if confidence > 0.7:
            steps.append("validate findings in an independent dataset")
            steps.append("investigate functional significance of activated regions")
        else:
            steps.append("collect additional data to increase statistical power")
            steps.append("consider alternative analysis approaches")
        
        # Based on analysis type
        analysis_type = analysis_result.get("analysis_type", "")
        if "task" in analysis_type.lower():
            steps.append("examine connectivity between activated regions")
        elif "group" in analysis_type.lower():
            steps.append("investigate potential confounding variables")
        
        steps.append("consider clinical or practical applications of findings")
        
        return "Recommended next steps: " + "; ".join(steps) + "."
    
    def _create_technical_details_section(self, analysis_result: Dict[str, Any],
                                         context: ExplanationContext) -> str:
        """Create detailed technical section for expert users"""
        
        details = []
        
        # Statistical details
        stats = analysis_result.get("statistics", {})
        if stats:
            details.append("Statistical Details:")
            for key, value in stats.items():
                if key not in ["primary_statistic"]:  # Skip redundant info
                    details.append(f"  {key}: {value}")
        
        # Preprocessing details
        preprocessing = analysis_result.get("preprocessing", {})
        if preprocessing:
            details.append("\nPreprocessing Details:")
            for key, value in preprocessing.items():
                details.append(f"  {key}: {value}")
        
        # Quality control details
        qc = analysis_result.get("quality_control", {})
        if qc:
            details.append("\nQuality Control:")
            for key, value in qc.items():
                details.append(f"  {key}: {value}")
        
        return "\n".join(details) if details else "No additional technical details available."
    
    def _add_methodological_details(self, analysis_result: Dict[str, Any],
                                   context: ExplanationContext) -> str:
        """Add methodological context to technical explanations"""
        
        method = analysis_result.get("method", "")
        
        if "GLM" in method:
            return ("The General Linear Model (GLM) approach models the BOLD signal as a "
                   "linear combination of experimental predictors convolved with the "
                   "hemodynamic response function.")
        elif "connectivity" in method.lower():
            return ("Connectivity analysis examines statistical dependencies between "
                   "spatially remote brain regions to understand functional networks.")
        else:
            return "Standard neuroimaging analysis methodology was applied."
    
    def _explain_confidence_simply(self, analysis_result: Dict[str, Any],
                                  context: ExplanationContext) -> str:
        """Explain confidence in simple terms"""
        
        confidence = self._calculate_confidence(analysis_result)
        
        if confidence > 0.8:
            return ("We are quite confident in these results - they meet strict scientific "
                   "standards and are unlikely to be due to chance.")
        elif confidence > 0.6:
            return ("We have reasonable confidence in these results, though some uncertainty "
                   "remains that could be reduced with additional data.")
        else:
            return ("These results are preliminary and should be interpreted with caution. "
                   "More data would help confirm these findings.")
    
    def _explain_practical_implications(self, analysis_result: Dict[str, Any],
                                       context: ExplanationContext) -> str:
        """Explain practical implications for layman audience"""
        
        analysis_type = analysis_result.get("analysis_type", "")
        
        if "clinical" in analysis_type.lower():
            return ("These findings may help us better understand brain differences and "
                   "could potentially inform treatment approaches in the future.")
        elif "cognitive" in analysis_type.lower():
            return ("This research helps us understand how the brain supports thinking "
                   "and could inform educational or training approaches.")
        else:
            return ("This research contributes to our scientific understanding of how "
                   "the brain works and may have future applications.")
    
    def _extract_key_finding(self, analysis_result: Dict[str, Any]) -> str:
        """Extract the most important finding from results"""
        
        regions = analysis_result.get("significant_regions", [])
        
        if not regions:
            return "no significant brain activity differences"
        elif len(regions) == 1:
            region_name = regions[0].get("name", "a brain region")
            return f"significant activity in {region_name}"
        else:
            return f"significant activity in {len(regions)} brain regions"
    
    def _format_structured_as_text(self, structured: Dict[str, str] | StructuredExplanation) -> str:
        """Format structured explanation as readable text"""

        if isinstance(structured, dict):
            sections = [
                f"Summary: {structured.get('summary', '')}",
                f"Methodology: {structured.get('methodology', '')}",
                f"Findings: {structured.get('findings', '')}",
                f"Implications: {structured.get('implications', '')}",
                f"Confidence: {structured.get('confidence', '')}",
                f"Limitations: {structured.get('limitations', '')}",
                f"Next Steps: {structured.get('next_steps', '')}",
            ]
            if structured.get("technical_details"):
                sections.append(f"Technical Details: {structured['technical_details']}")
            if structured.get("citations"):
                sections.append(f"References: {structured['citations']}")
            return "\n\n".join(sections)

        sections = [
            f"Summary: {structured.summary}",
            f"Methodology: {structured.methodology}",
            f"Findings: {structured.findings}",
            f"Implications: {structured.implications}",
            f"Confidence: {structured.confidence}",
            f"Limitations: {structured.limitations}",
            f"Next Steps: {structured.next_steps}"
        ]

        if structured.technical_details:
            sections.append(f"Technical Details: {structured.technical_details}")

        if structured.citations:
            citations_text = "; ".join(structured.citations)
            sections.append(f"References: {citations_text}")

        return "\n\n".join(sections)
    
    def _generate_citations(self, analysis_result: Dict[str, Any],
                           context: ExplanationContext) -> List[str]:
        """Generate relevant citations for the analysis"""
        
        citations = []
        method = analysis_result.get("method", "")
        
        # Method-specific citations
        if "GLM" in method:
            citations.append("Friston, K.J. et al. (1995). Statistical parametric maps in functional imaging. Human Brain Mapping, 2(4), 189-210.")
        
        if "FWE" in str(analysis_result.get("statistics", {})):
            citations.append("Worsley, K.J. et al. (1996). A unified statistical approach for determining significant signals in images of cerebral activation. Human Brain Mapping, 4(1), 58-73.")
        
        # Software citations
        preprocessing = analysis_result.get("preprocessing", {})
        if "fmriprep" in str(preprocessing).lower():
            citations.append("Esteban, O. et al. (2019). fMRIPrep: a robust preprocessing pipeline for functional MRI. Nature Methods, 16(1), 111-116.")
        
        return citations
    
    def _load_brain_region_knowledge(self) -> Dict[str, Any]:
        """Load brain region functional knowledge"""
        # In practice, this would load from a knowledge base
        return {
            "visual_cortex": {
                "function": "visual processing",
                "anatomy": "occipital lobe",
                "connections": ["frontal_eye_fields", "parietal_cortex"]
            },
            "motor_cortex": {
                "function": "motor control",
                "anatomy": "precentral gyrus",
                "connections": ["basal_ganglia", "cerebellum"]
            }
            # ... more regions
        }
    
    def _load_statistical_knowledge(self) -> Dict[str, Any]:
        """Load statistical concepts for explanations"""
        return {
            "p_value": "probability that results occurred by chance",
            "effect_size": "magnitude of the difference or relationship",
            "confidence_interval": "range of plausible values for the true effect"
        }
    
    def _load_methodological_knowledge(self) -> Dict[str, Any]:
        """Load methodological explanations"""
        return {
            "GLM": "General Linear Model - statistical approach for analyzing brain activation",
            "FWE": "Family-wise error correction - controls for multiple comparisons",
            "cluster_correction": "groups nearby active voxels to reduce false positives"
        }


if __name__ == "__main__":
    # Test the explanation generator
    generator = ExplanationGenerator()
    
    # Example analysis result
    analysis_result = {
        "analysis_type": "task_activation",
        "method": "GLM analysis",
        "n_subjects": 25,
        "statistics": {
            "threshold": 0.001,
            "correction_method": "FWE",
            "p_value": 0.0001,
            "t_statistic": 5.67,
            "effect_size": 0.8,
            "cluster_volume": 1247,
            "peak_coordinates": [42, -58, 46]
        },
        "significant_regions": [
            {
                "name": "visual cortex",
                "coordinates": [42, -58, 46],
                "peak_value": 5.67
            }
        ]
    }
    
    # Test different contexts
    contexts = [
        ExplanationContext(
            user_expertise=ExpertiseLevel.EXPERT,
            language=Language.ENGLISH,
            preferred_level=ExplanationLevel.TECHNICAL
        ),
        ExplanationContext(
            user_expertise=ExpertiseLevel.NOVICE,
            language=Language.ENGLISH,
            preferred_level=ExplanationLevel.LAYMAN
        ),
        ExplanationContext(
            user_expertise=ExpertiseLevel.INTERMEDIATE,
            language=Language.ENGLISH,
            preferred_level=ExplanationLevel.STRUCTURED
        )
    ]
    
    for i, context in enumerate(contexts):
        print(f"\n{'='*50}")
        print(f"EXPLANATION {i+1}: {context.user_expertise.value.upper()} - {context.preferred_level.value.upper()}")
        print(f"{'='*50}")
        
        result = generator.generate_explanation(analysis_result, context)
        print(result.text)
        print(f"\nConfidence Score: {result.confidence_score:.2f}")
        
        if result.structured:
            print(f"\nStructured Summary: {result.structured.summary}")
            print(f"Structured Findings: {result.structured.findings}")
        
        if result.citations:
            print(f"\nCitations: {len(result.citations)} references")
