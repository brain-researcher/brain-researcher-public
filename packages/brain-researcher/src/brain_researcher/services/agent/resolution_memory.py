"""Session-scoped resolution memory + cross-session platform knowledge.

This module provides two lightweight layers used to avoid repeated discovery:

- session cache: exact step results keyed by a per-thread step signature
- platform knowledge: coarse Redis-backed facts shared across sessions

V1 keeps the payloads intentionally small and only memoizes:
- query-understanding results for an exact query
- tool-candidate discovery for an exact query
- dataset derivative availability facts
- capability availability / negative hosted-tool findings
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Iterable, MutableMapping
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SESSION_CACHE_CTX_KEY = "_resolution_session_cache"
SESSION_EVENTS_CTX_KEY = "_resolution_events"
SESSION_GENERIC_CLARIFICATION_CTX_KEY = "_resolution_generic_clarifications"
SESSION_PENDING_CTX_KEY = "_resolution_pending_decisions"
SESSION_OVERRIDES_CTX_KEY = "_resolution_overrides"
SESSION_STATS_CTX_KEY = "_resolution_cache_stats"
SESSION_STEP_STATUS_CTX_KEY = "_resolution_step_statuses"

_SESSION_MEMORY: dict[str, dict[str, Any]] = {}
_SESSION_MEMORY_LOCK = threading.Lock()

_PLATFORM_STORE: "PlatformKnowledgeStore | None" = None
_PLATFORM_STORE_LOCK = threading.Lock()

_WHITESPACE_RE = re.compile(r"\s+")
_DERIVATIVE_HINTS = {
    "fmriprep": ("fmriprep",),
    "mriqc": ("mriqc",),
    "fitlins": ("fitlins", "glmfitlins"),
    "xcpd": ("xcpd",),
}

_SESSION_STATE_KEYS = (
    SESSION_CACHE_CTX_KEY,
    SESSION_EVENTS_CTX_KEY,
    SESSION_GENERIC_CLARIFICATION_CTX_KEY,
    SESSION_PENDING_CTX_KEY,
    SESSION_OVERRIDES_CTX_KEY,
    SESSION_STATS_CTX_KEY,
    SESSION_STEP_STATUS_CTX_KEY,
)


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _normalize_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "").strip().lower())


def _safe_ctx(ctx: Optional[MutableMapping[str, Any]]) -> MutableMapping[str, Any]:
    if ctx is None:
        raise ValueError("resolution memory requires a mutable context dict")
    return ctx


def _thread_id(ctx: Optional[MutableMapping[str, Any]]) -> Optional[str]:
    if not isinstance(ctx, MutableMapping):
        return None
    for key in ("thread_id", "session_id"):
        value = ctx.get(key)
        if value:
            return str(value)
    return None


def _ensure_ctx_state(ctx: MutableMapping[str, Any]) -> None:
    thread_id = _thread_id(ctx)
    if thread_id:
        with _SESSION_MEMORY_LOCK:
            existing = _SESSION_MEMORY.get(thread_id)
        if isinstance(existing, dict):
            restored = _json_clone(existing)
            for key in _SESSION_STATE_KEYS:
                if key not in ctx and key in restored:
                    ctx[key] = restored[key]
    if SESSION_CACHE_CTX_KEY not in ctx:
        ctx[SESSION_CACHE_CTX_KEY] = {}
    if SESSION_EVENTS_CTX_KEY not in ctx:
        ctx[SESSION_EVENTS_CTX_KEY] = []
    if SESSION_GENERIC_CLARIFICATION_CTX_KEY not in ctx:
        ctx[SESSION_GENERIC_CLARIFICATION_CTX_KEY] = {
            "answered_keys": [],
            "answers": [],
        }
    if SESSION_PENDING_CTX_KEY not in ctx:
        ctx[SESSION_PENDING_CTX_KEY] = []
    if SESSION_OVERRIDES_CTX_KEY not in ctx:
        ctx[SESSION_OVERRIDES_CTX_KEY] = {}
    if SESSION_STEP_STATUS_CTX_KEY not in ctx:
        ctx[SESSION_STEP_STATUS_CTX_KEY] = {}
    if SESSION_STATS_CTX_KEY not in ctx:
        ctx[SESSION_STATS_CTX_KEY] = {
            "session_hits": 0,
            "platform_hits": 0,
            "misses": 0,
            "writes": 0,
        }


def _persist_ctx_session_state(ctx: MutableMapping[str, Any]) -> None:
    thread_id = _thread_id(ctx)
    if not thread_id:
        return
    state: dict[str, Any] = {}
    for key in _SESSION_STATE_KEYS:
        if key in ctx:
            state[key] = _json_clone(ctx[key])
    with _SESSION_MEMORY_LOCK:
        _SESSION_MEMORY[thread_id] = state


def build_step_signature(step_kind: str, query: str, extra: Optional[Dict[str, Any]] = None) -> str:
    payload = {
        "kind": _normalize_text(step_kind),
        "query": _normalize_text(query),
        "extra": extra or {},
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(data.encode("utf-8")).hexdigest()[:20]
    return f"{payload['kind']}:{digest}"


def resolve_runtime_surface(ctx: Optional[MutableMapping[str, Any]], default: str = "agent") -> str:
    if isinstance(ctx, MutableMapping):
        value = ctx.get("runtime_surface") or ctx.get("execution_surface")
        if value:
            return _normalize_text(str(value))
    env_value = os.getenv("BR_RESOLUTION_RUNTIME_SURFACE")
    if env_value:
        return _normalize_text(env_value)
    return _normalize_text(default)


def get_session_entry(
    ctx: Optional[MutableMapping[str, Any]],
    step_signature: str,
) -> Optional[Dict[str, Any]]:
    if not isinstance(ctx, MutableMapping):
        return None
    _ensure_ctx_state(ctx)
    entry = (ctx.get(SESSION_CACHE_CTX_KEY) or {}).get(step_signature)
    return _json_clone(entry) if isinstance(entry, dict) else None


def set_session_entry(
    ctx: Optional[MutableMapping[str, Any]],
    step_signature: str,
    value: Dict[str, Any],
) -> None:
    if not isinstance(ctx, MutableMapping):
        return
    context = _safe_ctx(ctx)
    _ensure_ctx_state(context)
    cache = context[SESSION_CACHE_CTX_KEY]
    assert isinstance(cache, dict)
    cache[step_signature] = _json_clone(value)
    stats = context[SESSION_STATS_CTX_KEY]
    if isinstance(stats, dict):
        stats["writes"] = int(stats.get("writes", 0)) + 1
    _persist_ctx_session_state(context)


def record_event(
    ctx: Optional[MutableMapping[str, Any]],
    event_type: str,
    *,
    layer: Optional[str] = None,
    cache_family: Optional[str] = None,
    cache_key: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    if not isinstance(ctx, MutableMapping):
        return
    _ensure_ctx_state(ctx)
    event = {
        "event_type": str(event_type),
        "ts": time.time(),
    }
    if layer:
        event["layer"] = layer
    if cache_family:
        event["cache_family"] = cache_family
    if cache_key:
        event["cache_key"] = cache_key
    if payload:
        event["payload"] = _json_clone(payload)
    events = ctx[SESSION_EVENTS_CTX_KEY]
    if isinstance(events, list):
        events.append(event)

    stats = ctx.get(SESSION_STATS_CTX_KEY)
    if not isinstance(stats, dict):
        return
    if event_type == "resolution_cache_hit":
        if layer == "session":
            stats["session_hits"] = int(stats.get("session_hits", 0)) + 1
        elif layer == "platform":
            stats["platform_hits"] = int(stats.get("platform_hits", 0)) + 1
    elif event_type == "resolution_cache_miss":
        stats["misses"] = int(stats.get("misses", 0)) + 1
    _persist_ctx_session_state(ctx)


def set_step_status(
    ctx: Optional[MutableMapping[str, Any]],
    step_name: str,
    *,
    status: str,
    source: str,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    if not isinstance(ctx, MutableMapping):
        return
    _ensure_ctx_state(ctx)
    statuses = ctx[SESSION_STEP_STATUS_CTX_KEY]
    if not isinstance(statuses, dict):
        return
    row = {
        "status": status,
        "source": source,
    }
    if detail:
        row["detail"] = _json_clone(detail)
    statuses[str(step_name)] = row
    _persist_ctx_session_state(ctx)


def add_pending_decision(
    ctx: Optional[MutableMapping[str, Any]],
    decision: Dict[str, Any],
) -> None:
    if not isinstance(ctx, MutableMapping):
        return
    _ensure_ctx_state(ctx)
    pending = ctx[SESSION_PENDING_CTX_KEY]
    if not isinstance(pending, list):
        return
    key = json.dumps(decision, sort_keys=True, default=str)
    existing = {json.dumps(item, sort_keys=True, default=str) for item in pending if isinstance(item, dict)}
    if key not in existing:
        pending.append(_json_clone(decision))
        _persist_ctx_session_state(ctx)


def clear_pending_decisions(ctx: Optional[MutableMapping[str, Any]], capability_intent: Optional[str] = None) -> None:
    if not isinstance(ctx, MutableMapping):
        return
    _ensure_ctx_state(ctx)
    pending = ctx.get(SESSION_PENDING_CTX_KEY)
    if not isinstance(pending, list):
        return
    if not capability_intent:
        pending.clear()
        _persist_ctx_session_state(ctx)
        return
    pending[:] = [
        item
        for item in pending
        if not isinstance(item, dict)
        or item.get("capability_intent") != capability_intent
    ]
    _persist_ctx_session_state(ctx)


def get_pending_decisions(ctx: Optional[MutableMapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(ctx, MutableMapping):
        return []
    _ensure_ctx_state(ctx)
    pending = ctx.get(SESSION_PENDING_CTX_KEY)
    if not isinstance(pending, list):
        return []
    return [_json_clone(item) for item in pending if isinstance(item, dict)]


def pop_pending_decision(
    ctx: Optional[MutableMapping[str, Any]],
) -> Optional[dict[str, Any]]:
    if not isinstance(ctx, MutableMapping):
        return None
    _ensure_ctx_state(ctx)
    pending = ctx.get(SESSION_PENDING_CTX_KEY)
    if not isinstance(pending, list) or not pending:
        return None
    item = pending.pop(0)
    _persist_ctx_session_state(ctx)
    return _json_clone(item) if isinstance(item, dict) else None


def set_override(
    ctx: Optional[MutableMapping[str, Any]],
    capability_intent: str,
    choice: str,
) -> None:
    if not isinstance(ctx, MutableMapping):
        return
    _ensure_ctx_state(ctx)
    overrides = ctx[SESSION_OVERRIDES_CTX_KEY]
    if not isinstance(overrides, dict):
        return
    overrides[str(capability_intent)] = str(choice)
    record_event(
        ctx,
        "resolution_decision_applied",
        layer="session",
        cache_family="capability",
        cache_key=capability_intent,
        payload={"choice": choice},
    )
    clear_pending_decisions(ctx, capability_intent)
    _persist_ctx_session_state(ctx)


def get_override(ctx: Optional[MutableMapping[str, Any]], capability_intent: str) -> Optional[str]:
    if not isinstance(ctx, MutableMapping):
        return None
    _ensure_ctx_state(ctx)
    overrides = ctx.get(SESSION_OVERRIDES_CTX_KEY)
    if not isinstance(overrides, dict):
        return None
    value = overrides.get(capability_intent)
    return str(value) if value else None


def get_overrides(ctx: Optional[MutableMapping[str, Any]]) -> Dict[str, str]:
    if not isinstance(ctx, MutableMapping):
        return {}
    _ensure_ctx_state(ctx)
    overrides = ctx.get(SESSION_OVERRIDES_CTX_KEY)
    if not isinstance(overrides, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in overrides.items()
        if key and value
    }


def export_resolution_state(ctx: Optional[MutableMapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(ctx, MutableMapping):
        return {
            "step_statuses": {},
            "pending_decisions": [],
            "generic_clarifications": {
                "answered_keys": [],
                "answers": [],
            },
            "resolution_cache_stats": {},
            "resolution_events": [],
        }
    _ensure_ctx_state(ctx)
    return {
        "step_statuses": _json_clone(ctx.get(SESSION_STEP_STATUS_CTX_KEY) or {}),
        "pending_decisions": _json_clone(ctx.get(SESSION_PENDING_CTX_KEY) or []),
        "generic_clarifications": _json_clone(
            ctx.get(SESSION_GENERIC_CLARIFICATION_CTX_KEY)
            or {"answered_keys": [], "answers": []}
        ),
        "resolution_cache_stats": _json_clone(ctx.get(SESSION_STATS_CTX_KEY) or {}),
        "resolution_events": _json_clone(ctx.get(SESSION_EVENTS_CTX_KEY) or []),
    }


def get_generic_clarification_state(
    ctx: Optional[MutableMapping[str, Any]],
) -> Dict[str, Any]:
    if not isinstance(ctx, MutableMapping):
        return {"answered_keys": [], "answers": []}
    _ensure_ctx_state(ctx)
    state = ctx.get(SESSION_GENERIC_CLARIFICATION_CTX_KEY)
    if not isinstance(state, dict):
        state = {"answered_keys": [], "answers": []}
        ctx[SESSION_GENERIC_CLARIFICATION_CTX_KEY] = state
        _persist_ctx_session_state(ctx)
    return _json_clone(state)


def record_generic_clarification_answer(
    ctx: Optional[MutableMapping[str, Any]],
    decision: Dict[str, Any],
    answer: str,
) -> None:
    if not isinstance(ctx, MutableMapping):
        return
    _ensure_ctx_state(ctx)
    state = ctx.get(SESSION_GENERIC_CLARIFICATION_CTX_KEY)
    if not isinstance(state, dict):
        state = {"answered_keys": [], "answers": []}
        ctx[SESSION_GENERIC_CLARIFICATION_CTX_KEY] = state

    answered_keys = state.setdefault("answered_keys", [])
    answers = state.setdefault("answers", [])
    if not isinstance(answered_keys, list) or not isinstance(answers, list):
        state["answered_keys"] = []
        state["answers"] = []
        answered_keys = state["answered_keys"]
        answers = state["answers"]

    clarification_key = str(decision.get("clarification_key") or "").strip()
    question = str(decision.get("question") or "").strip()
    normalized_answer = str(answer or "").strip()

    if clarification_key and clarification_key not in answered_keys:
        answered_keys.append(clarification_key)
    answers.append(
        {
            "clarification_key": clarification_key or None,
            "question": question or None,
            "answer": normalized_answer or None,
        }
    )
    if len(answers) > 12:
        del answers[:-12]
    _persist_ctx_session_state(ctx)


def normalize_capability_intent(
    query: str,
    *,
    ctx: Optional[MutableMapping[str, Any]] = None,
) -> Optional[str]:
    text = _normalize_text(query)
    if not text:
        return None

    if any(token in text for token in ("timeseries", "time series")):
        if any(token in text for token in ("extract", "atlas", "roi", "masker", "label", "labels")):
            return "extract_timeseries"
    if any(token in text for token in ("confound", "confounds", "nuisance", "denoise", "regress", "regression")):
        return "clean_confounds"
    if "connectivity" in text and any(token in text for token in ("workflow", "pipeline")):
        return "connectivity_pipeline"

    if isinstance(ctx, MutableMapping):
        predicted = ctx.get("predicted_capabilities")
        if isinstance(predicted, Iterable) and not isinstance(predicted, (str, bytes)):
            for item in predicted:
                if item:
                    return _normalize_text(str(item))
    return None


def infer_derivative_family(query: str) -> Optional[str]:
    text = _normalize_text(query)
    if not text:
        return None
    for family, hints in _DERIVATIVE_HINTS.items():
        if any(hint in text for hint in hints):
            return family
    return None


def build_pending_decision(capability_intent: str) -> Optional[Dict[str, Any]]:
    if capability_intent == "extract_timeseries":
        return {
            "capability_intent": capability_intent,
            "question": (
                "I couldn't find a hosted ROI time-series extraction tool. "
                "Use a local Nilearn implementation instead, or should I keep searching?"
            ),
            "recommended_choice": "local_nilearn",
            "options": ["local_nilearn", "search_more"],
        }
    if capability_intent == "clean_confounds":
        return {
            "capability_intent": capability_intent,
            "question": (
                "I couldn't find a hosted confound-cleaning tool. "
                "Use a local Nilearn-based confound regression step instead, or should I keep searching?"
            ),
            "recommended_choice": "local_nilearn",
            "options": ["local_nilearn", "search_more"],
        }
    return None


def serialize_query_understanding(qur: Any) -> Dict[str, Any]:
    from brain_researcher.services.agent.query_models import QueryUnderstandingModel

    if isinstance(qur, dict):
        return _json_clone(qur)
    model = QueryUnderstandingModel.from_dataclass(qur)
    return model.model_dump(mode="json")


def deserialize_query_understanding(payload: Dict[str, Any]) -> Any:
    from brain_researcher.services.agent.query_models import QueryUnderstandingModel

    model = QueryUnderstandingModel.model_validate(payload)
    return model.to_dataclass()


class PlatformKnowledgeStore:
    """Redis-backed coarse knowledge shared across sessions."""

    def __init__(self, namespace: str = "brain_researcher:resolution") -> None:
        self.namespace = namespace
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        try:
            import redis

            self.redis = redis.from_url(redis_url, decode_responses=True)
            self.redis.ping()
        except Exception as exc:
            logger.debug("Resolution memory Redis unavailable (%s); using fakeredis", exc)
            import fakeredis

            self.redis = fakeredis.FakeRedis(decode_responses=True)

    @property
    def positive_ttl_seconds(self) -> int:
        return int(os.getenv("BR_RESOLUTION_KNOWLEDGE_TTL_S", str(7 * 24 * 3600)))

    @property
    def negative_ttl_seconds(self) -> int:
        return int(os.getenv("BR_RESOLUTION_NEGATIVE_TTL_S", str(24 * 3600)))

    def _set(self, key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
        self.redis.setex(key, max(1, ttl_seconds), json.dumps(value, default=str))

    def _get(self, key: str) -> Optional[Dict[str, Any]]:
        raw = self.redis.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def dataset_key(self, dataset_ref: str, derivative_family: str) -> str:
        return f"{self.namespace}:dataset:{_normalize_text(dataset_ref)}:{_normalize_text(derivative_family)}"

    def capability_key(self, capability_intent: str, runtime_surface: str) -> str:
        return f"{self.namespace}:capability:{_normalize_text(runtime_surface)}:{_normalize_text(capability_intent)}"

    def get_dataset_resolution(self, dataset_ref: str, derivative_family: str) -> Optional[Dict[str, Any]]:
        return self._get(self.dataset_key(dataset_ref, derivative_family))

    def set_dataset_resolution(
        self,
        dataset_ref: str,
        derivative_family: str,
        *,
        resolved_id_or_path: str,
        source_run_id: Optional[str] = None,
    ) -> None:
        value = {
            "status": "resolved",
            "resolved_id_or_path": str(resolved_id_or_path),
            "source_run_id": source_run_id,
            "ts": time.time(),
        }
        self._set(
            self.dataset_key(dataset_ref, derivative_family),
            value,
            self.positive_ttl_seconds,
        )

    def get_capability(self, capability_intent: str, runtime_surface: str) -> Optional[Dict[str, Any]]:
        return self._get(self.capability_key(capability_intent, runtime_surface))

    def set_capability(
        self,
        capability_intent: str,
        runtime_surface: str,
        *,
        status: str,
        resolved_id_or_path: Optional[str] = None,
        source_run_id: Optional[str] = None,
    ) -> None:
        value = {
            "status": str(status),
            "resolved_id_or_path": resolved_id_or_path,
            "source_run_id": source_run_id,
            "ts": time.time(),
        }
        ttl = self.negative_ttl_seconds if status == "negative" else self.positive_ttl_seconds
        self._set(self.capability_key(capability_intent, runtime_surface), value, ttl)

    def invalidate_capability_entries(self, runtime_surface: Optional[str] = None) -> int:
        if runtime_surface:
            pattern = f"{self.namespace}:capability:{_normalize_text(runtime_surface)}:*"
        else:
            pattern = f"{self.namespace}:capability:*"
        deleted = 0
        for key in self.redis.scan_iter(match=pattern):
            deleted += int(self.redis.delete(key) or 0)
        return deleted


def get_platform_knowledge_store() -> PlatformKnowledgeStore:
    global _PLATFORM_STORE
    if _PLATFORM_STORE is not None:
        return _PLATFORM_STORE
    with _PLATFORM_STORE_LOCK:
        if _PLATFORM_STORE is None:
            _PLATFORM_STORE = PlatformKnowledgeStore()
    return _PLATFORM_STORE


def invalidate_capability_knowledge(runtime_surface: Optional[str] = None) -> int:
    return get_platform_knowledge_store().invalidate_capability_entries(runtime_surface)


def harvest_dataset_knowledge(qur: Any, *, source_run_id: Optional[str] = None) -> None:
    store = get_platform_knowledge_store()
    resolved = list(getattr(qur, "resolved_datasets", []) or [])
    derivative_hits = list(getattr(qur, "existing_derivatives", []) or [])

    for dataset in resolved:
        dataset_ref = getattr(dataset, "dataset_id", None)
        if not dataset_ref:
            continue
        resources = getattr(dataset, "resources", None)
        derivatives = getattr(resources, "derivatives", {}) if resources else {}
        if isinstance(derivatives, dict):
            for family, raw_path in derivatives.items():
                if raw_path:
                    store.set_dataset_resolution(
                        dataset_ref,
                        family,
                        resolved_id_or_path=str(raw_path),
                        source_run_id=source_run_id,
                    )

    for hit in derivative_hits:
        dataset_ref = getattr(hit, "dataset_id", None)
        family = getattr(hit, "kind", None)
        path = getattr(hit, "path", None)
        if dataset_ref and family and path:
            store.set_dataset_resolution(
                dataset_ref,
                family,
                resolved_id_or_path=str(path),
                source_run_id=source_run_id,
            )


def apply_dataset_knowledge(
    qur: Any,
    *,
    query: str,
    ctx: Optional[MutableMapping[str, Any]] = None,
) -> bool:
    family = infer_derivative_family(query)
    if not family:
        return False

    store = get_platform_knowledge_store()
    applied = False
    derivative_hits = list(getattr(qur, "existing_derivatives", []) or [])

    for dataset in list(getattr(qur, "resolved_datasets", []) or []):
        dataset_ref = getattr(dataset, "dataset_id", None)
        if not dataset_ref:
            continue

        resources = getattr(dataset, "resources", None)
        derivatives = getattr(resources, "derivatives", {}) if resources else {}
        if isinstance(derivatives, dict) and derivatives.get(family):
            continue
        if any(
            getattr(hit, "dataset_id", None) == dataset_ref and getattr(hit, "kind", None) == family
            for hit in derivative_hits
        ):
            continue

        entry = store.get_dataset_resolution(dataset_ref, family)
        if not entry or entry.get("status") != "resolved" or not entry.get("resolved_id_or_path"):
            continue

        resolved_path = str(entry["resolved_id_or_path"])
        if resources is not None:
            resources.derivatives.setdefault(family, resolved_path)
            available = list(getattr(resources, "available_derivatives", []) or [])
            if family not in available:
                available.append(family)
                resources.available_derivatives = sorted(set(available))

        try:
            from brain_researcher.services.agent.kg_resolution import DerivativeHit

            derivative_hits.append(
                DerivativeHit(
                    dataset_id=dataset_ref,
                    kind=family,
                    path=Path(resolved_path),
                    description="Cached derivative availability",
                    metadata={"source": "platform_knowledge"},
                )
            )
            qur.existing_derivatives = derivative_hits
        except Exception:
            pass

        applied = True
        set_step_status(
            ctx,
            "dataset_resolution",
            status="confirmed",
            source="platform_knowledge",
            detail={"dataset_ref": dataset_ref, "derivative_family": family},
        )
        record_event(
            ctx,
            "resolution_cache_hit",
            layer="platform",
            cache_family="dataset_resolution",
            cache_key=f"{dataset_ref}:{family}",
        )
    return applied


__all__ = [
    "SESSION_GENERIC_CLARIFICATION_CTX_KEY",
    "SESSION_OVERRIDES_CTX_KEY",
    "add_pending_decision",
    "apply_dataset_knowledge",
    "build_pending_decision",
    "build_step_signature",
    "clear_pending_decisions",
    "deserialize_query_understanding",
    "export_resolution_state",
    "get_generic_clarification_state",
    "get_override",
    "get_overrides",
    "get_pending_decisions",
    "get_platform_knowledge_store",
    "get_session_entry",
    "harvest_dataset_knowledge",
    "infer_derivative_family",
    "invalidate_capability_knowledge",
    "normalize_capability_intent",
    "pop_pending_decision",
    "record_event",
    "record_generic_clarification_answer",
    "resolve_runtime_surface",
    "serialize_query_understanding",
    "set_override",
    "set_session_entry",
    "set_step_status",
]
