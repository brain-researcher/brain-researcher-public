"""
Natural Language Generation API Endpoints

This module provides FastAPI endpoints for the enhanced NLG system including:
- Response generation with multiple explanation levels
- Multi-language support
- User profile management
- Adaptive explanation optimization
- Quality assessment and feedback collection
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any, Union
import asyncio
import logging
from datetime import datetime
import json
import io

# Import NLG components
from ..agent.nlg_enhancement import (
    EnhancedNLGEngine, ResponseType, UserProfile, ResponseContext,
    ExpertiseLevel, AdaptationStrategy, NLGResponse
)
from ..agent.language_templates import Language, ExplanationLevel
from ..agent.explanation_generator import ExplanationContext

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/api/nlg", tags=["Natural Language Generation"])

# Global NLG engine instance (in production, use dependency injection)
nlg_engine = EnhancedNLGEngine()


# Pydantic models for API contracts
class NLGRequest(BaseModel):
    """Request to generate natural language response"""
    content: Dict[str, Any] = Field(..., description="Content to generate response for")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context")

    # Response configuration
    response_type: str = Field(default="analysis_result", description="Type of response")
    explanation_level: str = Field(default="structured", description="Level of explanation")
    language: str = Field(default="en", description="Target language (ISO 639-1)")

    # User configuration
    user_id: Optional[str] = Field(default=None, description="User identifier")
    expertise_level: str = Field(default="intermediate", description="User expertise level")

    # Generation options
    include_alternatives: bool = Field(default=True, description="Include alternative explanations")
    include_citations: bool = Field(default=True, description="Include citations")
    include_visualizations: bool = Field(default=False, description="Include visualization descriptions")
    time_preference: Optional[str] = Field(default=None, description="Time preference: brief, standard, comprehensive")


class ExplanationRequest(BaseModel):
    """Request for detailed explanation generation"""
    analysis_result: Dict[str, Any] = Field(..., description="Analysis result to explain")

    # Explanation configuration
    explanation_levels: List[str] = Field(default=["technical", "layman"], description="Explanation levels to generate")
    languages: List[str] = Field(default=["en"], description="Languages to generate")

    # User context
    user_profile: Optional[Dict[str, Any]] = Field(default=None, description="User profile")
    domain_focus: List[str] = Field(default=[], description="Domain focus areas")

    # Output options
    structured_output: bool = Field(default=True, description="Include structured explanation")
    confidence_analysis: bool = Field(default=True, description="Include confidence analysis")


class UserProfileUpdate(BaseModel):
    """Request to update user profile"""
    user_id: str = Field(..., description="User identifier")

    # Profile updates
    expertise_level: Optional[str] = Field(default=None, description="User expertise level")
    preferred_language: Optional[str] = Field(default=None, description="Preferred language")
    preferred_explanation_level: Optional[str] = Field(default=None, description="Preferred explanation level")
    adaptation_strategy: Optional[str] = Field(default=None, description="Adaptation strategy")

    # Preferences
    detailed_methodology: Optional[bool] = Field(default=None, description="Include detailed methodology")
    include_citations: Optional[bool] = Field(default=None, description="Include citations")
    visual_descriptions: Optional[bool] = Field(default=None, description="Include visual descriptions")
    statistical_details: Optional[bool] = Field(default=None, description="Include statistical details")

    # Domain focus
    domain_focus: Optional[List[str]] = Field(default=None, description="Domain focus areas")
    time_preferences: Optional[str] = Field(default=None, description="Time preferences")


class FeedbackRequest(BaseModel):
    """Request to provide feedback on generated response"""
    response_id: Optional[str] = Field(default=None, description="Response identifier")
    user_id: str = Field(..., description="User identifier")

    # Feedback
    quality_score: float = Field(..., description="Quality score (0-1)", ge=0, le=1)
    clarity_score: float = Field(..., description="Clarity score (0-1)", ge=0, le=1)
    usefulness_score: float = Field(..., description="Usefulness score (0-1)", ge=0, le=1)

    # Optional feedback
    comments: Optional[str] = Field(default=None, description="Additional comments")
    suggested_improvements: Optional[List[str]] = Field(default=None, description="Suggested improvements")
    confusion_points: Optional[List[str]] = Field(default=None, description="Points of confusion")


class TranslationRequest(BaseModel):
    """Request to translate text"""
    text: str = Field(..., description="Text to translate")
    target_language: str = Field(..., description="Target language (ISO 639-1)")
    source_language: str = Field(default="en", description="Source language")
    preserve_technical_terms: bool = Field(default=True, description="Preserve technical terminology")


# Response models
class NLGResponse(BaseModel):
    """Natural language generation response"""
    primary_text: str
    alternative_texts: List[str] = []
    confidence_score: float
    explanation_level: str
    language: str

    # Structured components
    structured_explanation: Optional[Dict[str, str]] = None
    citations: List[str] = []
    visualizations: List[Dict[str, Any]] = []

    # Metadata
    generation_time: str
    complexity_score: float
    estimated_reading_time: int

    # Interactive elements
    follow_up_questions: List[str] = []
    clarification_options: List[str] = []
    related_topics: List[str] = []


class ExplanationResponse(BaseModel):
    """Multi-level explanation response"""
    explanations: Dict[str, Dict[str, str]]  # level -> language -> text
    structured_explanation: Optional[Dict[str, str]] = None
    confidence_analysis: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = {}


class UserProfileResponse(BaseModel):
    """User profile response"""
    user_id: str
    expertise_level: str
    preferred_language: str
    preferred_explanation_level: str
    adaptation_strategy: str

    # Preferences
    detailed_methodology: bool
    include_citations: bool
    visual_descriptions: bool
    statistical_details: bool

    # Learning data
    interaction_count: int
    average_feedback_score: Optional[float]
    successful_explanations_count: int

    # Domain focus
    domain_focus: List[str]
    time_preferences: Optional[str]


class LanguageSupport(BaseModel):
    """Supported languages response"""
    supported_languages: List[Dict[str, str]]
    explanation_levels: List[str]
    response_types: List[str]


# API Endpoints

@router.post("/generate", response_model=NLGResponse)
async def generate_response(request: NLGRequest):
    """Generate natural language response for given content"""
    try:
        # Parse request parameters
        response_type = ResponseType(request.response_type)
        explanation_level = ExplanationLevel(request.explanation_level)
        language = Language(request.language)
        expertise_level = ExpertiseLevel(request.expertise_level)

        # Create user profile
        user_profile = UserProfile(
            user_id=request.user_id or "anonymous",
            expertise_level=expertise_level,
            preferred_language=language,
            preferred_explanation_level=explanation_level,
            include_citations=request.include_citations,
            visual_descriptions=request.include_visualizations,
            time_preferences=request.time_preference
        )

        # Create response context
        context = ResponseContext(
            response_type=response_type,
            user_profile=user_profile,
            analysis_context=request.context or {},
            session_context={}
        )

        # Generate response
        nlg_response = await nlg_engine.generate_response(request.content, context)

        # Convert to API response format
        structured_dict = None
        if nlg_response.structured_explanation:
            structured_dict = {
                "summary": nlg_response.structured_explanation.summary,
                "methodology": nlg_response.structured_explanation.methodology,
                "findings": nlg_response.structured_explanation.findings,
                "implications": nlg_response.structured_explanation.implications,
                "confidence": nlg_response.structured_explanation.confidence,
                "limitations": nlg_response.structured_explanation.limitations,
                "next_steps": nlg_response.structured_explanation.next_steps
            }

        return NLGResponse(
            primary_text=nlg_response.primary_text,
            alternative_texts=nlg_response.alternative_texts if request.include_alternatives else [],
            confidence_score=nlg_response.confidence_score,
            explanation_level=nlg_response.explanation_level.value,
            language=nlg_response.language.value,
            structured_explanation=structured_dict,
            citations=nlg_response.citations,
            visualizations=nlg_response.visualizations,
            generation_time=nlg_response.generation_time.isoformat(),
            complexity_score=nlg_response.complexity_score,
            estimated_reading_time=nlg_response.estimated_reading_time,
            follow_up_questions=nlg_response.follow_up_questions,
            clarification_options=nlg_response.clarification_options,
            related_topics=nlg_response.related_topics
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameter: {str(e)}")
    except Exception as e:
        logger.error(f"Error generating NLG response: {e}")
        raise HTTPException(status_code=500, detail=f"Response generation failed: {str(e)}")


@router.post("/explain", response_model=ExplanationResponse)
async def generate_multi_level_explanation(request: ExplanationRequest):
    """Generate detailed explanations at multiple levels and languages"""
    try:
        explanations = {}

        # Generate explanations for each level and language combination
        for level_str in request.explanation_levels:
            explanation_level = ExplanationLevel(level_str)
            explanations[level_str] = {}

            for lang_str in request.languages:
                language = Language(lang_str)

                # Create explanation context
                context = ExplanationContext(
                    user_expertise=ExpertiseLevel.INTERMEDIATE,  # Default
                    language=language,
                    preferred_level=explanation_level,
                    domain_knowledge={"domain_focus": request.domain_focus}
                )

                # Generate explanation
                explanation_result = nlg_engine.explanation_generator.generate_explanation(
                    request.analysis_result, context
                )

                explanations[level_str][lang_str] = explanation_result.text

        # Generate structured explanation if requested
        structured_explanation = None
        if request.structured_output:
            context = ExplanationContext(
                preferred_level=ExplanationLevel.STRUCTURED,
                domain_knowledge={"domain_focus": request.domain_focus}
            )

            structured = nlg_engine.explanation_generator.generate_structured_explanation(
                request.analysis_result, context
            )

            structured_explanation = {
                "summary": structured.summary,
                "methodology": structured.methodology,
                "findings": structured.findings,
                "implications": structured.implications,
                "confidence": structured.confidence,
                "limitations": structured.limitations,
                "next_steps": structured.next_steps
            }

        # Generate confidence analysis if requested
        confidence_analysis = None
        if request.confidence_analysis:
            confidence_score = nlg_engine.explanation_generator._calculate_confidence(
                request.analysis_result
            )
            confidence_analysis = {
                "overall_confidence": confidence_score,
                "factors": _analyze_confidence_factors(request.analysis_result),
                "recommendations": _get_confidence_recommendations(confidence_score)
            }

        return ExplanationResponse(
            explanations=explanations,
            structured_explanation=structured_explanation,
            confidence_analysis=confidence_analysis,
            metadata={
                "generation_time": datetime.now().isoformat(),
                "levels_generated": len(request.explanation_levels),
                "languages_generated": len(request.languages)
            }
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameter: {str(e)}")
    except Exception as e:
        logger.error(f"Error generating multi-level explanation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/languages", response_model=LanguageSupport)
async def get_language_support():
    """Get information about supported languages and features"""
    try:
        supported_languages = [
            {"code": lang.value, "name": _get_language_name(lang)}
            for lang in Language
        ]

        explanation_levels = [level.value for level in ExplanationLevel]
        response_types = [rtype.value for rtype in ResponseType]

        return LanguageSupport(
            supported_languages=supported_languages,
            explanation_levels=explanation_levels,
            response_types=response_types
        )

    except Exception as e:
        logger.error(f"Error getting language support info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/translate")
async def translate_text(request: TranslationRequest):
    """Translate text to target language"""
    try:
        source_lang = Language(request.source_language)
        target_lang = Language(request.target_language)

        translated_text = nlg_engine.translator.translate(
            request.text, target_lang, request.preserve_technical_terms
        )

        return {
            "translated_text": translated_text,
            "source_language": source_lang.value,
            "target_language": target_lang.value,
            "translation_time": datetime.now().isoformat()
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid language code: {str(e)}")
    except Exception as e:
        logger.error(f"Error translating text: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profile/{user_id}", response_model=UserProfileResponse)
async def get_user_profile(user_id: str):
    """Get user profile for NLG personalization"""
    try:
        profile = nlg_engine._get_user_profile(user_id)

        # Calculate derived metrics
        avg_feedback = None
        if profile.feedback_scores:
            avg_feedback = sum(profile.feedback_scores) / len(profile.feedback_scores)

        return UserProfileResponse(
            user_id=profile.user_id,
            expertise_level=profile.expertise_level.value,
            preferred_language=profile.preferred_language.value,
            preferred_explanation_level=profile.preferred_explanation_level.value,
            adaptation_strategy=profile.adaptation_strategy.value,
            detailed_methodology=profile.detailed_methodology,
            include_citations=profile.include_citations,
            visual_descriptions=profile.visual_descriptions,
            statistical_details=profile.statistical_details,
            interaction_count=len(profile.successful_explanations),
            average_feedback_score=avg_feedback,
            successful_explanations_count=len(profile.successful_explanations),
            domain_focus=profile.domain_focus,
            time_preferences=profile.time_preferences
        )

    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/profile/{user_id}")
async def update_user_profile(user_id: str, request: UserProfileUpdate):
    """Update user profile for NLG personalization"""
    try:
        profile = nlg_engine._get_user_profile(user_id)

        # Update profile fields if provided
        if request.expertise_level:
            profile.expertise_level = ExpertiseLevel(request.expertise_level)
        if request.preferred_language:
            profile.preferred_language = Language(request.preferred_language)
        if request.preferred_explanation_level:
            profile.preferred_explanation_level = ExplanationLevel(request.preferred_explanation_level)
        if request.adaptation_strategy:
            profile.adaptation_strategy = AdaptationStrategy(request.adaptation_strategy)

        # Update preferences
        if request.detailed_methodology is not None:
            profile.detailed_methodology = request.detailed_methodology
        if request.include_citations is not None:
            profile.include_citations = request.include_citations
        if request.visual_descriptions is not None:
            profile.visual_descriptions = request.visual_descriptions
        if request.statistical_details is not None:
            profile.statistical_details = request.statistical_details

        # Update domain focus and time preferences
        if request.domain_focus is not None:
            profile.domain_focus = request.domain_focus
        if request.time_preferences:
            profile.time_preferences = request.time_preferences

        return {"message": "User profile updated successfully", "user_id": user_id}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameter: {str(e)}")
    except Exception as e:
        logger.error(f"Error updating user profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    """Submit feedback on generated response"""
    try:
        profile = nlg_engine._get_user_profile(request.user_id)

        # Calculate overall feedback score
        overall_score = (request.quality_score + request.clarity_score +
                        request.usefulness_score) / 3

        # Update profile with feedback
        profile.feedback_scores.append(overall_score)

        # Limit feedback history
        if len(profile.feedback_scores) > 20:
            profile.feedback_scores = profile.feedback_scores[-20:]

        # Process confusion points
        if request.confusion_points:
            profile.confusion_patterns.extend(request.confusion_points)
            if len(profile.confusion_patterns) > 50:
                profile.confusion_patterns = profile.confusion_patterns[-50:]

        # Log feedback for analysis
        logger.info(f"Feedback received for user {request.user_id}: "
                   f"Quality={request.quality_score}, "
                   f"Clarity={request.clarity_score}, "
                   f"Usefulness={request.usefulness_score}")

        return {
            "message": "Feedback submitted successfully",
            "overall_score": overall_score,
            "user_id": request.user_id
        }

    except Exception as e:
        logger.error(f"Error submitting feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quality/analytics")
async def get_quality_analytics():
    """Get analytics on NLG quality and user satisfaction"""
    try:
        analytics = {}

        # Aggregate user feedback
        all_feedback_scores = []
        user_count = 0

        for user_id, profile in nlg_engine.user_profiles.items():
            if profile.feedback_scores:
                all_feedback_scores.extend(profile.feedback_scores)
                user_count += 1

        if all_feedback_scores:
            analytics["average_user_satisfaction"] = sum(all_feedback_scores) / len(all_feedback_scores)
            analytics["total_feedback_count"] = len(all_feedback_scores)
            analytics["satisfaction_distribution"] = {
                "high": len([s for s in all_feedback_scores if s >= 0.8]),
                "medium": len([s for s in all_feedback_scores if 0.5 <= s < 0.8]),
                "low": len([s for s in all_feedback_scores if s < 0.5])
            }
        else:
            analytics["average_user_satisfaction"] = None
            analytics["total_feedback_count"] = 0
            analytics["satisfaction_distribution"] = {"high": 0, "medium": 0, "low": 0}

        analytics["active_users"] = user_count
        analytics["cache_hit_rate"] = len(nlg_engine.response_cache) / max(user_count, 1)

        # Response type distribution
        response_type_counts = {}
        for response in nlg_engine.response_cache.values():
            # This would need to be tracked properly in the engine
            pass

        analytics["response_types"] = response_type_counts
        analytics["generation_time"] = datetime.now().isoformat()

        return analytics

    except Exception as e:
        logger.error(f"Error getting quality analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize/response")
async def optimize_response_for_user(user_id: str, content: Dict[str, Any]):
    """Optimize response generation for specific user"""
    try:
        profile = nlg_engine._get_user_profile(user_id)

        # Create optimized context
        context = ResponseContext(
            response_type=ResponseType.ANALYSIS_RESULT,
            user_profile=profile
        )

        # Generate multiple response variants
        variants = []

        for level in [ExplanationLevel.TECHNICAL, ExplanationLevel.STRUCTURED, ExplanationLevel.LAYMAN]:
            temp_profile = profile
            temp_profile.preferred_explanation_level = level
            temp_context = context
            temp_context.user_profile = temp_profile

            response = await nlg_engine.generate_response(content, temp_context)

            variants.append({
                "level": level.value,
                "text": response.primary_text,
                "confidence": response.confidence_score,
                "complexity": response.complexity_score,
                "reading_time": response.estimated_reading_time
            })

        # Recommend best variant based on user profile
        recommended_variant = _recommend_best_variant(variants, profile)

        return {
            "recommended_response": recommended_variant,
            "all_variants": variants,
            "user_id": user_id,
            "optimization_time": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error optimizing response: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Helper functions

def _get_language_name(language: Language) -> str:
    """Get human-readable language name"""
    names = {
        Language.ENGLISH: "English",
        Language.SPANISH: "Spanish",
        Language.FRENCH: "French",
        Language.GERMAN: "German",
        Language.CHINESE: "Chinese"
    }
    return names.get(language, language.value)


def _analyze_confidence_factors(analysis_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Analyze factors contributing to confidence"""
    factors = []

    # Statistical significance
    p_value = analysis_result.get("statistics", {}).get("p_value")
    if p_value is not None:
        if p_value < 0.001:
            factors.append({"factor": "statistical_significance", "strength": "very_high", "value": p_value})
        elif p_value < 0.01:
            factors.append({"factor": "statistical_significance", "strength": "high", "value": p_value})
        elif p_value < 0.05:
            factors.append({"factor": "statistical_significance", "strength": "moderate", "value": p_value})
        else:
            factors.append({"factor": "statistical_significance", "strength": "low", "value": p_value})

    # Sample size
    n_subjects = analysis_result.get("n_subjects", 0)
    if n_subjects > 50:
        factors.append({"factor": "sample_size", "strength": "high", "value": n_subjects})
    elif n_subjects > 20:
        factors.append({"factor": "sample_size", "strength": "moderate", "value": n_subjects})
    else:
        factors.append({"factor": "sample_size", "strength": "low", "value": n_subjects})

    # Effect size
    effect_size = analysis_result.get("statistics", {}).get("effect_size")
    if effect_size is not None:
        if effect_size > 0.8:
            factors.append({"factor": "effect_size", "strength": "large", "value": effect_size})
        elif effect_size > 0.5:
            factors.append({"factor": "effect_size", "strength": "medium", "value": effect_size})
        else:
            factors.append({"factor": "effect_size", "strength": "small", "value": effect_size})

    return factors


def _get_confidence_recommendations(confidence_score: float) -> List[str]:
    """Get recommendations based on confidence score"""
    recommendations = []

    if confidence_score < 0.3:
        recommendations.extend([
            "Consider collecting more data to increase statistical power",
            "Review analysis methodology for potential improvements",
            "Interpret results with high caution"
        ])
    elif confidence_score < 0.6:
        recommendations.extend([
            "Results should be replicated in independent samples",
            "Consider additional validation analyses",
            "Report limitations prominently"
        ])
    elif confidence_score < 0.8:
        recommendations.extend([
            "Results are reasonably robust but replication is recommended",
            "Consider investigating clinical or practical significance"
        ])
    else:
        recommendations.extend([
            "Results are highly reliable and suitable for publication",
            "Consider broader implications and applications"
        ])

    return recommendations


def _recommend_best_variant(variants: List[Dict], profile: UserProfile) -> Dict:
    """Recommend the best response variant for user"""
    # Simple scoring based on user preferences
    best_variant = None
    best_score = -1

    for variant in variants:
        score = 0

        # Match preferred explanation level
        if variant["level"] == profile.preferred_explanation_level.value:
            score += 3

        # Prefer higher confidence
        score += variant["confidence"] * 2

        # Consider time preferences
        if profile.time_preferences == "brief" and variant["reading_time"] < 30:
            score += 1
        elif profile.time_preferences == "comprehensive" and variant["reading_time"] > 60:
            score += 1

        # Consider expertise level and complexity match
        if profile.expertise_level == ExpertiseLevel.EXPERT and variant["complexity"] > 0.7:
            score += 1
        elif profile.expertise_level == ExpertiseLevel.NOVICE and variant["complexity"] < 0.4:
            score += 1

        if score > best_score:
            best_score = score
            best_variant = variant

    return best_variant or variants[0]