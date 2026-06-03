"""
Cache Management API Endpoints for Brain Researcher Orchestrator (AGENT-016)

This module provides REST API endpoints for cache management functionality,
allowing clients to monitor cache performance, invalidate cache entries,
and warm the cache with common queries.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException, BackgroundTasks, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# API Models
class CacheStats(BaseModel):
    """Response model for cache statistics."""

    hit_rate: float = Field(..., description="Cache hit rate (0.0-1.0)")
    total_hits: int = Field(..., description="Total number of cache hits")
    total_misses: int = Field(..., description="Total number of cache misses")
    total_requests: int = Field(..., description="Total cache requests")
    total_sets: int = Field(..., description="Total cache sets")
    total_invalidations: int = Field(..., description="Total cache invalidations")
    avg_hit_latency_ms: float = Field(..., description="Average hit latency in milliseconds")
    avg_miss_latency_ms: float = Field(..., description="Average miss latency in milliseconds")
    memory_used_bytes: int = Field(..., description="Memory used by cache in bytes")
    memory_limit_bytes: int = Field(..., description="Memory limit in bytes")
    memory_usage_percent: float = Field(..., description="Memory usage percentage")
    policy: str = Field(..., description="Current cache policy")
    default_ttl_seconds: int = Field(..., description="Default TTL in seconds")
    last_updated: str = Field(..., description="Last update timestamp")


class CacheInvalidationRequest(BaseModel):
    """Request model for cache invalidation."""

    pattern: Optional[str] = Field(default=None, description="Redis key pattern to match")
    tags: Optional[List[str]] = Field(default=None, description="Tags to invalidate")
    key_type: Optional[str] = Field(
        default=None,
        description="Specific key type to invalidate (query_result, tool_exec, planning, reasoning, analysis, viz)"
    )


class CacheInvalidationResponse(BaseModel):
    """Response model for cache invalidation."""

    invalidated_count: int = Field(..., description="Number of cache entries invalidated")
    timestamp: str = Field(..., description="Invalidation timestamp")


class CacheWarmupRequest(BaseModel):
    """Request model for cache warming."""

    queries: List[str] = Field(..., description="List of queries to warm the cache with")
    background: bool = Field(default=True, description="Whether to run warming in background")


class CacheWarmupResponse(BaseModel):
    """Response model for cache warming."""

    queued_queries: int = Field(..., description="Number of queries queued for warming")
    status: str = Field(..., description="Warming status")
    timestamp: str = Field(..., description="Request timestamp")


class CachePolicyRequest(BaseModel):
    """Request model for changing cache policy."""

    policy: str = Field(
        ...,
        description="Cache policy (aggressive, moderate, conservative, disabled)"
    )


class CachePolicyResponse(BaseModel):
    """Response model for cache policy changes."""

    old_policy: str = Field(..., description="Previous cache policy")
    new_policy: str = Field(..., description="New cache policy")
    timestamp: str = Field(..., description="Change timestamp")


# Initialize router
cache_router = APIRouter(prefix="/api/cache", tags=["cache"])


def _get_cache_manager():
    """Get cache manager from agent service."""
    try:
        from brain_researcher.services.agent.cache_manager import get_global_cache_manager
        return get_global_cache_manager()
    except Exception as e:
        logger.error(f"Failed to get cache manager: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service unavailable"
        )


@cache_router.get("/stats", response_model=CacheStats)
async def get_cache_stats() -> CacheStats:
    """
    Get comprehensive cache statistics.

    Returns:
        Current cache performance metrics

    Raises:
        HTTPException: If cache service is unavailable
    """
    try:
        cache_manager = _get_cache_manager()
        stats_data = cache_manager.get_stats()

        return CacheStats(**stats_data)

    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve cache statistics: {str(e)}"
        )


@cache_router.delete("/invalidate", response_model=CacheInvalidationResponse)
async def invalidate_cache(
    request: CacheInvalidationRequest
) -> CacheInvalidationResponse:
    """
    Invalidate cache entries by pattern, tags, or key type.

    Args:
        request: Invalidation request parameters

    Returns:
        Number of cache entries invalidated

    Raises:
        HTTPException: If invalidation fails or no criteria provided
    """
    try:
        cache_manager = _get_cache_manager()

        # Validate request
        if not any([request.pattern, request.tags, request.key_type]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must provide at least one of: pattern, tags, or key_type"
            )

        # Convert key_type string to enum if provided
        key_type = None
        if request.key_type:
            from brain_researcher.services.agent.cache_manager import CacheKeyType
            try:
                key_type = CacheKeyType(request.key_type.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid key_type: {request.key_type}"
                )

        # Convert tags list to set
        tags = set(request.tags) if request.tags else None

        # Perform invalidation
        invalidated_count = cache_manager.invalidate(
            pattern=request.pattern,
            tags=tags,
            key_type=key_type
        )

        logger.info(
            f"Invalidated {invalidated_count} cache entries - "
            f"pattern: {request.pattern}, tags: {request.tags}, key_type: {request.key_type}"
        )

        return CacheInvalidationResponse(
            invalidated_count=invalidated_count,
            timestamp=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cache invalidation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cache invalidation failed: {str(e)}"
        )


@cache_router.post("/warm", response_model=CacheWarmupResponse)
async def warm_cache(
    request: CacheWarmupRequest,
    background_tasks: BackgroundTasks
) -> CacheWarmupResponse:
    """
    Warm the cache with common queries.

    Args:
        request: Cache warming request with queries
        background_tasks: Background tasks for async processing

    Returns:
        Cache warming status

    Raises:
        HTTPException: If warming fails
    """
    try:
        if not request.queries:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must provide at least one query for cache warming"
            )

        if len(request.queries) > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot warm cache with more than 100 queries at once"
            )

        if request.background:
            # Queue cache warming in background
            background_tasks.add_task(
                _warm_cache_background,
                request.queries
            )

            status_msg = "queued"
        else:
            # Perform cache warming synchronously
            await _warm_cache_sync(request.queries)
            status_msg = "completed"

        logger.info(f"Cache warming {status_msg} for {len(request.queries)} queries")

        return CacheWarmupResponse(
            queued_queries=len(request.queries),
            status=status_msg,
            timestamp=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cache warming failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cache warming failed: {str(e)}"
        )


@cache_router.delete("/clear", response_model=CacheInvalidationResponse)
async def clear_all_cache() -> CacheInvalidationResponse:
    """
    Clear all cache entries.

    Returns:
        Number of cache entries cleared

    Raises:
        HTTPException: If cache clearing fails
    """
    try:
        cache_manager = _get_cache_manager()
        cleared_count = cache_manager.clear_all()

        logger.warning(f"Cleared all cache entries: {cleared_count}")

        return CacheInvalidationResponse(
            invalidated_count=cleared_count,
            timestamp=datetime.now().isoformat()
        )

    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear cache: {str(e)}"
        )


@cache_router.put("/policy", response_model=CachePolicyResponse)
async def update_cache_policy(
    request: CachePolicyRequest
) -> CachePolicyResponse:
    """
    Update the cache policy.

    Args:
        request: New cache policy

    Returns:
        Policy change confirmation

    Raises:
        HTTPException: If policy update fails
    """
    try:
        from brain_researcher.services.agent.cache_manager import CachePolicy

        # Validate policy
        try:
            new_policy = CachePolicy(request.policy.lower())
        except ValueError:
            valid_policies = [p.value for p in CachePolicy]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid policy: {request.policy}. Must be one of: {valid_policies}"
            )

        cache_manager = _get_cache_manager()
        old_policy = cache_manager.policy.value

        # Update policy
        cache_manager.policy = new_policy
        cache_manager.policy_config = cache_manager._get_policy_config()

        logger.info(f"Cache policy changed from {old_policy} to {new_policy.value}")

        return CachePolicyResponse(
            old_policy=old_policy,
            new_policy=new_policy.value,
            timestamp=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update cache policy: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update cache policy: {str(e)}"
        )


@cache_router.get("/health")
async def cache_health_check() -> Dict[str, Any]:
    """
    Health check endpoint for cache service.

    Returns:
        Cache service health status
    """
    try:
        cache_manager = _get_cache_manager()
        stats = cache_manager.get_stats()

        # Determine health status
        hit_rate = stats.get("hit_rate", 0.0)
        memory_usage = stats.get("memory_usage_percent", 0.0)

        if memory_usage > 90:
            health_status = "degraded"
            health_message = "High memory usage"
        elif hit_rate < 0.3:
            health_status = "degraded"
            health_message = "Low cache hit rate"
        else:
            health_status = "healthy"
            health_message = "Cache operating normally"

        return {
            "status": health_status,
            "message": health_message,
            "service": "cache-manager",
            "hit_rate": hit_rate,
            "memory_usage_percent": memory_usage,
            "policy": stats.get("policy", "unknown"),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "message": str(e),
            "service": "cache-manager",
            "timestamp": datetime.now().isoformat()
        }


@cache_router.get("/metrics/prometheus")
async def cache_metrics_prometheus() -> str:
    """
    Get cache metrics in Prometheus format for monitoring.

    Returns:
        Prometheus-formatted metrics
    """
    try:
        cache_manager = _get_cache_manager()
        stats = cache_manager.get_stats()

        metrics = [
            f"# HELP brain_researcher_cache_hit_rate Cache hit rate",
            f"# TYPE brain_researcher_cache_hit_rate gauge",
            f"brain_researcher_cache_hit_rate {stats.get('hit_rate', 0.0)}",
            f"",
            f"# HELP brain_researcher_cache_requests_total Total cache requests",
            f"# TYPE brain_researcher_cache_requests_total counter",
            f"brain_researcher_cache_requests_total {{type=\"hits\"}} {stats.get('total_hits', 0)}",
            f"brain_researcher_cache_requests_total {{type=\"misses\"}} {stats.get('total_misses', 0)}",
            f"",
            f"# HELP brain_researcher_cache_memory_usage_bytes Cache memory usage",
            f"# TYPE brain_researcher_cache_memory_usage_bytes gauge",
            f"brain_researcher_cache_memory_usage_bytes {stats.get('memory_used_bytes', 0)}",
            f"",
            f"# HELP brain_researcher_cache_latency_ms Cache operation latency",
            f"# TYPE brain_researcher_cache_latency_ms gauge",
            f"brain_researcher_cache_latency_ms {{type=\"hit\"}} {stats.get('avg_hit_latency_ms', 0.0)}",
            f"brain_researcher_cache_latency_ms {{type=\"miss\"}} {stats.get('avg_miss_latency_ms', 0.0)}",
        ]

        return "\n".join(metrics)

    except Exception as e:
        logger.error(f"Failed to generate Prometheus metrics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate metrics"
        )


# Background task functions
async def _warm_cache_background(queries: List[str]):
    """Background task to warm cache with queries."""
    try:
        await _warm_cache_sync(queries)
        logger.info(f"Background cache warming completed for {len(queries)} queries")
    except Exception as e:
        logger.error(f"Background cache warming failed: {e}")


async def _warm_cache_sync(queries: List[str]):
    """Synchronously warm cache with queries."""
    try:
        # Import graph to avoid circular imports
        from brain_researcher.services.agent.graph import get_core_graph

        graph_app = get_core_graph()

        success_count = 0
        for i, query in enumerate(queries):
            try:
                # Run query to populate cache
                thread_id = f"warmup_{i}_{hash(query)}"
                result = graph_app.invoke({
                    "messages": [{"type": "human", "content": query}],
                    "thread_id": thread_id
                }, {"configurable": {"thread_id": thread_id}})

                success_count += 1
                logger.debug(f"Warmed cache for query {i+1}/{len(queries)}")

            except Exception as e:
                logger.warning(f"Failed to warm cache for query {i+1}: {e}")

        logger.info(f"Cache warming completed: {success_count}/{len(queries)} successful")

    except Exception as e:
        logger.error(f"Cache warming failed: {e}")
        raise


# Export router
__all__ = ["cache_router"]