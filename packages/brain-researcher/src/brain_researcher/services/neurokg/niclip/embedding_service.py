"""
NICLIP Embedding Service

This module provides services for handling NICLIP embeddings including:
- Loading pre-computed embeddings
- Creating FAISS indices for fast similarity search
- Managing vocabulary embeddings
- Integrating with brain-decoder utilities

Author: BR-KG Team
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
import torch

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class EmbeddingConfig:
    """Configuration for embedding service."""

    model_name: str = "BrainGPT-7B-v0.2"
    section: str = "abstract"
    embedding_dim: int = 768
    use_gpu: bool = False
    normalize: bool = True


class NICLIPEmbeddingService:
    """Service for managing NICLIP embeddings and similarity search."""

    def __init__(self, niclip_data_path: str, config: EmbeddingConfig | None = None):
        """
        Initialize the NICLIP embedding service.

        Args:
            niclip_data_path: Path to NICLIP data directory
            config: Configuration for embeddings
        """
        self.niclip_path = Path(niclip_data_path)
        self.config = config or EmbeddingConfig()

        # Paths to data: accept multiple layouts
        if (self.niclip_path / "vocabulary").exists():
            self.data_root = self.niclip_path
        elif (self.niclip_path / "data" / "vocabulary").exists():
            # Common layout shipped in this repo: data/niclip/data/vocabulary
            self.data_root = self.niclip_path / "data"
        else:
            self.data_root = (
                self.niclip_path / "osf_data/dsj56/osfstorage/osfstorage/data"
            )

        # Caches
        self.vocabulary_cache = {}
        self.embedding_cache = {}
        self.index_cache = {}

        # Statistics
        self.stats = {
            "embeddings_loaded": 0,
            "indices_created": 0,
            "searches_performed": 0,
        }

    def load_vocabulary_embeddings(
        self, vocabulary_type: str = "cogatlas_task-names"
    ) -> tuple[list[str], np.ndarray]:
        """
        Load vocabulary and their embeddings.

        Args:
            vocabulary_type: Type of vocabulary to load
                - "cogatlas_task": Full Cognitive Atlas tasks
                - "cogatlasred_task": Reduced 88 tasks (recommended)
                - "cogatlas_task-names": Task names embeddings (no .txt file)
                - "cogatlas_task-definitions": Task definitions embeddings

        Returns:
            Tuple of (vocabulary list, embeddings array)
        """
        cache_key = f"{vocabulary_type}_{self.config.model_name}_{self.config.section}"

        if cache_key in self.vocabulary_cache:
            return self.vocabulary_cache[cache_key]

        # Handle different vocabulary naming patterns
        vocab_base = vocabulary_type
        embedding_type = vocabulary_type

        # Map vocabulary types to correct file names
        if vocabulary_type == "cogatlas_task-names":
            vocab_base = "cogatlas_task"  # Use base vocabulary file
            embedding_type = "cogatlas_task-names"  # But task-names embeddings
        elif vocabulary_type == "cogatlasred_task-names":
            vocab_base = "cogatlasred_task"  # Use reduced vocabulary file
            embedding_type = "cogatlasred_task-names"  # But task-names embeddings
        elif vocabulary_type == "cogatlas_task-definitions":
            vocab_base = "cogatlas_task"  # Use base vocabulary file
            embedding_type = "cogatlas_task-definitions"  # But definitions embeddings
        elif vocabulary_type == "cogatlasred_task-definitions":
            vocab_base = "cogatlasred_task"  # Use reduced vocabulary file
            embedding_type = (
                "cogatlasred_task-definitions"  # But definitions embeddings
            )

        # Load vocabulary file
        vocab_path = self.data_root / "vocabulary" / f"vocabulary-{vocab_base}.txt"

        if not vocab_path.exists():
            # Try alternate naming patterns
            alt_paths = [
                self.data_root / "vocabulary" / f"vocabulary-{vocabulary_type}.txt",
                self.data_root
                / "cognitive_atlas"
                / "reduced_tasks.csv",  # For task names
            ]

            vocab_path = None
            for alt_path in alt_paths:
                if alt_path.exists():
                    vocab_path = alt_path
                    break

            if vocab_path is None:
                raise FileNotFoundError(
                    f"Vocabulary file not found. Tried: vocabulary-{vocab_base}.txt and alternatives"
                )

        # Load vocabulary
        if vocab_path.suffix == ".csv":
            # Load from CSV (e.g., reduced_tasks.csv)
            df = pd.read_csv(vocab_path)
            vocabulary = (
                df["task"].tolist() if "task" in df.columns else df.iloc[:, 0].tolist()
            )
        else:
            with open(vocab_path) as f:
                vocabulary = [line.strip() for line in f if line.strip()]

        # Load embeddings
        embedding_path = (
            self.data_root
            / "vocabulary"
            / f"vocabulary-{embedding_type}_embedding-{self.config.model_name}.npy"
        )

        if not embedding_path.exists():
            # Try without model name suffix for some embeddings
            alt_embedding_path = (
                self.data_root / "vocabulary" / f"vocabulary-{embedding_type}.npy"
            )
            if alt_embedding_path.exists():
                embedding_path = alt_embedding_path
            else:
                raise FileNotFoundError(f"Embedding file not found: {embedding_path}")

        embeddings = np.load(embedding_path)

        # Ensure vocabulary and embeddings have same length
        if len(vocabulary) != embeddings.shape[0]:
            logger.warning(
                f"Vocabulary size ({len(vocabulary)}) != embedding size ({embeddings.shape[0]}). "
                f"Truncating to minimum."
            )
            min_size = min(len(vocabulary), embeddings.shape[0])
            vocabulary = vocabulary[:min_size]
            embeddings = embeddings[:min_size]

        # Normalize if requested
        if self.config.normalize:
            embeddings = embeddings / (
                np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-8
            )

        # Cache results
        self.vocabulary_cache[cache_key] = (vocabulary, embeddings)
        self.stats["embeddings_loaded"] += len(vocabulary)

        logger.info(f"Loaded {len(vocabulary)} vocabulary items with embeddings")

        return vocabulary, embeddings

    def load_text_embeddings(self, normalized: bool = True) -> np.ndarray:
        """
        Load pre-computed text embeddings from publications.

        Args:
            normalized: Whether to use normalized embeddings

        Returns:
            Array of text embeddings
        """
        prefix = "normalized" if normalized else "raw"
        filename = f"text-{prefix}_section-{self.config.section}_embedding-{self.config.model_name}.npy"

        embedding_path = self.data_root / "text" / filename

        if not embedding_path.exists():
            raise FileNotFoundError(f"Text embedding file not found: {embedding_path}")

        embeddings = np.load(embedding_path)

        if self.config.normalize and not normalized:
            embeddings = embeddings / (
                np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-8
            )

        self.stats["embeddings_loaded"] += embeddings.shape[0]
        logger.info(f"Loaded {embeddings.shape[0]} text embeddings")

        return embeddings

    def load_image_embeddings(
        self, coordinate_type: str = "standardized"
    ) -> np.ndarray:
        """
        Load pre-computed brain image embeddings.

        Args:
            coordinate_type: Type of coordinates (raw, normalized, standardized)

        Returns:
            Array of image embeddings
        """
        filename = f"image-{coordinate_type}_coord-MKDA_embedding-DiFuMo.npy"
        embedding_path = self.data_root / "image" / filename

        if not embedding_path.exists():
            raise FileNotFoundError(f"Image embedding file not found: {embedding_path}")

        embeddings = np.load(embedding_path)

        if self.config.normalize:
            embeddings = embeddings / (
                np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-8
            )

        self.stats["embeddings_loaded"] += embeddings.shape[0]
        logger.info(f"Loaded {embeddings.shape[0]} image embeddings")

        return embeddings

    def create_faiss_index(
        self, embeddings: np.ndarray, index_type: str = "flat"
    ) -> faiss.Index:
        """
        Create a FAISS index for fast similarity search.

        Args:
            embeddings: Embeddings to index
            index_type: Type of FAISS index (flat, ivf, hnsw)

        Returns:
            FAISS index
        """
        d = embeddings.shape[1]

        if index_type == "flat":
            # Exact search
            index = faiss.IndexFlatIP(d)  # Inner product for cosine similarity
        elif index_type == "ivf":
            # Approximate search with inverted file
            quantizer = faiss.IndexFlatIP(d)
            n_list = min(100, embeddings.shape[0] // 10)
            index = faiss.IndexIVFFlat(quantizer, d, n_list)
            index.train(embeddings.astype(np.float32))
        elif index_type == "hnsw":
            # Hierarchical Navigable Small World graph
            index = faiss.IndexHNSWFlat(d, 32)
        else:
            raise ValueError(f"Unknown index type: {index_type}")

        # Add embeddings to index
        index.add(embeddings.astype(np.float32))

        # Move to GPU if requested and available
        if self.config.use_gpu and faiss.get_num_gpus() > 0:
            index = faiss.index_cpu_to_gpu(faiss.StandardGpuResources(), 0, index)

        self.stats["indices_created"] += 1
        logger.info(
            f"Created FAISS {index_type} index with {embeddings.shape[0]} vectors"
        )

        return index

    def search_similar(
        self,
        query_embedding: np.ndarray | torch.Tensor,
        index: faiss.Index,
        k: int = 10,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Search for similar embeddings using FAISS.

        Args:
            query_embedding: Query embedding vector
            index: FAISS index to search
            k: Number of nearest neighbors

        Returns:
            Tuple of (distances, indices)
        """
        # Convert to numpy if tensor
        if isinstance(query_embedding, torch.Tensor):
            query_embedding = query_embedding.cpu().numpy()

        # Ensure 2D array
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)
        else:
            query_embedding = query_embedding.reshape(query_embedding.shape[0], -1)

        # Resize/truncate/pad to match index dimension
        target_dim = index.d
        if query_embedding.shape[1] != target_dim:
            logger.warning(
                "Resizing query embedding from %s to %s to match FAISS index",
                query_embedding.shape[1],
                target_dim,
            )
            resized = np.zeros((query_embedding.shape[0], target_dim), dtype=np.float32)
            for i in range(resized.shape[0]):
                src = query_embedding[i].astype(np.float32)
                if src.size >= target_dim:
                    resized[i] = src[:target_dim]
                else:
                    resized[i, : src.size] = src
            query_embedding = resized

        # Normalize query if needed
        if self.config.normalize:
            query_embedding = query_embedding / (
                np.linalg.norm(query_embedding, axis=1, keepdims=True) + 1e-8
            )

        # Search
        distances, indices = index.search(query_embedding.astype(np.float32), k)

        self.stats["searches_performed"] += 1

        return distances[0], indices[0]

    def load_prior_probabilities(
        self, vocabulary_type: str = "cogatlas_task-names"
    ) -> np.ndarray:
        """
        Load prior probabilities for vocabulary items.

        Args:
            vocabulary_type: Type of vocabulary

        Returns:
            Array of prior probabilities
        """
        prior_path = (
            self.data_root
            / "vocabulary"
            / f"vocabulary-{vocabulary_type}_embedding-{self.config.model_name}_section-{self.config.section}_prior.npy"
        )

        if prior_path.exists():
            return np.load(prior_path)

        # Try CSV format
        prior_csv_path = prior_path.with_suffix(".csv")
        if prior_csv_path.exists():
            df = pd.read_csv(prior_csv_path)
            # Assuming the last column contains probabilities
            return df.iloc[:, -1].values

        logger.warning(f"Prior probability file not found: {prior_path}")
        # Return uniform priors as fallback
        vocab, _ = self.load_vocabulary_embeddings(vocabulary_type)
        return np.ones(len(vocab)) / len(vocab)

    def get_vocabulary_index(
        self, vocabulary_type: str = "cogatlas_task-names", index_type: str = "flat"
    ) -> tuple[list[str], faiss.Index, np.ndarray]:
        """
        Get or create a FAISS index for vocabulary embeddings.

        Args:
            vocabulary_type: Type of vocabulary
            index_type: Type of FAISS index

        Returns:
            Tuple of (vocabulary, index, prior_probabilities)
        """
        cache_key = f"{vocabulary_type}_{self.config.model_name}_{self.config.section}_{index_type}"

        if cache_key in self.index_cache:
            vocab, index = self.index_cache[cache_key]
            priors = self.load_prior_probabilities(vocabulary_type)
            return vocab, index, priors

        # Load vocabulary and embeddings
        vocab, embeddings = self.load_vocabulary_embeddings(vocabulary_type)

        # Create index
        index = self.create_faiss_index(embeddings, index_type)

        # Load priors
        priors = self.load_prior_probabilities(vocabulary_type)

        # Cache
        self.index_cache[cache_key] = (vocab, index)

        return vocab, index, priors

    def compute_similarity_matrix(
        self, embeddings1: np.ndarray, embeddings2: np.ndarray | None = None
    ) -> np.ndarray:
        """
        Compute pairwise cosine similarity matrix.

        Args:
            embeddings1: First set of embeddings
            embeddings2: Second set of embeddings (if None, compute self-similarity)

        Returns:
            Similarity matrix
        """
        # Normalize embeddings
        if self.config.normalize:
            embeddings1 = embeddings1 / (
                np.linalg.norm(embeddings1, axis=1, keepdims=True) + 1e-8
            )

        if embeddings2 is None:
            # Self-similarity
            similarity = embeddings1 @ embeddings1.T
        else:
            if self.config.normalize:
                embeddings2 = embeddings2 / (
                    np.linalg.norm(embeddings2, axis=1, keepdims=True) + 1e-8
                )
            similarity = embeddings1 @ embeddings2.T

        return similarity

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self.stats.copy()


def main():
    """Example usage of NICLIPEmbeddingService."""
    import argparse

    parser = argparse.ArgumentParser(description="NICLIP Embedding Service")
    parser.add_argument(
        "--niclip-path",
        default="/data/ECoG-foundation-model/mnndl_temp/niclip",
        help="Path to NICLIP data",
    )
    parser.add_argument(
        "--query", default="working memory", help="Query term to search for"
    )

    args = parser.parse_args()

    # Initialize service
    service = NICLIPEmbeddingService(args.niclip_path)

    # Load vocabulary
    vocab, index, priors = service.get_vocabulary_index()

    # Example: Find similar tasks
    if args.query in vocab:
        idx = vocab.index(args.query)
        query_emb = index.reconstruct(idx)
        distances, indices = service.search_similar(query_emb, index, k=5)

        print(f"\nTop 5 similar tasks to '{args.query}':")
        for i, (dist, idx) in enumerate(zip(distances, indices, strict=False)):
            print(f"{i+1}. {vocab[idx]} (similarity: {dist:.3f})")
    else:
        print(f"Query '{args.query}' not found in vocabulary")


if __name__ == "__main__":
    main()
