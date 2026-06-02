"""NiCLIP engine: unified entrypoint for embeddings, search, and status."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class NiclipEngineConfig:
    """Configuration for the NiclipEngine."""

    data_path: Optional[str] = None
    model_dir: Optional[str] = None
    model_path: Optional[str] = None
    faiss_index_path: Optional[str] = None
    model_name: str = "BrainGPT-7B-v0.2"
    section: str = "abstract"
    device: Optional[str] = None
    vocabulary_type: str = "cogatlas_task-names"
    index_type: str = "flat"
    normalize: bool = True
    use_gpu: Optional[bool] = None

    DEFAULT_DATA_PATH: str = field(
        default="/data/ECoG-foundation-model/mnndl_temp/niclip",
        repr=False,
    )

    @classmethod
    def from_env(cls) -> "NiclipEngineConfig":
        data_path = os.environ.get("NICLIP_EMBEDDINGS_PATH") or os.environ.get(
            "NICLIP_DATA_PATH"
        )
        device = os.environ.get("NICLIP_DEVICE") or os.environ.get("DEVICE")
        use_gpu_env = os.environ.get("NICLIP_USE_GPU")
        use_gpu = None
        if use_gpu_env is not None:
            use_gpu = use_gpu_env.strip().lower() in {"1", "true", "yes", "on"}
        return cls(
            data_path=data_path,
            model_dir=os.environ.get("NICLIP_MODEL_DIR"),
            model_path=os.environ.get("NICLIP_MODEL_PATH"),
            faiss_index_path=os.environ.get("NICLIP_FAISS_INDEX_PATH"),
            model_name=os.environ.get("NICLIP_MODEL_NAME", "BrainGPT-7B-v0.2"),
            section=os.environ.get("NICLIP_TEXT_SECTION", "abstract"),
            device=device,
            use_gpu=use_gpu,
        )

    def resolved_data_path(self) -> str:
        return self.data_path or self.DEFAULT_DATA_PATH

    def resolved_data_root(self) -> Path:
        base = Path(self.resolved_data_path())
        if (base / "vocabulary").exists():
            return base
        return base / "osf_data/dsj56/osfstorage/osfstorage/data"

    def resolve_model_path(self) -> Optional[str]:
        if self.model_path:
            return self.model_path
        if self.model_dir:
            model_dir = Path(self.model_dir)
            if model_dir.is_file():
                return str(model_dir)
            candidate = (
                model_dir
                / f"model-clip_section-{self.section}_embedding-{self.model_name}_best.pth"
            )
            if candidate.exists():
                return str(candidate)
        return None


class NiclipEngine:
    """Unified NiCLIP engine for embeddings, search, and status."""

    _instance: Optional["NiclipEngine"] = None
    _lock = threading.Lock()

    def __init__(self, config: NiclipEngineConfig):
        self.config = config
        self._embedding_service = None
        self._embedding_error: Optional[Exception] = None
        self._text_encoder = None
        self._text_encoder_error: Optional[Exception] = None
        self._model = None
        self._model_error: Optional[Exception] = None
        self._vocab_cache: dict[tuple[str, str], tuple[list[str], Any, np.ndarray]] = {}
        self._init_lock = threading.Lock()

    @classmethod
    def get(
        cls,
        config: Optional[NiclipEngineConfig] = None,
        *,
        force_reload: bool = False,
    ) -> "NiclipEngine":
        with cls._lock:
            if cls._instance is None or force_reload:
                cfg = config or NiclipEngineConfig.from_env()
                cls._instance = cls(cfg)
            return cls._instance

    def _ensure_embedding_service(self):
        if self._embedding_service is not None or self._embedding_error is not None:
            return self._embedding_service
        with self._init_lock:
            if self._embedding_service is not None or self._embedding_error is not None:
                return self._embedding_service
            try:
                from brain_researcher.services.br_kg.niclip import (
                    EmbeddingConfig,
                    NICLIPEmbeddingService,
                )

                use_gpu = (
                    self.config.use_gpu
                    if self.config.use_gpu is not None
                    else bool(self.config.device and "cuda" in self.config.device)
                )
                cfg = EmbeddingConfig(
                    model_name=self.config.model_name,
                    section=self.config.section,
                    normalize=self.config.normalize,
                    use_gpu=bool(use_gpu),
                )
                self._embedding_service = NICLIPEmbeddingService(
                    self.config.resolved_data_path(), cfg
                )
            except Exception as exc:  # pragma: no cover - env dependent
                self._embedding_error = exc
                logger.warning("Failed to initialize NiCLIP embedding service: %s", exc)
        return self._embedding_service

    def _ensure_text_encoder(self):
        if self._text_encoder is not None or self._text_encoder_error is not None:
            return self._text_encoder
        with self._init_lock:
            if self._text_encoder is not None or self._text_encoder_error is not None:
                return self._text_encoder
            try:
                from brain_researcher.services.br_kg.utils.niclip_encoder import (
                    NiCLIPTextEncoder,
                )

                self._text_encoder = NiCLIPTextEncoder(
                    niclip_data_path=str(self.config.resolved_data_root())
                )
            except Exception as exc:  # pragma: no cover - env dependent
                self._text_encoder_error = exc
                logger.warning("Failed to initialize NiCLIP text encoder: %s", exc)
        return self._text_encoder

    def _ensure_model(self):
        if self._model is not None or self._model_error is not None:
            return self._model
        with self._init_lock:
            if self._model is not None or self._model_error is not None:
                return self._model
            try:
                from brain_researcher.services.br_kg.models.fmri_text_alignment import (
                    FmriTextAlignmentModel,
                )

                self._model = FmriTextAlignmentModel(
                    model_path=self.config.resolve_model_path(),
                    niclip_data_path=self.config.resolved_data_path(),
                    model_name=self.config.model_name,
                    section=self.config.section,
                    device=self.config.device,
                )
            except Exception as exc:  # pragma: no cover - env dependent
                self._model_error = exc
                logger.warning("Failed to initialize NiCLIP model: %s", exc)
        return self._model

    def get_embedding_service(self):
        return self._ensure_embedding_service()

    def get_text_encoder(self):
        return self._ensure_text_encoder()

    def get_model(self):
        return self._ensure_model()

    def get_vocabulary_index(
        self,
        vocabulary_type: Optional[str] = None,
        index_type: Optional[str] = None,
    ):
        vocab_type = vocabulary_type or self.config.vocabulary_type
        idx_type = index_type or self.config.index_type
        cache_key = (vocab_type, idx_type)
        if cache_key in self._vocab_cache:
            return self._vocab_cache[cache_key]

        service = self._ensure_embedding_service()
        if service is None:
            raise RuntimeError("NiCLIP embedding service not available")

        vocab, index, priors = service.get_vocabulary_index(vocab_type, idx_type)
        self._vocab_cache[cache_key] = (vocab, index, priors)
        return vocab, index, priors

    def encode_text(self, texts: str | Sequence[str]) -> np.ndarray:
        encoder = self._ensure_text_encoder()
        if encoder is not None:
            return encoder.encode(texts)

        model = self._ensure_model()
        if model is not None:
            return model.encode_text(texts)

        raise RuntimeError("NiCLIP text encoder not available")

    def encode_fmri(self, fmri_data) -> np.ndarray:
        model = self._ensure_model()
        if model is None:
            raise RuntimeError("NiCLIP model not available")
        return model.encode_fmri(fmri_data)

    def predict_from_nifti(
        self, nifti_path: str, top_k: int = 10, use_bayes: bool = True
    ):
        model = self._ensure_model()
        if model is None:
            raise RuntimeError("NiCLIP model not available")
        return model.predict_from_nifti(nifti_path, top_k=top_k, use_bayes=use_bayes)

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        vocabulary_type: Optional[str] = None,
        index_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        vocab, index, priors = self.get_vocabulary_index(
            vocabulary_type=vocabulary_type, index_type=index_type
        )
        service = self._ensure_embedding_service()
        if service is None:
            raise RuntimeError("NiCLIP embedding service not available")

        query_embedding = self.encode_text(query)
        distances, indices = service.search_similar(query_embedding, index, k=top_k)
        results = []
        for dist, idx in zip(distances, indices, strict=False):
            results.append(
                {
                    "item": vocab[idx],
                    "similarity": float(dist),
                    "vocabulary_index": int(idx),
                    "prior_probability": (
                        float(priors[idx]) if idx < len(priors) else None
                    ),
                }
            )
        return results

    def similarity(self, text_a: str, text_b: str) -> float:
        emb_a = self.encode_text(text_a)
        emb_b = self.encode_text(text_b)
        if emb_a.ndim > 1:
            emb_a = emb_a[0]
        if emb_b.ndim > 1:
            emb_b = emb_b[0]
        denom = (np.linalg.norm(emb_a) * np.linalg.norm(emb_b)) + 1e-8
        return float(np.dot(emb_a, emb_b) / denom)

    def similarity_brain_text(self, fmri_data, text: str) -> float:
        model = self._ensure_model()
        if model is None:
            raise RuntimeError("NiCLIP model not available")
        return model.compute_similarity(fmri_data, text)

    def status(self) -> dict[str, Any]:
        missing: list[str] = []
        data_path = Path(self.config.resolved_data_path())
        if not data_path.exists():
            missing.append("data_path")

        model_loaded = bool(
            self._model and getattr(self._model, "model", None) is not None
        )

        text_encoder_loaded = False
        try:
            text_encoder_loaded = self._ensure_text_encoder() is not None
        except Exception as exc:  # pragma: no cover - env dependent
            logger.warning("NiclipEngine status encoder error: %s", exc)

        can_encode_text = model_loaded or text_encoder_loaded
        if not can_encode_text:
            missing.append("text_encoder")
            if not model_loaded:
                missing.append("model")

        vocab_size = None
        index_size = None
        embedding_ready = False
        service = self._ensure_embedding_service()
        if service is None:
            missing.append("embedding_service")
        else:
            try:
                vocab, index, _ = self.get_vocabulary_index()
                vocab_size = len(vocab)
                index_size = int(index.ntotal)
                embedding_ready = vocab_size > 0
                if not embedding_ready:
                    missing.append("vocabulary")
            except Exception as exc:
                logger.warning("NiclipEngine status vocab error: %s", exc)
                missing.append("vocabulary")

        mode = "full" if model_loaded and embedding_ready else "embedding_only"
        if not embedding_ready and not can_encode_text:
            mode = "unavailable"

        return {
            "status": "healthy" if not missing else "degraded",
            "ready": not missing,
            "mode": mode,
            "missing": missing,
            "model_loaded": model_loaded,
            "text_encoder_loaded": text_encoder_loaded,
            "embedding_service_loaded": service is not None,
            "niclip_data_path": self.config.resolved_data_path(),
            "niclip_model_path": self.config.resolve_model_path(),
            "niclip_faiss_index_path": self.config.faiss_index_path,
            "niclip_device": self.config.device,
            "vocabulary_size": vocab_size,
            "index_size": index_size,
        }
