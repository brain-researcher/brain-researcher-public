"""Thin V0 principle controller for hypothesis workflow reranking.

Relocated to ``services.shared`` (round 2 services-layer DAG work) so that
``services.tools`` can reuse the principle controller without a
``tools -> agent`` import back-edge. The public symbols are re-exported from
``brain_researcher.services.agent.principle_controller`` for backward
compatibility.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from functools import lru_cache
from typing import Any

from brain_researcher.services.shared.r2toolsagent_plan_memory import (
    create_plan_memory,
)

_CONTROLLER_MODE = "principle_v0"
_LEGACY_MODE = "legacy"
_MAX_ACTIVE_PRINCIPLES = 5
_EPSILON = 1e-9


_BASE_PROFILES: dict[str, dict[str, Any]] = {
    "novelty_first": {
        "label": "Novelty-first search",
        "kind": "base",
        "weights": {
            "novelty_score": 0.42,
            "leverage_score": 0.20,
            "coherence_score": 0.12,
            "feasibility_score": 0.10,
            "contradiction_score": 0.08,
            "bridge_score": 0.08,
        },
    },
    "balanced": {
        "label": "Balanced search",
        "kind": "base",
        "weights": {
            "novelty_score": 0.18,
            "leverage_score": 0.18,
            "coherence_score": 0.16,
            "feasibility_score": 0.16,
            "contradiction_score": 0.16,
            "bridge_score": 0.16,
        },
    },
    "evidence_first": {
        "label": "Evidence-first search",
        "kind": "base",
        "weights": {
            "feasibility_score": 0.30,
            "coherence_score": 0.24,
            "leverage_score": 0.18,
            "bridge_score": 0.12,
            "novelty_score": 0.08,
            "contradiction_score": 0.08,
        },
    },
}

_ANOMALY_PROFILES: dict[str, dict[str, Any]] = {
    "contradiction_resolving": {
        "label": "Contradiction-resolving search",
        "kind": "anomaly",
        "weights": {
            "contradiction_score": 0.32,
            "coherence_score": 0.18,
            "leverage_score": 0.18,
            "feasibility_score": 0.14,
            "novelty_score": 0.10,
            "bridge_score": 0.08,
        },
        "trigger": "contradiction",
    },
    "topology_shift_seeking": {
        "label": "Topology-shift-seeking search",
        "kind": "anomaly",
        "weights": {
            "bridge_score": 0.28,
            "contradiction_score": 0.18,
            "leverage_score": 0.18,
            "novelty_score": 0.14,
            "coherence_score": 0.12,
            "feasibility_score": 0.10,
        },
        "trigger": "topology_shift",
    },
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _sorted_unique(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values or []:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    out.sort(key=str.lower)
    return out


def _normalize_distribution(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(_EPSILON, _safe_float(value, 0.0)) for value in weights.values())
    if total <= 0:
        total = float(len(weights) or 1)
        return {key: round(1.0 / total, 6) for key in weights}
    return {
        key: round(max(_EPSILON, _safe_float(value, 0.0)) / total, 6)
        for key, value in weights.items()
    }


def _profile_for_id(principle_id: str) -> dict[str, Any]:
    raw = dict(
        _BASE_PROFILES.get(principle_id)
        or _ANOMALY_PROFILES.get(principle_id)
        or _BASE_PROFILES["novelty_first"]
    )
    return {
        "principle_id": principle_id,
        "label": raw.get("label") or principle_id.replace("_", " ").title(),
        "kind": raw.get("kind") or "base",
        "weights": _normalize_distribution(dict(raw.get("weights") or {})),
        "trigger": raw.get("trigger"),
    }


def _find_principle(
    principles: list[dict[str, Any]], principle_id: str
) -> dict[str, Any] | None:
    for principle in principles:
        if str(principle.get("principle_id") or "") == principle_id:
            return principle
    return None


def _ensure_principle(
    principles: list[dict[str, Any]], principle_id: str
) -> tuple[list[dict[str, Any]], bool]:
    existing = _find_principle(principles, principle_id)
    if existing is not None:
        return principles, False
    updated = list(principles)
    updated.append(_profile_for_id(principle_id))
    return updated, True


def _trim_principles(
    principles: list[dict[str, Any]],
    posterior: dict[str, float],
    *,
    keep_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    keep_ids = set(keep_ids or set())
    if len(principles) <= _MAX_ACTIVE_PRINCIPLES:
        return principles, posterior

    ranked_ids = sorted(
        (str(item.get("principle_id") or "") for item in principles),
        key=lambda pid: (
            pid not in keep_ids,
            float(posterior.get(pid) or 0.0),
            pid,
        ),
    )
    retained = set(ranked_ids[-_MAX_ACTIVE_PRINCIPLES:]) | keep_ids
    trimmed_principles = [
        principle
        for principle in principles
        if str(principle.get("principle_id") or "") in retained
    ]
    trimmed_posterior = {
        key: value for key, value in posterior.items() if key in retained
    }
    return trimmed_principles, _normalize_distribution(trimmed_posterior)


def build_principle_session_key(
    *,
    query: str,
    seed_kg_ids: list[str] | None,
    relation_types: list[str] | None,
    taste_mode: str,
) -> str:
    payload = {
        "query": str(query or "").strip().lower(),
        "seed_kg_ids": _sorted_unique(seed_kg_ids),
        "relation_types": _sorted_unique(relation_types),
        "taste_mode": str(taste_mode or "novelty_first").strip().lower(),
    }
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"pcs_{digest}"


def _current_plan_memory_db_path() -> str | None:
    return (
        os.getenv("BR_PRINCIPLE_CONTROLLER_PLAN_MEMORY_DB")
        or os.getenv("BR_PLAN_MEMORY_DB")
        or None
    )


@lru_cache(maxsize=8)
def _get_plan_memory(db_path: str | None):
    return create_plan_memory(db_path=db_path)


def _build_empty_state(
    *,
    controller_mode: str,
    query: str,
    seed_kg_ids: list[str],
    relation_types: list[str],
    taste_mode: str,
) -> dict[str, Any]:
    return {
        "schema_version": "principle-controller-v0",
        "controller_mode": controller_mode,
        "enabled": controller_mode == _CONTROLLER_MODE,
        "session_key": build_principle_session_key(
            query=query,
            seed_kg_ids=seed_kg_ids,
            relation_types=relation_types,
            taste_mode=taste_mode,
        ),
        "query_text": str(query or "").strip(),
        "query_hash": hashlib.md5(
            str(query or "").strip().lower().encode()
        ).hexdigest(),
        "seed_signature": _sorted_unique(seed_kg_ids),
        "relation_signature": _sorted_unique(relation_types),
        "taste_mode": str(taste_mode or "novelty_first").strip().lower(),
        "principles": [],
        "posterior": {},
        "active_principle_id": None,
        "active_principle": None,
        "principle_confidence": None,
        "selection_reason": None,
        "anomaly_state": {"counts": {}, "latest_flags": []},
    }


def _select_active_principle_id(
    posterior: dict[str, float], *, preferred_id: str | None = None
) -> str:
    if preferred_id and preferred_id in posterior:
        top_score = (
            max(float(value) for value in posterior.values()) if posterior else 0.0
        )
        if abs(float(posterior.get(preferred_id) or 0.0) - top_score) <= 1e-6:
            return preferred_id
    ranked = sorted(
        posterior.items(),
        key=lambda item: (-float(item[1] or 0.0), item[0]),
    )
    if ranked:
        return str(ranked[0][0])
    return preferred_id or "novelty_first"


def initialize_principle_state(
    *,
    query: str,
    seed_kg_ids: list[str] | None,
    relation_types: list[str] | None,
    taste_mode: str,
    controller_mode: str = _LEGACY_MODE,
    leverage_items: list[dict[str, Any]] | None = None,
    run_id: str | None = None,
    step_id: str = "principle_state_init",
) -> dict[str, Any]:
    """Create or load cross-run principle state for the hypothesis workflow."""
    seed_signature = _sorted_unique(seed_kg_ids)
    relation_signature = _sorted_unique(relation_types)
    state = _build_empty_state(
        controller_mode=controller_mode,
        query=query,
        seed_kg_ids=seed_signature,
        relation_types=relation_signature,
        taste_mode=taste_mode,
    )
    if controller_mode != _CONTROLLER_MODE:
        state["selection_reason"] = "legacy_mode_disabled"
        return state

    session_key = str(state["session_key"])
    memory = _get_plan_memory(_current_plan_memory_db_path())
    record = memory.get_principle_session(session_key)
    if record is None:
        principles = [_profile_for_id(principle_id) for principle_id in _BASE_PROFILES]
        posterior = _normalize_distribution(
            {p["principle_id"]: 1.0 for p in principles}
        )
        active_principle_id = (
            taste_mode
            if taste_mode in posterior
            else _select_active_principle_id(posterior)
        )
        principle = _find_principle(principles, active_principle_id)
        state.update(
            {
                "principles": principles,
                "posterior": posterior,
                "active_principle_id": active_principle_id,
                "active_principle": principle,
                "principle_confidence": posterior.get(active_principle_id),
                "selection_reason": "cold_start_taste_mode",
            }
        )
        memory.upsert_principle_session(
            session_key=session_key,
            query_text=str(query or "").strip(),
            query_hash=str(state["query_hash"]),
            seed_signature=seed_signature,
            relation_signature=relation_signature,
            taste_mode=str(state["taste_mode"]),
            controller_mode=_CONTROLLER_MODE,
            active_principle_id=active_principle_id,
            posterior=posterior,
            principles=principles,
            anomaly_state=dict(state["anomaly_state"]),
            session_state=state,
            last_run_id=run_id,
        )
        memory.append_principle_event(
            session_key=session_key,
            event_type="init",
            run_id=run_id,
            step_id=step_id,
            active_principle_id=active_principle_id,
            payload={
                "selection_reason": "cold_start_taste_mode",
                "top_candidate_ids": [
                    str((row or {}).get("kg_id") or "")
                    for row in (leverage_items or [])[:3]
                    if isinstance(row, dict)
                ],
            },
        )
    else:
        session_state = dict(record.session_state or {})
        principles = list(session_state.get("principles") or record.principles or [])
        posterior = dict(session_state.get("posterior") or record.posterior or {})
        principles, _ = _ensure_principle(
            principles, taste_mode if taste_mode in _BASE_PROFILES else "novelty_first"
        )
        for principle in principles:
            principle_id = str(principle.get("principle_id") or "")
            posterior.setdefault(principle_id, _EPSILON)
        posterior = _normalize_distribution(posterior)
        preferred_id = str(record.active_principle_id or "") or None
        active_principle_id = _select_active_principle_id(
            posterior, preferred_id=preferred_id
        )
        principle = _find_principle(principles, active_principle_id)
        state.update(session_state)
        state.update(
            {
                "schema_version": "principle-controller-v0",
                "controller_mode": _CONTROLLER_MODE,
                "enabled": True,
                "session_key": session_key,
                "query_text": str(query or "").strip(),
                "query_hash": str(state["query_hash"]),
                "seed_signature": seed_signature,
                "relation_signature": relation_signature,
                "taste_mode": str(state["taste_mode"]),
                "principles": principles,
                "posterior": posterior,
                "active_principle_id": active_principle_id,
                "active_principle": principle,
                "principle_confidence": posterior.get(active_principle_id),
                "selection_reason": "warm_start_resume",
            }
        )
        memory.upsert_principle_session(
            session_key=session_key,
            query_text=str(query or "").strip(),
            query_hash=str(state["query_hash"]),
            seed_signature=seed_signature,
            relation_signature=relation_signature,
            taste_mode=str(state["taste_mode"]),
            controller_mode=_CONTROLLER_MODE,
            active_principle_id=active_principle_id,
            posterior=posterior,
            principles=principles,
            anomaly_state=dict(state.get("anomaly_state") or {}),
            session_state=state,
            last_run_id=run_id or record.last_run_id,
        )

    memory.append_principle_event(
        session_key=session_key,
        event_type="selection",
        run_id=run_id,
        step_id=step_id,
        active_principle_id=state.get("active_principle_id"),
        payload={
            "selection_reason": state.get("selection_reason"),
            "principle_confidence": state.get("principle_confidence"),
            "top_candidate_ids": [
                str((row or {}).get("kg_id") or "")
                for row in (leverage_items or [])[:3]
                if isinstance(row, dict)
            ],
        },
    )
    return state


def rerank_leverage_items(
    principle_state: dict[str, Any] | None,
    leverage_items: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rerank leverage rows using the currently active principle profile."""
    rows = [dict(item) for item in (leverage_items or []) if isinstance(item, dict)]
    state = dict(principle_state or {})
    if not rows:
        return rows, {}
    if str(state.get("controller_mode") or _LEGACY_MODE) != _CONTROLLER_MODE:
        return rows, {}

    principle_id = str(state.get("active_principle_id") or "").strip()
    principle = _find_principle(list(state.get("principles") or []), principle_id)
    if principle is None and isinstance(state.get("active_principle"), dict):
        active_principle = dict(state.get("active_principle") or {})
        if str(active_principle.get("principle_id") or "").strip() == principle_id:
            principle = active_principle
    if not principle:
        return rows, {}

    def _field_value(row: dict[str, Any], field_name: str) -> float:
        if field_name in row:
            return _safe_float(row.get(field_name), 0.0)
        breakdown = row.get("score_breakdown") or {}
        if isinstance(breakdown, dict):
            return _safe_float(breakdown.get(field_name), 0.0)
        return 0.0

    weights = dict(principle.get("weights") or {})
    selection_reason = f"{principle_id}:weighted_rerank"
    reranked: list[dict[str, Any]] = []
    for row in rows:
        principle_score = 0.0
        for field_name, weight in weights.items():
            principle_score += _safe_float(weight, 0.0) * _field_value(row, field_name)
        enriched = dict(row)
        enriched["principle_score"] = round(principle_score, 6)
        enriched["active_principle_id"] = principle_id
        enriched["selection_reason"] = selection_reason
        reranked.append(enriched)

    reranked.sort(
        key=lambda item: (
            -_safe_float(item.get("principle_score"), 0.0),
            -_safe_float(item.get("leverage_score"), 0.0),
            -_safe_float(item.get("novelty_score"), 0.0),
            str(item.get("kg_id") or ""),
        )
    )
    metadata = {
        "principle_session_key": state.get("session_key")
        or state.get("principle_session_key"),
        "active_principle_id": principle_id,
        "active_principle": principle,
        "principle_posterior": dict(state.get("posterior") or {}),
        "principle_confidence": state.get("posterior", {}).get(principle_id),
        "selection_reason": selection_reason,
        "controller_mode": _CONTROLLER_MODE,
    }
    return reranked, metadata


def update_principle_state(
    *,
    query: str,
    seed_kg_ids: list[str] | None,
    relation_types: list[str] | None,
    taste_mode: str,
    controller_mode: str = _LEGACY_MODE,
    principle_state: dict[str, Any] | None,
    ood_result: dict[str, Any] | None,
    contradiction_result: dict[str, Any] | None,
    topology_result: dict[str, Any] | None,
    run_id: str | None = None,
    step_id: str = "principle_state_update",
) -> dict[str, Any]:
    """Update cross-run principle state using anomaly and output signals."""
    state = dict(principle_state or {})
    if controller_mode != _CONTROLLER_MODE:
        state = _build_empty_state(
            controller_mode=controller_mode,
            query=query,
            seed_kg_ids=_sorted_unique(seed_kg_ids),
            relation_types=_sorted_unique(relation_types),
            taste_mode=taste_mode,
        )
        state["selection_reason"] = "legacy_mode_disabled"
        return state

    if not state:
        state = initialize_principle_state(
            query=query,
            seed_kg_ids=seed_kg_ids,
            relation_types=relation_types,
            taste_mode=taste_mode,
            controller_mode=controller_mode,
            run_id=run_id,
            step_id=step_id,
        )

    memory = _get_plan_memory(_current_plan_memory_db_path())
    principles = list(state.get("principles") or [])
    posterior = _normalize_distribution(dict(state.get("posterior") or {}))
    active_principle_id = str(state.get("active_principle_id") or "").strip()
    anomaly_state = dict(
        state.get("anomaly_state") or {"counts": {}, "latest_flags": []}
    )
    anomaly_counts = dict(anomaly_state.get("counts") or {})
    anomaly_flags: list[str] = []
    injection_events: list[tuple[str, dict[str, Any]]] = []

    ood_summary = (ood_result or {}).get("summary") or {}
    n_requested = int(_safe_float(ood_summary.get("n_requested"), 0))
    n_returned = int(_safe_float(ood_summary.get("n_returned"), 0))
    n_vetoed = int(_safe_float(ood_summary.get("n_vetoed"), 0))
    motifs = list((contradiction_result or {}).get("motifs") or [])
    proposals = list((topology_result or {}).get("proposals") or [])

    contradiction_signal = False
    if motifs:
        top_motif = motifs[0] if isinstance(motifs[0], dict) else {}
        contradiction_signal = (
            _safe_float(top_motif.get("contradiction_density"), 0.0) >= 0.30
            or _safe_float(top_motif.get("motif_score"), 0.0) >= 0.20
            or len(motifs) >= 2
        )
    topology_signal = False
    if proposals:
        top_proposal = proposals[0] if isinstance(proposals[0], dict) else {}
        topology_signal = (
            abs(_safe_float(top_proposal.get("delta"), 0.0)) >= 0.15
            or len(proposals) >= 2
        )

    if contradiction_signal:
        anomaly_flags.append("contradiction")
    if topology_signal:
        anomaly_flags.append("topology_shift")
    if n_returned <= 0:
        anomaly_flags.append("zero_output")
    if n_requested >= 2 and n_vetoed >= max(2, math.ceil(n_requested * 0.5)):
        anomaly_flags.append("veto_spike")

    for flag in anomaly_flags:
        anomaly_counts[flag] = int(anomaly_counts.get(flag) or 0) + 1
    anomaly_state["counts"] = anomaly_counts
    anomaly_state["latest_flags"] = anomaly_flags
    anomaly_state["latest_summary"] = {
        "n_requested": n_requested,
        "n_returned": n_returned,
        "n_vetoed": n_vetoed,
        "motif_count": len(motifs),
        "proposal_count": len(proposals),
    }

    log_weights = {
        key: math.log(max(_EPSILON, _safe_float(value, _EPSILON)))
        for key, value in posterior.items()
    }
    if active_principle_id and active_principle_id not in log_weights:
        log_weights[active_principle_id] = math.log(_EPSILON)

    selection_reason = "stable_posterior"
    if active_principle_id:
        if anomaly_flags:
            log_weights[active_principle_id] = (
                log_weights.get(active_principle_id, math.log(_EPSILON)) - 0.18
            )
        elif n_returned > 0:
            log_weights[active_principle_id] = (
                log_weights.get(active_principle_id, math.log(_EPSILON)) + 0.14
            )

    if "zero_output" in anomaly_flags:
        selection_reason = "zero_output_penalty"
        if active_principle_id:
            log_weights[active_principle_id] -= 0.12
    if "veto_spike" in anomaly_flags:
        selection_reason = "veto_spike_penalty"
        if active_principle_id:
            log_weights[active_principle_id] -= 0.10
    baseline_mass = max(
        (_safe_float(value, 0.0) for value in posterior.values()), default=0.0
    )
    if baseline_mass <= 0:
        baseline_mass = 1.0 / max(len(principles), 1)
    if "contradiction" in anomaly_flags:
        principles, created = _ensure_principle(principles, "contradiction_resolving")
        log_weights["contradiction_resolving"] = max(
            log_weights.get("contradiction_resolving", math.log(_EPSILON)) + 0.32,
            math.log(max(baseline_mass, _EPSILON)) + 0.12,
        )
        selection_reason = "contradiction_triggered"
        if created:
            injection_events.append(
                (
                    "contradiction_resolving",
                    {
                        "flag": "contradiction",
                        "motif_count": len(motifs),
                    },
                )
            )
    if "topology_shift" in anomaly_flags:
        principles, created = _ensure_principle(principles, "topology_shift_seeking")
        log_weights["topology_shift_seeking"] = max(
            log_weights.get("topology_shift_seeking", math.log(_EPSILON)) + 0.32,
            math.log(max(baseline_mass, _EPSILON)) + 0.12,
        )
        selection_reason = "topology_shift_triggered"
        if created:
            injection_events.append(
                (
                    "topology_shift_seeking",
                    {
                        "flag": "topology_shift",
                        "proposal_count": len(proposals),
                    },
                )
            )

    posterior = _normalize_distribution(
        {key: math.exp(value) for key, value in log_weights.items()}
    )
    principles, posterior = _trim_principles(
        principles,
        posterior,
        keep_ids={active_principle_id} if active_principle_id else None,
    )
    active_principle_id = _select_active_principle_id(
        posterior, preferred_id=active_principle_id
    )
    active_principle = _find_principle(principles, active_principle_id)

    state.update(
        {
            "schema_version": "principle-controller-v0",
            "controller_mode": _CONTROLLER_MODE,
            "enabled": True,
            "principles": principles,
            "posterior": posterior,
            "active_principle_id": active_principle_id,
            "active_principle": active_principle,
            "principle_confidence": posterior.get(active_principle_id),
            "selection_reason": selection_reason,
            "anomaly_state": anomaly_state,
            "anomaly_flags": anomaly_flags,
        }
    )

    memory.upsert_principle_session(
        session_key=str(state.get("session_key")),
        query_text=str(query or "").strip(),
        query_hash=str(state.get("query_hash") or ""),
        seed_signature=_sorted_unique(seed_kg_ids),
        relation_signature=_sorted_unique(relation_types),
        taste_mode=str(state.get("taste_mode") or taste_mode),
        controller_mode=_CONTROLLER_MODE,
        active_principle_id=active_principle_id,
        posterior=posterior,
        principles=principles,
        anomaly_state=anomaly_state,
        session_state=state,
        last_run_id=run_id,
    )
    for injected_id, payload in injection_events:
        memory.append_principle_event(
            session_key=str(state.get("session_key")),
            event_type="anomaly_injection",
            run_id=run_id,
            step_id=step_id,
            active_principle_id=injected_id,
            payload=payload,
        )
    memory.append_principle_event(
        session_key=str(state.get("session_key")),
        event_type="update",
        run_id=run_id,
        step_id=step_id,
        active_principle_id=active_principle_id,
        payload={
            "anomaly_flags": anomaly_flags,
            "selection_reason": selection_reason,
            "principle_confidence": state.get("principle_confidence"),
            "n_returned": n_returned,
            "n_vetoed": n_vetoed,
            "motif_count": len(motifs),
            "proposal_count": len(proposals),
        },
    )
    return state


__all__ = [
    "build_principle_session_key",
    "initialize_principle_state",
    "rerank_leverage_items",
    "update_principle_state",
]
