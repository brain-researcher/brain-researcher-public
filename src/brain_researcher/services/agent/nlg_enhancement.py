"""
Enhanced Natural Language Generation Engine for Brain Researcher

This module provides comprehensive natural language generation capabilities including:
- Context-aware response generation
- Multi-language and multi-level explanations
- Adaptive content based on user expertise
- Confidence indicators and uncertainty quantification
- Citation integration and reference management
- Real-time explanation optimization
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .explanation_generator import (
    ExpertiseLevel,
    ExplanationContext,
    ExplanationGenerator,
    StructuredExplanation,
)
from .language_templates import (
    ExplanationLevel,
    Language,
    LanguageTemplates,
    TemplateCategory,
)

logger = logging.getLogger(__name__)


class ResponseType(Enum):
    """Types of responses the NLG engine can generate"""

    ANALYSIS_RESULT = "analysis_result"
    ERROR_MESSAGE = "error_message"
    PROGRESS_UPDATE = "progress_update"
    RECOMMENDATION = "recommendation"
    METHODOLOGY_EXPLANATION = "methodology_explanation"
    STATISTICAL_INTERPRETATION = "statistical_interpretation"
    VISUALIZATION_DESCRIPTION = "visualization_description"
    HELP_RESPONSE = "help_response"


class AdaptationStrategy(Enum):
    """Strategies for adapting responses to users"""

    FIXED = "fixed"  # Always use same level
    PROGRESSIVE = "progressive"  # Gradually increase complexity
    ADAPTIVE = "adaptive"  # Adapt based on user feedback
    CONTEXTUAL = "contextual"  # Adapt based on context clues


@dataclass
class UserProfile:
    """User profile for adaptive NLG"""

    user_id: str
    expertise_level: ExpertiseLevel = ExpertiseLevel.INTERMEDIATE
    preferred_language: Language = Language.ENGLISH
    preferred_explanation_level: ExplanationLevel = ExplanationLevel.STRUCTURED
    adaptation_strategy: AdaptationStrategy = AdaptationStrategy.ADAPTIVE

    # Learning preferences
    detailed_methodology: bool = True
    include_citations: bool = True
    visual_descriptions: bool = True
    statistical_details: bool = False

    # Interaction history
    successful_explanations: list[str] = field(default_factory=list)
    feedback_scores: list[float] = field(default_factory=list)
    confusion_patterns: list[str] = field(default_factory=list)

    # Context preferences
    domain_focus: list[str] = field(
        default_factory=list
    )  # ["cognitive", "clinical", "methods"]
    time_preferences: str | None = None  # "brief", "standard", "comprehensive"


@dataclass
class ResponseContext:
    """Context for generating responses"""

    response_type: ResponseType
    user_profile: UserProfile
    session_context: dict[str, Any] = field(default_factory=dict)
    analysis_context: dict[str, Any] = field(default_factory=dict)
    temporal_context: dict[str, Any] = field(default_factory=dict)

    # Previous interactions in session
    previous_responses: list[str] = field(default_factory=list)
    current_complexity_level: float = 0.5  # 0=simple, 1=complex
    user_engagement_level: float = 0.5  # 0=low, 1=high


@dataclass
class NLGResponse:
    """Complete NLG response with metadata"""

    primary_text: str
    alternative_texts: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    explanation_level: ExplanationLevel = ExplanationLevel.STRUCTURED
    language: Language = Language.ENGLISH

    # Structured components
    structured_explanation: StructuredExplanation | None = None
    citations: list[str] = field(default_factory=list)
    visualizations: list[dict[str, Any]] = field(default_factory=list)

    # Metadata
    generation_time: datetime = field(default_factory=datetime.now)
    adaptation_applied: bool = False
    complexity_score: float = 0.5
    estimated_reading_time: int = 0  # seconds

    # Interactive elements
    follow_up_questions: list[str] = field(default_factory=list)
    clarification_options: list[str] = field(default_factory=list)
    related_topics: list[str] = field(default_factory=list)


class MultiLanguageTranslator:
    """Advanced multi-language translation with domain knowledge"""

    def __init__(self):
        self.supported_languages = [
            Language.ENGLISH,
            Language.SPANISH,
            Language.FRENCH,
            Language.GERMAN,
            Language.CHINESE,
        ]
        self.fallback_language = Language.ENGLISH

        # Domain-specific terminology
        self.domain_terms = self._load_domain_terminology()

        # Translation models (in practice, would integrate with translation APIs)
        self.translation_models = {}

    def translate(
        self,
        text: str,
        target_language: Language,
        preserve_technical_terms: bool = True,
    ) -> str:
        """Translate text while preserving domain-specific terminology"""

        if target_language == Language.ENGLISH:
            return text

        # Extract technical terms to preserve
        technical_terms = []
        if preserve_technical_terms:
            technical_terms = self._extract_technical_terms(text)

        # Perform translation (placeholder - would use actual translation service)
        translated_text = self._perform_translation(text, target_language)

        # Restore technical terms
        if technical_terms:
            translated_text = self._restore_technical_terms(
                translated_text, technical_terms, target_language
            )

        return translated_text

    def _load_domain_terminology(self) -> dict[Language, dict[str, str]]:
        """Load domain-specific terminology mappings"""
        return {
            Language.SPANISH: {
                "activation": "activación",
                "connectivity": "conectividad",
                "preprocessing": "preprocesamiento",
                "statistical significance": "significancia estadística",
                "false discovery rate": "tasa de falsos descubrimientos",
            },
            Language.FRENCH: {
                "activation": "activation",
                "connectivity": "connectivité",
                "preprocessing": "prétraitement",
                "statistical significance": "significativité statistique",
                "false discovery rate": "taux de fausses découvertes",
            },
            Language.GERMAN: {
                "activation": "Aktivierung",
                "connectivity": "Konnektivität",
                "preprocessing": "Vorverarbeitung",
                "statistical significance": "statistische Signifikanz",
                "false discovery rate": "falsche Entdeckungsrate",
            },
            Language.CHINESE: {
                "activation": "激活",
                "connectivity": "连接",
                "preprocessing": "预处理",
                "statistical significance": "统计显著性",
                "false discovery rate": "错误发现率",
            },
        }

    def _extract_technical_terms(self, text: str) -> list[str]:
        """Extract technical terms that should be preserved"""
        # Pattern matching for common neuroimaging terms
        technical_patterns = [
            r"\bp\s*[<>=]\s*\d+\.?\d*",  # p-values
            r"\bt\s*=\s*\d+\.?\d*",  # t-statistics
            r"\bFWE\b",
            r"\bFDR\b",  # correction methods
            r"\bGLM\b",
            r"\bICA\b",  # analysis methods
            r"\bBOLD\b",
            r"\bfMRI\b",  # imaging terms
            r"\b\w+\s*cortex\b",  # brain regions
        ]

        terms = []
        for pattern in technical_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            terms.extend(matches)

        return terms

    def _perform_translation(self, text: str, target_language: Language) -> str:
        """Perform actual translation (placeholder implementation)"""
        # In practice, this would call a translation API like Google Translate,
        # Azure Translator, or a specialized scientific translation service

        # For now, return original text with language marker
        return f"[{target_language.value}] {text}"

    def _restore_technical_terms(
        self,
        translated_text: str,
        technical_terms: list[str],
        target_language: Language,
    ) -> str:
        """Restore technical terms in translated text"""
        # Simple placeholder - would need sophisticated term restoration
        for term in technical_terms:
            # Keep technical terms in original form
            translated_text = translated_text.replace(f"[TRANSLATED_{term}]", term)

        return translated_text


class EnhancedNLGEngine:
    """Main enhanced NLG engine with adaptive capabilities"""

    def __init__(self, llm_client=None):
        self.templates = LanguageTemplates()
        self.explanation_generator = ExplanationGenerator()
        self.translator = MultiLanguageTranslator()

        # LLM integration for dynamic generation
        self.llm_client = llm_client

        # User profiles and adaptation
        self.user_profiles: dict[str, UserProfile] = {}
        self.adaptation_engine = AdaptationEngine()

        # Response optimization
        self.response_optimizer = ResponseOptimizer()
        self.quality_assessor = ResponseQualityAssessor()

        # Cache for improved performance
        self.response_cache: dict[str, NLGResponse] = {}
        self.cache_ttl = 3600  # 1 hour

    async def generate_response(
        self, content: dict[str, Any], context: ResponseContext
    ) -> NLGResponse:
        """Generate comprehensive response with all enhancements"""

        # Check cache first
        cache_key = self._generate_cache_key(content, context)
        cached_response = self._get_cached_response(cache_key)
        if cached_response:
            return cached_response

        # Get or create user profile
        user_profile = self._get_user_profile(context.user_profile.user_id)

        # Adapt context based on user profile and history
        adapted_context = await self.adaptation_engine.adapt_context(
            context, user_profile
        )

        # Generate base response
        base_response = await self._generate_base_response(content, adapted_context)

        # Apply enhancements
        enhanced_response = await self._apply_enhancements(
            base_response, content, adapted_context
        )

        # Optimize response
        optimized_response = await self.response_optimizer.optimize(
            enhanced_response, adapted_context
        )

        # Assess quality
        quality_score = await self.quality_assessor.assess(
            optimized_response, adapted_context
        )
        optimized_response.confidence_score = quality_score

        # Cache response
        self._cache_response(cache_key, optimized_response)

        # Update user profile based on response
        await self._update_user_profile(
            user_profile, optimized_response, adapted_context
        )

        return optimized_response

    async def _generate_base_response(
        self, content: dict[str, Any], context: ResponseContext
    ) -> NLGResponse:
        """Generate base response using templates and explanation generator"""

        # Create explanation context
        explanation_context = ExplanationContext(
            user_expertise=context.user_profile.expertise_level,
            language=context.user_profile.preferred_language,
            preferred_level=context.user_profile.preferred_explanation_level,
            domain_knowledge=context.analysis_context,
            time_constraints=context.user_profile.time_preferences,
        )

        # Generate explanation
        if context.response_type == ResponseType.ANALYSIS_RESULT:
            explanation_result = self.explanation_generator.generate_explanation(
                content, explanation_context
            )

            primary_text = explanation_result.text
            structured = explanation_result.structured
            citations = explanation_result.citations
            confidence = explanation_result.confidence_score

        else:
            # Use templates for other response types
            template_category = self._map_response_type_to_template(
                context.response_type
            )
            primary_text = self.templates.format_template(
                template_category,
                content,
                context.user_profile.preferred_language,
                context.user_profile.preferred_explanation_level,
            )
            structured = None
            citations = []
            confidence = 0.8  # Default confidence for template-based responses

        # Create base response
        response = NLGResponse(
            primary_text=primary_text or "Response generation failed",
            confidence_score=confidence,
            explanation_level=context.user_profile.preferred_explanation_level,
            language=context.user_profile.preferred_language,
            structured_explanation=structured,
            citations=citations,
        )

        return response

    async def _apply_enhancements(
        self,
        base_response: NLGResponse,
        content: dict[str, Any],
        context: ResponseContext,
    ) -> NLGResponse:
        """Apply various enhancements to the base response"""

        enhanced_response = base_response

        # Multi-language translation if needed
        if context.user_profile.preferred_language != Language.ENGLISH:
            enhanced_response.primary_text = self.translator.translate(
                enhanced_response.primary_text, context.user_profile.preferred_language
            )

        # Generate alternative explanations
        enhanced_response.alternative_texts = await self._generate_alternatives(
            base_response, content, context
        )

        # Add interactive elements
        enhanced_response.follow_up_questions = self._generate_follow_up_questions(
            content, context
        )
        enhanced_response.clarification_options = self._generate_clarification_options(
            content, context
        )
        enhanced_response.related_topics = self._generate_related_topics(
            content, context
        )

        # Add visualizations if applicable
        enhanced_response.visualizations = self._generate_visualization_descriptions(
            content, context
        )

        # Calculate complexity and reading time
        enhanced_response.complexity_score = self._calculate_complexity(
            enhanced_response.primary_text
        )
        enhanced_response.estimated_reading_time = self._estimate_reading_time(
            enhanced_response.primary_text
        )

        return enhanced_response

    async def _generate_alternatives(
        self,
        base_response: NLGResponse,
        content: dict[str, Any],
        context: ResponseContext,
    ) -> list[str]:
        """Generate alternative explanations at different levels"""

        alternatives = []
        current_level = context.user_profile.preferred_explanation_level

        # Generate explanation at different levels
        other_levels = [level for level in ExplanationLevel if level != current_level]

        for level in other_levels[:2]:  # Limit to 2 alternatives
            alt_context = ExplanationContext(
                user_expertise=context.user_profile.expertise_level,
                language=context.user_profile.preferred_language,
                preferred_level=level,
                domain_knowledge=context.analysis_context,
            )

            if context.response_type == ResponseType.ANALYSIS_RESULT:
                alt_result = self.explanation_generator.generate_explanation(
                    content, alt_context
                )
                alternatives.append(alt_result.text)
            else:
                template_category = self._map_response_type_to_template(
                    context.response_type
                )
                alt_text = self.templates.format_template(
                    template_category,
                    content,
                    context.user_profile.preferred_language,
                    level,
                )
                if alt_text:
                    alternatives.append(alt_text)

        return alternatives

    def _generate_follow_up_questions(
        self, content: dict[str, Any], context: ResponseContext
    ) -> list[str]:
        """Generate relevant follow-up questions"""

        questions = []

        if context.response_type == ResponseType.ANALYSIS_RESULT:
            questions.extend(
                [
                    "Would you like me to explain the methodology in more detail?",
                    "Are you interested in seeing visualizations of these results?",
                    "Would you like to know about the clinical significance of these findings?",
                ]
            )
        elif context.response_type == ResponseType.ERROR_MESSAGE:
            questions.extend(
                [
                    "Would you like suggestions for fixing this issue?",
                    "Do you need help understanding what went wrong?",
                    "Should I recommend alternative approaches?",
                ]
            )
        elif context.response_type == ResponseType.PROGRESS_UPDATE:
            questions.extend(
                [
                    "Would you like more details about the current processing step?",
                    "Are you interested in estimated completion time?",
                    "Do you want to see intermediate results?",
                ]
            )

        # Add expertise-level appropriate questions
        if context.user_profile.expertise_level == ExpertiseLevel.EXPERT:
            questions.extend(
                [
                    "Would you like to see the raw statistical output?",
                    "Do you want to explore the parameter sensitivity?",
                ]
            )
        elif context.user_profile.expertise_level == ExpertiseLevel.NOVICE:
            questions.extend(
                [
                    "Would you like me to explain any technical terms?",
                    "Do you need background information on this analysis type?",
                ]
            )

        return questions[:3]  # Limit to 3 questions

    def _generate_clarification_options(
        self, content: dict[str, Any], context: ResponseContext
    ) -> list[str]:
        """Generate clarification options for ambiguous results"""

        options = []

        # Check for ambiguous or uncertain results
        if context.response_type == ResponseType.ANALYSIS_RESULT:
            stats = content.get("statistics", {})
            p_value = stats.get("p_value", 1.0)

            if 0.05 < p_value < 0.1:
                options.append("Explain what 'marginally significant' means")

            if stats.get("effect_size", 0) < 0.3:
                options.append("Discuss the practical significance of small effects")

            if content.get("n_subjects", 0) < 20:
                options.append("Explain limitations due to small sample size")

        # General clarification options
        options.extend(
            [
                "Simplify the explanation",
                "Provide more technical detail",
                "Focus on practical implications",
            ]
        )

        return options[:3]

    def _generate_related_topics(
        self, content: dict[str, Any], context: ResponseContext
    ) -> list[str]:
        """Generate related topics for further exploration"""

        topics = []

        if context.response_type == ResponseType.ANALYSIS_RESULT:
            method = content.get("method", "")

            if "GLM" in method:
                topics.extend(
                    [
                        "Multiple comparison correction methods",
                        "Effect size interpretation",
                        "Power analysis for fMRI studies",
                    ]
                )
            elif "connectivity" in method.lower():
                topics.extend(
                    [
                        "Network analysis approaches",
                        "Dynamic connectivity",
                        "Graph theory metrics",
                    ]
                )

        # Add domain-specific topics based on user profile
        if "cognitive" in context.user_profile.domain_focus:
            topics.extend(
                [
                    "Cognitive task design",
                    "Behavioral correlations",
                    "Individual differences",
                ]
            )

        if "clinical" in context.user_profile.domain_focus:
            topics.extend(
                [
                    "Clinical applications",
                    "Biomarker development",
                    "Diagnostic accuracy",
                ]
            )

        return topics[:4]

    def _generate_visualization_descriptions(
        self, content: dict[str, Any], context: ResponseContext
    ) -> list[dict[str, Any]]:
        """Generate descriptions for relevant visualizations"""

        visualizations = []

        if (
            context.response_type == ResponseType.ANALYSIS_RESULT
            and context.user_profile.visual_descriptions
        ):

            # Statistical map visualization
            if "significant_regions" in content:
                visualizations.append(
                    {
                        "type": "statistical_map",
                        "description": "Brain activation map showing significant clusters",
                        "data_source": "statistical_results",
                        "recommended": True,
                    }
                )

            # Connectivity visualization
            if "connectivity" in str(content.get("method", "")).lower():
                visualizations.append(
                    {
                        "type": "connectivity_matrix",
                        "description": "Network connectivity visualization",
                        "data_source": "connectivity_matrix",
                        "recommended": True,
                    }
                )

            # Time series plot
            if "time_series" in content:
                visualizations.append(
                    {
                        "type": "time_series",
                        "description": "Signal time course visualization",
                        "data_source": "time_series_data",
                        "recommended": False,
                    }
                )

        return visualizations

    def _calculate_complexity(self, text: str) -> float:
        """Calculate text complexity score (0=simple, 1=complex)"""

        complexity_factors = []

        # Sentence length
        sentences = text.split(".")
        avg_sentence_length = sum(len(s.split()) for s in sentences) / len(sentences)
        complexity_factors.append(min(avg_sentence_length / 20, 1.0))

        # Technical term density
        technical_terms = [
            "statistical",
            "significance",
            "correlation",
            "regression",
            "activation",
            "connectivity",
            "preprocessing",
            "threshold",
        ]
        term_count = sum(1 for term in technical_terms if term.lower() in text.lower())
        term_density = term_count / len(text.split()) * 100
        complexity_factors.append(min(term_density / 5, 1.0))

        # Statistical notation
        stat_notation = len(re.findall(r"[pt]\s*[<>=]\s*\d+\.?\d*", text))
        complexity_factors.append(min(stat_notation / 3, 1.0))

        return sum(complexity_factors) / len(complexity_factors)

    def _estimate_reading_time(self, text: str) -> int:
        """Estimate reading time in seconds (assuming 200 WPM)"""
        word_count = len(text.split())
        return int((word_count / 200) * 60)  # 200 words per minute

    def _map_response_type_to_template(
        self, response_type: ResponseType
    ) -> TemplateCategory:
        """Map response type to template category"""
        mapping = {
            ResponseType.ANALYSIS_RESULT: TemplateCategory.ANALYSIS_COMPLETE,
            ResponseType.ERROR_MESSAGE: TemplateCategory.ERROR_OCCURRED,
            ResponseType.PROGRESS_UPDATE: TemplateCategory.PROGRESS_UPDATE,
            ResponseType.STATISTICAL_INTERPRETATION: TemplateCategory.STATISTICAL_RESULTS,
            ResponseType.METHODOLOGY_EXPLANATION: TemplateCategory.METHODOLOGY,
        }
        return mapping.get(response_type, TemplateCategory.ANALYSIS_COMPLETE)

    def _get_user_profile(self, user_id: str) -> UserProfile:
        """Get or create user profile"""
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = UserProfile(user_id=user_id)
        return self.user_profiles[user_id]

    def _generate_cache_key(
        self, content: dict[str, Any], context: ResponseContext
    ) -> str:
        """Generate cache key for response"""
        key_components = [
            str(hash(json.dumps(content, sort_keys=True))),
            context.response_type.value,
            context.user_profile.preferred_language.value,
            context.user_profile.preferred_explanation_level.value,
            str(context.current_complexity_level),
        ]
        return "_".join(key_components)

    def _get_cached_response(self, cache_key: str) -> NLGResponse | None:
        """Get cached response if available and valid"""
        if cache_key in self.response_cache:
            cached = self.response_cache[cache_key]
            # Check if cache is still valid (simple TTL check)
            if (datetime.now() - cached.generation_time).seconds < self.cache_ttl:
                return cached
        return None

    def _cache_response(self, cache_key: str, response: NLGResponse) -> None:
        """Cache response"""
        self.response_cache[cache_key] = response

    async def _update_user_profile(
        self, profile: UserProfile, response: NLGResponse, context: ResponseContext
    ) -> None:
        """Update user profile based on response and context"""
        # This would incorporate user feedback and interaction patterns
        # For now, just track successful explanations
        profile.successful_explanations.append(response.primary_text[:100])

        # Limit history size
        if len(profile.successful_explanations) > 10:
            profile.successful_explanations = profile.successful_explanations[-10:]


class AdaptationEngine:
    """Engine for adapting responses to user needs"""

    async def adapt_context(
        self, context: ResponseContext, profile: UserProfile
    ) -> ResponseContext:
        """Adapt context based on user profile and interaction history"""

        adapted_context = context

        # Adjust explanation level based on user feedback
        if profile.adaptation_strategy == AdaptationStrategy.ADAPTIVE:
            adapted_context = self._adapt_explanation_level(adapted_context, profile)

        # Adjust complexity based on user engagement
        adapted_context = self._adapt_complexity(adapted_context, profile)

        # Incorporate domain focus
        adapted_context = self._incorporate_domain_focus(adapted_context, profile)

        return adapted_context

    def _adapt_explanation_level(
        self, context: ResponseContext, profile: UserProfile
    ) -> ResponseContext:
        """Adapt explanation level based on user feedback"""

        # Simple adaptation based on feedback scores
        if profile.feedback_scores:
            avg_feedback = sum(profile.feedback_scores) / len(profile.feedback_scores)

            if avg_feedback < 0.3:  # Low satisfaction
                # Try simpler explanation
                if (
                    context.user_profile.preferred_explanation_level
                    == ExplanationLevel.TECHNICAL
                ):
                    context.user_profile.preferred_explanation_level = (
                        ExplanationLevel.STRUCTURED
                    )
                elif (
                    context.user_profile.preferred_explanation_level
                    == ExplanationLevel.STRUCTURED
                ):
                    context.user_profile.preferred_explanation_level = (
                        ExplanationLevel.LAYMAN
                    )

        return context

    def _adapt_complexity(
        self, context: ResponseContext, profile: UserProfile
    ) -> ResponseContext:
        """Adapt complexity based on user engagement"""

        # Adjust complexity based on confusion patterns
        if profile.confusion_patterns:
            context.current_complexity_level *= 0.8  # Reduce complexity

        return context

    def _incorporate_domain_focus(
        self, context: ResponseContext, profile: UserProfile
    ) -> ResponseContext:
        """Incorporate user's domain focus into context"""

        if profile.domain_focus:
            context.analysis_context["domain_focus"] = profile.domain_focus

        return context


class ResponseOptimizer:
    """Optimizes responses for clarity and effectiveness"""

    async def optimize(
        self, response: NLGResponse, context: ResponseContext
    ) -> NLGResponse:
        """Optimize response for the given context"""

        optimized = response

        # Optimize for reading time if user prefers brief responses
        if context.user_profile.time_preferences == "brief":
            optimized = self._optimize_for_brevity(optimized)

        # Optimize for clarity
        optimized = self._optimize_for_clarity(optimized)

        # Optimize for engagement
        optimized = self._optimize_for_engagement(optimized, context)

        return optimized

    def _optimize_for_brevity(self, response: NLGResponse) -> NLGResponse:
        """Optimize response for brevity"""

        # Simplify sentences (placeholder implementation)
        text = response.primary_text

        # Remove unnecessary qualifiers
        text = re.sub(r"\b(very|quite|rather|somewhat)\s+", "", text)

        # Shorten technical explanations
        text = re.sub(r"\([^)]*\)", "", text)  # Remove parenthetical remarks

        response.primary_text = text
        return response

    def _optimize_for_clarity(self, response: NLGResponse) -> NLGResponse:
        """Optimize response for clarity"""

        # Add paragraph breaks for long text
        text = response.primary_text
        sentences = text.split(". ")

        if len(sentences) > 4:
            # Group sentences into paragraphs
            paragraphs = []
            current_paragraph = []

            for sentence in sentences:
                current_paragraph.append(sentence)
                if len(current_paragraph) >= 3:
                    paragraphs.append(". ".join(current_paragraph) + ".")
                    current_paragraph = []

            if current_paragraph:
                paragraphs.append(". ".join(current_paragraph))

            response.primary_text = "\n\n".join(paragraphs)

        return response

    def _optimize_for_engagement(
        self, response: NLGResponse, context: ResponseContext
    ) -> NLGResponse:
        """Optimize response for user engagement"""

        # Add engaging elements based on user profile
        if context.user_profile.expertise_level == ExpertiseLevel.NOVICE:
            # Add encouraging language
            if response.confidence_score > 0.8:
                response.primary_text += (
                    "\n\nThese are robust findings that you can be confident in!"
                )

        return response


class ResponseQualityAssessor:
    """Assesses the quality of generated responses"""

    async def assess(self, response: NLGResponse, context: ResponseContext) -> float:
        """Assess response quality and return score (0-1)"""

        quality_factors = []

        # Completeness check
        completeness = self._assess_completeness(response, context)
        quality_factors.append(completeness)

        # Clarity check
        clarity = self._assess_clarity(response)
        quality_factors.append(clarity)

        # Appropriateness check
        appropriateness = self._assess_appropriateness(response, context)
        quality_factors.append(appropriateness)

        # Technical accuracy check
        accuracy = self._assess_technical_accuracy(response, context)
        quality_factors.append(accuracy)

        return sum(quality_factors) / len(quality_factors)

    def _assess_completeness(
        self, response: NLGResponse, context: ResponseContext
    ) -> float:
        """Assess if response addresses all relevant aspects"""

        required_elements = []
        present_elements = []

        if context.response_type == ResponseType.ANALYSIS_RESULT:
            required_elements = ["method", "results", "significance"]
            text_lower = response.primary_text.lower()

            if any(word in text_lower for word in ["analysis", "method", "approach"]):
                present_elements.append("method")
            if any(word in text_lower for word in ["significant", "result", "finding"]):
                present_elements.append("results")
            if any(word in text_lower for word in ["p", "significant", "threshold"]):
                present_elements.append("significance")

        if not required_elements:
            return 1.0

        return len(present_elements) / len(required_elements)

    def _assess_clarity(self, response: NLGResponse) -> float:
        """Assess text clarity"""

        clarity_score = 1.0
        text = response.primary_text

        # Penalize overly long sentences
        sentences = text.split(".")
        avg_sentence_length = sum(len(s.split()) for s in sentences) / len(sentences)
        if avg_sentence_length > 25:
            clarity_score -= 0.2

        # Penalize excessive jargon for non-expert users
        if response.explanation_level == ExplanationLevel.LAYMAN:
            technical_terms = [
                "statistical",
                "correlation",
                "regression",
                "significance",
            ]
            jargon_count = sum(1 for term in technical_terms if term in text.lower())
            if jargon_count > 3:
                clarity_score -= 0.3

        return max(clarity_score, 0.0)

    def _assess_appropriateness(
        self, response: NLGResponse, context: ResponseContext
    ) -> float:
        """Assess appropriateness for user and context"""

        # Check explanation level appropriateness
        if (
            context.user_profile.expertise_level == ExpertiseLevel.NOVICE
            and response.explanation_level == ExplanationLevel.TECHNICAL
        ):
            return 0.5

        if (
            context.user_profile.expertise_level == ExpertiseLevel.EXPERT
            and response.explanation_level == ExplanationLevel.LAYMAN
        ):
            return 0.7

        return 1.0

    def _assess_technical_accuracy(
        self, response: NLGResponse, context: ResponseContext
    ) -> float:
        """Assess technical accuracy (simplified check)"""

        # Basic checks for common errors
        text = response.primary_text.lower()

        # Check for contradictory statements
        if "significant" in text and "not significant" in text:
            return 0.5

        # Check for impossible values
        p_values = re.findall(r"p\s*[<>=]\s*(\d+\.?\d*)", text)
        for p_val in p_values:
            if float(p_val) > 1.0:
                return 0.3

        return 1.0


if __name__ == "__main__":
    # Test the enhanced NLG engine
    import asyncio

    async def test_nlg_engine():
        engine = EnhancedNLGEngine()

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
            },
            "significant_regions": [
                {"name": "visual cortex", "coordinates": [42, -58, 46]}
            ],
        }

        # Test user profiles
        user_profiles = [
            UserProfile(
                user_id="expert_user",
                expertise_level=ExpertiseLevel.EXPERT,
                preferred_explanation_level=ExplanationLevel.TECHNICAL,
            ),
            UserProfile(
                user_id="novice_user",
                expertise_level=ExpertiseLevel.NOVICE,
                preferred_explanation_level=ExplanationLevel.LAYMAN,
            ),
        ]

        for profile in user_profiles:
            context = ResponseContext(
                response_type=ResponseType.ANALYSIS_RESULT, user_profile=profile
            )

            print(f"\n{'='*60}")
            print(f"TESTING: {profile.user_id} ({profile.expertise_level.value})")
            print(f"{'='*60}")

            response = await engine.generate_response(analysis_result, context)

            print(f"Primary Text:\n{response.primary_text}")
            print(f"\nConfidence Score: {response.confidence_score:.2f}")
            print(f"Complexity Score: {response.complexity_score:.2f}")
            print(f"Reading Time: {response.estimated_reading_time} seconds")

            if response.follow_up_questions:
                print("\nFollow-up Questions:")
                for q in response.follow_up_questions:
                    print(f"  - {q}")

            if response.alternative_texts:
                print(
                    f"\nAlternative Explanations: {len(response.alternative_texts)} available"
                )

    # Run test
    asyncio.run(test_nlg_engine())
