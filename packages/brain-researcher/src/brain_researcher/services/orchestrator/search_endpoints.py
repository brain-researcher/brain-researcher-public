"""
Search API endpoints for autocomplete, trending searches, and search history.
Integrates with BR-KG and Agent services to provide intelligent search suggestions.
"""

import asyncio
import hashlib
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set
import logging

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
import httpx

from .env import AGENT_URL, NEUROKG_URL

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/api/search", tags=["search"])

# ============================================================================
# Models
# ============================================================================

class SearchSuggestion(BaseModel):
    """Search suggestion with metadata"""
    text: str = Field(..., description="Suggestion text")
    type: str = Field(..., description="Type: term, dataset, brain_region, task, concept")
    frequency: int = Field(default=0, description="Usage frequency")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")
    source: str = Field(..., description="Source: agent, neurokg, user_history")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score")

class SearchSuggestionsResponse(BaseModel):
    """Response for search suggestions"""
    suggestions: List[SearchSuggestion]
    total: int
    query_time_ms: int

class TrendingSearch(BaseModel):
    """Trending search query"""
    query: str
    count: int
    growth_rate: float  # Percentage growth
    category: str  # e.g., "fmri", "connectivity", "preprocessing"
    last_searched: datetime

class TrendingSearchResponse(BaseModel):
    """Response for trending searches"""
    trending: List[TrendingSearch]
    timeframe: str  # e.g., "24h", "7d", "30d"
    updated_at: datetime

class SearchHistoryItem(BaseModel):
    """Search history item"""
    query: str
    timestamp: datetime
    results_count: Optional[int] = None
    clicked_result: Optional[str] = None
    session_id: Optional[str] = None

class SearchHistoryResponse(BaseModel):
    """Response for search history"""
    history: List[SearchHistoryItem]
    total: int
    has_more: bool

# ============================================================================
# In-Memory Storage (Replace with Redis/Database in production)
# ============================================================================

# Search suggestions cache
search_cache: Dict[str, List[SearchSuggestion]] = {}
cache_timestamps: Dict[str, datetime] = {}
CACHE_TTL = timedelta(minutes=15)

# Search history and trending data
search_history: Dict[str, List[SearchHistoryItem]] = defaultdict(list)  # user_id -> history
trending_queries: Dict[str, TrendingSearch] = {}
query_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))  # timeframe -> query -> count

# Predefined suggestions based on common neuroscience terms
PREDEFINED_SUGGESTIONS = {
    "brain_regions": [
        {"text": "prefrontal cortex", "type": "brain_region", "source": "atlas"},
        {"text": "hippocampus", "type": "brain_region", "source": "atlas"},
        {"text": "amygdala", "type": "brain_region", "source": "atlas"},
        {"text": "insula", "type": "brain_region", "source": "atlas"},
        {"text": "anterior cingulate cortex", "type": "brain_region", "source": "atlas"},
        {"text": "default mode network", "type": "network", "source": "atlas"},
        {"text": "salience network", "type": "network", "source": "atlas"},
        {"text": "executive control network", "type": "network", "source": "atlas"},
    ],
    "tasks": [
        {"text": "n-back", "type": "task", "source": "paradigm"},
        {"text": "stroop", "type": "task", "source": "paradigm"},
        {"text": "go/no-go", "type": "task", "source": "paradigm"},
        {"text": "working memory", "type": "task", "source": "paradigm"},
        {"text": "emotional faces", "type": "task", "source": "paradigm"},
        {"text": "motor task", "type": "task", "source": "paradigm"},
        {"text": "resting state", "type": "task", "source": "paradigm"},
    ],
    "analyses": [
        {"text": "GLM analysis", "type": "analysis", "source": "method"},
        {"text": "connectivity analysis", "type": "analysis", "source": "method"},
        {"text": "ICA decomposition", "type": "analysis", "source": "method"},
        {"text": "seed-based connectivity", "type": "analysis", "source": "method"},
        {"text": "group comparison", "type": "analysis", "source": "method"},
        {"text": "longitudinal analysis", "type": "analysis", "source": "method"},
    ]
}

# ============================================================================
# Service Clients
# ============================================================================

class SearchServiceClient:
    """Client for retrieving search suggestions from various services"""
    
    @staticmethod
    async def get_neurokg_suggestions(query: str, limit: int = 10) -> List[SearchSuggestion]:
        """Get suggestions from BR-KG service"""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(
                    f"{NEUROKG_URL}/api/search/suggest",
                    params={"q": query, "limit": limit}
                )
                if response.status_code == 200:
                    data = response.json()
                    suggestions = []
                    for item in data.get("suggestions", []):
                        suggestions.append(SearchSuggestion(
                            text=item["text"],
                            type=item.get("type", "term"),
                            frequency=item.get("frequency", 0),
                            source="neurokg",
                            confidence=item.get("confidence", 0.8),
                            metadata=item.get("metadata")
                        ))
                    return suggestions
        except Exception as e:
            logger.warning(f"Failed to get BR-KG suggestions: {e}")
        return []
    
    @staticmethod
    async def get_agent_suggestions(query: str, limit: int = 10) -> List[SearchSuggestion]:
        """Get suggestions from Agent service"""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.post(
                    f"{AGENT_URL}/search/suggest",
                    json={"query": query, "limit": limit}
                )
                if response.status_code == 200:
                    data = response.json()
                    suggestions = []
                    for item in data.get("suggestions", []):
                        suggestions.append(SearchSuggestion(
                            text=item["text"],
                            type=item.get("type", "concept"),
                            source="agent",
                            confidence=item.get("confidence", 0.7),
                            metadata=item.get("metadata")
                        ))
                    return suggestions
        except Exception as e:
            logger.warning(f"Failed to get Agent suggestions: {e}")
        return []

# ============================================================================
# Search Logic
# ============================================================================

def get_predefined_suggestions(query: str, limit: int = 5) -> List[SearchSuggestion]:
    """Get predefined suggestions based on query"""
    query_lower = query.lower()
    suggestions = []
    
    # Search through all predefined categories
    for category, items in PREDEFINED_SUGGESTIONS.items():
        for item in items:
            if query_lower in item["text"].lower():
                suggestions.append(SearchSuggestion(
                    text=item["text"],
                    type=item["type"],
                    source=item["source"],
                    confidence=0.9,
                    frequency=100  # Mock frequency
                ))
    
    # Sort by relevance (starts with query gets higher score)
    suggestions.sort(key=lambda x: (
        0 if x.text.lower().startswith(query_lower) else 1,
        -x.confidence
    ))
    
    return suggestions[:limit]

def get_cached_suggestions(query: str) -> Optional[List[SearchSuggestion]]:
    """Get cached suggestions if still valid"""
    cache_key = hashlib.md5(query.encode()).hexdigest()
    
    if cache_key in search_cache and cache_key in cache_timestamps:
        if datetime.utcnow() - cache_timestamps[cache_key] < CACHE_TTL:
            return search_cache[cache_key]
    
    return None

def cache_suggestions(query: str, suggestions: List[SearchSuggestion]):
    """Cache suggestions with timestamp"""
    cache_key = hashlib.md5(query.encode()).hexdigest()
    search_cache[cache_key] = suggestions
    cache_timestamps[cache_key] = datetime.utcnow()

async def get_user_history_suggestions(user_id: str, query: str, limit: int = 3) -> List[SearchSuggestion]:
    """Get suggestions from user's search history"""
    if user_id not in search_history:
        return []
    
    query_lower = query.lower()
    suggestions = []
    
    # Find matching queries from history
    for item in search_history[user_id]:
        if query_lower in item.query.lower() and item.query.lower() != query_lower:
            suggestions.append(SearchSuggestion(
                text=item.query,
                type="history",
                source="user_history",
                confidence=0.6,
                frequency=1,
                metadata={"last_searched": item.timestamp.isoformat()}
            ))
    
    # Remove duplicates and limit
    seen = set()
    unique_suggestions = []
    for s in suggestions:
        if s.text not in seen:
            seen.add(s.text)
            unique_suggestions.append(s)
    
    return unique_suggestions[:limit]

def update_trending_queries(query: str):
    """Update trending query statistics"""
    now = datetime.utcnow()
    
    # Update counters for different timeframes
    timeframes = {
        "1h": timedelta(hours=1),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30)
    }
    
    for timeframe in timeframes.keys():
        query_counts[timeframe][query] += 1
    
    # Update trending query object
    if query in trending_queries:
        old_count = trending_queries[query].count
        trending_queries[query].count += 1
        trending_queries[query].growth_rate = ((trending_queries[query].count - old_count) / old_count) * 100
        trending_queries[query].last_searched = now
    else:
        trending_queries[query] = TrendingSearch(
            query=query,
            count=1,
            growth_rate=0.0,
            category="general",  # Could be improved with classification
            last_searched=now
        )

# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/autocomplete", response_model=SearchSuggestionsResponse)
async def get_search_suggestions(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of suggestions"),
    user_id: Optional[str] = Query(None, description="User ID for personalized suggestions")
) -> SearchSuggestionsResponse:
    """Get search suggestions for autocomplete"""
    start_time = datetime.utcnow()
    
    # Check cache first
    cached = get_cached_suggestions(q)
    if cached:
        query_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        return SearchSuggestionsResponse(
            suggestions=cached[:limit],
            total=len(cached),
            query_time_ms=query_time
        )
    
    # Collect suggestions from multiple sources
    all_suggestions = []
    
    try:
        # Get suggestions in parallel
        tasks = [
            get_predefined_suggestions(q, limit // 3),
        ]
        
        # Add service-based suggestions
        if len(q) >= 2:  # Only call services for longer queries
            tasks.extend([
                SearchServiceClient.get_neurokg_suggestions(q, limit // 3),
                SearchServiceClient.get_agent_suggestions(q, limit // 3)
            ])
        
        # Add user history suggestions
        if user_id:
            tasks.append(get_user_history_suggestions(user_id, q, limit // 4))
        
        # Execute all tasks
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect valid results
        for result in results:
            if isinstance(result, list):
                all_suggestions.extend(result)
            elif isinstance(result, Exception):
                logger.warning(f"Suggestion task failed: {result}")
    
    except Exception as e:
        logger.error(f"Error getting suggestions: {e}")
        # Fall back to predefined suggestions
        all_suggestions = get_predefined_suggestions(q, limit)
    
    # Remove duplicates and sort by relevance
    seen = set()
    unique_suggestions = []
    for suggestion in all_suggestions:
        if suggestion.text not in seen:
            seen.add(suggestion.text)
            unique_suggestions.append(suggestion)
    
    # Sort by confidence and relevance
    unique_suggestions.sort(key=lambda x: (
        0 if x.text.lower().startswith(q.lower()) else 1,
        -x.confidence,
        -x.frequency
    ))
    
    # Limit results
    final_suggestions = unique_suggestions[:limit]
    
    # Cache results
    cache_suggestions(q, final_suggestions)
    
    query_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
    
    return SearchSuggestionsResponse(
        suggestions=final_suggestions,
        total=len(final_suggestions),
        query_time_ms=query_time
    )

@router.get("/trending", response_model=TrendingSearchResponse)
async def get_trending_searches(
    timeframe: str = Query("24h", pattern="^(1h|24h|7d|30d)$", description="Time period"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of trending searches")
) -> TrendingSearchResponse:
    """Get trending search queries"""
    
    # Get queries from the specified timeframe
    queries = query_counts.get(timeframe, {})
    
    # If no real data, provide mock trending data
    if not queries:
        mock_trending = [
            TrendingSearch(
                query="working memory fMRI",
                count=45,
                growth_rate=25.0,
                category="fmri",
                last_searched=datetime.utcnow() - timedelta(minutes=30)
            ),
            TrendingSearch(
                query="default mode network connectivity",
                count=38,
                growth_rate=18.5,
                category="connectivity",
                last_searched=datetime.utcnow() - timedelta(hours=2)
            ),
            TrendingSearch(
                query="motor cortex activation",
                count=32,
                growth_rate=12.3,
                category="activation",
                last_searched=datetime.utcnow() - timedelta(hours=1)
            ),
            TrendingSearch(
                query="resting state preprocessing",
                count=28,
                growth_rate=8.7,
                category="preprocessing",
                last_searched=datetime.utcnow() - timedelta(minutes=45)
            ),
            TrendingSearch(
                query="group analysis GLM",
                count=24,
                growth_rate=15.2,
                category="statistics",
                last_searched=datetime.utcnow() - timedelta(hours=3)
            )
        ]
        
        return TrendingSearchResponse(
            trending=mock_trending[:limit],
            timeframe=timeframe,
            updated_at=datetime.utcnow()
        )
    
    # Convert to TrendingSearch objects and sort by count
    trending_list = []
    for query, count in queries.items():
        if query in trending_queries:
            trending_list.append(trending_queries[query])
    
    trending_list.sort(key=lambda x: x.count, reverse=True)
    
    return TrendingSearchResponse(
        trending=trending_list[:limit],
        timeframe=timeframe,
        updated_at=datetime.utcnow()
    )

@router.get("/history", response_model=SearchHistoryResponse)
async def get_search_history(
    user_id: str = Query(..., description="User ID"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of history items"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
) -> SearchHistoryResponse:
    """Get user's search history"""
    
    user_history = search_history.get(user_id, [])
    
    # Sort by timestamp (most recent first)
    sorted_history = sorted(user_history, key=lambda x: x.timestamp, reverse=True)
    
    # Apply pagination
    paginated_history = sorted_history[offset:offset + limit]
    has_more = len(sorted_history) > offset + limit
    
    return SearchHistoryResponse(
        history=paginated_history,
        total=len(user_history),
        has_more=has_more
    )

@router.post("/track")
async def track_search(
    query: str = Query(..., description="Search query"),
    user_id: Optional[str] = Query(None, description="User ID"),
    results_count: Optional[int] = Query(None, description="Number of results returned"),
    session_id: Optional[str] = Query(None, description="Session ID")
) -> Dict[str, str]:
    """Track a search query for analytics and trending"""
    
    # Update trending data
    update_trending_queries(query)
    
    # Add to user history if user_id provided
    if user_id:
        history_item = SearchHistoryItem(
            query=query,
            timestamp=datetime.utcnow(),
            results_count=results_count,
            session_id=session_id
        )
        search_history[user_id].append(history_item)
        
        # Keep only last 1000 searches per user
        if len(search_history[user_id]) > 1000:
            search_history[user_id] = search_history[user_id][-1000:]
    
    return {"status": "tracked", "query": query}

@router.post("/click")
async def track_search_click(
    query: str = Query(..., description="Original search query"),
    clicked_result: str = Query(..., description="Clicked result identifier"),
    user_id: Optional[str] = Query(None, description="User ID"),
    position: Optional[int] = Query(None, description="Position in search results")
) -> Dict[str, str]:
    """Track when user clicks on a search result"""
    
    # Update user history with click information
    if user_id and user_id in search_history:
        # Find the most recent matching query and update it
        for item in reversed(search_history[user_id]):
            if item.query == query and item.clicked_result is None:
                item.clicked_result = clicked_result
                break
    
    logger.info(f"Search click tracked: query='{query}', result='{clicked_result}', position={position}")
    
    return {"status": "tracked", "query": query, "clicked_result": clicked_result}

@router.delete("/history/{user_id}")
async def clear_search_history(user_id: str) -> Dict[str, str]:
    """Clear user's search history"""
    
    if user_id in search_history:
        del search_history[user_id]
    
    return {"status": "cleared", "user_id": user_id}

@router.get("/popular")
async def get_popular_searches(
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of results")
) -> Dict[str, List[str]]:
    """Get popular search queries"""
    
    # Mock popular searches by category
    popular_by_category = {
        "fmri": [
            "working memory fMRI analysis",
            "motor task activation",
            "emotional faces paradigm",
            "resting state connectivity",
            "GLM statistical analysis"
        ],
        "preprocessing": [
            "motion correction",
            "spatial normalization",
            "temporal filtering",
            "slice timing correction",
            "skull stripping"
        ],
        "connectivity": [
            "seed-based connectivity",
            "independent component analysis",
            "graph theory analysis",
            "dynamic functional connectivity",
            "network modularity"
        ],
        "statistics": [
            "multiple comparisons correction",
            "cluster-based thresholding",
            "group comparison",
            "longitudinal analysis",
            "mixed effects models"
        ]
    }
    
    if category and category in popular_by_category:
        return {category: popular_by_category[category][:limit]}
    
    # Return all categories if no specific category requested
    result = {}
    for cat, queries in popular_by_category.items():
        result[cat] = queries[:limit]
    
    return result
