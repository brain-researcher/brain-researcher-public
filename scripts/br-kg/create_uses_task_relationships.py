#!/usr/bin/env python3
"""
Create USES_TASK relationships between Study and Task nodes.

This script analyzes study abstracts and titles to identify which tasks are used,
creating USES_TASK relationships between Study and Task nodes.
"""

import logging
import os
import re
import sys
from difflib import SequenceMatcher

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.neo4j_utils import require_neo4j_db
from graph.neo4j_graph_database import Neo4jGraphDB

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


class StudyTaskLinker:
    """Links studies to tasks they use based on text analysis."""

    def __init__(self, db: Neo4jGraphDB):
        self.db = db
        self.task_cache = {}
        self.created_count = 0
        self.skipped_count = 0

    def load_tasks(self) -> dict[str, dict]:
        """Load all Task nodes and create search index."""
        logger.info("Loading Task nodes...")

        tasks = self.db.find_nodes(labels="Task")

        task_dict = {}
        for task_node_id, task_data in tasks:
            task_id = task_data.get("id", task_node_id)
            name = task_data.get("name", "")
            desc = task_data.get("description", "")

            # Create search terms from task name
            # Remove common words and create variations
            search_terms = self._create_search_terms(name)

            task_dict[task_id] = {
                "node_id": task_node_id,
                "name": name,
                "description": desc,
                "search_terms": search_terms,
            }

        logger.info(f"Loaded {len(task_dict)} tasks")
        return task_dict

    def _create_search_terms(self, task_name: str) -> set[str]:
        """Create search terms from task name."""
        # Common words to remove
        stopwords = {
            "task",
            "test",
            "paradigm",
            "experiment",
            "cognitive",
            "the",
            "a",
            "an",
            "of",
            "in",
            "for",
            "and",
            "or",
        }

        # Clean and split task name
        name_lower = task_name.lower()
        words = re.findall(r"\b\w+\b", name_lower)

        # Remove stopwords
        meaningful_words = [w for w in words if w not in stopwords and len(w) > 2]

        search_terms = set()

        # Add full name
        search_terms.add(name_lower)

        # Add meaningful word combinations
        if len(meaningful_words) >= 2:
            # Add pairs
            for i in range(len(meaningful_words) - 1):
                search_terms.add(f"{meaningful_words[i]} {meaningful_words[i+1]}")

        # Add individual meaningful words
        search_terms.update(meaningful_words)

        # Add common variations
        if "memory" in meaningful_words:
            search_terms.update(["working memory", "wm"])
        if "attention" in meaningful_words:
            search_terms.update(["attentional", "attention task"])
        if "stroop" in meaningful_words:
            search_terms.update(["stroop task", "stroop effect"])
        if "go" in meaningful_words and "nogo" in meaningful_words:
            search_terms.update(["go/no-go", "go-nogo", "go no go"])

        return search_terms

    def find_tasks_in_text(self, text: str, task_dict: dict) -> list[tuple[str, float]]:
        """Find task mentions in text with confidence scores."""
        if not text:
            return []

        text_lower = text.lower()
        matches = []

        for task_id, task_info in task_dict.items():
            best_score = 0.0

            # Check each search term
            for term in task_info["search_terms"]:
                if term in text_lower:
                    # Calculate score based on term length and position
                    base_score = len(term) / 50.0  # Longer terms are more specific

                    # Bonus for exact phrase match
                    if f" {term} " in f" {text_lower} ":
                        base_score += 0.2

                    # Bonus for task-related context
                    context_words = [
                        "task",
                        "paradigm",
                        "performed",
                        "used",
                        "completed",
                    ]
                    for ctx in context_words:
                        if (
                            ctx
                            in text_lower[
                                max(0, text_lower.find(term) - 50) : text_lower.find(
                                    term
                                )
                                + 50
                            ]
                        ):
                            base_score += 0.1
                            break

                    best_score = max(best_score, min(base_score, 1.0))

            # Also check for fuzzy matching of full task name
            if len(task_info["name"]) > 5:  # Only for longer names
                similarity = SequenceMatcher(
                    None, task_info["name"].lower(), text_lower
                ).ratio()
                if similarity > 0.8:
                    best_score = max(best_score, similarity)

            if best_score > 0.3:  # Confidence threshold
                matches.append((task_id, best_score))

        # Sort by confidence and return top matches
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:5]  # Max 5 tasks per study

    def create_uses_task_relationships(self, limit: int = None):
        """Create USES_TASK relationships between studies and tasks."""
        logger.info("Creating USES_TASK relationships...")

        # Load tasks
        task_dict = self.load_tasks()
        if not task_dict:
            logger.warning("No tasks found")
            return

        # Get studies
        studies = self.db.find_nodes(labels="Study")
        if limit:
            studies = studies[:limit]

        logger.info(f"Processing {len(studies)} studies...")

        batch_size = 100
        for i in range(0, len(studies), batch_size):
            batch = studies[i : i + batch_size]

            for study_node_id, study_data in batch:
                pmid = study_data.get("pmid", "")
                title = study_data.get("title", "")
                abstract = study_data.get("abstract", "")

                # Combine title and abstract for search
                full_text = f"{title} {abstract}"

                # Find task mentions
                task_matches = self.find_tasks_in_text(full_text, task_dict)

                for task_id, confidence in task_matches:
                    # Get task node ID
                    task_info = task_dict.get(task_id)
                    if not task_info:
                        continue

                    task_node_id = task_info["node_id"]

                    # Check if relationship already exists
                    existing_rels = self.db.find_relationships(
                        start_node=study_node_id,
                        end_node=task_node_id,
                        rel_type="USES_TASK",
                    )

                    if not existing_rels:
                        # Create relationship
                        self.db.create_relationship(
                            study_node_id,
                            task_node_id,
                            "USES_TASK",
                            {"confidence": confidence, "method": "text_analysis"},
                        )
                        self.created_count += 1
                    else:
                        self.skipped_count += 1

            if (i + batch_size) % 500 == 0:
                logger.info(
                    f"Progress: {i + batch_size}/{len(studies)} studies processed"
                )
                logger.info(
                    f"Created {self.created_count} relationships, skipped {self.skipped_count}"
                )

        logger.info(f"Completed: Created {self.created_count} USES_TASK relationships")
        logger.info(f"Skipped {self.skipped_count} existing relationships")


def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(description="Create USES_TASK relationships")
    parser.add_argument(
        "--db-path",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument("--limit", type=int, help="Limit number of studies to process")

    args = parser.parse_args()

    # Get absolute path
    logger.info("Connecting to Neo4j backend for USES_TASK linking")

    # Open database
    db = require_neo4j_db(args.db_path, preload_cache=False)

    try:
        # Create linker
        linker = StudyTaskLinker(db)

        # Create relationships
        linker.create_uses_task_relationships(limit=args.limit)

        # Show final stats
        stats = db.get_stats()
        uses_task_count = stats.get("relationship_types", {}).get("USES_TASK", 0)
        logger.info(f"Total USES_TASK relationships in database: {uses_task_count}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
