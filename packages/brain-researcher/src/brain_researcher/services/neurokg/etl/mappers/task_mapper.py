#!/usr/bin/env python3
"""
TaskSpec to TaskDef Mapper

This module provides mapping functionality between TaskSpec nodes (from OpenNeuro)
and TaskDef nodes (from Cognitive Atlas) using multiple matching strategies:
1. Exact matching
2. Fuzzy string matching
3. NiCLIP synonym-based matching

Author: BR-KG Team
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from fuzzywuzzy import fuzz, process

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaskMapper:
    """Maps TaskSpec nodes to TaskDef nodes using multiple strategies"""

    def __init__(
        self,
        config_path: str = "configs/legacy/task_mapping.yaml",
        synonym_cache_path: str = "cache/niclip_synonyms.json",
    ):
        """
        Initialize mapper with configuration and synonym cache

        Args:
            config_path: Path to task mapping configuration file
            synonym_cache_path: Path to NiCLIP synonym cache
        """
        # Load configuration
        self.config = self._load_config(config_path)

        # Load NiCLIP synonyms
        self.synonyms = self._load_synonyms(synonym_cache_path)

        # Build task definition lookup
        self.task_defs = {}  # To be populated from database

        # Initialize stats
        self.stats = {
            "total_mapped": 0,
            "exact_matches": 0,
            "fuzzy_matches": 0,
            "niclip_matches": 0,
            "unmatched": 0,
            "blacklisted": 0,
        }

        # Unmatched tasks log
        self.unmatched_tasks = []

    def _load_config(self, config_path: str) -> dict[str, Any]:
        """Load configuration from YAML file"""
        with open(config_path) as f:
            return yaml.safe_load(f)

    def _load_synonyms(self, synonym_cache_path: str) -> dict[str, Any]:
        """Load NiCLIP synonym dictionary"""
        if not os.path.exists(synonym_cache_path):
            logger.warning(f"Synonym cache not found at {synonym_cache_path}")
            return {}

        with open(synonym_cache_path) as f:
            return json.load(f)

    def set_task_definitions(self, task_defs: list[tuple[str, dict[str, Any]]]):
        """
        Set available TaskDef nodes from database

        Args:
            task_defs: List of (node_id, node_data) tuples
        """
        self.task_defs = {}

        for task_id, task_data in task_defs:
            name = task_data.get("name", "").lower()

            # Store by normalized name
            self.task_defs[name] = {
                "id": task_id,
                "name": task_data.get("name", ""),
                "definition": task_data.get("definition", ""),
                "data": task_data,
            }

            # Also store by aliases if available
            if "alias" in task_data and task_data["alias"]:
                alias = task_data["alias"].lower()
                self.task_defs[alias] = self.task_defs[name]

        logger.info(f"Loaded {len(self.task_defs)} task definitions")

    def normalize_task_name(self, name: str) -> str:
        """
        Normalize task name according to configuration rules

        Args:
            name: Raw task name

        Returns:
            Normalized task name
        """
        normalized = name.lower().strip()

        # Apply suffix removals
        for suffix in self.config["name_normalizations"]["remove_suffixes"]:
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)].strip()

        # Apply replacements
        for pattern, replacement in self.config["name_normalizations"][
            "replacements"
        ].items():
            normalized = normalized.replace(pattern.lower(), replacement)

        return normalized

    def is_blacklisted(self, name: str) -> bool:
        """Check if task name is in blacklist"""
        name_lower = name.lower()
        return any(
            blacklisted in name_lower for blacklisted in self.config["blacklist"]
        )

    def find_exact_match(self, task_spec_name: str) -> str | None:
        """
        Find exact match for task spec name

        Returns:
            TaskDef node ID if found, None otherwise
        """
        normalized_name = self.normalize_task_name(task_spec_name)

        if normalized_name in self.task_defs:
            return self.task_defs[normalized_name]["id"]

        return None

    def find_fuzzy_match(self, task_spec_name: str) -> tuple[str, float] | None:
        """
        Find fuzzy match for task spec name

        Returns:
            Tuple of (TaskDef node ID, similarity score) if found, None otherwise
        """
        normalized_name = self.normalize_task_name(task_spec_name)
        threshold = (
            self.config["thresholds"]["fuzzy_match"] * 100
        )  # fuzzywuzzy uses 0-100

        # Get all task def names
        task_def_names = list(self.task_defs.keys())

        if not task_def_names:
            return None

        # Find best match
        result = process.extractOne(normalized_name, task_def_names, scorer=fuzz.ratio)

        if result and result[1] >= threshold:
            match_name = result[0]
            return (self.task_defs[match_name]["id"], result[1] / 100.0)

        return None

    def find_niclip_match(self, task_spec_name: str) -> tuple[str, float] | None:
        """
        Find match using NiCLIP synonyms

        Returns:
            Tuple of (TaskDef node ID, confidence) if found, None otherwise
        """
        if not self.synonyms:
            return None

        normalized_name = self.normalize_task_name(task_spec_name)
        min_confidence = self.config["thresholds"]["niclip_confidence"]

        # Check variant lookup
        variant_lookup = self.synonyms.get("variant_lookup", {})

        if normalized_name in variant_lookup:
            # Get best matching canonical task
            for mapping in variant_lookup[normalized_name]:
                canonical = mapping["canonical"]
                confidence = mapping["confidence"]

                if confidence >= min_confidence:
                    # Check if canonical task exists in task defs
                    if canonical in self.task_defs:
                        return (self.task_defs[canonical]["id"], confidence)

        # Check direct synonyms
        synonyms_dict = self.synonyms.get("synonyms", {})

        if normalized_name in synonyms_dict:
            syn_info = synonyms_dict[normalized_name]
            confidence = syn_info.get("confidence", 0)

            if confidence >= min_confidence:
                # Check if this task exists in task defs
                if normalized_name in self.task_defs:
                    return (self.task_defs[normalized_name]["id"], confidence)

        return None

    def map_task(
        self, task_spec_name: str, task_spec_data: dict[str, Any] = None
    ) -> dict[str, Any] | None:
        """
        Map a single TaskSpec to TaskDef

        Args:
            task_spec_name: Name of the task spec
            task_spec_data: Optional additional task spec data

        Returns:
            Mapping result with TaskDef ID and match info, or None if no match
        """
        # Check blacklist
        if self.is_blacklisted(task_spec_name):
            self.stats["blacklisted"] += 1
            logger.debug(f"Task '{task_spec_name}' is blacklisted")
            return None

        # Try exact match first
        exact_match = self.find_exact_match(task_spec_name)
        if exact_match:
            self.stats["exact_matches"] += 1
            self.stats["total_mapped"] += 1
            return {
                "task_def_id": exact_match,
                "match_type": "exact",
                "confidence": 1.0,
                "original_name": task_spec_name,
            }

        # Try fuzzy match
        fuzzy_result = self.find_fuzzy_match(task_spec_name)
        if fuzzy_result:
            task_def_id, score = fuzzy_result
            self.stats["fuzzy_matches"] += 1
            self.stats["total_mapped"] += 1
            return {
                "task_def_id": task_def_id,
                "match_type": "fuzzy",
                "confidence": score,
                "original_name": task_spec_name,
            }

        # Try NiCLIP match
        niclip_result = self.find_niclip_match(task_spec_name)
        if niclip_result:
            task_def_id, confidence = niclip_result
            self.stats["niclip_matches"] += 1
            self.stats["total_mapped"] += 1
            return {
                "task_def_id": task_def_id,
                "match_type": "niclip",
                "confidence": confidence,
                "original_name": task_spec_name,
            }

        # No match found
        self.stats["unmatched"] += 1
        self.unmatched_tasks.append(
            {
                "name": task_spec_name,
                "normalized": self.normalize_task_name(task_spec_name),
                "data": task_spec_data,
            }
        )

        logger.debug(f"No match found for task '{task_spec_name}'")
        return None

    def map_batch(
        self, task_specs: list[tuple[str, dict[str, Any]]]
    ) -> dict[str, dict[str, Any]]:
        """
        Map multiple TaskSpecs to TaskDefs

        Args:
            task_specs: List of (task_name, task_data) tuples

        Returns:
            Dictionary mapping task_spec_name to mapping result
        """
        results = {}

        for task_name, task_data in task_specs:
            result = self.map_task(task_name, task_data)
            if result:
                results[task_name] = result

        return results

    def save_unmatched_log(self, output_path: str = None):
        """Save unmatched tasks to TSV file"""
        if output_path is None:
            output_path = self.config["logging"]["unmatched_log"]

        # Ensure directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            f.write("task_name\tnormalized_name\tadditional_info\n")

            for task in self.unmatched_tasks:
                info = json.dumps(task.get("data", {})) if task.get("data") else ""
                f.write(f"{task['name']}\t{task['normalized']}\t{info}\n")

        logger.info(
            f"Saved {len(self.unmatched_tasks)} unmatched tasks to {output_path}"
        )

    def save_stats(self, output_path: str = None):
        """Save mapping statistics to JSON file"""
        if output_path is None:
            output_path = self.config["logging"]["stats_log"]

        # Ensure directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        stats_with_rates = self.stats.copy()

        # Calculate rates
        total_processed = sum(
            [
                self.stats["total_mapped"],
                self.stats["unmatched"],
                self.stats["blacklisted"],
            ]
        )

        if total_processed > 0:
            stats_with_rates["mapping_rate"] = (
                self.stats["total_mapped"] / total_processed
            )
            stats_with_rates["unmatched_rate"] = (
                self.stats["unmatched"] / total_processed
            )
            stats_with_rates["blacklist_rate"] = (
                self.stats["blacklisted"] / total_processed
            )

        # Add method distribution
        if self.stats["total_mapped"] > 0:
            stats_with_rates["method_distribution"] = {
                "exact": self.stats["exact_matches"] / self.stats["total_mapped"],
                "fuzzy": self.stats["fuzzy_matches"] / self.stats["total_mapped"],
                "niclip": self.stats["niclip_matches"] / self.stats["total_mapped"],
            }

        with open(output_path, "w") as f:
            json.dump(stats_with_rates, f, indent=2)

        logger.info(f"Saved mapping statistics to {output_path}")

    def get_stats_summary(self) -> str:
        """Get human-readable statistics summary"""
        total_processed = sum(
            [
                self.stats["total_mapped"],
                self.stats["unmatched"],
                self.stats["blacklisted"],
            ]
        )

        if total_processed == 0:
            return "No tasks processed yet"

        summary = f"""
Task Mapping Summary:
--------------------
Total processed: {total_processed}
Successfully mapped: {self.stats['total_mapped']} ({self.stats['total_mapped']/total_processed*100:.1f}%)
  - Exact matches: {self.stats['exact_matches']}
  - Fuzzy matches: {self.stats['fuzzy_matches']}
  - NiCLIP matches: {self.stats['niclip_matches']}
Unmatched: {self.stats['unmatched']} ({self.stats['unmatched']/total_processed*100:.1f}%)
Blacklisted: {self.stats['blacklisted']} ({self.stats['blacklisted']/total_processed*100:.1f}%)
"""
        return summary


# Example usage and testing
if __name__ == "__main__":
    import sys

    # Add parent directory to path
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )

    # Initialize mapper
    mapper = TaskMapper()

    # Test with sample data
    logger.info("Testing TaskMapper with sample data...")

    # Create sample task definitions (simulating database content)
    sample_task_defs = [
        (
            "task_001",
            {
                "name": "n-back task",
                "definition": "Working memory task",
                "labels": ["TaskDef"],
            },
        ),
        (
            "task_002",
            {
                "name": "stroop task",
                "definition": "Attention/inhibition task",
                "labels": ["TaskDef"],
            },
        ),
        (
            "task_003",
            {
                "name": "go/no-go task",
                "definition": "Response inhibition task",
                "alias": "gonogo",
                "labels": ["TaskDef"],
            },
        ),
    ]

    mapper.set_task_definitions(sample_task_defs)

    # Test various task spec names
    test_cases = [
        "n-back",  # Should match exactly after normalization
        "N-Back Task",  # Should match exactly after normalization
        "stroop_task",  # Should match exactly after normalization
        "go-no-go",  # Should match via normalization rules
        "GoNoGo",  # Should match via alias
        "working memory task",  # Should match via NiCLIP if available
        "some_unknown_task",  # Should not match
        "test_task",  # Should be blacklisted
        "practice",  # Should be blacklisted
    ]

    logger.info("\nTesting individual mappings:")
    for task_name in test_cases:
        result = mapper.map_task(task_name)
        if result:
            logger.info(
                f"  {task_name} -> {result['match_type']} match (confidence: {result['confidence']:.2f})"
            )
        else:
            logger.info(f"  {task_name} -> No match")

    # Print summary
    print(mapper.get_stats_summary())

    # Save logs
    mapper.save_unmatched_log("logs/test_unmatched.tsv")
    mapper.save_stats("logs/test_stats.json")
