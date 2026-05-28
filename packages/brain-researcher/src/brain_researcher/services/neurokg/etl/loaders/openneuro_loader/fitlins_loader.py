#!/usr/bin/env python3
"""
OpenNeuro FitLins Data Loader

Simplified loader for OpenNeuro datasets processed with FitLins.
Based on the OpenNeuroBatchLoader but optimized for single dataset loading.

Author: BR-KG Team
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class OpenNeuroFitLinsLoader:
    """Loader for OpenNeuro datasets with FitLins processing"""

    def __init__(self, db, openneuro_dir: str = None):
        """
        Initialize OpenNeuro FitLins loader

        Args:
            db: BR-KG database instance
            openneuro_dir: Directory containing statsmodel_specs
        """
        self.db = db

        # Set default OpenNeuro directory
        if openneuro_dir is None:
            # Default to the known location based on project structure
            project_root = Path(__file__).parent.parent.parent.parent
            openneuro_dir = (
                project_root / "llm_cogitive_function" / "openneuro_glmfitlins"
            )

        self.openneuro_dir = Path(openneuro_dir)
        self.statsmodel_dir = self.openneuro_dir / "statsmodel_specs"

        logger.info(
            f"Initialized OpenNeuroFitLinsLoader with directory: {self.statsmodel_dir}"
        )

    def load_dataset(self, dataset_id: str) -> str | None:
        """
        Load a single OpenNeuro dataset with all its tasks and contrasts

        Args:
            dataset_id: Dataset ID (e.g., 'ds000002')

        Returns:
            Dataset ID if successful, None if failed
        """
        try:
            dataset_dir = self.statsmodel_dir / dataset_id
            if not dataset_dir.exists():
                logger.error(f"Dataset directory not found: {dataset_dir}")
                return None

            # Load basic details
            details_file = dataset_dir / f"{dataset_id}_basic-details.json"
            if not details_file.exists():
                logger.error(f"Basic details file not found: {details_file}")
                return None

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

            logger.info(
                f"Successfully loaded dataset {dataset_id} with {len(tasks)} tasks"
            )
            return dataset_id

        except Exception as e:
            logger.error(f"Error loading dataset {dataset_id}: {e}")
            return None

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
            else:
                logger.warning(f"Contrasts file not found: {contrasts_file}")

        except Exception as e:
            logger.error(f"Error loading task {task_name} for {dataset_id}: {e}")

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

            logger.debug(f"Created Contrast: {contrast_id}")

        except Exception as e:
            logger.error(f"Error loading contrast {contrast_name}: {e}")

    def get_available_datasets(self):
        """Get list of available datasets in the statsmodel_specs directory"""
        if not self.statsmodel_dir.exists():
            logger.warning(f"Statsmodel directory not found: {self.statsmodel_dir}")
            return []

        datasets = []
        for item in self.statsmodel_dir.iterdir():
            if item.is_dir() and item.name.startswith("ds"):
                details_file = item / f"{item.name}_basic-details.json"
                if details_file.exists():
                    datasets.append(item.name)

        return sorted(datasets)
