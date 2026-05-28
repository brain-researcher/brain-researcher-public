#!/usr/bin/env python3
"""
Batch Load All OpenNeuro Datasets

This script loads all OpenNeuro datasets from the statsmodel_specs directory
and integrates them with NiCLIP mappings.

Author: BR-KG Team
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.neurokg.etl.loaders.cognitive_atlas_loader import CognitiveAtlasLoader
from brain_researcher.services.neurokg.etl.mappers.contrast_concept_linker import ContrastConceptLinker
from brain_researcher.services.neurokg.etl.mappers.cross_source_linker import CrossSourceLinker
from brain_researcher.services.neurokg.etl.mappers.task_mapper import TaskMapper
from graph.graph_database import NeuroKGGraphDB

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            f'logs/openneuro_batch_load_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        ),
    ],
)
logger = logging.getLogger(__name__)


class OpenNeuroBatchLoader:
    """Batch loader for OpenNeuro datasets with NiCLIP integration"""

    def __init__(self, db: NeuroKGGraphDB, openneuro_dir: str):
        """
        Initialize batch loader

        Args:
            db: BR-KG database instance
            openneuro_dir: Directory containing statsmodel_specs
        """
        self.db = db
        self.openneuro_dir = Path(openneuro_dir)
        self.statsmodel_dir = self.openneuro_dir / "statsmodel_specs"

        # Initialize mappers
        self.task_mapper = TaskMapper()
        self.contrast_linker = ContrastConceptLinker()

        # Track statistics
        self.stats = {
            "datasets_loaded": 0,
            "datasets_failed": 0,
            "tasks_loaded": 0,
            "contrasts_loaded": 0,
            "taskspec_mappings": 0,
            "contrast_links": 0,
            "errors": [],
        }

    def load_cognitive_atlas(self):
        """Load Cognitive Atlas data if not already present"""
        # Check if concepts and tasks already exist
        concept_count = self.db.get_node_count("Concept")
        taskdef_count = self.db.get_node_count("TaskDef")

        if concept_count > 0 and taskdef_count > 0:
            logger.info(
                f"Cognitive Atlas data already loaded: {concept_count} concepts, {taskdef_count} tasks"
            )
            return

        logger.info("Loading Cognitive Atlas data...")
        cog_loader = CognitiveAtlasLoader(self.db)

        # Use temporary directory for fetching data
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # Try to fetch from API (will use sample data as fallback)
                output_files = cog_loader.fetch_cognitive_atlas_data(temp_dir)
                concepts_loaded = cog_loader.load_concepts_from_json(
                    output_files["concepts"]
                )
                tasks_loaded = cog_loader.load_tasks_from_json(output_files["tasks"])
                logger.info(
                    f"Loaded {concepts_loaded} concepts and {tasks_loaded} tasks"
                )
            except Exception as e:
                logger.error(f"Failed to load Cognitive Atlas data: {e}")
                # Create minimal sample data
                logger.info("Creating minimal sample Cognitive Atlas data...")
                self._create_minimal_cognitive_atlas_data()

    def _create_minimal_cognitive_atlas_data(self):
        """Create minimal Cognitive Atlas data for mapping"""
        # Create essential concepts
        concepts = [
            {
                "id": "trm_001",
                "name": "working memory",
                "definition": "Ability to maintain and manipulate information",
            },
            {
                "id": "trm_002",
                "name": "attention",
                "definition": "Selective concentration on information",
            },
            {
                "id": "trm_003",
                "name": "executive control",
                "definition": "High-level cognitive control processes",
            },
            {
                "id": "trm_004",
                "name": "response inhibition",
                "definition": "Ability to suppress inappropriate responses",
            },
            {
                "id": "trm_005",
                "name": "emotion",
                "definition": "Complex psychological state",
            },
            {
                "id": "trm_006",
                "name": "face recognition",
                "definition": "Ability to identify faces",
            },
            {
                "id": "trm_007",
                "name": "motor control",
                "definition": "Control of bodily movements",
            },
            {
                "id": "trm_008",
                "name": "visual perception",
                "definition": "Interpretation of visual information",
            },
            {
                "id": "trm_009",
                "name": "memory",
                "definition": "Faculty for storing and retrieving information",
            },
            {
                "id": "trm_010",
                "name": "language",
                "definition": "System of communication",
            },
        ]

        # Create essential tasks
        tasks = [
            {
                "id": "tsk_001",
                "name": "n-back task",
                "definition": "Working memory task",
            },
            {
                "id": "tsk_002",
                "name": "stroop task",
                "definition": "Attention and inhibition task",
            },
            {
                "id": "tsk_003",
                "name": "flanker task",
                "definition": "Attention and conflict monitoring",
            },
            {
                "id": "tsk_004",
                "name": "go/no-go task",
                "definition": "Response inhibition task",
            },
            {
                "id": "tsk_005",
                "name": "stop signal task",
                "definition": "Motor inhibition task",
            },
            {
                "id": "tsk_006",
                "name": "face matching task",
                "definition": "Face recognition task",
            },
            {
                "id": "tsk_007",
                "name": "emotion regulation task",
                "definition": "Emotion control task",
            },
            {
                "id": "tsk_008",
                "name": "finger tapping task",
                "definition": "Motor control task",
            },
            {
                "id": "tsk_009",
                "name": "object recognition task",
                "definition": "Visual perception task",
            },
            {
                "id": "tsk_010",
                "name": "verbal fluency task",
                "definition": "Language production task",
            },
        ]

        # Load concepts
        for concept in concepts:
            try:
                self.db.create_node("Concept", concept)
            except:
                pass  # Ignore duplicates

        # Load tasks
        for task in tasks:
            try:
                self.db.create_node("TaskDef", task)
            except:
                pass  # Ignore duplicates

        logger.info(
            f"Created minimal Cognitive Atlas data: {len(concepts)} concepts, {len(tasks)} tasks"
        )

    def load_dataset(self, dataset_id: str) -> bool:
        """
        Load a single dataset with all its tasks and contrasts

        Args:
            dataset_id: Dataset ID (e.g., 'ds000002')

        Returns:
            Success status
        """
        try:
            dataset_dir = self.statsmodel_dir / dataset_id
            if not dataset_dir.exists():
                logger.error(f"Dataset directory not found: {dataset_dir}")
                return False

            # Load basic details
            details_file = dataset_dir / f"{dataset_id}_basic-details.json"
            if not details_file.exists():
                logger.error(f"Basic details file not found: {details_file}")
                return False

            with open(details_file) as f:
                details = json.load(f)

            # Create Dataset node
            dataset_node_id = self.db.create_node(
                "Dataset",
                {
                    "id": dataset_id,
                    "name": dataset_id,
                    "subjects": details.get("Subjects", []),
                    "sessions": details.get("Sessions", []),
                    "source": "openneuro_fitlins",
                },
            )

            logger.info(f"Created Dataset node: {dataset_id}")

            # Process each task
            tasks = details.get("Tasks", {})
            for task_name, task_info in tasks.items():
                self._load_task(dataset_id, dataset_node_id, task_name, task_info)

            self.stats["datasets_loaded"] += 1
            return True

        except Exception as e:
            logger.error(f"Error loading dataset {dataset_id}: {e}")
            self.stats["datasets_failed"] += 1
            self.stats["errors"].append(f"{dataset_id}: {str(e)}")
            return False

    def _load_task(
        self,
        dataset_id: str,
        dataset_node_id: str,
        task_name: str,
        task_info: dict[str, Any],
    ):
        """Load a single task with its contrasts"""
        try:
            # Create TaskSpec node
            task_spec_id = f"{dataset_id}_task-{task_name}"
            task_spec_node_id = self.db.create_node(
                "TaskSpec",
                {
                    "id": task_spec_id,
                    "name": task_name,
                    "dataset": dataset_id,
                    "bold_volumes": task_info.get("bold_volumes"),
                    "dummy_volumes": task_info.get("dummy_volumes"),
                    "cite_links": task_info.get("cite_links", []),
                    "column_names": task_info.get("column_names", []),
                },
                node_id=task_spec_id,
            )

            # Create or find publication node from cite_links
            publication_node_id = None
            cite_links = task_info.get("cite_links", [])
            if cite_links:
                doi = cite_links[0]
                try:
                    existing = self.db.find_nodes("Study", {"doi": doi})
                    if existing:
                        publication_node_id = existing[0][0]
                        logger.debug(f"Found existing publication node for DOI {doi}")
                    else:
                        publication_node_id = self.db.create_node(
                            "Study",
                            {"doi": doi, "title": doi},
                        )
                        logger.debug(f"Created new publication node for DOI {doi}")
                except Exception as e:
                    logger.warning(
                        f"Failed to create/find publication node for DOI {doi}: {e}"
                    )

            # Create relationship to dataset
            self.db.create_relationship(
                dataset_node_id, task_spec_node_id, "HAS_TASK", {"task_name": task_name}
            )

            self.stats["tasks_loaded"] += 1
            logger.debug(f"Created TaskSpec: {task_spec_id}")

            # Load contrasts
            contrasts_file = (
                self.statsmodel_dir
                / dataset_id
                / f"{dataset_id}-{task_name}_contrasts.json"
            )
            if contrasts_file.exists():
                with open(contrasts_file) as f:
                    contrasts_data = json.load(f)

                contrasts = contrasts_data.get("Contrasts", [])
                for contrast in contrasts:
                    self._load_contrast(
                        dataset_id,
                        task_spec_node_id,
                        task_name,
                        contrast,
                        publication_node_id,
                    )

        except Exception as e:
            logger.error(f"Error loading task {task_name} for {dataset_id}: {e}")
            self.stats["errors"].append(f"{dataset_id}/{task_name}: {str(e)}")

    def _load_contrast(
        self,
        dataset_id: str,
        task_spec_node_id: str,
        task_name: str,
        contrast_data: dict[str, Any],
        publication_node_id: str | None = None,
    ):
        """Load a single contrast"""
        try:
            contrast_name = contrast_data.get("Name", "unnamed")
            contrast_id = f"{dataset_id}_task-{task_name}_contrast-{contrast_name}"

            # Create Contrast node
            contrast_node_id = self.db.create_node(
                "Contrast",
                {
                    "id": contrast_id,
                    "name": contrast_name,
                    "dataset": dataset_id,
                    "task_name": task_name,
                    "task_label": task_name,
                    "condition_list": contrast_data.get("ConditionList", []),
                    "weights": contrast_data.get("Weights", []),
                    "test": contrast_data.get("Test", "t"),
                },
                node_id=contrast_id,
            )

            # Create relationship to task
            self.db.create_relationship(
                task_spec_node_id,
                contrast_node_id,
                "HAS_CONTRAST",
                {"contrast_name": contrast_name},
            )

            # Create relationship to publication if available
            if publication_node_id:
                self.db.create_relationship(
                    contrast_node_id,
                    publication_node_id,
                    "BELONGS_TO",
                )
                logger.debug(
                    "Created BELONGS_TO relationship from contrast to publication"
                )

            self.stats["contrasts_loaded"] += 1
            logger.debug(f"Created Contrast: {contrast_id}")

        except Exception as e:
            logger.error(f"Error loading contrast {contrast_name}: {e}")

    def map_tasks_to_taskdefs(self):
        """Map all TaskSpec nodes to TaskDef nodes using NiCLIP"""
        logger.info("Mapping TaskSpecs to TaskDefs...")

        # Get all TaskDef nodes
        task_def_nodes = self.db.find_nodes("TaskDef")
        self.task_mapper.set_task_definitions(task_def_nodes)

        # Get all TaskSpec nodes
        task_spec_nodes = self.db.find_nodes("TaskSpec")

        for task_spec_id, task_spec_data in task_spec_nodes:
            task_name = task_spec_data.get("name", "")

            # Skip if already mapped
            existing_mappings = self.db.find_relationships(
                start_node=task_spec_id, rel_type="MAPS_TO"
            )
            if existing_mappings:
                continue

            mapping_result = self.task_mapper.map_task(task_name, task_spec_data)

            if mapping_result:
                # Create MAPS_TO relationship
                success = self.db.create_relationship(
                    task_spec_id,
                    mapping_result["task_def_id"],
                    "MAPS_TO",
                    {
                        "match_type": mapping_result["match_type"],
                        "confidence": mapping_result["confidence"],
                        "mapping_source": "niclip_batch",
                    },
                )

                if success:
                    self.stats["taskspec_mappings"] += 1
                    logger.debug(
                        f"Mapped '{task_name}' -> TaskDef "
                        f"({mapping_result['match_type']}, "
                        f"confidence: {mapping_result['confidence']:.2f})"
                    )

    def link_contrasts_to_concepts(self):
        """Link all Contrast nodes to Concept nodes"""
        logger.info("Linking Contrasts to Concepts...")

        # Get all nodes
        contrast_nodes = self.db.find_nodes("Contrast")
        concept_nodes = self.db.find_nodes("Concept")

        # Skip if no concepts
        if not concept_nodes:
            logger.warning("No Concept nodes found, skipping contrast linking")
            return

        # Link contrasts in batches
        edges = self.contrast_linker.link_batch(contrast_nodes, concept_nodes)

        # Create edges in database
        for edge_spec in edges:
            success = self.db.create_relationship(
                edge_spec["start_node"],
                edge_spec["end_node"],
                edge_spec["type"],
                edge_spec["properties"],
            )

            if success:
                self.stats["contrast_links"] += 1

    def load_all_datasets(self):
        """Load all datasets from the statsmodel_specs directory"""
        # Get all dataset directories
        dataset_dirs = sorted(
            [
                d
                for d in self.statsmodel_dir.iterdir()
                if d.is_dir() and d.name.startswith("ds")
            ]
        )

        logger.info(f"Found {len(dataset_dirs)} datasets to load")

        # Load each dataset
        for i, dataset_dir in enumerate(dataset_dirs, 1):
            dataset_id = dataset_dir.name
            logger.info(f"Loading dataset {i}/{len(dataset_dirs)}: {dataset_id}")
            self.load_dataset(dataset_id)

        logger.info("All datasets loaded")

    def generate_report(self):
        """Generate and save a loading report"""
        report = f"""
OpenNeuro Batch Loading Report
==============================
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Summary Statistics:
------------------
Datasets loaded: {self.stats['datasets_loaded']}
Datasets failed: {self.stats['datasets_failed']}
Tasks loaded: {self.stats['tasks_loaded']}
Contrasts loaded: {self.stats['contrasts_loaded']}
TaskSpec->TaskDef mappings: {self.stats['taskspec_mappings']}
Contrast->Concept links: {self.stats['contrast_links']}

Task Mapping Statistics:
-----------------------
{self.task_mapper.get_stats_summary()}

Contrast Linking Statistics:
---------------------------
{self.contrast_linker.get_stats_summary()}

Database Statistics:
-------------------
"""
        # Add database stats
        db_stats = self.db.get_stats()
        report += f"Total nodes: {db_stats['total_nodes']}\n"
        report += f"Total relationships: {db_stats['total_relationships']}\n\n"

        report += "Nodes by type:\n"
        for label, count in sorted(db_stats["node_labels"].items()):
            report += f"  {label}: {count}\n"

        report += "\nRelationships by type:\n"
        for rel_type, count in sorted(db_stats["relationship_types"].items()):
            report += f"  {rel_type}: {count}\n"

        # Add errors if any
        if self.stats["errors"]:
            report += f"\nErrors ({len(self.stats['errors'])}):\n"
            for error in self.stats["errors"][:20]:  # Show first 20 errors
                report += f"  - {error}\n"
            if len(self.stats["errors"]) > 20:
                report += f"  ... and {len(self.stats['errors']) - 20} more errors\n"

        # Save report
        report_path = f"logs/openneuro_batch_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(report_path, "w") as f:
            f.write(report)

        logger.info(f"Report saved to: {report_path}")
        print("\n" + report)

        return report


def load_vocab_list_from_niclip_json(db: NeuroKGGraphDB, vocab_list_path: str):
    """Load a vocab list from a JSON file"""
    # e.g. /data/ECoG-foundation-model/mnndl_temp/niclip/osf_data/dsj56/osfstorage/osfstorage/data/cognitive_atlas
    with open(vocab_list_path) as f:
        vocab_list = json.load(f)

    for vocab in vocab_list:
        db.create_node("Vocab", vocab)


def main():
    """Main batch loading workflow"""

    # Configuration
    db_path = "/data/ECoG-foundation-model/mnndl_temp/brain_researcher/neurokg/data/neurokg/db/neurokg_full.db"
    openneuro_dir = "/data/ECoG-foundation-model/mnndl_temp/brain_researcher/llm_cogitive_function/openneuro_glmfitlins"

    # Ensure directories exist
    Path("logs").mkdir(parents=True, exist_ok=True)
    # Skip creating cognitive_atlas dir - will use temp if needed

    logger.info("Starting OpenNeuro batch load")
    logger.info(f"Database: {db_path}")
    logger.info(f"OpenNeuro directory: {openneuro_dir}")

    # Initialize database
    db = NeuroKGGraphDB(db_path)

    # Create constraints if not exist
    logger.info("Creating database constraints...")
    db.create_constraint("Dataset", "id", "UNIQUE")
    db.create_constraint("TaskSpec", "id", "UNIQUE")
    db.create_constraint("TaskDef", "id", "UNIQUE")
    db.create_constraint("Contrast", "id", "UNIQUE")
    db.create_constraint("Concept", "id", "UNIQUE")

    # Initialize batch loader
    loader = OpenNeuroBatchLoader(db, openneuro_dir)

    # Initialize cross-source linker
    cross_linker = CrossSourceLinker(db, auto_link=True, dry_run=False)
    logger.info("Cross-source linker initialized")

    try:
        # Step 1: Load Cognitive Atlas data
        logger.info("\n=== Step 1: Loading Cognitive Atlas data ===")
        loader.load_cognitive_atlas()

        # Run cross-source linking for Cognitive Atlas
        logger.info("Running cross-source linking for Cognitive Atlas...")
        links_created = cross_linker.link_after_source_load("cognitive_atlas")
        logger.info(
            f"Created {links_created} MAPS_TO relationships for Cognitive Atlas"
        )

        # Step 2: Load all OpenNeuro datasets
        logger.info("\n=== Step 2: Loading OpenNeuro datasets ===")
        loader.load_all_datasets()

        # Run cross-source linking for OpenNeuro
        logger.info("Running cross-source linking for OpenNeuro...")
        links_created = cross_linker.link_after_source_load("openneuro")
        logger.info(f"Created {links_created} MAPS_TO relationships for OpenNeuro")

        # Step 3: Map TaskSpecs to TaskDefs
        logger.info("\n=== Step 3: Mapping TaskSpecs to TaskDefs ===")
        loader.map_tasks_to_taskdefs()

        # Save mapping statistics
        loader.task_mapper.save_unmatched_log("logs/batch_unmatched_tasks.tsv")
        loader.task_mapper.save_stats("logs/batch_mapping_stats.json")

        # Step 4: Link Contrasts to Concepts
        logger.info("\n=== Step 4: Linking Contrasts to Concepts ===")
        loader.link_contrasts_to_concepts()

        # Step 5: Generate report
        logger.info("\n=== Step 5: Generating report ===")
        loader.generate_report()

        # Add cross-source linking report
        logger.info("\n=== Cross-Source Linking Summary ===")
        logger.info(cross_linker.get_linking_report())

    except Exception as e:
        logger.error(f"Batch loading failed: {e}", exc_info=True)

    finally:
        # Close database
        db.close()

    logger.info("\nBatch loading completed!")
    logger.info(
        "You can now explore the graph in the Web UI: br serve web (then open /en/kg/explore)"
    )


if __name__ == "__main__":
    main()
