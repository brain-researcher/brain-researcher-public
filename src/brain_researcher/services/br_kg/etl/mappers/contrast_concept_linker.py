#!/usr/bin/env python3
"""Contrast → Concept linker with multi-source weights."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add the parent directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from brain_researcher.services.br_kg.etl.loaders.ca_task_concept_loader import (
        load_task_concept_weights,
    )
    from brain_researcher.services.br_kg.utils.task_matcher import TaskMatcher
except ImportError:
    # For running as a script from brain_researcher.services.br_kg directory
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from brain_researcher.core.utils.task_matcher import TaskMatcher
    from brain_researcher.services.br_kg.etl.loaders.ca_task_concept_loader import (
        load_task_concept_weights,
    )

logger = logging.getLogger(__name__)

# Constants for weight types
CSV_WEIGHT = "csv_w"
LLM_WEIGHT = "llm_w"
PUBMED_WEIGHT = "pubmed_w"
WEIGHT_TYPES = [CSV_WEIGHT, LLM_WEIGHT, PUBMED_WEIGHT]
WEIGHT_SOURCES = {CSV_WEIGHT: "csv", LLM_WEIGHT: "llm", PUBMED_WEIGHT: "pubmed"}


class ContrastConceptLinker:
    """Link Contrasts to Concepts using multiple evidence sources."""

    def __init__(
        self,
        ca_weights_path: str | Path | None = None,
        matcher: TaskMatcher | None = None,
    ) -> None:
        try:
            self.matcher = matcher or TaskMatcher()
        except Exception as e:
            logger.warning(
                f"Failed to initialize TaskMatcher: {e}. Falling back to None."
            )
            self.matcher = None

        try:
            self.ca_weights = load_task_concept_weights(
                Path(ca_weights_path) if ca_weights_path else None
            )
        except Exception as e:
            logger.error(f"Failed to load CA weights from {ca_weights_path}: {e}")
            self.ca_weights = {}

        self.seen_pairs: set[tuple[str, str]] = set()
        self._task_cache: dict[str, str | None] = {}  # Cache for task matching results
        self.stats = {
            "total_contrasts": 0,
            "linked_contrasts": 0,
            "total_edges_created": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

    # ------------------------------------------------------------------
    def _match_task(self, task_name: str) -> str | None:
        """Match task name to canonical form with caching."""
        if not task_name:
            return None

        # Check cache first
        if task_name in self._task_cache:
            self.stats["cache_hits"] += 1
            return self._task_cache[task_name]

        # import pdb; pdb.set_trace()
        self.stats["cache_misses"] += 1

        # Perform matching if matcher is available
        result = None
        if self.matcher:
            try:
                hits = self.matcher.match_candidates(task_name, top_k=1)
                result = hits[0]["label"].lower() if hits else None
            except Exception as e:
                logger.warning(f"Task matching failed for '{task_name}': {e}")

        # Cache the result
        self._task_cache[task_name] = result
        return result

    # ------------------------------------------------------------------
    def _merge_weights(
        self,
        contrast: dict[str, Any],
        canonical_task: str | None,
        original_task: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Merge weights from multiple sources efficiently."""

        # Initialize with default structure
        def default_weights():
            return {wt: 0.0 for wt in WEIGHT_TYPES}

        weights: dict[str, dict[str, Any]] = defaultdict(default_weights)

        # Add CSV weights if available
        # Try canonical task first, then original task (lowercased)
        task_to_check = canonical_task
        if not task_to_check and original_task:
            task_to_check = original_task.lower()

        if task_to_check and task_to_check in self.ca_weights:
            task_weights = self.ca_weights[task_to_check]
            for concept, w in task_weights.items():
                weights[concept][CSV_WEIGHT] = w
        elif original_task and original_task.lower() in self.ca_weights:
            # Fallback: always check original task lowercased even if canonical exists
            task_weights = self.ca_weights[original_task.lower()]
            for concept, w in task_weights.items():
                weights[concept][CSV_WEIGHT] = w

        # Add weights from contrast concepts
        concepts = contrast.get("concepts", [])
        for c in concepts:
            if not isinstance(c, dict):
                logger.warning(f"Invalid concept format: {c}")
                continue

            name = c.get("name", "").lower()
            if not name:
                continue

            # Update weights
            concept_weights = weights[name]
            concept_weights[LLM_WEIGHT] = float(c.get(LLM_WEIGHT, 0.0))
            concept_weights[PUBMED_WEIGHT] = float(c.get(PUBMED_WEIGHT, 0.0))

            # Store concept ID if available
            concept_id = c.get("concept_id")
            if concept_id:
                concept_weights["concept_id"] = concept_id

        return dict(weights)

    # ------------------------------------------------------------------
    def link_contrast(self, contrast: dict[str, Any]) -> list[dict[str, Any]]:
        contrast_id = contrast.get("contrast_id")
        task = contrast.get("task")
        canonical = self._match_task(task)
        # Pass both canonical and original task name to merge_weights
        weights = self._merge_weights(contrast, canonical, task)

        edges: list[dict[str, Any]] = []
        timestamp = datetime.now(timezone.utc).isoformat()
        for name, vals in weights.items():
            concept_id = vals.get("concept_id")
            if not contrast_id or not concept_id:
                continue
            pair = (contrast_id, concept_id)
            if pair in self.seen_pairs:
                continue
            self.seen_pairs.add(pair)
            # Build properties efficiently
            props = {wt: vals.get(wt, 0.0) for wt in WEIGHT_TYPES}

            # Add sources list
            props["sources"] = [
                WEIGHT_SOURCES[wt] for wt in WEIGHT_TYPES if vals.get(wt, 0.0) > 0
            ]

            props["method"] = "multi_source"
            props["timestamp"] = timestamp
            edges.append(
                {
                    "start_node": contrast_id,
                    "end_node": concept_id,
                    "type": "HAS_CONCEPT",
                    "properties": props,
                }
            )
        if edges:
            self.stats["linked_contrasts"] += 1
        self.stats["total_contrasts"] += 1
        self.stats["total_edges_created"] += len(edges)
        return edges

    # ------------------------------------------------------------------
    def link_from_annotations(
        self, annotations: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Process multiple annotations and return all edges."""
        if not isinstance(annotations, list):
            logger.error(
                f"Invalid annotations format: expected list, got {type(annotations)}"
            )
            return []

        all_edges: list[dict[str, Any]] = []
        for i, contrast in enumerate(annotations):
            try:
                edges = self.link_contrast(contrast)
                all_edges.extend(edges)
            except Exception as e:
                logger.error(f"Failed to process contrast {i}: {e}")
                continue

        return all_edges

    # ------------------------------------------------------------------
    def get_stats_summary(self) -> str:
        """Get comprehensive statistics summary."""
        cache_rate = (
            self.stats["cache_hits"]
            / max(self.stats["cache_hits"] + self.stats["cache_misses"], 1)
            * 100
        )
        return (
            f"Total contrasts: {self.stats['total_contrasts']}, "
            f"linked: {self.stats['linked_contrasts']}, "
            f"edges: {self.stats['total_edges_created']}, "
            f"cache hit rate: {cache_rate:.1f}%"
        )


# ----------------------------------------------------------------------
def _run_sample():
    """Run a small sample demonstration for testing."""
    linker = ContrastConceptLinker()

    sample_contrasts = [
        (
            "contrast_001",
            {
                "name": "nback_2back_vs_0back",
                "task_name": "n-back task",
                "task_label": "nback",
                "description": "2-back vs 0-back contrast",
            },
        ),
        (
            "contrast_002",
            {
                "name": "faces_vs_shapes",
                "task_name": "face matching",
                "task_label": "faces",
                "description": "Faces vs shapes contrast",
            },
        ),
        (
            "contrast_003",
            {
                "name": "stroop_incongruent_vs_congruent",
                "task_name": "stroop task",
                "task_label": "stroop",
                "description": "Incongruent vs congruent",
            },
        ),
    ]

    sample_concepts = [
        ("concept_001", {"name": "working memory"}),
        ("concept_002", {"name": "attention"}),
        ("concept_003", {"name": "emotion"}),
        ("concept_004", {"name": "face recognition"}),
        ("concept_005", {"name": "executive control"}),
        ("concept_006", {"name": "response inhibition"}),
    ]

    logger.info("Testing ContrastConceptLinker with sample data...")

    # The new linker doesn't have link_batch, need to transform data
    sample_annotations = []
    for contrast_id, contrast_data in sample_contrasts:
        annotation = {
            "contrast_id": contrast_id,
            "task": contrast_data.get("task_name", ""),
            "concepts": [],
        }
        # For demo, just add some dummy concepts
        if "nback" in contrast_data.get("name", ""):
            annotation["concepts"].append(
                {
                    "concept_id": "concept_001",
                    "name": "working memory",
                    "llm_w": 0.8,
                    "pubmed_w": 0.5,
                }
            )
        elif "face" in contrast_data.get("name", ""):
            annotation["concepts"].append(
                {
                    "concept_id": "concept_004",
                    "name": "face recognition",
                    "llm_w": 0.9,
                    "pubmed_w": 0.4,
                }
            )
        elif "stroop" in contrast_data.get("name", ""):
            annotation["concepts"].append(
                {
                    "concept_id": "concept_006",
                    "name": "response inhibition",
                    "llm_w": 0.7,
                    "pubmed_w": 0.6,
                }
            )
        sample_annotations.append(annotation)

    all_edges = linker.link_from_annotations(sample_annotations)
    print(linker.get_stats_summary())

    for edge in all_edges:
        logger.info(
            f"  Edge created: {edge['start_node']} -> {edge['end_node']} "
            f"(csv_w: {edge['properties'].get('csv_w', 0):.2f}, "
            f"llm_w: {edge['properties'].get('llm_w', 0):.2f}, "
            f"pubmed_w: {edge['properties'].get('pubmed_w', 0):.2f})"
        )


# ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> None:
    """CLI entry point for contrast-concept linking."""
    parser = argparse.ArgumentParser(description="Link contrasts to concepts")
    parser.add_argument("--input", help="JSON annotations file")
    parser.add_argument(
        "--ca-tsv",
        default="data/ca_task_concept_weights.tsv",
        help="Task→concept weight TSV",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument(
        "--sample", action="store_true", help="Run a sample demonstration"
    )
    args = parser.parse_args(argv)

    # Configure logging
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Handle sample mode
    if args.sample:
        _run_sample()
        return

    # Regular mode requires input file
    if not args.input:
        parser.error("--input is required when not using --sample")

    try:
        with open(args.input) as f:
            annotations = json.load(f)
    except FileNotFoundError:
        logger.error(f"Input file not found: {args.input}")
        return
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {args.input}: {e}")
        return

    linker = ContrastConceptLinker(args.ca_tsv)
    edges = linker.link_from_annotations(annotations)

    # Print results
    print(json.dumps(edges, indent=2))

    # Log statistics
    logger.info(linker.get_stats_summary())


if __name__ == "__main__":
    main()
