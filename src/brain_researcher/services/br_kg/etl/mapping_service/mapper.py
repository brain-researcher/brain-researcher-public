"""
BR-KG ID Mapping Service

This module provides functionality to map external identifiers to internal knowledge graph IDs.
It handles the conversion between different ID systems used by various data sources:

- Cognitive Atlas IDs -> Internal concept/task IDs
- PubMed IDs -> Internal publication IDs
- Brain atlas coordinates -> Internal coordinate IDs
- External region names -> Internal region IDs

The mapper outputs CSV files that can be consumed by the ETL pipeline.
"""

import csv
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class MappingResult:
    """Result of an ID mapping operation."""

    external_id: str
    internal_id: str
    entity_type: str
    confidence: float
    source: str
    metadata: dict = None


class IDMapper:
    """Main class for handling ID mappings between external and internal systems."""

    def __init__(self, output_dir: str = "/tmp/br_kg_mappings"):
        """
        Initialize the ID mapper.

        Args:
            output_dir: Directory to save mapping CSV files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Cache for already mapped IDs to avoid duplicates
        self.mapped_concepts: set[str] = set()
        self.mapped_tasks: set[str] = set()
        self.mapped_publications: set[str] = set()
        self.mapped_regions: set[str] = set()

        # Mapping results storage
        self.concept_mappings: list[MappingResult] = []
        self.task_mappings: list[MappingResult] = []
        self.publication_mappings: list[MappingResult] = []
        self.region_mappings: list[MappingResult] = []
        self.coordinate_mappings: list[MappingResult] = []

    def generate_internal_id(
        self, external_id: str, entity_type: str, additional_data: str = ""
    ) -> str:
        """
        Generate a deterministic internal ID from external ID.

        Args:
            external_id: The external identifier
            entity_type: Type of entity (concept, task, publication, etc.)
            additional_data: Additional data to include in hash

        Returns:
            Generated internal ID
        """
        # Create a deterministic hash from the external ID and type
        hash_input = f"{entity_type}:{external_id}:{additional_data}"
        hash_object = hashlib.md5(hash_input.encode())
        hash_hex = hash_object.hexdigest()[:12]  # Use first 12 characters

        return f"{entity_type}_{hash_hex}"

    def map_cognitive_concept(
        self, external_id: str, name: str, definition: str = ""
    ) -> MappingResult:
        """Map a single cognitive concept"""
        internal_id = self.generate_internal_id(
            external_id, "concept", name.lower().replace(" ", "_")
        )

        mapping = MappingResult(
            external_id=external_id,
            internal_id=internal_id,
            entity_type="CognitiveConcept",
            confidence=1.0,
            source="cognitive_atlas",
            metadata={"name": name, "definition": definition, "category": "general"},
        )

        self.concept_mappings.append(mapping)
        return mapping

    def map_cognitive_task(
        self, external_id: str, name: str, definition: str = ""
    ) -> MappingResult:
        """Map a single cognitive task"""
        internal_id = self.generate_internal_id(
            external_id, "task", name.lower().replace(" ", "_")
        )

        mapping = MappingResult(
            external_id=external_id,
            internal_id=internal_id,
            entity_type="CognitiveTask",
            confidence=1.0,
            source="cognitive_atlas",
            metadata={"name": name, "definition": definition, "category": "general"},
        )

        self.task_mappings.append(mapping)
        return mapping

    def map_publication(
        self, pmid: str, title: str, authors: list[str] = None
    ) -> MappingResult:
        """Map a single publication"""
        internal_id = self.generate_internal_id(pmid, "publication", title[:50])

        mapping = MappingResult(
            external_id=pmid,
            internal_id=internal_id,
            entity_type="Publication",
            confidence=1.0,
            source="pubmed",
            metadata={"title": title, "authors": authors or [], "pmid": pmid},
        )

        self.publication_mappings.append(mapping)
        return mapping

    def map_coordinate(
        self, x: float, y: float, z: float, space: str = "MNI"
    ) -> MappingResult:
        """Map a single coordinate"""
        coord_str = f"{x}_{y}_{z}_{space}"
        internal_id = self.generate_internal_id(coord_str, "coordinate", space)

        mapping = MappingResult(
            external_id=coord_str,
            internal_id=internal_id,
            entity_type="Coordinate",
            confidence=1.0,
            source="neurosynth",
            metadata={"x": x, "y": y, "z": z, "space": space},
        )

        self.coordinate_mappings.append(mapping)
        return mapping

    def map_brain_region(
        self, name: str, hemisphere: str = "", coordinates: list[dict] = None
    ) -> MappingResult:
        """Map a single brain region"""
        internal_id = self.generate_internal_id(name, "region", hemisphere)

        mapping = MappingResult(
            external_id=name,
            internal_id=internal_id,
            entity_type="BrainRegion",
            confidence=1.0,
            source="atlas",
            metadata={
                "name": name,
                "hemisphere": hemisphere,
                "coordinates": coordinates or [],
            },
        )

        self.region_mappings.append(mapping)
        return mapping
        """
        Map Cognitive Atlas concept IDs to internal IDs.

        Args:
            concepts_data: List of concept dictionaries from Cognitive Atlas API

        Returns:
            List of mapping results
        """
        logger.info(f"Mapping {len(concepts_data)} cognitive concepts")

        mappings = []
        for concept in concepts_data:
            external_id = concept.get("id", "")
            name = concept.get("name", "")

            if not external_id or external_id in self.mapped_concepts:
                continue

            internal_id = self.generate_internal_id(
                external_id, "concept", name.lower().replace(" ", "_")
            )

            mapping = MappingResult(
                external_id=external_id,
                internal_id=internal_id,
                entity_type="CognitiveConcept",
                confidence=1.0,
                source="cognitive_atlas",
                metadata={
                    "name": name,
                    "definition": concept.get("definition", ""),
                    "category": concept.get("category", ""),
                },
            )

            mappings.append(mapping)
            self.mapped_concepts.add(external_id)

        self.concept_mappings.extend(mappings)
        logger.info(f"Mapped {len(mappings)} cognitive concepts")
        return mappings

    def map_cognitive_atlas_tasks(self, tasks_data: list[dict]) -> list[MappingResult]:
        """
        Map Cognitive Atlas task IDs to internal IDs.

        Args:
            tasks_data: List of task dictionaries from Cognitive Atlas API

        Returns:
            List of mapping results
        """
        logger.info(f"Mapping {len(tasks_data)} cognitive tasks")

        mappings = []
        for task in tasks_data:
            external_id = task.get("id", "")
            name = task.get("name", "")

            if not external_id or external_id in self.mapped_tasks:
                continue

            internal_id = self.generate_internal_id(
                external_id, "task", name.lower().replace(" ", "_")
            )

            mapping = MappingResult(
                external_id=external_id,
                internal_id=internal_id,
                entity_type="CognitiveTask",
                confidence=1.0,
                source="cognitive_atlas",
                metadata={
                    "name": name,
                    "definition": task.get("definition", ""),
                    "category": task.get("category", ""),
                },
            )

            mappings.append(mapping)
            self.mapped_tasks.add(external_id)

        self.task_mappings.extend(mappings)
        logger.info(f"Mapped {len(mappings)} cognitive tasks")
        return mappings

    def map_pubmed_publications(
        self, publications_data: list[dict]
    ) -> list[MappingResult]:
        """
        Map PubMed IDs to internal publication IDs.

        Args:
            publications_data: List of publication dictionaries from PubMed

        Returns:
            List of mapping results
        """
        logger.info(f"Mapping {len(publications_data)} publications")

        mappings = []
        for pub in publications_data:
            pmid = pub.get("pmid", "")
            doi = pub.get("doi", "")
            title = pub.get("title", "")

            if not pmid or pmid in self.mapped_publications:
                continue

            # Use DOI if available, otherwise use PMID for internal ID generation
            id_source = doi if doi else pmid
            internal_id = self.generate_internal_id(
                id_source,
                "publication",
                title[:50].lower().replace(" ", "_") if title else "",
            )

            mapping = MappingResult(
                external_id=pmid,
                internal_id=internal_id,
                entity_type="Publication",
                confidence=1.0,
                source="pubmed",
                metadata={
                    "doi": doi,
                    "title": title,
                    "year": pub.get("year", ""),
                    "journal": pub.get("journal", ""),
                    "authors": pub.get("authors", []),
                },
            )

            mappings.append(mapping)
            self.mapped_publications.add(pmid)

        self.publication_mappings.extend(mappings)
        logger.info(f"Mapped {len(mappings)} publications")
        return mappings

    def map_brain_coordinates(
        self, coordinates_data: list[dict], publication_id: str = None
    ) -> list[MappingResult]:
        """
        Map brain coordinates to internal coordinate IDs.

        Args:
            coordinates_data: List of coordinate dictionaries
            publication_id: Associated publication ID

        Returns:
            List of mapping results
        """
        logger.info(f"Mapping {len(coordinates_data)} brain coordinates")

        mappings = []
        for i, coord in enumerate(coordinates_data):
            x = coord.get("x", 0)
            y = coord.get("y", 0)
            z = coord.get("z", 0)

            # Create unique coordinate identifier
            coord_key = f"{x}_{y}_{z}_{publication_id or 'unknown'}"
            internal_id = self.generate_internal_id(coord_key, "coordinate", f"{i}")

            mapping = MappingResult(
                external_id=coord_key,
                internal_id=internal_id,
                entity_type="Coordinate",
                confidence=1.0,
                source="neurosynth",
                metadata={
                    "x": x,
                    "y": y,
                    "z": z,
                    "space": coord.get("space", "MNI"),
                    "statistic_type": coord.get("statistic_type", ""),
                    "statistic_value": coord.get("statistic_value", ""),
                    "publication_id": publication_id,
                },
            )

            mappings.append(mapping)

        self.coordinate_mappings.extend(mappings)
        logger.info(f"Mapped {len(mappings)} coordinates")
        return mappings

    def map_brain_regions(self, regions_data: list[dict]) -> list[MappingResult]:
        """
        Map brain region names to internal region IDs.

        Args:
            regions_data: List of brain region dictionaries

        Returns:
            List of mapping results
        """
        logger.info(f"Mapping {len(regions_data)} brain regions")

        mappings = []
        for region in regions_data:
            name = region.get("name", "")
            atlas = region.get("atlas", "unknown")

            if not name or name in self.mapped_regions:
                continue

            # Normalize region name for ID generation
            normalized_name = re.sub(r"[^a-zA-Z0-9]", "_", name.lower())
            region_key = f"{normalized_name}_{atlas}"

            internal_id = self.generate_internal_id(region_key, "region", atlas)

            mapping = MappingResult(
                external_id=name,
                internal_id=internal_id,
                entity_type="BrainRegion",
                confidence=1.0,
                source=atlas,
                metadata={
                    "name": name,
                    "full_name": region.get("full_name", name),
                    "hemisphere": region.get("hemisphere", ""),
                    "lobe": region.get("lobe", ""),
                    "atlas": atlas,
                },
            )

            mappings.append(mapping)
            self.mapped_regions.add(name)

        self.region_mappings.extend(mappings)
        logger.info(f"Mapped {len(mappings)} brain regions")
        return mappings

    def save_mappings_to_csv(self) -> dict[str, str]:
        """
        Save all mappings to CSV files.

        Returns:
            Dictionary mapping entity type to CSV file path
        """
        file_paths = {}

        # Save concept mappings
        if self.concept_mappings:
            concepts_file = self.output_dir / "concept_mappings.csv"
            self._save_mappings_csv(self.concept_mappings, concepts_file)
            file_paths["concepts"] = str(concepts_file)

        # Save task mappings
        if self.task_mappings:
            tasks_file = self.output_dir / "task_mappings.csv"
            self._save_mappings_csv(self.task_mappings, tasks_file)
            file_paths["tasks"] = str(tasks_file)

        # Save publication mappings
        if self.publication_mappings:
            pubs_file = self.output_dir / "publication_mappings.csv"
            self._save_mappings_csv(self.publication_mappings, pubs_file)
            file_paths["publications"] = str(pubs_file)

        # Save coordinate mappings
        if self.coordinate_mappings:
            coords_file = self.output_dir / "coordinate_mappings.csv"
            self._save_mappings_csv(self.coordinate_mappings, coords_file)
            file_paths["coordinates"] = str(coords_file)

        # Save region mappings
        if self.region_mappings:
            regions_file = self.output_dir / "region_mappings.csv"
            self._save_mappings_csv(self.region_mappings, regions_file)
            file_paths["regions"] = str(regions_file)

        logger.info(f"Saved mappings to {len(file_paths)} CSV files")
        return file_paths

    def _save_mappings_csv(self, mappings: list[MappingResult], file_path: Path):
        """Save a list of mappings to a CSV file."""
        with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "external_id",
                "internal_id",
                "entity_type",
                "confidence",
                "source",
                "metadata",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for mapping in mappings:
                writer.writerow(
                    {
                        "external_id": mapping.external_id,
                        "internal_id": mapping.internal_id,
                        "entity_type": mapping.entity_type,
                        "confidence": mapping.confidence,
                        "source": mapping.source,
                        "metadata": str(mapping.metadata) if mapping.metadata else "",
                    }
                )

    def get_mapping_stats(self) -> dict[str, int]:
        """Get statistics about current mappings."""
        return {
            "concepts": len(self.concept_mappings),
            "tasks": len(self.task_mappings),
            "publications": len(self.publication_mappings),
            "coordinates": len(self.coordinate_mappings),
            "regions": len(self.region_mappings),
            "total": (
                len(self.concept_mappings)
                + len(self.task_mappings)
                + len(self.publication_mappings)
                + len(self.coordinate_mappings)
                + len(self.region_mappings)
            ),
        }


def main():
    """Example usage of the ID mapper."""
    mapper = IDMapper()

    # Example data (would normally come from API calls)
    sample_concepts = [
        {
            "id": "trm_4a3fd79d096be",
            "name": "working memory",
            "definition": "A system for temporarily storing and managing information",
            "category": "memory",
        }
    ]

    sample_tasks = [
        {
            "id": "tsk_4a3fd79d096be",
            "name": "n-back task",
            "definition": "A continuous performance task",
            "category": "working_memory",
        }
    ]

    # Map the sample data
    mapper.map_cognitive_atlas_concepts(sample_concepts)
    mapper.map_cognitive_atlas_tasks(sample_tasks)

    # Save to CSV
    file_paths = mapper.save_mappings_to_csv()

    # Print statistics
    stats = mapper.get_mapping_stats()
    print(f"Mapping Statistics: {stats}")
    print(f"Generated files: {file_paths}")


if __name__ == "__main__":
    main()
