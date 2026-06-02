"""Collaborative Filtering Recommendation System - implements KG-025.

This module provides recommendation capabilities based on graph patterns,
user similarity, item similarity, and hybrid approaches.
"""

import heapq
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from scipy.sparse import csr_matrix
from scipy.spatial.distance import cosine

logger = logging.getLogger(__name__)


@dataclass
class UserProfile:
    """Represents a user profile for recommendations."""

    user_id: str
    interactions: Dict[str, float]  # item_id -> rating/weight
    preferences: Dict[str, Any] = field(default_factory=dict)
    history: List[Tuple[str, str, float]] = field(
        default_factory=list
    )  # (item_id, timestamp, rating)


@dataclass
class RecommendationResult:
    """Represents a recommendation result."""

    item_id: str
    score: float
    explanation: str
    evidence: List[str] = field(default_factory=list)
    confidence: float = 1.0


class CollaborativeFiltering:
    """Collaborative filtering recommendation system."""

    def __init__(self, neo4j_driver, min_interactions: int = 5):
        """Initialize collaborative filtering.

        Args:
            neo4j_driver: Neo4j driver instance
            min_interactions: Minimum interactions for recommendations
        """
        self.driver = neo4j_driver
        self.min_interactions = min_interactions

        # Caches
        self.user_profiles = {}
        self.item_features = {}
        self.similarity_cache = {}
        self.pattern_cache = {}

    def build_user_profile(self, user_id: str) -> UserProfile:
        """Build user profile from interactions.

        Args:
            user_id: User ID

        Returns:
            UserProfile object
        """
        if user_id in self.user_profiles:
            return self.user_profiles[user_id]

        with self.driver.session() as session:
            # Get user interactions
            query = """
            MATCH (u:User {id: $user_id})-[r:INTERACTED|VIEWED|RATED|DOWNLOADED]->(item)
            RETURN item.id as item_id,
                   type(r) as interaction_type,
                   r.rating as rating,
                   r.timestamp as timestamp,
                   labels(item) as item_types
            ORDER BY r.timestamp DESC
            """

            result = session.run(query, {"user_id": user_id})

            interactions = {}
            history = []

            for record in result:
                item_id = record["item_id"]
                interaction_type = record["interaction_type"]
                rating = record.get("rating", 1.0)
                timestamp = record.get("timestamp", "")

                # Weight by interaction type
                weight = self._get_interaction_weight(interaction_type, rating)
                interactions[item_id] = weight
                history.append((item_id, timestamp, weight))

            # Get user preferences
            pref_query = """
            MATCH (u:User {id: $user_id})
            RETURN u.preferences as preferences
            """
            pref_result = session.run(pref_query, {"user_id": user_id}).single()
            preferences = pref_result["preferences"] if pref_result else {}

        profile = UserProfile(
            user_id=user_id,
            interactions=interactions,
            preferences=preferences,
            history=history,
        )

        self.user_profiles[user_id] = profile
        return profile

    def _get_interaction_weight(
        self, interaction_type: str, rating: Optional[float]
    ) -> float:
        """Get weight for an interaction type.

        Args:
            interaction_type: Type of interaction
            rating: Optional explicit rating

        Returns:
            Interaction weight
        """
        if rating is not None:
            return rating

        weights = {"RATED": 1.0, "DOWNLOADED": 0.8, "VIEWED": 0.5, "INTERACTED": 0.3}

        return weights.get(interaction_type, 0.5)

    def recommend_by_user_similarity(
        self, user_id: str, top_k: int = 10, similarity_threshold: float = 0.3
    ) -> List[RecommendationResult]:
        """Recommend items based on similar users.

        Args:
            user_id: User ID
            top_k: Number of recommendations
            similarity_threshold: Minimum similarity

        Returns:
            List of recommendations
        """
        profile = self.build_user_profile(user_id)

        if len(profile.interactions) < self.min_interactions:
            logger.warning(f"User {user_id} has insufficient interactions")
            return []

        # Find similar users
        similar_users = self._find_similar_users(user_id, similarity_threshold)

        if not similar_users:
            return []

        # Aggregate recommendations from similar users
        item_scores = defaultdict(float)
        item_evidence = defaultdict(list)

        for similar_user_id, similarity in similar_users:
            similar_profile = self.build_user_profile(similar_user_id)

            for item_id, weight in similar_profile.interactions.items():
                if (
                    item_id not in profile.interactions
                ):  # Don't recommend already interacted items
                    item_scores[item_id] += similarity * weight
                    item_evidence[item_id].append(
                        f"User {similar_user_id} (sim: {similarity:.2f})"
                    )

        # Sort and create recommendations
        recommendations = []
        for item_id, score in sorted(
            item_scores.items(), key=lambda x: x[1], reverse=True
        )[:top_k]:
            recommendations.append(
                RecommendationResult(
                    item_id=item_id,
                    score=score,
                    explanation=f"Recommended based on {len(item_evidence[item_id])} similar users",
                    evidence=item_evidence[item_id][:3],  # Top 3 evidence
                    confidence=min(1.0, score),
                )
            )

        return recommendations

    def _find_similar_users(
        self, user_id: str, threshold: float = 0.3
    ) -> List[Tuple[str, float]]:
        """Find users similar to given user.

        Args:
            user_id: User ID
            threshold: Similarity threshold

        Returns:
            List of (user_id, similarity) tuples
        """
        cache_key = f"similar_users:{user_id}"
        if cache_key in self.similarity_cache:
            return self.similarity_cache[cache_key]

        profile = self.build_user_profile(user_id)

        with self.driver.session() as session:
            # Find users with overlapping interactions
            query = """
            MATCH (u1:User {id: $user_id})-[:INTERACTED|VIEWED|RATED|DOWNLOADED]->(item)
            <-[:INTERACTED|VIEWED|RATED|DOWNLOADED]-(u2:User)
            WHERE u2.id <> $user_id
            WITH u2, count(DISTINCT item) as common_items
            WHERE common_items >= $min_common
            RETURN u2.id as user_id, common_items
            """

            result = session.run(query, {"user_id": user_id, "min_common": 3})

            similar_users = []

            for record in result:
                other_user_id = record["user_id"]
                other_profile = self.build_user_profile(other_user_id)

                # Calculate similarity
                similarity = self._calculate_user_similarity(profile, other_profile)

                if similarity >= threshold:
                    similar_users.append((other_user_id, similarity))

        # Sort by similarity
        similar_users.sort(key=lambda x: x[1], reverse=True)

        self.similarity_cache[cache_key] = similar_users[:20]  # Cache top 20
        return similar_users

    def _calculate_user_similarity(
        self, profile1: UserProfile, profile2: UserProfile
    ) -> float:
        """Calculate similarity between two users.

        Args:
            profile1: First user profile
            profile2: Second user profile

        Returns:
            Similarity score (0-1)
        """
        # Get common items
        common_items = set(profile1.interactions.keys()) & set(
            profile2.interactions.keys()
        )

        if len(common_items) < 2:
            return 0.0

        # Calculate cosine similarity on common items
        vec1 = np.array([profile1.interactions[item] for item in common_items])
        vec2 = np.array([profile2.interactions[item] for item in common_items])

        if np.all(vec1 == 0) or np.all(vec2 == 0):
            return 0.0

        similarity = 1 - cosine(vec1, vec2)

        # Adjust for number of common items
        overlap_bonus = min(1.0, len(common_items) / 10)

        return similarity * (0.7 + 0.3 * overlap_bonus)

    def recommend_by_item_similarity(
        self, user_id: str, top_k: int = 10, similarity_threshold: float = 0.3
    ) -> List[RecommendationResult]:
        """Recommend items based on item similarity.

        Args:
            user_id: User ID
            top_k: Number of recommendations
            similarity_threshold: Minimum similarity

        Returns:
            List of recommendations
        """
        profile = self.build_user_profile(user_id)

        if len(profile.interactions) < self.min_interactions:
            return []

        # Get candidate items based on similarity to user's items
        item_scores = defaultdict(float)
        item_evidence = defaultdict(list)

        for seed_item_id, weight in profile.interactions.items():
            similar_items = self._find_similar_items(seed_item_id, similarity_threshold)

            for similar_item_id, similarity in similar_items:
                if similar_item_id not in profile.interactions:
                    item_scores[similar_item_id] += weight * similarity
                    item_evidence[similar_item_id].append(
                        f"Similar to {seed_item_id} (sim: {similarity:.2f})"
                    )

        # Sort and create recommendations
        recommendations = []
        for item_id, score in sorted(
            item_scores.items(), key=lambda x: x[1], reverse=True
        )[:top_k]:
            recommendations.append(
                RecommendationResult(
                    item_id=item_id,
                    score=score,
                    explanation=f"Similar to items you've interacted with",
                    evidence=item_evidence[item_id][:3],
                    confidence=min(1.0, score / len(profile.interactions)),
                )
            )

        return recommendations

    def _find_similar_items(
        self, item_id: str, threshold: float = 0.3
    ) -> List[Tuple[str, float]]:
        """Find items similar to given item.

        Args:
            item_id: Item ID
            threshold: Similarity threshold

        Returns:
            List of (item_id, similarity) tuples
        """
        cache_key = f"similar_items:{item_id}"
        if cache_key in self.similarity_cache:
            return self.similarity_cache[cache_key]

        with self.driver.session() as session:
            # Find items with common properties/relationships
            query = """
            MATCH (i1 {id: $item_id})
            MATCH (i1)-[r1]-(common)-[r2]-(i2)
            WHERE i2.id <> $item_id AND labels(i1) = labels(i2)
            WITH i2,
                 count(DISTINCT common) as common_connections,
                 collect(DISTINCT type(r1) + '-' + type(r2)) as path_types
            RETURN i2.id as item_id,
                   i2.name as name,
                   common_connections,
                   path_types
            ORDER BY common_connections DESC
            LIMIT 50
            """

            result = session.run(query, {"item_id": item_id})

            similar_items = []

            for record in result:
                other_item_id = record["item_id"]
                common_connections = record["common_connections"]

                # Calculate similarity based on connections
                similarity = min(1.0, common_connections / 10)

                if similarity >= threshold:
                    similar_items.append((other_item_id, similarity))

        self.similarity_cache[cache_key] = similar_items[:20]
        return similar_items

    def recommend_by_patterns(
        self, user_id: str, top_k: int = 10
    ) -> List[RecommendationResult]:
        """Recommend based on graph patterns.

        Args:
            user_id: User ID
            top_k: Number of recommendations

        Returns:
            List of recommendations
        """
        profile = self.build_user_profile(user_id)

        # Extract patterns from user's interaction history
        patterns = self._extract_user_patterns(user_id)

        if not patterns:
            return []

        # Find items matching patterns
        item_scores = defaultdict(float)
        item_evidence = defaultdict(list)

        for pattern in patterns:
            matching_items = self._find_items_matching_pattern(
                pattern, profile.interactions.keys()
            )

            for item_id, match_score in matching_items:
                item_scores[item_id] += pattern["weight"] * match_score
                item_evidence[item_id].append(
                    f"Matches pattern: {pattern['description']}"
                )

        # Sort and create recommendations
        recommendations = []
        for item_id, score in sorted(
            item_scores.items(), key=lambda x: x[1], reverse=True
        )[:top_k]:
            recommendations.append(
                RecommendationResult(
                    item_id=item_id,
                    score=score,
                    explanation="Based on your interaction patterns",
                    evidence=item_evidence[item_id][:3],
                    confidence=min(1.0, score),
                )
            )

        return recommendations

    def _extract_user_patterns(self, user_id: str) -> List[Dict[str, Any]]:
        """Extract patterns from user's interactions.

        Args:
            user_id: User ID

        Returns:
            List of patterns
        """
        cache_key = f"user_patterns:{user_id}"
        if cache_key in self.pattern_cache:
            return self.pattern_cache[cache_key]

        patterns = []

        with self.driver.session() as session:
            # Pattern 1: Co-occurrence patterns
            query1 = """
            MATCH (u:User {id: $user_id})-[:INTERACTED|VIEWED|RATED]->(i1)
            -[:RELATES_TO|SIMILAR_TO|CO_OCCURS]-(i2)
            <-[:INTERACTED|VIEWED|RATED]-(u)
            WITH i1, i2, count(*) as frequency
            WHERE frequency > 1
            RETURN 'co-occurrence' as pattern_type,
                   collect({item1: i1.id, item2: i2.id}) as instances,
                   avg(frequency) as weight
            """

            result1 = session.run(query1, {"user_id": user_id})
            for record in result1:
                if record["instances"]:
                    patterns.append(
                        {
                            "type": "co-occurrence",
                            "instances": record["instances"],
                            "weight": record["weight"],
                            "description": "Items frequently accessed together",
                        }
                    )

            # Pattern 2: Sequential patterns
            query2 = """
            MATCH (u:User {id: $user_id})-[r1:INTERACTED|VIEWED]->(i1)
            MATCH (u)-[r2:INTERACTED|VIEWED]->(i2)
            WHERE r1.timestamp < r2.timestamp
            AND duration.between(r1.timestamp, r2.timestamp).days < 7
            WITH i1, i2, count(*) as frequency
            WHERE frequency > 1
            RETURN 'sequential' as pattern_type,
                   collect({from: i1.id, to: i2.id}) as instances,
                   avg(frequency) as weight
            """

            try:
                result2 = session.run(query2, {"user_id": user_id})
                for record in result2:
                    if record["instances"]:
                        patterns.append(
                            {
                                "type": "sequential",
                                "instances": record["instances"],
                                "weight": record["weight"],
                                "description": "Sequential access patterns",
                            }
                        )
            except:
                pass  # Sequential pattern may not work without proper timestamp format

            # Pattern 3: Category preferences
            query3 = """
            MATCH (u:User {id: $user_id})-[:INTERACTED|VIEWED|RATED]->(item)
            WITH labels(item) as categories, count(*) as count
            WHERE count > 2
            RETURN categories, count as weight
            """

            result3 = session.run(query3, {"user_id": user_id})
            for record in result3:
                patterns.append(
                    {
                        "type": "category",
                        "categories": record["categories"],
                        "weight": record["weight"] / 10,  # Normalize
                        "description": f"Preference for {record['categories']}",
                    }
                )

        self.pattern_cache[cache_key] = patterns
        return patterns

    def _find_items_matching_pattern(
        self, pattern: Dict[str, Any], exclude_items: Set[str]
    ) -> List[Tuple[str, float]]:
        """Find items matching a pattern.

        Args:
            pattern: Pattern dictionary
            exclude_items: Items to exclude

        Returns:
            List of (item_id, score) tuples
        """
        matching_items = []

        with self.driver.session() as session:
            if pattern["type"] == "co-occurrence":
                # Find items that co-occur with pattern instances
                for instance in pattern["instances"][:5]:  # Limit to top 5
                    query = """
                    MATCH (i1 {id: $item_id})-[:RELATES_TO|SIMILAR_TO|CO_OCCURS]-(i2)
                    WHERE i2.id NOT IN $exclude
                    RETURN i2.id as item_id, 1.0 as score
                    LIMIT 10
                    """
                    result = session.run(
                        query,
                        {"item_id": instance["item1"], "exclude": list(exclude_items)},
                    )

                    for record in result:
                        matching_items.append((record["item_id"], record["score"]))

            elif pattern["type"] == "category":
                # Find items in same categories
                query = """
                MATCH (item)
                WHERE ANY(label IN labels(item) WHERE label IN $categories)
                AND item.id NOT IN $exclude
                RETURN item.id as item_id, 1.0 as score
                LIMIT 20
                """
                result = session.run(
                    query,
                    {
                        "categories": pattern["categories"],
                        "exclude": list(exclude_items),
                    },
                )

                for record in result:
                    matching_items.append((record["item_id"], record["score"]))

        return matching_items

    def hybrid_recommend(
        self, user_id: str, top_k: int = 10, weights: Optional[Dict[str, float]] = None
    ) -> List[RecommendationResult]:
        """Hybrid recommendation combining multiple approaches.

        Args:
            user_id: User ID
            top_k: Number of recommendations
            weights: Weights for different approaches

        Returns:
            List of recommendations
        """
        if weights is None:
            weights = {"user_similarity": 0.3, "item_similarity": 0.4, "patterns": 0.3}

        all_recommendations = defaultdict(
            lambda: {"score": 0, "explanations": [], "evidence": [], "confidence": []}
        )

        # Get recommendations from each method
        if weights.get("user_similarity", 0) > 0:
            user_recs = self.recommend_by_user_similarity(user_id, top_k * 2)
            for rec in user_recs:
                all_recommendations[rec.item_id]["score"] += (
                    rec.score * weights["user_similarity"]
                )
                all_recommendations[rec.item_id]["explanations"].append(
                    f"User-based: {rec.explanation}"
                )
                all_recommendations[rec.item_id]["evidence"].extend(rec.evidence)
                all_recommendations[rec.item_id]["confidence"].append(rec.confidence)

        if weights.get("item_similarity", 0) > 0:
            item_recs = self.recommend_by_item_similarity(user_id, top_k * 2)
            for rec in item_recs:
                all_recommendations[rec.item_id]["score"] += (
                    rec.score * weights["item_similarity"]
                )
                all_recommendations[rec.item_id]["explanations"].append(
                    f"Item-based: {rec.explanation}"
                )
                all_recommendations[rec.item_id]["evidence"].extend(rec.evidence)
                all_recommendations[rec.item_id]["confidence"].append(rec.confidence)

        if weights.get("patterns", 0) > 0:
            pattern_recs = self.recommend_by_patterns(user_id, top_k * 2)
            for rec in pattern_recs:
                all_recommendations[rec.item_id]["score"] += (
                    rec.score * weights["patterns"]
                )
                all_recommendations[rec.item_id]["explanations"].append(
                    f"Pattern-based: {rec.explanation}"
                )
                all_recommendations[rec.item_id]["evidence"].extend(rec.evidence)
                all_recommendations[rec.item_id]["confidence"].append(rec.confidence)

        # Combine and rank
        final_recommendations = []
        for item_id, data in sorted(
            all_recommendations.items(), key=lambda x: x[1]["score"], reverse=True
        )[:top_k]:
            final_recommendations.append(
                RecommendationResult(
                    item_id=item_id,
                    score=data["score"],
                    explanation=" | ".join(data["explanations"]),
                    evidence=list(set(data["evidence"]))[:5],  # Unique evidence
                    confidence=(
                        np.mean(data["confidence"]) if data["confidence"] else 0.5
                    ),
                )
            )

        return final_recommendations

    def evaluate_recommendations(
        self,
        user_id: str,
        recommendations: List[RecommendationResult],
        ground_truth: List[str],
    ) -> Dict[str, float]:
        """Evaluate recommendation quality.

        Args:
            user_id: User ID
            recommendations: List of recommendations
            ground_truth: Actual items user interacted with

        Returns:
            Evaluation metrics
        """
        if not ground_truth:
            return {}

        recommended_ids = [rec.item_id for rec in recommendations]

        # Calculate metrics
        k = len(recommendations)

        # Precision@K
        hits = sum(1 for item_id in recommended_ids if item_id in ground_truth)
        precision = hits / k if k > 0 else 0

        # Recall@K
        recall = hits / len(ground_truth) if ground_truth else 0

        # F1 Score
        f1 = (
            2 * (precision * recall) / (precision + recall)
            if (precision + recall) > 0
            else 0
        )

        # Mean Reciprocal Rank (MRR)
        mrr = 0
        for i, item_id in enumerate(recommended_ids):
            if item_id in ground_truth:
                mrr = 1 / (i + 1)
                break

        # Normalized Discounted Cumulative Gain (NDCG)
        dcg = sum(
            1 / np.log2(i + 2)
            for i, item_id in enumerate(recommended_ids)
            if item_id in ground_truth
        )

        idcg = sum(1 / np.log2(i + 2) for i in range(min(k, len(ground_truth))))
        ndcg = dcg / idcg if idcg > 0 else 0

        # Coverage
        profile = self.build_user_profile(user_id)
        coverage = (
            len(set(recommended_ids) - set(profile.interactions.keys())) / k
            if k > 0
            else 0
        )

        return {
            "precision_at_k": precision,
            "recall_at_k": recall,
            "f1_score": f1,
            "mrr": mrr,
            "ndcg": ndcg,
            "coverage": coverage,
            "k": k,
        }
