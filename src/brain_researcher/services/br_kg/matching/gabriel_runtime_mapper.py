"""Runtime ONVOC mapper backed by Gabriel lexical/embedding matching.

This module adapts the Gabriel ONVOC mapper for low-latency, on-demand calls
used by runtime tools (for example task mapping and related-concept reranking).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import yaml

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.services.br_kg.etl.evaluation import gabriel_onvoc_map as _gom

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUE_VALUES


def _env_float(name: str, default: float, *, lower: float, upper: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(lower, min(upper, value))


def _env_int(name: str, default: int, *, lower: int, upper: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(lower, min(upper, value))


def _clamp_unit(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    text = text.strip("-")
    return text or "runtime"


@dataclass(frozen=True)
class RuntimeMappingResult:
    """Serializable view of one runtime mapping decision."""

    query_text: str
    status: str
    reason: str
    backend_used: str
    onvoc_id: str | None = None
    onvoc_label: str | None = None
    onvoc_uri: str | None = None
    score: float | None = None
    method: str | None = None
    candidate_count_lexical: int = 0
    top_candidates: list[dict[str, Any]] | None = None
    top1_score: float | None = None
    top2_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query_text": self.query_text,
            "status": self.status,
            "reason": self.reason,
            "backend_used": self.backend_used,
            "candidate_count_lexical": self.candidate_count_lexical,
        }
        if self.onvoc_id:
            payload["onvoc_id"] = self.onvoc_id
        if self.onvoc_label:
            payload["onvoc_label"] = self.onvoc_label
        if self.onvoc_uri:
            payload["onvoc_uri"] = self.onvoc_uri
        if self.score is not None:
            payload["score"] = self.score
        if self.method:
            payload["method"] = self.method
        if self.top_candidates:
            payload["top_candidates"] = self.top_candidates
        if self.top1_score is not None:
            payload["top1_score"] = self.top1_score
        if self.top2_score is not None:
            payload["top2_score"] = self.top2_score
        return payload


class GabrielRuntimeMapper:
    """Small runtime wrapper around Gabriel's ONVOC mapper internals."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        embedding_enabled: bool = False,
        embedding_backend: str = "gemini",
        embedding_model: str = "gemini-embedding-001",
        embedding_batch_size: int = 32,
        embedding_timeout_sec: float = 8.0,
        candidate_top_k: int = 40,
        margin_min: float = 0.04,
        crosswalk_path: str | None = None,
        tree_path: str | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.embedding_enabled = bool(embedding_enabled)
        self.embedding_backend = str(embedding_backend or "gemini").strip().lower()
        self.embedding_model = str(embedding_model or "gemini-embedding-001").strip()
        self.embedding_batch_size = max(1, int(embedding_batch_size))
        self.embedding_timeout_sec = max(1.0, float(embedding_timeout_sec))
        self.candidate_top_k = max(1, int(candidate_top_k))
        self.margin_min = max(0.0, min(1.0, float(margin_min)))
        self.crosswalk_path = crosswalk_path
        self.tree_path = tree_path

        self.available = False
        self.init_error: str | None = None
        self.backend_active = "none"
        self._mapper: Any = None

        self._initialize()

    @classmethod
    def from_env(cls) -> GabrielRuntimeMapper:
        """Construct mapper from environment defaults."""
        return cls(
            enabled=_env_flag("BR_KG_GABRIEL_RUNTIME_ENABLED", True),
            embedding_enabled=_env_flag("BR_KG_GABRIEL_RUNTIME_EMBEDDING_ENABLED", False),
            embedding_backend=os.environ.get("BR_KG_GABRIEL_RUNTIME_EMBEDDING_BACKEND", "gemini"),
            embedding_model=os.environ.get(
                "BR_KG_GABRIEL_RUNTIME_EMBEDDING_MODEL", "gemini-embedding-001"
            ),
            embedding_batch_size=_env_int(
                "BR_KG_GABRIEL_RUNTIME_EMBEDDING_BATCH_SIZE",
                32,
                lower=1,
                upper=256,
            ),
            embedding_timeout_sec=_env_float(
                "BR_KG_GABRIEL_RUNTIME_EMBEDDING_TIMEOUT_SEC",
                8.0,
                lower=1.0,
                upper=120.0,
            ),
            candidate_top_k=_env_int(
                "BR_KG_GABRIEL_RUNTIME_CANDIDATE_TOP_K",
                40,
                lower=1,
                upper=200,
            ),
            margin_min=_env_float(
                "BR_KG_GABRIEL_RUNTIME_MARGIN_MIN",
                0.04,
                lower=0.0,
                upper=1.0,
            ),
            crosswalk_path=os.environ.get("BR_KG_GABRIEL_RUNTIME_CROSSWALK_PATH"),
            tree_path=os.environ.get("BR_KG_GABRIEL_RUNTIME_TREE_PATH"),
        )

    def _initialize(self) -> None:
        if not self.enabled:
            self.init_error = "runtime_mapper_disabled"
            return

        try:
            resolved_crosswalk = resolve_mapping_path(
                "onvoc_crosswalk",
                requested_path=self.crosswalk_path,
                fallback=_gom.DEFAULT_CROSSWALK_PATH,
                must_exist=True,
            )
            resolved_tree = resolve_mapping_path(
                "onvoc_tree",
                requested_path=self.tree_path,
                fallback=_gom.DEFAULT_TREE_PATH,
                must_exist=True,
            )
            crosswalk_payload = yaml.safe_load(resolved_crosswalk.read_text(encoding="utf-8")) or {}
            tree_payload = yaml.safe_load(resolved_tree.read_text(encoding="utf-8")) or {}

            provider = None
            if self.embedding_enabled:
                if self.embedding_backend == "gemini":
                    provider = _gom._GeminiEmbeddingProvider(
                        model=self.embedding_model,
                        batch_size=self.embedding_batch_size,
                        timeout_sec=self.embedding_timeout_sec,
                    )
                    if provider.available:
                        self.backend_active = provider.backend_name
                    else:
                        self.backend_active = "none"
                        logger.warning(
                            "Gabriel runtime embedding unavailable: %s", provider.error
                        )
                        provider = None
                else:
                    logger.warning(
                        "Gabriel runtime embedding backend unsupported: %s",
                        self.embedding_backend,
                    )

            self._mapper = _gom._OnvocMapper(
                crosswalk_payload=crosswalk_payload,
                tree_payload=tree_payload,
                provider=provider,
            )
            self.available = True
            if provider is None:
                self.backend_active = "none"
        except Exception as exc:
            self.init_error = str(exc)
            self.available = False
            self._mapper = None
            logger.warning("Gabriel runtime mapper init failed: %s", exc)

    def map_text(
        self,
        text: str,
        *,
        source_id: str | None = None,
        canonical_id: str | None = None,
        paper_id: str = "runtime",
    ) -> RuntimeMappingResult:
        """Map free text to ONVOC using Gabriel lexical/embedding logic."""
        query_text = str(text or "").strip()
        if not query_text:
            return RuntimeMappingResult(
                query_text=query_text,
                status="unmatched",
                reason="missing_source_label",
                backend_used="none",
            )
        if not self.available or self._mapper is None:
            return RuntimeMappingResult(
                query_text=query_text,
                status="unavailable",
                reason=self.init_error or "runtime_mapper_unavailable",
                backend_used="none",
            )

        normalized_id = f"concept:{_slug(query_text)}"
        source = _gom.ConceptSource(
            source_id=(source_id or normalized_id),
            source_label=query_text,
            canonical_id=(canonical_id or source_id or normalized_id),
            paper_id=paper_id,
        )
        details = self._mapper.match_with_details(
            source,
            candidate_top_k=self.candidate_top_k,
            margin_min=self.margin_min,
        )
        match = details.match
        return RuntimeMappingResult(
            query_text=query_text,
            status=details.status,
            reason=details.reason,
            backend_used=details.backend_used,
            onvoc_id=(match.onvoc_id if match else None),
            onvoc_label=(match.onvoc_label if match else None),
            onvoc_uri=(match.onvoc_uri if match else None),
            score=(match.score if match else None),
            method=(match.method if match else None),
            candidate_count_lexical=details.candidate_count_lexical,
            top_candidates=list(details.top_candidates or []),
            top1_score=details.top1_score,
            top2_score=details.top2_score,
        )

    def rerank_related_concepts(
        self,
        *,
        query_concept: str,
        related_concepts: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Rerank neighbor concepts with Gabriel mapping confidence."""
        if not self.available:
            return (
                list(related_concepts or []),
                {
                    "enabled": bool(self.enabled),
                    "available": False,
                    "init_error": self.init_error,
                },
            )

        query_mapping = self.map_text(query_concept, source_id=f"concept:{_slug(query_concept)}")
        query_onvoc_id = query_mapping.onvoc_id
        reranked: list[dict[str, Any]] = []
        mapped_count = 0

        for row in related_concepts or []:
            candidate = dict(row or {})
            concept_label = str(candidate.get("concept") or "").strip()
            mapping = self.map_text(concept_label, source_id=f"concept:{_slug(concept_label)}")
            if mapping.status == "mapped":
                mapped_count += 1

            graph_strength = _clamp_unit(candidate.get("strength"), default=0.0)
            mapped_strength = _clamp_unit(mapping.score, default=0.0)
            same_target_bonus = (
                1.0
                if query_onvoc_id and mapping.onvoc_id and query_onvoc_id == mapping.onvoc_id
                else 0.0
            )
            gabriel_score = (
                0.70 * graph_strength
                + 0.20 * mapped_strength
                + 0.10 * same_target_bonus
            )

            candidate["gabriel_score"] = round(gabriel_score, 6)
            candidate["gabriel_status"] = mapping.status
            candidate["gabriel_reason"] = mapping.reason
            if mapping.onvoc_id:
                candidate["gabriel_onvoc_id"] = mapping.onvoc_id
            if mapping.onvoc_label:
                candidate["gabriel_onvoc_label"] = mapping.onvoc_label
            if mapping.method:
                candidate["gabriel_method"] = mapping.method
            reranked.append(candidate)

        reranked.sort(
            key=lambda item: (
                -_clamp_unit(item.get("gabriel_score"), default=0.0),
                -_clamp_unit(item.get("strength"), default=0.0),
                str(item.get("concept") or ""),
            )
        )
        return (
            reranked,
            {
                "enabled": bool(self.enabled),
                "available": True,
                "backend_active": self.backend_active,
                "mapped_concepts": mapped_count,
                "query_mapping": query_mapping.as_dict(),
            },
        )


__all__ = ["GabrielRuntimeMapper", "RuntimeMappingResult"]
