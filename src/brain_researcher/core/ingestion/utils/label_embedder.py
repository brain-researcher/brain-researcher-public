"""
Hybrid label embedding utilities for cross-source linking.

Provides a small adapter that prefers NICLIP vocabulary embeddings when they
are available locally, and otherwise falls back to a sentence-transformer
model. This keeps embedding-based similarity in a single vector space while
allowing purely fuzzy matching when both options are unavailable.
"""

from __future__ import annotations

import logging
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

try:
    from sentence_transformers import SentenceTransformer  # type: ignore

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except Exception:  # pragma: no cover - import errors handled at runtime
    SentenceTransformer = None  # type: ignore
    SENTENCE_TRANSFORMERS_AVAILABLE = False

try:
    from brain_researcher.core.ingestion.loaders.niclip_embeddings import (
        NICLIPEmbeddingLoader,
    )

    NICLIP_DATA_AVAILABLE = True
except Exception:  # pragma: no cover
    NICLIPEmbeddingLoader = None  # type: ignore
    NICLIP_DATA_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingBatch:
    """Container returned from the hybrid embedder."""

    emb_a: np.ndarray
    mask_a: list[bool]
    emb_b: np.ndarray
    mask_b: list[bool]
    model_label: str


class HybridLabelEmbedder:
    """
    Produce label embeddings with a preference for NICLIP data.

    The embedder attempts the following strategies (in order):

    1. If NICLIP vocabulary embeddings are installed locally and cover at least
       ``min_niclip_coverage`` of both label sets, return normalized vectors in
       the NICLIP space (4096 dims for BrainGPT).
    2. Fall back to a sentence-transformer model (default MiniLM) if available.
    3. Return ``None`` to signal that only fuzzy matching should be used.
    """

    def __init__(
        self,
        niclip_model: str = "BrainGPT-7B-v0.2",
        min_niclip_coverage: float = 0.5,
        fallback_model: str = "all-MiniLM-L6-v2",
        niclip_root: str | None = None,
    ) -> None:
        self.niclip_model = niclip_model
        self.min_niclip_coverage = min_niclip_coverage
        self.fallback_model_name = fallback_model
        self.niclip_root = Path(niclip_root) if niclip_root else None

        self._niclip_lookup: dict[str, np.ndarray] = {}
        self._niclip_dim: int | None = None
        self._niclip_loaded = False

        self._fallback_model: SentenceTransformer | None = None
        self._fallback_dim: int | None = None
        self._use_gpu = os.environ.get("NICLIP_USE_GPU", "").lower() in {
            "1",
            "true",
            "yes",
        }

        if NICLIP_DATA_AVAILABLE:
            self._load_niclip_vocab()
        else:
            logger.debug("NICLIP data loader not available; skipping NICLIP embeddings")

    @property
    def niclip_available(self) -> bool:
        return self._niclip_loaded and bool(self._niclip_lookup)

    def compute_embeddings(
        self, labels_a: Sequence[str], labels_b: Sequence[str]
    ) -> EmbeddingBatch | None:
        """
        Compute embeddings for two label sets using a consistent vector space.

        Returns an ``EmbeddingBatch`` when a vector space is available; otherwise
        returns ``None`` to signal that the caller should rely on fuzzy matching.
        """
        if not labels_a or not labels_b:
            return None

        # Attempt NICLIP vocabulary embeddings first.
        if self.niclip_available:
            emb_a, mask_a = self._encode_with_niclip(labels_a)
            emb_b, mask_b = self._encode_with_niclip(labels_b)
            coverage_a = self._coverage(mask_a)
            coverage_b = self._coverage(mask_b)

            logger.info(
                "NICLIP embedding coverage: %.2f%% (A), %.2f%% (B)",
                coverage_a * 100.0,
                coverage_b * 100.0,
            )

            if (
                coverage_a >= self.min_niclip_coverage
                and coverage_b >= self.min_niclip_coverage
            ):
                return EmbeddingBatch(
                    emb_a=emb_a,
                    mask_a=mask_a,
                    emb_b=emb_b,
                    mask_b=mask_b,
                    model_label=f"niclip:{self.niclip_model}",
                )

        # Fall back to sentence-transformer if available.
        fallback = self._load_fallback_model()
        if fallback is not None:
            emb_a = self._encode_with_sentence_transformer(labels_a, fallback)
            emb_b = self._encode_with_sentence_transformer(labels_b, fallback)
            mask_a = [True] * len(labels_a)
            mask_b = [True] * len(labels_b)
            return EmbeddingBatch(
                emb_a=emb_a,
                mask_a=mask_a,
                emb_b=emb_b,
                mask_b=mask_b,
                model_label=f"sentence-transformer:{self.fallback_model_name}",
            )

        logger.warning(
            "No embedding backend available; falling back to fuzzy matching only"
        )
        return None

    # --------------------------------------------------------------------- #
    # NICLIP helpers
    # --------------------------------------------------------------------- #

    def _load_niclip_vocab(self) -> None:
        if self._niclip_loaded:
            return

        if NICLIPEmbeddingLoader is None:
            return

        try:
            loader = (
                NICLIPEmbeddingLoader(str(self.niclip_root))
                if self.niclip_root
                else NICLIPEmbeddingLoader()
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Failed to initialize NICLIP loader: {exc}")
            return

        vocab_types = ["cogatlas", "cogatlasred"]
        total_loaded = 0

        for vocab_type in vocab_types:
            try:
                terms = loader.get_vocabulary_list(vocab_type)
                embeddings = loader.get_vocabulary_embeddings(
                    vocab_type, "combined", self.niclip_model
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Failed loading NICLIP vocabulary '%s': %s", vocab_type, exc
                )
                continue

            if not terms or embeddings is None:
                continue

            if embeddings.shape[0] != len(terms):
                logger.warning(
                    "NICLIP vocabulary mismatch for %s (terms=%d, embeddings=%d)",
                    vocab_type,
                    len(terms),
                    embeddings.shape[0],
                )
                length = min(len(terms), embeddings.shape[0])
                terms = terms[:length]
                embeddings = embeddings[:length]

            if self._niclip_dim is None:
                self._niclip_dim = embeddings.shape[1]

            for term, vec in zip(terms, embeddings, strict=False):
                normalized = self._normalize_label(term)
                if not normalized:
                    continue
                if normalized in self._niclip_lookup:
                    # Keep the first occurrence – vocabularies often overlap.
                    continue
                normalized_vec = self._normalize_vector(vec)
                self._niclip_lookup[normalized] = normalized_vec
                total_loaded += 1

        if total_loaded:
            self._niclip_loaded = True
            logger.info(
                "Loaded %d NICLIP vocabulary embeddings (dim=%d)",
                total_loaded,
                self._niclip_dim or -1,
            )
        else:
            logger.info("NICLIP vocabulary embeddings not found; skipping NICLIP mode")

    def _encode_with_niclip(
        self, labels: Sequence[str]
    ) -> tuple[np.ndarray, list[bool]]:
        assert self._niclip_dim is not None  # ensured when niclip_available is True
        embeddings = np.zeros((len(labels), self._niclip_dim), dtype=np.float32)
        mask: list[bool] = []

        for idx, label in enumerate(labels):
            vec = self._lookup_niclip_vector(label)
            if vec is not None:
                embeddings[idx] = vec
                mask.append(True)
            else:
                mask.append(False)

        return embeddings, mask

    def _lookup_niclip_vector(self, label: str) -> np.ndarray | None:
        normalized = self._normalize_label(label)
        if not normalized:
            return None

        if normalized in self._niclip_lookup:
            return self._niclip_lookup[normalized]

        # Try a basic parentheses-stripped variant (e.g., "Task (alternate)")
        if "(" in normalized and normalized.endswith(")"):
            stripped = normalized.split("(", 1)[0].strip()
            return self._niclip_lookup.get(stripped)

        return None

    # --------------------------------------------------------------------- #
    # Sentence-transformer helpers
    # --------------------------------------------------------------------- #

    def _load_fallback_model(self) -> SentenceTransformer | None:
        if self._fallback_model is not None:
            return self._fallback_model

        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.debug("sentence-transformers package not available")
            return None

        try:
            cache_dir = Path("data/models/sentence-transformers")
            cache_dir.mkdir(parents=True, exist_ok=True)
            kwargs: dict[str, str] = {"cache_folder": str(cache_dir)}
            if self._use_gpu:
                try:
                    import torch

                    if torch.cuda.is_available():
                        kwargs["device"] = "cuda"
                        logger.info(
                            "Initializing sentence-transformer '%s' on GPU",
                            self.fallback_model_name,
                        )
                    else:
                        logger.debug(
                            "NICLIP_USE_GPU set but CUDA is unavailable; using CPU for '%s'",
                            self.fallback_model_name,
                        )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(
                        "Failed to configure CUDA for sentence-transformer '%s': %s",
                        self.fallback_model_name,
                        exc,
                    )

            self._fallback_model = SentenceTransformer(
                self.fallback_model_name,
                **kwargs,
            )
            # Determine embedding dimension lazily
            self._fallback_dim = self._fallback_model.get_sentence_embedding_dimension()
            logger.info(
                "Loaded fallback sentence-transformer model '%s' (dim=%d)",
                self.fallback_model_name,
                self._fallback_dim,
            )
        except Exception as exc:
            logger.warning(
                "Failed to load sentence-transformer '%s': %s",
                self.fallback_model_name,
                exc,
            )
            self._fallback_model = None

        return self._fallback_model

    def _encode_with_sentence_transformer(
        self, labels: Sequence[str], model: SentenceTransformer
    ) -> np.ndarray:
        if not labels:
            dim = self._fallback_dim or model.get_sentence_embedding_dimension()
            return np.zeros((0, dim), dtype=np.float32)

        embeddings = model.encode(
            list(labels),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.astype(np.float32)

    # --------------------------------------------------------------------- #
    # Utility helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _normalize_vector(vec: np.ndarray) -> np.ndarray:
        vec = np.asarray(vec, dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return vec

    @staticmethod
    def _coverage(mask: list[bool]) -> float:
        if not mask:
            return 0.0
        return sum(1 for flag in mask if flag) / len(mask)

    @staticmethod
    def _normalize_label(label: str) -> str:
        if not label:
            return ""
        text = unicodedata.normalize("NFKC", label).strip().lower()
        # Collapse internal whitespace
        text = " ".join(text.split())
        return text
