"""
TF-IDF based tool search index for intent-to-tool mapping.

This module provides a searchable index over neuroimaging tools, supporting:
- TF-IDF vectorization of tool names, descriptions, and tags
- Synonym expansion for better query matching
- Ranked search results with similarity scores
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np


@dataclass
class ToolEntry:
    """
    Metadata for a single neuroimaging tool.

    Attributes:
        id: Unique tool identifier (e.g., "fsl.bet", "afni.3dSkullStrip")
        name: Human-readable tool name
        description: What the tool does
        tags: Categorization tags (e.g., ["skull-strip", "preprocessing"])
        image: Container image path (optional)
        aliases: Alternative names for the tool
        category: Tool category (e.g., "preprocessing", "analysis")
    """

    id: str
    name: str
    description: str
    tags: List[str] = field(default_factory=list)
    image: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    category: Optional[str] = None


class ToolIndex:
    """
    Searchable index of neuroimaging tools using TF-IDF.

    The index vectorizes tool metadata (name + description + tags + aliases)
    and supports semantic search with optional synonym expansion.
    """

    def __init__(
        self,
        entries: List[ToolEntry],
        synonyms: Optional[Dict[str, List[str]]] = None,
    ):
        """
        Build a TF-IDF index from tool entries.

        Args:
            entries: List of tool metadata entries
            synonyms: Optional mapping of terms to synonyms for query expansion
        """
        self.entries = entries
        self.synonyms = synonyms or {}

        # Build corpus: concatenate name, description, tags, and aliases
        self.corpus = [
            self._build_document(entry) for entry in entries
        ]

        # Create TF-IDF vectorizer with bigrams for better phrase matching
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            lowercase=True,
            stop_words="english",
            max_features=5000,
        )

        # Fit and transform corpus
        self.matrix = self.vectorizer.fit_transform(self.corpus)

    def _build_document(self, entry: ToolEntry) -> str:
        """
        Build a searchable text document from tool metadata.

        We weight the name more heavily by repeating it, and include
        all aliases and tags for better matching.
        """
        parts = [
            entry.name,  # Primary name
            entry.name,  # Repeat for higher weight
            entry.description,
            " ".join(entry.tags),
            " ".join(entry.aliases),
        ]

        # Add synonyms for tags to improve matching
        expanded_tags = []
        for tag in entry.tags:
            expanded_tags.append(tag)
            if tag.lower() in self.synonyms:
                expanded_tags.extend(self.synonyms[tag.lower()])

        if expanded_tags:
            parts.append(" ".join(expanded_tags))

        # Add category if present
        if entry.category:
            parts.append(entry.category)

        return " ".join(filter(None, parts))

    def _expand_query(self, query: str) -> str:
        """
        Expand query with synonyms for better matching.

        Example: "skull strip" -> "skull strip brain extraction BET"
        """
        # Normalize query
        query = query.lower().strip()

        # Split into tokens and expand each
        tokens = re.split(r'\s+', query)
        expanded = [query]  # Include original query

        for token in tokens:
            if token in self.synonyms:
                expanded.extend(self.synonyms[token])

        # Also check for multi-word phrases
        if query in self.synonyms:
            expanded.extend(self.synonyms[query])

        return " ".join(expanded)

    def search(self, query: str, k: int = 8) -> List[Tuple[ToolEntry, float]]:
        """
        Search for tools matching the query.

        Args:
            query: Natural language intent (e.g., "skull strip")
            k: Number of top results to return

        Returns:
            List of (ToolEntry, similarity_score) tuples, sorted by score descending
        """
        if not query or not query.strip():
            return []

        # Expand query with synonyms
        expanded_query = self._expand_query(query)

        # Transform query to TF-IDF vector
        query_vec = self.vectorizer.transform([expanded_query])

        # Compute cosine similarity
        similarities = cosine_similarity(query_vec, self.matrix).ravel()

        # Get top-k indices
        top_indices = np.argsort(similarities)[::-1][:k]

        # Filter out zero scores
        results = [
            (self.entries[idx], float(similarities[idx]))
            for idx in top_indices
            if similarities[idx] > 0
        ]

        return results

    def get_tool_by_id(self, tool_id: str) -> Optional[ToolEntry]:
        """
        Retrieve a tool entry by its ID.

        Args:
            tool_id: Tool identifier

        Returns:
            ToolEntry if found, None otherwise
        """
        for entry in self.entries:
            if entry.id == tool_id:
                return entry
        return None

    def get_tools_by_category(self, category: str) -> List[ToolEntry]:
        """
        Get all tools in a specific category.

        Args:
            category: Category name (e.g., "preprocessing")

        Returns:
            List of tools in that category
        """
        return [
            entry for entry in self.entries
            if entry.category and entry.category.lower() == category.lower()
        ]


__all__ = ["ToolEntry", "ToolIndex"]
