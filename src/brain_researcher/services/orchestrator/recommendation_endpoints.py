"""
Query Recommendation API Endpoints for Brain Researcher Orchestrator (AGENT-022)

This module provides REST API endpoints for query recommendations, including
similar query suggestions, next-step recommendations, popular analyses,
and personalized recommendations based on user history.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# API Models
class RecommendationRequest(BaseModel):
    """Request model for getting recommendations."""

    query: str = Field(
        ..., description="Current query to base recommendations on", min_length=1
    )
    user_id: str | None = Field(
        default=None, description="Optional user ID for personalization"
    )
    limit: int = Field(
        default=5, description="Maximum number of recommendations", ge=1, le=20
    )
    include_explanations: bool = Field(
        default=True, description="Include explanation text"
    )
    categories: list[str] | None = Field(
        default=None,
        description="Filter by recommendation categories (similar, next_step, popular)",
    )


class RecommendationResponse(BaseModel):
    """Response model for recommendations."""

    query: str = Field(..., description="Recommended query")
    confidence: float = Field(..., description="Confidence score (0-1)", ge=0.0, le=1.0)
    reason: str = Field(..., description="Explanation for the recommendation")
    category: str = Field(..., description="Category of recommendation")
    metadata: dict[str, Any] = Field(..., description="Additional metadata")
    related_patterns: list[str] = Field(
        default_factory=list, description="Related query patterns"
    )
    expected_tools: list[str] = Field(
        default_factory=list, description="Tools likely to be used"
    )
    estimated_time: float | None = Field(
        default=None, description="Estimated execution time in seconds"
    )


class RecommendationsListResponse(BaseModel):
    """Response model for list of recommendations."""

    recommendations: list[RecommendationResponse] = Field(
        ..., description="List of recommendations"
    )
    query: str = Field(..., description="Original query")
    user_id: str | None = Field(default=None, description="User ID if provided")
    generated_at: str = Field(..., description="Generation timestamp")
    total_count: int = Field(..., description="Total number of recommendations")


class PopularQueriesResponse(BaseModel):
    """Response model for popular queries."""

    queries: list[dict[str, Any]] = Field(
        ..., description="Popular queries with counts"
    )
    time_window_days: int = Field(..., description="Time window used for analysis")
    total_queries: int = Field(..., description="Total queries in time window")
    generated_at: str = Field(..., description="Generation timestamp")


class TrendingTopicsResponse(BaseModel):
    """Response model for trending topics."""

    topics: list[dict[str, Any]] = Field(..., description="Trending topics with scores")
    generated_at: str = Field(..., description="Generation timestamp")


class UserRecommendationStats(BaseModel):
    """Response model for user recommendation statistics."""

    user_id: str = Field(..., description="User ID")
    total_queries: int = Field(..., description="Total queries by user")
    preferred_domains: dict[str, float] = Field(..., description="Domain preferences")
    preferred_tools: dict[str, float] = Field(..., description="Tool preferences")
    query_complexity_preference: float = Field(
        ..., description="Complexity preference (0-1)"
    )
    success_rate_by_category: dict[str, float] = Field(
        ..., description="Success rates by category"
    )
    last_updated: str = Field(..., description="Last update timestamp")


class FeedbackRequest(BaseModel):
    """Request model for recommendation feedback."""

    original_query: str = Field(..., description="Original query")
    recommended_query: str = Field(..., description="Query that was recommended")
    helpful: bool = Field(..., description="Whether the recommendation was helpful")
    user_id: str | None = Field(default=None, description="User providing feedback")
    additional_feedback: str | None = Field(
        default=None, description="Additional feedback text"
    )


# Initialize router
recommendation_router = APIRouter(
    prefix="/api/recommendations", tags=["recommendations"]
)


def _get_recommendation_engine():
    """Get recommendation engine instance."""
    try:
        from brain_researcher.services.agent.query_history import (
            create_query_history_store,
        )
        from brain_researcher.services.agent.recommendation_engine import (
            create_recommendation_engine,
        )

        # Create history store
        history_store = create_query_history_store()

        # Create recommendation engine
        engine = create_recommendation_engine(history_store=history_store)

        return engine, history_store

    except Exception as e:
        logger.error(f"Failed to get recommendation engine: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recommendation service unavailable",
        )


@recommendation_router.post("", response_model=RecommendationsListResponse)
async def get_recommendations(
    request: RecommendationRequest,
) -> RecommendationsListResponse:
    """
    Get query recommendations based on current query and user history.

    Args:
        request: Recommendation request parameters

    Returns:
        List of personalized query recommendations

    Raises:
        HTTPException: If recommendation generation fails
    """
    try:
        engine, _ = _get_recommendation_engine()

        # Generate recommendations
        recommendations = engine.recommend(
            query=request.query,
            user_id=request.user_id,
            limit=request.limit,
            include_explanations=request.include_explanations,
        )

        # Filter by categories if specified
        if request.categories:
            recommendations = [
                rec for rec in recommendations if rec.category in request.categories
            ]

        # Convert to response format
        rec_responses = []
        for rec in recommendations:
            rec_response = RecommendationResponse(
                query=rec.query,
                confidence=rec.confidence,
                reason=rec.reason,
                category=rec.category,
                metadata=rec.metadata,
                related_patterns=rec.related_patterns,
                expected_tools=rec.expected_tools,
                estimated_time=rec.estimated_time,
            )
            rec_responses.append(rec_response)

        response = RecommendationsListResponse(
            recommendations=rec_responses,
            query=request.query,
            user_id=request.user_id,
            generated_at=datetime.now().isoformat(),
            total_count=len(rec_responses),
        )

        logger.info(f"Generated {len(rec_responses)} recommendations for query")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Recommendation generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate recommendations",
        )


@recommendation_router.get(
    "/similar/{query}", response_model=list[RecommendationResponse]
)
async def get_similar_queries(
    query: str, limit: int = Query(5, ge=1, le=10), user_id: str | None = Query(None)
) -> list[RecommendationResponse]:
    """
    Get queries similar to the provided query.

    Args:
        query: Query to find similar queries for
        limit: Maximum number of similar queries to return
        user_id: Optional user ID for personalization

    Returns:
        List of similar query recommendations
    """
    try:
        engine, _ = _get_recommendation_engine()

        # Get only similar recommendations
        all_recommendations = engine.recommend(
            query=query, user_id=user_id, limit=limit * 2  # Get more to filter
        )

        # Filter for similar queries only
        similar_recommendations = [
            rec for rec in all_recommendations if rec.category == "similar"
        ][:limit]

        # Convert to response format
        responses = []
        for rec in similar_recommendations:
            response = RecommendationResponse(
                query=rec.query,
                confidence=rec.confidence,
                reason=rec.reason,
                category=rec.category,
                metadata=rec.metadata,
                related_patterns=rec.related_patterns,
                expected_tools=rec.expected_tools,
                estimated_time=rec.estimated_time,
            )
            responses.append(response)

        return responses

    except Exception as e:
        logger.error(f"Failed to get similar queries: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve similar queries",
        )


@recommendation_router.get("/popular", response_model=PopularQueriesResponse)
async def get_popular_queries(
    time_window_days: int = Query(7, ge=1, le=30), limit: int = Query(10, ge=1, le=50)
) -> PopularQueriesResponse:
    """
    Get most popular queries in a time window.

    Args:
        time_window_days: Time window in days for popularity analysis
        limit: Maximum number of popular queries to return

    Returns:
        List of popular queries with usage counts
    """
    try:
        _, history_store = _get_recommendation_engine()

        # Get popular queries from history
        popular_queries = history_store.get_popular_queries(
            time_window_days=time_window_days, limit=limit
        )

        # Format response
        queries_data = []
        for query, count in popular_queries:
            queries_data.append(
                {
                    "query": query,
                    "count": count,
                    "relative_popularity": (
                        count / max(1, popular_queries[0][1]) if popular_queries else 0
                    ),
                }
            )

        response = PopularQueriesResponse(
            queries=queries_data,
            time_window_days=time_window_days,
            total_queries=sum(count for _, count in popular_queries),
            generated_at=datetime.now().isoformat(),
        )

        return response

    except Exception as e:
        logger.error(f"Failed to get popular queries: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve popular queries",
        )


@recommendation_router.get("/trending", response_model=TrendingTopicsResponse)
async def get_trending_topics(
    limit: int = Query(5, ge=1, le=20)
) -> TrendingTopicsResponse:
    """
    Get currently trending analysis topics.

    Args:
        limit: Maximum number of trending topics to return

    Returns:
        List of trending topics with trend scores
    """
    try:
        engine, _ = _get_recommendation_engine()

        # Get trending topics
        trending_topics = engine.get_trending_topics(limit=limit)

        response = TrendingTopicsResponse(
            topics=trending_topics, generated_at=datetime.now().isoformat()
        )

        return response

    except Exception as e:
        logger.error(f"Failed to get trending topics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve trending topics",
        )


@recommendation_router.get(
    "/user/{user_id}/stats", response_model=UserRecommendationStats
)
async def get_user_recommendation_stats(user_id: str) -> UserRecommendationStats:
    """
    Get recommendation statistics and preferences for a user.

    Args:
        user_id: User identifier

    Returns:
        User recommendation statistics and preferences

    Raises:
        HTTPException: If user not found or stats unavailable
    """
    try:
        engine, history_store = _get_recommendation_engine()

        # Get user profile from engine
        if user_id not in engine.user_profiles:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User profile not found: {user_id}",
            )

        profile = engine.user_profiles[user_id]

        # Get additional stats from history
        user_queries = history_store.get_user_queries(user_id, limit=1000)

        stats = UserRecommendationStats(
            user_id=user_id,
            total_queries=len(user_queries),
            preferred_domains=profile.preferred_domains,
            preferred_tools=profile.preferred_tools,
            query_complexity_preference=profile.query_complexity_preference,
            success_rate_by_category=profile.success_rate_by_category,
            last_updated=profile.last_updated.isoformat(),
        )

        return stats

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user stats for {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user statistics",
        )


@recommendation_router.get("/user/{user_id}/patterns")
async def get_user_query_patterns(
    user_id: str, time_window_days: int = Query(30, ge=1, le=90)
) -> dict[str, Any]:
    """
    Get query patterns analysis for a specific user.

    Args:
        user_id: User identifier
        time_window_days: Time window for pattern analysis

    Returns:
        User query patterns and statistics
    """
    try:
        _, history_store = _get_recommendation_engine()

        # Get user query patterns
        patterns = history_store.get_query_patterns(
            user_id=user_id, time_window_days=time_window_days
        )

        if not patterns:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No query patterns found for user: {user_id}",
            )

        # Add metadata
        patterns["user_id"] = user_id
        patterns["time_window_days"] = time_window_days
        patterns["generated_at"] = datetime.now().isoformat()

        return patterns

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user patterns for {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user query patterns",
        )


@recommendation_router.post("/feedback")
async def submit_recommendation_feedback(
    request: FeedbackRequest, background_tasks: BackgroundTasks
) -> dict[str, str]:
    """
    Submit feedback on a recommendation.

    Args:
        request: Feedback request with recommendation details
        background_tasks: Background tasks for async processing

    Returns:
        Feedback submission confirmation
    """
    try:
        engine, _ = _get_recommendation_engine()

        # Submit feedback to engine
        engine.add_query_feedback(
            query=request.original_query,
            recommended_query=request.recommended_query,
            user_id=request.user_id,
            helpful=request.helpful,
        )

        # Process feedback in background for model improvement
        background_tasks.add_task(
            _process_feedback_background,
            request.original_query,
            request.recommended_query,
            request.helpful,
            request.user_id,
            request.additional_feedback,
        )

        logger.info(f"Received recommendation feedback: helpful={request.helpful}")

        return {
            "message": "Feedback submitted successfully",
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to submit feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit feedback",
        )


@recommendation_router.get("/stats")
async def get_recommendation_system_stats() -> dict[str, Any]:
    """
    Get overall recommendation system statistics.

    Returns:
        System-wide recommendation statistics
    """
    try:
        engine, history_store = _get_recommendation_engine()

        # Get history store stats
        history_stats = history_store.get_stats()

        # Get engine stats
        engine_stats = {
            "total_users": len(engine.user_profiles),
            "total_patterns": len(engine.pattern_analyzer.patterns),
            "popular_queries_count": len(engine.popular_queries),
            "trending_topics_count": len(engine.trending_topics),
        }

        # Get pattern stats
        pattern_stats = {
            "most_frequent_patterns": [
                {
                    "pattern_id": pattern.pattern_id,
                    "frequency": pattern.frequency,
                    "success_rate": pattern.success_rate,
                }
                for pattern in engine.pattern_analyzer.get_popular_patterns(limit=5)
            ]
        }

        combined_stats = {
            **history_stats,
            **engine_stats,
            **pattern_stats,
            "generated_at": datetime.now().isoformat(),
        }

        return combined_stats

    except Exception as e:
        logger.error(f"Failed to get recommendation stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve recommendation statistics",
        )


@recommendation_router.get("/health")
async def recommendation_health_check() -> dict[str, Any]:
    """
    Health check endpoint for recommendation service.

    Returns:
        Service health status
    """
    try:
        engine, history_store = _get_recommendation_engine()

        # Test basic functionality
        test_recommendations = engine.recommend("test query", limit=1)

        return {
            "status": "healthy",
            "service": "query-recommendations",
            "total_users": len(engine.user_profiles),
            "total_patterns": len(engine.pattern_analyzer.patterns),
            "history_cache_size": len(history_store.recent_cache),
            "test_recommendations_count": len(test_recommendations),
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "service": "query-recommendations",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


# Background task functions
async def _process_feedback_background(
    original_query: str,
    recommended_query: str,
    helpful: bool,
    user_id: str | None,
    additional_feedback: str | None,
):
    """Background task to process recommendation feedback."""
    try:
        # In a real implementation, this could:
        # - Update recommendation model weights
        # - Store feedback in analytics database
        # - Trigger model retraining if needed

        logger.info(
            f"Processing feedback: helpful={helpful}, "
            f"user={user_id}, additional='{additional_feedback}'"
        )

    except Exception as e:
        logger.error(f"Failed to process feedback in background: {e}")


# Export router
__all__ = ["recommendation_router"]
