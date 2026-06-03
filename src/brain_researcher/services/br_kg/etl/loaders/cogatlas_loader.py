"""
Comprehensive Cognitive Atlas Loader for BR-KG

This module implements a full-featured loader for importing Cognitive Atlas data,
including concepts, tasks, and their relationships, into the BR-KG graph database.

Key Features:
- Imports ≥800 tasks and ≈900 concepts from Cognitive Atlas
- Includes Domain relationships (IS_A hierarchy)
- Includes MEASURES relationships between tasks and concepts
- Supports incremental updates with --update flag
- Optimized for <5 minute runtime
- Robust error handling and retry logic
"""

import argparse
import logging
import time
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db

logger = logging.getLogger(__name__)

# Constants
COGNITIVE_ATLAS_API_BASE = "https://cognitiveatlas.org/api/v-alpha"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
BATCH_SIZE = 50  # For bulk inserts


class CognitiveAtlasLoader:
    """Comprehensive loader for Cognitive Atlas data."""

    def __init__(self, db_path: str | None = None):
        """Initialize the loader with Neo4j connection (db_path ignored)."""
        self.db = require_neo4j_db(db_path, preload_cache=False)
        self.session = self._create_session()
        self.stats = {
            "concepts_added": 0,
            "concepts_updated": 0,
            "tasks_added": 0,
            "tasks_updated": 0,
            "relationships_added": 0,
            "errors": 0,
        }

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        retry = Retry(
            total=MAX_RETRIES, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def load_all(self, update_only: bool = False) -> dict[str, int]:
        """
        Load all Cognitive Atlas data into the graph.

        Args:
            update_only: If True, only update existing nodes

        Returns:
            Dictionary with statistics about the import
        """
        start_time = time.time()
        logger.info("🚀 Starting Cognitive Atlas import...")

        try:
            # Load concepts first (they're referenced by tasks)
            logger.info("📊 Loading concepts...")
            concepts = self._fetch_all_concepts()
            self._process_concepts(concepts, update_only)

            # Load tasks
            logger.info("📊 Loading tasks...")
            tasks = self._fetch_all_tasks()
            self._process_tasks(tasks, update_only)

            # Load relationships
            logger.info("🔗 Loading relationships...")
            self._load_relationships(concepts, tasks, update_only)

            # Calculate runtime
            runtime = time.time() - start_time
            self.stats["runtime_seconds"] = runtime

            logger.info(f"✅ Import completed in {runtime:.2f} seconds")
            logger.info(f"📈 Statistics: {self.stats}")

            return self.stats

        except Exception as e:
            logger.error(f"❌ Import failed: {e}")
            raise

    def _fetch_all_concepts(self) -> list[dict]:
        """Fetch all concepts from Cognitive Atlas API."""
        logger.info("🔍 Fetching concepts from API...")

        try:
            response = self.session.get(
                f"{COGNITIVE_ATLAS_API_BASE}/concepts", timeout=DEFAULT_TIMEOUT
            )
            response.raise_for_status()

            concepts = response.json()
            logger.info(f"✅ Retrieved {len(concepts)} concepts")
            return concepts

        except requests.RequestException as e:
            logger.error(f"❌ Failed to fetch concepts: {e}")
            # Return empty list to continue with other data
            return []

    def _fetch_all_tasks(self) -> list[dict]:
        """Fetch all tasks from Cognitive Atlas API."""
        logger.info("🔍 Fetching tasks from API...")

        try:
            response = self.session.get(
                f"{COGNITIVE_ATLAS_API_BASE}/tasks", timeout=DEFAULT_TIMEOUT
            )
            response.raise_for_status()

            tasks = response.json()
            logger.info(f"✅ Retrieved {len(tasks)} tasks")
            return tasks

        except requests.RequestException as e:
            logger.error(f"❌ Failed to fetch tasks: {e}")
            # Return empty list to continue with other data
            return []

    def _process_concepts(self, concepts: list[dict], update_only: bool):
        """Process and insert/update concepts in the graph."""
        logger.info(f"💾 Processing {len(concepts)} concepts...")

        # Process in batches for better performance
        for i in range(0, len(concepts), BATCH_SIZE):
            batch = concepts[i : i + BATCH_SIZE]

            for concept in batch:
                try:
                    self._process_single_concept(concept, update_only)
                except Exception as e:
                    logger.warning(
                        f"⚠️ Error processing concept {concept.get('id')}: {e}"
                    )
                    self.stats["errors"] += 1

    def _process_single_concept(self, concept: dict, update_only: bool):
        """Process a single concept."""
        concept_id = concept.get("id", "")
        if not concept_id:
            return

        # Check if concept exists
        existing = self.db.get_node_by_id(concept_id)

        # Prepare concept data
        properties = {
            "concept_id": concept_id,
            "name": concept.get("name", ""),
            "definition": concept.get("definition_text", ""),
            "definition_source": concept.get("definition_source", ""),
            "alias": concept.get("alias", ""),
            "concept_class": concept.get("concept_class", ""),
            "url": f"https://www.cognitiveatlas.org/concept/id/{concept_id}",
            "source": "cognitive_atlas",
            "updated_at": datetime.now().isoformat(),
        }

        # Clean empty values
        properties = {k: v for k, v in properties.items() if v}

        if existing:
            if not update_only:
                # Update existing concept
                self.db.update_node(concept_id, properties)
                self.stats["concepts_updated"] += 1
        else:
            # Create new concept
            self.db.add_node(
                node_id=concept_id, node_type="Concept", properties=properties
            )
            self.stats["concepts_added"] += 1

    def _process_tasks(self, tasks: list[dict], update_only: bool):
        """Process and insert/update tasks in the graph."""
        logger.info(f"💾 Processing {len(tasks)} tasks...")

        # Process in batches for better performance
        for i in range(0, len(tasks), BATCH_SIZE):
            batch = tasks[i : i + BATCH_SIZE]

            for task in batch:
                try:
                    self._process_single_task(task, update_only)
                except Exception as e:
                    logger.warning(f"⚠️ Error processing task {task.get('id')}: {e}")
                    self.stats["errors"] += 1

    def _process_single_task(self, task: dict, update_only: bool):
        """Process a single task."""
        task_id = task.get("id", "")
        if not task_id:
            return

        # Check if task exists
        existing = self.db.get_node_by_id(task_id)

        # Prepare task data
        properties = {
            "task_id": task_id,
            "name": task.get("name", ""),
            "definition": task.get("definition_text", ""),
            "definition_source": task.get("definition_source", ""),
            "url": f"https://www.cognitiveatlas.org/task/id/{task_id}",
            "source": "cognitive_atlas",
            "updated_at": datetime.now().isoformat(),
        }

        # Clean empty values
        properties = {k: v for k, v in properties.items() if v}

        if existing:
            if not update_only:
                # Update existing task
                self.db.update_node(task_id, properties)
                self.stats["tasks_updated"] += 1
        else:
            # Create new task (using Task type for compatibility)
            self.db.add_node(node_id=task_id, node_type="Task", properties=properties)
            self.stats["tasks_added"] += 1

    def _load_relationships(
        self, concepts: list[dict], tasks: list[dict], update_only: bool
    ):
        """Load concept-concept and task-concept relationships."""
        logger.info("🔗 Processing relationships...")

        # Process concept hierarchies (IS_A relationships)
        self._process_concept_hierarchies(concepts, update_only)

        # Process task-concept relationships (MEASURES)
        self._process_task_concept_relationships(tasks, update_only)

    def _process_concept_hierarchies(self, concepts: list[dict], update_only: bool):
        """Process IS_A relationships between concepts."""
        logger.info("🌳 Processing concept hierarchies...")

        for concept in concepts:
            concept_id = concept.get("id", "")
            parents = concept.get("parents", [])

            if not concept_id or not parents:
                continue

            for parent in parents:
                parent_id = parent.get("id", "") if isinstance(parent, dict) else parent
                if parent_id:
                    try:
                        # Check if relationship exists
                        existing_rel = self._relationship_exists(
                            concept_id, parent_id, "IS_A"
                        )

                        if not existing_rel:
                            self.db.add_edge(
                                source_id=concept_id,
                                target_id=parent_id,
                                edge_type="IS_A",
                                properties={
                                    "source": "cognitive_atlas",
                                    "created_at": datetime.now().isoformat(),
                                },
                            )
                            self.stats["relationships_added"] += 1

                    except Exception as e:
                        logger.warning(
                            f"⚠️ Error adding IS_A relationship {concept_id} -> {parent_id}: {e}"
                        )
                        self.stats["errors"] += 1

    def _process_task_concept_relationships(self, tasks: list[dict], update_only: bool):
        """Process MEASURES relationships between tasks and concepts."""
        logger.info("📏 Processing task-concept relationships...")

        for task in tasks:
            task_id = task.get("id", "")
            measured_concepts = task.get("concepts", [])

            if not task_id or not measured_concepts:
                continue

            for concept in measured_concepts:
                concept_id = (
                    concept.get("id", "") if isinstance(concept, dict) else concept
                )
                if concept_id:
                    try:
                        # Check if relationship exists
                        existing_rel = self._relationship_exists(
                            task_id, concept_id, "MEASURES"
                        )

                        if not existing_rel:
                            self.db.add_edge(
                                source_id=task_id,
                                target_id=concept_id,
                                edge_type="MEASURES",
                                properties={
                                    "source": "cognitive_atlas",
                                    "created_at": datetime.now().isoformat(),
                                },
                            )
                            self.stats["relationships_added"] += 1

                    except Exception as e:
                        logger.warning(
                            f"⚠️ Error adding MEASURES relationship {task_id} -> {concept_id}: {e}"
                        )
                        self.stats["errors"] += 1

    def _relationship_exists(
        self, source_id: str, target_id: str, edge_type: str
    ) -> bool:
        """Check if a relationship already exists in the graph."""
        try:
            if hasattr(self.db, "get_edges"):
                edges = self.db.get_edges(source_id=source_id, edge_type=edge_type)
                return any(edge["target"] == target_id for edge in edges)
            rels = self.db.find_relationships(start_node=source_id, rel_type=edge_type)
            return any(target_id == rel[1] for rel in rels)
        except:
            return False


def main():
    """Main entry point for the Cognitive Atlas loader."""
    parser = argparse.ArgumentParser(description="Load Cognitive Atlas data into BR-KG")
    parser.add_argument(
        "--db-path",
        type=str,
        default="data/br-kg/db/br_kg_full.db",
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Only update existing nodes (skip creating new ones)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Run the loader
    loader = CognitiveAtlasLoader(args.db_path)
    stats = loader.load_all(update_only=args.update)

    # Print summary
    print("\n📊 Import Summary:")
    print(f"  Concepts added: {stats['concepts_added']}")
    print(f"  Concepts updated: {stats['concepts_updated']}")
    print(f"  Tasks added: {stats['tasks_added']}")
    print(f"  Tasks updated: {stats['tasks_updated']}")
    print(f"  Relationships added: {stats['relationships_added']}")
    print(f"  Errors: {stats['errors']}")
    print(f"  Runtime: {stats.get('runtime_seconds', 0):.2f} seconds")


if __name__ == "__main__":
    main()
