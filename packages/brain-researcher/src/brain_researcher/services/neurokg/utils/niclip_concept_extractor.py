#!/usr/bin/env python3
"""
NiCLIP Concept Frequency Extractor

This utility extracts concept frequencies and GLM weights from NiCLIP data
to build a comprehensive weight prior dictionary for concept linking.

Author: BR-KG Team
"""

import argparse
import csv
import json
import logging
from pathlib import Path

import numpy as np

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NiCLIPConceptExtractor:
    """Extract concept frequencies and weights from NiCLIP data"""

    def __init__(self, niclip_dir: str):
        """
        Initialize extractor with NiCLIP data directory

        Args:
            niclip_dir: Path to NiCLIP OSF data directory
        """
        self.niclip_dir = Path(niclip_dir)
        self.data_dir = self.niclip_dir / "data"
        self.results_dir = self.niclip_dir / "results" / "pubmed"
        self.cogatlas_dir = self.data_dir / "cognitive_atlas"

        # Validate directories
        if not self.data_dir.exists():
            raise ValueError(f"NiCLIP data directory not found: {self.data_dir}")
        if not self.results_dir.exists():
            raise ValueError(f"NiCLIP results directory not found: {self.results_dir}")

    def load_concept_definitions(self) -> dict[str, dict[str, str]]:
        """
        Load concept definitions from Cognitive Atlas snapshot

        Returns:
            Dict mapping concept IDs to concept metadata
        """
        concept_snapshot_path = self.cogatlas_dir / "concept_snapshot-02-19-25.json"

        with open(concept_snapshot_path) as f:
            concepts = json.load(f)

        concept_defs = {}
        for concept_data in concepts:
            concept_id = concept_data.get("id", "")
            concept_defs[concept_id] = {
                "name": concept_data.get("name", ""),
                "definition": concept_data.get("definition_text", ""),
                "alias": concept_data.get("alias", ""),
                "id_concept_class": concept_data.get("id_concept_class", ""),
            }

        logger.info(f"Loaded {len(concept_defs)} concept definitions")
        return concept_defs

    def load_pubmed_frequencies(self) -> dict[str, dict[str, float]]:
        """
        Load concept frequencies from PubMed co-occurrence data

        Returns:
            Dict with concept frequencies and co-occurrence scores
        """
        frequencies = {}

        # Load concept frequency file
        freq_file = self.results_dir / "concept_frequencies_pubmed.json"
        if freq_file.exists():
            with open(freq_file) as f:
                frequencies = json.load(f)
                logger.info(f"Loaded concept frequencies from {freq_file}")
        else:
            logger.warning(f"Concept frequency file not found: {freq_file}")

        # Load co-occurrence matrix if available
        cooccur_file = self.results_dir / "concept_cooccurrence_matrix.npy"
        if cooccur_file.exists():
            cooccur_matrix = np.load(cooccur_file)
            logger.info(
                f"Loaded co-occurrence matrix with shape {cooccur_matrix.shape}"
            )
            frequencies["_cooccurrence_matrix"] = cooccur_matrix.tolist()

        return frequencies

    def load_glm_weights(self) -> dict[str, dict[str, float]]:
        """
        Load GLM weights from NiCLIP model results

        Returns:
            Dict mapping contrasts to concept weights
        """
        glm_weights = {}

        # Look for GLM weight files
        weight_files = list(self.results_dir.glob("glm_weights_*.json"))
        logger.info(f"Found {len(weight_files)} GLM weight files")

        for weight_file in weight_files:
            with open(weight_file) as f:
                weights = json.load(f)

            # Extract contrast name from filename
            contrast_name = weight_file.stem.replace("glm_weights_", "")
            glm_weights[contrast_name] = weights

        # Also check for aggregated weights
        aggregated_file = self.results_dir / "aggregated_glm_weights.json"
        if aggregated_file.exists():
            with open(aggregated_file) as f:
                glm_weights["_aggregated"] = json.load(f)
                logger.info("Loaded aggregated GLM weights")

        return glm_weights

    def load_contrast_concept_mappings(self) -> dict[str, list[tuple[str, float]]]:
        """
        Load pre-computed contrast to concept mappings

        Returns:
            Dict mapping contrast names to list of (concept, weight) tuples
        """
        mappings = {}

        # Look for mapping files
        mapping_file = self.results_dir / "contrast_concept_mappings.json"
        if mapping_file.exists():
            with open(mapping_file) as f:
                raw_mappings = json.load(f)

            # Convert to expected format
            for contrast, concepts in raw_mappings.items():
                if isinstance(concepts, list):
                    mappings[contrast] = [
                        (c["concept"], c["weight"])
                        for c in concepts
                        if "concept" in c and "weight" in c
                    ]
                elif isinstance(concepts, dict):
                    mappings[contrast] = [
                        (concept, weight) for concept, weight in concepts.items()
                    ]

            logger.info(f"Loaded mappings for {len(mappings)} contrasts")

        return mappings

    def extract_concept_vocabulary(self) -> dict[str, float]:
        """
        Extract concept vocabulary with prior probabilities

        Returns:
            Dict mapping concept names to prior probabilities
        """
        concept_priors = {}

        # Load vocabulary files
        vocab_files = list((self.data_dir / "vocabulary").glob("*_prior.csv"))

        for vocab_file in vocab_files:
            # Skip non-concept vocabularies
            if "concept" not in vocab_file.name.lower():
                continue

            with open(vocab_file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    concept_name = row["name"]
                    prior = float(row["prior"])

                    # Keep highest prior if concept appears in multiple files
                    if (
                        concept_name not in concept_priors
                        or prior > concept_priors[concept_name]
                    ):
                        concept_priors[concept_name] = prior

        logger.info(f"Extracted priors for {len(concept_priors)} concepts")
        return concept_priors

    def calculate_concept_importance(
        self,
        concept_defs: dict[str, dict[str, str]],
        frequencies: dict[str, dict[str, float]],
        glm_weights: dict[str, dict[str, float]],
        concept_priors: dict[str, float],
    ) -> dict[str, float]:
        """
        Calculate overall importance score for each concept

        Args:
            concept_defs: Concept definitions
            frequencies: PubMed frequencies
            glm_weights: GLM model weights
            concept_priors: Vocabulary priors

        Returns:
            Dict mapping concept names to importance scores
        """
        importance_scores = {}

        # Weight components
        weights = {"frequency": 0.3, "glm": 0.4, "prior": 0.3}

        # Get all concept names
        all_concepts = set()
        for concept_id, concept_info in concept_defs.items():
            name = concept_info["name"].lower()
            all_concepts.add(name)
            if concept_info["alias"]:
                all_concepts.add(concept_info["alias"].lower())

        # Calculate scores
        for concept_name in all_concepts:
            score_components = []

            # Frequency component
            if concept_name in frequencies:
                freq_score = frequencies[concept_name].get("normalized_frequency", 0)
                score_components.append(("frequency", freq_score))

            # GLM component (average across all contrasts)
            glm_scores = []
            for contrast, weights_dict in glm_weights.items():
                if contrast.startswith("_"):
                    continue
                if concept_name in weights_dict:
                    glm_scores.append(abs(weights_dict[concept_name]))
            if glm_scores:
                glm_score = np.mean(glm_scores)
                score_components.append(("glm", glm_score))

            # Prior component
            if concept_name in concept_priors:
                prior_score = concept_priors[concept_name]
                score_components.append(("prior", prior_score))

            # Calculate weighted average
            if score_components:
                total_weight = sum(weights[comp[0]] for comp in score_components)
                weighted_sum = sum(
                    weights[comp[0]] * comp[1] for comp in score_components
                )
                importance_scores[concept_name] = weighted_sum / total_weight
            else:
                importance_scores[concept_name] = 0.0

        # Normalize scores to 0-1 range
        if importance_scores:
            max_score = max(importance_scores.values())
            if max_score > 0:
                for concept in importance_scores:
                    importance_scores[concept] /= max_score

        logger.info(
            f"Calculated importance scores for {len(importance_scores)} concepts"
        )
        return importance_scores

    def build_weight_prior_dictionary(self) -> dict[str, dict[str, any]]:
        """
        Build comprehensive weight prior dictionary

        Returns:
            Dictionary with structure:
            {
                "concepts": {
                    "concept_name": {
                        "importance": 0.8,
                        "frequency": 0.05,
                        "glm_weight_mean": 2.3,
                        "prior": 0.03,
                        "aliases": ["alias1", "alias2"],
                        "definition": "...",
                        "contrasts": {
                            "contrast1": 2.5,
                            "contrast2": 1.8
                        }
                    }
                },
                "contrast_mappings": {
                    "contrast_name": [
                        {"concept": "concept1", "weight": 2.5},
                        {"concept": "concept2", "weight": 1.8}
                    ]
                },
                "metadata": {...}
            }
        """
        # Load all data sources
        concept_defs = self.load_concept_definitions()
        frequencies = self.load_pubmed_frequencies()
        glm_weights = self.load_glm_weights()
        concept_priors = self.extract_concept_vocabulary()
        contrast_mappings = self.load_contrast_concept_mappings()

        # Calculate importance scores
        importance_scores = self.calculate_concept_importance(
            concept_defs, frequencies, glm_weights, concept_priors
        )

        # Build concept dictionary
        concepts_dict = {}

        for concept_id, concept_info in concept_defs.items():
            name = concept_info["name"].lower()

            # Collect all GLM weights for this concept
            contrast_weights = {}
            for contrast, weights_dict in glm_weights.items():
                if contrast.startswith("_"):
                    continue
                if name in weights_dict:
                    contrast_weights[contrast] = weights_dict[name]

            # Build concept entry
            concepts_dict[name] = {
                "importance": importance_scores.get(name, 0.0),
                "frequency": frequencies.get(name, {}).get("frequency", 0),
                "glm_weight_mean": (
                    np.mean(list(contrast_weights.values()))
                    if contrast_weights
                    else 0.0
                ),
                "glm_weight_std": (
                    np.std(list(contrast_weights.values())) if contrast_weights else 0.0
                ),
                "prior": concept_priors.get(name, 0.0),
                "aliases": [concept_info["alias"]] if concept_info["alias"] else [],
                "definition": concept_info["definition"],
                "id": concept_id,
                "contrasts": contrast_weights,
            }

        # Format contrast mappings
        formatted_mappings = {}
        for contrast, concept_list in contrast_mappings.items():
            formatted_mappings[contrast] = [
                {"concept": concept, "weight": weight}
                for concept, weight in concept_list[:20]  # Top 20 concepts per contrast
            ]

        # Build final dictionary
        result = {
            "concepts": concepts_dict,
            "contrast_mappings": formatted_mappings,
            "metadata": {
                "total_concepts": len(concepts_dict),
                "total_contrasts": len(formatted_mappings),
                "sources": ["cognitive_atlas", "pubmed", "niclip_glm"],
                "importance_weights": {"frequency": 0.3, "glm": 0.4, "prior": 0.3},
            },
        }

        return result

    def save_weight_priors(self, output_path: str):
        """
        Build and save weight prior dictionary to JSON file

        Args:
            output_path: Path to save the weight prior dictionary
        """
        logger.info("Building weight prior dictionary...")
        weight_data = self.build_weight_prior_dictionary()

        # Ensure output directory exists
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save to JSON
        with open(output_path, "w") as f:
            json.dump(weight_data, f, indent=2, sort_keys=True)

        logger.info(f"Saved weight prior dictionary to {output_path}")
        logger.info(f"Total concepts: {weight_data['metadata']['total_concepts']}")
        logger.info(f"Total contrasts: {weight_data['metadata']['total_contrasts']}")

        return weight_data


def main():
    """Command line interface for NiCLIP concept extraction"""
    parser = argparse.ArgumentParser(
        description="Extract concept frequencies and weights from NiCLIP data"
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
        default="cache/niclip_weight_priors.json",
        help="Output path for weight prior dictionary",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Extract and save weight priors
    extractor = NiCLIPConceptExtractor(args.niclip_dir)
    extractor.save_weight_priors(args.out)


if __name__ == "__main__":
    main()
