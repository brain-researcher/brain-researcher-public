"""BR-KG multi-hop question answering tool."""

import os
import re
import time
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.services.neurokg.query_service import QueryService
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

_PMID_ONLY_RE = re.compile(r"^\s*(?:pmid[:\s]*)?([0-9]{5,9})\s*$", re.IGNORECASE)
_PMID_ANY_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:pmid[:\s]*)?([0-9]{5,9})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_DOI_ONLY_RE = re.compile(r"^\s*(?:doi[:\s]*)?(10\.[0-9]{4,9}/\S+)\s*$", re.IGNORECASE)
_DOI_ANY_RE = re.compile(r"10\.[0-9]{4,9}/\S+", re.IGNORECASE)
_SEED_RELATION_PAIR_RE = re.compile(
    r"\b(?:between|links?|connect(?:s|ed|ing)?|relationship(?:s)?)\s+(.+?)\s+"
    r"(?:and|to|with)\s+(.+?)(?:[?.!,;]|$)",
    re.IGNORECASE,
)
_SEED_SPLIT_RE = re.compile(
    r"[?.!;]+|\b(?:and|or|between|with|to|from|via|vs|versus|"
    r"connect(?:s|ed|ing)?|relationship(?:s)?)\b",
    re.IGNORECASE,
)
_SEED_CONTEXT_BREAK_TOKENS = {
    "in",
    "during",
    "across",
    "among",
    "within",
    "under",
    "over",
    "for",
    "from",
}
_SEED_NOISE_TERMS = {
    "what",
    "which",
    "how",
    "why",
    "show",
    "find",
    "list",
    "explain",
    "evidence",
    "question",
    "links",
    "link",
    "relationship",
    "relationships",
    "connection",
    "connections",
    "related",
}
_SEED_BOUNDARY_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "being",
    "been",
    "of",
    "for",
    "from",
    "in",
    "on",
    "to",
    "with",
    "about",
    "by",
}


class KGMultihopQAArgs(BaseModel):
    """Arguments for multi-hop question answering."""

    question: str = Field(
        description="Natural language question to answer over the knowledge graph"
    )
    max_hops: int = Field(
        default=3,
        description="Maximum number of graph hops to traverse (1-5)",
    )
    mode: str = Field(
        default="breadth_first",
        description="Traversal mode (breadth_first, depth_first, shortest_path, weighted_path, bidirectional, pattern_match)",
    )
    max_results: int = Field(
        default=50,
        description="Maximum number of paths to return (1-500)",
    )
    allowed_edge_types: list[str] | None = Field(
        default=None,
        description="Optional relationship type allowlist",
    )
    return_subgraph: bool = Field(
        default=True,
        description="Return the subgraph used for reasoning",
    )
    semantic: bool = Field(
        default=False,
        description="Enable heavyweight semantic matching and embedding-backed seed resolution",
    )


class KGMultihopQATool(NeuroToolWrapper):
    """Answer questions via multi-hop reasoning over the knowledge graph.

    Returns:
        - answer: Natural language answer to the question
        - subgraph: Subgraph nodes and edges used in reasoning (if requested)
    """

    def __init__(self, query_service: QueryService | None = None):
        super().__init__()
        self.query_service = query_service or QueryService()
        self.runtime_seed_mapper_mode = (
            os.environ.get("NEUROKG_MULTIHOP_RUNTIME_SEED_MAPPER", "auto")
            .strip()
            .lower()
        )
        self._runtime_mapper: Any | None = None
        self._runtime_mapper_initialized = False

    def get_tool_name(self) -> str:
        return "kg_multihop_qa"

    def get_tool_description(self) -> str:
        return (
            "Answer complex questions via multi-hop reasoning over BR-KG. "
            "Traverses relationships to find answers requiring multiple inference steps. "
            "Returns answers with reasoning paths and supporting subgraphs."
        )

    def get_args_schema(self):
        return KGMultihopQAArgs

    @staticmethod
    def _runtime_mode_enabled(mode: str) -> bool:
        normalized = str(mode or "").strip().lower()
        if normalized in {"", "off", "false", "0", "disabled"}:
            return False
        return normalized in {"auto", "on", "true", "1", "force", "yes"}

    def _resolve_runtime_mapper(self) -> Any | None:
        if self._runtime_mapper_initialized:
            return self._runtime_mapper
        self._runtime_mapper_initialized = True
        if not self._runtime_mode_enabled(self.runtime_seed_mapper_mode):
            return None
        try:
            from brain_researcher.services.neurokg.matching.gabriel_runtime_mapper import (
                GabrielRuntimeMapper,
            )

            self._runtime_mapper = GabrielRuntimeMapper.from_env()
        except Exception:
            self._runtime_mapper = None
        return self._runtime_mapper

    @staticmethod
    def _resolve_runtime_budget_s() -> float:
        raw = os.getenv("BR_KG_MULTIHOP_TOOL_BUDGET_S", "45")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 45.0
        if value <= 0:
            value = 45.0
        return max(2.0, min(300.0, value))

    @staticmethod
    def _resolve_min_traversal_window_s() -> float:
        raw = os.getenv("BR_KG_MULTIHOP_TOOL_MIN_TRAVERSAL_WINDOW_S", "4")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 4.0
        if value <= 0:
            value = 4.0
        return max(1.0, min(30.0, value))

    @staticmethod
    def _resolve_seed_budget_ratio() -> float:
        raw = os.getenv("BR_KG_MULTIHOP_SEED_BUDGET_RATIO", "0.55")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.55
        if value <= 0:
            value = 0.55
        return max(0.2, min(0.9, value))

    @staticmethod
    def _resolve_max_search_terms() -> int:
        raw = os.getenv("BR_KG_MULTIHOP_MAX_SEARCH_TERMS", "6")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 6
        return max(2, min(12, value))

    @staticmethod
    def _resolve_max_seed_entities(relation_question: bool) -> int:
        raw = os.getenv(
            "BR_KG_MULTIHOP_MAX_SEED_ENTITIES_REL" if relation_question else "BR_KG_MULTIHOP_MAX_SEED_ENTITIES",
            "2" if relation_question else "6",
        )
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 2 if relation_question else 6
        return max(2, min(10, value))

    @staticmethod
    def _seed_stage_timeout_s(remaining_budget_s: float) -> float | None:
        try:
            remaining = float(remaining_budget_s)
        except (TypeError, ValueError):
            return None
        if remaining <= 0:
            return None
        # Keep each seed-stage query bounded and leave a small headroom for loop
        # bookkeeping so a single DB call doesn't consume the whole budget.
        return max(0.25, min(3.0, max(0.25, remaining - 0.35)))

    @staticmethod
    def _normalize_doi(value: str) -> str:
        doi = (value or "").strip().lower()
        doi = re.sub(r"^doi:\s*", "", doi)
        doi = re.sub(r"\s+", "", doi)
        doi = doi.strip(" \t\r\n'\"")
        doi = doi.rstrip(".,;:)]}")
        doi = doi.lstrip("([{")
        return doi

    @classmethod
    def _id_variants(cls, text: str) -> list[str]:
        raw = (text or "").strip()
        if not raw:
            return []
        variants: list[str] = []
        seen: set[str] = set()

        def _add(item: str | None) -> None:
            if not item:
                return
            normalized = item.strip()
            if not normalized:
                return
            key = normalized.lower()
            if key in seen:
                return
            seen.add(key)
            variants.append(normalized)

        lowered = raw.lower()
        compact = re.sub(r"\s+", "", lowered)
        _add(raw)
        _add(lowered)
        # Avoid compacting long natural-language phrases into low-signal tokens
        # like "whatlinksworkingmemory...", which creates expensive misses.
        looks_like_identifier = bool(
            _PMID_ONLY_RE.match(raw)
            or _DOI_ONLY_RE.match(raw)
            or (":" in raw)
            or raw.isdigit()
            or (" " not in raw and len(raw) <= 40)
        )
        if looks_like_identifier:
            _add(compact)

        pmid_match = _PMID_ONLY_RE.match(raw)
        pmid = pmid_match.group(1) if pmid_match else None
        if pmid is None and compact.startswith("pmid:"):
            maybe = compact.split(":", 1)[1]
            if maybe.isdigit():
                pmid = maybe
        if pmid:
            _add(pmid)
            _add(f"pmid:{pmid}")

        doi_match = _DOI_ONLY_RE.match(raw)
        doi = cls._normalize_doi(doi_match.group(1)) if doi_match else None
        if doi is None and compact.startswith("doi:"):
            doi = cls._normalize_doi(compact.split(":", 1)[1])
        if doi is None:
            any_match = _DOI_ANY_RE.search(compact)
            if any_match and len(compact) <= len(any_match.group(0)) + 6:
                doi = cls._normalize_doi(any_match.group(0))
        if doi:
            _add(doi)
            _add(f"doi:{doi}")

        return variants

    @staticmethod
    def _slug_seed_text(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
        slug = slug.strip("-")
        return slug or "seed"

    @staticmethod
    def _normalize_seed_phrase(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_:/\.\-\s]", " ", str(value or ""))
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\r\n-_,:;")
        if not cleaned:
            return ""

        tokens = cleaned.split()
        while tokens and (
            tokens[0].lower() in _SEED_BOUNDARY_STOPWORDS
            or tokens[0].lower() in _SEED_NOISE_TERMS
        ):
            tokens.pop(0)
        while tokens and (
            tokens[-1].lower() in _SEED_BOUNDARY_STOPWORDS
            or tokens[-1].lower() in _SEED_NOISE_TERMS
        ):
            tokens.pop()
        if not tokens:
            return ""

        if len(tokens) > 2:
            for idx, token in enumerate(tokens):
                if idx >= 2 and token.lower() in _SEED_CONTEXT_BREAK_TOKENS:
                    tokens = tokens[:idx]
                    break

        if not tokens:
            return ""
        if len(tokens) > 8:
            tokens = tokens[:8]

        phrase = " ".join(tokens).strip()
        if not phrase:
            return ""
        if phrase.lower() in _SEED_NOISE_TERMS:
            return ""
        return phrase

    @staticmethod
    def _extract_search_terms(question: str) -> list[str]:
        text = (question or "").strip()
        if not text:
            return []

        terms: list[str] = []
        seen: set[str] = set()

        def _add_term(term: str | None) -> None:
            if not term:
                return
            normalized = KGMultihopQATool._normalize_seed_phrase(term)
            if len(normalized) < 2:
                return
            if len(normalized) > 80:
                return
            key = normalized.lower()
            if key in seen:
                return
            seen.add(key)
            terms.append(normalized)

        # Highest precision first: explicit full-query identifiers only.
        if _PMID_ONLY_RE.match(text) or _DOI_ONLY_RE.match(text):
            for variant in KGMultihopQATool._id_variants(text):
                _add_term(variant)
        for doi_match in _DOI_ANY_RE.findall(text):
            doi = KGMultihopQATool._normalize_doi(doi_match)
            if doi:
                _add_term(doi)
                _add_term(f"doi:{doi}")
        for pmid_match in _PMID_ANY_RE.findall(text):
            pmid = (pmid_match or "").strip()
            if pmid:
                _add_term(pmid)
                _add_term(f"pmid:{pmid}")

        # Quoted mentions are typically high precision.
        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
        for grp in quoted:
            phrase = (grp[0] or grp[1] or "").strip()
            _add_term(phrase)
            for variant in KGMultihopQATool._id_variants(phrase):
                _add_term(variant)

        # Relation-style prompts ("links A to B") often expose two entity mentions.
        for match in _SEED_RELATION_PAIR_RE.finditer(text):
            left = KGMultihopQATool._normalize_seed_phrase(match.group(1))
            right = KGMultihopQATool._normalize_seed_phrase(match.group(2))
            _add_term(left)
            _add_term(right)

        # Remaining short clauses without combinatorial n-gram expansion.
        chunks = _SEED_SPLIT_RE.split(text)
        for chunk in chunks:
            cleaned = KGMultihopQATool._normalize_seed_phrase(chunk)
            if not cleaned:
                continue
            _add_term(cleaned)

        # Keep a small high-precision list for lookup latency control.
        return terms[: KGMultihopQATool._resolve_max_search_terms()]

    def _augment_seed_terms_with_runtime_mapping(
        self,
        *,
        search_terms: list[str],
    ) -> tuple[list[str], dict[str, Any] | None]:
        if not self._runtime_mode_enabled(self.runtime_seed_mapper_mode):
            return search_terms, None

        mapper = self._resolve_runtime_mapper()
        if mapper is None:
            return search_terms, {
                "enabled": True,
                "available": False,
                "mode": self.runtime_seed_mapper_mode,
                "init_error": "runtime_mapper_unavailable",
            }

        runtime_terms: list[str] = []
        mapped_count = 0
        checked_count = 0
        max_checks = 6

        try:
            for term in search_terms:
                if checked_count >= max_checks:
                    break
                if not term or len(term) > 120:
                    continue
                checked_count += 1
                mapping = mapper.map_text(
                    term,
                    source_id=f"seed:{self._slug_seed_text(term)}",
                )
                if mapping.status != "mapped":
                    continue
                mapped_count += 1
                for candidate in (mapping.onvoc_label, mapping.onvoc_id):
                    normalized = self._normalize_seed_phrase(str(candidate or ""))
                    if normalized:
                        runtime_terms.append(normalized)
        except Exception as exc:
            return search_terms, {
                "enabled": True,
                "available": False,
                "mode": self.runtime_seed_mapper_mode,
                "runtime_error": str(exc),
            }

        merged: list[str] = []
        seen: set[str] = set()
        for term in runtime_terms + search_terms:
            key = str(term).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(str(term).strip())

        return merged[:10], {
            "enabled": True,
            "available": True,
            "mode": self.runtime_seed_mapper_mode,
            "mapped_terms": mapped_count,
            "checked_terms": checked_count,
            "added_terms": max(0, len(merged) - len(search_terms)),
        }

    @staticmethod
    def _seed_from_node(node: Any) -> dict[str, Any]:
        return {
            "kg_id": node.kg_id,
            "label": node.label,
            "node_type": node.node_type,
            "score": float(node.score),
            "element_id": node.element_id,
        }

    @staticmethod
    def _node_label(node: dict[str, Any]) -> str:
        for key in ("label", "name", "id", "concept_id", "task_id", "region_id", "kg_id"):
            value = node.get(key)
            if value:
                return str(value)
        return "unknown"

    @classmethod
    def _format_path_preview(cls, path: dict[str, Any]) -> str:
        labels = [
            cls._node_label(node)
            for node in (path.get("nodes") or [])
            if isinstance(node, dict)
        ]
        labels = [label for label in labels if label][:5]
        if len(labels) >= 2:
            return " -> ".join(labels)
        if labels:
            return labels[0]
        return "path details unavailable"

    @classmethod
    def _compose_answer(
        cls,
        *,
        question: str,
        max_hops: int,
        seed_entities: list[dict[str, Any]],
        paths: list[dict[str, Any]],
    ) -> str:
        if not seed_entities:
            return (
                "No matching seed entities were found in BR-KG for the "
                f"question: '{question}'."
            )
        if not paths:
            return (
                f"Identified {len(seed_entities)} seed entities, but no connecting "
                f"paths were found within {max_hops} hops."
            )

        shortest = min(
            (
                int(path.get("path_length", 0))
                for path in paths
                if isinstance(path.get("path_length"), int | float)
            ),
            default=0,
        )
        seed_labels = ", ".join(entity["label"] for entity in seed_entities[:3] if entity.get("label"))
        if not seed_labels:
            seed_labels = ", ".join(entity["kg_id"] for entity in seed_entities[:3])
        preview = cls._format_path_preview(paths[0])
        return (
            f"Found {len(paths)} path(s) within {max_hops} hops around "
            f"{seed_labels}; shortest path length is {shortest}. "
            f"Example path: {preview}."
        )

    @staticmethod
    def _estimate_confidence(
        *,
        seed_entities: list[dict[str, Any]],
        paths: list[dict[str, Any]],
        max_hops: int,
        max_results: int,
    ) -> float:
        if not seed_entities:
            return 0.0
        if not paths:
            return 0.2

        avg_len = 0.0
        valid_lengths = [
            float(path.get("path_length"))
            for path in paths
            if isinstance(path.get("path_length"), int | float)
        ]
        if valid_lengths:
            avg_len = sum(valid_lengths) / len(valid_lengths)

        path_density = min(1.0, len(paths) / max(1, max_results))
        depth_score = 1.0
        if avg_len > 0:
            depth_score = max(0.0, 1.0 - (avg_len - 1.0) / max(1, max_hops))
        seed_score = min(1.0, len(seed_entities) / 3.0)

        confidence = 0.35 + 0.35 * path_density + 0.2 * depth_score + 0.1 * seed_score
        return round(max(0.0, min(1.0, confidence)), 2)

    @staticmethod
    def _build_provenance(
        *,
        search_terms: list[str],
        seed_hits_by_term: list[dict[str, Any]],
        traversal_provenance: Any,
        runtime_seed_mapper: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        provenance: list[dict[str, Any]] = [
            {
                "stage": "seed_search",
                "search_terms": search_terms,
                "seed_hits_by_term": seed_hits_by_term,
            }
        ]
        if isinstance(runtime_seed_mapper, dict):
            provenance[0]["runtime_seed_mapper"] = runtime_seed_mapper
        if isinstance(traversal_provenance, list):
            for entry in traversal_provenance:
                if not isinstance(entry, dict):
                    continue
                payload = {"stage": "traversal"}
                payload.update(entry)
                provenance.append(payload)
        return provenance

    @staticmethod
    def _resolve_completion_state(
        *,
        degraded: bool,
        completion_state: str | None,
    ) -> str:
        state = str(completion_state or "").strip().lower()
        if state not in {"complete", "partial", "degraded"}:
            state = "degraded" if degraded else "complete"
        if degraded:
            return "degraded"
        if state == "degraded":
            return "complete"
        return state

    @staticmethod
    def _build_summary(
        *,
        question: str,
        max_hops: int,
        hops_used: int,
        n_seed_entities: int,
        n_paths: int,
        n_nodes_traversed: int,
        n_edges_traversed: int,
        query_time_s: float,
        mode: str,
        degraded: bool = False,
        degraded_reason: str | None = None,
        runtime_budget_s: float | None = None,
        runtime_elapsed_s: float | None = None,
        seed_extract_ms: float = 0.0,
        seed_lookup_ms: float = 0.0,
        traversal_ms: float = 0.0,
        fallback_ms: float = 0.0,
        completion_state: str | None = None,
        degraded_stage: str | None = None,
    ) -> dict[str, Any]:
        resolved_completion_state = KGMultihopQATool._resolve_completion_state(
            degraded=degraded,
            completion_state=completion_state,
        )
        summary = {
            "question": question,
            "max_hops": max_hops,
            "hops_used": hops_used,
            "n_seed_entities": n_seed_entities,
            "n_paths": n_paths,
            "n_nodes_traversed": n_nodes_traversed,
            "n_edges_traversed": n_edges_traversed,
            "query_time_s": query_time_s,
            "reasoning_method": "kg_multi_hop_traversal",
            "mode": mode,
            "degraded": degraded,
            "completion_state": resolved_completion_state,
            "seed_extract_ms": round(float(seed_extract_ms), 3),
            "seed_lookup_ms": round(float(seed_lookup_ms), 3),
            "traversal_ms": round(float(traversal_ms), 3),
            "fallback_ms": round(float(fallback_ms), 3),
        }
        if degraded_reason:
            summary["degraded_reason"] = degraded_reason
        stage = str(degraded_stage or "").strip()
        if (
            not stage
            and degraded_reason
            and isinstance(degraded_reason, str)
            and ":" in degraded_reason
        ):
            stage = degraded_reason.split(":", 1)[1].strip()
        if resolved_completion_state == "degraded" and stage:
            summary["degraded_stage"] = stage
        if runtime_budget_s is not None:
            summary["runtime_budget_s"] = round(float(runtime_budget_s), 3)
        if runtime_elapsed_s is not None:
            summary["runtime_elapsed_s"] = round(float(runtime_elapsed_s), 3)
        return summary

    @staticmethod
    def _build_data_payload(
        *,
        answer: str,
        seed_entities: list[dict[str, Any]],
        paths: list[dict[str, Any]],
        subgraph: dict[str, Any],
        provenance: list[dict[str, Any]],
        confidence: float,
        warnings: list[str],
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "answer": answer,
            "seed_entities": seed_entities,
            "paths": paths,
            "subgraph": subgraph,
            "provenance": provenance,
            "confidence": confidence,
            "warnings": warnings,
            "summary": summary,
        }
        # Backward-compatibility mirror for older `data.outputs.*` readers.
        payload["outputs"] = {
            "answer": answer,
            "seed_entities": seed_entities,
            "paths": paths,
            "subgraph": subgraph,
            "provenance": provenance,
            "confidence": confidence,
            "warnings": warnings,
            "summary": summary,
        }
        return payload

    def _run(self, **kwargs) -> ToolResult:
        """Execute multi-hop QA using in-process query_service traversal."""

        try:
            args = KGMultihopQAArgs(**kwargs)
        except Exception as exc:
            return ToolResult(status="error", error=f"Invalid arguments: {exc}")

        warnings: list[str] = []
        max_hops = int(args.max_hops)
        if max_hops < 1 or max_hops > 5:
            return ToolResult(
                status="error",
                error="max_hops must be between 1 and 5",
            )

        max_results = int(args.max_results)
        if max_results < 1 or max_results > 500:
            clamped_results = min(500, max(1, max_results))
            warnings.append(
                f"max_results={max_results} is out of range; using {clamped_results}"
            )
            max_results = clamped_results

        runtime_budget_s = self._resolve_runtime_budget_s()
        min_traversal_window_s = self._resolve_min_traversal_window_s()
        relation_question = bool(
            re.search(
                r"\b(connect|connection|between|path|relationship|relate|links?)\b",
                args.question.lower(),
            )
        )
        max_seed_entities = self._resolve_max_seed_entities(relation_question)
        seed_budget_ratio = self._resolve_seed_budget_ratio()
        started_at = time.monotonic()
        deadline = started_at + runtime_budget_s
        seed_stage_deadline = max(
            started_at + 0.25,
            min(
                deadline - min_traversal_window_s,
                started_at + (runtime_budget_s * seed_budget_ratio),
            ),
        )
        budget_exhausted = False
        degraded_reason: str | None = None
        seed_extract_ms = 0.0
        seed_lookup_ms = 0.0
        traversal_ms = 0.0
        fallback_ms = 0.0
        runtime_seed_mapper_meta: dict[str, Any] | None = None

        def _remaining_budget_s() -> float:
            return deadline - time.monotonic()

        def _remaining_seed_stage_budget_s() -> float:
            return seed_stage_deadline - time.monotonic()

        def _mark_budget_exhausted(stage: str, *, message: str | None = None) -> None:
            nonlocal budget_exhausted, degraded_reason
            if budget_exhausted:
                return
            budget_exhausted = True
            degraded_reason = f"runtime_budget_exhausted:{stage}"
            elapsed_s = max(0.0, time.monotonic() - started_at)
            if message:
                warnings.append(message)
            else:
                warnings.append(
                    "Runtime budget exhausted at stage="
                    f"'{stage}' after {elapsed_s:.2f}s (budget={runtime_budget_s:.2f}s); "
                    "returning degraded response"
                )

        seed_entities: list[dict[str, Any]] = []
        seed_hits_by_term: list[dict[str, Any]] = []
        seen_seed_ids: set[str] = set()

        seed_extract_started = time.monotonic()
        search_terms = self._extract_search_terms(args.question)
        search_terms, runtime_seed_mapper_meta = self._augment_seed_terms_with_runtime_mapping(
            search_terms=search_terms
        )
        seed_extract_ms = (time.monotonic() - seed_extract_started) * 1000.0

        seed_budget_reached = False

        seed_lookup_started = time.monotonic()
        for term in search_terms:
            if len(seed_entities) >= max_seed_entities:
                break
            if _remaining_budget_s() <= 0:
                _mark_budget_exhausted("seed_search")
                break
            if _remaining_seed_stage_budget_s() <= 0:
                seed_budget_reached = True
                break
            direct_hit_count = 0
            for candidate in self._id_variants(term):
                remaining_s = min(_remaining_budget_s(), _remaining_seed_stage_budget_s())
                if remaining_s <= 0:
                    if _remaining_budget_s() <= 0:
                        _mark_budget_exhausted("seed_node_lookup")
                    else:
                        seed_budget_reached = True
                    break
                seed_timeout_s = self._seed_stage_timeout_s(remaining_s)
                if seed_timeout_s is None:
                    if _remaining_budget_s() <= 0:
                        _mark_budget_exhausted("seed_node_lookup")
                    else:
                        seed_budget_reached = True
                    break
                try:
                    direct_node = self.query_service.node_details(
                        candidate,
                        timeout_s=seed_timeout_s,
                    )
                except Exception:
                    direct_node = None
                if direct_node is None or not direct_node.kg_id:
                    continue
                if direct_node.kg_id in seen_seed_ids:
                    continue
                seed_entities.append(self._seed_from_node(direct_node))
                seen_seed_ids.add(direct_node.kg_id)
                direct_hit_count += 1
                if len(seed_entities) >= max_seed_entities:
                    break
            if seed_budget_reached or len(seed_entities) >= max_seed_entities:
                seed_hits_by_term.append(
                    {
                        "term": term,
                        "direct_hits": direct_hit_count,
                        "search_hits": 0,
                    }
                )
                break

            remaining_s = min(_remaining_budget_s(), _remaining_seed_stage_budget_s())
            if remaining_s <= 0:
                if _remaining_budget_s() <= 0:
                    _mark_budget_exhausted("seed_text_search")
                else:
                    seed_budget_reached = True
                break
            seed_timeout_s = self._seed_stage_timeout_s(remaining_s)
            if seed_timeout_s is None:
                if _remaining_budget_s() <= 0:
                    _mark_budget_exhausted("seed_text_search")
                else:
                    seed_budget_reached = True
                break
            try:
                hits = self.query_service.search_nodes(
                    term,
                    limit=6,
                    timeout_s=seed_timeout_s,
                )
            except Exception as exc:
                warnings.append(f"Seed search failed for '{term}': {exc}")
                continue

            search_hit_count = 0
            for hit in hits:
                if not hit.kg_id or hit.kg_id in seen_seed_ids:
                    continue
                seed_entities.append(self._seed_from_node(hit))
                seen_seed_ids.add(hit.kg_id)
                search_hit_count += 1
                if len(seed_entities) >= max_seed_entities:
                    break
            seed_hits_by_term.append(
                {
                    "term": term,
                    "direct_hits": direct_hit_count,
                    "search_hits": search_hit_count,
                }
            )
            if len(seed_entities) >= max_seed_entities:
                break
        seed_lookup_ms = (time.monotonic() - seed_lookup_started) * 1000.0
        if seed_budget_reached and not budget_exhausted:
            warnings.append(
                "Seed lookup budget reached; proceeding with collected seed entities"
            )

        if not seed_entities:
            runtime_elapsed_s = max(0.0, time.monotonic() - started_at)
            summary = self._build_summary(
                question=args.question,
                max_hops=max_hops,
                hops_used=0,
                n_seed_entities=0,
                n_paths=0,
                n_nodes_traversed=0,
                n_edges_traversed=0,
                query_time_s=0.0,
                mode=args.mode,
                degraded=budget_exhausted,
                degraded_reason=degraded_reason,
                runtime_budget_s=runtime_budget_s,
                runtime_elapsed_s=runtime_elapsed_s,
                seed_extract_ms=seed_extract_ms,
                seed_lookup_ms=seed_lookup_ms,
                traversal_ms=traversal_ms,
                fallback_ms=fallback_ms,
            )
            provenance = self._build_provenance(
                search_terms=search_terms,
                seed_hits_by_term=seed_hits_by_term,
                traversal_provenance=[],
                runtime_seed_mapper=runtime_seed_mapper_meta,
            )
            payload = self._build_data_payload(
                answer=self._compose_answer(
                    question=args.question,
                    max_hops=max_hops,
                    seed_entities=[],
                    paths=[],
                ),
                seed_entities=[],
                paths=[],
                subgraph={"nodes": [], "edges": []},
                provenance=provenance,
                confidence=0.0,
                warnings=warnings,
                summary=summary,
            )
            if budget_exhausted:
                return ToolResult(status="success", data=payload)
            return ToolResult(
                status="error",
                error="No seed entities found for the provided question",
                data=payload,
            )

        start_kg_ids: list[str] = []
        target_kg_id = None
        if seed_entities:
            if relation_question and len(seed_entities) >= 2:
                start_kg_ids = [seed_entities[0]["kg_id"]]
                target_kg_id = seed_entities[1]["kg_id"]
            else:
                start_kg_ids = [seed["kg_id"] for seed in seed_entities[:3]]

        traversal: dict[str, Any] = {
            "paths": [],
            "subgraph": {"nodes": [], "edges": []},
            "provenance": [],
            "statistics": {"execution_time_ms": 0.0},
            "warnings": [],
            "mode": args.mode,
            "error": None,
        }
        fallback_used = False

        if start_kg_ids:
            remaining_s = _remaining_budget_s()
            if remaining_s <= min_traversal_window_s:
                _mark_budget_exhausted(
                    "pre_traversal",
                    message=(
                        "Skipping traversal because remaining runtime budget is "
                        f"{max(0.0, remaining_s):.2f}s (minimum={min_traversal_window_s:.2f}s)"
                    ),
                )
                traversal["error"] = "runtime_budget_exhausted_before_traversal"
            else:
                traversal_started = time.monotonic()
                try:
                    traversal = self.query_service.multi_hop_traverse(
                        start_kg_ids,
                        max_hops=max_hops,
                        allowed_edge_types=args.allowed_edge_types,
                        target_kg_id=target_kg_id,
                        mode=args.mode,
                        max_results=max_results,
                    )
                except Exception as exc:
                    warnings.append(f"Traversal execution failed: {exc}")
                traversal_ms = (time.monotonic() - traversal_started) * 1000.0
        else:
            warnings.append("No seed entities selected for traversal")

        traversal_warnings = traversal.get("warnings") or []
        warnings.extend(str(w) for w in traversal_warnings if w)
        if any("budget exhausted" in str(w).lower() for w in traversal_warnings):
            _mark_budget_exhausted("traversal_budget")
        if traversal.get("error"):
            warnings.append(f"Traversal error: {traversal['error']}")

        paths = traversal.get("paths") or []
        full_subgraph = traversal.get("subgraph") or {"nodes": [], "edges": []}

        if not paths and start_kg_ids and not budget_exhausted:
            fallback_started = time.monotonic()
            fallback_nodes: dict[str, dict[str, Any]] = {}
            fallback_edges: list[dict[str, Any]] = []
            fallback_paths: list[dict[str, Any]] = []
            for seed in seed_entities[: len(start_kg_ids)]:
                if _remaining_budget_s() <= 0:
                    _mark_budget_exhausted("neighbor_fallback")
                    break
                seed_id = seed["kg_id"]
                fallback_nodes.setdefault(seed_id, dict(seed))
                try:
                    nbrs = self.query_service.neighbors(seed_id, limit=max_results)
                except Exception as exc:
                    warnings.append(f"Neighbor fallback failed for '{seed_id}': {exc}")
                    continue
                for nbr in nbrs:
                    nbr_id = str(nbr.get("kg_id") or "").strip()
                    if not nbr_id:
                        continue
                    fallback_nodes.setdefault(
                        nbr_id,
                        {
                            "kg_id": nbr_id,
                            "label": nbr.get("label"),
                            "node_type": nbr.get("node_type"),
                            "score": nbr.get("score", 1.0),
                        },
                    )
                    relation = str(nbr.get("relation") or "RELATED_TO")
                    fallback_edges.append(
                        {
                            "source": seed_id,
                            "target": nbr_id,
                            "type": relation,
                            "properties": nbr.get("properties") or {},
                        }
                    )
                    fallback_paths.append(
                        {
                            "nodes": [dict(seed), fallback_nodes[nbr_id]],
                            "edges": [{"type": relation}],
                            "path_length": 1,
                            "start_node_id": seed_id,
                            "end_node_id": nbr_id,
                        }
                    )
            if fallback_paths:
                paths = fallback_paths[:max_results]
                full_subgraph = {
                    "nodes": list(fallback_nodes.values()),
                    "edges": fallback_edges[:max_results],
                }
                warnings.append("Used neighbors fallback because multi-hop traversal returned no paths")
                fallback_used = True
            fallback_ms = (time.monotonic() - fallback_started) * 1000.0
        elif not paths and budget_exhausted:
            warnings.append("Skipped neighbors fallback because runtime budget was exhausted")

        subgraph = full_subgraph if args.return_subgraph else {"nodes": [], "edges": []}
        if not args.return_subgraph:
            warnings.append("Subgraph omitted because return_subgraph=False")

        stats = traversal.get("statistics") or {}
        hops_used = max(
            (
                int(path.get("path_length", 0))
                for path in paths
                if isinstance(path.get("path_length"), int | float)
            ),
            default=0,
        )
        n_nodes = len(subgraph.get("nodes", []))
        n_edges = len(subgraph.get("edges", []))
        if not args.return_subgraph:
            n_nodes = int(stats.get("n_unique_nodes", 0) or 0)
            n_edges = int(stats.get("n_unique_edges", 0) or 0)

        runtime_elapsed_s = max(0.0, time.monotonic() - started_at)
        traversal_error = str(traversal.get("error") or "").strip()
        completion_state = "degraded"
        if not budget_exhausted:
            completion_state = (
                "partial" if (fallback_used or bool(traversal_error)) else "complete"
            )
        degraded_stage = (
            degraded_reason.split(":", 1)[1].strip()
            if degraded_reason and ":" in degraded_reason
            else None
        )
        summary = self._build_summary(
            question=args.question,
            max_hops=max_hops,
            hops_used=hops_used,
            n_seed_entities=len(seed_entities),
            n_paths=len(paths),
            n_nodes_traversed=n_nodes,
            n_edges_traversed=n_edges,
            query_time_s=round(float(stats.get("execution_time_ms", 0.0)) / 1000.0, 3),
            mode=str(traversal.get("mode", args.mode)),
            degraded=budget_exhausted,
            degraded_reason=degraded_reason,
            runtime_budget_s=runtime_budget_s,
            runtime_elapsed_s=runtime_elapsed_s,
            seed_extract_ms=seed_extract_ms,
            seed_lookup_ms=seed_lookup_ms,
            traversal_ms=traversal_ms,
            fallback_ms=fallback_ms,
            completion_state=completion_state,
            degraded_stage=degraded_stage,
        )
        provenance = self._build_provenance(
            search_terms=search_terms,
            seed_hits_by_term=seed_hits_by_term,
            traversal_provenance=traversal.get("provenance") or [],
            runtime_seed_mapper=runtime_seed_mapper_meta,
        )
        answer = self._compose_answer(
            question=args.question,
            max_hops=max_hops,
            seed_entities=seed_entities,
            paths=paths,
        )
        confidence = self._estimate_confidence(
            seed_entities=seed_entities,
            paths=paths,
            max_hops=max_hops,
            max_results=max_results,
        )
        payload = self._build_data_payload(
            answer=answer,
            seed_entities=seed_entities,
            paths=paths,
            subgraph=subgraph,
            provenance=provenance,
            confidence=confidence,
            warnings=warnings,
            summary=summary,
        )

        if not paths:
            traversal_error = traversal.get("error")
            error = "No connecting paths found for the provided question"
            if traversal_error:
                error = f"{error}; traversal error: {traversal_error}"
            if budget_exhausted:
                return ToolResult(status="success", data=payload)
            return ToolResult(status="error", error=error, data=payload)

        return ToolResult(status="success", data=payload)


class KGMultihopQATools:
    """Factory class for multi-hop QA tools."""

    @staticmethod
    def get_kg_multihop_qa() -> KGMultihopQATool:
        """Get multi-hop QA tool instance."""
        return KGMultihopQATool()
