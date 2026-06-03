"""Cache management API endpoints (P2.5)."""

from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional, Dict, Any
import logging
from pydantic import BaseModel

router = APIRouter(prefix="/api/cache", tags=["cache"])
logger = logging.getLogger(__name__)


class CacheResolveRequest(BaseModel):
    """Request model for POST /api/cache/resolve."""
    tool: str
    tool_version: Optional[str] = None
    parameters: Dict[str, Any] = {}
    container_image: str = ""


@router.get("/resolve")
async def resolve_cache_key(key: str = Query(..., description="Cache key to resolve")):
    """Resolve a cache key to run_id and run_dir.

    Args:
        key: Cache key in format "sha256:..."

    Returns:
        Cache entry details including run_id, run_dir, state

    Raises:
        503: Cache not enabled
        404: Cache entry not found
    """
    from .main_enhanced import cache_store

    if not cache_store:
        raise HTTPException(503, "Cache not enabled (BR_CACHE_ENABLED=false)")

    entry = await cache_store.lookup(key)
    if not entry:
        raise HTTPException(404, f"Cache entry not found for key {key[:16]}...")

    return entry.to_dict()


@router.post("/resolve")
async def resolve_from_params(request: CacheResolveRequest):
    """Compute cache key from parameters and resolve.

    This endpoint allows computing a cache key from job parameters
    without submitting the job, useful for checking if a result is already cached.

    Args:
        request: Cache resolve request with tool, parameters, etc.

    Returns:
        Dict with cache_key, found flag, and optional entry details

    Raises:
        503: Cache not enabled
    """
    from .main_enhanced import cache_store
    from .cache_key import build_cache_key

    if not cache_store:
        raise HTTPException(503, "Cache not enabled (BR_CACHE_ENABLED=false)")

    # Extract input paths from parameters
    input_paths = []
    for key in ["input", "inputs", "in_file", "source", "image"]:
        if key in request.parameters:
            value = request.parameters[key]
            if isinstance(value, str):
                input_paths.append(value)
            elif isinstance(value, list):
                input_paths.extend([v for v in value if isinstance(v, str)])

    # Build cache key
    cache_key = build_cache_key(
        tool=request.tool,
        tool_version=request.tool_version,
        canonical_params=request.parameters,
        input_paths=input_paths,
        container_image=request.container_image,
    )

    # Lookup
    entry = await cache_store.lookup(cache_key)
    if not entry:
        return {"cache_key": cache_key, "found": False}

    return {"cache_key": cache_key, "found": True, "entry": entry.to_dict()}


@router.get("/stats")
async def get_cache_stats():
    """Get cache statistics.

    Returns cache metrics including:
    - Total entries (pending, completed, failed)
    - Total size in MB
    - Hit/miss counts and hit rate

    Returns:
        Dict with cache statistics

    Raises:
        503: Cache not enabled
    """
    from .main_enhanced import cache_store

    if not cache_store:
        raise HTTPException(503, "Cache not enabled (BR_CACHE_ENABLED=false)")

    stats = await cache_store.get_stats()
    return stats.to_dict()


@router.delete("")
async def clear_cache(
    tool_version: Optional[str] = Query(None, description="Clear entries for specific tool version"),
    git_sha: Optional[str] = Query(None, description="Clear entries for specific git SHA"),
):
    """Clear cache entries.

    Supports clearing:
    - All entries (no filters)
    - By tool version (e.g., "fsl.bet:6.0.7")
    - By git SHA (e.g., "abc123...")

    Args:
        tool_version: Optional tool version filter
        git_sha: Optional git SHA filter

    Returns:
        Dict with number of entries deleted and filter used

    Raises:
        503: Cache not enabled
    """
    from .main_enhanced import cache_store

    if not cache_store:
        raise HTTPException(503, "Cache not enabled (BR_CACHE_ENABLED=false)")

    if tool_version:
        deleted = await cache_store.clear_by_tool(tool_version)
        return {"deleted": deleted, "filter": f"tool_version={tool_version}"}

    elif git_sha:
        deleted = await cache_store.clear_by_git(git_sha)
        return {"deleted": deleted, "filter": f"git_sha={git_sha}"}

    else:
        # Clear all
        deleted = await cache_store.clear_all()
        return {"deleted": deleted, "filter": "all"}


@router.post("/gc")
async def garbage_collect(
    max_entries: int = Query(10000, description="Maximum number of entries to keep")
):
    """Run LRU garbage collection to keep cache under size limit.

    Evicts oldest entries (by last_accessed_at) to keep total under max_entries.

    Args:
        max_entries: Maximum entries to keep (default: 10000)

    Returns:
        Dict with number of entries evicted

    Raises:
        503: Cache not enabled
        400: Invalid max_entries value
    """
    from .main_enhanced import cache_store

    if not cache_store:
        raise HTTPException(503, "Cache not enabled (BR_CACHE_ENABLED=false)")

    if max_entries < 0:
        raise HTTPException(400, "max_entries must be non-negative")

    evicted = await cache_store.gc_lru(max_entries)
    return {
        "evicted": evicted,
        "max_entries": max_entries,
        "message": f"Evicted {evicted} old entries, kept {max_entries} most recent",
    }
