"""
NiCLIP Encoder Module

This module provides a proper NiCLIP text encoder implementation that loads
pre-computed embeddings from the NiCLIP OSF data directory.

Author: BR-KG Team
"""

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class NiCLIPTextEncoder:
    """NiCLIP text encoder using pre-computed embeddings from OSF data."""

    def __init__(
        self,
        niclip_data_path: str = "/data/ECoG-foundation-model/mnndl_temp/niclip/osf_data/dsj56/osfstorage/osfstorage/data",
    ):
        """
        Initialize NiCLIP encoder with pre-computed embeddings.

        Args:
            niclip_data_path: Path to NiCLIP OSF data directory
        """
        self.data_path = Path(niclip_data_path)
        self.vocab_path = self.data_path / "vocabulary"
        self.cogatlas_path = self.data_path / "cognitive_atlas"

        # Load vocabulary and embeddings
        self.vocabulary = self._load_vocabulary()
        self.embeddings = self._load_embeddings()
        self.embedding_dim = (
            self.embeddings.shape[1] if self.embeddings is not None else 0
        )

        # Create lookup dictionary for fast access
        self.vocab_to_idx = {
            task.lower(): idx for idx, task in enumerate(self.vocabulary)
        }

        logger.info(
            f"Loaded NiCLIP encoder with {len(self.vocabulary)} tasks, embedding dim: {self.embedding_dim}"
        )

    def _load_vocabulary(self) -> list[str]:
        """Load task vocabulary from NiCLIP data."""
        # Try to load vocabulary from txt file first
        vocab_file = self.vocab_path / "vocabulary-cogatlas_task.txt"
        if vocab_file.exists():
            with open(vocab_file) as f:
                vocabulary = [line.strip() for line in f if line.strip()]
            return vocabulary

        # Fallback: load from reduced_tasks.csv
        reduced_tasks_file = self.cogatlas_path / "reduced_tasks.csv"
        if reduced_tasks_file.exists():
            import csv

            vocabulary = []
            with open(reduced_tasks_file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    task = row.get("task", "")
                    if task and task not in vocabulary:
                        vocabulary.append(task)
            return vocabulary

        logger.warning("No vocabulary file found in NiCLIP data")
        return []

    def _load_embeddings(self) -> np.ndarray | None:
        """Load pre-computed embeddings from NiCLIP data."""
        # Try different embedding files in order of preference
        embedding_files = [
            "vocabulary-cogatlas_task-names_embedding-BrainGPT-7B-v0.2.npy",
            "vocabulary-cogatlas_task-names_embedding-BrainGPT-7B-v0.1.npy",
            "vocabulary-cogatlas_task-combined_embedding-BrainGPT-7B-v0.2.npy",
            "vocabulary-cogatlas_task-combined_embedding-BrainGPT-7B-v0.1.npy",
        ]

        for filename in embedding_files:
            embedding_path = self.vocab_path / filename
            if embedding_path.exists():
                logger.info(f"Loading embeddings from {filename}")
                embeddings = np.load(embedding_path)

                # Ensure embeddings match vocabulary size
                if len(embeddings) == len(self.vocabulary):
                    return embeddings
                else:
                    logger.warning(
                        f"Embedding size mismatch: {len(embeddings)} vs {len(self.vocabulary)} vocabulary items"
                    )

        logger.warning("No suitable embedding file found in NiCLIP data")
        return None

    def encode(self, texts: str | list[str], batch_size: int = 32) -> np.ndarray:
        """
        Encode text(s) using pre-computed NiCLIP embeddings.

        For texts not in vocabulary, returns zero vectors.

        Args:
            texts: Single text or list of texts to encode
            batch_size: Not used, kept for API compatibility

        Returns:
            numpy array of shape (n_texts, embedding_dim)
        """
        if isinstance(texts, str):
            texts = [texts]

        if self.embeddings is None:
            # Return zero vectors if no embeddings loaded
            return np.zeros((len(texts), 768), dtype=np.float32)  # Default dim

        embeddings = []
        for text in texts:
            text_lower = text.lower().strip()

            # Try exact match first
            if text_lower in self.vocab_to_idx:
                idx = self.vocab_to_idx[text_lower]
                embeddings.append(self.embeddings[idx])
            else:
                # Try removing common suffixes
                base_text = text_lower
                for suffix in [" task", " paradigm", " test", " experiment"]:
                    if base_text.endswith(suffix):
                        base_text = base_text[: -len(suffix)].strip()
                        if base_text in self.vocab_to_idx:
                            idx = self.vocab_to_idx[base_text]
                            embeddings.append(self.embeddings[idx])
                            break
                else:
                    # Return zero vector for unknown texts
                    embeddings.append(np.zeros(self.embedding_dim, dtype=np.float32))

        return np.array(embeddings, dtype=np.float32)

    def get_vocabulary(self) -> list[str]:
        """Get the loaded vocabulary."""
        return self.vocabulary.copy()


# For backward compatibility
TextEncoder = NiCLIPTextEncoder
