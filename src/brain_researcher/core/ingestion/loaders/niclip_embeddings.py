"""
NICLIP Embedding Loader

Central loader for all NICLIP pre-computed embeddings, models, and mappings.
This module provides easy access to:
- Text embeddings (abstracts/bodies) from multiple LLMs
- Brain coordinate embeddings (MKDA, DiFuMo)
- Task-concept vocabulary mappings
- Pre-trained CLIP models for text-brain mapping
- Prior distributions for Bayesian inference

Author: Brain Researcher Team
"""

import gzip
import json
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingBatch:
    """Container for a batch of NICLIP embeddings and their metadata."""

    embeddings: np.ndarray
    study_ids: List[str]
    file_path: str
    metadata: Dict[str, Any]


class NICLIPEmbeddingLoader:
    """
    Central loader for all NICLIP resources.

    NICLIP (Neuroimaging-Cognitive Mapping with Language-Image Pretraining)
    provides pre-computed embeddings and trained models for text-brain mapping.
    """

    # Available models
    AVAILABLE_MODELS = [
        "BrainGPT-7B-v0.1",
        "BrainGPT-7B-v0.2",
        "Llama-2-7b-chat-hf",
        "Mistral-7B-v0.1"
    ]

    # Available text sections
    TEXT_SECTIONS = ["abstract", "body"]

    # Available normalizations
    NORMALIZATIONS = ["raw", "normalized", "standardized"]

    # Coordinate embedding methods
    COORDINATE_METHODS = ["MKDA", "DiFuMo"]

    def __init__(self, root_path: Optional[str] = None):
        """
        Initialize the NICLIP embedding loader.

        Args:
            root_path: Root path to NICLIP data directory
        """
        # Set root path
        if root_path:
            self.root = Path(root_path)
        else:
            # Try common locations
            for path in [
                Path("data/niclip"),
                Path("/data/niclip"),
                Path("/app/data/niclip"),
            ]:
                if path.exists():
                    self.root = path
                    break
            else:
                self.root = Path("data/niclip")

        # Define subdirectories
        self.data_dir = self.root / "data"
        self.results_dir = self.root / "results"

        # Cache for loaded data
        self._cache: Dict[str, Any] = {}
        self._pmid_mapping: Optional[List[str]] = None
        self._study_index_lookup: Optional[Dict[str, int]] = None

        # Statistics
        self.stats = {
            "embeddings_loaded": 0,
            "models_loaded": 0,
            "vocabularies_loaded": 0
        }

        # Validate installation
        self._validate_installation()

        logger.info(f"Initialized NICLIPEmbeddingLoader at {self.root}")

    def _validate_installation(self):
        """Validate that NICLIP data is properly installed."""
        if not self.root.exists():
            logger.warning(f"NICLIP root directory not found: {self.root}")
            return

        # Check for key directories
        required_dirs = ["data", "results"]
        missing = []

        for dir_name in required_dirs:
            dir_path = self.root / dir_name
            if not dir_path.exists():
                missing.append(dir_name)

        if missing:
            logger.warning(f"Missing NICLIP directories: {missing}")

        # Check for key data files
        if self.data_dir.exists():
            subdirs = ["text", "image", "vocabulary", "cognitive_atlas"]
            for subdir in subdirs:
                if not (self.data_dir / subdir).exists():
                    logger.warning(f"Missing NICLIP data subdirectory: {subdir}")

    def _load_study_id_mapping(self) -> List[str]:
        if self._pmid_mapping is not None:
            return self._pmid_mapping

        mapping_file = self.data_dir / "text" / "pmid_mapping.txt"
        if not mapping_file.exists():
            logger.warning("NICLIP PMID mapping file not found; placeholder IDs will be used")
            self._pmid_mapping = []
            return self._pmid_mapping

        with mapping_file.open() as handle:
            self._pmid_mapping = [line.strip() for line in handle if line.strip()]
        logger.info(
            "Loaded %d NICLIP study IDs from pmid_mapping.txt",
            len(self._pmid_mapping),
        )
        return self._pmid_mapping


    def _align_study_ids(self, count: int) -> List[str]:
        mapping = self._load_study_id_mapping()
        if mapping:
            if len(mapping) >= count:
                return mapping[:count]
            padded = mapping + [f"niclip_study_{i}" for i in range(len(mapping), count)]
            return padded
        return [f"niclip_study_{i}" for i in range(count)]

    def _relativize_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(Path.cwd()))
        except ValueError:
            return str(path)

    def _normalize_study_id(self, study_id: str) -> str:
        sid = str(study_id or "").strip()
        if sid.startswith("neurosynth:"):
            return sid.split("neurosynth:", 1)[1]
        return sid

    def _get_study_index(self, study_id: str) -> Optional[int]:
        sid = self._normalize_study_id(study_id)
        mapping = self._load_study_id_mapping()
        if not mapping:
            return None
        if self._study_index_lookup is None:
            self._study_index_lookup = {val: idx for idx, val in enumerate(mapping) if val}
        if sid in self._study_index_lookup:
            return self._study_index_lookup[sid]
        return None

    def _load_vector_at(
        self, filepath: Path, index: int, include_vector: bool
    ) -> Tuple[Optional[np.ndarray], float, int]:
        arr = np.load(filepath, mmap_mode="r")
        vector = np.asarray(arr[index]).astype(np.float32)
        norm = float(np.linalg.norm(vector))
        dimension = int(vector.shape[0])
        if not include_vector:
            return None, norm, dimension
        return vector, norm, dimension


    def get_text_embeddings(
        self,
        *,
        model: str = "BrainGPT-7B-v0.2",
        section: str = "abstract",
        normalization: str = "normalized"
    ) -> Optional[EmbeddingBatch]:
        """Load NICLIP text embeddings and study identifiers."""

        if model not in self.AVAILABLE_MODELS:
            logger.warning("Model %s not supported", model)
            return None
        if section not in self.TEXT_SECTIONS:
            logger.warning("Section %s not supported", section)
            return None
        if normalization not in self.NORMALIZATIONS:
            logger.warning("Normalization %s not supported", normalization)
            return None

        cache_key = f"text_{model}_{section}_{normalization}"
        cached = self._cache.get(cache_key)
        if isinstance(cached, EmbeddingBatch):
            return cached

        filename = f"text-{normalization}_section-{section}_embedding-{model}.npy"
        filepath = self.data_dir / "text" / filename
        if not filepath.exists():
            logger.warning("Text embedding file not found: %s", filepath)
            return None

        try:
            embeddings = np.load(filepath)
        except Exception as exc:
            logger.error("Unable to load %s: %s", filepath, exc)
            return None

        study_ids = self._align_study_ids(len(embeddings))
        batch = EmbeddingBatch(
            embeddings=embeddings,
            study_ids=study_ids,
            file_path=self._relativize_path(filepath),
            metadata={
                "kind": "text",
                "model": model,
                "section": section,
                "normalization": normalization,
            },
        )
        self._cache[cache_key] = batch
        self.stats["embeddings_loaded"] += 1
        logger.info("Loaded %s text embeddings", embeddings.shape)
        return batch

    def get_coordinate_embeddings(
        self,
        *,
        method: str = "MKDA",
        normalization: str = "standardized",
        model: str = "BrainGPT-7B-v0.2",
        summary: Optional[str] = None,
        file_override: Optional[str] = None,
    ) -> Optional[EmbeddingBatch]:
        """Load NICLIP activation embeddings (coordinate-derived)."""

        cache_key = f"coord_{method}_{normalization}_{model}_{summary}_{file_override}"
        cached = self._cache.get(cache_key)
        if isinstance(cached, EmbeddingBatch):
            return cached

        filepath = self._resolve_coordinate_file(
            method=method,
            normalization=normalization,
            model=model,
            summary=summary,
            file_override=file_override,
        )
        if filepath is None:
            return None

        try:
            embeddings = np.load(filepath)
        except Exception as exc:
            logger.error("Unable to load %s: %s", filepath, exc)
            return None

        study_ids = self._align_study_ids(len(embeddings))
        resolved_summary = summary or method
        resolved_model = filepath.stem.split("embedding-")[-1]
        batch = EmbeddingBatch(
            embeddings=embeddings,
            study_ids=study_ids,
            file_path=self._relativize_path(filepath),
            metadata={
                "kind": "activation",
                "method": method,
                "summary": resolved_summary,
                "model": resolved_model,
                "normalization": normalization,
            },
        )
        self._cache[cache_key] = batch
        self.stats["embeddings_loaded"] += 1
        logger.info("Loaded coordinate embeddings %s (summary=%s)", embeddings.shape, resolved_summary)
        return batch

    def _resolve_coordinate_file(
        self,
        *,
        method: str,
        normalization: str,
        model: str,
        summary: Optional[str],
        file_override: Optional[str],
    ) -> Optional[Path]:
        if file_override:
            override = Path(file_override)
            if override.exists():
                return override
            logger.warning("Coordinate override file not found: %s", override)
        candidates: List[Path] = []
        if summary:
            candidates.append(
                self.data_dir / "image" / f"coords_method-{method}_summary-{summary}_embedding-{model}.npy"
            )
        candidates.append(
            self.data_dir / "image" / f"coords_method-{method}_embedding-{model}.npy"
        )
        candidates.append(
            self.data_dir / "image" / f"image-{normalization}_coord-{method}_embedding-{model}.npy"
        )
        candidates.append(
            self.data_dir / "image" / f"image-{normalization}_coord-{method}_embedding-DiFuMo.npy"
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        logger.warning(
            "Coordinate embeddings not found (method=%s, model=%s)",
            method,
            model,
        )
        return None

    def get_single_embedding(
        self,
        *,
        study_id: str,
        kind: str = "text",
        include_vector: bool = False,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """Return a single NICLIP embedding row without loading the full matrix."""

        index = self._get_study_index(study_id)
        if index is None:
            logger.warning("Unknown study_id %s for NICLIP embeddings", study_id)
            return None

        if kind == "text":
            model = kwargs.get("model", "BrainGPT-7B-v0.2")
            section = kwargs.get("section", "abstract")
            normalization = kwargs.get("normalization", "normalized")
            filename = f"text-{normalization}_section-{section}_embedding-{model}.npy"
            filepath = self.data_dir / "text" / filename
            if not filepath.exists():
                logger.warning("Text embedding file not found: %s", filepath)
                return None
            vector, norm, dimension = self._load_vector_at(
                filepath, index, include_vector
            )
            return {
                "study_id": self._normalize_study_id(study_id),
                "kind": "text",
                "model": model,
                "section": section,
                "normalization": normalization,
                "storage_path": self._relativize_path(filepath),
                "storage_index": index,
                "dimension": dimension,
                "vector_norm": norm,
                "vector": vector.tolist() if (include_vector and vector is not None) else None,
            }

        if kind == "activation":
            method = kwargs.get("method", "MKDA")
            normalization = kwargs.get("normalization", "standardized")
            model = kwargs.get("model", "BrainGPT-7B-v0.2")
            summary = kwargs.get("summary")
            file_override = kwargs.get("file_override")
            filepath = self._resolve_coordinate_file(
                method=method,
                normalization=normalization,
                model=model,
                summary=summary,
                file_override=file_override,
            )
            if filepath is None:
                return None
            vector, norm, dimension = self._load_vector_at(
                filepath, index, include_vector
            )
            resolved_summary = summary or method
            return {
                "study_id": self._normalize_study_id(study_id),
                "kind": "activation",
                "model": filepath.stem.split("embedding-")[-1],
                "activation_method": method,
                "activation_summary": resolved_summary,
                "normalization": normalization,
                "storage_path": self._relativize_path(filepath),
                "storage_index": index,
                "dimension": dimension,
                "vector_norm": norm,
                "vector": vector.tolist() if (include_vector and vector is not None) else None,
            }

        logger.warning("Unsupported NICLIP embedding kind %s", kind)
        return None
    def get_vocabulary_embeddings(
        self,
        task_type: str = "cogatlas",
        embedding_type: str = "combined",
        model: str = "BrainGPT-7B-v0.2"
    ) -> Optional[np.ndarray]:
        """
        Load vocabulary embeddings for tasks/concepts.

        Args:
            task_type: Task vocabulary type (cogatlas or cogatlasred)
            embedding_type: Type of embedding (names, definitions, combined)
            model: Model used for embeddings

        Returns:
            Numpy array of vocabulary embeddings or None if not found
        """
        # Check cache
        cache_key = f"vocab_{task_type}_{embedding_type}_{model}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Build file path
        filename = f"vocabulary-{task_type}_task-{embedding_type}_embedding-{model}.npy"
        filepath = self.data_dir / "vocabulary" / filename

        if not filepath.exists():
            logger.warning(f"Vocabulary embedding file not found: {filepath}")
            return None

        try:
            # Load embeddings
            logger.info(f"Loading vocabulary embeddings: {filename}")
            embeddings = np.load(filepath)

            # Cache and update stats
            self._cache[cache_key] = embeddings
            self.stats["vocabularies_loaded"] += 1

            logger.info(f"Loaded vocabulary embeddings shape: {embeddings.shape}")
            return embeddings

        except Exception as e:
            logger.error(f"Error loading vocabulary embeddings: {e}")
            return None

    def get_vocabulary_list(self, task_type: str = "cogatlas") -> List[str]:
        """
        Get the vocabulary list for a task type.

        Args:
            task_type: Task vocabulary type (cogatlas or cogatlasred)

        Returns:
            List of vocabulary terms
        """
        vocab_file = self.data_dir / "vocabulary" / f"vocabulary-{task_type}_task.txt"

        if not vocab_file.exists():
            logger.warning(f"Vocabulary file not found: {vocab_file}")
            return []

        try:
            with open(vocab_file) as f:
                vocabulary = [line.strip() for line in f]

            logger.info(f"Loaded {len(vocabulary)} vocabulary terms")
            return vocabulary

        except Exception as e:
            logger.error(f"Error loading vocabulary: {e}")
            return []

    def get_prior_distributions(
        self,
        task_type: str = "cogatlas",
        model: str = "BrainGPT-7B-v0.2",
        section: str = "abstract"
    ) -> Optional[Union[np.ndarray, pd.DataFrame]]:
        """
        Load prior distributions for Bayesian inference.

        Args:
            task_type: Task vocabulary type
            model: Model name
            section: Text section

        Returns:
            Prior distributions as numpy array or pandas DataFrame
        """
        # Try numpy format first
        npy_file = (self.data_dir / "vocabulary" /
                   f"vocabulary-{task_type}_task-combined_embedding-{model}_section-{section}_prior.npy")

        if npy_file.exists():
            try:
                priors = np.load(npy_file)
                logger.info(f"Loaded prior distributions: {priors.shape}")
                return priors
            except Exception as e:
                logger.warning(f"Could not load numpy priors: {e}")

        # Try CSV format
        csv_file = (self.data_dir / "vocabulary" /
                   f"vocabulary-{task_type}_task-combined_embedding-{model}_section-{section}_prior.csv")

        if csv_file.exists():
            try:
                priors = pd.read_csv(csv_file)
                logger.info(f"Loaded prior distributions: {priors.shape}")
                return priors
            except Exception as e:
                logger.warning(f"Could not load CSV priors: {e}")

        logger.warning("No prior distributions found")
        return None

    def get_trained_models(
        self,
        dataset: str = "neurosynth",
        model_type: str = "gclda"
    ) -> Dict[str, Any]:
        """
        Load pre-trained NICLIP models.

        Args:
            dataset: Dataset the model was trained on (neurosynth, pubmed)
            model_type: Type of model (gclda, clip, baseline)

        Returns:
            Dictionary of available models
        """
        models = {}

        if dataset == "neurosynth" and model_type == "gclda":
            models.update(self._load_gclda_models())
        elif dataset == "neurosynth" and model_type == "baseline":
            models.update(self._load_baseline_models())
        elif dataset == "pubmed" and model_type == "clip":
            models.update(self._load_clip_models())

        self.stats["models_loaded"] += len(models)
        return models

    def _load_gclda_models(self) -> Dict[str, Any]:
        """Load GCLDA topic models."""
        models = {}
        baseline_dir = self.results_dir / "baseline"

        if not baseline_dir.exists():
            return models

        for model_file in baseline_dir.glob("model-gclda_*.pkl"):
            try:
                # Try gzip-compressed pickle first (NICLIP files are often compressed)
                try:
                    with gzip.open(model_file, 'rb') as f:
                        model = pickle.load(f)
                except (OSError, gzip.BadGzipFile):
                    # Fallback to raw pickle
                    with open(model_file, 'rb') as f:
                        model = pickle.load(f)

                models[model_file.stem] = {
                    "model": model,
                    "path": str(model_file),
                    "type": "gclda"
                }
                logger.info(f"Loaded GCLDA model: {model_file.name}")

            except Exception as e:
                logger.warning(f"Could not load {model_file}: {e}")

        return models

    def _load_baseline_models(self) -> Dict[str, Any]:
        """Load baseline models."""
        models = {}
        baseline_dir = self.results_dir / "baseline"

        if not baseline_dir.exists():
            return models

        for model_file in baseline_dir.glob("model-neurosynth_*.pkl"):
            try:
                # Try gzip-compressed pickle first (NICLIP files are often compressed)
                try:
                    with gzip.open(model_file, 'rb') as f:
                        model = pickle.load(f)
                except (OSError, gzip.BadGzipFile):
                    # Fallback to raw pickle
                    with open(model_file, 'rb') as f:
                        model = pickle.load(f)

                models[model_file.stem] = {
                    "model": model,
                    "path": str(model_file),
                    "type": "baseline"
                }
                logger.info(f"Loaded baseline model: {model_file.name}")

            except Exception as e:
                logger.warning(f"Could not load {model_file}: {e}")

        return models

    def _load_clip_models(self) -> Dict[str, Any]:
        """Load CLIP models."""
        models = {}
        pubmed_dir = self.results_dir / "pubmed"

        if not pubmed_dir.exists():
            return models

        # Look for PyTorch model files
        for model_file in pubmed_dir.glob("model-clip_*_best.pth"):
            try:
                # Extract model info from filename
                parts = model_file.stem.split('_')
                section = parts[1].split('-')[1] if len(parts) > 1 else "unknown"
                embedding = parts[2].split('-')[1] if len(parts) > 2 else "unknown"

                model_info = {
                    "path": str(model_file),
                    "type": "clip",
                    "section": section,
                    "embedding": embedding
                }

                # Check for indices file
                indices_file = model_file.parent / f"{model_file.stem}-indices.npz"
                if indices_file.exists():
                    indices = np.load(indices_file)
                    model_info["indices"] = indices

                # Check for metrics
                metrics_file = model_file.parent / model_file.name.replace("_best.pth", "_metrics.csv")
                if metrics_file.exists():
                    metrics = pd.read_csv(metrics_file)
                    model_info["metrics"] = metrics

                models[model_file.stem] = model_info
                logger.info(f"Found CLIP model: {model_file.name}")

            except Exception as e:
                logger.warning(f"Could not process {model_file}: {e}")

        return models

    def get_cognitive_atlas_mappings(self) -> Dict[str, Any]:
        """
        Load Cognitive Atlas mappings from NICLIP.

        Returns:
            Dictionary with concept-task-process mappings
        """
        mappings = {}
        ca_dir = self.data_dir / "cognitive_atlas"

        if not ca_dir.exists():
            logger.warning(f"Cognitive Atlas directory not found: {ca_dir}")
            return mappings

        # Load concept to task mapping
        concept_task_file = ca_dir / "concept_to_task.json"
        if concept_task_file.exists():
            try:
                with open(concept_task_file) as f:
                    mappings["concept_to_task"] = json.load(f)
                logger.info(f"Loaded {len(mappings['concept_to_task'])} concept-task mappings")
            except Exception as e:
                logger.warning(f"Could not load concept-task mappings: {e}")

        # Load concept to process mapping
        concept_process_file = ca_dir / "concept_to_process.json"
        if concept_process_file.exists():
            try:
                with open(concept_process_file) as f:
                    mappings["concept_to_process"] = json.load(f)
                logger.info(f"Loaded {len(mappings['concept_to_process'])} concept-process mappings")
            except Exception as e:
                logger.warning(f"Could not load concept-process mappings: {e}")

        # Load reduced tasks
        reduced_tasks_file = ca_dir / "reduced_tasks.csv"
        if reduced_tasks_file.exists():
            try:
                mappings["reduced_tasks"] = pd.read_csv(reduced_tasks_file)
                logger.info(f"Loaded {len(mappings['reduced_tasks'])} reduced task mappings")
            except Exception as e:
                logger.warning(f"Could not load reduced tasks: {e}")

        return mappings

    def compute_similarity(
        self,
        query_embedding: np.ndarray,
        target_embeddings: np.ndarray,
        method: str = "cosine"
    ) -> np.ndarray:
        """
        Compute similarity between query and target embeddings.

        Args:
            query_embedding: Query embedding vector
            target_embeddings: Target embedding matrix
            method: Similarity method (cosine, euclidean, dot)

        Returns:
            Similarity scores
        """
        if method == "cosine":
            # Normalize embeddings
            query_norm = query_embedding / np.linalg.norm(query_embedding)
            target_norms = target_embeddings / np.linalg.norm(target_embeddings, axis=1, keepdims=True)
            # Compute cosine similarity
            similarities = np.dot(target_norms, query_norm)

        elif method == "euclidean":
            # Compute euclidean distance (convert to similarity)
            distances = np.linalg.norm(target_embeddings - query_embedding, axis=1)
            similarities = 1 / (1 + distances)

        elif method == "dot":
            # Simple dot product
            similarities = np.dot(target_embeddings, query_embedding)

        else:
            raise ValueError(f"Unknown similarity method: {method}")

        return similarities

    def find_similar_items(
        self,
        query_embedding: np.ndarray,
        target_embeddings: np.ndarray,
        vocabulary: List[str],
        top_k: int = 10,
        method: str = "cosine"
    ) -> List[Tuple[str, float]]:
        """
        Find most similar items to a query embedding.

        Args:
            query_embedding: Query embedding vector
            target_embeddings: Target embedding matrix
            vocabulary: List of item names
            top_k: Number of top items to return
            method: Similarity method

        Returns:
            List of (item_name, similarity_score) tuples
        """
        # Compute similarities
        similarities = self.compute_similarity(query_embedding, target_embeddings, method)

        # Get top-k indices
        top_indices = np.argsort(similarities)[-top_k:][::-1]

        # Return items with scores
        results = []
        for idx in top_indices:
            if idx < len(vocabulary):
                results.append((vocabulary[idx], float(similarities[idx])))

        return results

    def get_statistics(self) -> Dict[str, Any]:
        """Get loader statistics."""
        stats = self.stats.copy()

        # Add available data info
        stats["available_models"] = self.AVAILABLE_MODELS
        stats["data_directory"] = str(self.root)
        stats["cache_size"] = len(self._cache)

        return stats

    def clear_cache(self):
        """Clear the cache to free memory."""
        self._cache.clear()
        logger.info("Cleared NICLIP cache")


# Convenience functions
def load_niclip_embeddings(
    model: str = "BrainGPT-7B-v0.2",
    section: str = "abstract"
) -> Optional[np.ndarray]:
    """
    Quick function to load NICLIP text embeddings.

    Args:
        model: Model name
        section: Text section

    Returns:
        Embeddings array or None
    """
    loader = NICLIPEmbeddingLoader()
    batch = loader.get_text_embeddings(model=model, section=section)
    return batch.embeddings if batch else None


def load_niclip_models(dataset: str = "neurosynth") -> Dict[str, Any]:
    """
    Quick function to load NICLIP trained models.

    Args:
        dataset: Dataset name

    Returns:
        Dictionary of models
    """
    loader = NICLIPEmbeddingLoader()
    models = {}
    models.update(loader.get_trained_models(dataset, "gclda"))
    models.update(loader.get_trained_models(dataset, "baseline"))
    models.update(loader.get_trained_models("pubmed", "clip"))
    return models


if __name__ == "__main__":
    # Example usage
    loader = NICLIPEmbeddingLoader()

    # Load text embeddings
    text_embeddings = loader.get_text_embeddings(
        model="BrainGPT-7B-v0.2",
        section="abstract"
    )
    if text_embeddings is not None:
        print(f"Text embeddings shape: {text_embeddings.embeddings.shape}")

    # Load coordinate embeddings
    coord_embeddings = loader.get_coordinate_embeddings(
        method="MKDA",
        normalization="standardized"
    )
    if coord_embeddings is not None:
        print(f"Coordinate embeddings shape: {coord_embeddings.embeddings.shape}")

    # Load vocabulary
    vocabulary = loader.get_vocabulary_list("cogatlas")
    print(f"Vocabulary size: {len(vocabulary)}")

    # Load Cognitive Atlas mappings
    mappings = loader.get_cognitive_atlas_mappings()
    print(f"Mappings loaded: {list(mappings.keys())}")

    # Load trained models
    models = loader.get_trained_models("neurosynth", "gclda")
    print(f"GCLDA models: {len(models)}")

    # Print statistics
    print(f"\nStatistics: {loader.get_statistics()}")
