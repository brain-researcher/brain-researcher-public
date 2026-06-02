#!/usr/bin/env python3
"""
Example integration of improved task linking in init_database.py

This shows how to properly integrate the enhanced task linking functionality
when loading PubMed data.
"""

import json
import logging
from pathlib import Path

# Example code to add to init_database.py


def load_pubmed_with_task_linking(db, data_dir: str):
    """
    Enhanced PubMed loading with sophisticated task linking.

    This function should replace the existing PubMed loading section
    in init_database.py
    """
    logging.info("\n=== Loading PubMed data with enhanced task linking ===")

    # Import required modules
    from brain_researcher.services.br_kg.etl.loaders.enhanced_pubmed_loader import fetch_pubmed_sample
    from brain_researcher.services.br_kg.etl.pubmed_task_linker_improved import (
        build_comprehensive_task_index,
        ingest_publication_with_tasks,
    )
    from brain_researcher.services.br_kg.etl.task_extraction import extract_tasks_from_metadata

    # Try to import TaskMatcher for advanced matching
    try:
        from brain_researcher.core.utils.task_matcher import TaskMatcher

        task_matcher = TaskMatcher()
        logging.info("Using advanced TaskMatcher for task linking")
    except ImportError:
        task_matcher = None
        logging.info("TaskMatcher not available, using fallback matching")

    try:
        # Fetch PubMed data
        pubmed_file = fetch_pubmed_sample(
            str(data_dir),
            sample_size=5000,
            search_terms=[
                "fMRI",
                "neuroimaging",
                "brain",
                "cognitive",
                "neuroscience",
                # Add task-related search terms
                "working memory task",
                "stroop task",
                "n-back task",
                "cognitive task",
                "behavioral task",
                "experimental paradigm",
            ],
        )
        logging.info(f"PubMed data saved: {pubmed_file}")

        # Build comprehensive task index from all task node types
        logging.info("Building comprehensive task index...")
        task_index = build_comprehensive_task_index(db)
        logging.info(f"Task index contains {len(task_index)} unique task names")

        # Track overall statistics
        overall_stats = {
            "papers_processed": 0,
            "total_tasks_extracted": 0,
            "total_tasks_matched": 0,
            "total_relationships": 0,
            "match_methods": {},
            "all_unmatched_tasks": set(),
        }

        # Load papers with task linking
        if Path(pubmed_file).exists():
            with open(pubmed_file) as f:
                papers = json.load(f)

                logging.info(f"Processing {len(papers)} papers...")

                for i, paper in enumerate(papers):
                    try:
                        # Extract tasks if not already present
                        if "tasks" not in paper or not paper["tasks"]:
                            paper["tasks"] = extract_tasks_from_metadata(
                                paper.get("title", ""),
                                paper.get("abstract", ""),
                                paper.get("mesh_terms", []),
                                paper.get("keywords", []),
                            )

                        # Ingest publication with task linking
                        pub_id, stats = ingest_publication_with_tasks(
                            db, paper, task_index, task_matcher
                        )

                        # Update overall statistics
                        overall_stats["papers_processed"] += 1
                        overall_stats["total_tasks_extracted"] += stats[
                            "tasks_extracted"
                        ]
                        overall_stats["total_tasks_matched"] += stats["tasks_matched"]
                        overall_stats["total_relationships"] += stats[
                            "relationships_created"
                        ]

                        for method, count in stats["match_methods"].items():
                            overall_stats["match_methods"][method] = (
                                overall_stats["match_methods"].get(method, 0) + count
                            )

                        overall_stats["all_unmatched_tasks"].update(
                            stats["unmatched_tasks"]
                        )

                        # Progress logging
                        if (i + 1) % 100 == 0:
                            logging.info(f"  Processed {i + 1} papers...")

                    except Exception as e:
                        logging.error(
                            f"Failed to process paper {paper.get('pmid', 'unknown')}: {e}"
                        )

                # Report final statistics
                logging.info("\n=== PubMed Task Linking Statistics ===")
                logging.info(f"Papers processed: {overall_stats['papers_processed']}")
                logging.info(
                    f"Total tasks extracted: {overall_stats['total_tasks_extracted']}"
                )
                logging.info(
                    f"Total tasks matched: {overall_stats['total_tasks_matched']}"
                )
                logging.info(
                    f"Total USES_PARADIGM relationships: {overall_stats['total_relationships']}"
                )

                if overall_stats["total_tasks_extracted"] > 0:
                    match_rate = (
                        overall_stats["total_tasks_matched"]
                        / overall_stats["total_tasks_extracted"]
                    ) * 100
                    logging.info(f"Overall match rate: {match_rate:.1f}%")

                logging.info("\nMatching methods used:")
                for method, count in sorted(overall_stats["match_methods"].items()):
                    logging.info(f"  {method}: {count}")

                # Log some unmatched tasks for vocabulary improvement
                if overall_stats["all_unmatched_tasks"]:
                    unmatched_sample = list(overall_stats["all_unmatched_tasks"])[:20]
                    logging.info(
                        f"\nSample of unmatched tasks ({len(overall_stats['all_unmatched_tasks'])} total):"
                    )
                    for task in unmatched_sample:
                        logging.info(f"  - {task}")

                    # Optionally save all unmatched tasks for analysis
                    unmatched_file = Path(data_dir) / "unmatched_tasks.txt"
                    with open(unmatched_file, "w") as f:
                        for task in sorted(overall_stats["all_unmatched_tasks"]):
                            f.write(f"{task}\n")
                    logging.info(f"All unmatched tasks saved to: {unmatched_file}")

    except Exception as e:
        logging.error(f"Failed to load PubMed data with task linking: {e}")
        raise


# Additional helper function to create task nodes from Cognitive Atlas
def ensure_cognitive_atlas_tasks(db):
    """
    Ensure Cognitive Atlas tasks are loaded before PubMed ingestion.

    This should be called before load_pubmed_with_task_linking to ensure
    we have a good vocabulary of tasks to match against.
    """
    logging.info("Loading Cognitive Atlas tasks...")

    from brain_researcher.services.br_kg.etl.loaders.cognitive_atlas_loader import fetch_cognitive_atlas_data

    try:
        # Fetch and load tasks
        ca_data_file = fetch_cognitive_atlas_data("data/br-kg/raw")

        if Path(ca_data_file).exists():
            with open(ca_data_file) as f:
                ca_data = json.load(f)

            # Load tasks
            tasks_loaded = 0
            for task in ca_data.get("tasks", []):
                try:
                    db.create_node(
                        "Task",
                        {
                            "name": task.get("name", ""),
                            "definition": task.get("definition", ""),
                            "ca_id": task.get("id", ""),
                            "source": "cognitive_atlas",
                        },
                        node_id=task.get("id"),
                    )
                    tasks_loaded += 1
                except Exception as e:
                    logging.debug(f"Failed to create task node: {e}")

            logging.info(f"Loaded {tasks_loaded} tasks from Cognitive Atlas")

    except Exception as e:
        logging.warning(f"Failed to load Cognitive Atlas tasks: {e}")


# Update the main init_database.py load_full_database function:
def example_integration():
    """
    Example of how to integrate in load_full_database function.

    Add this to the PubMed section of load_full_database:
    """
    # ... existing code ...

    # 2.5 Ensure we have tasks to match against
    ensure_cognitive_atlas_tasks(db)

    # 3. Load PubMed data with enhanced task linking
    load_pubmed_with_task_linking(db, data_dir)

    # ... rest of the code ...
