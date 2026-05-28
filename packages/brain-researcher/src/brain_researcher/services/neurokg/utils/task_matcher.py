"""Task Matcher Module

Hybrid matcher cascades NiCLIP embeddings, SBERT embeddings and RapidFuzz string
matching. Engine order and default thresholds:
 1. NiCLIP (>=0.85)
 2. SBERT (>=0.86)
 3. RapidFuzz ratio (>=90, with semantic corroboration)

NiCLIP model hash: 2024-07-17-clip-vit-b32
SBERT model: sentence-transformers/all-MiniLM-L6-v2

The matcher loads Cognitive Atlas task labels from
``neurokg/data/neurokg/raw/cognitive_tasks.json`` and additional synonyms from
``data/ca_task_synonyms.tsv``. Indices are built using faiss HNSW.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any

import faiss
import numpy as np
from rapidfuzz import fuzz, process
from sentence_transformers import SentenceTransformer

from brain_researcher.config.paths import get_data_root, get_package_root, get_repo_root
from brain_researcher.services.shared.runtime_semantic import (
    get_cached_sentence_transformer,
    semantic_matching_enabled,
)

logger = logging.getLogger(__name__)

try:
    from .niclip_encoder import NiCLIPTextEncoder as NiCLIPEncoder

    _NICLIP_AVAILABLE = True
except Exception:  # pragma: no cover - library optional
    _NICLIP_AVAILABLE = False
    NiCLIPEncoder = None


class TaskMatcher:
    """Hybrid task matcher using NiCLIP → SBERT → Fuzzy."""

    _RESOURCE_CACHE: dict[str, dict[str, Any]] = {}
    _RESOURCE_LOCK = threading.Lock()

    def __init__(
        self,
        niclip_threshold: float = 0.85,
        sbert_threshold: float = 0.86,
        fuzzy_threshold: int = 90,
        fuzzy_semantic_corroboration: float = 0.80,
        enable_semantic: bool | None = None,
        prewarm: bool = False,
    ) -> None:
        self.niclip_threshold = niclip_threshold
        self.sbert_threshold = sbert_threshold
        self.fuzzy_threshold = fuzzy_threshold
        self.fuzzy_semantic_corroboration = fuzzy_semantic_corroboration
        self.enable_semantic = semantic_matching_enabled(enable_semantic, default=True)

        self.labels, self.label_lookup = self._load_vocabulary()
        self.sbert_model: SentenceTransformer | None = None
        self.sbert_embs: np.ndarray | None = None
        self.sbert_index: Any | None = None
        self.niclip_encoder: Any | None = None
        self.niclip_embs: np.ndarray | None = None
        self.niclip_index: Any | None = None

        if prewarm and self.enable_semantic:
            self._ensure_indices()

    # ------------------------------------------------------------------
    def _load_vocabulary(self) -> tuple[list[str], dict[str, str]]:
        labels = []
        lookup: dict[str, str] = {}

        # Try loading from database first (primary source)
        try:
            from ..graph.graph_database import NeuroKGGraphDB
            db = NeuroKGGraphDB()
            tasks = db.find_nodes(labels="Task")

            for nid, data in tasks:
                # Get name/label from task
                name = data.get("name") or data.get("label") or data.get("id")
                if name and isinstance(name, str):
                    labels.append(name)
                    lookup[name.lower()] = name

            db.close()

            if labels:
                logger.info(f"Loaded {len(labels)} tasks from database")
        except Exception as e:
            logger.warning(
                "Failed to load tasks from Neo4j (set NEO4J_URI/NEO4J_PASSWORD): %s",
                e,
            )

        # Fallback: Try loading from files
        if not labels:
            ca_path = get_data_root() / "neurokg" / "raw" / "cognitive_tasks.json"
            if ca_path.exists():
                try:
                    with ca_path.open() as f:
                        data = json.load(f)
                        for item in data:
                            name = item.get("name", "")
                            if name:
                                labels.append(name)
                                lookup[name.lower()] = name
                except (OSError, json.JSONDecodeError) as e:
                    logger.warning(f"Failed to load cognitive tasks: {e}")

        # Load synonyms if available
        syn_path = get_repo_root() / "ca_task_synonyms.tsv"
        if syn_path.exists():
            try:
                with syn_path.open() as f:
                    next(f, None)  # header
                    for line in f:
                        if not line.strip():
                            continue
                        parts = line.rstrip().split("\t")
                        if len(parts) >= 2:
                            label, syn = parts[:2]
                            labels.append(syn)
                            lookup[syn.lower()] = label
                            if label not in lookup:
                                lookup[label.lower()] = label
            except OSError as e:
                logger.warning(f"Failed to load task synonyms: {e}")

        # Merge canonical taxonomy definitions
        taxonomy_path = get_package_root() / "semantics" / "taxonomy" / "entities.json"
        if taxonomy_path.exists():
            try:
                taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
                for entity_id, entity in taxonomy.get("entities", {}).items():
                    if entity.get("type") != "Task":
                        continue
                    canonical = entity.get("label")
                    if canonical:
                        labels.append(canonical)
                        lookup.setdefault(canonical.lower(), canonical)
                    for alias in entity.get("alt_labels", []) or []:
                        if alias:
                            labels.append(alias)
                            lookup[alias.lower()] = canonical or alias
                    for alias_list in (entity.get("source_aliases", {}) or {}).values():
                        if not alias_list:
                            continue
                        if isinstance(alias_list, str):
                            alias_candidates = [alias_list]
                        else:
                            alias_candidates = list(alias_list)
                        for alias in alias_candidates:
                            if alias:
                                labels.append(alias)
                                lookup[alias.lower()] = canonical or alias
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to load taxonomy entities: %s", exc)

        # Unique preserve order
        seen = set()
        seen_lower = set()
        uniq = []
        for lab in labels:
            if not lab:
                continue
            norm = lab.strip()
            if not norm:
                continue
            norm_lower = norm.lower()
            if norm in seen or norm_lower in seen_lower:
                continue
            uniq.append(norm)
            seen.add(norm)
            seen_lower.add(norm_lower)

        if not uniq:
            logger.warning(
                "No vocabulary loaded - matcher will have limited functionality"
            )

        return uniq, lookup

    # ------------------------------------------------------------------
    def _cache_key(self) -> str:
        payload = "\0".join(self.labels).encode("utf-8", errors="ignore")
        return hashlib.sha256(payload).hexdigest()

    def _attach_cached_resources(self, payload: dict[str, Any]) -> None:
        self.sbert_model = payload.get("sbert_model")
        self.sbert_embs = payload.get("sbert_embs")
        self.sbert_index = payload.get("sbert_index")
        self.niclip_encoder = payload.get("niclip_encoder")
        self.niclip_embs = payload.get("niclip_embs")
        self.niclip_index = payload.get("niclip_index")

    def _build_indices(self) -> dict[str, Any]:
        # Safety check: skip if no vocabulary
        if not self.labels:
            logger.warning("No vocabulary available, skipping index building")
            return {
                "sbert_model": None,
                "sbert_embs": None,
                "sbert_index": None,
                "niclip_encoder": None,
                "niclip_embs": None,
                "niclip_index": None,
            }

        started_at = time.perf_counter()
        sbert_model = get_cached_sentence_transformer("all-MiniLM-L6-v2")
        sbert_embs = sbert_model.encode(
            self.labels, normalize_embeddings=True, convert_to_numpy=True
        ).astype("float32")

        dim_sbert = sbert_embs.shape[1]
        sbert_index = faiss.IndexHNSWFlat(dim_sbert, 32)
        sbert_index.hnsw.efConstruction = 40
        sbert_index.add(sbert_embs)

        niclip_encoder = None
        niclip_embs = None
        niclip_index = None
        if _NICLIP_AVAILABLE:  # pragma: no cover - heavy optional dependency
            niclip_encoder = NiCLIPEncoder()
            niclip_embs = niclip_encoder.encode(
                self.labels, batch_size=32
            ).astype("float32")
            dim_n = niclip_embs.shape[1]
            niclip_index = faiss.IndexHNSWFlat(dim_n, 32)
            niclip_index.hnsw.efConstruction = 40
            niclip_index.add(niclip_embs)

        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        logger.info(
            "TaskMatcher semantic indices ready labels=%d elapsed_ms=%.1f",
            len(self.labels),
            elapsed_ms,
        )
        return {
            "sbert_model": sbert_model,
            "sbert_embs": sbert_embs,
            "sbert_index": sbert_index,
            "niclip_encoder": niclip_encoder,
            "niclip_embs": niclip_embs,
            "niclip_index": niclip_index,
        }

    def _ensure_indices(self) -> None:
        if not self.enable_semantic:
            return
        if self.sbert_model is not None and self.sbert_index is not None:
            return
        cache_key = self._cache_key()
        cached = self._RESOURCE_CACHE.get(cache_key)
        if cached is not None:
            self._attach_cached_resources(cached)
            return
        with self._RESOURCE_LOCK:
            cached = self._RESOURCE_CACHE.get(cache_key)
            if cached is None:
                cached = self._build_indices()
                self._RESOURCE_CACHE[cache_key] = cached
            self._attach_cached_resources(cached)

    # ------------------------------------------------------------------
    def _encode_niclip(self, text: str) -> np.ndarray:
        if not self.niclip_encoder:
            raise RuntimeError("NiCLIP encoder unavailable")
        emb = self.niclip_encoder.encode([text])[0].astype("float32")
        return emb.reshape(1, -1)

    def _encode_sbert(self, text: str) -> np.ndarray:
        emb = self.sbert_model.encode(
            [text], normalize_embeddings=True, convert_to_numpy=True
        ).astype("float32")
        return emb.reshape(1, -1)

    # ------------------------------------------------------------------
    def match_candidates(
        self, task_string: str, top_k: int = 5
    ) -> list[dict[str, any]]:
        if not task_string or not isinstance(task_string, str):
            logger.warning(f"Invalid task_string: {task_string}")
            return []

        if not self.labels:
            logger.warning("No vocabulary loaded - cannot match candidates")
            return []

        results: list[dict[str, any]] = []
        semantic_support: dict[str, float] = {}
        query = task_string.strip()

        if not query:
            return []

        exact_label = self.label_lookup.get(query.lower())
        if exact_label:
            return [{"label": exact_label, "score": 1.0, "engine": "exact"}]

        if self.enable_semantic:
            self._ensure_indices()

        # Try NiCLIP first if available
        if self.enable_semantic and self.niclip_encoder and self.niclip_index is not None:
            try:
                q = self._encode_niclip(query)
                D, I = self.niclip_index.search(q, min(top_k, len(self.labels)))
                for score, idx in zip(D[0], I[0], strict=False):
                    if 0 <= idx < len(self.labels):
                        label = self.labels[idx]
                        score_float = float(score)
                        results.append(
                            {"label": label, "score": score_float, "engine": "niclip"}
                        )
                        semantic_support[label] = max(
                            semantic_support.get(label, 0.0), score_float
                        )
                if results and results[0]["score"] >= self.niclip_threshold:
                    return results
            except Exception as e:
                logger.error(f"NiCLIP search failed: {e}")

        # Try SBERT
        try:
            if not self.enable_semantic or self.sbert_model is None or self.sbert_index is None:
                raise RuntimeError("semantic_disabled")
            q = self._encode_sbert(query)
            D, I = self.sbert_index.search(q, min(top_k, len(self.labels)))
            sbert_hits = []
            for score, idx in zip(D[0], I[0], strict=False):
                if 0 <= idx < len(self.labels):
                    label = self.labels[idx]
                    score_float = float(score)
                    sbert_hits.append(
                        {"label": label, "score": score_float, "engine": "sbert"}
                    )
                    semantic_support[label] = max(
                        semantic_support.get(label, 0.0), score_float
                    )
            results.extend(sbert_hits)
            if sbert_hits and sbert_hits[0]["score"] >= self.sbert_threshold:
                return results
        except Exception as e:
            if self.enable_semantic:
                logger.error(f"SBERT search failed: {e}")

        # Fallback to fuzzy matching
        fuzzy_best_label = ""
        fuzzy_best_score = 0.0
        try:
            fuzzy_hits = process.extract(
                query,
                self.labels,
                scorer=fuzz.ratio,
                limit=min(top_k, len(self.labels)),
            )
            for label, score, _ in fuzzy_hits:
                score_norm = score / 100.0
                fuzzy_best_label = fuzzy_best_label or label
                fuzzy_best_score = max(fuzzy_best_score, score_norm)
                semantic_score = semantic_support.get(label, 0.0)
                if score < self.fuzzy_threshold:
                    continue
                if self.enable_semantic:
                    if semantic_score < self.fuzzy_semantic_corroboration:
                        logger.debug(
                            "Rejected fuzzy-only task match: query='%s', label='%s', "
                            "fuzzy=%.2f, semantic=%.2f",
                            query,
                            label,
                            score_norm,
                            semantic_score,
                        )
                        continue
                    results.append(
                        {
                            "label": label,
                            "score": score_norm,
                            "engine": "fuzzy",
                            "semantic_corroboration": semantic_score,
                        }
                    )
                    return results
                results.append(
                    {
                        "label": label,
                        "score": score_norm,
                        "engine": "fuzzy",
                    }
                )
            if results and not self.enable_semantic:
                return results
        except Exception as e:
            logger.error(f"Fuzzy search failed: {e}")

        if results:
            best_label = results[0]["label"]
            best_score = results[0]["score"]
            engine = results[0]["engine"]
        elif fuzzy_best_label:
            best_label = fuzzy_best_label
            best_score = fuzzy_best_score
            engine = "fuzzy"
        else:
            best_label = ""
            best_score = 0.0
            engine = "none"
        self._log_miss(query, best_label, best_score, engine)
        return results

    # ------------------------------------------------------------------
    def _log_miss(
        self, query: str, best_label: str, best_score: float, engine: str
    ) -> None:
        log_path = get_repo_root() / "logs" / "match_fails.tsv"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(f"{query}\t{best_label}\t{best_score:.3f}\t{engine}\n")


# ----------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover - manual test
    import argparse

    parser = argparse.ArgumentParser(description="Self test TaskMatcher")
    parser.add_argument("--self-test", action="store_true", help="run demo search")
    args = parser.parse_args()
    if args.self_test:
        matcher = TaskMatcher()
        demo = ["nback", "bart", "unknown task"]
        for q in demo:
            hits = matcher.match_candidates(q, top_k=3)
            print(q, "->", hits)
