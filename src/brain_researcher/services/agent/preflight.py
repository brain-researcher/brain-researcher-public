"""Preflight helpers to enrich context with query understanding + KG tool hints."""

from __future__ import annotations

import logging
import os
import shutil
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from brain_researcher.services.agent.domain_knowledge import get_domain_knowledge
from brain_researcher.services.agent.kg_resolution import (
    QueryUnderstandingResult,
    build_query_understanding_result,
)
from brain_researcher.services.agent.query_understanding import (
    ParsedQuery,
    QueryIntent,
    create_advanced_parser,
)
from brain_researcher.services.agent.resolution_memory import (
    add_pending_decision,
    apply_dataset_knowledge,
    build_pending_decision,
    build_step_signature,
    clear_pending_decisions,
    deserialize_query_understanding,
    get_override,
    get_platform_knowledge_store,
    get_session_entry,
    harvest_dataset_knowledge,
    normalize_capability_intent,
    record_event,
    resolve_runtime_surface,
    serialize_query_understanding,
    set_session_entry,
    set_step_status,
)

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _minimal_parsed_query(query: str) -> ParsedQuery:
    normalized = " ".join((query or "").strip().split())
    return ParsedQuery(
        original_query=query,
        normalized_query=normalized,
        primary_intent=QueryIntent.ANALYSIS,
        secondary_intents=[],
        entities=[],
        expansion=None,
        context_vector=None,
        complexity_score=0.0,
        confidence=0.0,
        metadata={"fallback": True},
    )


def _tool_candidate_source_counts(
    candidates: Sequence[dict[str, Any]] | None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        source = str(candidate.get("source") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return counts


def _store_tool_candidate_diagnostics(
    ctx: dict[str, Any] | None,
    *,
    candidates: Sequence[dict[str, Any]] | None,
    start_time: float,
    retrieval_path: str,
    cache_hit: bool = False,
) -> dict[str, Any]:
    diagnostics = {
        "surface": resolve_runtime_surface(ctx, default="agent"),
        "candidate_count": len(candidates or []),
        "candidate_source_counts": _tool_candidate_source_counts(candidates),
        "candidate_generation_latency_ms": round(
            (time.perf_counter() - start_time) * 1000.0, 3
        ),
        "routing_latency_ms": round((time.perf_counter() - start_time) * 1000.0, 3),
        "retrieval_path": retrieval_path,
        "cache_hit": cache_hit,
    }
    source_counts = diagnostics["candidate_source_counts"]
    diagnostics["candidate_source"] = (
        next(iter(source_counts.keys()))
        if len(source_counts) == 1
        else "mixed" if source_counts else None
    )
    if isinstance(ctx, dict):
        ctx["tool_candidate_diagnostics"] = diagnostics
    return diagnostics


def ensure_query_understanding(
    query: str,
    ctx: dict[str, Any] | None = None,
    *,
    parser=None,
) -> QueryUnderstandingResult | None:
    """Attach QueryUnderstandingResult into ctx when missing (best-effort)."""

    if not query:
        return None

    if isinstance(ctx, dict) and ctx.get("query_understanding"):
        return ctx["query_understanding"]

    step_signature = build_step_signature("query_understanding", query)
    cached_entry = get_session_entry(ctx, step_signature)
    if cached_entry and cached_entry.get("status") == "resolved":
        payload = cached_entry.get("value")
        if isinstance(payload, dict):
            try:
                qur = deserialize_query_understanding(payload)
                if isinstance(ctx, dict):
                    ctx["query_understanding"] = qur
                set_step_status(
                    ctx,
                    "query_understanding",
                    status="confirmed",
                    source="session_cache",
                )
                record_event(
                    ctx,
                    "resolution_cache_hit",
                    layer="session",
                    cache_family="query_understanding",
                    cache_key=step_signature,
                )
                return qur
            except Exception as exc:
                logger.debug(
                    "Failed to deserialize cached query understanding: %s", exc
                )

    record_event(
        ctx,
        "resolution_cache_miss",
        layer="session",
        cache_family="query_understanding",
        cache_key=step_signature,
    )

    try:
        if parser is None:
            parser = create_advanced_parser(
                domain_knowledge=get_domain_knowledge(), llm=None
            )
        parsed = parser.parse(query, context=ctx or {})
    except Exception as exc:
        logger.debug("Query understanding parser failed: %s", exc)
        parsed = _minimal_parsed_query(query)

    try:
        qur = build_query_understanding_result(parsed)
    except Exception as exc:
        logger.debug("Query understanding build failed: %s", exc)
        return None

    if isinstance(ctx, dict):
        ctx["query_understanding"] = qur
    apply_dataset_knowledge(qur, query=query, ctx=ctx)
    harvest_dataset_knowledge(
        qur,
        source_run_id=(ctx or {}).get("run_id") if isinstance(ctx, dict) else None,
    )
    set_session_entry(
        ctx,
        step_signature,
        {"status": "resolved", "value": serialize_query_understanding(qur)},
    )
    set_step_status(
        ctx,
        "query_understanding",
        status="confirmed",
        source="fresh",
    )
    return qur


def _extract_tool_id(candidate: Any) -> str | None:
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        for key in ("tool_id", "id", "name", "source_id"):
            value = candidate.get(key)
            if value:
                return str(value)
        return None
    for attr in ("tool_id", "id", "name"):
        value = getattr(candidate, attr, None)
        if value:
            return str(value)
    return None


def _registry_has_tool(registry: Any, tool_id: str | None) -> bool:
    if registry is None or not tool_id:
        return False
    try:
        getter = getattr(registry, "get_tool", None)
        if getter and getter(tool_id) is not None:
            return True
    except Exception:
        pass
    try:
        getter = getattr(registry, "get_runtime_tool", None)
        if getter and getter(tool_id) is not None:
            return True
    except Exception:
        pass
    try:
        tools = getattr(registry, "tools", None)
        if isinstance(tools, dict) and tool_id in tools:
            return True
    except Exception:
        pass
    return False


def _iter_tool_id_variants(tool_id: str) -> list[str]:
    variants: list[str] = []

    def add(value: str | None) -> None:
        if value and value not in variants:
            variants.append(value)

    raw = (tool_id or "").strip()
    if not raw:
        return variants

    add(raw)

    prefixes = ("python.", "container.", "mcp.")
    for prefix in prefixes:
        if raw.startswith(prefix):
            add(raw[len(prefix) :])

    def strip_run(value: str) -> str:
        return value[:-4] if value.endswith(".run") else value

    for value in list(variants):
        stripped = strip_run(value)
        add(stripped)

    for value in list(variants):
        if "." in value:
            add(value.replace(".", "_"))

    return variants


def _canonicalize_tool_id(raw_id: str | None, registry: Any) -> str | None:
    if not raw_id:
        return None

    normalized = str(raw_id).strip()
    if not normalized:
        return None

    try:
        from brain_researcher.services.tools.catalog_loader import (
            resolve_primary_runtime_tool_id,
            resolve_runtime_tool_ids,
        )
    except Exception:
        resolve_primary_runtime_tool_id = None  # type: ignore
        resolve_runtime_tool_ids = None  # type: ignore

    primary_runtime = (
        resolve_primary_runtime_tool_id(normalized)
        if resolve_primary_runtime_tool_id
        else None
    )

    if registry is None:
        return primary_runtime or normalized

    if primary_runtime and _registry_has_tool(registry, primary_runtime):
        return primary_runtime

    if _registry_has_tool(registry, normalized):
        return normalized

    candidates: list[str] = []
    if primary_runtime:
        candidates.append(primary_runtime)

    if resolve_runtime_tool_ids:
        candidates.extend(resolve_runtime_tool_ids(normalized, include_self=False))

    candidates.extend(_iter_tool_id_variants(normalized))

    seen: set[str] = {normalized}
    if primary_runtime:
        seen.add(primary_runtime)
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if _registry_has_tool(registry, candidate):
            return candidate

    return primary_runtime or normalized


def _normalize_tool_candidate(
    candidate: Any,
    *,
    registry: Any,
    catalog_lookup: Any = None,
    default_source: str = "br_kg",
    default_rank: int | None = None,
) -> dict[str, Any] | None:
    raw_tool_id = _extract_tool_id(candidate)
    if not raw_tool_id:
        return None

    effective_id = _canonicalize_tool_id(raw_tool_id, registry) or raw_tool_id
    payload = dict(candidate) if isinstance(candidate, dict) else {}
    payload["tool_id"] = effective_id
    payload["tool_id_raw"] = raw_tool_id

    if payload.get("source") in (None, ""):
        payload["source"] = default_source

    if payload.get("rank") in (None, "") and default_rank is not None:
        payload["rank"] = default_rank

    if payload.get("score") is not None:
        score = payload.get("score")
        if isinstance(score, int | float):
            payload["score"] = float(score)

    if registry is not None:
        registry_available = _registry_has_tool(registry, effective_id)
        payload["available"] = registry_available
        payload["registry_available"] = registry_available
    else:
        payload.setdefault("available", None)
        payload.setdefault("registry_available", None)

    if catalog_lookup is not None:
        catalog_available = None
        try:
            catalog_available = catalog_lookup(raw_tool_id) is not None
            if (
                catalog_available is False
                and effective_id
                and effective_id != raw_tool_id
            ):
                catalog_available = catalog_lookup(effective_id) is not None
        except Exception:
            catalog_available = None
        payload["catalog_available"] = catalog_available
    else:
        payload.setdefault("catalog_available", None)

    return payload


def ensure_tool_candidates(
    query: str,
    ctx: dict[str, Any] | None = None,
    *,
    tool_retriever=None,
    registry=None,
    top_k: int = 12,
) -> list[dict[str, Any]]:
    """Attach KG-backed tool candidates into ctx when missing (best-effort)."""

    if not query:
        return []

    started_at = time.perf_counter()
    runtime_surface = resolve_runtime_surface(ctx, default="agent")

    if isinstance(ctx, dict) and ctx.get("tool_candidates"):
        existing = ctx.get("tool_candidates") or []
        existing_list = list(existing) if isinstance(existing, Iterable) else []
        existing_list = [
            normalized
            for idx, candidate in enumerate(existing_list, start=1)
            if (
                normalized := _normalize_tool_candidate(
                    candidate,
                    registry=registry,
                    default_rank=idx,
                )
            )
            is not None
        ]
        if isinstance(ctx, dict):
            ctx["tool_candidates"] = existing_list
        _store_tool_candidate_diagnostics(
            ctx,
            candidates=existing_list,
            start_time=started_at,
            retrieval_path="existing_ctx",
            cache_hit=True,
        )
        return existing_list

    step_signature = build_step_signature("tool_candidates", query)
    cached_entry = get_session_entry(ctx, step_signature)
    if cached_entry and cached_entry.get("status") == "resolved":
        cached_value = cached_entry.get("value")
        if isinstance(cached_value, list):
            normalized_cached = [
                normalized
                for idx, candidate in enumerate(cached_value, start=1)
                if (
                    normalized := _normalize_tool_candidate(
                        candidate,
                        registry=registry,
                        default_rank=idx,
                    )
                )
                is not None
            ]
            if isinstance(ctx, dict):
                ctx["tool_candidates"] = normalized_cached
            set_step_status(
                ctx,
                "tool_candidates",
                status="confirmed",
                source="session_cache",
            )
            record_event(
                ctx,
                "resolution_cache_hit",
                layer="session",
                cache_family="capability",
                cache_key=step_signature,
            )
            _store_tool_candidate_diagnostics(
                ctx,
                candidates=normalized_cached,
                start_time=started_at,
                retrieval_path="session_cache",
                cache_hit=True,
            )
            return normalized_cached

    record_event(
        ctx,
        "resolution_cache_miss",
        layer="session",
        cache_family="capability",
        cache_key=step_signature,
    )

    capability_intent = normalize_capability_intent(query, ctx=ctx)
    override = get_override(ctx, capability_intent) if capability_intent else None
    platform_store = get_platform_knowledge_store()
    force_fresh_capability_lookup = (
        isinstance(ctx, dict)
        and capability_intent
        and ctx.pop("_resolution_force_capability_lookup", None) == capability_intent
    )

    if force_fresh_capability_lookup:
        clear_pending_decisions(ctx, capability_intent)
        record_event(
            ctx,
            "resolution_decision_applied",
            layer="session",
            cache_family="capability",
            cache_key=capability_intent,
            payload={"choice": "search_more"},
        )

    if capability_intent and override and override != "search_more":
        clear_pending_decisions(ctx, capability_intent)
        set_step_status(
            ctx,
            "tool_candidates",
            status="needs_verification",
            source="user_override",
            detail={"capability_intent": capability_intent, "choice": override},
        )
        set_session_entry(ctx, step_signature, {"status": "resolved", "value": []})
        _store_tool_candidate_diagnostics(
            ctx,
            candidates=[],
            start_time=started_at,
            retrieval_path="user_override",
        )
        return []

    if capability_intent:
        platform_entry = platform_store.get_capability(
            capability_intent, runtime_surface
        )
        if (
            not force_fresh_capability_lookup
            and platform_entry
            and platform_entry.get("status") == "negative"
        ):
            decision = build_pending_decision(capability_intent)
            if decision:
                add_pending_decision(ctx, decision)
                record_event(
                    ctx,
                    "resolution_decision_required",
                    layer="platform",
                    cache_family="capability",
                    cache_key=capability_intent,
                    payload={"runtime_surface": runtime_surface},
                )
            set_step_status(
                ctx,
                "tool_candidates",
                status="needs_verification",
                source="platform_knowledge",
                detail={"capability_intent": capability_intent},
            )
            record_event(
                ctx,
                "resolution_cache_hit",
                layer="platform",
                cache_family="capability",
                cache_key=capability_intent,
            )
            if isinstance(ctx, dict):
                ctx["tool_candidates"] = []
            set_session_entry(ctx, step_signature, {"status": "resolved", "value": []})
            _store_tool_candidate_diagnostics(
                ctx,
                candidates=[],
                start_time=started_at,
                retrieval_path="platform_knowledge_negative",
                cache_hit=True,
            )
            return []
        if (
            platform_entry
            and platform_entry.get("status") == "resolved"
            and platform_entry.get("resolved_id_or_path")
        ):
            tool_id = str(platform_entry["resolved_id_or_path"])
            candidate = _normalize_tool_candidate(
                {
                    "tool_id": tool_id,
                    "tool_id_raw": tool_id,
                    "score": 1.0,
                    "source": "platform_knowledge",
                    "rank": 1,
                },
                registry=registry,
                default_source="platform_knowledge",
            )
            if candidate is None:
                candidate = {
                    "tool_id": tool_id,
                    "tool_id_raw": tool_id,
                    "score": 1.0,
                    "source": "platform_knowledge",
                    "available": None,
                    "registry_available": None,
                    "catalog_available": None,
                    "rank": 1,
                }
            if isinstance(ctx, dict):
                ctx["tool_candidates"] = [candidate]
            clear_pending_decisions(ctx, capability_intent)
            set_step_status(
                ctx,
                "tool_candidates",
                status="confirmed",
                source="platform_knowledge",
                detail={
                    "capability_intent": capability_intent,
                    "tool_id": candidate["tool_id"],
                },
            )
            record_event(
                ctx,
                "resolution_cache_hit",
                layer="platform",
                cache_family="capability",
                cache_key=capability_intent,
            )
            set_session_entry(
                ctx, step_signature, {"status": "resolved", "value": [candidate]}
            )
            _store_tool_candidate_diagnostics(
                ctx,
                candidates=[candidate],
                start_time=started_at,
                retrieval_path="platform_knowledge",
                cache_hit=True,
            )
            return [candidate]

    if (
        os.getenv("PYTEST_CURRENT_TEST")
        and os.getenv("BR_USE_TOOL_RETRIEVER") is None
        and tool_retriever is None
    ):
        _store_tool_candidate_diagnostics(
            ctx,
            candidates=[],
            start_time=started_at,
            retrieval_path="pytest_disabled",
        )
        return []

    if (
        os.getenv("BR_USE_TOOL_RETRIEVER") is None
        and tool_retriever is None
        and runtime_surface in {"plan", "plan_preflight"}
    ):
        _store_tool_candidate_diagnostics(
            ctx,
            candidates=[],
            start_time=started_at,
            retrieval_path="surface_default_disabled",
        )
        return []

    if not _env_flag("BR_USE_TOOL_RETRIEVER", True):
        _store_tool_candidate_diagnostics(
            ctx,
            candidates=[],
            start_time=started_at,
            retrieval_path="retriever_disabled",
        )
        return []

    if tool_retriever is None:
        try:
            from brain_researcher.services.agent.tool_retriever import ToolRetriever

            tool_retriever = ToolRetriever()
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("ToolRetriever unavailable: %s", exc)
            _store_tool_candidate_diagnostics(
                ctx,
                candidates=[],
                start_time=started_at,
                retrieval_path="retriever_unavailable",
            )
            return []

    filters = {}
    if isinstance(ctx, dict):
        if ctx.get("disable_gfs") or ctx.get("disable_literature"):
            filters["disable_gfs"] = True

    try:
        matches = tool_retriever.retrieve_tools(
            query=query, family_ids=None, top_k=top_k, filters=filters or None
        )
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("ToolRetriever failed: %s", exc)
        _store_tool_candidate_diagnostics(
            ctx,
            candidates=[],
            start_time=started_at,
            retrieval_path="retriever_failed",
        )
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    catalog_lookup = None
    if registry is None:
        try:
            from brain_researcher.services.agent.planner.catalog_loader import (
                get_tool_by_id,
            )

            catalog_lookup = get_tool_by_id
        except Exception:
            catalog_lookup = None
    for idx, match in enumerate(matches or []):
        raw_tool_id = _extract_tool_id(match)
        if not raw_tool_id:
            continue

        normalized_candidate = _normalize_tool_candidate(
            {
                "tool_id": raw_tool_id,
                "tool_id_raw": raw_tool_id,
                "score": (
                    getattr(match, "score", None)
                    if not isinstance(match, dict)
                    else match.get("score")
                ),
                "source": (
                    getattr(match, "source", None)
                    if not isinstance(match, dict)
                    else match.get("source")
                ),
                "rank": idx + 1,
            },
            registry=registry,
            catalog_lookup=catalog_lookup,
            default_rank=idx + 1,
        )
        if normalized_candidate is None:
            continue
        effective_id = str(normalized_candidate.get("tool_id") or "").strip()
        if not effective_id or effective_id in seen:
            continue
        seen.add(effective_id)
        candidates.append(normalized_candidate)

    if isinstance(ctx, dict) and candidates:
        ctx["tool_candidates"] = candidates

    retrieval_path = "fresh"
    if tool_retriever is not None:
        if getattr(tool_retriever, "use_query_service", False):
            retrieval_path = "query_service"
        elif getattr(tool_retriever, "embed_model", None) is not None:
            retrieval_path = "embedding"

    if candidates:
        set_session_entry(
            ctx, step_signature, {"status": "resolved", "value": candidates}
        )
        set_step_status(
            ctx,
            "tool_candidates",
            status="confirmed",
            source="fresh",
            detail={"count": len(candidates)},
        )
        if capability_intent:
            top_tool = candidates[0].get("tool_id")
            if top_tool:
                platform_store.set_capability(
                    capability_intent,
                    runtime_surface,
                    status="resolved",
                    resolved_id_or_path=str(top_tool),
                    source_run_id=(
                        (ctx or {}).get("run_id") if isinstance(ctx, dict) else None
                    ),
                )
                clear_pending_decisions(ctx, capability_intent)
    else:
        set_session_entry(ctx, step_signature, {"status": "resolved", "value": []})
        if capability_intent:
            platform_store.set_capability(
                capability_intent,
                runtime_surface,
                status="negative",
                resolved_id_or_path=None,
                source_run_id=(
                    (ctx or {}).get("run_id") if isinstance(ctx, dict) else None
                ),
            )
            decision = build_pending_decision(capability_intent)
            if decision:
                add_pending_decision(ctx, decision)
                record_event(
                    ctx,
                    "resolution_discovery_bounded",
                    layer="fresh",
                    cache_family="capability",
                    cache_key=capability_intent,
                    payload={"runtime_surface": runtime_surface},
                )
                record_event(
                    ctx,
                    "resolution_decision_required",
                    layer="fresh",
                    cache_family="capability",
                    cache_key=capability_intent,
                    payload={"runtime_surface": runtime_surface},
                )
                set_step_status(
                    ctx,
                    "tool_candidates",
                    status="needs_verification",
                    source="fresh",
                    detail={"capability_intent": capability_intent},
                )
            else:
                set_step_status(
                    ctx,
                    "tool_candidates",
                    status="unresolved",
                    source="fresh",
                )
        else:
            set_step_status(
                ctx,
                "tool_candidates",
                status="unresolved",
                source="fresh",
            )

    _store_tool_candidate_diagnostics(
        ctx,
        candidates=candidates,
        start_time=started_at,
        retrieval_path=retrieval_path,
    )
    return candidates


__all__ = [
    "ensure_query_understanding",
    "ensure_tool_candidates",
    "resolve_attachments_for_tool",
    "PreflightConfig",
    "PreflightItem",
    "PreflightMode",
    "PreflightReport",
    "run_preflight",
    "preflight_batch",
]


class PreflightMode(str, Enum):
    OFF = "OFF"
    WARN = "WARN"
    HARD_FAIL = "HARD_FAIL"

    @classmethod
    def from_env(cls) -> PreflightMode:
        raw = os.getenv("BR_PREFLIGHT_MODE", "WARN").upper()
        if raw in cls.__members__:
            return cls[raw]
        return cls.WARN


@dataclass(frozen=True)
class PreflightConfig:
    min_disk_gb: float = 1.0
    check_timeout_sec: int = 2
    root_path: Path = Path(".")

    @classmethod
    def from_env(cls) -> PreflightConfig:
        min_disk = os.getenv("BR_PREFLIGHT_MIN_DISK_GB")
        try:
            min_disk_gb = float(min_disk) if min_disk is not None else 1.0
        except ValueError:
            min_disk_gb = 1.0
        return cls(min_disk_gb=min_disk_gb, check_timeout_sec=2, root_path=Path("."))


class PreflightItem(BaseModel):
    check: str
    ok: bool
    detail: str | None = None

    @property
    def passed(self) -> bool:  # legacy alias
        return self.ok


class PreflightReport(BaseModel):
    ok: bool | None = None
    blockers: list[PreflightItem] = Field(default_factory=list)
    warnings: list[PreflightItem] = Field(default_factory=list)
    disk_free_gb: float | None = None

    @property
    def passed(self) -> bool:  # legacy alias for tests expecting .passed
        return self.ok if self.ok is not None else len(self.blockers) == 0

    @model_validator(mode="after")
    def _set_ok(self):
        if self.ok is None:
            self.ok = len(self.blockers) == 0
        return self


_PATH_SUFFIXES = (
    ".nii",
    ".nii.gz",
    ".tsv",
    ".csv",
    ".json",
    ".txt",
    ".fif",
    ".bval",
    ".bvec",
    ".nii.gz",
)


def _looks_like_path(value: str) -> bool:
    if value.startswith(("/", "./", "../")):
        return True
    if "/" in value or "\\" in value:
        return True
    return value.lower().endswith(_PATH_SUFFIXES)


def _iter_candidate_paths(value: Any) -> Iterable[Path]:
    if isinstance(value, Path):
        yield value
    elif isinstance(value, str):
        if _looks_like_path(value):
            yield Path(value)
    elif isinstance(value, list | tuple | set):
        for item in value:
            yield from _iter_candidate_paths(item)


async def resolve_attachments_for_tool(
    attachments: Sequence[dict[str, Any]],
    tool_name: str,
    *,
    resolver: Any = None,
) -> dict[str, str]:
    """Resolve attachments to local paths (best-effort)."""

    if not attachments:
        return {}

    resolved: dict[str, str] = {}
    for att in attachments:
        if not isinstance(att, dict):
            continue
        file_id = att.get("id")
        path = att.get("path")
        if file_id and path:
            try:
                if Path(path).exists():
                    resolved[str(file_id)] = str(path)
            except Exception:
                pass

    try:
        from brain_researcher.services.agent.file_resolver import FileResolver
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.warning("Attachment resolver unavailable for %s: %s", tool_name, exc)
        return resolved

    if resolver is None:
        resolver = FileResolver()

    try:
        batch = await resolver.resolve_batch(list(attachments))
        resolved.update(batch)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Attachment resolution failed for %s: %s", tool_name, exc)

    return resolved


def run_preflight(
    *,
    tool_name: str | None = None,
    params: dict[str, Any] | None = None,
    image_path: str | None = None,
    attachments: Sequence[dict[str, Any]] | None = None,
    config: PreflightConfig | None = None,
) -> PreflightReport:
    """Best-effort preflight checks for disk space + missing inputs."""

    cfg = config or PreflightConfig.from_env()
    blockers: list[PreflightItem] = []
    warnings: list[PreflightItem] = []

    disk_free_gb = None
    try:
        usage = shutil.disk_usage(cfg.root_path)
        disk_free_gb = usage.free / (1024**3)
        if disk_free_gb < cfg.min_disk_gb:
            blockers.append(
                PreflightItem(
                    check="disk_free_gb",
                    ok=False,
                    detail=f"free={disk_free_gb:.3f}GB < min={cfg.min_disk_gb:.3f}GB",
                )
            )
    except Exception as exc:  # pragma: no cover - best effort
        warnings.append(PreflightItem(check="disk_free_gb", ok=False, detail=str(exc)))

    missing_paths: list[str] = []
    for value in (params or {}).values():
        for path in _iter_candidate_paths(value):
            if not path.exists():
                missing_paths.append(str(path))

    if missing_paths:
        blockers.append(
            PreflightItem(
                check="input_files",
                ok=False,
                detail="missing: " + ", ".join(sorted(set(missing_paths))[:5]),
            )
        )

    if image_path and _looks_like_path(image_path):
        image = Path(image_path)
        if not image.exists():
            warnings.append(
                PreflightItem(
                    check="container_image",
                    ok=False,
                    detail=f"image not found: {image_path}",
                )
            )

    if attachments:
        for attachment in attachments:
            if isinstance(attachment, dict) and attachment.get("size", 1) == 0:
                warnings.append(
                    PreflightItem(
                        check="attachments",
                        ok=False,
                        detail=f"empty attachment: {attachment.get('name')}",
                    )
                )

    report = PreflightReport(
        blockers=blockers,
        warnings=warnings,
        disk_free_gb=disk_free_gb,
    )
    return report


def preflight_batch(
    tools: Iterable[Any], use_cache: bool = True
) -> dict[str, PreflightReport]:
    """Run preflight on an iterable of tool-like objects.

    This is a lightweight placeholder so unit tests can import and exercise the
    batching API without requiring heavy runtime checks.
    """

    results: dict[str, PreflightReport] = {}
    for idx, tool in enumerate(tools):
        tool_id = (
            getattr(tool, "id", None) or getattr(tool, "name", None) or f"tool-{idx}"
        )
        results[str(tool_id)] = run_preflight(tool_name=str(tool_id), config=None)
    return results
