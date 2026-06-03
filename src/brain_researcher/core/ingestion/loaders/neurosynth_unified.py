"""
Unified NeuroSynth Data Loader with NICLIP Models

This module provides a unified interface for loading NeuroSynth meta-analysis data,
integrating NICLIP's pre-trained topic models and enhanced term associations.

Features:
- Local NIMARE format data loading
- NICLIP GCLDA topic models with multiple LLM embeddings
- Enhanced term-brain associations
- Pre-computed TF-IDF features
- Coordinate database with 14,000+ studies

Author: Brain Researcher Team
"""

import gzip
import logging
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse

logger = logging.getLogger(__name__)


class NeuroSynthUnifiedLoader:
    """
    Unified NeuroSynth loader with NICLIP model integration.

    Combines functionality from:
    - neurosynth_loader.py (basic data loading)
    - enhanced_neurosynth_loader.py (relationship building)

    Adds NICLIP integration for:
    - Pre-trained GCLDA topic models
    - Enhanced term associations
    - Multiple LLM embedding variants
    """

    def __init__(
        self,
        use_niclip_models: bool = True,
        data_path: str | None = None,
        niclip_path: str | None = None,
        model_name: str = "BrainGPT-7B-v0.2",
        section: str = "abstract",
        clip_model_path: str | None = None,
    ):
        """
        Initialize the unified NeuroSynth loader.

        Args:
            use_niclip_models: Whether to use NICLIP topic models
            data_path: Path to NeuroSynth NIMARE data
            niclip_path: Path to NICLIP models
            model_name: Which NICLIP model to use
            section: Which text section (abstract/body)
        """
        self.use_niclip = use_niclip_models
        self.model_name = model_name
        self.section = (section or "abstract").lower()
        self.clip_model_override = Path(clip_model_path) if clip_model_path else None

        # Set data path
        if data_path:
            self.data_path = Path(data_path)
        else:
            # Try common locations
            for path in [
                Path("data/neurosynth_nimare/neurosynth_v7"),
                Path("/data/neurosynth_nimare/neurosynth_v7"),
                Path("/app/data/neurosynth_nimare/neurosynth_v7"),
            ]:
                if path.exists():
                    self.data_path = path
                    break
            else:
                self.data_path = Path("data/neurosynth_nimare/neurosynth_v7")

        # Set NICLIP path
        if niclip_path:
            self.niclip_path = Path(niclip_path)
        else:
            # Try common locations
            for path in [
                Path("data/niclip"),
                Path("/data/niclip"),
                Path("/app/data/niclip"),
            ]:
                if path.exists():
                    self.niclip_path = path
                    break
            else:
                self.niclip_path = Path("data/niclip")

        # Cache for loaded data
        self._coordinates_cache = None
        self._metadata_cache = None
        self._vocabulary_cache = None
        self._features_cache = None
        self._topic_models_cache = {}

        # Statistics
        self.stats = {
            "studies_loaded": 0,
            "coordinates_loaded": 0,
            "terms_loaded": 0,
            "models_loaded": 0,
            "topic_assignments": 0,
        }

        logger.info(
            f"Initialized NeuroSynthUnifiedLoader (NICLIP: {use_niclip_models})"
        )

    def load_data(
        self,
        include_coordinates: bool = True,
        include_metadata: bool = True,
        include_features: bool = True,
        include_models: bool = True,
    ) -> dict[str, Any]:
        """
        Load NeuroSynth data with optional NICLIP enhancements.

        Args:
            include_coordinates: Load coordinate data
            include_metadata: Load study metadata
            include_features: Load term features
            include_models: Load NICLIP topic models

        Returns:
            Dictionary with loaded data components
        """
        data = {}

        # Load base NeuroSynth data
        if include_coordinates:
            logger.info("Loading NeuroSynth coordinates...")
            data["coordinates"] = self.load_coordinates()

        if include_metadata:
            logger.info("Loading NeuroSynth metadata...")
            data["metadata"] = self.load_metadata()

        if include_features:
            logger.info("Loading NeuroSynth features...")
            data["features"] = self.load_features()
            data["vocabulary"] = self.load_vocabulary()

        # Enhance with NICLIP models if available
        if include_models and self.use_niclip and self._has_niclip_models():
            logger.info("Loading NICLIP topic models...")
            data["topic_models"] = self.load_topic_models()

            # Apply topic models to enhance data
            if "coordinates" in data and "topic_models" in data:
                data["enhanced_associations"] = self._enhance_with_topics(
                    data["coordinates"], data["metadata"], data["topic_models"]
                )

        return data

    def load_coordinates(self) -> pd.DataFrame:
        """Load NeuroSynth coordinate data."""
        if self._coordinates_cache is not None:
            return self._coordinates_cache

        coords_file = self.data_path / "data-neurosynth_version-7_coordinates.tsv.gz"

        if not coords_file.exists():
            logger.error(f"Coordinates file not found: {coords_file}")
            return pd.DataFrame()

        try:
            # Load coordinates
            with gzip.open(coords_file, "rt") as f:
                coords_df = pd.read_csv(f, sep="\t")

            # Rename 'id' to 'study_id' to prevent node_id collisions
            # The 'id' column contains the study PMID, but if used as-is,
            # it causes coordinates to overwrite Study/Publication nodes
            if "id" in coords_df.columns:
                coords_df.rename(columns={"id": "study_id"}, inplace=True)
                logger.info(
                    "Renamed 'id' column to 'study_id' to prevent node collisions"
                )

            # Add source field for provenance
            coords_df["source"] = "neurosynth_v7"

            # Add space field if not present
            if "space" not in coords_df.columns:
                coords_df["space"] = "MNI"

            self._coordinates_cache = coords_df
            self.stats["coordinates_loaded"] = len(coords_df)
            logger.info(f"Loaded {len(coords_df)} coordinates")

            return coords_df

        except Exception as e:
            logger.error(f"Error loading coordinates: {e}")
            return pd.DataFrame()

    def load_metadata(self) -> pd.DataFrame:
        """Load NeuroSynth study metadata."""
        if self._metadata_cache is not None:
            return self._metadata_cache

        metadata_file = self.data_path / "data-neurosynth_version-7_metadata.tsv.gz"

        if not metadata_file.exists():
            logger.error(f"Metadata file not found: {metadata_file}")
            return pd.DataFrame()

        try:
            # Load metadata
            with gzip.open(metadata_file, "rt") as f:
                metadata_df = pd.read_csv(f, sep="\t")

            self._metadata_cache = metadata_df
            self.stats["studies_loaded"] = len(metadata_df)
            logger.info(f"Loaded metadata for {len(metadata_df)} studies")

            return metadata_df

        except Exception as e:
            logger.error(f"Error loading metadata: {e}")
            return pd.DataFrame()

    def load_features(self) -> sparse.csr_matrix:
        """Load NeuroSynth term features (TF-IDF)."""
        if self._features_cache is not None:
            return self._features_cache

        features_file = (
            self.data_path
            / f"data-neurosynth_version-7_vocab-terms_source-{self.section}_type-tfidf_features.npz"
        )

        if not features_file.exists():
            if self.section != "abstract":
                fallback = (
                    self.data_path
                    / "data-neurosynth_version-7_vocab-terms_source-abstract_type-tfidf_features.npz"
                )
                if fallback.exists():
                    logger.warning(
                        "Features file for section '%s' not found; falling back to abstract features",
                        self.section,
                    )
                    features_file = fallback
                else:
                    logger.error(f"Features file not found: {features_file}")
                    return sparse.csr_matrix((0, 0))
            else:
                logger.error(f"Features file not found: {features_file}")
                return sparse.csr_matrix((0, 0))

        try:
            # Load sparse feature matrix
            features = sparse.load_npz(features_file)

            self._features_cache = features
            logger.info(f"Loaded feature matrix: {features.shape}")

            return features

        except Exception as e:
            logger.error(f"Error loading features: {e}")
            return sparse.csr_matrix((0, 0))

    def load_vocabulary(self) -> list[str]:
        """Load NeuroSynth vocabulary."""
        if self._vocabulary_cache is not None:
            return self._vocabulary_cache

        vocab_file = (
            self.data_path / "data-neurosynth_version-7_vocab-terms_vocabulary.txt"
        )

        if not vocab_file.exists():
            logger.error(f"Vocabulary file not found: {vocab_file}")
            return []

        try:
            # Load vocabulary
            with open(vocab_file) as f:
                vocabulary = [line.strip() for line in f]

            self._vocabulary_cache = vocabulary
            self.stats["terms_loaded"] = len(vocabulary)
            logger.info(f"Loaded {len(vocabulary)} terms")

            return vocabulary

        except Exception as e:
            logger.error(f"Error loading vocabulary: {e}")
            return []

    def load_topic_models(self) -> dict[str, Any]:
        """Load NICLIP pre-trained topic models."""
        if self._topic_models_cache:
            return self._topic_models_cache

        models = {}

        # Load GCLDA models
        gclda_models = self._load_gclda_models()
        if gclda_models:
            models["gclda"] = gclda_models

        # Load NeuroSynth baseline models
        baseline_models = self._load_baseline_models()
        if baseline_models:
            models["baseline"] = baseline_models

        # Load CLIP models
        clip_models = self._load_clip_models()
        if clip_models:
            models["clip"] = clip_models

        self._topic_models_cache = models
        self.stats["models_loaded"] = len(models)

        return models

    def _has_niclip_models(self) -> bool:
        """Check if NICLIP models are available."""
        if self.clip_model_override and self.clip_model_override.exists():
            return True

        if not self.niclip_path.exists():
            return False

        baseline_dir = self.niclip_path / "results" / "baseline"
        pubmed_dir = self.niclip_path / "results" / "pubmed"

        return baseline_dir.exists() or pubmed_dir.exists()

    def _load_gclda_models(self) -> dict[str, Any]:
        """Load GCLDA topic models from NICLIP."""
        models = {}

        baseline_dir = self.niclip_path / "results" / "baseline"
        if not baseline_dir.exists():
            return models

        # Pattern for GCLDA model files
        model_pattern = f"model-gclda_*{self.model_name}*{self.section}*.pkl"

        for model_file in baseline_dir.glob(model_pattern):
            try:
                logger.info(f"Loading GCLDA model: {model_file.name}")

                # Try gzip-compressed pickle first (most common)
                try:
                    with gzip.open(model_file, "rb") as f:
                        model = pickle.load(f)
                except (OSError, gzip.BadGzipFile):
                    # Fallback to regular pickle
                    with open(model_file, "rb") as f:
                        model = pickle.load(f)

                # Extract model configuration from filename
                model_file.stem.split("_")
                config = {
                    "type": "gclda",
                    "embedding": self.model_name,
                    "section": self.section,
                    "file": model_file.name,
                }

                models[model_file.stem] = {"model": model, "config": config}

            except Exception as e:
                logger.warning(f"Could not load model {model_file}: {e}")

        logger.info(f"Loaded {len(models)} GCLDA models")
        return models

    def _load_baseline_models(self) -> dict[str, Any]:
        """Load NeuroSynth baseline models from NICLIP."""
        models = {}

        baseline_dir = self.niclip_path / "results" / "baseline"
        if not baseline_dir.exists():
            return models

        # Pattern for NeuroSynth model files
        model_pattern = f"model-neurosynth_*{self.model_name}*{self.section}*.pkl"

        for model_file in baseline_dir.glob(model_pattern):
            try:
                logger.info(f"Loading baseline model: {model_file.name}")

                # Try gzip-compressed pickle first (most common)
                try:
                    with gzip.open(model_file, "rb") as f:
                        model = pickle.load(f)
                except (OSError, gzip.BadGzipFile):
                    # Fallback to regular pickle
                    with open(model_file, "rb") as f:
                        model = pickle.load(f)

                models[model_file.stem] = {
                    "model": model,
                    "config": {
                        "type": "neurosynth_baseline",
                        "embedding": self.model_name,
                        "section": self.section,
                    },
                }

            except Exception as e:
                logger.warning(f"Could not load model {model_file}: {e}")

        return models

    def _load_clip_models(self) -> dict[str, Any]:
        """Load CLIP models from NICLIP."""
        models = {}

        if self.clip_model_override:
            model_file = self.clip_model_override
            try:
                if not model_file.exists():
                    logger.warning("Clip model override does not exist: %s", model_file)
                else:
                    logger.info(f"Loading CLIP model override: {model_file.name}")
                    models[model_file.stem] = {
                        "path": str(model_file),
                        "config": {
                            "type": "clip",
                            "embedding": self.model_name,
                            "section": self.section,
                        },
                    }
                    indices_file = model_file.parent / f"{model_file.stem}-indices.npz"
                    if indices_file.exists():
                        models[model_file.stem]["indices"] = np.load(indices_file)
            except Exception as e:
                logger.warning(
                    "Could not load override clip model %s: %s", model_file, e
                )
            # If override provided, still allow directory scan in case additional models exist

        pubmed_dir = self.niclip_path / "results" / "pubmed"
        if not pubmed_dir.exists():
            return models

        # Load best CLIP models from directory matching section/model
        model_pattern = (
            f"model-clip_section-{self.section}_embedding-{self.model_name}_best.pth"
        )

        for model_file in pubmed_dir.glob(model_pattern):
            if model_file.stem in models:
                continue
            try:
                logger.info(f"Loading CLIP model: {model_file.name}")

                # Would need PyTorch to load .pth files
                # For now, just record that the model exists
                models[model_file.stem] = {
                    "path": str(model_file),
                    "config": {
                        "type": "clip",
                        "embedding": self.model_name,
                        "section": self.section,
                    },
                }

                # Load associated indices if available
                indices_file = model_file.parent / f"{model_file.stem}-indices.npz"
                if indices_file.exists():
                    indices_data = np.load(indices_file)
                    models[model_file.stem]["indices"] = indices_data

            except Exception as e:
                logger.warning(f"Could not load model {model_file}: {e}")

        return models

    def _enhance_with_topics(
        self,
        coordinates: pd.DataFrame,
        metadata: pd.DataFrame,
        topic_models: dict[str, Any],
    ) -> dict[str, Any]:
        """Enhance NeuroSynth data with topic model predictions."""
        enhancements = {}

        # Use the first available GCLDA model
        gclda_models = topic_models.get("gclda", {})
        if not gclda_models:
            return enhancements

        model_name, model_data = next(iter(gclda_models.items()))
        model = model_data["model"]

        logger.info(f"Enhancing data with model: {model_name}")

        try:
            # Extract topic assignments
            if hasattr(model, "doc_topic_"):
                doc_topics = model.doc_topic_
                enhancements["document_topics"] = doc_topics

                # Find dominant topics
                dominant_topics = np.argmax(doc_topics, axis=1)
                enhancements["dominant_topics"] = dominant_topics

                self.stats["topic_assignments"] = len(dominant_topics)

            # Extract topic-word distributions
            if hasattr(model, "topic_word_"):
                topic_words = model.topic_word_
                enhancements["topic_words"] = topic_words

            # Extract topic-coordinate distributions if available
            if hasattr(model, "topic_coordinate_"):
                topic_coords = model.topic_coordinate_
                enhancements["topic_coordinates"] = topic_coords

            logger.info(f"Enhanced {len(enhancements)} data components")

        except Exception as e:
            logger.error(f"Error enhancing with topics: {e}")

        return enhancements

    def get_term_associations(
        self, term: str, threshold: float = 0.001
    ) -> list[dict[str, Any]]:
        """Get brain regions associated with a term."""
        associations = []

        # Load vocabulary and features
        vocabulary = self.load_vocabulary()
        features = self.load_features()
        coordinates = self.load_coordinates()

        if term not in vocabulary:
            logger.warning(f"Term '{term}' not in vocabulary")
            return associations

        # Get term index
        term_idx = vocabulary.index(term)

        # Get studies with this term
        term_features = features[:, term_idx].toarray().flatten()
        active_studies = np.where(term_features > threshold)[0]

        # Get coordinates for active studies
        for study_idx in active_studies:
            study_coords = coordinates[coordinates["id"] == study_idx]
            for _, coord in study_coords.iterrows():
                associations.append(
                    {
                        "study_id": study_idx,
                        "x": coord["x"],
                        "y": coord["y"],
                        "z": coord["z"],
                        "weight": term_features[study_idx],
                    }
                )

        return associations

    def perform_meta_analysis(
        self, terms: list[str], method: str = "mkda"
    ) -> dict[str, Any]:
        """Perform meta-analysis for given terms."""
        results = {"terms": terms, "method": method, "studies": [], "coordinates": []}

        # Get associations for each term
        all_coords = []
        for term in terms:
            associations = self.get_term_associations(term)
            all_coords.extend(associations)

        if not all_coords:
            logger.warning(f"No coordinates found for terms: {terms}")
            return results

        # Aggregate coordinates
        coords_df = pd.DataFrame(all_coords)

        # Simple aggregation for now
        results["studies"] = coords_df["study_id"].unique().tolist()
        results["coordinates"] = coords_df[["x", "y", "z", "weight"]].to_dict("records")
        results["n_studies"] = len(results["studies"])
        results["n_coordinates"] = len(results["coordinates"])

        return results

    def export_for_nimare(self, output_dir: str) -> dict[str, str]:
        """Export data in NiMARE format for meta-analysis."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        files = {}

        # Export coordinates
        coords = self.load_coordinates()
        if not coords.empty:
            coords_file = output_dir / "coordinates.tsv"
            coords.to_csv(coords_file, sep="\t", index=False)
            files["coordinates"] = str(coords_file)

        # Export metadata
        metadata = self.load_metadata()
        if not metadata.empty:
            metadata_file = output_dir / "metadata.tsv"
            metadata.to_csv(metadata_file, sep="\t", index=False)
            files["metadata"] = str(metadata_file)

        # Export vocabulary
        vocabulary = self.load_vocabulary()
        if vocabulary:
            vocab_file = output_dir / "vocabulary.txt"
            with open(vocab_file, "w") as f:
                f.write("\n".join(vocabulary))
            files["vocabulary"] = str(vocab_file)

        logger.info(f"Exported NiMARE data to {output_dir}")
        return files

    def get_statistics(self) -> dict[str, Any]:
        """Get loader statistics."""
        return self.stats.copy()


# Convenience function for backward compatibility
def load_neurosynth(use_niclip: bool = True, model: str = "BrainGPT-7B-v0.2"):
    """
    Load NeuroSynth data using the unified loader.

    Args:
        use_niclip: Whether to use NICLIP models
        model: Which NICLIP model to use

    Returns:
        Dictionary with NeuroSynth data components
    """
    loader = NeuroSynthUnifiedLoader(use_niclip_models=use_niclip, model_name=model)
    return loader.load_data()


if __name__ == "__main__":
    # Example usage
    loader = NeuroSynthUnifiedLoader(use_niclip_models=True)

    # Load all data
    data = loader.load_data()

    # Print summary
    print(f"Studies: {loader.stats['studies_loaded']}")
    print(f"Coordinates: {loader.stats['coordinates_loaded']}")
    print(f"Terms: {loader.stats['terms_loaded']}")
    print(f"Models: {loader.stats['models_loaded']}")

    # Perform meta-analysis
    results = loader.perform_meta_analysis(["working memory", "attention"])
    print(
        f"\nMeta-analysis: {results['n_studies']} studies, {results['n_coordinates']} coordinates"
    )

    # Get term associations
    associations = loader.get_term_associations("language")
    print(f"\nLanguage associations: {len(associations)} coordinates")
