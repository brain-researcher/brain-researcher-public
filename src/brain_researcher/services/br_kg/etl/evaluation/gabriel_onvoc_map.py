"""Research-only ONVOC mapping for KGGEN-adapted Gabriel records.

This module maps KGGEN concept candidates (``concept:*``) to ONVOC targets and
emits offline artifacts for downstream review or ingestion preparation.
It does not write to Neo4j.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.semantics.taxonomy.matcher import normalize_text

logger = logging.getLogger(__name__)

ONVOC_MAP_SCHEMA_VERSION = "gabriel-onvoc-map-v1"
ONVOC_MAPPER_VERSION = "gabriel-onvoc-map/v1"

DEFAULT_CROSSWALK_PATH = Path("configs/legacy/mappings/onvoc_crosswalk.yaml")
DEFAULT_TREE_PATH = Path("configs/onvoc_tree.yaml")

_DISEASE_ENTRY_PATTERN = re.compile(
    r"\b("
    r"disease|disorder|syndrome|depress|anxiety|adhd|ptsd|autism|schizophren|"
    r"bipolar|obsessive|compulsive|addiction|substance|abuse|dependence|"
    r"insomnia|obesity|diabetes|migraine|epilep|dementia|alzheimer|parkinson|"
    r"tourette|somatization|prader|willi|panic"
    r")\b",
    re.I,
)

_DISEASE_RULE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "onvoc_id": "ONVOC_0000208",
        "patterns": (r"\bbipolar depression\b",),
        "score": 0.95,
        "reason": "disease_bipolar_depression",
    },
    {
        "onvoc_id": "ONVOC_0000211",
        "patterns": (r"\bptsd\b", r"\bpost traumatic stress\b"),
        "score": 0.94,
        "reason": "disease_ptsd",
    },
    {
        "onvoc_id": "ONVOC_0000210",
        "patterns": (r"\badhd\b", r"\battention deficit hyperactivity\b"),
        "score": 0.94,
        "reason": "disease_adhd",
    },
    {
        "onvoc_id": "ONVOC_0000215",
        "patterns": (r"\bautism\b", r"\basd\b", r"\bautistic\b"),
        "score": 0.93,
        "reason": "disease_autism",
    },
    {
        "onvoc_id": "ONVOC_0000217",
        "patterns": (r"\bschizophren",),
        "score": 0.93,
        "reason": "disease_schizophrenia",
    },
    {
        "onvoc_id": "ONVOC_0000208",
        "patterns": (r"\bbipolar\b",),
        "score": 0.92,
        "reason": "disease_bipolar",
    },
    {
        "onvoc_id": "ONVOC_0000206",
        "patterns": (r"\bpanic disorder\b",),
        "score": 0.92,
        "reason": "disease_panic",
    },
    {
        "onvoc_id": "ONVOC_0000212",
        "patterns": (
            r"\bocd\b",
            r"\bobsessive compulsive\b",
            r"\bskin[- ]?picking\b",
        ),
        "score": 0.91,
        "reason": "disease_ocd",
    },
    {
        "onvoc_id": "ONVOC_0000207",
        "patterns": (
            r"\bdepress",
            r"\bmdd\b",
            r"\bmajor depressive\b",
            r"\bunipolar depression\b",
        ),
        "score": 0.92,
        "reason": "disease_depressive",
    },
    {
        "onvoc_id": "ONVOC_0000694",
        "patterns": (r"\banxiety\b",),
        "score": 0.90,
        "reason": "disease_anxiety",
    },
    {
        "onvoc_id": "ONVOC_0000213",
        "patterns": (r"\beating disorder", r"\bade\b"),
        "score": 0.90,
        "reason": "disease_eating_disorder",
    },
    {
        "onvoc_id": "ONVOC_0000017",
        "patterns": (
            r"\balcohol (abuse|addiction|dependence|use disorder)\b",
            r"\balcohol addiction\b",
        ),
        "score": 0.92,
        "reason": "disease_alcohol_abuse",
    },
    {
        "onvoc_id": "ONVOC_0000216",
        "patterns": (
            r"\bsubstance (use|abuse|dependence)\b",
            r"\bsubstance use disorder",
            r"\bcocaine use disorder\b",
            r"\bdrug use disorder\b",
            r"\baddiction\b",
            r"\bdependence\b",
        ),
        "score": 0.89,
        "reason": "disease_substance_use",
    },
    {
        "onvoc_id": "ONVOC_0000211",
        "patterns": (
            r"\bdomestic abuse\b",
            r"\bchildhood abuse\b",
        ),
        "score": 0.84,
        "reason": "disease_trauma_abuse",
    },
    {
        "onvoc_id": "ONVOC_0000178",
        "patterns": (r"\bparkinson",),
        "score": 0.93,
        "reason": "disease_parkinson",
    },
    {
        "onvoc_id": "ONVOC_0000176",
        "patterns": (r"\balzheimer",),
        "score": 0.93,
        "reason": "disease_alzheimer",
    },
    {
        "onvoc_id": "ONVOC_0000190",
        "patterns": (r"\bdementia\b", r"\bfrontotemporal dementia\b"),
        "score": 0.92,
        "reason": "disease_dementia",
    },
    {
        "onvoc_id": "ONVOC_0000174",
        "patterns": (r"\bmigraine\b",),
        "score": 0.92,
        "reason": "disease_migraine",
    },
    {
        "onvoc_id": "ONVOC_0000177",
        "patterns": (r"\bepilep",),
        "score": 0.92,
        "reason": "disease_epilepsy",
    },
    {
        "onvoc_id": "ONVOC_0000166",
        "patterns": (r"\binsomnia\b",),
        "score": 0.91,
        "reason": "disease_insomnia",
    },
    {
        "onvoc_id": "ONVOC_0000142",
        "patterns": (r"\bobesity\b",),
        "score": 0.91,
        "reason": "disease_obesity",
    },
    {
        "onvoc_id": "ONVOC_0000141",
        "patterns": (
            r"\btype 2 diabetes\b",
            r"\btype ii diabetes\b",
            r"\bt2d\b",
            r"\bdiabetes\b",
        ),
        "score": 0.90,
        "reason": "disease_diabetes_type2",
    },
    {
        "onvoc_id": "ONVOC_0000140",
        "patterns": (r"\btype 1 diabetes\b", r"\btype i diabetes\b", r"\bt1d\b"),
        "score": 0.90,
        "reason": "disease_diabetes_type1",
    },
    {
        "onvoc_id": "ONVOC_0000144",
        "patterns": (r"\bkidney disease\b", r"\brenal disease\b", r"\bend stage renal disease\b"),
        "score": 0.90,
        "reason": "disease_renal",
    },
    {
        "onvoc_id": "ONVOC_0000163",
        "patterns": (r"\bcrohn", r"\bgastrointestinal disorder\b"),
        "score": 0.88,
        "reason": "disease_gastrointestinal",
    },
    {
        "onvoc_id": "ONVOC_0000152",
        "patterns": (r"\bsmall vessel disease\b", r"\bcerebrovascular disease\b"),
        "score": 0.86,
        "reason": "disease_vascular",
    },
    {
        "onvoc_id": "ONVOC_0000153",
        "patterns": (r"\bexhaustion syndrome\b", r"\bchronic fatigue\b"),
        "score": 0.86,
        "reason": "disease_fatigue",
    },
    {
        "onvoc_id": "ONVOC_0000172",
        "patterns": (r"\bpremenstrual syndrome\b",),
        "score": 0.85,
        "reason": "disease_hormonal",
    },
    {
        "onvoc_id": "ONVOC_0000169",
        "patterns": (r"\bprader[- ]?willi\b", r"\btourette\b", r"\bchromosomal disorder\b"),
        "score": 0.86,
        "reason": "disease_chromosomal",
    },
    {
        "onvoc_id": "ONVOC_0000235",
        "patterns": (r"\bsomatization disorder\b", r"\bdissociative disorder\b"),
        "score": 0.87,
        "reason": "disease_dissociative",
    },
)


@dataclass(frozen=True)
class OnvocEntry:
    onvoc_id: str
    uri: str
    label: str
    level: int | None


@dataclass(frozen=True)
class OnvocMatch:
    onvoc_id: str
    onvoc_uri: str
    onvoc_label: str
    score: float
    method: str
    reason: str


@dataclass(frozen=True)
class ConceptSource:
    source_id: str
    source_label: str
    canonical_id: str
    paper_id: str


@dataclass(frozen=True)
class LexicalCandidate:
    onvoc_id: str
    onvoc_label: str
    lexical_score: float
    token_jaccard: float
    stem_jaccard: float
    chargram_jaccard: float
    ratio_compact: float
    ratio_text: float
    source: str


@dataclass
class MatchDetails:
    match: OnvocMatch | None
    status: str
    reason: str
    candidate_count_lexical: int = 0
    top_candidates: list[dict[str, Any]] = field(default_factory=list)
    lexical_no_candidate: bool = False
    embedding_no_candidate: bool = False
    backend_used: str = "none"
    top1_score: float | None = None
    top2_score: float | None = None


class _GeminiEmbeddingProvider:
    """Gemini embedding provider with in-memory cache and basic telemetry."""

    def __init__(
        self,
        *,
        model: str = "gemini-embedding-001",
        batch_size: int = 64,
        timeout_sec: float = 8.0,
    ) -> None:
        self.model = model
        self.batch_size = max(1, int(batch_size))
        self.timeout_sec = max(1.0, float(timeout_sec))
        self.backend_name = "gemini"
        self.available = False
        self.error: str | None = None
        self._cache: dict[str, list[float]] = {}
        self.stats = {
            "requests": 0,
            "batches": 0,
            "api_errors": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self.error = "missing_api_key"
            return

        try:
            from google import genai  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on runtime env
            self.error = f"google-genai-import-failed:{exc}"
            return

        try:
            self._client = genai.Client(api_key=api_key)
            self.available = True
        except Exception as exc:  # pragma: no cover - depends on runtime env
            self.error = f"gemini-client-init-failed:{exc}"
            self.available = False

    def has(self, text: str) -> bool:
        return text in self._cache

    def get(self, text: str) -> list[float] | None:
        return self._cache.get(text)

    def prewarm(self, texts: list[str]) -> None:
        self.embed_texts(texts)

    def embed_texts(self, texts: list[str]) -> dict[str, list[float]]:
        cleaned = [str(text).strip() for text in texts if str(text).strip()]
        if not cleaned:
            return {}

        if not self.available:
            raise RuntimeError(self.error or "embedding_backend_unavailable")

        pending = []
        seen_pending: set[str] = set()
        for text in cleaned:
            if text in self._cache or text in seen_pending:
                continue
            pending.append(text)
            seen_pending.add(text)
        self.stats["cache_hits"] += len(cleaned) - len(pending)
        self.stats["cache_misses"] += len(pending)
        if not pending:
            return {text: self._cache[text] for text in cleaned}

        for offset in range(0, len(pending), self.batch_size):
            batch = pending[offset : offset + self.batch_size]
            started = time.perf_counter()
            try:
                response = self._client.models.embed_content(  # type: ignore[attr-defined]
                    model=self.model,
                    contents=batch,
                )
            except Exception as exc:
                self.stats["api_errors"] += 1
                raise RuntimeError(f"gemini-embed-failed:{exc}") from exc
            elapsed = time.perf_counter() - started
            if elapsed > self.timeout_sec:
                logger.warning(
                    "Gemini embedding batch latency %.2fs exceeded timeout %.2fs",
                    elapsed,
                    self.timeout_sec,
                )

            vectors = _extract_embedding_vectors(response, expected=len(batch))
            if len(vectors) != len(batch):
                self.stats["api_errors"] += 1
                raise RuntimeError(
                    f"gemini-embed-count-mismatch expected={len(batch)} got={len(vectors)}"
                )
            for text, vector in zip(batch, vectors, strict=True):
                self._cache[text] = vector
            self.stats["requests"] += len(batch)
            self.stats["batches"] += 1

        return {text: self._cache[text] for text in cleaned if text in self._cache}


def _extract_embedding_vectors(response: Any, *, expected: int) -> list[list[float]]:
    embeddings = getattr(response, "embeddings", None)
    if embeddings is None:
        one = getattr(response, "embedding", None)
        if one is not None:
            embeddings = [one]
    if embeddings is None and isinstance(response, dict):
        if "embeddings" in response:
            embeddings = response["embeddings"]
        elif "embedding" in response:
            embeddings = [response["embedding"]]
    if embeddings is None:
        return []

    vectors: list[list[float]] = []
    for item in embeddings:
        values = getattr(item, "values", None)
        if values is None and isinstance(item, dict):
            values = item.get("values") or item.get("value")
        if values is None and hasattr(item, "model_dump"):
            payload = item.model_dump()
            values = payload.get("values") or payload.get("value")
        if not isinstance(values, list):
            continue
        vector = [float(v) for v in values]
        normed = _l2_normalize(vector)
        vectors.append(normed)

    if len(vectors) == 1 and expected > 1:
        return []
    return vectors

def map_kggen_to_onvoc(
    *,
    kggen_input: Path | str,
    output_dir: Path | str,
    min_score: float = 0.82,
    same_as_threshold: float = 0.97,
    normalize_targets: bool = True,
    crosswalk_path: Path | str | None = None,
    tree_path: Path | str | None = None,
    candidate_top_k: int = 40,
    embedding_enabled: bool = True,
    embedding_backend: str = "gemini",
    embedding_model: str = "gemini-embedding-001",
    embedding_batch_size: int = 64,
    embedding_timeout_sec: float = 8.0,
    margin_min: float = 0.04,
) -> dict[str, Any]:
    """Map KGGEN-adapted concept records to ONVOC and emit artifacts."""

    if not (0.0 <= min_score <= 1.0):
        raise ValueError("min_score must be in [0, 1]")
    if not (0.0 <= same_as_threshold <= 1.0):
        raise ValueError("same_as_threshold must be in [0, 1]")
    if same_as_threshold < min_score:
        raise ValueError("same_as_threshold must be >= min_score")
    if candidate_top_k <= 0:
        raise ValueError("candidate_top_k must be > 0")
    if not (0.0 <= margin_min <= 1.0):
        raise ValueError("margin_min must be in [0, 1]")

    output_dir_path = Path(output_dir).expanduser().resolve()
    output_dir_path.mkdir(parents=True, exist_ok=True)

    resolved_input = Path(kggen_input).expanduser().resolve()
    input_files = _resolve_input_files(resolved_input)
    records, parse_errors, parse_reasons = _read_json_records(input_files)

    resolved_crosswalk = resolve_mapping_path(
        "onvoc_crosswalk",
        requested_path=crosswalk_path,
        fallback=DEFAULT_CROSSWALK_PATH,
        must_exist=True,
    )
    resolved_tree = resolve_mapping_path(
        "onvoc_tree",
        requested_path=tree_path,
        fallback=DEFAULT_TREE_PATH,
        must_exist=True,
    )

    crosswalk_payload = yaml.safe_load(resolved_crosswalk.read_text(encoding="utf-8")) or {}
    tree_payload = yaml.safe_load(resolved_tree.read_text(encoding="utf-8")) or {}

    backend_name = str(embedding_backend or "gemini").strip().lower()
    provider: _GeminiEmbeddingProvider | None = None
    embedding_meta: dict[str, Any] = {
        "enabled": bool(embedding_enabled),
        "backend_requested": backend_name,
        "backend_active": "none",
        "model": embedding_model,
        "fallback_to_lexical_only": False,
        "init_error": None,
    }
    if embedding_enabled and backend_name == "gemini":
        provider = _GeminiEmbeddingProvider(
            model=embedding_model,
            batch_size=embedding_batch_size,
            timeout_sec=embedding_timeout_sec,
        )
        if provider.available:
            embedding_meta["backend_active"] = provider.backend_name
        else:
            embedding_meta["fallback_to_lexical_only"] = True
            embedding_meta["init_error"] = provider.error
            provider = None
    elif embedding_enabled and backend_name not in {"none", "off", "disabled"}:
        embedding_meta["fallback_to_lexical_only"] = True
        embedding_meta["init_error"] = f"unsupported_backend:{backend_name}"

    mapper = _OnvocMapper(
        crosswalk_payload=crosswalk_payload,
        tree_payload=tree_payload,
        provider=provider,
    )

    if provider is not None:
        source_texts = []
        for record in records:
            source = _extract_concept_source(record)
            if source is None:
                continue
            source_texts.append(_normalize_for_embedding(source.source_label))
        mapper.prewarm_embeddings(source_texts=source_texts)

    mapping_rows: list[dict[str, Any]] = []
    maps_to_edges: list[dict[str, Any]] = []
    same_as_edges: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    normalized_records: list[dict[str, Any]] = []

    status_counts: Counter[str] = Counter()
    method_counts: Counter[str] = Counter()
    candidate_count_total = 0
    records_with_candidates = 0
    no_candidate_after_lexical = 0
    no_candidate_after_embedding = 0

    params_hash = _stable_hash(
        f"{min_score:.3f}|{same_as_threshold:.3f}|{normalize_targets}|"
        f"{candidate_top_k}|{embedding_enabled}|{backend_name}|{margin_min:.3f}|"
        f"{resolved_crosswalk}|{resolved_tree}|{ONVOC_MAPPER_VERSION}"
    )

    for index, record in enumerate(records, start=1):
        source = _extract_concept_source(record)
        if source is None:
            status = "skipped_non_concept"
            status_counts[status] += 1
            mapping_rows.append(
                {
                    "record_index": index,
                    "paper_id": _paper_id(record),
                    "status": status,
                    "reason": "target_not_concept",
                }
            )
            if normalize_targets:
                normalized_records.append(record)
            continue

        details = mapper.match_with_details(
            source,
            candidate_top_k=candidate_top_k,
            margin_min=margin_min,
        )
        match = details.match
        status = details.status
        reason = details.reason
        status_counts[status] += 1
        candidate_count_total += details.candidate_count_lexical
        if details.candidate_count_lexical > 0:
            records_with_candidates += 1
        if details.lexical_no_candidate:
            no_candidate_after_lexical += 1
        if details.embedding_no_candidate:
            no_candidate_after_embedding += 1

        row: dict[str, Any] = {
            "record_index": index,
            "paper_id": source.paper_id,
            "source_id": source.source_id,
            "source_label": source.source_label,
            "canonical_id": source.canonical_id,
            "status": status,
            "reason": reason,
            "candidate_count_lexical": details.candidate_count_lexical,
            "backend_used": details.backend_used,
            "top1_score": details.top1_score,
            "top2_score": details.top2_score,
        }
        if details.top_candidates:
            row["top_candidates"] = details.top_candidates

        if match is not None:
            row.update(
                {
                    "onvoc_id": match.onvoc_id,
                    "onvoc_uri": match.onvoc_uri,
                    "onvoc_label": match.onvoc_label,
                    "score": match.score,
                    "method": match.method,
                }
            )
            method_counts[match.method] += 1

        mapping_rows.append(row)

        if match is None:
            review_rows.append(_review_row(row, reason=reason, score=None))
            if normalize_targets:
                normalized_records.append(record)
            continue

        if match.score < min_score:
            status_counts[status] -= 1
            status_counts["below_threshold"] += 1
            row["status"] = "below_threshold"
            row["reason"] = "below_threshold"
            review_rows.append(_review_row(row, reason="below_threshold", score=match.score))
            if normalize_targets:
                normalized_records.append(record)
            continue

        maps_to_edge = _build_maps_to_edge(
            source=source,
            match=match,
            params_hash=params_hash,
        )
        maps_to_edges.append(maps_to_edge)

        if _same_as_allowed(match, same_as_threshold=same_as_threshold):
            same_as_edges.append(
                _build_same_as_edge(
                    source=source,
                    match=match,
                    params_hash=params_hash,
                )
            )

        if normalize_targets:
            normalized_records.append(_normalize_record_onvoc(record, match))

    if not normalize_targets:
        normalized_records = []

    report: dict[str, Any] = {
        "schema_version": ONVOC_MAP_SCHEMA_VERSION,
        "generated_at": _utc_now_iso(),
        "configuration": {
            "kggen_input": str(resolved_input),
            "input_files": [str(path) for path in input_files],
            "crosswalk_path": str(resolved_crosswalk),
            "tree_path": str(resolved_tree),
            "min_score": min_score,
            "same_as_threshold": same_as_threshold,
            "candidate_top_k": candidate_top_k,
            "embedding_enabled": embedding_enabled,
            "embedding_backend": backend_name,
            "embedding_model": embedding_model,
            "embedding_batch_size": embedding_batch_size,
            "embedding_timeout_sec": embedding_timeout_sec,
            "margin_min": margin_min,
            "normalize_targets": normalize_targets,
            "mapper_version": ONVOC_MAPPER_VERSION,
        },
        "input": {
            "records_total": len(records),
            "parse_errors": parse_errors,
            "parse_error_reasons": dict(parse_reasons),
        },
        "summary": {
            "concept_records": sum(
                count for status, count in status_counts.items() if status != "skipped_non_concept"
            ),
            "mapped_records": int(len(maps_to_edges)),
            "maps_to_edges": int(len(maps_to_edges)),
            "same_as_edges": int(len(same_as_edges)),
            "review_items": int(len(review_rows)),
            "normalized_records": int(len(normalized_records)),
            "skipped_non_concept_records": int(status_counts.get("skipped_non_concept", 0)),
            "mapping_rate": _ratio(len(maps_to_edges), max(1, len(records) - status_counts.get("skipped_non_concept", 0))),
            "same_as_rate": _ratio(len(same_as_edges), max(1, len(maps_to_edges))),
        },
        "candidate_stats": {
            "records_with_lexical_candidates": records_with_candidates,
            "avg_candidates_per_record": _ratio(candidate_count_total, max(1, len(records))),
            "avg_candidates_when_present": _ratio(
                candidate_count_total,
                max(1, records_with_candidates),
            ),
            "no_candidate_after_lexical": no_candidate_after_lexical,
            "no_candidate_after_embedding": no_candidate_after_embedding,
        },
        "embedding": {
            **embedding_meta,
            "stats": dict(provider.stats) if provider is not None else {},
            "cache_size": len(provider._cache) if provider is not None else 0,
            "cache_hit_rate": _ratio(
                (provider.stats.get("cache_hits", 0) if provider is not None else 0),
                max(
                    1,
                    (
                        (provider.stats.get("cache_hits", 0) if provider is not None else 0)
                        + (provider.stats.get("cache_misses", 0) if provider is not None else 0)
                    ),
                ),
            ),
            "api_error_rate": _ratio(
                (provider.stats.get("api_errors", 0) if provider is not None else 0),
                max(1, provider.stats.get("batches", 0) if provider is not None else 0),
            ),
        },
        "status_counts": dict(status_counts),
        "method_counts": dict(method_counts),
        "artifacts": {},
    }

    report_path = output_dir_path / "report_onvoc.json"
    mapping_rows_path = output_dir_path / "mapping_rows.jsonl"
    review_queue_path = output_dir_path / "review_queue_onvoc.jsonl"
    maps_to_path = output_dir_path / "edges_maps_to.jsonl"
    same_as_path = output_dir_path / "edges_same_as.jsonl"

    _write_json(report_path, report)
    _write_jsonl(mapping_rows_path, mapping_rows)
    _write_jsonl(review_queue_path, review_rows)
    _write_jsonl(maps_to_path, maps_to_edges)
    _write_jsonl(same_as_path, same_as_edges)

    normalized_path: Path | None = None
    if normalize_targets:
        normalized_path = output_dir_path / "kggen_normalized_onvoc.jsonl"
        _write_jsonl(normalized_path, normalized_records)

    report["artifacts"] = {
        "report_path": str(report_path),
        "mapping_rows_path": str(mapping_rows_path),
        "review_queue_path": str(review_queue_path),
        "maps_to_edges_path": str(maps_to_path),
        "same_as_edges_path": str(same_as_path),
        "normalized_records_path": str(normalized_path) if normalized_path else None,
    }
    _write_json(report_path, report)
    return report


class _OnvocMapper:
    def __init__(
        self,
        *,
        crosswalk_payload: dict[str, Any],
        tree_payload: dict[str, Any],
        provider: _GeminiEmbeddingProvider | None = None,
    ) -> None:
        self._entries = _flatten_onvoc_tree(tree_payload)
        if not self._entries:
            raise RuntimeError("No ONVOC entries found in tree payload")

        self._entry_by_id = {entry.onvoc_id: entry for entry in self._entries}
        self._provider = provider

        self._tree_label_index: dict[str, list[OnvocEntry]] = defaultdict(list)
        self._token_index: dict[str, set[str]] = defaultdict(set)
        self._stem_index: dict[str, set[str]] = defaultdict(set)
        self._chargram_index: dict[str, set[str]] = defaultdict(set)
        self._normalized_label_by_id: dict[str, str] = {}
        self._compact_label_by_id: dict[str, str] = {}
        self._text_tokens_by_id: dict[str, set[str]] = {}
        self._stems_by_id: dict[str, set[str]] = {}
        self._chargrams_by_id: dict[str, set[str]] = {}
        self._embedding_text_by_id: dict[str, str] = {}
        for entry in self._entries:
            normalized_label = normalize_text(entry.label)
            if not normalized_label:
                continue
            compact_label = _compact_text(normalized_label)
            self._normalized_label_by_id[entry.onvoc_id] = normalized_label
            self._compact_label_by_id[entry.onvoc_id] = compact_label
            token_set = _expanded_tokens_for_lexical(normalized_label)
            stems = {
                stem for token in token_set for stem in (_simple_stem(token),) if len(stem) >= 3
            }
            self._text_tokens_by_id[entry.onvoc_id] = token_set
            self._stems_by_id[entry.onvoc_id] = stems
            chargrams = _chargrams(compact_label, n_values=(3, 4))
            self._chargrams_by_id[entry.onvoc_id] = chargrams
            for gram in chargrams:
                self._chargram_index[gram].add(entry.onvoc_id)
            self._embedding_text_by_id[entry.onvoc_id] = _normalize_for_embedding(
                entry.label
            )
            self._tree_label_index[normalized_label].append(entry)
            for token in token_set:
                if len(token) >= 3:
                    self._token_index[token].add(entry.onvoc_id)
            for stem in stems:
                self._stem_index[stem].add(entry.onvoc_id)

        self._crosswalk_by_key: dict[str, str] = {}
        self._crosswalk_label_index: dict[str, set[str]] = defaultdict(set)
        self._task_alias_index: dict[str, set[str]] = defaultdict(set)
        self._disease_entry_ids: set[str] = set()
        self._disease_token_index: dict[str, set[str]] = defaultdict(set)
        self._load_crosswalk(crosswalk_payload)
        self._build_disease_indexes()

    def prewarm_embeddings(self, *, source_texts: list[str]) -> None:
        if self._provider is None:
            return
        labels = list(self._embedding_text_by_id.values())
        payload = labels + [text for text in source_texts if text]
        try:
            self._provider.prewarm(payload)
        except Exception as exc:
            logger.warning("Embedding prewarm failed; reverting to lexical-only: %s", exc)
            self._provider = None

    def _load_crosswalk(self, payload: dict[str, Any]) -> None:
        sections = ["tasks", "concepts", "contrasts", "datasets", "statsmaps"]
        for section in sections:
            section_payload = payload.get(section)
            if not isinstance(section_payload, dict):
                continue
            for key, raw_spec in section_payload.items():
                if not isinstance(raw_spec, dict):
                    continue
                primary = str(raw_spec.get("primary") or "").strip()
                if not primary:
                    continue
                if primary not in self._entry_by_id:
                    continue

                normalized_key = _normalize_identifier(str(key))
                if normalized_key:
                    self._crosswalk_by_key[normalized_key] = primary

                labels = raw_spec.get("labels")
                if isinstance(labels, list):
                    for label in labels:
                        normalized_label = normalize_text(str(label))
                        if normalized_label:
                            self._crosswalk_label_index[normalized_label].add(primary)

                if section == "tasks":
                    for alias in _task_aliases_from_key(str(key)):
                        self._task_alias_index[alias].add(primary)

    def match(self, source: ConceptSource) -> tuple[OnvocMatch | None, str, str]:
        details = self.match_with_details(source)
        return details.match, details.status, details.reason

    def match_with_details(
        self,
        source: ConceptSource,
        *,
        candidate_top_k: int = 40,
        margin_min: float = 0.04,
    ) -> MatchDetails:
        for key in (
            _normalize_identifier(source.canonical_id),
            _normalize_identifier(source.source_id),
        ):
            if not key:
                continue
            if key in self._crosswalk_by_key:
                onvoc_id = self._crosswalk_by_key[key]
                entry = self._entry_by_id[onvoc_id]
                return MatchDetails(
                    match=OnvocMatch(
                        onvoc_id=entry.onvoc_id,
                        onvoc_uri=entry.uri,
                        onvoc_label=entry.label,
                        score=0.99,
                        method="crosswalk_id",
                        reason="crosswalk_canonical",
                    ),
                    status="mapped",
                    reason="crosswalk_canonical",
                    backend_used="none",
                )

        normalized_label = normalize_text(source.source_label)
        if not normalized_label:
            return MatchDetails(
                match=None,
                status="unmatched",
                reason="missing_source_label",
                lexical_no_candidate=True,
                embedding_no_candidate=True,
                backend_used="none",
            )

        crosswalk_hits = sorted(self._crosswalk_label_index.get(normalized_label, set()))
        if len(crosswalk_hits) == 1:
            entry = self._entry_by_id[crosswalk_hits[0]]
            return MatchDetails(
                match=OnvocMatch(
                    onvoc_id=entry.onvoc_id,
                    onvoc_uri=entry.uri,
                    onvoc_label=entry.label,
                    score=0.96,
                    method="crosswalk_label",
                    reason="crosswalk_label_exact",
                ),
                status="mapped",
                reason="crosswalk_label_exact",
                backend_used="none",
            )
        if len(crosswalk_hits) > 1:
            return MatchDetails(
                match=None,
                status="ambiguous",
                reason="crosswalk_label_multiple_matches",
                backend_used="none",
                lexical_no_candidate=False,
                embedding_no_candidate=False,
            )

        task_family = self._match_task_family(source, normalized_label)
        if task_family is not None:
            return MatchDetails(
                match=task_family,
                status="mapped",
                reason="crosswalk_task_family",
                backend_used="none",
            )

        disease_family = self._match_disease_alias(source, normalized_label)
        if disease_family is not None:
            return MatchDetails(
                match=disease_family,
                status="mapped",
                reason=disease_family.reason,
                backend_used="none",
            )

        exact_hits = self._tree_label_index.get(normalized_label, [])
        if len(exact_hits) == 1:
            entry = exact_hits[0]
            return MatchDetails(
                match=OnvocMatch(
                    onvoc_id=entry.onvoc_id,
                    onvoc_uri=entry.uri,
                    onvoc_label=entry.label,
                    score=0.94,
                    method="tree_exact",
                    reason="tree_label_exact",
                ),
                status="mapped",
                reason="tree_label_exact",
                backend_used="none",
            )
        if len(exact_hits) > 1:
            return MatchDetails(
                match=None,
                status="ambiguous",
                reason="tree_label_multiple_matches",
                backend_used="none",
            )

        candidates = self._lexical_candidates(
            source=source,
            normalized_label=normalized_label,
            top_k=candidate_top_k,
        )
        if not candidates:
            return MatchDetails(
                match=None,
                status="unmatched",
                reason="no_candidate_after_lexical",
                candidate_count_lexical=0,
                top_candidates=[],
                lexical_no_candidate=True,
                embedding_no_candidate=True,
                backend_used="none",
            )

        top_candidates_payload = [
            {
                "onvoc_id": candidate.onvoc_id,
                "onvoc_label": candidate.onvoc_label,
                "lexical_score": round(candidate.lexical_score, 6),
                "source": candidate.source,
            }
            for candidate in candidates[:5]
        ]

        best_candidate = candidates[0]
        top1 = best_candidate.lexical_score
        top2 = candidates[1].lexical_score if len(candidates) > 1 else None
        match_method = _lexical_method_from_source(best_candidate.source)
        match_reason = "lexical_candidate"
        backend_used = "none"

        if self._provider is not None:
            reranked = self._rerank_with_embedding(
                normalized_label=normalized_label,
                candidates=candidates,
                margin_min=margin_min,
            )
            if reranked is not None:
                best_candidate, top1, top2, backend_used, match_method, match_reason = reranked
            else:
                return MatchDetails(
                    match=None,
                    status="unmatched",
                    reason="no_candidate_after_embedding",
                    candidate_count_lexical=len(candidates),
                    top_candidates=top_candidates_payload,
                    lexical_no_candidate=False,
                    embedding_no_candidate=True,
                    backend_used="none",
                )

        if top2 is not None and top1 is not None and (top1 - top2) < margin_min:
            return MatchDetails(
                match=None,
                status="ambiguous",
                reason="margin_too_small",
                candidate_count_lexical=len(candidates),
                top_candidates=top_candidates_payload,
                lexical_no_candidate=False,
                embedding_no_candidate=False,
                backend_used=backend_used,
                top1_score=top1,
                top2_score=top2,
            )

        if backend_used == "none":
            match_method = _lexical_method_from_source(best_candidate.source)
            if best_candidate.source == "lexical_compound":
                match_reason = "lexical_compound"
            elif best_candidate.source == "lexical_subword":
                match_reason = "lexical_subword"
            elif best_candidate.source == "lexical_stem":
                match_reason = "lexical_stem"

        entry = self._entry_by_id[best_candidate.onvoc_id]
        return MatchDetails(
            match=OnvocMatch(
                onvoc_id=entry.onvoc_id,
                onvoc_uri=entry.uri,
                onvoc_label=entry.label,
                score=max(0.0, min(1.0, top1 if top1 is not None else best_candidate.lexical_score)),
                method=match_method,
                reason=match_reason,
            ),
            status="mapped",
            reason=match_reason,
            candidate_count_lexical=len(candidates),
            top_candidates=top_candidates_payload,
            lexical_no_candidate=False,
            embedding_no_candidate=False,
            backend_used=backend_used,
            top1_score=top1,
            top2_score=top2,
        )

    def _lexical_candidates(
        self,
        *,
        source: ConceptSource,
        normalized_label: str,
        top_k: int,
    ) -> list[LexicalCandidate]:
        query_variants = _query_variants_for_lexical(
            normalized_label=normalized_label,
            source_id=source.source_id,
            canonical_id=source.canonical_id,
        )
        query_tokens = {
            token for variant in query_variants for token in _expanded_tokens_for_lexical(variant)
        }
        query_stems = {
            stem for token in query_tokens for stem in (_simple_stem(token),) if len(stem) >= 3
        }
        query_compact = _compact_text(normalized_label)
        query_chargrams = _chargrams(query_compact, n_values=(3, 4))

        candidate_ids: set[str] = set()
        for token in query_tokens:
            candidate_ids.update(self._token_index.get(token, set()))
        for stem in query_stems:
            candidate_ids.update(self._stem_index.get(stem, set()))
        for gram in query_chargrams:
            candidate_ids.update(self._chargram_index.get(gram, set()))

        if not candidate_ids:
            return []

        rows: list[LexicalCandidate] = []
        for onvoc_id in candidate_ids:
            entry = self._entry_by_id.get(onvoc_id)
            if entry is None:
                continue
            label_tokens = self._text_tokens_by_id.get(onvoc_id, set())
            label_stems = self._stems_by_id.get(onvoc_id, set())
            label_chargrams = self._chargrams_by_id.get(onvoc_id, set())
            normalized_entry = self._normalized_label_by_id.get(onvoc_id, "")
            compact_entry = self._compact_label_by_id.get(onvoc_id, "")
            if not normalized_entry:
                continue

            token_jaccard = _token_jaccard(query_tokens, label_tokens)
            stem_jaccard = _token_jaccard(query_stems, label_stems)
            chargram_jaccard = _token_jaccard(query_chargrams, label_chargrams)
            ratio_text = max(
                SequenceMatcher(None, normalized_label, normalized_entry).ratio(),
                max(
                    SequenceMatcher(None, variant, normalized_entry).ratio()
                    for variant in query_variants
                ),
            )
            ratio_compact = SequenceMatcher(None, query_compact, compact_entry).ratio()

            contains_bonus = 0.0
            if normalized_entry in normalized_label or normalized_label in normalized_entry:
                contains_bonus = 0.08

            lexical_score = (
                0.24 * token_jaccard
                + 0.20 * stem_jaccard
                + 0.30 * chargram_jaccard
                + 0.16 * ratio_compact
                + 0.10 * ratio_text
                + contains_bonus
            )

            source_name = "lexical_ngram"
            if token_jaccard == 0 and chargram_jaccard > 0:
                source_name = "lexical_subword"
            if token_jaccard == 0 and stem_jaccard > 0:
                source_name = "lexical_stem"
            if ratio_compact > ratio_text + 0.10:
                source_name = "lexical_compound"

            rows.append(
                LexicalCandidate(
                    onvoc_id=onvoc_id,
                    onvoc_label=entry.label,
                    lexical_score=max(0.0, min(1.0, lexical_score)),
                    token_jaccard=token_jaccard,
                    stem_jaccard=stem_jaccard,
                    chargram_jaccard=chargram_jaccard,
                    ratio_compact=ratio_compact,
                    ratio_text=ratio_text,
                    source=source_name,
                )
            )

        rows.sort(
            key=lambda candidate: (
                -candidate.lexical_score,
                -candidate.chargram_jaccard,
                -candidate.ratio_compact,
                candidate.onvoc_label,
            )
        )
        return rows[:top_k]

    def _rerank_with_embedding(
        self,
        *,
        normalized_label: str,
        candidates: list[LexicalCandidate],
        margin_min: float,
    ) -> tuple[LexicalCandidate, float, float | None, str, str, str] | None:
        if self._provider is None:
            return None

        source_text = _normalize_for_embedding(normalized_label)
        label_texts = [self._embedding_text_by_id.get(candidate.onvoc_id, "") for candidate in candidates]
        try:
            self._provider.embed_texts([source_text, *label_texts])
        except Exception as exc:
            logger.warning("Embedding rerank failed; fallback to lexical-only: %s", exc)
            self._provider = None
            return None

        query_vector = self._provider.get(source_text)
        if query_vector is None:
            return None

        scored: list[tuple[float, LexicalCandidate, float]] = []
        for candidate, label_text in zip(candidates, label_texts, strict=True):
            label_vector = self._provider.get(label_text)
            if label_vector is None:
                continue
            embedding_score = _cosine_similarity(query_vector, label_vector)
            final_score = max(
                0.0,
                min(
                    1.0,
                    0.60 * embedding_score + 0.30 * candidate.lexical_score + 0.10 * candidate.ratio_text,
                ),
            )
            scored.append((final_score, candidate, embedding_score))

        if not scored:
            return None
        scored.sort(
            key=lambda item: (-item[0], -item[2], -item[1].lexical_score, item[1].onvoc_label)
        )
        top1_score, best_candidate, top1_embed = scored[0]
        top2_score = scored[1][0] if len(scored) > 1 else None

        method = "embedding_rerank_gemini"
        reason = "embedding_rerank"
        if top2_score is not None and (top1_score - top2_score) < margin_min:
            method = "embedding_rerank_gemini_close_margin"
        if best_candidate.source == "lexical_compound":
            reason = "embedding_rerank_compound"

        return best_candidate, top1_score, top2_score, "gemini", method, reason

    def _match_task_family(
        self,
        source: ConceptSource,
        normalized_label: str,
    ) -> OnvocMatch | None:
        if not self._task_alias_index:
            return None

        search_texts = [
            _normalize_for_task_matching(normalized_label),
            _normalize_for_task_matching(_identifier_surface(source.canonical_id)),
            _normalize_for_task_matching(_identifier_surface(source.source_id)),
        ]
        search_texts = [text for text in search_texts if text]
        if not search_texts:
            return None

        # 1) Exact alias hit.
        for text in search_texts:
            onvoc_ids = self._task_alias_index.get(text, set())
            if len(onvoc_ids) == 1:
                onvoc_id = next(iter(onvoc_ids))
                entry = self._entry_by_id[onvoc_id]
                return OnvocMatch(
                    onvoc_id=entry.onvoc_id,
                    onvoc_uri=entry.uri,
                    onvoc_label=entry.label,
                    score=0.93,
                    method="crosswalk_task_family",
                    reason="crosswalk_task_alias_exact",
                )

        # 2) Phrase containment for multi-token aliases.
        for text in search_texts:
            for alias, onvoc_ids in self._task_alias_index.items():
                if len(alias.split()) < 2:
                    continue
                if not _contains_phrase(text, alias):
                    continue
                if len(onvoc_ids) != 1:
                    continue
                onvoc_id = next(iter(onvoc_ids))
                entry = self._entry_by_id[onvoc_id]
                return OnvocMatch(
                    onvoc_id=entry.onvoc_id,
                    onvoc_uri=entry.uri,
                    onvoc_label=entry.label,
                    score=0.90,
                    method="crosswalk_task_family",
                    reason="crosswalk_task_alias_contains",
                )

        # 3) Fuzzy fallback over task aliases.
        best_onvoc_id: str | None = None
        best_score = 0.0
        tie = False

        for text in search_texts:
            text_tokens = {token for token in text.split() if len(token) >= 2}
            for alias, onvoc_ids in self._task_alias_index.items():
                if len(onvoc_ids) != 1:
                    continue
                alias_tokens = {token for token in alias.split() if len(token) >= 2}
                ratio = SequenceMatcher(None, text, alias).ratio()
                jaccard = _token_jaccard(text_tokens, alias_tokens)
                score = max(ratio, 0.65 * ratio + 0.35 * jaccard)
                if alias_tokens and alias_tokens <= text_tokens:
                    score = max(score, min(0.91, score + 0.08))

                onvoc_id = next(iter(onvoc_ids))
                if score > best_score + 1e-6:
                    best_onvoc_id = onvoc_id
                    best_score = score
                    tie = False
                elif abs(score - best_score) <= 0.01 and best_onvoc_id is not None and onvoc_id != best_onvoc_id:
                    tie = True

        if best_onvoc_id is None or tie or best_score < 0.84:
            return None

        entry = self._entry_by_id[best_onvoc_id]
        return OnvocMatch(
            onvoc_id=entry.onvoc_id,
            onvoc_uri=entry.uri,
            onvoc_label=entry.label,
            score=min(0.92, max(0.0, best_score)),
            method="crosswalk_task_family",
            reason="crosswalk_task_alias_fuzzy",
        )

    def _build_disease_indexes(self) -> None:
        for entry in self._entries:
            normalized = normalize_text(entry.label)
            if not normalized:
                continue
            if not _DISEASE_ENTRY_PATTERN.search(normalized):
                continue
            self._disease_entry_ids.add(entry.onvoc_id)
            for token in normalized.split():
                if len(token) >= 3:
                    self._disease_token_index[token].add(entry.onvoc_id)

    def _match_disease_alias(
        self,
        source: ConceptSource,
        normalized_label: str,
    ) -> OnvocMatch | None:
        search_texts = [
            _normalize_for_disease_matching(normalized_label),
            _normalize_for_disease_matching(_identifier_surface(source.canonical_id)),
            _normalize_for_disease_matching(_identifier_surface(source.source_id)),
        ]
        search_texts = [text for text in search_texts if text]
        if not search_texts:
            return None

        candidates: list[tuple[float, str, str]] = []
        for rule in _DISEASE_RULE_SPECS:
            onvoc_id = str(rule["onvoc_id"])
            if onvoc_id not in self._entry_by_id:
                continue
            patterns = tuple(str(pattern) for pattern in rule["patterns"])
            score = float(rule["score"])
            reason = str(rule["reason"])
            if any(
                re.search(pattern, text) is not None
                for text in search_texts
                for pattern in patterns
            ):
                candidates.append((score, onvoc_id, reason))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            top_score = candidates[0][0]
            top_ids = {onvoc_id for score, onvoc_id, _ in candidates if abs(score - top_score) <= 0.01}
            if len(top_ids) == 1:
                _, onvoc_id, reason = candidates[0]
                entry = self._entry_by_id[onvoc_id]
                return OnvocMatch(
                    onvoc_id=entry.onvoc_id,
                    onvoc_uri=entry.uri,
                    onvoc_label=entry.label,
                    score=top_score,
                    method="crosswalk_disease_alias",
                    reason=reason,
                )

        return self._fuzzy_disease_match(search_texts)

    def _fuzzy_disease_match(self, search_texts: list[str]) -> OnvocMatch | None:
        best_onvoc_id: str | None = None
        best_score = 0.0
        tie = False

        for text in search_texts:
            text_tokens = {token for token in text.split() if len(token) >= 3}
            candidate_ids: set[str] = set()
            for token in text_tokens:
                candidate_ids.update(self._disease_token_index.get(token, set()))
            if not candidate_ids and any(
                marker in text
                for marker in (
                    "disease",
                    "disorder",
                    "syndrome",
                    "depression",
                    "anxiety",
                    "adhd",
                    "ptsd",
                    "autism",
                    "schizophren",
                    "bipolar",
                )
            ):
                candidate_ids = set(self._disease_entry_ids)

            for onvoc_id in candidate_ids:
                entry = self._entry_by_id.get(onvoc_id)
                if entry is None:
                    continue
                entry_text = _normalize_for_disease_matching(entry.label)
                if not entry_text:
                    continue
                entry_tokens = {token for token in entry_text.split() if len(token) >= 3}
                ratio = SequenceMatcher(None, text, entry_text).ratio()
                jaccard = _token_jaccard(text_tokens, entry_tokens)
                score = max(ratio, 0.60 * ratio + 0.40 * jaccard)
                if entry_tokens and entry_tokens <= text_tokens:
                    score = max(score, min(0.90, score + 0.06))
                if score > best_score + 1e-6:
                    best_onvoc_id = onvoc_id
                    best_score = score
                    tie = False
                elif abs(score - best_score) <= 0.01 and best_onvoc_id is not None and onvoc_id != best_onvoc_id:
                    tie = True

        if best_onvoc_id is None or tie or best_score < 0.78:
            return None

        entry = self._entry_by_id[best_onvoc_id]
        return OnvocMatch(
            onvoc_id=entry.onvoc_id,
            onvoc_uri=entry.uri,
            onvoc_label=entry.label,
            score=min(0.90, max(0.78, best_score)),
            method="crosswalk_disease_fuzzy",
            reason="disease_fuzzy",
        )

    def _fuzzy_tree_match(self, normalized_label: str) -> OnvocMatch | None:
        tokens = [token for token in normalized_label.split() if len(token) >= 3]
        candidate_ids: set[str] = set()
        for token in tokens:
            candidate_ids.update(self._token_index.get(token, set()))

        if not candidate_ids:
            return None

        label_token_set = set(tokens)
        best_entry: OnvocEntry | None = None
        best_score = 0.0
        tie = False

        for onvoc_id in candidate_ids:
            entry = self._entry_by_id.get(onvoc_id)
            if entry is None:
                continue
            entry_norm = normalize_text(entry.label)
            if not entry_norm:
                continue

            ratio = SequenceMatcher(None, normalized_label, entry_norm).ratio()
            entry_tokens = {token for token in entry_norm.split() if len(token) >= 3}
            jaccard = _token_jaccard(label_token_set, entry_tokens)
            score = max(ratio, 0.65 * ratio + 0.35 * jaccard)

            if score > best_score + 1e-6:
                best_entry = entry
                best_score = score
                tie = False
            elif abs(score - best_score) <= 0.01 and best_entry is not None and entry.onvoc_id != best_entry.onvoc_id:
                tie = True

        if best_entry is None:
            return None
        if tie:
            return None
        if best_score < 0.86:
            return None

        return OnvocMatch(
            onvoc_id=best_entry.onvoc_id,
            onvoc_uri=best_entry.uri,
            onvoc_label=best_entry.label,
            score=min(0.92, max(0.0, best_score)),
            method="tree_fuzzy",
            reason="tree_label_fuzzy",
        )


def _flatten_onvoc_tree(tree_payload: dict[str, Any]) -> list[OnvocEntry]:
    tree_nodes = tree_payload.get("tree")
    if not isinstance(tree_nodes, list):
        return []

    entries: dict[str, OnvocEntry] = {}

    def visit(node: dict[str, Any]) -> None:
        if not isinstance(node, dict):
            return
        onvoc_id = str(node.get("id") or "").strip()
        label = str(node.get("label") or "").strip()
        if onvoc_id and label:
            uri = str(node.get("uri") or f"https://w3id.org/onvoc/{onvoc_id}").strip()
            level_raw = node.get("level")
            level: int | None
            try:
                level = int(level_raw) if level_raw is not None else None
            except (TypeError, ValueError):
                level = None
            entries[onvoc_id] = OnvocEntry(
                onvoc_id=onvoc_id,
                uri=uri,
                label=label,
                level=level,
            )

        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    visit(child)

    for top_node in tree_nodes:
        if isinstance(top_node, dict):
            visit(top_node)

    return sorted(entries.values(), key=lambda entry: (entry.onvoc_id, entry.label))


def _extract_concept_source(record: dict[str, Any]) -> ConceptSource | None:
    target = record.get("target") or {}
    mapping = record.get("mapping") or {}
    if not isinstance(target, dict) or not isinstance(mapping, dict):
        return None

    target_type = str(target.get("type") or "").strip().lower()
    source_id = _as_text(target.get("id"), mapping.get("canonical_id"))
    canonical_id = _as_text(mapping.get("canonical_id"), target.get("id"))
    source_label = _as_text(target.get("label"), target.get("name"), canonical_id)

    source_is_concept = source_id.startswith("concept:") or canonical_id.startswith("concept:")
    if target_type and target_type != "concept" and not source_is_concept:
        return None
    if not source_is_concept and target_type != "concept":
        return None

    if not source_id:
        source_id = f"concept:{_slugify(source_label)}"
    if not canonical_id:
        canonical_id = source_id

    return ConceptSource(
        source_id=source_id,
        source_label=source_label,
        canonical_id=canonical_id,
        paper_id=_paper_id(record),
    )


def _paper_id(record: dict[str, Any]) -> str:
    paper = record.get("paper") or {}
    if not isinstance(paper, dict):
        return "paper:unknown"
    return _as_text(paper.get("id"), paper.get("pmid"), paper.get("doi"), "paper:unknown")


def _normalize_record_onvoc(record: dict[str, Any], match: OnvocMatch) -> dict[str, Any]:
    updated = json.loads(json.dumps(record))
    target = updated.setdefault("target", {})
    mapping = updated.setdefault("mapping", {})

    original_target_id = _as_text(target.get("id"))
    original_canonical_id = _as_text(mapping.get("canonical_id"))

    normalized_target_id = _onvoc_concept_id(match.onvoc_id)
    target["type"] = "Concept"
    target["id"] = normalized_target_id
    target["label"] = match.onvoc_label
    target["onvoc_id"] = match.onvoc_id
    target["onvoc_uri"] = match.onvoc_uri
    if original_target_id and original_target_id != normalized_target_id:
        target["original_id"] = original_target_id

    mapping["canonical_id"] = normalized_target_id
    mapping["mapping_type"] = _maps_to_type(match.method)
    mapping["mapping_confidence"] = max(_to_float(mapping.get("mapping_confidence"), default=0.0), match.score)
    mapping["onvoc_id"] = match.onvoc_id
    mapping["onvoc_uri"] = match.onvoc_uri
    if original_canonical_id and original_canonical_id != normalized_target_id:
        mapping["original_canonical_id"] = original_canonical_id

    updated["normalization"] = {
        "onvoc": {
            "onvoc_id": match.onvoc_id,
            "onvoc_uri": match.onvoc_uri,
            "onvoc_label": match.onvoc_label,
            "score": match.score,
            "method": match.method,
            "version": ONVOC_MAPPER_VERSION,
        }
    }
    return updated


def _build_maps_to_edge(
    *,
    source: ConceptSource,
    match: OnvocMatch,
    params_hash: str,
) -> dict[str, Any]:
    method = _prov_method(match.method)
    return {
        "edge_type": "MAPS_TO",
        "source_id": source.source_id,
        "target_id": _onvoc_concept_id(match.onvoc_id),
        "mapping_type": _maps_to_type(match.method),
        "similarity_score": match.score,
        "strength": match.score,
        "confidence": match.score,
        "prov": {
            "source": "gabriel",
            "method": method,
            "confidence": match.score,
            "timestamp": _utc_now_iso(),
            "loader_version": ONVOC_MAPPER_VERSION,
            "params_hash": params_hash,
        },
        "properties": {
            "paper_id": source.paper_id,
            "source_label": source.source_label,
            "canonical_id": source.canonical_id,
            "onvoc_id": match.onvoc_id,
            "onvoc_uri": match.onvoc_uri,
            "onvoc_label": match.onvoc_label,
            "mapping_reason": match.reason,
            "mapping_method": match.method,
        },
    }


def _build_same_as_edge(
    *,
    source: ConceptSource,
    match: OnvocMatch,
    params_hash: str,
) -> dict[str, Any]:
    method = _prov_method(match.method)
    return {
        "edge_type": "SAME_AS",
        "source_id": source.source_id,
        "target_id": _onvoc_concept_id(match.onvoc_id),
        "strength": match.score,
        "confidence": match.score,
        "merge_timestamp": _utc_now_iso(),
        "merge_reason": f"onvoc_mapping:{match.method}",
        "canonical_selection": "target",
        "prov": {
            "source": "gabriel",
            "method": method,
            "confidence": match.score,
            "timestamp": _utc_now_iso(),
            "loader_version": ONVOC_MAPPER_VERSION,
            "params_hash": params_hash,
        },
        "properties": {
            "paper_id": source.paper_id,
            "source_label": source.source_label,
            "canonical_id": source.canonical_id,
            "onvoc_id": match.onvoc_id,
            "onvoc_uri": match.onvoc_uri,
            "onvoc_label": match.onvoc_label,
            "mapping_reason": match.reason,
            "mapping_method": match.method,
        },
    }


def _review_row(row: dict[str, Any], *, reason: str, score: float | None) -> dict[str, Any]:
    payload = {
        "source": "kggen_onvoc_mapper",
        "paper_id": row.get("paper_id"),
        "source_id": row.get("source_id"),
        "source_label": row.get("source_label"),
        "canonical_id": row.get("canonical_id"),
        "status": row.get("status"),
        "reason": reason,
    }
    if score is not None:
        payload["score"] = score
    if row.get("onvoc_id"):
        payload["candidate_onvoc_id"] = row.get("onvoc_id")
        payload["candidate_onvoc_label"] = row.get("onvoc_label")
    return payload


def _resolve_input_files(input_path: Path) -> list[Path]:
    if not input_path.exists():
        raise FileNotFoundError(f"KGGEN input not found: {input_path}")
    if input_path.is_file():
        return [input_path]

    files = sorted(
        path
        for path in input_path.rglob("*")
        if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".ndjson"}
    )
    if not files:
        raise FileNotFoundError(f"No JSON/JSONL files found under: {input_path}")
    return files


def _read_json_records(paths: list[Path]) -> tuple[list[dict[str, Any]], int, Counter[str]]:
    rows: list[dict[str, Any]] = []
    parse_errors = 0
    parse_reasons: Counter[str] = Counter()

    for file_path in paths:
        suffix = file_path.suffix.lower()
        if suffix in {".jsonl", ".ndjson"}:
            with file_path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        parse_errors += 1
                        parse_reasons["json_decode_error"] += 1
                        continue
                    if isinstance(payload, dict):
                        rows.append(payload)
                    else:
                        parse_errors += 1
                        parse_reasons["payload_not_object"] += 1
            continue

        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            parse_errors += 1
            parse_reasons["json_decode_error"] += 1
            continue

        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
            items = payload.get("records") or []
        else:
            items = [payload]

        for item in items:
            if isinstance(item, dict):
                rows.append(item)
            else:
                parse_errors += 1
                parse_reasons["payload_not_object"] += 1

    return rows, parse_errors, parse_reasons


def _same_as_allowed(match: OnvocMatch, *, same_as_threshold: float) -> bool:
    if match.score < same_as_threshold:
        return False
    return match.method in {"crosswalk_id", "crosswalk_label", "tree_exact"}


def _maps_to_type(method: str) -> str:
    if method in {"crosswalk_id", "tree_exact"}:
        return "exact"
    if method in {
        "crosswalk_label",
        "crosswalk_task_family",
        "crosswalk_disease_alias",
        "lexical_ngram",
        "lexical_subword",
        "lexical_stem",
        "lexical_compound",
    }:
        return "synonym"
    return "related"


def _prov_method(method: str) -> str:
    if method == "crosswalk_id":
        return "exact_id"
    if method in {
        "crosswalk_label",
        "tree_exact",
        "crosswalk_task_family",
        "crosswalk_disease_alias",
        "lexical_ngram",
        "lexical_subword",
        "lexical_stem",
        "lexical_compound",
    }:
        return "string_match"
    if method.startswith("embedding_rerank_"):
        return "embedding_match"
    return "embedding_match"


def _onvoc_concept_id(onvoc_id: str) -> str:
    return f"concept:{onvoc_id}"


def _task_aliases_from_key(key: str) -> set[str]:
    normalized_key = _normalize_identifier(key)
    if not normalized_key:
        return set()

    prefix, _, suffix = normalized_key.partition(":")
    if prefix != "task" or not suffix:
        return set()

    raw = suffix.replace("-", " ").strip()
    if not raw:
        return set()

    aliases = {
        _normalize_for_task_matching(raw),
        _normalize_for_task_matching(raw.replace(" no go", " nogo")),
    }
    if "go nogo" in aliases or "go no go" in aliases:
        aliases.add("go no go")
        aliases.add("go nogo")

    cleaned = {alias for alias in aliases if alias}
    return cleaned


def _identifier_surface(identifier: str) -> str:
    text = str(identifier or "").strip()
    if not text:
        return ""
    if ":" in text:
        _, suffix = text.split(":", 1)
    else:
        suffix = text
    return suffix.replace("_", " ").replace("-", " ")


def _normalize_for_task_matching(value: str) -> str:
    normalized = normalize_text(value)
    if not normalized:
        return ""
    normalized = normalized.replace("nogo", "no go")
    normalized = normalized.replace("gonogo", "go no go")
    normalized = re.sub(r"\borthogonalized\b", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _contains_phrase(text: str, phrase: str) -> bool:
    escaped = re.escape(phrase)
    return re.search(rf"(^|\\s){escaped}(\\s|$)", text) is not None


def _lexical_method_from_source(source: str) -> str:
    if source == "lexical_subword":
        return "lexical_subword"
    if source == "lexical_stem":
        return "lexical_stem"
    if source == "lexical_compound":
        return "lexical_compound"
    return "lexical_ngram"


def _simple_stem(token: str) -> str:
    value = str(token or "").strip().lower()
    if len(value) <= 4:
        return value
    for suffix in (
        "ization",
        "ations",
        "ation",
        "ments",
        "ment",
        "ings",
        "ing",
        "edly",
        "ly",
        "ed",
        "ies",
        "es",
        "s",
    ):
        if value.endswith(suffix) and len(value) - len(suffix) >= 3:
            if suffix == "ies":
                return value[:-3] + "y"
            return value[: -len(suffix)]
    return value


def _split_compound_token(token: str) -> list[str]:
    value = str(token or "").strip().lower()
    if len(value) < 7:
        return [value] if value else []
    prefixes = ("fronto", "temporo", "parieto", "occipito", "hippocampo", "thalamo")
    for prefix in prefixes:
        if value.startswith(prefix) and len(value) > len(prefix) + 2:
            suffix = value[len(prefix) :]
            return [prefix, suffix]
    return [value] if value else []


def _expanded_tokens_for_lexical(value: str) -> set[str]:
    normalized = normalize_text(value)
    if not normalized:
        return set()
    tokens = [token for token in normalized.split() if len(token) >= 2]
    expanded: set[str] = set(tokens)
    for token in tokens:
        for piece in _split_compound_token(token):
            if len(piece) >= 2:
                expanded.add(piece)
        stem = _simple_stem(token)
        if len(stem) >= 2:
            expanded.add(stem)
    return expanded


def _query_variants_for_lexical(
    *,
    normalized_label: str,
    source_id: str,
    canonical_id: str,
) -> list[str]:
    variants: set[str] = set()
    base = normalized_label.strip()
    if base:
        variants.add(base)
        variants.add(base.replace(" ", ""))

    for identifier in (source_id, canonical_id):
        surface = _identifier_surface(identifier)
        normalized = normalize_text(surface)
        if normalized:
            variants.add(normalized)
            variants.add(normalized.replace(" ", ""))

    prefixed = ("fronto", "temporo", "parieto", "occipito", "hippocampo", "thalamo")
    expanded: set[str] = set()
    for variant in variants:
        tokens = variant.split()
        if len(tokens) < 2:
            continue
        for idx in range(len(tokens) - 1):
            left = tokens[idx]
            right = tokens[idx + 1]
            if left in prefixed and len(right) >= 4:
                merged = tokens[:idx] + [left + right] + tokens[idx + 2 :]
                expanded.add(" ".join(merged))
                expanded.add("".join(merged))
        for idx, token in enumerate(tokens):
            pieces = _split_compound_token(token)
            if len(pieces) <= 1:
                continue
            split_tokens = tokens[:idx] + pieces + tokens[idx + 1 :]
            expanded.add(" ".join(split_tokens))
            expanded.add("".join(split_tokens))
    variants.update(expanded)
    ordered = sorted(v for v in variants if v)
    return ordered


def _compact_text(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum())


def _chargrams(value: str, *, n_values: tuple[int, ...]) -> set[str]:
    compact = _compact_text(value.casefold())
    grams: set[str] = set()
    if not compact:
        return grams
    for n in n_values:
        if n <= 0:
            continue
        if len(compact) < n:
            continue
        for idx in range(len(compact) - n + 1):
            grams.add(compact[idx : idx + n])
    return grams


def _normalize_for_embedding(value: str) -> str:
    normalized = normalize_text(value)
    if not normalized:
        return ""
    normalized = normalized.replace("fronto parietal", "frontoparietal")
    normalized = normalized.replace("temporo parietal", "temporoparietal")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _normalize_for_disease_matching(value: str) -> str:
    normalized = normalize_text(value)
    if not normalized:
        return ""
    normalized = normalized.replace("alzheimers", "alzheimer")
    normalized = normalized.replace("parkinsons", "parkinson")
    normalized = re.sub(r"\bmdd\b", "major depressive disorder", normalized)
    normalized = re.sub(r"\bptsd\b", "ptsd", normalized)
    normalized = re.sub(r"\badhd\b", "adhd", normalized)
    normalized = re.sub(
        r"\b("
        r"patient|patients|participant|participants|individual|individuals|subject|subjects|"
        r"history|current|medication|medication free|drug free|drug naive|drug naive|naive|"
        r"first episode|adolescent|adolescents|adult|adults|youth|severe|moderate|mild|"
        r"high|low|level|levels|symptom|symptoms|processing|provoking|afflicted|study|"
        r"children|child"
        r")\b",
        " ",
        normalized,
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _normalize_identifier(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text.casefold()
    return normalized.replace("_", "-")


def _token_jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _l2_normalize(vector: list[float]) -> list[float]:
    if not vector:
        return []
    norm_sq = sum(value * value for value in vector)
    if norm_sq <= 0:
        return vector
    norm = norm_sq ** 0.5
    return [value / norm for value in vector]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    if size == 0:
        return 0.0
    dot = 0.0
    for idx in range(size):
        dot += left[idx] * right[idx]
    return max(0.0, min(1.0, dot))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _as_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _to_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ratio(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)


def _stable_hash(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "unknown"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
