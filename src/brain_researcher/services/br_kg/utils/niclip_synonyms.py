#!/usr/bin/env python3
"""
NiCLIP Synonym Extractor

This utility extracts task synonyms and related concepts from NiCLIP data
to build a comprehensive synonym dictionary for task mapping.

Author: BR-KG Team
"""

import argparse
import csv
import json
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NiCLIPSynonymExtractor:
    """Extract task synonyms from NiCLIP vocabulary and concept data"""

    def __init__(self, niclip_dir: str):
        """
        Initialize extractor with NiCLIP data directory

        Args:
            niclip_dir: Path to NiCLIP OSF data directory
        """
        self.niclip_dir = Path(niclip_dir)
        self.data_dir = self.niclip_dir / "data"
        self.vocab_dir = self.data_dir / "vocabulary"
        self.cogatlas_dir = self.data_dir / "cognitive_atlas"

        # Validate directories exist
        if not self.data_dir.exists():
            raise ValueError(f"NiCLIP data directory not found: {self.data_dir}")

    def load_reduced_tasks(self) -> dict[str, list[str]]:
        """
        Load reduced tasks with their top 3 related concepts

        Returns:
            Dict mapping task names to list of related concepts
        """
        reduced_tasks_path = self.cogatlas_dir / "reduced_tasks.csv"
        task_concepts = {}

        with open(reduced_tasks_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                task = row["task"]
                concepts = [row["concept_1"], row["concept_2"], row["concept_3"]]
                task_concepts[task] = concepts

        logger.info(f"Loaded {len(task_concepts)} reduced tasks")
        return task_concepts

    def load_vocabulary_priors(self) -> dict[str, float]:
        """
        Load task vocabulary with prior probabilities from NiCLIP

        Returns:
            Dict mapping task names to prior probabilities
        """
        task_priors = {}

        # Load all vocabulary prior files
        prior_files = list(self.vocab_dir.glob("*_prior.csv"))
        logger.info(f"Found {len(prior_files)} vocabulary prior files")

        for prior_file in prior_files:
            # Skip non-task vocabularies
            if "task" not in prior_file.name:
                continue

            with open(prior_file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    task_name = row["name"]
                    prior = float(row["prior"])

                    # Keep the highest prior if task appears in multiple files
                    if task_name not in task_priors or prior > task_priors[task_name]:
                        task_priors[task_name] = prior

        logger.info(f"Loaded priors for {len(task_priors)} tasks")
        return task_priors

    def load_task_definitions(self) -> dict[str, dict[str, str]]:
        """
        Load task definitions from Cognitive Atlas snapshot

        Returns:
            Dict mapping task IDs to task metadata
        """
        task_snapshot_path = self.cogatlas_dir / "task_snapshot-02-19-25.json"

        with open(task_snapshot_path) as f:
            tasks = json.load(f)

        task_defs = {}
        for task_data in tasks:
            task_id = task_data.get("id", "")
            task_defs[task_id] = {
                "name": task_data.get("name", ""),
                "definition": task_data.get("definition_text", ""),
                "alias": task_data.get("alias", ""),
            }

        logger.info(f"Loaded {len(task_defs)} task definitions")
        return task_defs

    def extract_task_variants(self, task_name: str) -> set[str]:
        """
        Extract common variants of a task name

        Args:
            task_name: Original task name

        Returns:
            Set of task name variants
        """
        variants = {task_name.lower()}

        # Remove common suffixes
        suffixes = [" task", " paradigm", " fMRI task paradigm", " test", " experiment"]
        base_name = task_name.lower()
        for suffix in suffixes:
            if base_name.endswith(suffix):
                base_name = base_name[: -len(suffix)]
                variants.add(base_name)

        # Add hyphen/space variations
        if "-" in base_name:
            variants.add(base_name.replace("-", " "))
            variants.add(base_name.replace("-", "_"))
        if " " in base_name:
            variants.add(base_name.replace(" ", "-"))
            variants.add(base_name.replace(" ", "_"))

        # Add common abbreviations
        abbreviations = {
            "theory of mind": ["tom"],
            "working memory": ["wm"],
            "response inhibition": ["ri"],
            "stop signal": ["sst"],
            "go no go": ["gng", "gonogo"],
            "attention network": ["ant"],
            "continuous performance": ["cpt"],
        }

        for full_name, abbrevs in abbreviations.items():
            if full_name in base_name:
                for abbrev in abbrevs:
                    variants.add(base_name.replace(full_name, abbrev))

        return variants

    def build_synonym_dictionary(self) -> dict[str, dict[str, any]]:
        """
        Build comprehensive synonym dictionary from all sources

        Returns:
            Dictionary with structure:
            {
                "canonical_task_name": {
                    "variants": ["variant1", "variant2", ...],
                    "related_concepts": ["concept1", "concept2", ...],
                    "prior": 0.05,
                    "confidence": 0.8
                }
            }
        """
        # Load all data sources
        task_concepts = self.load_reduced_tasks()
        task_priors = self.load_vocabulary_priors()
        task_defs = self.load_task_definitions()

        synonym_dict = {}

        # Process reduced tasks (high confidence)
        for task_name, concepts in task_concepts.items():
            canonical_name = task_name.lower()

            synonym_dict[canonical_name] = {
                "variants": list(self.extract_task_variants(task_name)),
                "related_concepts": concepts,
                "prior": task_priors.get(task_name, 0.0),
                "confidence": 0.9,  # High confidence for reduced set
                "source": "reduced_tasks",
            }

        # Add tasks from vocabulary that aren't in reduced set
        for task_name, prior in task_priors.items():
            canonical_name = task_name.lower()

            if (
                canonical_name not in synonym_dict and prior > 0.001
            ):  # Min prior threshold
                synonym_dict[canonical_name] = {
                    "variants": list(self.extract_task_variants(task_name)),
                    "related_concepts": [],
                    "prior": prior,
                    "confidence": 0.7,  # Lower confidence
                    "source": "vocabulary",
                }

        # Enhance with task definitions and aliases
        for task_id, task_info in task_defs.items():
            task_name = task_info["name"].lower()
            alias = task_info["alias"]

            if task_name in synonym_dict:
                # Add alias as variant
                if alias:
                    synonym_dict[task_name]["variants"].append(alias.lower())

        # Create reverse mapping for fast lookup
        variant_to_canonical = {}
        for canonical, info in synonym_dict.items():
            for variant in info["variants"]:
                if variant not in variant_to_canonical:
                    variant_to_canonical[variant] = []
                variant_to_canonical[variant].append(
                    {
                        "canonical": canonical,
                        "confidence": info["confidence"],
                        "prior": info["prior"],
                    }
                )

        # Sort multiple mappings by confidence and prior
        for variant in variant_to_canonical:
            variant_to_canonical[variant].sort(
                key=lambda x: (x["confidence"], x["prior"]), reverse=True
            )

        result = {
            "synonyms": synonym_dict,
            "variant_lookup": variant_to_canonical,
            "metadata": {
                "total_tasks": len(synonym_dict),
                "total_variants": len(variant_to_canonical),
                "sources": ["reduced_tasks", "vocabulary", "task_definitions"],
            },
        }

        return result

    def save_synonyms(self, output_path: str):
        """
        Build and save synonym dictionary to JSON file

        Args:
            output_path: Path to save the synonym dictionary
        """
        logger.info("Building synonym dictionary...")
        synonym_data = self.build_synonym_dictionary()

        # Ensure output directory exists
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save to JSON
        with open(output_path, "w") as f:
            json.dump(synonym_data, f, indent=2, sort_keys=True)

        logger.info(f"Saved synonym dictionary to {output_path}")
        logger.info(f"Total tasks: {synonym_data['metadata']['total_tasks']}")
        logger.info(f"Total variants: {synonym_data['metadata']['total_variants']}")

        return synonym_data


def main():
    """Command line interface for NiCLIP synonym extraction"""
    parser = argparse.ArgumentParser(
        description="Extract task synonyms from NiCLIP data"
    )
    parser.add_argument(
        "--niclip-dir",
        type=str,
        default="/data/ECoG-foundation-model/mnndl_temp/niclip/osf_data/dsj56/osfstorage/osfstorage",
        help="Path to NiCLIP OSF data directory",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="cache/niclip_synonyms.json",
        help="Output path for synonym dictionary",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Extract and save synonyms
    extractor = NiCLIPSynonymExtractor(args.niclip_dir)
    extractor.save_synonyms(args.out)


if __name__ == "__main__":
    main()
