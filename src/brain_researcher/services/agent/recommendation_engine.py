"""
Query Recommendation System for Brain Researcher Agent (AGENT-022)

This module implements a recommendation system that suggests related queries and
analyses based on user history, popular patterns, and semantic similarity.
"""

import asyncio
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class QueryPattern:
    """Represents a common query pattern."""

    pattern_id: str
    description: str
    template: str
    frequency: int = 0
    success_rate: float = 0.0
    avg_execution_time: float = 0.0
    domains: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    example_queries: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    """Represents a query recommendation."""

    query: str
    confidence: float
    reason: str
    category: str
    metadata: dict[str, Any] = field(default_factory=dict)
    related_patterns: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    estimated_time: float | None = None


@dataclass
class UserProfile:
    """Represents user preferences and patterns."""

    user_id: str
    preferred_domains: dict[str, float] = field(default_factory=dict)
    preferred_tools: dict[str, float] = field(default_factory=dict)
    query_complexity_preference: float = 0.5  # 0=simple, 1=complex
    avg_session_length: float = 30.0  # minutes
    common_keywords: dict[str, int] = field(default_factory=dict)
    success_rate_by_category: dict[str, float] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class RecommendationContext:
    """Context metadata for recommendation generation."""

    setting: str | None = None
    urgency: str | None = None
    experience_level: str | None = None
    dataset_size: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecommendationResult:
    """Recommendation result returned by RecommendationService."""

    query: str
    relevance_score: float
    explanation: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _QueryRecord:
    user_id: str
    query: str
    timestamp: datetime
    context: dict[str, Any]
    results_quality: float


@dataclass
class _InteractionRecord:
    user_id: str
    original_query: str
    recommended_query: str
    interaction_type: str
    timestamp: datetime
    satisfaction_score: float | None
    response_time: float | None
    session_metadata: dict[str, Any]


class SimilarityEngine:
    """Calculates similarity between queries using various methods."""

    def __init__(self, embedding_model=None):
        """
        Initialize the similarity engine.

        Args:
            embedding_model: Optional embedding model for semantic similarity
        """
        self.embedding_model = embedding_model

        # Cache for query embeddings
        self.embedding_cache: dict[str, np.ndarray] = {}

        # Common neuroimaging terms for term-based similarity
        self.domain_terms = self._load_domain_terms()

    def _load_domain_terms(self) -> set[str]:
        """Load domain-specific terms for similarity calculation."""
        return {
            # Brain regions
            "prefrontal",
            "parietal",
            "temporal",
            "occipital",
            "cingulate",
            "amygdala",
            "hippocampus",
            "thalamus",
            "caudate",
            "putamen",
            "insula",
            "cerebellum",
            "brainstem",
            "cortex",
            "subcortical",
            # Tasks and paradigms
            "nback",
            "stroop",
            "oddball",
            "flanker",
            "working_memory",
            "attention",
            "emotion",
            "motor",
            "language",
            "visual",
            # Methods and analyses
            "glm",
            "connectivity",
            "activation",
            "contrast",
            "correlation",
            "classification",
            "regression",
            "ica",
            "pca",
            "svm",
            # Modalities
            "fmri",
            "bold",
            "dwi",
            "dti",
            "asl",
            "pet",
            "eeg",
            "meg",
            # Processing
            "preprocessing",
            "normalization",
            "smoothing",
            "motion_correction",
            "registration",
            "segmentation",
            "parcellation",
        }

    def calculate_similarity(
        self, query1: str, query2: str, method: str = "hybrid"
    ) -> float:
        """
        Calculate similarity between two queries.

        Args:
            query1: First query
            query2: Second query
            method: Similarity method ("semantic", "lexical", "hybrid")

        Returns:
            Similarity score (0-1)
        """
        if method == "semantic" and self.embedding_model:
            return self._semantic_similarity(query1, query2)
        elif method == "lexical":
            return self._lexical_similarity(query1, query2)
        else:
            # Hybrid approach
            lexical = self._lexical_similarity(query1, query2)
            if self.embedding_model:
                semantic = self._semantic_similarity(query1, query2)
                return 0.6 * semantic + 0.4 * lexical
            else:
                return lexical

    def _semantic_similarity(self, query1: str, query2: str) -> float:
        """Calculate semantic similarity using embeddings."""
        try:
            # Get or compute embeddings
            emb1 = self._get_embedding(query1)
            emb2 = self._get_embedding(query2)

            if emb1 is None or emb2 is None:
                return 0.0

            # Cosine similarity
            dot_product = np.dot(emb1, emb2)
            norm1 = np.linalg.norm(emb1)
            norm2 = np.linalg.norm(emb2)

            if norm1 > 0 and norm2 > 0:
                return dot_product / (norm1 * norm2)
            else:
                return 0.0

        except Exception as e:
            logger.warning(f"Semantic similarity calculation failed: {e}")
            return 0.0

    def _lexical_similarity(self, query1: str, query2: str) -> float:
        """Calculate lexical similarity using term overlap."""
        # Tokenize and normalize
        words1 = set(query1.lower().split())
        words2 = set(query2.lower().split())

        # Basic Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))

        if union == 0:
            return 0.0

        jaccard = intersection / union

        # Boost similarity for domain-specific terms
        domain_overlap = len(
            words1.intersection(words2).intersection(self.domain_terms)
        )
        domain_boost = min(domain_overlap * 0.1, 0.3)  # Max 30% boost

        return min(jaccard + domain_boost, 1.0)

    def _get_embedding(self, query: str) -> np.ndarray | None:
        """Get embedding for a query (with caching)."""
        if query in self.embedding_cache:
            return self.embedding_cache[query]

        try:
            if hasattr(self.embedding_model, "embed_query"):
                embedding = np.array(self.embedding_model.embed_query(query))
            elif hasattr(self.embedding_model, "encode"):
                embedding = np.array(self.embedding_model.encode([query])[0])
            else:
                return None

            self.embedding_cache[query] = embedding
            return embedding

        except Exception as e:
            logger.warning(f"Failed to get embedding for query: {e}")
            return None


class PatternAnalyzer:
    """Analyzes query patterns to identify common workflows."""

    def __init__(self):
        """Initialize the pattern analyzer."""
        self.patterns: dict[str, QueryPattern] = {}
        self.pattern_transitions: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )

    def add_query_execution(
        self,
        query: str,
        tools_used: list[str],
        execution_time: float,
        success: bool,
        domain: str,
    ):
        """
        Record a query execution for pattern analysis.

        Args:
            query: The executed query
            tools_used: Tools used in execution
            execution_time: Time taken for execution
            success: Whether execution was successful
            domain: Domain of the query
        """
        # Extract pattern from query and tools
        pattern_id = self._extract_pattern_id(query, tools_used, domain)

        if pattern_id not in self.patterns:
            self.patterns[pattern_id] = QueryPattern(
                pattern_id=pattern_id,
                description=self._generate_pattern_description(query, tools_used),
                template=self._generate_pattern_template(query),
                domains=[domain],
            )

        pattern = self.patterns[pattern_id]

        # Update pattern statistics
        pattern.frequency += 1

        # Update success rate (exponential moving average)
        alpha = 0.1
        if pattern.frequency == 1:
            pattern.success_rate = 1.0 if success else 0.0
        else:
            pattern.success_rate = (1 - alpha) * pattern.success_rate + alpha * (
                1.0 if success else 0.0
            )

        # Update execution time (moving average)
        if pattern.frequency == 1:
            pattern.avg_execution_time = execution_time
        else:
            pattern.avg_execution_time = (
                1 - alpha
            ) * pattern.avg_execution_time + alpha * execution_time

        # Add domain if not present
        if domain not in pattern.domains:
            pattern.domains.append(domain)

        # Add example query
        if query not in pattern.example_queries and len(pattern.example_queries) < 5:
            pattern.example_queries.append(query)

    def _extract_pattern_id(
        self, query: str, tools_used: list[str], domain: str
    ) -> str:
        """Extract a pattern ID from query characteristics."""
        # Normalize query to identify pattern
        query_lower = query.lower()

        # Identify key components
        components = []

        # Domain component
        components.append(f"domain:{domain}")

        # Intent component
        if any(word in query_lower for word in ["compare", "contrast", "difference"]):
            components.append("intent:comparison")
        elif any(
            word in query_lower for word in ["correlat", "connect", "relationship"]
        ):
            components.append("intent:correlation")
        elif any(word in query_lower for word in ["predict", "classify", "decode"]):
            components.append("intent:prediction")
        elif any(word in query_lower for word in ["visual", "plot", "show", "display"]):
            components.append("intent:visualization")
        else:
            components.append("intent:analysis")

        # Tool component (main tool category)
        if any(tool.startswith("glm") for tool in tools_used):
            components.append("tools:glm")
        elif any(tool.startswith("connectivity") for tool in tools_used):
            components.append("tools:connectivity")
        elif any(tool.startswith("ml") or "svm" in tool for tool in tools_used):
            components.append("tools:ml")
        elif any("preprocessing" in tool for tool in tools_used):
            components.append("tools:preprocessing")

        return "_".join(components)

    def _generate_pattern_description(self, query: str, tools_used: list[str]) -> str:
        """Generate a human-readable description of the pattern."""
        main_tools = [tool for tool in tools_used if not tool.endswith("_tool")]
        tool_str = ", ".join(main_tools[:3]) if main_tools else "various tools"

        return f"Analysis pattern using {tool_str}"

    def _generate_pattern_template(self, query: str) -> str:
        """Generate a template from the query."""
        # Simple template generation - replace specific terms with placeholders
        template = query.lower()

        # Replace common specific terms with placeholders
        replacements = {
            r"\bds\d+\b": "{dataset}",
            r"\b\d+\.\d+\b": "{number}",
            r"\b\w+\.nii\.gz\b": "{file}",
            r"\b[a-z]+_[a-z]+_[a-z]+\b": "{identifier}",
        }

        import re

        for pattern, replacement in replacements.items():
            template = re.sub(pattern, replacement, template)

        return template

    def get_popular_patterns(self, limit: int = 10) -> list[QueryPattern]:
        """Get most popular query patterns."""
        sorted_patterns = sorted(
            self.patterns.values(),
            key=lambda p: p.frequency * p.success_rate,
            reverse=True,
        )
        return sorted_patterns[:limit]

    def find_next_step_patterns(
        self, current_pattern_id: str
    ) -> list[tuple[str, float]]:
        """Find patterns that commonly follow the current pattern."""
        if current_pattern_id in self.pattern_transitions:
            transitions = self.pattern_transitions[current_pattern_id]
            return sorted(transitions.items(), key=lambda x: x[1], reverse=True)
        return []


class QueryRecommendationEngine:
    """
    Main query recommendation engine.

    Features:
    - Similar query suggestions (top-5)
    - Next-step recommendations
    - Popular analyses tracking
    - Basic personalization
    - Confidence scores for recommendations
    """

    def __init__(self, embedding_model=None, history_store=None):
        """
        Initialize the recommendation engine.

        Args:
            embedding_model: Model for semantic embeddings
            history_store: Storage for query history
        """
        self.similarity_engine = SimilarityEngine(embedding_model)
        self.pattern_analyzer = PatternAnalyzer()
        self.history_store = history_store

        # User profiles
        self.user_profiles: dict[str, UserProfile] = {}

        # Global popularity tracking
        self.popular_queries: Counter = Counter()
        self.trending_topics: dict[str, int] = defaultdict(int)

        logger.info("Query Recommendation Engine initialized")

    def recommend(
        self,
        query: str,
        user_id: str | None = None,
        limit: int = 5,
        include_explanations: bool = True,
    ) -> list[Recommendation]:
        """
        Generate recommendations for a given query.

        Args:
            query: Current query to base recommendations on
            user_id: Optional user ID for personalization
            limit: Maximum number of recommendations
            include_explanations: Whether to include explanation text

        Returns:
            List of recommendations with confidence scores
        """
        recommendations = []

        # Get similar queries
        similar_recs = self._get_similar_queries(query, limit=limit // 2 + 1)
        recommendations.extend(similar_recs)

        # Get next-step recommendations
        next_step_recs = self._get_next_step_recommendations(query, limit=limit // 2)
        recommendations.extend(next_step_recs)

        # Get popular recommendations
        popular_recs = self._get_popular_recommendations(query, limit=2)
        recommendations.extend(popular_recs)

        # Apply personalization if user provided
        if user_id:
            recommendations = self._personalize_recommendations(
                recommendations, user_id, query
            )

        # Remove duplicates and sort by confidence
        seen_queries = set()
        filtered_recs = []
        for rec in recommendations:
            if rec.query not in seen_queries:
                seen_queries.add(rec.query)
                filtered_recs.append(rec)

        # Sort by confidence and limit
        filtered_recs.sort(key=lambda r: r.confidence, reverse=True)
        final_recs = filtered_recs[:limit]

        # Add explanations if requested
        if include_explanations:
            for rec in final_recs:
                if not rec.reason:
                    rec.reason = self._generate_explanation(rec, query)

        logger.info(f"Generated {len(final_recs)} recommendations for query")
        return final_recs

    def _get_similar_queries(self, query: str, limit: int = 3) -> list[Recommendation]:
        """Get queries similar to the current one."""
        recommendations = []

        if not self.history_store:
            return recommendations

        try:
            # Get recent queries from history
            recent_queries = self.history_store.get_recent_queries(limit=100)

            # Calculate similarities
            similarities = []
            for hist_query in recent_queries:
                if hist_query != query:  # Don't recommend the same query
                    similarity = self.similarity_engine.calculate_similarity(
                        query, hist_query
                    )
                    if similarity > 0.3:  # Minimum similarity threshold
                        similarities.append((hist_query, similarity))

            # Sort by similarity and take top ones
            similarities.sort(key=lambda x: x[1], reverse=True)

            for hist_query, similarity in similarities[:limit]:
                rec = Recommendation(
                    query=hist_query,
                    confidence=similarity,
                    reason="Similar to your current query",
                    category="similar",
                    metadata={"similarity_score": similarity},
                )
                recommendations.append(rec)

        except Exception as e:
            logger.warning(f"Failed to get similar queries: {e}")

        return recommendations


class RecommendationService:
    """Async recommendation service wrapper with caching and analytics."""

    def __init__(
        self,
        vector_db: Any,
        user_db: Any,
        cache_size: int = 1000,
        enable_real_time_updates: bool = True,
        enable_analytics: bool = True,
    ) -> None:
        self.vector_db = vector_db
        self.user_db = user_db
        self.cache_size = cache_size
        self.enable_real_time_updates = enable_real_time_updates
        self.enable_analytics = enable_analytics

        self._cache: dict[str, list[RecommendationResult]] = {}
        self._cache_order: list[str] = []
        self._query_history: list[_QueryRecord] = []
        self._interactions: list[_InteractionRecord] = []
        self._request_metrics: list[dict[str, Any]] = []
        self._user_profiles: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def add_user_query(
        self,
        user_id: str,
        query: str,
        timestamp: datetime | None = None,
        context: dict[str, Any] | None = None,
        results_quality: float = 0.8,
    ) -> None:
        timestamp = timestamp or datetime.utcnow()
        context = context or {}

        async with self._lock:
            self._query_history.append(
                _QueryRecord(
                    user_id=user_id,
                    query=query,
                    timestamp=timestamp,
                    context=context,
                    results_quality=results_quality,
                )
            )
            profile = self._user_profiles.setdefault(
                user_id,
                {
                    "user_id": user_id,
                    "query_count": 0,
                    "interaction_count": 0,
                    "preferences": {},
                    "expertise_level": 0.5,
                    "interaction_scores": [],
                },
            )
            profile["query_count"] += 1
            profile["last_query_at"] = timestamp
            profile["preferences"].setdefault("keywords", {})
            for token in query.lower().split():
                profile["preferences"]["keywords"][token] = (
                    profile["preferences"]["keywords"].get(token, 0) + 1
                )
            tool_pref = context.get("tool_preference")
            if tool_pref:
                profile["preferences"].setdefault("tools", {})
                profile["preferences"]["tools"][tool_pref] = (
                    profile["preferences"]["tools"].get(tool_pref, 0) + 1
                )
            specialization = context.get("specialization")
            if specialization:
                profile["preferences"].setdefault("specializations", {})
                profile["preferences"]["specializations"][specialization] = (
                    profile["preferences"]["specializations"].get(specialization, 0) + 1
                )
            profile["version"] = profile.get("version", 0) + 1

        if self.user_db is not None:
            try:
                if hasattr(self.user_db, "add_query_history"):
                    await self.user_db.add_query_history(
                        user_id=user_id,
                        query=query,
                        timestamp=timestamp,
                        metadata=context,
                    )
                if hasattr(self.user_db, "update_user_profile"):
                    await self.user_db.update_user_profile(user_id, profile)
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning("User DB update failed: %s", exc)
        self._invalidate_cache_for_user(user_id)

    async def get_recommendations(
        self,
        query: str,
        user_id: str | None = None,
        max_results: int = 5,
        include_explanations: bool = False,
        context: dict[str, Any] | None = None,
    ) -> list[RecommendationResult]:
        context = context or {}
        cache_key = self._make_cache_key(query, user_id, context)
        cached = self._cache.get(cache_key)
        cache_hit = False

        if isinstance(cached, list) and all(
            isinstance(item, RecommendationResult) for item in cached
        ):
            cache_hit = True
            results = cached[:max_results]
        else:
            results = await self._build_recommendations(
                query, user_id, context, max_results
            )
            self._set_cache(cache_key, results)

        if include_explanations:
            for rec in results:
                if not rec.explanation:
                    rec.explanation = (
                        f"Suggested based on query similarity to '{query}'."
                    )

        self._record_request_metrics(cache_hit)
        return results

    async def track_recommendation_interaction(
        self,
        user_id: str,
        original_query: str,
        recommended_query: str,
        interaction_type: str,
        satisfaction_score: float | None = None,
        response_time: float | None = None,
        session_metadata: dict[str, Any] | None = None,
    ) -> None:
        session_metadata = session_metadata or {}
        timestamp = datetime.utcnow()
        async with self._lock:
            self._interactions.append(
                _InteractionRecord(
                    user_id=user_id,
                    original_query=original_query,
                    recommended_query=recommended_query,
                    interaction_type=interaction_type,
                    timestamp=timestamp,
                    satisfaction_score=satisfaction_score,
                    response_time=response_time,
                    session_metadata=session_metadata,
                )
            )
            profile = self._user_profiles.setdefault(
                user_id,
                {
                    "user_id": user_id,
                    "query_count": 0,
                    "interaction_count": 0,
                    "preferences": {},
                    "expertise_level": 0.5,
                    "interaction_scores": [],
                },
            )
            profile["interaction_count"] += 1
            if satisfaction_score is not None:
                profile["interaction_scores"].append(satisfaction_score)

    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        profile = self._user_profiles.get(user_id)
        if profile:
            return profile
        if self.user_db is not None:
            try:
                if hasattr(self.user_db, "get_user_profile"):
                    return await self.user_db.get_user_profile(user_id)
            except Exception as exc:  # pragma: no cover
                logger.warning("User DB profile fetch failed: %s", exc)
        return {"user_id": user_id, "query_count": 0, "interaction_count": 0}

    async def get_performance_metrics(self, time_period: timedelta) -> dict[str, Any]:
        cutoff = datetime.utcnow() - time_period
        recent = [m for m in self._request_metrics if m["timestamp"] >= cutoff]
        total_requests = len(recent)
        avg_response = (
            sum(m["response_time"] for m in recent) / total_requests
            if total_requests
            else 0.0
        )
        cache_hit_rate = (
            sum(1 for m in recent if m["cache_hit"]) / total_requests
            if total_requests
            else 0.0
        )
        satisfaction_scores = [
            i.satisfaction_score
            for i in self._interactions
            if i.satisfaction_score is not None and i.timestamp >= cutoff
        ]
        avg_satisfaction = (
            sum(satisfaction_scores) / len(satisfaction_scores)
            if satisfaction_scores
            else 0.0
        )
        return {
            "total_requests": total_requests,
            "average_response_time": avg_response if avg_response > 0 else 0.01,
            "cache_hit_rate": cache_hit_rate,
            "user_satisfaction_score": avg_satisfaction,
        }

    async def get_quality_metrics(
        self, user_id: str, time_period: timedelta
    ) -> dict[str, Any]:
        cutoff = datetime.utcnow() - time_period
        user_interactions = [
            i
            for i in self._interactions
            if i.user_id == user_id and i.timestamp >= cutoff
        ]
        scores = [
            i.satisfaction_score
            for i in user_interactions
            if i.satisfaction_score is not None
        ]
        avg_satisfaction = sum(scores) / len(scores) if scores else 0.0
        recommended_queries = [i.recommended_query for i in user_interactions]
        diversity = (
            len(set(recommended_queries)) / len(recommended_queries)
            if recommended_queries
            else 0.0
        )
        coverage = (
            min(1.0, len(set(recommended_queries)) / 5) if recommended_queries else 0.0
        )
        return {
            "average_satisfaction": avg_satisfaction,
            "recommendation_diversity": diversity,
            "coverage_score": coverage,
        }

    async def analyze_user_segments(self, time_period: timedelta) -> dict[str, Any]:
        cutoff = datetime.utcnow() - time_period
        segments: dict[str, list[dict[str, Any]]] = {"general": []}
        for user_id, profile in self._user_profiles.items():
            interactions = [
                i
                for i in self._interactions
                if i.user_id == user_id and i.timestamp >= cutoff
            ]
            avg_satisfaction = (
                sum(
                    i.satisfaction_score
                    for i in interactions
                    if i.satisfaction_score is not None
                )
                / len([i for i in interactions if i.satisfaction_score is not None])
                if interactions
                else 0.0
            )
            segments["general"].append(
                {
                    "user_id": user_id,
                    "avg_satisfaction": avg_satisfaction,
                    "avg_expertise_level": profile.get("expertise_level", 0.5),
                }
            )
        segment_stats = []
        if segments["general"]:
            avg_sat = sum(s["avg_satisfaction"] for s in segments["general"]) / len(
                segments["general"]
            )
            avg_exp = sum(s["avg_expertise_level"] for s in segments["general"]) / len(
                segments["general"]
            )
            segment_stats.append(
                {
                    "segment": "general",
                    "user_count": len(segments["general"]),
                    "avg_satisfaction": avg_sat,
                    "avg_expertise_level": avg_exp,
                }
            )
        return {"segments": segment_stats}

    async def analyze_query_trends(
        self, time_period: timedelta, trend_window: timedelta
    ) -> dict[str, Any]:
        end_time = datetime.utcnow()
        start_time = end_time - time_period
        window_start = end_time - trend_window
        recent_terms: dict[str, int] = {}
        earlier_terms: dict[str, int] = {}

        for record in self._query_history:
            if record.timestamp < start_time:
                continue
            target = recent_terms if record.timestamp >= window_start else earlier_terms
            for token in record.query.lower().split():
                target[token] = target.get(token, 0) + 1

        trending_up = []
        trending_down = []
        all_terms = set(recent_terms) | set(earlier_terms)
        for term in all_terms:
            delta = recent_terms.get(term, 0) - earlier_terms.get(term, 0)
            if delta > 0:
                trending_up.append(term)
            elif delta < 0:
                trending_down.append(term)

        if not trending_up and recent_terms:
            trending_up = sorted(recent_terms, key=recent_terms.get, reverse=True)[:5]
        if not trending_down and earlier_terms:
            trending_down = sorted(earlier_terms, key=earlier_terms.get, reverse=True)[
                :5
            ]

        return {"trending_up": trending_up, "trending_down": trending_down}

    async def _build_recommendations(
        self,
        query: str,
        user_id: str | None,
        context: dict[str, Any],
        max_results: int,
    ) -> list[RecommendationResult]:
        results: list[RecommendationResult] = []
        query_lower = query.lower()

        # Vector-based recommendations
        if self.vector_db is not None:
            try:
                embedding = await self.vector_db.embed_query(query)
                similar = await self.vector_db.similarity_search(
                    embedding, k=max_results * 2
                )
                for item in similar:
                    results.append(
                        RecommendationResult(
                            query=item.get("query", ""),
                            relevance_score=float(item.get("score", 0.5)),
                            explanation="Similar to your query",
                            source="vector",
                        )
                    )
            except Exception as exc:
                logger.warning("Vector search failed: %s", exc)

        # History-based fallback
        if len(results) < max_results:
            for record in self._query_history:
                if record.query == query:
                    continue
                overlap = self._lexical_overlap(query_lower, record.query.lower())
                if overlap > 0.1:
                    results.append(
                        RecommendationResult(
                            query=record.query,
                            relevance_score=min(1.0, 0.4 + overlap),
                            explanation="Based on historical queries",
                            source="history",
                        )
                    )

        # Personalization based on user history/context
        if user_id and user_id in self._user_profiles:
            profile = self._user_profiles[user_id]
            preferences = profile.get("preferences", {})

            specializations = self._top_preferences(
                preferences.get("specializations", {}), limit=2
            )
            for specialization in specializations:
                spec_text = specialization.replace("_", " ")
                results.append(
                    RecommendationResult(
                        query=f"{spec_text} methods for {query}",
                        relevance_score=0.94,
                        explanation=f"Tailored to your {spec_text} focus",
                        source="personalized",
                        metadata={"specialization": specialization},
                    )
                )
                results.append(
                    RecommendationResult(
                        query=f"Best practices in {spec_text} studies",
                        relevance_score=0.92,
                        explanation=f"Aligned with your {spec_text} specialization",
                        source="personalized",
                        metadata={"specialization": specialization},
                    )
                )

            tools = self._top_preferences(preferences.get("tools", {}), limit=1)
            for tool in tools:
                results.append(
                    RecommendationResult(
                        query=f"{tool.upper()} pipeline for {query}",
                        relevance_score=0.91,
                        explanation=f"Based on your preference for {tool.upper()}",
                        source="personalized",
                        metadata={"tool_preference": tool},
                    )
                )

            keywords = self._top_preferences(preferences.get("keywords", {}), limit=2)
            for keyword in keywords:
                results.append(
                    RecommendationResult(
                        query=f"{keyword} analysis for {query}",
                        relevance_score=0.9,
                        explanation=f"Personalized based on your interest in {keyword}",
                        source="personalized",
                        metadata={"keyword": keyword},
                    )
                )

        # Generic fallbacks
        if not results:
            seed_terms = [
                "analysis",
                "preprocessing",
                "connectivity",
                "quality control",
            ]
            for term in seed_terms:
                results.append(
                    RecommendationResult(
                        query=f"{term.title()} methods for {query}",
                        relevance_score=0.5,
                        explanation="General recommendation",
                        source="fallback",
                    )
                )

        # Context-based adjustments
        setting = context.get("setting")
        experience = context.get("experience_level")
        if setting == "clinical" or experience == "beginner":
            results.append(
                RecommendationResult(
                    query=f"Clinical-ready workflow for {query}",
                    relevance_score=0.96,
                    explanation="Prioritized for clinical settings",
                    source="context",
                )
            )
        if setting == "research" or experience == "expert":
            results.append(
                RecommendationResult(
                    query=f"Research-grade {query} pipeline",
                    relevance_score=0.95,
                    explanation="Prioritized for research settings",
                    source="context",
                )
            )

        # Deduplicate and sort
        seen = set()
        unique_results: list[RecommendationResult] = []
        for rec in results:
            if rec.query and rec.query not in seen:
                seen.add(rec.query)
                unique_results.append(rec)

        unique_results.sort(key=lambda r: r.relevance_score, reverse=True)
        return unique_results[:max_results]

    def _lexical_overlap(self, a: str, b: str) -> float:
        words_a = set(a.split())
        words_b = set(b.split())
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / len(words_a | words_b)

    def _make_cache_key(
        self, query: str, user_id: str | None, context: dict[str, Any]
    ) -> str:
        context_key = (
            "|".join(f"{k}={context[k]}" for k in sorted(context)) if context else ""
        )
        return f"{user_id}:{query}:{context_key}"

    def _set_cache(self, key: str, value: list[RecommendationResult]) -> None:
        if key in self._cache:
            return
        if len(self._cache_order) >= self.cache_size:
            oldest = self._cache_order.pop(0)
            self._cache.pop(oldest, None)
        self._cache[key] = value
        self._cache_order.append(key)

    def _invalidate_cache_for_user(self, user_id: str) -> None:
        prefix = f"{user_id}:"
        stale_keys = [key for key in self._cache if key.startswith(prefix)]
        for key in stale_keys:
            self._cache.pop(key, None)
            if key in self._cache_order:
                self._cache_order.remove(key)

    def _top_preferences(self, prefs: dict[str, int], limit: int) -> list[str]:
        if not prefs:
            return []
        return sorted(prefs, key=prefs.get, reverse=True)[:limit]

    def _record_request_metrics(self, cache_hit: bool) -> None:
        self._request_metrics.append(
            {
                "timestamp": datetime.utcnow(),
                "cache_hit": cache_hit,
                "response_time": 0.01,
            }
        )

    def _get_next_step_recommendations(
        self, query: str, limit: int = 2
    ) -> list[Recommendation]:
        """Get recommendations for logical next steps."""
        recommendations = []

        try:
            # Analyze current query to identify likely next steps
            next_steps = self._infer_next_steps(query)

            for step_query, confidence in next_steps[:limit]:
                rec = Recommendation(
                    query=step_query,
                    confidence=confidence,
                    reason="Common next step in analysis workflow",
                    category="next_step",
                    metadata={"workflow_position": "follow_up"},
                )
                recommendations.append(rec)

        except Exception as e:
            logger.warning(f"Failed to get next step recommendations: {e}")

        return recommendations

    def _get_popular_recommendations(
        self, query: str, limit: int = 2
    ) -> list[Recommendation]:
        """Get popular queries related to the current domain."""
        recommendations = []

        try:
            # Determine query domain
            domain = self._infer_domain(query)

            # Get popular patterns for this domain
            popular_patterns = self.pattern_analyzer.get_popular_patterns(limit=10)
            domain_patterns = [p for p in popular_patterns if domain in p.domains]

            for pattern in domain_patterns[:limit]:
                if pattern.example_queries:
                    example_query = pattern.example_queries[0]
                    confidence = min(pattern.frequency / 100.0, 0.8)  # Scale frequency

                    rec = Recommendation(
                        query=example_query,
                        confidence=confidence,
                        reason=f"Popular {domain} analysis",
                        category="popular",
                        metadata={
                            "pattern_id": pattern.pattern_id,
                            "frequency": pattern.frequency,
                            "success_rate": pattern.success_rate,
                        },
                    )
                    recommendations.append(rec)

        except Exception as e:
            logger.warning(f"Failed to get popular recommendations: {e}")

        return recommendations

    def _personalize_recommendations(
        self, recommendations: list[Recommendation], user_id: str, query: str
    ) -> list[Recommendation]:
        """Apply personalization to recommendations based on user profile."""
        if user_id not in self.user_profiles:
            return recommendations  # No personalization data

        profile = self.user_profiles[user_id]

        # Adjust confidence based on user preferences
        for rec in recommendations:
            # Domain preference adjustment
            rec_domain = self._infer_domain(rec.query)
            if rec_domain in profile.preferred_domains:
                domain_boost = profile.preferred_domains[rec_domain] * 0.2
                rec.confidence = min(rec.confidence + domain_boost, 1.0)

            # Complexity preference adjustment
            rec_complexity = self._estimate_complexity(rec.query)
            complexity_diff = abs(rec_complexity - profile.query_complexity_preference)
            complexity_penalty = complexity_diff * 0.1
            rec.confidence = max(rec.confidence - complexity_penalty, 0.1)

            # Add personalization metadata
            rec.metadata["personalized"] = True
            rec.metadata["user_id"] = user_id

        return recommendations

    def _infer_next_steps(self, query: str) -> list[tuple[str, float]]:
        """Infer logical next steps based on the current query."""
        query_lower = query.lower()
        next_steps = []

        # Rule-based next step inference
        if "preprocess" in query_lower:
            next_steps.extend(
                [
                    ("Run GLM analysis on preprocessed data", 0.8),
                    ("Perform quality control checks", 0.7),
                ]
            )
        elif "glm" in query_lower or "activation" in query_lower:
            next_steps.extend(
                [
                    ("Create statistical maps visualization", 0.8),
                    ("Perform group-level analysis", 0.7),
                    ("Extract ROI time series for connectivity", 0.6),
                ]
            )
        elif "connectivity" in query_lower:
            next_steps.extend(
                [
                    ("Analyze network properties", 0.8),
                    ("Compare connectivity between groups", 0.7),
                ]
            )
        elif "classify" in query_lower or "decode" in query_lower:
            next_steps.extend(
                [
                    ("Evaluate classifier performance", 0.9),
                    ("Create feature importance maps", 0.8),
                ]
            )
        elif "visualiz" in query_lower:
            next_steps.extend(
                [
                    ("Generate publication-ready figures", 0.7),
                    ("Create interactive brain plots", 0.6),
                ]
            )
        else:
            # Generic next steps
            next_steps.extend(
                [
                    ("Visualize the analysis results", 0.6),
                    ("Perform statistical testing", 0.5),
                ]
            )

        return next_steps

    def _infer_domain(self, query: str) -> str:
        """Infer the domain of a query."""
        query_lower = query.lower()

        domain_keywords = {
            "fmri": ["fmri", "bold", "activation", "glm"],
            "connectivity": ["connectivity", "network", "correlation", "functional"],
            "structural": ["structural", "anatomy", "morphometry", "vbm"],
            "preprocessing": ["preprocess", "motion", "registration", "normalization"],
            "statistics": ["statistics", "test", "comparison", "contrast"],
            "machine_learning": [
                "classify",
                "decode",
                "predict",
                "svm",
                "machine learning",
            ],
            "visualization": ["plot", "visualiz", "display", "render"],
        }

        for domain, keywords in domain_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                return domain

        return "general"

    def _estimate_complexity(self, query: str) -> float:
        """Estimate query complexity (0=simple, 1=complex)."""
        complexity_factors = [
            len(query.split()) / 30.0,  # Length factor
            query.count("and") * 0.1,  # Multiple conditions
            query.count("?") * 0.1,  # Multiple questions
            int("compare" in query.lower() or "contrast" in query.lower()) * 0.2,
            int("machine learning" in query.lower() or "classify" in query.lower())
            * 0.3,
        ]

        return min(sum(complexity_factors), 1.0)

    def _generate_explanation(
        self, recommendation: Recommendation, original_query: str
    ) -> str:
        """Generate explanation for why this recommendation was made."""
        if recommendation.category == "similar":
            return f"This query is similar to your current one about {self._infer_domain(original_query)} analysis"
        elif recommendation.category == "next_step":
            return "This is a common next step after your current analysis"
        elif recommendation.category == "popular":
            freq = recommendation.metadata.get("frequency", 0)
            return f"This is a popular analysis (used {freq} times) in this domain"
        else:
            return "Recommended based on analysis patterns"

    def update_user_profile(
        self,
        user_id: str,
        query: str,
        tools_used: list[str],
        execution_time: float,
        success: bool,
    ):
        """
        Update user profile based on query execution.

        Args:
            user_id: User identifier
            query: Executed query
            tools_used: Tools used in execution
            execution_time: Time taken
            success: Whether execution was successful
        """
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = UserProfile(user_id=user_id)

        profile = self.user_profiles[user_id]

        # Update domain preferences
        domain = self._infer_domain(query)
        if domain not in profile.preferred_domains:
            profile.preferred_domains[domain] = 0.0
        profile.preferred_domains[domain] = 0.9 * profile.preferred_domains[
            domain
        ] + 0.1 * (1.0 if success else 0.5)

        # Update tool preferences
        for tool in tools_used:
            if tool not in profile.preferred_tools:
                profile.preferred_tools[tool] = 0.0
            profile.preferred_tools[tool] = 0.9 * profile.preferred_tools[tool] + 0.1

        # Update complexity preference
        query_complexity = self._estimate_complexity(query)
        if success:
            # Move preference toward successful complexity levels
            profile.query_complexity_preference = (
                0.9 * profile.query_complexity_preference + 0.1 * query_complexity
            )

        # Update common keywords
        keywords = [word.lower() for word in query.split() if len(word) > 3]
        for keyword in keywords:
            profile.common_keywords[keyword] = (
                profile.common_keywords.get(keyword, 0) + 1
            )

        # Update success rate by category
        category = self._infer_domain(query)
        if category not in profile.success_rate_by_category:
            profile.success_rate_by_category[category] = 0.0

        profile.success_rate_by_category[category] = (
            0.9 * profile.success_rate_by_category[category]
            + 0.1 * (1.0 if success else 0.0)
        )

        profile.last_updated = datetime.now()

        # Also update global pattern analyzer
        self.pattern_analyzer.add_query_execution(
            query, tools_used, execution_time, success, domain
        )

    def get_trending_topics(self, limit: int = 5) -> list[dict[str, Any]]:
        """Get currently trending analysis topics."""
        # Calculate recent trend scores
        now = datetime.now()
        trending = []

        for topic, count in self.trending_topics.items():
            # Simple trending calculation (could be more sophisticated)
            trend_score = count / max(1, (now - datetime.now()).days + 1)
            trending.append(
                {"topic": topic, "count": count, "trend_score": trend_score}
            )

        trending.sort(key=lambda x: x["trend_score"], reverse=True)
        return trending[:limit]

    def add_query_feedback(
        self, query: str, recommended_query: str, user_id: str | None, helpful: bool
    ):
        """
        Record feedback on a recommendation.

        Args:
            query: Original query
            recommended_query: Query that was recommended
            user_id: User who provided feedback
            helpful: Whether the recommendation was helpful
        """
        # Update recommendation quality metrics
        # This could be used to improve future recommendations

        if helpful:
            # Increase similarity threshold for similar recommendations
            similarity = self.similarity_engine.calculate_similarity(
                query, recommended_query
            )
            logger.info(f"Positive feedback: similarity={similarity:.3f}")
        else:
            logger.info("Negative feedback recorded")

        # Could also update user preferences based on feedback


# Factory function
def create_recommendation_engine(
    embedding_model=None, history_store=None
) -> QueryRecommendationEngine:
    """
    Create a query recommendation engine instance.

    Args:
        embedding_model: Embedding model for semantic similarity
        history_store: Storage for query history

    Returns:
        Configured recommendation engine
    """
    return QueryRecommendationEngine(embedding_model, history_store)
