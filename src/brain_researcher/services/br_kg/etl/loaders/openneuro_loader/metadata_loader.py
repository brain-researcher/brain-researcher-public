import logging
import os
import sys
from collections.abc import Generator
from pathlib import Path

import requests

# Add parent directory to path
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

try:
    from brain_researcher.services.br_kg.utils.text_norm import normalize_task_name
except ImportError:
    from brain_researcher.core.utils.text_norm import normalize_task_name

logger = logging.getLogger(__name__)


class OpenNeuroMetadataLoader:
    """Fetch dataset metadata from the OpenNeuro GraphQL API and load into the
    BR-KG graph database."""

    GRAPHQL_ENDPOINT = "https://openneuro.org/crn/graphql"

    def __init__(self, db, batch_size: int = 50, dry_run: bool = False):
        self.db = db
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.unmatched: list[dict[str, str]] = []

    # ------------------------- Fetching Helpers -------------------------
    def _fetch_page(self, cursor: str | None = None) -> dict:
        query = (
            "query($cursor:String){\n"
            "  datasets(first:%d, after:$cursor){\n"
            "    pageInfo{hasNextPage endCursor}\n"
            "    edges{node{ id name latestSnapshot{description{DatasetDOI Name}"
            "} summary{subjects modalities tasks}}}\n"
            "  }\n"
            "}" % self.batch_size
        )
        variables = {"cursor": cursor}
        resp = requests.post(
            self.GRAPHQL_ENDPOINT, json={"query": query, "variables": variables}
        )
        resp.raise_for_status()
        return resp.json()["data"]["datasets"]

    def iter_datasets(self, limit: int | None = None) -> Generator[dict, None, None]:
        cursor = None
        fetched = 0
        while True:
            data = self._fetch_page(cursor)
            for edge in data.get("edges", []):
                node = edge.get("node", {})
                snap = node.get("latestSnapshot") or {}
                desc = snap.get("description") or {}
                summ = snap.get("summary") or {}
                record = {
                    "dataset_id": node.get("id"),
                    "title": desc.get("Name"),
                    "doi": desc.get("DatasetDOI"),
                    "subjects": summ.get("subjects", []),
                    "modalities": summ.get("modalities", []),
                    "tasks": summ.get("tasks", []),
                }
                yield record
                fetched += 1
                if limit and fetched >= limit:
                    return
            if not data.get("pageInfo", {}).get("hasNextPage"):
                break
            cursor = data.get("pageInfo", {}).get("endCursor")

    # -------------------------- Loading Helpers -------------------------
    def load_datasets(self, limit: int | None = None):
        for record in self.iter_datasets(limit):
            self._upsert_dataset(record)

    def _find_task_node(self, normalized: str) -> str | None:
        for node_id, data in self.db.find_nodes(["Task", "TaskDef"]):
            name = data.get("name") or data.get("task") or ""
            if normalize_task_name(name) == normalized:
                return node_id
        return None

    def _upsert_dataset(self, record: dict):
        ds_id = record["dataset_id"]
        if not self.dry_run:
            self.db.create_node(
                "Dataset",
                {
                    "dataset_id": ds_id,
                    "title": record["title"],
                    "doi": record["doi"],
                    "subjects": record["subjects"],
                    "modalities": record["modalities"],
                },
                node_id=ds_id,
            )

        # Handle subjects and phenotypes
        subjects = record.get("subjects", [])
        phenotypes = record.get("phenotypes", [])

        if not self.dry_run and subjects:
            # Create SubjectGroup for this dataset
            subject_group_id = f"{ds_id}_subject_group"
            try:
                self.db.create_node(
                    "SubjectGroup",
                    {
                        "id": subject_group_id,
                        "dataset_id": ds_id,
                        "source": "openneuro",
                    },
                    node_id=subject_group_id,
                )

                # Link dataset to subject group
                self.db.create_relationship(
                    ds_id,
                    subject_group_id,
                    "INCLUDES",
                    {"source": "openneuro_metadata"},
                )
            except ValueError as e:
                if "Constraint violation" not in str(e):
                    logger.error(f"Failed to create SubjectGroup for {ds_id}: {e}")

            # Create individual subjects
            for subj in subjects:
                # Use openneuro prefix to avoid conflicts with other sources
                subj_node_id = f"openneuro_{ds_id}_{subj}"
                try:
                    self.db.create_node(
                        "Subject",
                        {
                            "subject_id": subj,
                            "dataset_id": ds_id,
                            "source": "openneuro",
                        },
                        node_id=subj_node_id,
                    )

                    # Link subject group to subject
                    self.db.create_relationship(
                        subject_group_id,
                        subj_node_id,
                        "HAS_SUBJECT",
                        {"source": "openneuro_metadata"},
                    )

                    # Only create phenotype relationships if phenotypes exist
                    if phenotypes:
                        for pheno in phenotypes:
                            pheno_id = f"{pheno.replace(' ', '_').lower()}_phenotype"
                            try:
                                self.db.create_node(
                                    "Phenotype",
                                    {
                                        "name": pheno,
                                        "record_id": pheno_id,
                                        "source": "openneuro",
                                    },
                                    node_id=pheno_id,
                                )
                            except ValueError as e:
                                if "Constraint violation" not in str(e):
                                    logger.error(
                                        f"Failed to create Phenotype {pheno}: {e}"
                                    )

                            # Link subject to phenotype
                            self.db.create_relationship(
                                subj_node_id,
                                pheno_id,
                                "HAS_PHENOTYPE",
                                {"source": "openneuro_metadata"},
                            )
                except ValueError as e:
                    if "Constraint violation" not in str(e):
                        logger.error(
                            f"Failed to create Subject {subj} for {ds_id}: {e}"
                        )

        # Handle tasks
        for task in record["tasks"]:
            normalized = normalize_task_name(task)
            match = self._find_task_node(normalized)
            if match:
                if not self.dry_run:
                    self.db.create_relationship(
                        ds_id,
                        match,
                        "USES_PARADIGM",
                        {"confidence": 1.0, "method": "exact_taskname"},
                    )
            else:
                self.unmatched.append({"dataset_id": ds_id, "task": task})

    def save_unmatched(self, path: str = "logs/unmatched_tasks.csv"):
        if not self.unmatched:
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write("dataset_id,task\n")
            for row in self.unmatched:
                f.write(f"{row['dataset_id']},{row['task']}\n")
        logger.info(f"Saved {len(self.unmatched)} unmatched tasks to {path}")
