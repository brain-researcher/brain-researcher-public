"""
Memory Store for parsing, indexing, and searching project memories.

This module handles:
- Loading memory files from markdown with YAML frontmatter
- Building keyword and semantic indices
- Searching memories by various criteria
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


@dataclass
class Memory:
    """Represents a single memory with metadata and content."""

    id: str
    type: str
    scope: str  # codebase, research, ops
    confidence: float
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    applies_when: list[str] = field(default_factory=list)
    avoid_when: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    provenance: list[str] = field(default_factory=list)
    created: datetime | None = None
    updated: datetime | None = None
    owner: str | None = None
    decay_half_life_days: int = 180
    llm_prompt: str | None = None
    file_path: Path | None = None

    @property
    def decay_factor(self) -> float:
        """Calculate decay factor based on age and half-life."""
        if not self.updated:
            return 1.0

        age_days = (datetime.now() - self.updated).days
        return 0.5 ** (age_days / self.decay_half_life_days)

    @property
    def effective_confidence(self) -> float:
        """Confidence adjusted for decay."""
        return self.confidence * self.decay_factor


class MemoryStore:
    """Manages loading, indexing, and searching of memory files."""

    def __init__(self, root_path: str = "memory/"):
        """
        Initialize the memory store.

        Args:
            root_path: Path to memory directory
        """
        self.root_path = Path(root_path)
        self.memories: list[Memory] = []
        self.keyword_index: dict[str, list[int]] = {}
        self.tag_index: dict[str, list[int]] = {}
        self.scope_index: dict[str, list[int]] = {}

        # Initialize embedding model for semantic search
        self._init_embedding_model()

        # Load memories on initialization
        if self.root_path.exists():
            self.load()

    def _init_embedding_model(self):
        """Initialize the sentence transformer model."""
        try:
            self.encoder = SentenceTransformer("all-MiniLM-L6-v2")
            self.embeddings = None
            logger.info("Initialized embedding model: all-MiniLM-L6-v2")
        except Exception as e:
            logger.warning(f"Could not initialize embedding model: {e}")
            self.encoder = None
            self.embeddings = None

    def load(self) -> list[Memory]:
        """
        Load all memory files from the root directory.

        Returns:
            List of loaded Memory objects
        """
        self.memories.clear()

        # Find all markdown files recursively
        memory_files = list(self.root_path.glob("**/*.md"))

        for file_path in memory_files:
            # Skip README files
            if file_path.name.lower() == "readme.md":
                continue

            try:
                memory = self._parse_memory_file(file_path)
                if memory:
                    self.memories.append(memory)
                    logger.debug(f"Loaded memory: {memory.id}")
            except Exception as e:
                logger.error(f"Error loading {file_path}: {e}")

        # Build indices after loading
        self.build_index()

        logger.info(f"Loaded {len(self.memories)} memories from {self.root_path}")
        return self.memories

    def _parse_memory_file(self, file_path: Path) -> Memory | None:
        """
        Parse a single memory file with YAML frontmatter and markdown content.

        Args:
            file_path: Path to the memory file

        Returns:
            Parsed Memory object or None if parsing fails
        """
        content = file_path.read_text(encoding="utf-8")

        # Extract YAML frontmatter
        yaml_match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
        if not yaml_match:
            logger.warning(f"No YAML frontmatter found in {file_path}")
            return None

        yaml_content = yaml_match.group(1)
        markdown_content = yaml_match.group(2)

        try:
            metadata = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in {file_path}: {e}")
            return None

        # Extract title from first markdown heading
        title_match = re.search(r"^#\s+(.+)$", markdown_content, re.MULTILINE)
        title = title_match.group(1) if title_match else file_path.stem

        # Extract LLM prompt fragment
        llm_prompt = None
        prompt_match = re.search(
            r">\s*House Rule:\s*(.+?)(?:\n\n|$)", markdown_content, re.DOTALL
        )
        if prompt_match:
            llm_prompt = prompt_match.group(1).strip()

        # Parse dates
        created = self._parse_date(metadata.get("created"))
        updated = self._parse_date(metadata.get("updated"))

        return Memory(
            id=metadata.get("id", file_path.stem),
            type=metadata.get("type", "memory"),
            scope=metadata.get("scope", "codebase"),
            confidence=metadata.get("confidence", 0.5),
            title=title,
            content=markdown_content,
            tags=metadata.get("tags", []),
            applies_when=metadata.get("applies_when", []),
            avoid_when=metadata.get("avoid_when", []),
            related=metadata.get("related", []),
            provenance=metadata.get("provenance", []),
            created=created,
            updated=updated,
            owner=metadata.get("owner"),
            decay_half_life_days=metadata.get("decay_half_life_days", 180),
            llm_prompt=llm_prompt,
            file_path=file_path,
        )

    def _parse_date(self, date_str: Any) -> datetime | None:
        """Parse date from various formats."""
        if not date_str:
            return None

        if isinstance(date_str, datetime):
            return date_str

        if isinstance(date_str, str):
            try:
                return datetime.fromisoformat(date_str)
            except:
                try:
                    return datetime.strptime(date_str, "%Y-%m-%d")
                except:
                    pass

        return None

    def build_index(self):
        """Build keyword, tag, and scope indices for fast searching."""
        self.keyword_index.clear()
        self.tag_index.clear()
        self.scope_index.clear()

        for idx, memory in enumerate(self.memories):
            # Build tag index
            for tag in memory.tags:
                if tag not in self.tag_index:
                    self.tag_index[tag] = []
                self.tag_index[tag].append(idx)

            # Build scope index
            if memory.scope not in self.scope_index:
                self.scope_index[memory.scope] = []
            self.scope_index[memory.scope].append(idx)

            # Build keyword index from title and content
            text = f"{memory.title} {memory.content}".lower()
            words = re.findall(r"\w+", text)
            for word in set(words):
                if len(word) > 2:  # Skip very short words
                    if word not in self.keyword_index:
                        self.keyword_index[word] = []
                    self.keyword_index[word].append(idx)

        # Build embeddings if model is available
        if self.encoder and self.memories:
            texts = [f"{m.title}\n{m.content[:500]}" for m in self.memories]
            self.embeddings = self.encoder.encode(texts)
            logger.info(f"Built embeddings for {len(self.memories)} memories")

    def search(
        self,
        query: str = "",
        tags: list[str] | None = None,
        scope: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 10,
    ) -> list[Memory]:
        """
        Search memories using multiple criteria.

        Args:
            query: Text query for keyword/semantic search
            tags: Filter by tags
            scope: Filter by scope (codebase/research/ops)
            min_confidence: Minimum effective confidence
            limit: Maximum number of results

        Returns:
            List of matching memories sorted by relevance
        """
        candidates = set(range(len(self.memories)))

        # Filter by scope
        if scope:
            candidates &= set(self.scope_index.get(scope, []))

        # Filter by tags
        if tags:
            for tag in tags:
                if tag in self.tag_index:
                    candidates &= set(self.tag_index[tag])

        # Filter by confidence
        candidates = {
            idx
            for idx in candidates
            if self.memories[idx].effective_confidence >= min_confidence
        }

        # Score candidates
        scores = {}
        for idx in candidates:
            memory = self.memories[idx]
            score = memory.effective_confidence

            # Keyword matching
            if query:
                query_words = set(re.findall(r"\w+", query.lower()))
                text_words = set(
                    re.findall(r"\w+", f"{memory.title} {memory.content}".lower())
                )
                overlap = len(query_words & text_words)
                score += overlap * 0.1

            scores[idx] = score

        # Add semantic similarity if available
        if query and self.encoder and self.embeddings is not None:
            query_embedding = self.encoder.encode([query])
            similarities = np.dot(self.embeddings, query_embedding.T).flatten()
            for idx in candidates:
                scores[idx] += similarities[idx] * 0.5

        # Sort by score and return top results
        sorted_indices = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        return [self.memories[idx] for idx in sorted_indices[:limit]]

    def get_by_id(self, memory_id: str) -> Memory | None:
        """Get a specific memory by ID."""
        for memory in self.memories:
            if memory.id == memory_id:
                return memory
        return None

    def get_related(self, memory: Memory, max_depth: int = 2) -> list[Memory]:
        """
        Get related memories following the relationship graph.

        Args:
            memory: Starting memory
            max_depth: Maximum relationship depth to follow

        Returns:
            List of related memories
        """
        visited = {memory.id}
        related = []
        queue = [(memory, 0)]

        while queue:
            current, depth = queue.pop(0)

            if depth >= max_depth:
                continue

            for rel in current.related:
                # Extract memory reference from [[...]] syntax
                match = re.search(r"\[\[([^\]]+)\]\]", rel)
                if match:
                    ref_title = match.group(1)
                    # Find memory by title
                    for m in self.memories:
                        if m.title == ref_title and m.id not in visited:
                            visited.add(m.id)
                            related.append(m)
                            queue.append((m, depth + 1))

        return related

    def save_index(self, index_path: Path | None = None):
        """Save the index to a JSON file for faster loading."""
        if index_path is None:
            index_path = self.root_path / "index.json"

        index_data = {
            "memories": [
                {
                    "id": m.id,
                    "title": m.title,
                    "tags": m.tags,
                    "scope": m.scope,
                    "confidence": m.confidence,
                    "file_path": str(m.file_path) if m.file_path else None,
                }
                for m in self.memories
            ],
            "keyword_index": self.keyword_index,
            "tag_index": self.tag_index,
            "scope_index": self.scope_index,
            "generated": datetime.now().isoformat(),
        }

        with open(index_path, "w") as f:
            json.dump(index_data, f, indent=2)

        logger.info(f"Saved index to {index_path}")
