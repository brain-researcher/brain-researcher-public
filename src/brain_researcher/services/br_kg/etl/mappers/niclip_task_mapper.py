"""
NiCLIP Task Classification Mapper

This module provides task→concept→process mappings using NiCLIP's
scientifically validated cognitive task classifications.

Based on:
- reduced_tasks.csv: 90 tasks mapped to 3 concepts each
- concept_to_process.json: Concepts mapped to 6 cognitive processes
- NiCLIP embeddings for similarity-based lookups
"""

import csv
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

# NiCLIP data paths
NICLIP_BASE = (
    Path(__file__).parent.parent.parent.parent.parent.parent
    / "data"
    / "niclip"
    / "dsj56"
    / "osfstorage"
    / "osfstorage"
    / "data"
)
if not NICLIP_BASE.exists():
    # Try alternate path
    NICLIP_BASE = (
        Path(__file__).parent.parent.parent.parent.parent
        / "data"
        / "niclip"
        / "dsj56"
        / "osfstorage"
        / "osfstorage"
        / "data"
    )

DATA_PATH = NICLIP_BASE if NICLIP_BASE.exists() else None


class NiCLIPTaskMapper:
    """Maps tasks to concepts and cognitive processes using NiCLIP data."""

    # Process names from NiCLIP
    PROCESS_NAMES = {
        "ctp_C1": "Perception",
        "ctp_C3": "Cognitive Control",
        "ctp_C4": "Visual Processing",
        "ctp_C6": "Language",
        "ctp_C7": "Motor",
        "ctp_C8": "Emotion",
    }

    def __init__(self, data_path: Path | None = None):
        """Initialize the mapper with optional custom data path."""
        self.data_path = data_path or DATA_PATH
        if not self.data_path or not self.data_path.exists():
            logger.warning(f"NiCLIP data path not found: {self.data_path}")

        # Data structures
        self.task_to_concepts: dict[str, list[str]] = {}
        self.concept_to_process: dict[str, str] = {}
        self.process_to_tasks: dict[str, set[str]] = defaultdict(set)
        self.process_to_concepts: dict[str, set[str]] = defaultdict(set)

        # Load data on initialization
        self._loaded = False
        self._load_data()

    def _load_data(self) -> bool:
        """Load all NiCLIP data files."""
        if not self.data_path:
            return False

        try:
            # Load task-concept mappings
            self._load_reduced_tasks()
            # Load concept-process mappings
            self._load_concept_to_process()
            # Build reverse mappings
            self._build_reverse_mappings()

            self._loaded = True
            logger.info(
                f"Loaded NiCLIP mappings: {len(self.task_to_concepts)} tasks, "
                f"{len(self.concept_to_process)} concept-process mappings"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to load NiCLIP data: {e}")
            return False

    def _load_reduced_tasks(self):
        """Load task-concept mappings from reduced_tasks.csv"""
        csv_path = self.data_path / "cognitive_atlas" / "reduced_tasks.csv"

        if not csv_path.exists():
            # Try alternate naming
            csv_path = self.data_path / "cognitive_atlas" / "reduced_tasks.csv"
            if not csv_path.exists():
                logger.warning(f"reduced_tasks.csv not found at {csv_path}")
                return

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                task = row["task"].strip()
                concepts = [
                    row.get("concept_1", "").strip(),
                    row.get("concept_2", "").strip(),
                    row.get("concept_3", "").strip(),
                ]
                # Filter out empty concepts
                concepts = [c for c in concepts if c]
                if task and concepts:
                    self.task_to_concepts[task] = concepts

    def _load_concept_to_process(self):
        """Load concept to process mappings."""
        json_path = self.data_path / "cognitive_atlas" / "concept_to_process.json"

        if not json_path.exists():
            logger.warning(f"concept_to_process.json not found at {json_path}")
            return

        with open(json_path) as f:
            self.concept_to_process = json.load(f)

    def _build_reverse_mappings(self):
        """Build reverse mappings for efficient lookups."""
        # Build process -> tasks mapping
        for task, concepts in self.task_to_concepts.items():
            processes = self.get_task_processes(task)
            for process in processes:
                self.process_to_tasks[process].add(task)

        # Build process -> concepts mapping
        for concept, process in self.concept_to_process.items():
            self.process_to_concepts[process].add(concept)

    def get_task_concepts(self, task_name: str) -> list[str]:
        """Get concepts associated with a task."""
        # Try exact match first
        if task_name in self.task_to_concepts:
            return self.task_to_concepts[task_name]

        # Try case-insensitive match
        task_lower = task_name.lower()
        for task, concepts in self.task_to_concepts.items():
            if task.lower() == task_lower:
                return concepts

        return []

    def get_task_processes(self, task_name: str) -> list[str]:
        """Get all processes associated with a task via its concepts."""
        concepts = self.get_task_concepts(task_name)
        processes = []

        for concept in concepts:
            if concept in self.concept_to_process:
                process = self.concept_to_process[concept]
                if process not in processes:
                    processes.append(process)

        return processes

    def get_primary_process(self, task_name: str) -> str | None:
        """Get the primary (most common) process for a task."""
        processes = self.get_task_processes(task_name)

        if not processes:
            return None

        # If all concepts map to same process, that's primary
        if len(processes) == 1:
            return processes[0]

        # Otherwise, count which process appears most
        concepts = self.get_task_concepts(task_name)
        process_counts = Counter()

        for concept in concepts:
            if concept in self.concept_to_process:
                process = self.concept_to_process[concept]
                process_counts[process] += 1

        if process_counts:
            return process_counts.most_common(1)[0][0]

        return processes[0]  # Fallback to first

    def get_process_name(self, process_id: str) -> str:
        """Get human-readable name for a process ID."""
        return self.PROCESS_NAMES.get(process_id, process_id)

    def get_process_tasks(self, process_id: str) -> list[str]:
        """Get all tasks belonging to a process."""
        return list(self.process_to_tasks.get(process_id, []))

    def get_unmapped_concepts(self) -> list[str]:
        """Get concepts that don't have process mappings."""
        unmapped = []

        for task, concepts in self.task_to_concepts.items():
            for concept in concepts:
                if concept not in self.concept_to_process and concept not in unmapped:
                    unmapped.append(concept)

        return unmapped

    def get_classification_summary(self) -> dict:
        """Get summary statistics of the classification."""
        summary = {
            "total_tasks": len(self.task_to_concepts),
            "total_concepts": len(
                set(c for concepts in self.task_to_concepts.values() for c in concepts)
            ),
            "mapped_concepts": len(self.concept_to_process),
            "unmapped_concepts": len(self.get_unmapped_concepts()),
            "processes": {},
        }

        for process_id, process_name in self.PROCESS_NAMES.items():
            tasks = self.get_process_tasks(process_id)
            concepts = list(self.process_to_concepts.get(process_id, []))

            summary["processes"][process_id] = {
                "name": process_name,
                "task_count": len(tasks),
                "concept_count": len(concepts),
                "example_tasks": tasks[:5] if tasks else [],
                "example_concepts": concepts[:5] if concepts else [],
            }

        return summary

    def format_task_info(self, task_name: str) -> dict:
        """Get formatted information about a task."""
        concepts = self.get_task_concepts(task_name)
        processes = self.get_task_processes(task_name)
        primary_process = self.get_primary_process(task_name)

        return {
            "task": task_name,
            "concepts": concepts,
            "processes": [
                {
                    "id": p,
                    "name": self.get_process_name(p),
                    "is_primary": p == primary_process,
                }
                for p in processes
            ],
            "primary_category": (
                self.get_process_name(primary_process) if primary_process else None
            ),
        }

    def search_similar_tasks(
        self, query: str, top_k: int = 5
    ) -> list[tuple[str, float]]:
        """
        Search for similar tasks based on name similarity.
        Returns list of (task_name, similarity_score) tuples.
        """
        query_lower = query.lower()
        results = []

        for task in self.task_to_concepts:
            task_lower = task.lower()

            # Exact match
            if query_lower == task_lower:
                results.append((task, 1.0))
                continue

            # Substring match
            if query_lower in task_lower:
                # Score based on how much of the task name is the query
                score = len(query_lower) / len(task_lower)
                results.append((task, score * 0.9))  # Scale down slightly
                continue

            # Word overlap
            query_words = set(query_lower.split())
            task_words = set(task_lower.split())

            if query_words & task_words:  # Intersection
                overlap = len(query_words & task_words)
                score = overlap / max(len(query_words), len(task_words))
                results.append((task, score * 0.7))  # Scale down more

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)

        return results[:top_k]


# Singleton instance
_mapper = None


def get_mapper() -> NiCLIPTaskMapper:
    """Get singleton mapper instance."""
    global _mapper
    if _mapper is None:
        _mapper = NiCLIPTaskMapper()
    return _mapper
