"""Unified KG-driven tool planner used by both chat and contract planning.

This module centralizes tool candidate generation + scoring so that:
- Chat tool binding (/api/chat via NeuroAgentLLM) and
- Contract planning (/agent/plan in catalog mode)
use the same planner output and priors.

The planner integrates:
- Catalog scoring (selection.py) for explainable, deterministic ranking
- Optional KG retrieval (ToolRetriever) as a soft prior/boost
- Optional run-derived evidence prior (Neo4j) as a soft prior/boost
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from brain_researcher.core.contracts import (
    Violation,
    build_cross_stage_context,
    parse_loop_signals,
)
from brain_researcher.services.agent.monitoring import metrics_collector
from brain_researcher.services.agent.planner.capability_predictor import (
    CapabilityPrediction,
    predict_capabilities,
    score_tool_capability_match,
)
from brain_researcher.services.agent.planner.catalog_loader import get_tool_by_id
from brain_researcher.services.agent.planner.evidence import (
    ToolEvidenceReader,
    ToolEvidenceStats,
)
from brain_researcher.services.agent.planner.evidence_neo4j import (
    get_default_evidence_store,
)
from brain_researcher.services.agent.planner.kg_bridge import (
    get_failed_on_stats,
    resolve_dataset_id,
)
from brain_researcher.services.agent.planner.prior_config import load_prior_config
from brain_researcher.services.agent.planner.selection import (
    SelectionCandidate,
    load_hierarchical_config,
    select_tools,
)
from brain_researcher.services.agent.planner.synonyms_loader import match_intents
from brain_researcher.services.agent.resources.behavior_policies import (
    load_behavior_policies,
)
from brain_researcher.services.agent.tool_retriever import ToolRetriever
from brain_researcher.services.shared.planner.models import normalize_modality
from brain_researcher.services.tools.catalog_loader import (
    resolve_primary_runtime_tool_id,
)

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_GENERIC_QUERY_VERBS = {
    "run",
    "perform",
    "apply",
    "execute",
    "do",
    "compute",
}
_GENERIC_TOOL_TOKENS = {
    "visualization",
    "plot",
    "report",
    "generic",
    "statistical",
    "inference",
    "advanced",
    "analysis",
}
_INTENT_TOKEN_STOP = {
    "run",
    "tool",
    "analysis",
    "pipeline",
    "workflow",
    "python",
    "container",
    "mcp",
    "fmri",
    "mri",
}
_DOMAIN_TOOL_HINTS: dict[str, set[str]] = {
    "preprocessing": {
        "preprocessing",
        "motion",
        "registration",
        "segmentation",
        "slice",
        "denois",
        "scrub",
        "bias",
        "fmriprep",
        "volreg",
        "flirt",
    },
    "statistics": {
        "inference",
        "glm",
        "permutation",
        "anova",
        "regression",
        "clustsim",
        "palm",
        "wilcoxon",
        "mannwhitney",
    },
    "knowledge_graph": {
        "br_kg",
        "knowledge",
        "graph",
        "literature",
        "ontology",
        "neurosynth",
        "meta",
    },
    "workflow": {
        "pipeline",
        "workflow",
        "deep",
        "learning",
        "connectivity",
        "realtime",
        "bids",
    },
}


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(str(text or "").lower()))


def _tool_identity_tokens(tool: Any) -> set[str]:
    vals: list[str] = [
        str(getattr(tool, "id", "") or ""),
        str(getattr(tool, "name", "") or ""),
        str(getattr(tool, "package", "") or ""),
    ]
    for field in ("capabilities", "intents"):
        raw = getattr(tool, field, None) or []
        vals.extend([str(x) for x in raw if x])
    tokens: set[str] = set()
    for val in vals:
        tokens.update(_tokenize(val.replace("_", " ")))
    return tokens


def _resolve_primary_domain(
    prediction: CapabilityPrediction,
    *,
    query: str,
) -> str | None:
    if prediction.domain_signals:
        return str(prediction.domain_signals[0])

    aggregate = " ".join(
        list(prediction.predicted_capabilities or [])
        + list(prediction.predicted_intents or [])
        + [str(query or "")]
    ).lower()
    for domain, hints in _DOMAIN_TOOL_HINTS.items():
        if any(h in aggregate for h in hints):
            return domain
    return None


def _domain_prior_score(tool: Any, *, primary_domain: str | None) -> float:
    if not primary_domain:
        return 0.0
    hints = _DOMAIN_TOOL_HINTS.get(primary_domain)
    if not hints:
        return 0.0
    tokens = _tool_identity_tokens(tool)
    return 1.0 if any(h in tokens for h in hints) else 0.0


def _intent_affinity_score(tool: Any, prediction: CapabilityPrediction) -> float:
    intents = list(prediction.predicted_intents or [])
    if not intents:
        return 0.0
    tokens = _tool_identity_tokens(tool)
    best = 0.0
    for intent in intents:
        intent_tokens = {
            tok
            for tok in _tokenize(str(intent).replace("_", " "))
            if tok and tok not in _INTENT_TOKEN_STOP and len(tok) > 2
        }
        if not intent_tokens:
            continue
        overlap = len(intent_tokens & tokens) / float(len(intent_tokens))
        if overlap > best:
            best = overlap
    return _clamp(best)


def _generic_verb_penalty(
    *,
    query: str,
    tool: Any,
    prediction: CapabilityPrediction,
    capability_match_score: float,
    intent_affinity: float,
) -> float:
    if not (prediction.predicted_capabilities or prediction.predicted_intents):
        return 0.0
    if capability_match_score >= 0.5 or intent_affinity >= 0.5:
        return 0.0
    q_tokens = _tokenize(query)
    if not (_GENERIC_QUERY_VERBS & q_tokens):
        return 0.0
    tool_tokens = _tool_identity_tokens(tool)
    if _GENERIC_TOOL_TOKENS & tool_tokens:
        return 1.0
    return 0.0


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _get_float_env(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_bool_env(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_modality_token_set(value: Any) -> set[str]:
    if value is None:
        return set()
    raw_values = value if isinstance(value, list | tuple | set) else [value]
    modalities: set[str] = set()
    for raw in raw_values:
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            modalities.add(normalize_modality(text))
        except Exception:
            modalities.add(text.lower())
    return modalities


def _tool_modality_token_set(tool: Any) -> set[str]:
    return _normalize_modality_token_set(
        getattr(tool, "modality", None) or getattr(tool, "modalities", None)
    )


def _build_routing_diagnostics(
    *,
    candidates: list[dict[str, Any]],
    chosen_tool_id: str | None,
    started_at: float,
    source_counts: dict[str, int] | None = None,
    trace_limit: int = 15,
) -> dict[str, Any]:
    selected_rank = None
    if chosen_tool_id:
        for idx, row in enumerate(candidates, start=1):
            if row.get("tool_id") == chosen_tool_id:
                selected_rank = idx
                break
    # Additive routing trace (diagnostics-only; no behaviour change): the top-N
    # post-recall candidates with their retrieval score + source, and which one was
    # finally selected. This makes a *downstream override* observable — i.e. when the
    # selected tool is NOT the top-ranked candidate (selected_tool_outranked_by > 0),
    # which is exactly the silent failure class behind the MEG mis-route (a lower
    # candidate / keyword route winning over the embedding-ranked top). It does NOT
    # yet capture tools dropped by upstream gates (exposure/phase/modality) — those
    # never reach `candidates`; instrumenting the retriever/registry filters is a
    # follow-on slice.
    candidate_trace = [
        {
            "rank": idx,
            "tool_id": row.get("tool_id"),
            "score": row.get("score"),
            "source": row.get("source"),
            "selected": row.get("tool_id") == chosen_tool_id,
        }
        for idx, row in enumerate(candidates[:trace_limit], start=1)
    ]
    return {
        "surface": "plan",
        "candidate_count": len(candidates),
        "candidate_source_counts": source_counts or {},
        "selected_tool_id": chosen_tool_id,
        "selected_tool_rank": selected_rank,
        "selected_tool_in_top_5": (selected_rank is not None and selected_rank <= 5),
        "selected_tool_in_top_10": (selected_rank is not None and selected_rank <= 10),
        # 0 when the top-ranked candidate was selected; >0 means a downstream layer
        # overrode the ranking and picked a lower candidate (the override signal).
        "selected_tool_outranked_by": (
            selected_rank - 1 if (selected_rank and selected_rank > 1) else 0
        ),
        "candidate_trace": candidate_trace,
        "routing_latency_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
    }


@dataclass(frozen=True)
class UnifiedPlannerResult:
    """Core planner output used by adapters."""

    candidates: list[dict[str, Any]]
    scores: dict[str, float]
    selection_reasons: list[dict[str, Any]]
    constraints_applied: list[str]
    confidence_score: float
    chosen_tool_id: str | None = None
    intent: list[str] | None = None
    task_family: str | None = None
    kg_families: list[str] | None = None
    mask_reasons: list[Violation] | None = None
    predicted_capabilities: list[str] | None = None
    predicted_intents: list[str] | None = None
    capability_prediction: dict[str, Any] | None = None
    cross_stage_context: dict[str, Any] | None = None
    loop_signals: list[dict[str, Any]] | None = None
    routing_diagnostics: dict[str, Any] | None = None


class UnifiedPlanner:
    def __init__(
        self,
        *,
        tool_retriever: ToolRetriever | None = None,
        evidence_reader: ToolEvidenceReader | None = None,
    ) -> None:
        self._tool_retriever = tool_retriever
        self._evidence_reader = evidence_reader

    @staticmethod
    def _resolve_task_family(
        query: str,
        modality: str | None,
        *,
        predicted_intents: list[str] | None = None,
    ) -> tuple[list[str], str]:
        intents = list(predicted_intents or match_intents(query, modality=modality))
        primary = intents[0] if intents else "unknown"
        return intents, primary

    @staticmethod
    def _canonicalize_tool_id(tool_id: str | None) -> str | None:
        """Rewrite tool ids onto canonical runtime names (best-effort)."""
        if not tool_id:
            return tool_id

        runtime_id = resolve_primary_runtime_tool_id(tool_id)
        if runtime_id:
            return runtime_id

        tool = get_tool_by_id(tool_id)
        if tool is None:
            return tool_id

        tool_id_value = getattr(tool, "id", None)
        if tool_id_value:
            return resolve_primary_runtime_tool_id(str(tool_id_value)) or str(
                tool_id_value
            )

        constraints = getattr(tool, "constraints", None) or {}
        if isinstance(constraints, dict):
            alias_of = constraints.get("alias_of")
            if constraints.get("is_alias") and alias_of:
                alias_of_id = str(alias_of)
                return resolve_primary_runtime_tool_id(alias_of_id) or alias_of_id

        return tool_id

    def plan(
        self,
        *,
        query: str,
        modality: str | None = None,
        query_understanding: Mapping[str, Any] | None = None,
        dataset_id: str | None = None,
        task_family_hint: str | None = None,
        max_candidates: int = 10,
        require_preflight_pass: bool = True,
        environment: str | None = None,
        retriever_max_families: int = 3,
        retriever_top_k: int = 20,
        allowed_tool_ids: set[str] | None = None,
        include_local_first: bool = False,
        allowlist_mode: str | None = None,
    ) -> UnifiedPlannerResult:
        planner_started_at = time.perf_counter()
        capability_prediction: CapabilityPrediction = predict_capabilities(
            query=query,
            modality=modality,
            query_understanding=query_understanding,
        )
        task_intents = (
            capability_prediction.direct_intents
            or capability_prediction.predicted_intents
        )
        intents, task_family = self._resolve_task_family(
            query,
            modality,
            predicted_intents=task_intents,
        )
        if task_family_hint:
            task_family = task_family_hint
        if dataset_id:
            dataset_id = resolve_dataset_id(dataset_id) or dataset_id
        raw_loop_signals = []
        if isinstance(query_understanding, Mapping) and isinstance(
            query_understanding.get("loop_signals"), list
        ):
            raw_loop_signals = list(query_understanding.get("loop_signals") or [])
        parsed_loop_signals = parse_loop_signals(raw_loop_signals)
        cross_stage_context = build_cross_stage_context(
            task_family=task_family,
            dataset_id=dataset_id,
            predicted_intents=list(capability_prediction.predicted_intents or []),
            query_understanding=query_understanding,
            loop_signals=parsed_loop_signals,
        ).model_dump(mode="json", exclude_none=True)
        loop_signals_payload = [
            signal.model_dump(mode="json", exclude_none=True)
            for signal in parsed_loop_signals
        ]
        capability_weight = _clamp(_get_float_env("BR_CAPABILITY_RERANK_WEIGHT", 0.4))
        use_capability_prior = _get_bool_env("BR_PLANNER_USE_CAPABILITY_PRIOR", True)
        effective_capability_weight = (
            _clamp(capability_weight * max(0.0, capability_prediction.confidence))
            if use_capability_prior
            else 0.0
        )
        domain_prior_weight = (
            _clamp(_get_float_env("BR_DOMAIN_PRIOR_WEIGHT", 0.06), 0.0, 0.3)
            if use_capability_prior
            else 0.0
        )
        intent_affinity_weight = (
            _clamp(_get_float_env("BR_INTENT_AFFINITY_WEIGHT", 0.08), 0.0, 0.3)
            if use_capability_prior
            else 0.0
        )
        generic_penalty_weight = (
            _clamp(_get_float_env("BR_GENERIC_VERB_PENALTY", 0.03), 0.0, 0.3)
            if use_capability_prior
            else 0.0
        )
        primary_domain = _resolve_primary_domain(capability_prediction, query=query)
        use_evidence_prior = _get_bool_env("BR_PLANNER_USE_EVIDENCE_PRIOR", True)

        # Load the same hierarchical config used by selection.py so we can report constraints.
        config = load_hierarchical_config(
            modality=modality,
            operator=task_family if task_family != "unknown" else None,
            environment=environment,
        )
        constraints_cfg = (config.get("policy", {}) or {}).get("constraints", {}) or {}
        constraints_applied = [
            f"require_preflight={constraints_cfg.get('require_preflight', True)}",
            f"require_capability_match={constraints_cfg.get('require_capability_match', 'strict')}",
            f"require_container_availability={constraints_cfg.get('require_container_availability', False)}",
        ]
        if not use_capability_prior:
            constraints_applied.append("capability_prior=disabled")
        elif (
            capability_prediction.predicted_capabilities
            or capability_prediction.predicted_intents
        ):
            constraints_applied.append("capability_predictor=online")
            constraints_applied.append(
                f"capability_rerank_weight={effective_capability_weight:.3f}"
            )
            constraints_applied.append(
                f"intent_affinity_weight={intent_affinity_weight:.3f}"
            )
            constraints_applied.append(
                f"generic_verb_penalty={generic_penalty_weight:.3f}"
            )
        if use_capability_prior and primary_domain:
            constraints_applied.append(
                f"domain_prior={primary_domain}:{domain_prior_weight:.3f}"
            )
        if capability_prediction.abstain_reason:
            constraints_applied.append(
                f"capability_abstain={capability_prediction.abstain_reason}"
            )
        if loop_signals_payload:
            constraints_applied.append(f"loop_signals={len(loop_signals_payload)}")
        if not use_evidence_prior:
            constraints_applied.append("evidence_prior=disabled")
        if allowlist_mode:
            constraints_applied.append(f"allowlist_mode={allowlist_mode}")
        constraints_applied.append(
            "allowlist_masking=enabled"
            if allowed_tool_ids is not None
            else "allowlist_masking=disabled"
        )

        # ------------------------------------------------------------------
        # 1) Catalog candidates (deterministic baseline)
        # ------------------------------------------------------------------
        mask_reasons: list[Violation] = []
        base_candidates = select_tools(
            query=query,
            modality=modality,
            max_results=max(10, max_candidates),
            require_preflight_pass=require_preflight_pass,
            environment=environment,
            apply_selection_strategy=False,  # unified planner handles top-k itself
            include_unavailable=True,
            max_unavailable=max(5, max_candidates),
            mask_reasons_out=mask_reasons,
            allowed_tool_ids=allowed_tool_ids,
            include_local_first=include_local_first,
        )

        # NOTE: If the catalog scorer can't produce candidates (e.g., no intent
        # match), we can still fall back to KG retrieval (when available).

        # ------------------------------------------------------------------
        # 2) Optional KG retrieval as a soft prior (boost)
        # ------------------------------------------------------------------
        kg_scores: dict[str, float] = {}
        kg_families: list[str] = []
        if self._tool_retriever is not None:
            try:
                kg_families = self._tool_retriever.select_families_by_query(
                    query, llm=None, max_families=retriever_max_families
                )
                if kg_families:
                    kg_tools = self._tool_retriever.retrieve_tools(
                        query=query,
                        family_ids=kg_families,
                        top_k=retriever_top_k,
                    )
                    allowed_lookup = None
                    if allowed_tool_ids is not None:
                        allowed_lookup = {
                            str(tool_id).strip()
                            for tool_id in allowed_tool_ids
                            if str(tool_id).strip()
                        }
                    raw: dict[str, float] = {}
                    for tool in kg_tools:
                        tool_id = getattr(tool, "id", None)
                        if not tool_id:
                            continue
                        canonical_tool_id = self._canonicalize_tool_id(str(tool_id))
                        if not canonical_tool_id:
                            continue
                        if (
                            allowed_lookup is not None
                            and canonical_tool_id not in allowed_lookup
                        ):
                            continue
                        raw[canonical_tool_id] = float(tool.score)
                    if raw:
                        m = max(raw.values()) or 1.0
                        kg_scores = {k: _clamp(v / m) for k, v in raw.items()}
                        constraints_applied.append(
                            f"kg_families={','.join(kg_families)}"
                        )
            except Exception as exc:  # pragma: no cover - best-effort
                logger.debug("KG tool retrieval unavailable: %s", exc)

        if not base_candidates:
            # KG-only fallback: map KG tool ids into catalog tools (best-effort)
            if not kg_scores:
                routing_diagnostics = _build_routing_diagnostics(
                    candidates=[],
                    chosen_tool_id=None,
                    started_at=planner_started_at,
                )
                routing_diagnostics["allowlist_mode"] = allowlist_mode or "curated"
                routing_diagnostics["allowlist_masking"] = allowed_tool_ids is not None
                metrics_collector.record_tool_routing(
                    surface="plan",
                    candidate_count=routing_diagnostics["candidate_count"],
                    selected_rank=routing_diagnostics["selected_tool_rank"],
                    routing_latency_ms=routing_diagnostics["routing_latency_ms"],
                    top_k_hits={
                        5: bool(routing_diagnostics["selected_tool_in_top_5"]),
                        10: bool(routing_diagnostics["selected_tool_in_top_10"]),
                    },
                )
                return UnifiedPlannerResult(
                    candidates=[],
                    scores={},
                    selection_reasons=[],
                    constraints_applied=constraints_applied,
                    confidence_score=0.0,
                    chosen_tool_id=None,
                    intent=intents,
                    task_family=task_family,
                    kg_families=kg_families or None,
                    predicted_capabilities=capability_prediction.predicted_capabilities
                    or None,
                    predicted_intents=capability_prediction.predicted_intents or None,
                    capability_prediction=capability_prediction.as_dict(),
                    cross_stage_context=cross_stage_context,
                    loop_signals=loop_signals_payload or None,
                    routing_diagnostics=routing_diagnostics,
                )

            evidence_reader = self._evidence_reader or get_default_evidence_store()
            tool_versions: dict[str, str] = {}
            for tid in kg_scores.keys():
                tool = get_tool_by_id(tid)
                if tool is None:
                    continue
                tool_versions[tid] = getattr(tool, "entrypoint", None) or ""
            evidence: dict[str, ToolEvidenceStats] = {}
            if (
                use_evidence_prior
                and evidence_reader is not None
                and task_family
                and task_family != "unknown"
            ):
                try:
                    evidence = evidence_reader.read_stats(
                        tool_versions=tool_versions,
                        task_family=task_family,
                        tool_ids=list(tool_versions.keys()),
                        dataset_id=dataset_id,
                    )
                    if evidence:
                        constraints_applied.append("evidence_prior=enabled")
                    coverage = (
                        len(evidence) / max(1, len(tool_versions))
                        if tool_versions
                        else 0.0
                    )
                    metrics_collector.record("kg_evidence_coverage_total", coverage)
                except Exception as exc:  # pragma: no cover - best-effort
                    logger.debug("Evidence prior unavailable: %s", exc)

            prior_cfg = load_prior_config()
            evidence_weight = _get_float_env(
                "BR_EVIDENCE_PRIOR_WEIGHT",
                prior_cfg["weights"].get("evidence_prior", 0.15),
            )
            kg_weight = _get_float_env(
                "BR_KG_PRIOR_WEIGHT", prior_cfg["weights"].get("kg_prior", 0.05)
            )

            ranked = sorted(kg_scores.items(), key=lambda kv: kv[1], reverse=True)
            requested_modalities = _normalize_modality_token_set(modality)
            if requested_modalities:
                constraints_applied.append(
                    "kg_modality_gate=" + ",".join(sorted(requested_modalities))
                )
            candidates_payload: list[dict[str, Any]] = []
            scores: dict[str, float] = {}
            reasons: list[dict[str, Any]] = []
            rejected_for_modality: list[str] = []
            for tool_id, kg_score in ranked:
                tool = get_tool_by_id(tool_id)
                if tool is None:
                    continue
                tool_modalities = _tool_modality_token_set(tool)
                if (
                    requested_modalities
                    and tool_modalities
                    and not (requested_modalities & tool_modalities)
                ):
                    rejected_for_modality.append(tool_id)
                    continue
                prior = evidence.get(tool_id)
                prior_success = prior.success_rate_smoothed() if prior else None
                prior_latency = prior.latency_score() if prior else None
                prior_penalty = prior.failure_penalty() if prior else None

                score = _clamp(kg_score + kg_weight * kg_score)
                if prior_success is not None:
                    score = _clamp(
                        score
                        + evidence_weight * (prior_success - 0.5)
                        - (prior_penalty or 0.0)
                    )
                capability_match_score, capability_matches = (
                    score_tool_capability_match(tool, capability_prediction)
                )
                if effective_capability_weight > 0.0:
                    score = _clamp(
                        (1.0 - effective_capability_weight) * score
                        + effective_capability_weight * capability_match_score
                    )
                domain_prior_score = _domain_prior_score(
                    tool, primary_domain=primary_domain
                )
                intent_affinity_score = _intent_affinity_score(
                    tool, capability_prediction
                )
                generic_verb_penalty = _generic_verb_penalty(
                    query=query,
                    tool=tool,
                    prediction=capability_prediction,
                    capability_match_score=capability_match_score,
                    intent_affinity=intent_affinity_score,
                )
                score = _clamp(
                    score
                    + domain_prior_weight * domain_prior_score
                    + intent_affinity_weight * intent_affinity_score
                    - generic_penalty_weight * generic_verb_penalty
                )

                candidates_payload.append(
                    {
                        "tool_id": tool.id,
                        "tool_name": tool.name,
                        "final_score": score,
                        "intent_match_score": 0.0,
                        "preflight_passed": True,
                        "preflight_detail": {},
                        "description_score": 0.0,
                        "metadata_score": 0.0,
                        "resource_fit_score": 0.0,
                        "historical_quality_score": (
                            0.5 if prior_success is None else prior_success
                        ),
                        "latency_score": (
                            0.5 if prior_latency is None else prior_latency
                        ),
                        "explanation": "KG candidate (fallback)",
                        "kg_score": float(f"{kg_score:.6f}"),
                        "capability_match_score": float(
                            f"{capability_match_score:.6f}"
                        ),
                        "capability_blend_weight": float(
                            f"{effective_capability_weight:.6f}"
                        ),
                        "domain_prior_score": float(f"{domain_prior_score:.6f}"),
                        "intent_affinity_score": float(f"{intent_affinity_score:.6f}"),
                        "generic_verb_penalty": float(f"{generic_verb_penalty:.6f}"),
                        "capability_matched_labels": capability_matches or None,
                        "prior_success_rate": (
                            None
                            if prior_success is None
                            else float(f"{prior_success:.6f}")
                        ),
                        "prior_latency_score": (
                            None
                            if prior_latency is None
                            else float(f"{prior_latency:.6f}")
                        ),
                        "prior_failure_penalty": (
                            None
                            if prior_penalty is None
                            else float(f"{prior_penalty:.6f}")
                        ),
                        "available": True,
                        "source": "br_kg",
                    }
                )
                scores[tool.id] = score
                reasons.append(
                    {
                        "tool_id": tool.id,
                        "base_score": float(f"{kg_score:.6f}"),
                        "score": float(f"{score:.6f}"),
                        "kg_score": float(f"{kg_score:.6f}"),
                        "capability_match_score": float(
                            f"{capability_match_score:.6f}"
                        ),
                        "capability_blend_weight": float(
                            f"{effective_capability_weight:.6f}"
                        ),
                        "domain_prior_score": float(f"{domain_prior_score:.6f}"),
                        "intent_affinity_score": float(f"{intent_affinity_score:.6f}"),
                        "generic_verb_penalty": float(f"{generic_verb_penalty:.6f}"),
                        "capability_matched_labels": capability_matches or None,
                        "prior_success_rate": (
                            None
                            if prior_success is None
                            else float(f"{prior_success:.6f}")
                        ),
                        "prior_latency_score": (
                            None
                            if prior_latency is None
                            else float(f"{prior_latency:.6f}")
                        ),
                        "prior_failure_penalty": (
                            None
                            if prior_penalty is None
                            else float(f"{prior_penalty:.6f}")
                        ),
                    }
                )
                if len(candidates_payload) >= max_candidates:
                    break
            if rejected_for_modality:
                constraints_applied.append(
                    "kg_modality_rejected="
                    + ",".join(rejected_for_modality[:max_candidates])
                )

            confidence = 0.0
            if candidates_payload:
                top_score = candidates_payload[0]["final_score"]
                second = (
                    candidates_payload[1]["final_score"]
                    if len(candidates_payload) > 1
                    else 0.0
                )
                gap = max(0.0, float(top_score) - float(second))
                confidence = _clamp(0.65 * float(top_score) + 0.35 * gap)

            chosen_tool_id = (
                candidates_payload[0]["tool_id"] if candidates_payload else None
            )
            chosen_tool_id = self._canonicalize_tool_id(chosen_tool_id)
            routing_diagnostics = _build_routing_diagnostics(
                candidates=candidates_payload,
                chosen_tool_id=chosen_tool_id,
                started_at=planner_started_at,
                source_counts=(
                    {
                        "br_kg": len(candidates_payload),
                    }
                    if candidates_payload
                    else {}
                ),
            )
            metrics_collector.record_tool_routing(
                surface="plan",
                candidate_count=routing_diagnostics["candidate_count"],
                selected_rank=routing_diagnostics["selected_tool_rank"],
                routing_latency_ms=routing_diagnostics["routing_latency_ms"],
                top_k_hits={
                    5: bool(routing_diagnostics["selected_tool_in_top_5"]),
                    10: bool(routing_diagnostics["selected_tool_in_top_10"]),
                },
            )
            return UnifiedPlannerResult(
                candidates=candidates_payload,
                scores=scores,
                selection_reasons=reasons,
                constraints_applied=constraints_applied,
                confidence_score=confidence,
                chosen_tool_id=chosen_tool_id,
                intent=intents,
                task_family=task_family,
                kg_families=kg_families or None,
                predicted_capabilities=capability_prediction.predicted_capabilities
                or None,
                predicted_intents=capability_prediction.predicted_intents or None,
                capability_prediction=capability_prediction.as_dict(),
                cross_stage_context=cross_stage_context,
                loop_signals=loop_signals_payload or None,
                routing_diagnostics=routing_diagnostics,
            )

        # ------------------------------------------------------------------
        # 3) Optional evidence prior (success/latency/failure types)
        # ------------------------------------------------------------------
        evidence_reader = self._evidence_reader or get_default_evidence_store()
        evidence: dict[str, ToolEvidenceStats] = {}
        tool_versions: dict[str, str] = {}
        for cand in base_candidates:
            tool_versions[cand.tool.id] = getattr(cand.tool, "entrypoint", None) or ""

        if (
            use_evidence_prior
            and evidence_reader is not None
            and task_family
            and task_family != "unknown"
        ):
            try:
                evidence = evidence_reader.read_stats(
                    tool_versions=tool_versions,
                    task_family=task_family,
                    tool_ids=[c.tool.id for c in base_candidates],
                )
                if evidence:
                    constraints_applied.append("evidence_prior=enabled")
            except Exception as exc:  # pragma: no cover - best-effort
                logger.debug("Evidence prior unavailable: %s", exc)

        # ------------------------------------------------------------------
        # 4) Optional failure prior (FAILED_ON aggregates)
        # ------------------------------------------------------------------
        failure_prior: dict[str, dict[str, Any]] = {}
        use_failure_prior = os.getenv("BR_PLANNER_USE_FAILURE_PRIOR", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if use_failure_prior:
            try:
                failure_prior = get_failed_on_stats(
                    [c.tool.id for c in base_candidates],
                    dataset_id=dataset_id,
                    task_family=task_family if task_family != "unknown" else None,
                )
            except Exception:
                failure_prior = {}

        # ------------------------------------------------------------------
        # 5) Re-score with priors and return rich result
        # ------------------------------------------------------------------
        kg_weight = _get_float_env("BR_KG_PRIOR_WEIGHT", 0.05)

        rescored: list[tuple[float, SelectionCandidate, dict[str, Any]]] = []
        for cand in base_candidates:
            tool_id = cand.tool.id
            weights = cand.scoring_weights

            # Start from the candidate components, but override historical/latency using evidence when available.
            hist = cand.historical_quality_score
            lat = cand.latency_score

            prior = evidence.get(tool_id)
            prior_success = None
            prior_latency_score = None
            prior_penalty = None
            evidence_layer = None
            evidence_n = 0
            if prior is not None:
                prior_success = prior.success_rate_smoothed()
                prior_latency_score = prior.latency_score()
                prior_penalty = prior.failure_penalty()
                evidence_layer = prior.layer_used
                evidence_n = prior.samples_used
                hist = _clamp(prior_success - (prior_penalty or 0.0))
                lat = prior_latency_score

            preflight_score = 1.0 if cand.preflight_passed else 0.0
            base = (
                weights.get("intent_match", 0.3) * cand.intent_match_score
                + weights.get("preflight", 0.0) * preflight_score
                + weights.get("description", 0.2) * cand.description_score
                + weights.get("metadata", 0.1) * cand.metadata_score
                + weights.get("resource_fit", 0.15) * cand.resource_fit_score
                + weights.get("historical_quality", 0.15) * hist
                + weights.get("latency_pred", 0.1) * lat
            )
            base = _clamp(base)

            kg_boost = kg_weight * kg_scores.get(tool_id, 0.0)
            score = _clamp(base + kg_boost)
            capability_match_score, capability_matches = score_tool_capability_match(
                cand.tool, capability_prediction
            )
            if effective_capability_weight > 0.0:
                score = _clamp(
                    (1.0 - effective_capability_weight) * score
                    + effective_capability_weight * capability_match_score
                )
            domain_prior_score = _domain_prior_score(
                cand.tool, primary_domain=primary_domain
            )
            intent_affinity_score = _intent_affinity_score(
                cand.tool, capability_prediction
            )
            generic_verb_penalty = _generic_verb_penalty(
                query=query,
                tool=cand.tool,
                prediction=capability_prediction,
                capability_match_score=capability_match_score,
                intent_affinity=intent_affinity_score,
            )
            score = _clamp(
                score
                + domain_prior_weight * domain_prior_score
                + intent_affinity_weight * intent_affinity_score
                - generic_penalty_weight * generic_verb_penalty
            )

            failure_penalty = 0.0
            if failure_prior:
                fp = failure_prior.get(tool_id)
                if fp:
                    # Simple penalty: log-ish fail_count, capped
                    fc = max(0, fp.get("fail_count") or 0)
                    failure_penalty = min(0.2, 0.05 * (1 + fc**0.5))
                    score = _clamp(score - failure_penalty)

            rescored.append(
                (
                    score,
                    cand,
                    {
                        "tool_id": tool_id,
                        "base_score": float(f"{cand.final_score:.6f}"),
                        "score": float(f"{score:.6f}"),
                        "kg_score": float(f"{kg_scores.get(tool_id, 0.0):.6f}"),
                        "capability_match_score": float(
                            f"{capability_match_score:.6f}"
                        ),
                        "capability_blend_weight": float(
                            f"{effective_capability_weight:.6f}"
                        ),
                        "domain_prior_score": float(f"{domain_prior_score:.6f}"),
                        "intent_affinity_score": float(f"{intent_affinity_score:.6f}"),
                        "generic_verb_penalty": float(f"{generic_verb_penalty:.6f}"),
                        "capability_matched_labels": capability_matches or None,
                        "prior_success_rate": (
                            None
                            if prior_success is None
                            else float(f"{prior_success:.6f}")
                        ),
                        "prior_latency_score": (
                            None
                            if prior_latency_score is None
                            else float(f"{prior_latency_score:.6f}")
                        ),
                        "prior_failure_penalty": (
                            None
                            if prior_penalty is None
                            else float(f"{prior_penalty:.6f}")
                        ),
                        "evidence_layer": evidence_layer,
                        "evidence_n": evidence_n,
                        "failure_penalty": (
                            float(f"{failure_penalty:.6f}") if failure_prior else None
                        ),
                        "failed_on_count": (
                            int(fp.get("fail_count"))
                            if failure_prior and (fp := failure_prior.get(tool_id))
                            else None
                        ),
                        "failure_last_seen": (
                            None
                            if not (failure_prior and failure_prior.get(tool_id))
                            else failure_prior[tool_id].get("last_seen")
                        ),
                    },
                )
            )

        # Prefer available candidates, then higher score.
        rescored.sort(key=lambda x: (not x[1].available, -x[0]))
        top = rescored[: max(1, max_candidates)]

        # Build candidates payload (Plan.candidates compatible) and scores mapping.
        candidates_payload: list[dict[str, Any]] = []
        scores: dict[str, float] = {}
        reasons: list[dict[str, Any]] = []
        for score, cand, debug in top:
            row = cand.to_dict()
            row["final_score"] = score
            if debug.get("kg_score"):
                row["kg_score"] = debug["kg_score"]
            if debug.get("capability_match_score") is not None:
                row["capability_match_score"] = debug["capability_match_score"]
            if debug.get("capability_blend_weight") is not None:
                row["capability_blend_weight"] = debug["capability_blend_weight"]
            if debug.get("domain_prior_score") is not None:
                row["domain_prior_score"] = debug["domain_prior_score"]
            if debug.get("intent_affinity_score") is not None:
                row["intent_affinity_score"] = debug["intent_affinity_score"]
            if debug.get("generic_verb_penalty") is not None:
                row["generic_verb_penalty"] = debug["generic_verb_penalty"]
            if debug.get("capability_matched_labels"):
                row["capability_matched_labels"] = debug["capability_matched_labels"]
            if debug.get("prior_success_rate") is not None:
                row["prior_success_rate"] = debug["prior_success_rate"]
            if debug.get("prior_latency_score") is not None:
                row["prior_latency_score"] = debug["prior_latency_score"]
            if debug.get("prior_failure_penalty") is not None:
                row["prior_failure_penalty"] = debug["prior_failure_penalty"]
            if debug.get("evidence_layer") is not None:
                row["evidence_layer"] = debug["evidence_layer"]
            if debug.get("evidence_n") is not None:
                row["evidence_n"] = debug["evidence_n"]
            if debug.get("failure_penalty") is not None:
                row["failure_penalty"] = debug["failure_penalty"]
            if debug.get("failed_on_count") is not None:
                row["failed_on_count"] = debug["failed_on_count"]
            if debug.get("failure_last_seen") is not None:
                row["failure_last_seen"] = debug["failure_last_seen"]
            candidates_payload.append(row)
            scores[cand.tool.id] = score
            reasons.append(debug)

        confidence = 0.0
        if candidates_payload:
            top_score = candidates_payload[0]["final_score"]
            second = (
                candidates_payload[1]["final_score"]
                if len(candidates_payload) > 1
                else 0.0
            )
            gap = max(0.0, float(top_score) - float(second))
            confidence = _clamp(0.65 * float(top_score) + 0.35 * gap)

        chosen_tool_id = None
        for row in candidates_payload:
            if row.get("available", True):
                chosen_tool_id = row.get("tool_id")
                break
        chosen_tool_id = self._canonicalize_tool_id(chosen_tool_id)
        candidate_source_counts: dict[str, int] = {}
        for row in candidates_payload:
            source = str(row.get("source") or "catalog")
            candidate_source_counts[source] = candidate_source_counts.get(source, 0) + 1
        routing_diagnostics = _build_routing_diagnostics(
            candidates=candidates_payload,
            chosen_tool_id=chosen_tool_id,
            started_at=planner_started_at,
            source_counts=candidate_source_counts,
        )
        routing_diagnostics["allowlist_mode"] = allowlist_mode or "curated"
        routing_diagnostics["allowlist_masking"] = allowed_tool_ids is not None
        metrics_collector.record_tool_routing(
            surface="plan",
            candidate_count=routing_diagnostics["candidate_count"],
            selected_rank=routing_diagnostics["selected_tool_rank"],
            routing_latency_ms=routing_diagnostics["routing_latency_ms"],
            top_k_hits={
                5: bool(routing_diagnostics["selected_tool_in_top_5"]),
                10: bool(routing_diagnostics["selected_tool_in_top_10"]),
            },
        )

        # Surface behavior policy options for prompters (non-blocking)
        behavior_policy_reasons: list[dict[str, Any]] = []
        try:
            behavior_policies = load_behavior_policies()
            if behavior_policies:
                table_lines = [
                    f"- {p.get('policy_id', 'unknown')}: rt_min={p.get('rt_min_sec')}, "
                    f"rt_max={p.get('rt_max_sec')}, acc_min={p.get('accuracy_min')}, "
                    f"miss_max={p.get('miss_rate_max')}"
                    for p in behavior_policies
                    if isinstance(p, dict)
                ]
                behavior_policy_reasons.append(
                    {
                        "code": "behavior_policy_options",
                        "policies": behavior_policies,
                        "table": "\n".join(table_lines),
                    }
                )
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Behavior policy load skipped: %s", exc)

        return UnifiedPlannerResult(
            candidates=candidates_payload,
            scores=scores,
            selection_reasons=reasons + behavior_policy_reasons,
            constraints_applied=constraints_applied,
            confidence_score=confidence,
            chosen_tool_id=chosen_tool_id,
            intent=intents,
            task_family=task_family,
            kg_families=kg_families or None,
            mask_reasons=mask_reasons or None,
            predicted_capabilities=capability_prediction.predicted_capabilities or None,
            predicted_intents=capability_prediction.predicted_intents or None,
            capability_prediction=capability_prediction.as_dict(),
            cross_stage_context=cross_stage_context,
            loop_signals=loop_signals_payload or None,
            routing_diagnostics=routing_diagnostics,
        )


def get_default_unified_planner(
    *, tool_retriever: ToolRetriever | None = None
) -> UnifiedPlanner:
    """Factory with sensible defaults + optional ToolRetriever injection."""

    evidence_store = get_default_evidence_store()
    return UnifiedPlanner(tool_retriever=tool_retriever, evidence_reader=evidence_store)


__all__ = ["UnifiedPlanner", "UnifiedPlannerResult", "get_default_unified_planner"]
