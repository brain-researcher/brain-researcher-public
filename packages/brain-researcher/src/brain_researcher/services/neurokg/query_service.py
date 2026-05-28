"""Query-focused, read-only BR-KG service helpers.

This module exposes a thin, parameterised wrapper over Neo4j so that agent tools
can perform safe queries without embedding Cypher directly.  It is intentionally
lightweight and avoids returning heavy payloads.

The functions here are pure read operations and are safe to import from agents
or planners.  They all accept an optional ``db`` argument so tests can inject a
stub; in production the default cached Neo4j client is used.
"""

from __future__ import annotations

import functools
import hashlib
import importlib
import json
import logging
import math
import os
import re
import time
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from brain_researcher.core.literature.gfs_store import (
    _resolve_stores,
    classify_store_kind,
    route_gfs_stores,
    search_gfs,
)
from brain_researcher.core.literature.literature_priors import (
    infer_literature_priors,
    merge_priors,
)
from brain_researcher.services.neurokg.graph.neo4j_graph_database import (
    Neo4jGraphDB,
)
from brain_researcher.services.neurokg.query.evidence_pack import (
    EvidencePackConfig,
    build_evidence_pack,
)
from brain_researcher.services.neurokg.scoring.confidence_v2 import (
    EvidenceSignal,
    compute_confidence_v2,
)

logger = logging.getLogger(__name__)

_GENERIC_BEHAVIOR_TASK_LABELS = {
    "choice task",
    "memory task",
}
_GENERIC_BEHAVIOR_TASK_RE = re.compile(r"^exp\d+[a-z]?$")


def _deep_research_sync(request: dict[str, Any]) -> dict[str, Any]:
    module = importlib.import_module(
        "brain_researcher.core.literature.deep_research"
    )
    return module.deep_research_sync(request)


def _rank_wow_candidates(
    candidates: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    module = importlib.import_module(
        "brain_researcher.services.agent.wow_principle_controller"
    )
    return module.rank_wow_candidates(candidates)


def _rerank_leverage_items(
    principle_state: Mapping[str, Any] | None,
    leverage_rows: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    module = importlib.import_module(
        "brain_researcher.services.agent.principle_controller"
    )
    return module.rerank_leverage_items(principle_state, leverage_rows)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class KGNodeSummary:
    kg_id: str
    label: str
    node_type: str
    element_id: str | None = None
    score: float = 1.0
    properties: dict[str, Any] | None = None


@dataclass
class DatasetSummary:
    dataset_id: str
    title: str | None
    tasks: list[str]
    modalities: list[str]
    n_subjects: int | None
    kg_id: str
    species: str | None = None


@dataclass
class DatasetOnvocLinkSummary:
    dataset_id: str
    title: str | None
    kg_id: str
    primary_onvoc_id: str | None
    primary_onvoc_confidence: float | None
    onvoc_links: list[dict[str, Any]]


@dataclass
class DatasetResourceSummary:
    dataset_id: str
    resolved_dataset_id: str | None
    resolution_mode: str | None
    resolver_warnings: list[str]
    bids_path: str | None
    is_bids_available: bool
    derivatives: dict[str, str]
    available_derivatives: list[str]
    remote_urls: dict[str, str]
    size_bytes: int | None
    analysis_goal: str = "generic"
    source_trace: list[dict[str, Any]] = field(default_factory=list)
    required_files: dict[str, Any] = field(default_factory=dict)
    readiness: dict[str, Any] = field(default_factory=dict)
    auto_heal: dict[str, Any] = field(default_factory=dict)
    semantic_match: dict[str, Any] = field(default_factory=dict)
    source_access: dict[str, Any] = field(default_factory=dict)
    dataset_name: str = ""
    display_name: str = ""
    source_repo: str = ""
    local_path: str | None = None
    dataset_metadata: dict[str, Any] = field(default_factory=dict)
    mount_status: dict[str, Any] = field(default_factory=dict)
    kg_id: str | None = None


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------


_DOTENV_LOADED = False


def _maybe_load_repo_dotenv_for_neo4j() -> None:
    """Best-effort: load Neo4j env vars from the repo `.env` file.

    The local MCP server is often started without sourcing `.env`, so KG tools
    can silently fall back to default credentials and fail authentication.

    This helper only fills missing `NEO4J_*` keys and never overwrites existing
    environment variables.
    """

    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return

    if os.environ.get("NEO4J_PASSWORD"):
        _DOTENV_LOADED = True
        return

    dotenv_path = Path(__file__).resolve().parents[4] / ".env"
    if not dotenv_path.exists():
        _DOTENV_LOADED = True
        return

    try:
        for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key.startswith("NEO4J_"):
                continue
            if key in os.environ:
                continue
            value = value.strip().strip('"').strip("'")
            if value:
                os.environ[key] = value
    except Exception:  # pragma: no cover - best effort
        logger.debug("Failed to load Neo4j env vars from .env", exc_info=True)
    finally:
        _DOTENV_LOADED = True


@functools.lru_cache(maxsize=1)
def get_default_db() -> Neo4jGraphDB:
    """Create a cached Neo4j client from environment variables.

    The cache keeps the driver alive across tool calls while avoiding the heavy
    graph preload step.
    """

    _maybe_load_repo_dotenv_for_neo4j()

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    database = os.getenv("NEO4J_DATABASE")
    return Neo4jGraphDB(uri, user, password, database=database, preload_cache=False)


def _as_list(result: Iterable[Any]) -> list[Any]:
    """Consume a Neo4j result into a list.

    This helper makes it easy to test with simple iterables instead of the real
    Neo4j result type.
    """

    return list(result or [])


def _run_with_optional_timeout(
    client: Any,
    cypher: str,
    params: dict[str, Any] | None = None,
    *,
    timeout_s: float | None = None,
):
    """Execute cypher with optional per-call timeout and compatibility fallback."""

    run_params = params or {}
    if timeout_s is None:
        return client._run(cypher, run_params)
    try:
        return client._run(cypher, run_params, timeout_s=timeout_s)
    except TypeError as exc:
        if "timeout_s" not in str(exc):
            raise
        return client._run(cypher, run_params)


def _rec_get(record: Any, key: str, default: Any = None) -> Any:
    """Key lookup that works for neo4j.Record and dict alike."""

    try:
        return record[key]
    except Exception:
        try:
            return record.get(key, default)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defensive
            return default


def _node_id(node: Any) -> str:
    """Best-effort extraction of a node identifier."""

    if isinstance(node, dict):
        return node.get("id") or node.get("dataset_id") or node.get("uid") or ""
    # Neo4j Node
    for attr in ("element_id", "id", "_id"):
        if hasattr(node, attr):
            value = getattr(node, attr)
            if value:
                return value
    # Fallback: look inside properties
    try:
        return node.get("id")
    except Exception:  # pragma: no cover - defensive
        return ""


def _maybe_parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _normalize_prior_map(raw: Any) -> dict[str, float]:
    """Normalize a prior mapping into {name: probability}."""
    if raw is None:
        return {}
    raw = _maybe_parse_json(raw)
    if isinstance(raw, dict):
        cleaned: dict[str, float] = {}
        for k, v in raw.items():
            try:
                fv = float(v)
            except Exception:
                continue
            if not math.isfinite(fv):
                continue
            cleaned[str(k)] = fv
        total = sum(cleaned.values())
        if total <= 0:
            return {}
        return {k: v / total for k, v in cleaned.items()}
    if isinstance(raw, list):
        # Accept list of {name/value} or [name, value] pairs.
        tmp: dict[str, float] = {}
        for item in raw:
            if isinstance(item, dict):
                name = (
                    item.get("name")
                    or item.get("key")
                    or item.get("option")
                    or item.get("label")
                )
                val = (
                    item.get("value")
                    or item.get("weight")
                    or item.get("prob")
                    or item.get("probability")
                    or item.get("prior")
                )
                if name is None or val is None:
                    continue
                try:
                    tmp[str(name)] = float(val)
                except Exception:
                    continue
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                try:
                    tmp[str(item[0])] = float(item[1])
                except Exception:
                    continue
        total = sum(tmp.values())
        if total <= 0:
            return {}
        return {k: v / total for k, v in tmp.items()}
    return {}


def _extract_priors_from_node(node: Any) -> dict[str, dict[str, float]]:
    """Extract GLM priors from a KG node, normalizing each axis."""
    if not node:
        return {}

    def _get(key: str) -> Any:
        try:
            return node.get(key)
        except Exception:
            return None

    # Direct axes
    hrf = _normalize_prior_map(_get("hrf_basis") or _get("hrf"))
    conf = _normalize_prior_map(_get("confounds") or _get("confound_model"))
    hp = _normalize_prior_map(_get("high_pass") or _get("highpass"))

    # Nested map payloads
    axes = _maybe_parse_json(_get("axes") or _get("axis_priors") or _get("priors"))
    extra_axes: dict[str, dict[str, float]] = {}
    if isinstance(axes, dict):
        hrf = hrf or _normalize_prior_map(axes.get("hrf_basis") or axes.get("hrf"))
        conf = conf or _normalize_prior_map(
            axes.get("confounds") or axes.get("confound_model")
        )
        hp = hp or _normalize_prior_map(axes.get("high_pass") or axes.get("highpass"))
        for key, val in axes.items():
            if key in {
                "hrf_basis",
                "hrf",
                "confounds",
                "confound_model",
                "high_pass",
                "highpass",
            }:
                continue
            normalized = _normalize_prior_map(val)
            if normalized:
                extra_axes[str(key)] = normalized

    priors = {"hrf_basis": hrf, "confounds": conf, "high_pass": hp}
    for key, val in extra_axes.items():
        priors[key] = val
    return {k: v for k, v in priors.items() if v}


def get_glm_priors(
    *,
    task: str | None,
    study_id: str | None = None,
    db: Optional[Neo4jGraphDB] = None,
    limit: int = 3,
    scope: str | None = None,
    include_literature: bool | None = None,
) -> dict[str, Any] | None:
    """Fetch GLM priors from KG if available.

    Returns a dict with keys: priors, scanned, source, scope, support.
    """
    client = db or get_default_db()
    if client is None:
        return None
    task_value = (task or "").strip() or None
    scope_value = scope.lower() if scope else None
    if scope_value not in {None, "dataset", "task", "global"}:
        scope_value = None

    labels = [
        "GLMPrior",
        "GLMDesignPrior",
        "GLM_Prior",
        "StatsModelPrior",
    ]

    def _run_query(
        *,
        task_value: str | None,
        dataset_id: str | None,
        require_dataset: bool,
        require_task: bool,
        limit_value: int,
        allow_global: bool = False,
        use_relationships: bool = False,
    ) -> list[Any]:
        task_param = (task_value or "").lower() if task_value else None
        params = {
            "labels": labels,
            "task": task_param,
            "study_id": dataset_id,
            "limit": int(limit_value),
        }

        if use_relationships:
            if require_dataset:
                cypher = """
                MATCH (d:Dataset)
                WHERE d.dataset_id = $study_id OR d.id = $study_id OR d.name = $study_id
                MATCH (d)-[:HAS_GLM_PRIOR]->(p)
                WHERE any(lbl IN labels(p) WHERE lbl IN $labels)
                  AND ($task IS NULL OR toLower(coalesce(p.task, p.task_label, p.task_name, '')) = $task
                       OR toLower(coalesce(p.task, p.task_label, p.task_name, '')) CONTAINS $task)
                RETURN p AS prior
                LIMIT $limit
                """
                return _as_list(client._run(cypher, params))

            if require_task:
                cypher = """
                MATCH (t)
                WHERE any(lbl IN labels(t) WHERE lbl IN ['TaskSpec', 'Task'])
                  AND ($task IS NULL OR toLower(coalesce(t.name, t.task_label, t.task_name, '')) = $task
                       OR toLower(coalesce(t.name, t.task_label, t.task_name, '')) CONTAINS $task)
                MATCH (t)-[:HAS_GLM_PRIOR]->(p)
                WHERE any(lbl IN labels(p) WHERE lbl IN $labels)
                RETURN p AS prior
                LIMIT $limit
                """
                return _as_list(client._run(cypher, params))

        dataset_clause = ""
        task_clause = ""
        if require_dataset:
            dataset_clause = "AND (p.dataset_id = $study_id OR p.study_id = $study_id)"
        elif dataset_id is not None:
            dataset_clause = "AND (p.dataset_id IS NULL OR p.dataset_id = '' OR p.study_id IS NULL OR p.study_id = '')"

        if require_task:
            task_clause = (
                "AND ($task IS NULL OR toLower(coalesce(p.task, p.task_label, p.task_name, '')) = $task "
                "OR toLower(coalesce(p.task, p.task_label, p.task_name, '')) CONTAINS $task)"
            )
        elif allow_global:
            task_clause = (
                "AND (p.task IS NULL OR p.task = '' OR p.task IN ['__all__', 'all'])"
            )

        cypher = f"""
        MATCH (p)
        WHERE any(lbl IN labels(p) WHERE lbl IN $labels)
          {task_clause}
          {dataset_clause}
        RETURN p AS prior
        LIMIT $limit
        """
        return _as_list(client._run(cypher, params))

    # 1) Dataset-specific priors
    rows: list[Any] = []
    scope = None
    if study_id and scope_value in {None, "dataset"}:
        try:
            rows = _run_query(
                task_value=task_value,
                dataset_id=study_id,
                require_dataset=True,
                require_task=True,
                limit_value=limit,
                use_relationships=True,
            )
            if not rows:
                rows = _run_query(
                    task_value=task_value,
                    dataset_id=study_id,
                    require_dataset=True,
                    require_task=True,
                    limit_value=limit,
                )
            if rows:
                scope = "dataset"
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("KG GLM priors dataset query failed: %s", exc)
            rows = []

    # 2) Task-level priors (no dataset match)
    if not rows and scope_value in {None, "task"}:
        if scope_value == "task" and not task_value:
            rows = []
        else:
            try:
                rows = _run_query(
                    task_value=task_value,
                    dataset_id=None,
                    require_dataset=False,
                    require_task=True,
                    limit_value=limit,
                    use_relationships=True,
                )
                if not rows:
                    rows = _run_query(
                        task_value=task_value,
                        dataset_id=None,
                        require_dataset=False,
                        require_task=True,
                        limit_value=limit,
                    )
                if rows:
                    scope = "task"
            except Exception as exc:  # pragma: no cover - best effort
                logger.debug("KG GLM priors task query failed: %s", exc)
                rows = []

    # 3) Global priors
    if not rows and scope_value in {None, "global"}:
        try:
            rows = _run_query(
                task_value=None,
                dataset_id=None,
                require_dataset=False,
                require_task=False,
                allow_global=True,
                limit_value=limit,
            )
            if rows:
                scope = "global"
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("KG GLM priors global query failed: %s", exc)
            rows = []

    base_payload: dict[str, Any] | None = None
    priors: dict[str, dict[str, float]] = {}
    scanned = 0
    datasets: set[str] = set()
    tasks: set[str] = set()
    support_n_datasets_max = 0
    support_n_tasks_max = 0
    coverage_sums: dict[str, float] = {}
    coverage_weights: dict[str, float] = {}
    total_specs = 0

    def _node_prop(node: Any, key: str) -> Any:
        if node is None:
            return None
        if isinstance(node, dict):
            return node.get(key)
        try:
            return node.get(key)  # type: ignore[attr-defined]
        except Exception:
            return None

    if rows:
        for row in rows:
            node = _rec_get(row, "prior")
            extracted = _extract_priors_from_node(node)
            if extracted:
                for axis, vals in extracted.items():
                    priors.setdefault(axis, {})
                    for opt, val in vals.items():
                        priors[axis][opt] = priors[axis].get(opt, 0.0) + float(val)
                scanned += 1
                node_support_raw = _node_prop(node, "support")
                node_support = (
                    _maybe_parse_json(node_support_raw)
                    if node_support_raw is not None
                    else {}
                )
                if not isinstance(node_support, dict):
                    node_support = {}
                try:
                    support_n_datasets_max = max(
                        support_n_datasets_max, int(node_support.get("n_datasets", 0))
                    )
                except (TypeError, ValueError):
                    pass
                try:
                    support_n_tasks_max = max(
                        support_n_tasks_max, int(node_support.get("n_tasks", 0))
                    )
                except (TypeError, ValueError):
                    pass
                node_n_specs = (
                    node_support.get("n_specs")
                    or _node_prop(node, "n_specs")
                    or _node_prop(node, "support_n_specs")
                )
                try:
                    node_n_specs = int(node_n_specs) if node_n_specs is not None else 0
                except (TypeError, ValueError):
                    node_n_specs = 0
                if node_n_specs:
                    total_specs += node_n_specs
                node_coverage_raw = _node_prop(node, "coverage")
                node_coverage = (
                    _maybe_parse_json(node_coverage_raw)
                    if node_coverage_raw is not None
                    else {}
                )
                if not isinstance(node_coverage, dict):
                    node_coverage = {}
                if isinstance(node_coverage, dict):
                    # Keep coverage usable for legacy/partial priors that omit n_specs.
                    coverage_weight = float(node_n_specs) if node_n_specs else 1.0
                    for axis, value in node_coverage.items():
                        try:
                            cov_val = float(value)
                        except (TypeError, ValueError):
                            continue
                        coverage_sums[axis] = coverage_sums.get(axis, 0.0) + (
                            cov_val * coverage_weight
                        )
                        coverage_weights[axis] = (
                            coverage_weights.get(axis, 0.0) + coverage_weight
                        )
                dataset_val = _node_prop(node, "dataset_id") or _node_prop(
                    node, "study_id"
                )
                if dataset_val:
                    datasets.add(str(dataset_val))
                task_val = (
                    _node_prop(node, "task")
                    or _node_prop(node, "task_label")
                    or _node_prop(node, "task_name")
                )
                if task_val:
                    task_str = str(task_val)
                    if task_str.lower() not in {"__all__", "all"}:
                        tasks.add(task_str)

        # Normalize combined priors
        for axis, vals in list(priors.items()):
            total = sum(vals.values())
            if total <= 0:
                priors.pop(axis, None)
                continue
            priors[axis] = {k: v / total for k, v in vals.items()}

        if priors:
            coverage = {
                axis: (coverage_sums[axis] / coverage_weights[axis])
                for axis in coverage_sums
                if coverage_weights.get(axis, 0.0) > 0
            }
            base_payload = {
                "priors": priors,
                "scanned": scanned,
                "source": "neurokg",
                "scope": scope,
                "support": {
                    "n_nodes_scanned": scanned,
                    "n_datasets": max(len(datasets), support_n_datasets_max),
                    "n_tasks": max(len(tasks), support_n_tasks_max),
                },
            }
            if total_specs:
                base_payload["support"]["n_specs"] = total_specs
            if coverage:
                base_payload["coverage"] = coverage

    # Literature priors (optional, weak)
    if include_literature is None:
        include_lit = os.environ.get("BR_ENABLE_LITERATURE_PRIORS", "true").lower()
        include_lit = include_lit not in {"0", "false", "no"}
    else:
        include_lit = bool(include_literature)
    lit_payload = None
    if include_lit:
        try:
            lit_payload = infer_literature_priors(task=task_value, contrast=None)
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Literature priors lookup failed: %s", exc)
            lit_payload = {"status": "error", "priors": {}, "support": {}}

    lit_priors = (lit_payload or {}).get("priors") or {}
    lit_support = (lit_payload or {}).get("support") or {}

    if not base_payload and not lit_priors:
        return None

    if not base_payload and lit_priors:
        scope_guess = "task" if task_value else "global"
        base_payload = {
            "priors": lit_priors,
            "scanned": 0,
            "source": "literature",
            "scope": scope_guess,
            "support": {
                "n_nodes_scanned": 0,
                "n_datasets": 0,
                "n_tasks": 1 if task_value else 0,
            },
        }
    elif base_payload and lit_priors:
        weight = float(os.environ.get("BR_LITERATURE_PRIOR_WEIGHT", "0.2"))
        base_payload["priors"] = merge_priors(
            base_payload.get("priors", {}), lit_priors, weight=weight
        )
        base_payload["source"] = "hybrid"

    if base_payload is None:
        return None

    if lit_support:
        base_payload["literature_support"] = lit_support
        base_payload.setdefault("support", {})["literature"] = lit_support

    sources: dict[str, Any] = dict(base_payload.get("sources") or {})
    if base_payload.get("source") in {"neurokg", "hybrid"}:
        sources.setdefault("neurokg", base_payload.get("support", {}))
    if lit_support:
        sources.setdefault("literature", lit_support)
    if sources:
        base_payload["sources"] = sources

    return base_payload


_EFFECT_SIZE_NODE_LABELS = {
    "coordinate",
    "statsmap",
    "statisticalmap",
    "result",
    "study",
    "publication",
}


def _effect_size_text_matches(needle: str, attrs: Mapping[str, Any]) -> bool:
    needle_lower = needle.lower()
    for value in attrs.values():
        if isinstance(value, str) and needle_lower in value.lower():
            return True
    return False


def _effect_size_graph_lookup(
    *,
    db: Any,
    task: str | None,
    contrast: str | None,
    region: str | None,
    working_group: str | None,
) -> dict[str, Any] | None:
    graph = getattr(db, "graph", None)
    if graph is None:
        return None

    studies_data: list[dict[str, Any]] = []
    for _, attrs in getattr(graph, "nodes", lambda data=True: [])(data=True):
        labels = attrs.get("labels") or []
        if isinstance(labels, str):
            labels = [labels]
        if labels and not any(
            str(label).lower() in _EFFECT_SIZE_NODE_LABELS for label in labels
        ):
            continue

        effect_size = (
            attrs.get("effect_size")
            or attrs.get("cohens_d")
            or attrs.get("statistic_value")
        )
        if effect_size is None:
            continue
        try:
            effect_size_value = float(effect_size)
        except (TypeError, ValueError):
            continue
        if abs(effect_size_value) < 1e-9:
            continue

        if task and not _effect_size_text_matches(task, attrs):
            continue
        if contrast and not _effect_size_text_matches(contrast, attrs):
            continue
        if region and not _effect_size_text_matches(region, attrs):
            continue
        if working_group and not _effect_size_text_matches(working_group, attrs):
            continue

        try:
            sample_size = int(attrs.get("sample_size", attrs.get("n_subjects", 20)))
        except (TypeError, ValueError):
            sample_size = 20
        try:
            p_value = float(attrs.get("p_value", 0.05))
        except (TypeError, ValueError):
            p_value = 0.05

        studies_data.append(
            {
                "effect_size": effect_size_value,
                "p_value": p_value,
                "sample_size": sample_size,
            }
        )

    if len(studies_data) < 3:
        return {
            "status": "no_data",
            "source": "kg_meta_analysis",
            "priors": {},
            "support": {"n_studies": len(studies_data)},
        }

    try:
        from brain_researcher.services.neurokg.etl.strength_calculator import (
            StrengthCalculator,
        )

        calculator = StrengthCalculator()
        _, details = calculator.strength_from_effect_sizes(studies_data)
    except Exception:
        details = {}

    effect_sizes = sorted(abs(row["effect_size"]) for row in studies_data)
    summary = {
        "median_abs_d": round(effect_sizes[len(effect_sizes) // 2], 3),
        "p90_abs_d": round(effect_sizes[max(0, int(round(len(effect_sizes) * 0.9)) - 1)], 3)
        if effect_sizes
        else 0.0,
        "max_abs_d": round(effect_sizes[-1], 3),
        "n_mentions": len(effect_sizes),
    }
    if details.get("i_squared") is not None:
        summary["i_squared"] = details.get("i_squared")
    if details.get("weighted_mean_effect") is not None:
        summary["weighted_mean_effect"] = details.get("weighted_mean_effect")

    support: dict[str, Any] = {"n_studies": len(studies_data)}
    support.update(details)
    return {
        "status": "ok",
        "source": "kg_meta_analysis",
        "confidence_tier": "kg_meta",
        "priors": {"cohens_d": summary},
        "support": support,
        "task": task,
        "contrast": contrast,
        "region": region,
        "working_group": working_group,
    }


def get_effect_size_priors(
    *,
    task: str | None = None,
    contrast: str | None = None,
    region: str | None = None,
    working_group: str | None = None,
    db: Optional[Neo4jGraphDB] = None,
    store: str | None = None,
    model: str | None = None,
) -> dict[str, Any] | None:
    """Fetch effect-size priors from KG first, then fall back to multi-source priors."""

    client = db or get_default_db()
    payload: dict[str, Any] | None = None
    if client is not None:
        try:
            payload = _effect_size_graph_lookup(
                db=client,
                task=task,
                contrast=contrast,
                region=region,
                working_group=working_group,
            )
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("KG effect-size priors query failed: %s", exc)
            payload = None

    if payload is None or payload.get("status") != "ok":
        try:
            from brain_researcher.core.literature.literature_priors import (
                infer_effect_size_priors_multi,
            )

            payload = infer_effect_size_priors_multi(
                task=task,
                contrast=contrast,
                region=region,
                working_group=working_group,
                store=store,
                model=model,
            )
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Fallback effect-size priors query failed: %s", exc)
            return None

    if payload is None:
        return None

    if payload.get("status") == "ok" and payload.get("source") == "kg_meta_analysis":
        payload.setdefault("scope", "task" if task else "global")
        return payload

    payload = dict(payload)
    payload.setdefault("scope", "task" if task else "global")
    return payload


_METHOD_COMPATIBILITY_SEED_PATH = (
    Path(__file__).resolve().parents[4]
    / "configs"
    / "neurokg"
    / "method_compatibility_seed.yaml"
)
_METHOD_COMPATIBILITY_REL_TYPES = (
    "COMPATIBLE_WITH",
    "INCOMPATIBLE_WITH",
    "REQUIRES",
)
_METHOD_COMPATIBILITY_GENERIC_DESIGN_LABELS = {
    "experimental_design",
    "experimentaldesign",
    "design",
    "study_design",
}
_METHOD_COMPATIBILITY_GENERIC_METHOD_LABELS = {
    "statistical_method",
    "statisticalmethod",
    "method",
}


def _normalize_method_compatibility_text(value: str | None) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _build_method_compatibility_alias_index(
    seed: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    def _index_aliases(raw: Any) -> dict[str, str]:
        aliases: dict[str, str] = {}
        if not isinstance(raw, Mapping):
            return aliases
        for canonical, values in raw.items():
            canonical_text = _normalize_method_compatibility_text(str(canonical))
            if not canonical_text:
                continue
            aliases[canonical_text] = canonical_text
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, Iterable):
                continue
            for value in values:
                alias_text = _normalize_method_compatibility_text(str(value))
                if alias_text:
                    aliases[alias_text] = canonical_text
        return aliases

    design_aliases = _index_aliases(seed.get("design_aliases"))
    method_aliases = _index_aliases(seed.get("method_aliases"))
    return design_aliases, method_aliases


def _method_compatibility_aliases_for_canonical(
    aliases: Mapping[str, str],
    canonical: str,
) -> set[str]:
    return {
        alias
        for alias, mapped_canonical in aliases.items()
        if mapped_canonical == canonical and alias
    }


def _method_compatibility_expected_texts(
    *,
    canonical: str,
    aliases: Mapping[str, str],
    generic_texts: Collection[str],
) -> set[str]:
    expected = {canonical}
    expected.update(_method_compatibility_aliases_for_canonical(aliases, canonical))
    return {value for value in expected if value}


def _method_compatibility_node_texts(node: Any) -> set[str]:
    texts: set[str] = set()

    def _add(value: Any) -> None:
        normalized = _normalize_method_compatibility_text(value)
        if normalized:
            texts.add(normalized)

    try:
        if isinstance(node, Mapping):
            items = list(node.items())
        else:
            items = list(dict(node).items())  # type: ignore[arg-type]
    except Exception:
        items = []

    for key, value in items:
        key_norm = _normalize_method_compatibility_text(key)
        if isinstance(value, str):
            _add(value)
        elif isinstance(value, Collection) and not isinstance(value, (str, bytes)):
            for item in value:
                _add(item)
        elif value is not None:
            _add(value)
        if key_norm in {"label", "labels", "name", "id", "canonical_id", "type", "kind"}:
            _add(value)

    for attr in ("labels", "name", "label", "id", "canonical_id", "type", "kind"):
        try:
            value = getattr(node, attr)
        except Exception:
            continue
        if isinstance(value, str):
            _add(value)
        elif isinstance(value, Collection) and not isinstance(value, (str, bytes)):
            for item in value:
                _add(item)
        elif value is not None:
            _add(value)

    return texts


def _method_compatibility_node_matches(
    node: Any,
    expected_texts: Collection[str],
) -> bool:
    node_texts = _method_compatibility_node_texts(node)
    return any(text in node_texts for text in expected_texts)


def _method_compatibility_graph_node_attrs(graph: Any, node_id: Any) -> dict[str, Any]:
    try:
        node_attrs = graph.nodes[node_id]
    except Exception:
        return {}
    if isinstance(node_attrs, Mapping):
        return dict(node_attrs)
    try:
        return dict(node_attrs)
    except Exception:
        return {}


def _method_compatibility_rule_id(
    canonical_design: str,
    canonical_method: str,
    compatible: bool,
) -> str:
    rule_map = {
        ("repeated_measures", "paired_t_test", True): "repeated_measures_requires_paired_t_test",
        ("repeated_measures", "independent_t_test", False): "repeated_measures_blocks_independent_t_test",
        ("independent_groups", "independent_t_test", True): "independent_groups_supports_independent_t_test",
        ("independent_groups", "paired_t_test", False): "independent_groups_blocks_paired_t_test",
    }
    return rule_map.get(
        (canonical_design, canonical_method, compatible),
        f"graph_method_compatibility_{canonical_design}_{canonical_method}_{'compatible' if compatible else 'incompatible'}",
    )


def _method_compatibility_payload(
    *,
    design: str,
    method: str,
    canonical_design: str,
    canonical_method: str,
    compatible: bool,
    source: str,
    rationale: str | None = None,
    evidence: Mapping[str, Any] | None = None,
    graph_labels: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "design": {
            "raw": design,
            "canonical": canonical_design,
        },
        "method": {
            "raw": method,
            "canonical": canonical_method,
        },
        "compatible": compatible,
        "verdict": "compatible" if compatible else "incompatible",
        "severity": "ok" if compatible else "error",
        "rule_id": _method_compatibility_rule_id(
            canonical_design, canonical_method, compatible
        ),
        "source": source,
    }
    if rationale:
        payload["rationale"] = rationale
    if evidence:
        payload["evidence"] = dict(evidence)
    if graph_labels:
        payload["graph"] = dict(graph_labels)
    return payload


def _method_compatibility_graph_lookup(
    *,
    db: Any,
    design: str,
    method: str,
    canonical_design: str,
    canonical_method: str,
    design_aliases: Mapping[str, str],
    method_aliases: Mapping[str, str],
) -> dict[str, Any] | None:
    design_expected = _method_compatibility_expected_texts(
        canonical=canonical_design,
        aliases=design_aliases,
        generic_texts=_METHOD_COMPATIBILITY_GENERIC_DESIGN_LABELS,
    )
    method_expected = _method_compatibility_expected_texts(
        canonical=canonical_method,
        aliases=method_aliases,
        generic_texts=_METHOD_COMPATIBILITY_GENERIC_METHOD_LABELS,
    )

    graph = getattr(db, "graph", None)
    if graph is not None:
        try:
            edges_iter = graph.edges(data=True, keys=True)
        except Exception:
            try:
                edges_iter = ((u, v, None, data) for u, v, data in graph.edges(data=True))
            except Exception:
                edges_iter = ()
        for source_id, target_id, rel_key, rel_data in edges_iter:
            rel_type = _normalize_method_compatibility_text(
                _rec_get(rel_data, "type") or rel_key or _rec_get(rel_data, "label")
            ).upper()
            if rel_type not in _METHOD_COMPATIBILITY_REL_TYPES:
                continue
            source_node = _method_compatibility_graph_node_attrs(graph, source_id)
            target_node = _method_compatibility_graph_node_attrs(graph, target_id)
            forward_matches = _method_compatibility_node_matches(
                source_node, design_expected
            ) and _method_compatibility_node_matches(target_node, method_expected)
            reverse_matches = _method_compatibility_node_matches(
                source_node, method_expected
            ) and _method_compatibility_node_matches(target_node, design_expected)
            if not (forward_matches or reverse_matches):
                continue
            compatible = rel_type != "INCOMPATIBLE_WITH"
            rationale = (
                "Graph-backed compatibility edge indicates this design/method pair is appropriate."
                if compatible
                else "Graph-backed incompatibility edge indicates this design/method pair should be blocked."
            )
            evidence = {
                "relationship_type": rel_type,
                "relationship_direction": "design_to_method"
                if forward_matches
                else "method_to_design",
                "source_node_id": source_id,
                "target_node_id": target_id,
            }
            return _method_compatibility_payload(
                design=design,
                method=method,
                canonical_design=canonical_design,
                canonical_method=canonical_method,
                compatible=compatible,
                source="graph",
                rationale=rationale,
                evidence=evidence,
                graph_labels={
                    "design_labels": sorted(_method_compatibility_node_texts(source_node)),
                    "method_labels": sorted(_method_compatibility_node_texts(target_node)),
                },
            )

    cypher = """
        MATCH (source)-[rel]->(target)
        WHERE type(rel) IN $rel_types
        RETURN source, rel, target
        LIMIT $limit
    """
    try:
        records = _as_list(
            _run_with_optional_timeout(
                db,
                cypher,
                {"rel_types": list(_METHOD_COMPATIBILITY_REL_TYPES), "limit": 100},
                timeout_s=5.0,
            )
        )
    except Exception:
        return None

    for record in records:
        source_node = (
            _rec_get(record, "source")
            or _rec_get(record, "design")
            or _rec_get(record, "a")
        )
        target_node = (
            _rec_get(record, "target")
            or _rec_get(record, "method")
            or _rec_get(record, "b")
        )
        rel = _rec_get(record, "rel") or _rec_get(record, "r")
        rel_type = _normalize_method_compatibility_text(
            _rec_get(rel, "type") or _rec_get(record, "rel_type") or _rec_get(record, "type")
        ).upper()
        if rel_type not in _METHOD_COMPATIBILITY_REL_TYPES:
            continue

        forward_matches = _method_compatibility_node_matches(
            source_node, design_expected
        ) and _method_compatibility_node_matches(target_node, method_expected)
        reverse_matches = _method_compatibility_node_matches(
            source_node, method_expected
        ) and _method_compatibility_node_matches(target_node, design_expected)
        if not (forward_matches or reverse_matches):
            continue

        compatible = rel_type != "INCOMPATIBLE_WITH"
        rationale = (
            "KG-backed compatibility edge indicates this design/method pair is appropriate."
            if compatible
            else "KG-backed incompatibility edge indicates this design/method pair should be blocked."
        )
        evidence = {
            "relationship_type": rel_type,
            "relationship_direction": "design_to_method"
            if forward_matches
            else "method_to_design",
        }
        source_labels = sorted(_method_compatibility_node_texts(source_node))
        target_labels = sorted(_method_compatibility_node_texts(target_node))
        return _method_compatibility_payload(
            design=design,
            method=method,
            canonical_design=canonical_design,
            canonical_method=canonical_method,
            compatible=compatible,
            source="graph",
            rationale=rationale,
            evidence=evidence,
            graph_labels={
                "design_labels": source_labels if forward_matches else target_labels,
                "method_labels": target_labels if forward_matches else source_labels,
            },
        )

    return None


@functools.lru_cache(maxsize=1)
def _load_method_compatibility_seed() -> dict[str, Any]:
    """Load the curated method-compatibility seed used by B2 v0."""

    try:
        import yaml  # type: ignore

        if not _METHOD_COMPATIBILITY_SEED_PATH.exists():
            return {}
        payload = yaml.safe_load(
            _METHOD_COMPATIBILITY_SEED_PATH.read_text(encoding="utf-8")
        ) or {}
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug(
            "Failed to load method compatibility seed from %s: %s",
            _METHOD_COMPATIBILITY_SEED_PATH,
            exc,
        )
        return {}


def _resolve_design_via_onvoc(
    raw_design: str,
    seed: Mapping[str, Any],
) -> str | None:
    """Attempt to resolve a design label to a canonical key via ONVOC Study Design.

    Uses the ONVOC tree to find the closest matching Study Design node, then maps
    it to a canonical design key via the seed's ``onvoc_design_map``.
    """
    onvoc_design_map = seed.get("onvoc_design_map") or {}
    if not onvoc_design_map:
        return None
    try:
        from brain_researcher.services.neurokg.utils.onvoc_linker import DEFAULT_TREE_PATH
        from brain_researcher.services.neurokg.utils.onvoc_tree import OnvocTree

        tree = OnvocTree.load(DEFAULT_TREE_PATH)
    except Exception:
        return None

    # Get all descendants of ONVOC_0000007 (Study Design)
    study_design_root = "ONVOC_0000007"
    descendants = tree.descendants(study_design_root)
    descendants.add(study_design_root)

    # Build label→id index for study design subtree
    label_to_id: dict[str, str] = {}
    for node_id in descendants:
        node = tree.nodes.get(node_id)
        if node:
            label_to_id[node.label.lower()] = node_id

    if not label_to_id:
        return None

    raw_lower = raw_design.strip().lower()

    # Exact label match
    if raw_lower in label_to_id:
        matched_id = label_to_id[raw_lower]
        return onvoc_design_map.get(matched_id)

    # Fuzzy match via rapidfuzz if available
    try:
        from rapidfuzz import fuzz as _fuzz

        best_score, best_id = 0.0, None
        for label, node_id in label_to_id.items():
            score = _fuzz.QRatio(raw_lower, label)
            if score > best_score:
                best_score, best_id = score, node_id
        if best_score >= 80 and best_id is not None:
            return onvoc_design_map.get(best_id)
    except ImportError:
        # Substring match fallback
        for label, node_id in label_to_id.items():
            if raw_lower in label or label in raw_lower:
                return onvoc_design_map.get(node_id)

    return None


def get_method_compatibility(
    *,
    design: str | None,
    method: str | None,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any] | None:
    """Return a curated method-compatibility verdict for a design/method pair.

    B2.5: Supports all canonical design-method pairs via seed YAML and optional
    ONVOC Study Design vocabulary resolution as a second-chance normalization.
    """

    seed = _load_method_compatibility_seed()
    normalized_design = _normalize_method_compatibility_text(design)
    normalized_method = _normalize_method_compatibility_text(method)
    if not normalized_design or not normalized_method:
        return None

    design_aliases, method_aliases = _build_method_compatibility_alias_index(seed)
    canonical_design = design_aliases.get(normalized_design, normalized_design)
    canonical_method = method_aliases.get(normalized_method, normalized_method)

    # ONVOC second-chance resolution for designs not in the alias index.
    if canonical_design == normalized_design and seed:
        onvoc_resolved = _resolve_design_via_onvoc(str(design or ""), seed)
        if onvoc_resolved:
            canonical_design = onvoc_resolved

    if db is not None:
        graph_payload = _method_compatibility_graph_lookup(
            db=db,
            design=design,
            method=method,
            canonical_design=canonical_design,
            canonical_method=canonical_method,
            design_aliases=design_aliases,
            method_aliases=method_aliases,
        )
        if graph_payload is not None:
            return graph_payload

    if not seed:
        return None

    for rule in seed.get("rules", []) or []:
        if not isinstance(rule, Mapping):
            continue
        rule_design = _normalize_method_compatibility_text(rule.get("design"))
        rule_method = _normalize_method_compatibility_text(rule.get("method"))
        if rule_design != canonical_design or rule_method != canonical_method:
            continue

        compatible = bool(rule.get("compatible"))
        payload = _method_compatibility_payload(
            design=design,
            method=method,
            canonical_design=canonical_design,
            canonical_method=canonical_method,
            compatible=compatible,
            source="seed",
            rationale=rule.get("rationale"),
            evidence=rule.get("evidence") or {},
        )
        payload["severity"] = str(rule.get("severity") or ("ok" if compatible else "error"))
        payload["rule_id"] = rule.get("id")
        payload["seed"] = {
            "name": (seed.get("metadata") or {}).get("name"),
            "version": (seed.get("metadata") or {}).get("version"),
            "path": str(_METHOD_COMPATIBILITY_SEED_PATH),
        }
        return payload

    return None


def _stable_node_id(node: Any) -> str | None:
    if isinstance(node, dict):
        return (
            node.get("id")
            or node.get("dataset_id")
            or node.get("uid")
            or node.get("identifier")
        )
    try:
        for key in ("id", "dataset_id", "uid", "identifier"):
            if hasattr(node, "get"):
                val = node.get(key)
                if val:
                    return val
    except Exception:  # pragma: no cover - defensive
        pass
    return None


def _element_id(node: Any) -> str | None:
    if isinstance(node, dict):
        return node.get("element_id") or node.get("elementId")
    for attr in ("element_id", "elementId"):
        if hasattr(node, attr):
            val = getattr(node, attr)
            if val:
                return val
    return None


_ELEMENT_ID_RE = re.compile(r"^\d+:[0-9a-fA-F-]+:\d+$")
_DATASET_ID_RE = re.compile(r"^ds\d{6}$", re.IGNORECASE)
_ONTOLOGY_ID_RE = re.compile(
    r"^(ONVOC|COGPO|CAO|COGAT|NIFSTD|UBERON|FMA|BIRNLEX)[_:]\d+",
    re.IGNORECASE,
)
_CURIE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]+:(?:[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+)*)$"
)
_PMID_ONLY_RE = re.compile(r"^\s*(?:pmid[:\s]*)?([0-9]{5,9})\s*$", re.IGNORECASE)
_DOI_ONLY_RE = re.compile(r"^\s*(?:doi[:\s]*)?(10\.[0-9]{4,9}/\S+)\s*$", re.IGNORECASE)
_DOI_ANY_RE = re.compile(r"10\.[0-9]{4,9}/\S+", re.IGNORECASE)


def _looks_like_element_id(value: str) -> bool:
    return bool(_ELEMENT_ID_RE.match(value or ""))


def _normalize_doi(value: str) -> str:
    doi = (value or "").strip().lower()
    doi = re.sub(r"^doi:\s*", "", doi)
    doi = re.sub(r"\s+", "", doi)
    doi = doi.strip(" \t\r\n'\"")
    doi = doi.rstrip(".,;:)]}")
    doi = doi.lstrip("([{")
    return doi


def _extract_pmid_exact(value: str) -> str | None:
    match = _PMID_ONLY_RE.match(value or "")
    if not match:
        return None
    return match.group(1)


def _extract_doi_exact(value: str) -> str | None:
    match = _DOI_ONLY_RE.match(value or "")
    if not match:
        return None
    doi = _normalize_doi(match.group(1))
    return doi or None


def _build_lookup_terms(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []

    terms: list[str] = []
    seen: set[str] = set()

    def _add(term: str | None) -> None:
        if not term:
            return
        normalized = term.strip().lower()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        terms.append(normalized)

    lowered = raw.lower()
    compact = re.sub(r"\s+", "", lowered)
    stripped = compact.strip(" \t\r\n'\"")
    de_punct = stripped.strip(".,;:()[]{}")

    _add(lowered)
    _add(compact)
    _add(stripped)
    _add(de_punct)

    pmid = _extract_pmid_exact(raw)
    if pmid is None and compact.startswith("pmid:"):
        candidate = compact.split(":", 1)[1]
        if candidate.isdigit():
            pmid = candidate
    if pmid:
        _add(pmid)
        _add(f"pmid:{pmid}")

    doi = _extract_doi_exact(raw)
    if doi is None and compact.startswith("doi:"):
        doi = _normalize_doi(compact.split(":", 1)[1])
    if doi is None:
        any_match = _DOI_ANY_RE.search(compact)
        if any_match and len(compact) <= len(any_match.group(0)) + 6:
            doi = _normalize_doi(any_match.group(0))
    if doi:
        _add(doi)
        _add(f"doi:{doi}")

    return terms


_KG_IDENTIFIER_FIELDS = (
    "id",
    "dataset_id",
    "uid",
    "identifier",
    "task_id",
    "concept_id",
    "region_id",
    "study_id",
    "source_repo_id",
)

_PUBLICATION_IDENTIFIER_FIELDS = (
    "id",
    "dataset_id",
    "uid",
    "identifier",
    "study_id",
    "pmid",
    "pmcid",
    "doi",
)

_VERIFY_EXACT_FAST_PATH_TYPES = {
    "Atlas",
    "BrainRegion",
    "Concept",
    "Dataset",
    "Method",
    "Paper",
    "Publication",
    "Task",
    "TaskFamily",
    "Tool",
}

_VERIFY_TYPED_PATH_SCOPES = {"typed_path"}

_ENTITY_HINT_QUALITY_SCORES = {
    "exact_pair": 1.0,
    "exact_plus_label": 0.85,
    "exact_pair_untyped": 0.75,
    "exact_single": 0.65,
    "label_pair": 0.45,
    "label_single": 0.25,
    "none": 0.0,
}


def _infer_ood_hint_node_type(value: str, fallback: Any = None) -> str:
    canonical_fallback = _canonical_ood_node_type(fallback)
    if canonical_fallback not in {"", "Node"}:
        return canonical_fallback
    prefix = str(value or "").strip().split(":", 1)[0].lower()
    return {
        "atlas": "Atlas",
        "brainregion": "BrainRegion",
        "concept": "Concept",
        "dataset": "Dataset",
        "method": "Method",
        "region": "BrainRegion",
        "task": "Task",
        "taskfamily": "TaskFamily",
        "tool": "Tool",
        "neurostore_task": "Task",
        "trm": "Concept",
    }.get(prefix, canonical_fallback or "Node")


def _is_publication_like_entity_hint(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    if (
        lowered.startswith("doi:")
        or lowered.startswith("pmid:")
        or lowered.startswith("pmcid:")
    ):
        return True
    return (
        _extract_doi_exact(lowered) is not None
        or _extract_pmid_exact(lowered) is not None
        or lowered.startswith("pmc")
    )


def _is_dataset_like_entity_hint(value: str, fallback: Any = None) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    if _infer_ood_hint_node_type(normalized, fallback) == "Dataset":
        return True
    lowered = normalized.lower()
    return lowered.startswith("ds:") or lowered.startswith("openneuro:")


def _rank_ood_verification_partner(
    *,
    value: str,
    node_type: Any,
    candidate_type: str,
    has_label: bool,
) -> tuple[int, int, int]:
    normalized = str(value or "").strip()
    canonical_node_type = _infer_ood_hint_node_type(normalized, node_type)
    canonical_candidate_type = _canonical_ood_node_type(candidate_type)
    publication_like = _is_publication_like_entity_hint(normalized)
    dataset_like = _is_dataset_like_entity_hint(normalized, canonical_node_type)
    exact_fast_path = (
        canonical_node_type in _VERIFY_EXACT_FAST_PATH_TYPES and not publication_like
    )
    semantic_support = canonical_node_type in {"Task", "Concept"}
    complementary = (
        exact_fast_path
        and canonical_candidate_type not in {"", "Node"}
        and canonical_node_type != canonical_candidate_type
    )
    rank = (
        0
        if semantic_support and complementary
        else 1
        if semantic_support and exact_fast_path
        else 2
        if complementary and not dataset_like
        else 3
        if exact_fast_path and not dataset_like
        else 4
        if (has_label and not publication_like and not dataset_like)
        else 5
        if not publication_like and not dataset_like
        else 6
        if complementary
        else 7
        if exact_fast_path
        else 8
        if has_label and not publication_like
        else 9
        if not publication_like
        else 10
    )
    return (
        rank,
        0 if canonical_node_type not in {"", "Node"} else 1,
        0 if not dataset_like else 1,
    )


def _select_ood_verification_support_seed(
    *,
    touched_seeds: Sequence[str] | None,
    fallback_seeds: Sequence[str] | None,
    seed_types: Mapping[str, Any] | None,
    seed_labels: Mapping[str, Any] | None,
    candidate_type: str,
    exclude_ids: Collection[str] | None = None,
) -> str | None:
    excluded = {
        str(value or "").strip()
        for value in (exclude_ids or [])
        if str(value or "").strip()
    }
    canonical_candidate_type = _canonical_ood_node_type(candidate_type)
    ranked: list[tuple[int, int, int, str]] = []
    seen: set[str] = set()
    typed_map = seed_types or {}
    label_map = seed_labels or {}

    def _consider(seed_id: str, source_rank: int, ordinal: int) -> None:
        normalized = str(seed_id or "").strip()
        if not normalized or normalized in seen or normalized in excluded:
            return
        seen.add(normalized)
        node_type = _infer_ood_hint_node_type(
            normalized,
            typed_map.get(normalized),
        )
        has_label = bool(str(label_map.get(normalized) or "").strip())
        rank = _rank_ood_verification_partner(
            value=normalized,
            node_type=node_type,
            candidate_type=canonical_candidate_type,
            has_label=has_label,
        )
        ranked.append((rank, source_rank, ordinal, normalized))

    for ordinal, seed_id in enumerate(touched_seeds or []):
        _consider(seed_id, 0, ordinal)
    for ordinal, seed_id in enumerate(fallback_seeds or []):
        _consider(seed_id, 1, ordinal)

    if not ranked:
        return None
    ranked.sort()
    return ranked[0][3]


def _identifier_exact_match_clause(node_alias: str) -> str:
    return (
        f"any(key IN $identifier_keys WHERE "
        f"toLower(coalesce(toString({node_alias}[key]), '')) = term)"
    )


def _publication_anchor_match_clause(node_alias: str) -> str:
    return (
        f"any(key IN $publication_identifier_keys WHERE "
        f"toLower(coalesce(toString({node_alias}[key]), '')) = term)"
    )


def _identifier_value_from_props(props: Mapping[str, Any] | None) -> str | None:
    if not isinstance(props, Mapping):
        return None
    for key in ("kg_id",) + _KG_IDENTIFIER_FIELDS:
        value = props.get(key)
        if value not in {None, ""}:
            return str(value)
    return None


def _coalesce_dataset_property_values(entity: KGNodeSummary) -> list[str]:
    props = entity.properties or {}
    values: list[str] = []
    for key in (
        "id",
        "dataset_id",
        "uid",
        "identifier",
        "study_id",
        "source_repo_id",
        "source_version",
        "primary_url",
        "label",
        "name",
        "title",
        "alias",
    ):
        value = props.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value if item)
        elif value:
            values.append(str(value))
    for key in ("aliases", "synonyms", "keywords"):
        for item in props.get(key) or []:
            if item:
                values.append(str(item))
    dataset_id = str(props.get("dataset_id") or entity.kg_id or "").strip()
    if dataset_id.startswith("ds:openneuro:"):
        values.append(dataset_id.split(":")[-1])
    for raw in list(values):
        lowered = str(raw).strip().lower()
        if lowered.startswith("https://doi.org/"):
            values.append(lowered.rsplit("/", 1)[-1])
        doi = _extract_doi_exact(lowered) or _normalize_doi(lowered)
        if doi.startswith("10."):
            values.append(doi)
            values.append(f"doi:{doi}")
    return values


def _is_dataset_like_entity(entity: KGNodeSummary) -> bool:
    return _canonical_ood_node_type(entity.node_type) == "Dataset"


def _is_onvoc_like_entity(entity: KGNodeSummary) -> bool:
    canonical = _canonical_ood_node_type(entity.node_type)
    if canonical in {"Concept", "OntologyConcept", "OnvocClass", "LegacyOnvocTag"}:
        return True
    return str(entity.kg_id or "").strip().lower().startswith("legacy_onvoc:")


def _is_exact_identifier_hint(value: str) -> bool:
    hint = str(value or "").strip()
    if not hint:
        return False
    inferred = _infer_query_hints(hint)
    return bool(inferred.get("exact_id")) or _looks_like_element_id(hint)


def _is_fast_path_entity(entity: KGNodeSummary | None) -> bool:
    if entity is None:
        return False
    canonical = _canonical_ood_node_type(entity.node_type)
    if canonical == "Modality":
        return False
    return canonical in _VERIFY_EXACT_FAST_PATH_TYPES


def _resolve_exact_hint_entity(
    hint: str,
    *,
    client: Neo4jGraphDB,
    allowed_node_types: Sequence[str] | None = None,
) -> KGNodeSummary | None:
    detail = node_details(hint, db=client, include_neighbors=False)
    if detail is not None and _is_fast_path_entity(detail):
        return detail
    if detail is not None:
        return None
    if not _is_exact_identifier_hint(hint):
        return None
    hits = search_nodes(
        hint,
        node_types=allowed_node_types,
        limit=4,
        db=client,
        infer_types=True,
    )
    hint_norm = str(hint or "").strip().lower()
    for hit in hits:
        if not _is_fast_path_entity(hit):
            continue
        if str(hit.kg_id or "").strip().lower() == hint_norm:
            return hit
    for hit in hits:
        if _is_fast_path_entity(hit):
            return hit
    return None


_LUCENE_ESCAPE_RE = re.compile(r'([+\-!(){}[\]^"~*?:\\/]|&&|\|\|)')


def _escape_lucene(text: str) -> str:
    if not text:
        return ""
    return _LUCENE_ESCAPE_RE.sub(r"\\\1", text)


def _build_fulltext_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    tokens = [t for t in re.split(r"\s+", q) if t]
    escaped_tokens = [_escape_lucene(token) for token in tokens]
    if len(escaped_tokens) == 1:
        return escaped_tokens[0]
    phrase = " ".join(escaped_tokens)
    and_clause = " AND ".join(escaped_tokens)
    or_clause = " OR ".join(escaped_tokens)
    return f'("{phrase}")^4 OR ({and_clause})^2 OR ({or_clause})'


_NODE_TYPE_ALIASES = {
    "concept": ["Concept", "CognitiveConcept", "Term", "OntologyConcept"],
    "cognitiveconcept": ["CognitiveConcept", "Concept", "Term", "OntologyConcept"],
    "brain_region": ["BrainRegion", "Region", "Parcel"],
    "region": ["BrainRegion", "Region", "Parcel"],
    "dataset": ["Dataset"],
    "task": ["Task"],
    "tool": ["Tool", "Software"],
    "software": ["Tool", "Software"],
    "atlas": ["Atlas"],
}


def _expand_types(types: Optional[Sequence[str]]) -> Optional[list[str]]:
    if not types:
        return None
    expanded: list[str] = []
    for t in types:
        expanded.append(t)
        expanded.extend(_NODE_TYPE_ALIASES.get(str(t).lower(), []))
    return list(dict.fromkeys(expanded))


def _infer_query_hints(query: str) -> dict[str, Any]:
    q = (query or "").strip()
    q_lower = q.lower()
    hints: dict[str, Any] = {"exact_id": None, "node_types": None}

    pmid = _extract_pmid_exact(q)
    if pmid:
        hints["exact_id"] = f"pmid:{pmid}"
        hints["node_types"] = ["Publication", "Paper", "Study"]
        return hints

    doi = _extract_doi_exact(q)
    if doi:
        hints["exact_id"] = f"doi:{doi}"
        hints["node_types"] = ["Publication", "Paper", "Study"]
        return hints

    if _DATASET_ID_RE.match(q):
        hints["exact_id"] = q
        hints["node_types"] = ["Dataset"]
        return hints

    if _ONTOLOGY_ID_RE.match(q) or _CURIE_RE.match(q):
        hints["exact_id"] = q
        if _ONTOLOGY_ID_RE.match(q):
            hints["node_types"] = _NODE_TYPE_ALIASES["concept"]
        else:
            inferred_type = _infer_ood_hint_node_type(q)
            hints["node_types"] = [inferred_type] if inferred_type != "Node" else None
        return hints

    node_types: list[str] = []
    keyword_map = {
        "dataset": ["Dataset"],
        "datasets": ["Dataset"],
        "task": ["Task"],
        "paradigm": ["Task"],
        "tool": ["Tool", "Software"],
        "software": ["Tool", "Software"],
        "package": ["Tool", "Software"],
        "atlas": ["Atlas"],
        "region": _NODE_TYPE_ALIASES["region"],
        "roi": _NODE_TYPE_ALIASES["region"],
        "cortex": _NODE_TYPE_ALIASES["region"],
        "brodmann": _NODE_TYPE_ALIASES["region"],
    }
    for key, types in keyword_map.items():
        if key in q_lower:
            node_types.extend(types)

    if node_types:
        hints["node_types"] = list(dict.fromkeys(node_types))

    return hints


_FULLTEXT_INDEX_CACHE: dict[str | None, str | None] = {}


def _resolve_fulltext_index(
    client: Neo4jGraphDB,
    *,
    timeout_s: float | None = None,
) -> str | None:
    preferred = os.getenv("NEO4J_FULLTEXT_NODE_INDEX") or os.getenv(
        "NEO4J_FULLTEXT_INDEX"
    )
    if os.getenv("NEO4J_FULLTEXT_DISABLE") == "1":
        return None
    cache_key = preferred or "__auto__"
    if cache_key in _FULLTEXT_INDEX_CACHE:
        return _FULLTEXT_INDEX_CACHE[cache_key]
    try:
        records = _as_list(
            _run_with_optional_timeout(
                client,
                "CALL db.indexes() YIELD name, type, entityType "
                "WHERE type = 'FULLTEXT' AND entityType = 'NODE' "
                "RETURN name",
                {},
                timeout_s=timeout_s,
            )
        )
    except Exception:
        _FULLTEXT_INDEX_CACHE[cache_key] = None
        return None
    names = [str(_rec_get(r, "name")) for r in records if _rec_get(r, "name")]
    if preferred:
        _FULLTEXT_INDEX_CACHE[cache_key] = preferred if preferred in names else None
    else:
        for candidate in (
            "kgNodeFulltext",
            "kgFulltext",
            "ft_Task_Concept",
            "ft_Region",
            "ft_Publication",
        ):
            if candidate in names:
                _FULLTEXT_INDEX_CACHE[cache_key] = candidate
                break
        else:
            _FULLTEXT_INDEX_CACHE[cache_key] = names[0] if names else None
    return _FULLTEXT_INDEX_CACHE[cache_key]


def _records_to_nodes(records: Iterable[Any]) -> list[KGNodeSummary]:
    results: list[KGNodeSummary] = []
    for record in records:
        node = _rec_get(record, "n") or _rec_get(record, "node")
        if node is None:
            continue
        labels = _rec_get(record, "labels", []) or []
        if not labels and hasattr(node, "labels"):
            labels = list(node.labels)
        node_type = labels[0] if labels else (getattr(node, "type", None) or "Node")
        score = _rec_get(record, "score", 1.0) or 1.0
        label_val = None
        if hasattr(node, "get"):
            label_val = node.get("label") or node.get("name") or node.get("title")
        if not label_val:
            label_val = (
                getattr(node, "label", None)
                or getattr(node, "name", None)
                or getattr(node, "title", None)
                or ""
            )
        props = (
            dict(node)
            if hasattr(node, "keys")
            else (dict(node) if isinstance(node, dict) else None)
        )
        stable_id = _identifier_value_from_props(props) or _stable_node_id(node) or None
        element_id = _element_id(node) or None
        results.append(
            KGNodeSummary(
                kg_id=stable_id or element_id or _node_id(node),
                element_id=element_id,
                label=label_val,
                node_type=node_type,
                score=score,
                properties=props,
            )
        )
    return results


def search_nodes(
    query: str,
    *,
    node_types: Optional[Sequence[str]] = None,
    limit: int = 20,
    db: Optional[Neo4jGraphDB] = None,
    infer_types: bool = True,
    timeout_s: float | None = None,
) -> list[KGNodeSummary]:
    """Lightweight node search over label/name fields.

    Args:
        query: Free-text query for label/name match (case-insensitive substring).
        node_types: Optional label filter (e.g., ["CognitiveConcept", "BrainRegion"]).
        limit: Maximum results to return.
        db: Optional Neo4jGraphDB (injected for tests); defaults to cached client.
    """

    client = db or get_default_db()
    q = (query or "").strip()
    if not q:
        return []

    inferred = (
        _infer_query_hints(q) if infer_types else {"exact_id": None, "node_types": None}
    )
    exact_id = inferred.get("exact_id")
    merged_types = node_types or inferred.get("node_types")
    expanded_types = _expand_types(merged_types)

    if exact_id:
        lookup_terms = _build_lookup_terms(exact_id)
        element_candidates = [
            term for term in lookup_terms if _looks_like_element_id(term)
        ]

        for element_id in element_candidates:
            cypher = """
            MATCH (n)
            WHERE elementId(n) = $id
            AND ($types IS NULL OR any(t IN labels(n) WHERE t IN $types))
            RETURN n, labels(n) AS labels, 100.0 AS score
            LIMIT $limit
            """
            records = _as_list(
                _run_with_optional_timeout(
                    client,
                    cypher,
                    {"id": element_id, "types": expanded_types, "limit": int(limit)},
                    timeout_s=timeout_s,
                )
            )
            if records:
                return _records_to_nodes(records)
        cypher = """
        MATCH (n)
        WHERE ($types IS NULL OR any(t IN labels(n) WHERE t IN $types))
          AND any(term IN $lookup_terms WHERE
            any(key IN $identifier_keys WHERE
              toLower(coalesce(toString(n[key]), '')) = term
            ) OR
            toLower(coalesce(toString(n.label), '')) = term OR
            toLower(coalesce(toString(n.name), '')) = term OR
            toLower(coalesce(toString(n.pmid), '')) = term OR
            toLower(coalesce(toString(n.doi), '')) = term OR
            ('pmid:' + toLower(coalesce(toString(n.pmid), ''))) = term OR
            ('doi:' + toLower(coalesce(toString(n.doi), ''))) = term
          )
        RETURN n, labels(n) AS labels, 100.0 AS score
        LIMIT $limit
        """
        records = _as_list(
            _run_with_optional_timeout(
                client,
                cypher,
                {
                    "lookup_terms": lookup_terms or [exact_id.lower()],
                    "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
                    "types": expanded_types,
                    "limit": int(limit),
                },
                timeout_s=timeout_s,
            )
        )
        if records:
            return _records_to_nodes(records)

    index_name = _resolve_fulltext_index(client, timeout_s=timeout_s)
    if index_name:
        fulltext_query = _build_fulltext_query(q)
        cypher = """
        CALL db.index.fulltext.queryNodes($index, $q) YIELD node, score
        WHERE ($types IS NULL OR any(t IN labels(node) WHERE t IN $types))
        RETURN node, labels(node) AS labels, score
        ORDER BY score DESC, coalesce(node.label, node.name)
        LIMIT $limit
        """
        records = _as_list(
            _run_with_optional_timeout(
                client,
                cypher,
                {
                    "index": index_name,
                    "q": fulltext_query or q,
                    "types": expanded_types,
                    "limit": int(limit),
                },
                timeout_s=timeout_s,
            )
        )
        logger.debug(
            "KG search fulltext index=%s query=%s hits=%s",
            index_name,
            fulltext_query or q,
            len(records),
        )
        if records:
            return _records_to_nodes(records)

    q_tokens = _tokenize_query(q)
    min_token_hits = 1 if len(q_tokens) < 3 else 2
    prefer_semantic = bool(not exact_id and len(q_tokens) <= 1 and not expanded_types)
    preferred_type_labels = sorted(
        {
            _canonical_ood_node_type(value)
            for value in _HYPOTHESIS_PREFERRED_ENTITY_TYPES
            if _canonical_ood_node_type(value) not in {"", "Modality"}
        }
    )
    discouraged_type_labels = ["Publication", "Paper", "Study"]
    token_overlap_expr = """
        size([
          tok IN $q_tokens
          WHERE
            toLower(coalesce(n.label, '')) CONTAINS tok OR
            toLower(coalesce(n.name, '')) CONTAINS tok OR
            toLower(coalesce(n.title, '')) CONTAINS tok OR
            toLower(coalesce(n.id, '')) CONTAINS tok OR
            toLower(coalesce(toString(n.pmid), '')) CONTAINS tok OR
            toLower(coalesce(toString(n.doi), '')) CONTAINS tok OR
            toLower(coalesce(n.dataset_id, '')) CONTAINS tok OR
            toLower(coalesce(n.uid, '')) CONTAINS tok OR
            toLower(coalesce(n.identifier, '')) CONTAINS tok OR
            toLower(coalesce(n.tool_id, '')) CONTAINS tok OR
            toLower(coalesce(n.op_key, '')) CONTAINS tok OR
            toLower(coalesce(n.description, '')) CONTAINS tok OR
            toLower(coalesce(n.definition, '')) CONTAINS tok OR
            any(alias IN coalesce(n.aliases, []) WHERE toLower(alias) CONTAINS tok) OR
            any(synonym IN coalesce(n.synonyms, []) WHERE toLower(synonym) CONTAINS tok) OR
            any(keyword IN coalesce(n.keywords, []) WHERE toLower(keyword) CONTAINS tok)
          | tok
        ])
    """
    cypher = f"""
    MATCH (n)
    WHERE ($types IS NULL OR any(t IN labels(n) WHERE t IN $types))
    WITH n, {token_overlap_expr} AS token_hits
    WHERE
      (
        toLower(coalesce(n.label, '')) CONTAINS $q OR
        toLower(coalesce(n.name, '')) CONTAINS $q OR
        toLower(coalesce(n.title, '')) CONTAINS $q OR
        toLower(coalesce(n.id, '')) CONTAINS $q OR
        toLower(coalesce(toString(n.pmid), '')) CONTAINS $q OR
        toLower(coalesce(toString(n.doi), '')) CONTAINS $q OR
        toLower(coalesce(n.dataset_id, '')) CONTAINS $q OR
        toLower(coalesce(n.uid, '')) CONTAINS $q OR
        toLower(coalesce(n.identifier, '')) CONTAINS $q OR
        toLower(coalesce(n.tool_id, '')) CONTAINS $q OR
        toLower(coalesce(n.op_key, '')) CONTAINS $q OR
        toLower(coalesce(n.description, '')) CONTAINS $q OR
        toLower(coalesce(n.definition, '')) CONTAINS $q OR
        any(alias IN coalesce(n.aliases, []) WHERE toLower(alias) CONTAINS $q) OR
        any(synonym IN coalesce(n.synonyms, []) WHERE toLower(synonym) CONTAINS $q) OR
        any(keyword IN coalesce(n.keywords, []) WHERE toLower(keyword) CONTAINS $q) OR
        ($q_token_count > 0 AND token_hits >= $min_token_hits)
      )
    RETURN n, labels(n) AS labels,
      CASE
        WHEN toLower(coalesce(n.label, '')) CONTAINS $q
          OR toLower(coalesce(n.name, '')) CONTAINS $q
          OR toLower(coalesce(n.title, '')) CONTAINS $q
        THEN 10.0 + toFloat(token_hits)
        ELSE toFloat(token_hits)
      END AS score
    ORDER BY
      CASE
        WHEN $prefer_semantic
          AND any(t IN labels(n) WHERE t IN $preferred_type_labels)
        THEN 1
        WHEN $prefer_semantic
          AND any(t IN labels(n) WHERE t IN $discouraged_type_labels)
        THEN -1
        ELSE 0
      END DESC,
      score DESC,
      coalesce(n.label, n.name, n.title, n.id)
    LIMIT $limit
    """
    params = {
        "q": q.lower(),
        "q_tokens": q_tokens,
        "q_token_count": len(q_tokens),
        "min_token_hits": int(min_token_hits),
        "prefer_semantic": prefer_semantic,
        "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
        "preferred_type_labels": preferred_type_labels,
        "discouraged_type_labels": discouraged_type_labels,
        "types": expanded_types,
        "limit": int(limit),
    }
    records = _as_list(
        _run_with_optional_timeout(client, cypher, params, timeout_s=timeout_s)
    )
    logger.debug("KG search fallback used for query=%s hits=%s", q, len(records))
    return _records_to_nodes(records)


def _infer_filters_from_text(text: str) -> dict[str, Any]:
    text_l = text.lower()
    modality = None
    for key in ("fmri", "meg", "eeg", "dwi", "pet", "structural", "smri"):
        if key in text_l:
            modality = key
            break
    task_ids: list[str] = []
    for task_kw in (
        "motor",
        "visual",
        "language",
        "memory",
        "rest",
        "emotion",
        "attention",
    ):
        if task_kw in text_l:
            task_ids.append(task_kw)
    min_subjects = None
    import re

    for pat in (
        r"at least (\d+)",
        r">=\s*(\d+)",
        r"(\d+) subjects",
        r"(\d+) participants",
    ):
        m = re.search(pat, text_l)
        if m:
            try:
                min_subjects = int(m.group(1))
                break
            except Exception:
                pass
    species = None
    if "human" in text_l or "participant" in text_l:
        species = "human"
    elif "mouse" in text_l or "mice" in text_l or "rodent" in text_l:
        species = "mouse"
    return {
        "modality": modality,
        "task_ids": task_ids or None,
        "min_subjects": min_subjects,
        "species": species,
    }


def _structured_tool_query_where(
    *,
    exposed_only: bool,
    default_only: bool,
    primary_intents: Optional[Sequence[str]],
    softwares: Optional[Sequence[str]],
    query: Optional[str],
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    if default_only:
        clauses.append("t.is_default = true")
    params: dict[str, Any] = {}
    if exposed_only:
        clauses.append("t.exposed = true")
    if primary_intents:
        clauses.append("t.primary_intent IN $primary_intents")
        params["primary_intents"] = list(primary_intents)
    if softwares:
        clauses.append("t.software IN $softwares")
        params["softwares"] = list(softwares)
    if query:
        tokens = _tokenize_query(query)
        if tokens:
            clauses.append(
                "ANY(tok IN $q_tokens WHERE "
                "toLower(coalesce(t.primary_intent,'')) CONTAINS tok "
                "OR toLower(coalesce(t.category,'')) CONTAINS tok "
                "OR toLower(coalesce(t.op,'')) CONTAINS tok "
                "OR toLower(coalesce(t.description,'')) CONTAINS tok "
                "OR toLower(coalesce(t.tool_id,'')) CONTAINS tok "
                "OR ANY(i IN coalesce(t.intents, []) WHERE toLower(i) CONTAINS tok))"
            )
            params["q_tokens"] = tokens
    where = " AND ".join(clauses) if clauses else "TRUE"
    return where, params


def _tokenize_query(text: Optional[str]) -> list[str]:
    if not text:
        return []
    import re

    # Keep alnum tokens only; drop very short tokens to reduce noise.
    toks = [t for t in re.split(r"[^a-zA-Z0-9]+", text.lower()) if len(t) >= 3]

    # Stopword filter: prevents common English tokens from matching tool descriptions
    # and causing unrelated candidates to appear for nonsense queries.
    stopwords = {
        "the",
        "and",
        "that",
        "this",
        "with",
        "from",
        "into",
        "onto",
        "over",
        "under",
        "about",
        "have",
        "has",
        "had",
        "been",
        "being",
        "are",
        "is",
        "was",
        "were",
        "will",
        "would",
        "should",
        "could",
        "can",
        "to",
        "of",
        "in",
        "on",
        "for",
        "as",
        "at",
        "by",
        "or",
        "not",
        "no",
        "please",
        "help",
        "me",
        "my",
        "your",
        "our",
        "we",
        "you",
        "i",
        # Generic verbs/nouns that create spurious overlaps with tool descriptions.
        "run",
        "execute",
        "analysis",
        "analyze",
        "compute",
        "show",
        "get",
        "generate",
        "query",
        "match",
        "matches",
        "nothing",
        "something",
    }
    toks = [t for t in toks if t not in stopwords]
    return toks


def _priority_rank(method: Optional[str], intent_config: dict[str, Any]) -> int:
    if not method:
        return 10_000
    priority = (
        intent_config.get("priority", [])
        or intent_config.get("method_priority", [])
        or []
    )
    try:
        return int(priority.index(method))
    except Exception:
        return 10_000


def _overlap_score(tokens: list[str], haystack: str) -> tuple[int, list[str]]:
    if not tokens or not haystack:
        return 0, []
    hay_l = haystack.lower()
    matched = [t for t in tokens if t and t in hay_l]
    return len(matched), matched


def _weighted_tool_overlap_score(
    tokens: list[str],
    *,
    tool_id: str,
    method: Optional[str],
    software: Optional[str],
    version: Optional[str],
    op: Optional[str],
    op_key: Optional[str],
    category: Optional[str],
    intents: Any,
    description: Optional[str],
) -> tuple[int, list[str]]:
    """Weighted overlap score for tool candidates.

    Goal: prefer tokens that match stable identifiers (tool_id/op/op_key) over
    generic occurrences in free-text descriptions (e.g. "fast" meaning speed).
    """
    if not tokens:
        return 0, []

    tool_id_l = (tool_id or "").lower()
    op_l = (op or "").lower()
    op_key_l = (op_key or "").lower()
    method_l = (method or "").lower()
    category_l = (category or "").lower()
    desc_l = (description or "").lower()
    software_l = (software or "").lower()
    version_l = (version or "").lower()

    intents_l: list[str] = []
    if isinstance(intents, list):
        intents_l = [str(i).lower() for i in intents if i is not None]
    elif isinstance(intents, str):
        intents_l = [intents.lower()]

    score = 0
    matched: list[str] = []
    for tok in tokens:
        tok_score = 0
        if tok in tool_id_l or tok in op_l or tok in op_key_l:
            tok_score += 3
        if tok in method_l or tok in category_l:
            tok_score += 2
        if tok in software_l or tok in version_l:
            tok_score += 2
        if intents_l and any(tok in i for i in intents_l):
            tok_score += 2
        if tok in desc_l:
            tok_score += 1
        if tok_score:
            score += tok_score
            matched.append(tok)
    return score, matched


def _op_key_filter_candidates(op_key: Optional[str]) -> list[str]:
    """Return candidate spellings used when filtering by op_key.

    We accept both raw spellings (e.g., ``encoding_model``) and normalized
    spellings (e.g., ``encodingmodel``) to bridge KG-vs-caller conventions.
    """

    if not op_key:
        return []

    from brain_researcher.services.neurokg.loader.tools_catalog_loader import (
        normalize_op_key,
    )

    out: list[str] = []
    raw = str(op_key).strip().lower()
    if raw:
        out.append(raw)
    normalized = normalize_op_key(op_key)
    if normalized and normalized not in out:
        out.append(normalized)
    return out


def _structured_tool_resolve_where(
    *,
    method: Optional[str],
    software: Optional[str],
    op_key: Optional[str],
    exposed_only: bool,
    default_only: bool,
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if default_only:
        clauses.append("t.is_default = true")
    if exposed_only:
        clauses.append("t.exposed = true")
    if method:
        clauses.append("t.primary_intent = $method")
        params["method"] = method
    if software:
        clauses.append("t.software = $software")
        params["software"] = software
    if op_key:
        op_key_candidates = _op_key_filter_candidates(op_key)
        if op_key_candidates:
            clauses.append("toLower(coalesce(t.op_key, '')) IN $op_key_candidates")
            params["op_key_candidates"] = op_key_candidates
    where = " AND ".join(clauses) if clauses else "TRUE"
    return where, params


def _structured_from_catalog(
    *,
    query: Optional[str],
    primary_intents: Optional[Sequence[str]],
    softwares: Optional[Sequence[str]],
    exposed_only: bool,
    k_methods: int,
    k_softwares: int,
    k_candidates: int,
    fallback_reason: Optional[str] = None,
) -> dict[str, Any]:
    from collections import Counter, defaultdict

    from brain_researcher.services.neurokg.loader.tools_catalog_loader import (
        load_intent_config,
        normalize_op_key,
        parse_tool_id,
        resolve_op_key_method,
        select_primary_intent,
    )
    from brain_researcher.services.tools.registry import UnifiedToolRegistry

    reg = UnifiedToolRegistry()
    specs = reg.get_exposed_toolspecs() if exposed_only else reg.get_all_toolspecs()
    intent_config = load_intent_config()

    filtered = []
    for spec in specs:
        intents = list(spec.intents or [])
        category = spec.category
        method = select_primary_intent(intents, category, [], intent_config)
        parsed = parse_tool_id(spec.name, None)
        software = parsed.get("software")
        op = parsed.get("op") or spec.name
        op_key = normalize_op_key(op) or normalize_op_key(spec.name)
        mapped_method = resolve_op_key_method(op_key, intent_config)
        if mapped_method and (method is None or method == category):
            method = mapped_method
        if primary_intents and method not in primary_intents:
            continue
        if softwares and software not in softwares:
            continue
        if query:
            tokens = _tokenize_query(query)
            if tokens:
                hay = " ".join(
                    [spec.name, spec.description or "", " ".join(intents)]
                ).lower()
                if not any(tok in hay for tok in tokens):
                    continue
        filtered.append(
            {
                "tool_id": spec.name,
                "method": method,
                "software": software,
                "version": parsed.get("version"),
                "op": op,
                "op_key": op_key,
            }
        )

    method_counts = Counter([c["method"] for c in filtered if c.get("method")])
    methods = []
    for method, count in method_counts.most_common(k_methods):
        top_softs = Counter(
            [
                c["software"]
                for c in filtered
                if c.get("method") == method and c.get("software")
            ]
        ).most_common(k_softwares)
        methods.append(
            {
                "method": method,
                "count": count,
                "top_softwares": [s for s, _ in top_softs],
            }
        )
    if query:
        tokens = _tokenize_query(query)
        if tokens:
            intent_config = load_intent_config()
            for item in methods:
                score, matched = _overlap_score(tokens, str(item.get("method") or ""))
                item["score"] = score
                item["matched"] = matched[:5]
            methods.sort(
                key=lambda m: (
                    -int(m.get("score") or 0),
                    _priority_rank(m.get("method"), intent_config),
                    -int(m.get("count") or 0),
                    str(m.get("method") or ""),
                )
            )

    software_counts = Counter([c["software"] for c in filtered if c.get("software")])
    software_methods: dict[str, set[str]] = defaultdict(set)
    for c in filtered:
        if c.get("software") and c.get("method"):
            software_methods[c["software"]].add(c["method"])
    softwares_out = []
    for software, count in software_counts.most_common(k_softwares):
        softwares_out.append(
            {
                "software": software,
                "count": count,
                "methods": sorted(software_methods.get(software, [])),
            }
        )

    tokens = _tokenize_query(query)
    intent_config = load_intent_config()
    if tokens:
        for c in filtered:
            score, matched = _weighted_tool_overlap_score(
                tokens,
                tool_id=str(c.get("tool_id") or ""),
                method=c.get("method"),
                software=c.get("software"),
                version=c.get("version"),
                op=c.get("op"),
                op_key=c.get("op_key"),
                category=None,
                intents=None,
                description=None,
            )
            c["score"] = score
            c["matched"] = matched[:8]

    def score_candidate(c: dict[str, Any]) -> tuple[int, int, str]:
        score = int(c.get("score") or 0)
        return (
            -score,
            _priority_rank(c.get("method"), intent_config),
            str(c.get("tool_id") or ""),
        )

    if filtered:
        filtered.sort(key=score_candidate)
        candidates = filtered[:k_candidates]
        recommendation = candidates[0]
    else:
        candidates = []
        recommendation = None

    out = {
        "methods": methods,
        "softwares": softwares_out,
        "candidates": candidates,
        "recommendation": recommendation,
        "limits": {
            "methods": k_methods,
            "softwares": k_softwares,
            "candidates": k_candidates,
        },
        "source": "catalog_fallback",
        "resolver_mode": "catalog_fallback",
        "confidence": "low",
    }
    if fallback_reason:
        out["fallback_reason"] = fallback_reason
    return out


def _resolve_from_catalog(
    *,
    method: Optional[str],
    software: Optional[str],
    op_key: Optional[str],
    prefer_version: Optional[str],
    exposed_only: bool,
    fallback_reason: Optional[str] = None,
) -> dict[str, Any]:
    from brain_researcher.services.neurokg.loader.tools_catalog_loader import (
        load_intent_config,
        normalize_op_key,
        parse_tool_id,
        resolve_op_key_method,
        select_primary_intent,
    )
    from brain_researcher.services.tools.registry import UnifiedToolRegistry

    reg = UnifiedToolRegistry()
    specs = reg.get_exposed_toolspecs() if exposed_only else reg.get_all_toolspecs()
    intent_config = load_intent_config()
    op_key_candidates = _op_key_filter_candidates(op_key)

    candidates: list[dict[str, Any]] = []
    for spec in specs:
        intents = list(spec.intents or [])
        category = spec.category
        resolved_method = select_primary_intent(intents, category, [], intent_config)
        parsed = parse_tool_id(spec.name, None)
        resolved_software = parsed.get("software")
        resolved_op = parsed.get("op") or spec.name
        resolved_op_key = normalize_op_key(resolved_op) or normalize_op_key(spec.name)
        resolved_version = parsed.get("version")
        mapped_method = resolve_op_key_method(resolved_op_key, intent_config)
        if mapped_method and (resolved_method is None or resolved_method == category):
            resolved_method = mapped_method
        if method and resolved_method != method:
            continue
        if software and resolved_software != software:
            continue
        if op_key_candidates and resolved_op_key not in op_key_candidates:
            continue
        if prefer_version and resolved_version != prefer_version:
            continue
        candidates.append(
            {
                "tool_id": spec.name,
                "method": resolved_method,
                "software": resolved_software,
                "version": resolved_version,
                "op": resolved_op,
                "op_key": resolved_op_key,
            }
        )

    if candidates:
        recommendation = candidates[0]
    elif prefer_version:
        # Retry without version pin.
        return _resolve_from_catalog(
            method=method,
            software=software,
            op_key=op_key,
            prefer_version=None,
            exposed_only=exposed_only,
            fallback_reason=fallback_reason,
        )
    else:
        recommendation = None

    out = {
        "recommendation": recommendation,
        "candidates": candidates[:10],
        "source": "catalog_fallback",
        "resolver_mode": "catalog_fallback",
        "confidence": "low",
    }
    if fallback_reason:
        out["fallback_reason"] = fallback_reason
    return out


def search_tools_structured(
    *,
    query: Optional[str] = None,
    primary_intents: Optional[Sequence[str]] = None,
    softwares: Optional[Sequence[str]] = None,
    exposed_only: bool = True,
    default_only: bool = True,
    k_methods: int = 8,
    k_softwares: int = 5,
    k_candidates: int = 50,
    force_fallback: bool = False,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    """Structured tool search (method → software → version) over KG.

    Returns small, collapsed candidate sets and never dumps full tool_id lists.
    Set default_only=False to include non-default tool variants.
    """
    if force_fallback:
        return _structured_from_catalog(
            query=query,
            primary_intents=primary_intents,
            softwares=softwares,
            exposed_only=exposed_only,
            k_methods=int(k_methods),
            k_softwares=int(k_softwares),
            k_candidates=int(k_candidates),
            fallback_reason="force_fallback",
        )
    try:
        client = db or get_default_db()
        where, params = _structured_tool_query_where(
            exposed_only=exposed_only,
            default_only=default_only,
            primary_intents=primary_intents,
            softwares=softwares,
            query=query,
        )

        params_methods = dict(params)
        params_methods["k_methods"] = int(k_methods)

        cypher_methods = f"""
        MATCH (t:Tool)
        WHERE {where} AND t.primary_intent IS NOT NULL
        RETURN t.primary_intent AS method, count(*) AS n
        ORDER BY n DESC
        LIMIT $k_methods
        """
        method_records = _as_list(client._run(cypher_methods, params_methods))
        methods: list[dict[str, Any]] = []
        for rec in method_records:
            method = _rec_get(rec, "method")
            count = _rec_get(rec, "n", 0)
            if not method:
                continue
            # top softwares for each method
            cypher_soft = f"""
            MATCH (t:Tool)
            WHERE {where} AND t.primary_intent = $method AND t.software IS NOT NULL
            RETURN t.software AS software, count(*) AS n
            ORDER BY n DESC
            LIMIT $k_softwares
            """
            soft_records = _as_list(
                client._run(
                    cypher_soft,
                    {**params, "method": method, "k_softwares": int(k_softwares)},
                )
            )
            methods.append(
                {
                    "method": method,
                    "count": count,
                    "top_softwares": [
                        _rec_get(r, "software")
                        for r in soft_records
                        if _rec_get(r, "software")
                    ],
                }
            )
        # If a query is provided, prefer methods whose intent strings match the query tokens.
        if query:
            tokens = _tokenize_query(query)
            if tokens:
                from brain_researcher.services.neurokg.loader.tools_catalog_loader import (
                    load_intent_config,
                )

                intent_config = load_intent_config()
                for item in methods:
                    score, matched = _overlap_score(
                        tokens, str(item.get("method") or "")
                    )
                    item["score"] = score
                    item["matched"] = matched[:5]
                methods.sort(
                    key=lambda m: (
                        -int(m.get("score") or 0),
                        _priority_rank(m.get("method"), intent_config),
                        -int(m.get("count") or 0),
                        str(m.get("method") or ""),
                    )
                )

        params_soft = dict(params)
        params_soft["k_softwares"] = int(k_softwares)
        cypher_softwares = f"""
        MATCH (t:Tool)
        WHERE {where} AND t.software IS NOT NULL
        WITH t.software AS software, collect(distinct t.primary_intent) AS methods, count(*) AS n
        RETURN software, n, methods
        ORDER BY n DESC
        LIMIT $k_softwares
        """
        software_records = _as_list(client._run(cypher_softwares, params_soft))
        softwares_out = [
            {
                "software": _rec_get(r, "software"),
                "count": _rec_get(r, "n", 0),
                "methods": _rec_get(r, "methods", []) or [],
            }
            for r in software_records
            if _rec_get(r, "software")
        ]

        params_candidates = dict(params)
        params_candidates["k_candidates"] = int(k_candidates)
        q_tokens = _tokenize_query(query)
        params_candidates["q_tokens"] = q_tokens
        cypher_candidates = f"""
        MATCH (t:Tool)
        WHERE {where}
        WITH
          t,
          CASE
            WHEN $q_tokens IS NULL OR size($q_tokens) = 0 THEN 0
            ELSE reduce(
              score = 0,
              tok IN $q_tokens |
                score
                + CASE
                    WHEN toLower(coalesce(t.tool_id,'')) CONTAINS tok
                      OR toLower(coalesce(t.op,'')) CONTAINS tok
                      OR toLower(coalesce(t.op_key,'')) CONTAINS tok
                    THEN 3 ELSE 0 END
                + CASE
                    WHEN toLower(coalesce(t.primary_intent,'')) CONTAINS tok
                      OR toLower(coalesce(t.category,'')) CONTAINS tok
                    THEN 2 ELSE 0 END
                + CASE
                    WHEN toLower(coalesce(t.software,'')) CONTAINS tok
                      OR toLower(coalesce(t.version,'')) CONTAINS tok
                    THEN 2 ELSE 0 END
                + CASE
                    WHEN ANY(i IN coalesce(t.intents, []) WHERE toLower(i) CONTAINS tok)
                    THEN 2 ELSE 0 END
                + CASE
                    WHEN toLower(coalesce(t.description,'')) CONTAINS tok
                    THEN 1 ELSE 0 END
            )
          END AS score
        RETURN
          t.tool_id AS tool_id,
          t.primary_intent AS method,
          t.software AS software,
          t.version AS version,
          t.op AS op,
          t.op_key AS op_key,
          t.exposure_group AS exposure_group,
          t.category AS category,
          t.intents AS intents,
          t.description AS description,
          score AS score
        ORDER BY score DESC, t.primary_intent, t.software, t.op_key, t.tool_id
        LIMIT $k_candidates
        """
        candidate_records = _as_list(client._run(cypher_candidates, params_candidates))
        from brain_researcher.services.neurokg.loader.tools_catalog_loader import (
            load_intent_config,
        )

        intent_config = load_intent_config()
        tokens = q_tokens

        candidates: list[dict[str, Any]] = []
        for r in candidate_records:
            tool_id = _rec_get(r, "tool_id")
            if not tool_id:
                continue
            method = _rec_get(r, "method")
            software = _rec_get(r, "software")
            op = _rec_get(r, "op")
            op_key = _rec_get(r, "op_key")
            category = _rec_get(r, "category")
            intents = _rec_get(r, "intents") or []
            description = _rec_get(r, "description") or ""
            score, matched = _weighted_tool_overlap_score(
                tokens,
                tool_id=str(tool_id),
                method=method,
                software=software,
                version=_rec_get(r, "version"),
                op=op,
                op_key=op_key,
                category=category,
                intents=intents,
                description=description,
            )

            candidates.append(
                {
                    "tool_id": tool_id,
                    "method": method,
                    "software": software,
                    "version": _rec_get(r, "version"),
                    "op": op,
                    "op_key": op_key,
                    "exposure_group": _rec_get(r, "exposure_group"),
                    # Recompute score on the combined haystack for explainability.
                    # Cypher score is used only for candidate preselection.
                    "score": score,
                    "matched": matched[:8],
                }
            )

        # Prefer higher overlap score; tie-break by method priority; final tie-break stable.
        candidates.sort(
            key=lambda c: (
                -int(c.get("score") or 0),
                _priority_rank(c.get("method"), intent_config),
                str(c.get("tool_id") or ""),
            )
        )
        recommendation = candidates[0] if candidates else None

        return {
            "methods": methods,
            "softwares": softwares_out,
            "candidates": candidates,
            "recommendation": recommendation,
            "limits": {
                "methods": k_methods,
                "softwares": k_softwares,
                "candidates": k_candidates,
            },
            "source": "neurokg",
            "resolver_mode": "neurokg",
            "confidence": "high",
        }
    except Exception as exc:
        # Fallback to local catalog view with same schema
        return _structured_from_catalog(
            query=query,
            primary_intents=primary_intents,
            softwares=softwares,
            exposed_only=exposed_only,
            k_methods=int(k_methods),
            k_softwares=int(k_softwares),
            k_candidates=int(k_candidates),
            fallback_reason=f"neurokg_error:{type(exc).__name__}",
        )


def resolve_tool_structured(
    *,
    method: Optional[str] = None,
    software: Optional[str] = None,
    op_key: Optional[str] = None,
    prefer_version: Optional[str] = None,
    exposed_only: bool = True,
    default_only: bool = True,
    force_fallback: bool = False,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    """Resolve a single tool_id from method/software/op_key (optionally version-pinned).

    If prefer_version is supplied and default_only is True, the version pin will only
    succeed when that version is also the default. Set default_only=False to allow
    explicit version picks.
    """
    if force_fallback:
        return _resolve_from_catalog(
            method=method,
            software=software,
            op_key=op_key,
            prefer_version=prefer_version,
            exposed_only=exposed_only,
            fallback_reason="force_fallback",
        )
    try:
        client = db or get_default_db()
        where, params = _structured_tool_resolve_where(
            method=method,
            software=software,
            op_key=op_key,
            exposed_only=exposed_only,
            default_only=default_only,
        )

        if prefer_version:
            params_version = dict(params)
            params_version["prefer_version"] = prefer_version
            cypher_version = f"""
            MATCH (t:Tool)
            WHERE {where} AND t.version = $prefer_version
            RETURN t.tool_id AS tool_id,
                   t.primary_intent AS method,
                   t.software AS software,
                   t.version AS version,
                   t.op AS op,
                   t.op_key AS op_key,
                   t.exposure_group AS exposure_group,
                   t.is_default AS is_default,
                   t.exposed AS exposed
            LIMIT 1
            """
            recs = _as_list(client._run(cypher_version, params_version))
            if recs:
                rec = recs[0]
                return {
                    "recommendation": {
                        "tool_id": _rec_get(rec, "tool_id"),
                        "method": _rec_get(rec, "method"),
                        "software": _rec_get(rec, "software"),
                        "version": _rec_get(rec, "version"),
                        "op": _rec_get(rec, "op"),
                        "op_key": _rec_get(rec, "op_key"),
                        "exposure_group": _rec_get(rec, "exposure_group"),
                        "is_default": _rec_get(rec, "is_default"),
                        "exposed": _rec_get(rec, "exposed"),
                    },
                    "source": "neurokg",
                    "resolver_mode": "neurokg",
                    "confidence": "high",
                }

        cypher_default = f"""
        MATCH (t:Tool)
        WHERE {where}
        RETURN t.tool_id AS tool_id,
               t.primary_intent AS method,
               t.software AS software,
               t.version AS version,
               t.op AS op,
               t.op_key AS op_key,
               t.exposure_group AS exposure_group,
               t.is_default AS is_default,
               t.exposed AS exposed
        ORDER BY t.primary_intent, t.software, t.op_key, t.tool_id
        LIMIT 1
        """
        recs = _as_list(client._run(cypher_default, params))
        if not recs:
            return {
                "recommendation": None,
                "source": "neurokg",
                "resolver_mode": "neurokg",
                "confidence": "high",
            }
        rec = recs[0]
        return {
            "recommendation": {
                "tool_id": _rec_get(rec, "tool_id"),
                "method": _rec_get(rec, "method"),
                "software": _rec_get(rec, "software"),
                "version": _rec_get(rec, "version"),
                "op": _rec_get(rec, "op"),
                "op_key": _rec_get(rec, "op_key"),
                "exposure_group": _rec_get(rec, "exposure_group"),
                "is_default": _rec_get(rec, "is_default"),
                "exposed": _rec_get(rec, "exposed"),
            },
            "source": "neurokg",
            "resolver_mode": "neurokg",
            "confidence": "high",
        }
    except Exception as exc:
        return _resolve_from_catalog(
            method=method,
            software=software,
            op_key=op_key,
            prefer_version=prefer_version,
            exposed_only=exposed_only,
            fallback_reason=f"neurokg_error:{type(exc).__name__}",
        )


def search_datasets(
    *,
    text: str | None = None,
    task_ids: Optional[Sequence[str]] = None,
    modality: str | None = None,
    min_subjects: int | None = None,
    species: str | None = None,
    limit: int = 20,
    db: Optional[Neo4jGraphDB] = None,
    infer_from_text: bool = True,
    timeout_s: float | None = None,
) -> list[DatasetSummary]:
    """Search dataset subgraph by common filters (supports simple NL hints)."""

    client = db or get_default_db()
    # Light NLP-based inference from the free-text when explicit filters are not provided
    if infer_from_text and text:
        inferred = _infer_filters_from_text(text)
        modality = modality or inferred.get("modality")
        task_ids = task_ids or inferred.get("task_ids")
        min_subjects = min_subjects or inferred.get("min_subjects")
        species = species or inferred.get("species")

    # NOTE: Keep dataset-level filters attached to a dataset `MATCH`/`WITH`.
    # Cypher `WHERE` binds to the immediately preceding clause; placing dataset
    # filters after `OPTIONAL MATCH` can silently turn them into optional-match
    # conditions (i.e., not filtering datasets at all).
    cypher = """
    MATCH (d:Dataset)
    WHERE ($text IS NULL OR toLower(coalesce(d.title, d.name, d.dataset_id, '')) CONTAINS $text)
      AND ($species IS NULL OR toLower(coalesce(d.species, '')) = toLower($species))
      AND ($min_subjects IS NULL OR coalesce(d.subjects_count, 0) >= $min_subjects)
    WITH d
    OPTIONAL MATCH (d)-[:HAS_TASK]->(t:Task)
    OPTIONAL MATCH (d)-[:HAS_MODALITY]->(m:Modality)
    WITH d,
         collect(DISTINCT t.name) AS tasks,
         collect(DISTINCT t.id) AS task_node_ids,
         collect(DISTINCT m.name) AS modalities
    WHERE ($modality IS NULL OR any(mod IN modalities WHERE toLower(mod) = toLower($modality)))
      AND (
        $task_ids IS NULL
        OR any(tid IN $task_ids WHERE
          any(name IN tasks WHERE toLower(name) = toLower(tid))
          OR any(node_id IN task_node_ids WHERE toLower(node_id) = toLower(tid))
        )
      )
    RETURN d,
           tasks,
           modalities,
           d.species AS species,
           d.subjects_count AS n_subjects
    LIMIT $limit
    """
    params = {
        "text": text.lower() if text else None,
        "task_ids": list(task_ids) if task_ids else None,
        "modality": modality,
        "min_subjects": min_subjects,
        "species": species,
        "limit": int(limit),
    }
    records = _as_list(
        _run_with_optional_timeout(client, cypher, params, timeout_s=timeout_s)
    )

    results: list[DatasetSummary] = []
    for record in records:
        d = _rec_get(record, "d")
        if d is None:
            continue
        if hasattr(d, "get"):
            dataset_id = d.get("dataset_id")
        else:
            dataset_id = getattr(d, "dataset_id", None)
        tasks = _rec_get(record, "tasks", []) or []
        modalities = _rec_get(record, "modalities", []) or []
        n_subjects = _rec_get(record, "n_subjects", None)
        species_val = _rec_get(record, "species", None)
        title = None
        if hasattr(d, "get"):
            title = d.get("title") or d.get("name")
        if not title:
            title = getattr(d, "title", None) or getattr(d, "name", None)
        results.append(
            DatasetSummary(
                dataset_id=dataset_id or _node_id(d),
                title=title,
                tasks=[t for t in tasks if t],
                modalities=[m for m in modalities if m],
                n_subjects=n_subjects,
                kg_id=_node_id(d),
                species=species_val,
            )
        )
    return results


def list_dataset_onvoc_links(
    *,
    onvoc_id: str | None = None,
    page: int = 1,
    page_size: int = 100,
    db: Optional[Neo4jGraphDB] = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """Return paginated direct Dataset->ONVOC annotation links.

    Pagination is applied to dataset seeds before ONVOC aggregation so the query
    shape remains bounded even when the graph is large.
    """

    client = db or get_default_db()
    page_num = max(1, int(page))
    per_page = max(1, int(page_size))
    skip = (page_num - 1) * per_page
    onvoc_id_norm = (onvoc_id or "").strip().lower() or None

    onvoc_match = """
    (
      any(lbl IN labels(o) WHERE lbl IN ['Concept', 'OnvocClass', 'OntologyConcept', 'LegacyOnvocTag'])
      AND (
        toUpper(coalesce(o.scheme, '')) IN ['ONVOC', 'ONVOC_LEGACY']
        OR toUpper(coalesce(o.id, '')) STARTS WITH 'ONVOC_'
        OR toUpper(coalesce(o.id, '')) STARTS WITH 'ONVOC:'
        OR toLower(coalesce(o.id, '')) STARTS WITH 'legacy_onvoc:'
      )
    )
    """

    count_cypher = f"""
    MATCH (d:Dataset)
    WHERE EXISTS {{
      MATCH (d)-[r]-(o)
      WHERE type(r) IN ['IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
        AND {onvoc_match}
        AND (
          $onvoc_id IS NULL
          OR toLower(coalesce(o.id, '')) = $onvoc_id
          OR toLower(coalesce(o.legacy_onvoc_id, '')) = $onvoc_id
        )
    }}
    RETURN count(DISTINCT d) AS total
    """
    count_records = _as_list(
        _run_with_optional_timeout(
            client,
            count_cypher,
            {"onvoc_id": onvoc_id_norm},
            timeout_s=timeout_s,
        )
    )
    total = int(_rec_get(count_records[0], "total", 0) or 0) if count_records else 0

    if total == 0:
        return {
            "items": [],
            "page": page_num,
            "page_size": per_page,
            "total": 0,
            "has_more": False,
        }

    page_cypher = f"""
    CALL {{
      MATCH (d:Dataset)
      WHERE EXISTS {{
        MATCH (d)-[r]-(o)
        WHERE type(r) IN ['IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
          AND {onvoc_match}
          AND (
            $onvoc_id IS NULL
            OR toLower(coalesce(o.id, '')) = $onvoc_id
            OR toLower(coalesce(o.legacy_onvoc_id, '')) = $onvoc_id
          )
      }}
      RETURN d
      ORDER BY toLower(coalesce(d.dataset_id, d.id, elementId(d)))
      SKIP $skip
      LIMIT $page_size
    }}
    OPTIONAL MATCH (d)-[rin]-(o)
    WHERE type(rin) IN ['IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
      AND {onvoc_match}
      AND (
        $onvoc_id IS NULL
        OR toLower(coalesce(o.id, '')) = $onvoc_id
        OR toLower(coalesce(o.legacy_onvoc_id, '')) = $onvoc_id
      )
    WITH
      d,
      collect(
        DISTINCT {{
          id: coalesce(o.id, elementId(o)),
          label: coalesce(o.label, o.name),
          confidence: rin.confidence
        }}
      ) AS onvoc_links
    RETURN d, onvoc_links
    ORDER BY toLower(coalesce(d.dataset_id, d.id, elementId(d)))
    """
    page_records = _as_list(
        _run_with_optional_timeout(
            client,
            page_cypher,
            {
                "onvoc_id": onvoc_id_norm,
                "skip": skip,
                "page_size": per_page,
            },
            timeout_s=timeout_s,
        )
    )

    items: list[DatasetOnvocLinkSummary] = []
    for record in page_records:
        d = _rec_get(record, "d")
        if d is None:
            continue
        props = (
            dict(d) if hasattr(d, "keys") else (dict(d) if isinstance(d, dict) else {})
        )
        dataset_id = (
            props.get("dataset_id")
            or props.get("id")
            or props.get("uid")
            or _node_id(d)
        )
        items.append(
            DatasetOnvocLinkSummary(
                dataset_id=str(dataset_id or ""),
                title=props.get("title") or props.get("name"),
                kg_id=_node_id(d),
                primary_onvoc_id=props.get("primary_onvoc_id"),
                primary_onvoc_confidence=props.get("primary_onvoc_confidence"),
                onvoc_links=[
                    link
                    for link in (_rec_get(record, "onvoc_links", []) or [])
                    if isinstance(link, dict) and link.get("id")
                ],
            )
        )

    return {
        "items": items,
        "page": page_num,
        "page_size": per_page,
        "total": total,
        "has_more": skip + len(items) < total,
    }


def dataset_resources(
    dataset_ref: str,
    *,
    dataset_version: str | None = None,
    analysis_goal: str = "generic",
    semantic_intent: str | None = None,
    auto_heal: bool = False,
    run_bids_validation: bool = True,
    enforce_semantic_gate: bool = True,
    check_source_access: bool = True,
    db: Optional[Neo4jGraphDB] = None,
    loader=None,
) -> Optional[DatasetResourceSummary]:
    """Return lightweight dataset resources.

    `loader` is kept injectable so tests can substitute `collect_dataset_resources`.
    """

    from brain_researcher.services.agent.kg_resolution import collect_dataset_resources

    resolver = loader or collect_dataset_resources
    try:
        resources = resolver(
            dataset_ref,
            dataset_version=dataset_version,
            analysis_goal=analysis_goal,
            semantic_intent=semantic_intent,
            auto_heal=auto_heal,
            run_bids_validation=run_bids_validation,
            enforce_semantic_gate=enforce_semantic_gate,
            check_source_access=check_source_access,
        )
    except TypeError:
        try:
            resources = resolver(
                dataset_ref,
                dataset_version=dataset_version,
            )
        except TypeError:
            resources = resolver(dataset_ref)
    if not resources:
        return None

    # Attempt to find KG node to attach kg_id (only if a db is provided so we
    # don't eagerly open new connections in lightweight callers/tests).
    kg_id = None
    if db is not None:
        try:
            matches = search_datasets(text=dataset_ref, limit=1, db=db)
            if matches:
                kg_id = matches[0].kg_id
        except Exception:  # pragma: no cover - defensive
            kg_id = None

    return DatasetResourceSummary(
        dataset_id=dataset_ref,
        resolved_dataset_id=getattr(resources, "resolved_dataset_id", None),
        resolution_mode=getattr(resources, "resolution_mode", None),
        resolver_warnings=list(getattr(resources, "resolver_warnings", []) or []),
        local_path=str(resources.local_path)
        if getattr(resources, "local_path", None)
        else None,
        bids_path=str(resources.bids_path) if resources.bids_path else None,
        is_bids_available=resources.is_bids_available,
        derivatives=resources.derivatives,
        available_derivatives=resources.available_derivatives,
        remote_urls=resources.remote_urls,
        size_bytes=resources.size_bytes,
        analysis_goal=resources.analysis_goal,
        source_trace=resources.source_trace,
        required_files=resources.required_files,
        readiness=resources.readiness,
        auto_heal=resources.auto_heal,
        semantic_match=resources.semantic_match,
        source_access=resources.source_access,
        dataset_name=getattr(resources, "dataset_name", "") or "",
        display_name=getattr(resources, "display_name", "") or "",
        source_repo=getattr(resources, "source_repo", "") or "",
        dataset_metadata=dict(getattr(resources, "dataset_metadata", {}) or {}),
        mount_status=dict(getattr(resources, "mount_status", {}) or {}),
        kg_id=kg_id,
    )


def node_details(
    kg_id: str,
    *,
    db: Optional[Neo4jGraphDB] = None,
    timeout_s: float | None = None,
    include_neighbors: bool = True,
) -> Optional[KGNodeSummary]:
    """Fetch a single node by KG id with a trimmed property set."""

    client = db or get_default_db()
    lookup_terms = _build_lookup_terms(kg_id)
    result: list[Any] = []
    element_candidates = [term for term in lookup_terms if _looks_like_element_id(term)]
    return_clause = (
        "RETURN n, labels(n) AS labels, "
        "collect({rel:type(r), target: coalesce(nbr.id, elementId(nbr))}) AS neighbors "
        "LIMIT 1"
        if include_neighbors
        else "RETURN n, labels(n) AS labels LIMIT 1"
    )
    if element_candidates:
        optional_match = "OPTIONAL MATCH (n)-[r]->(nbr)" if include_neighbors else ""
        cypher = f"""
            MATCH (n)
            WHERE elementId(n) = $id
            {optional_match}
            {return_clause}
            """
        for candidate in element_candidates:
            try:
                result = _as_list(
                    _run_with_optional_timeout(
                        client,
                        cypher,
                        {"id": candidate},
                        timeout_s=timeout_s,
                    )
                )
            except Exception:  # pragma: no cover - defensive fallback
                result = []
            if result:
                break
    if not result:
        optional_match = "OPTIONAL MATCH (n)-[r]->(nbr)" if include_neighbors else ""
        cypher = f"""
        MATCH (n)
        WHERE any(term IN $lookup_terms WHERE
            {_identifier_exact_match_clause("n")} OR
            toLower(coalesce(toString(n.pmid), '')) = term OR
            toLower(coalesce(toString(n.doi), '')) = term OR
            ('pmid:' + toLower(coalesce(toString(n.pmid), ''))) = term OR
            ('doi:' + toLower(coalesce(toString(n.doi), ''))) = term
        )
        {optional_match}
        {return_clause}
        """
        try:
            result = _as_list(
                _run_with_optional_timeout(
                    client,
                    cypher,
                    {
                        "lookup_terms": lookup_terms or [kg_id.lower()],
                        "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
                    },
                    timeout_s=timeout_s,
                )
            )
        except Exception:  # pragma: no cover - defensive fallback
            result = []
    if not result and not _looks_like_element_id(kg_id):
        optional_match = "OPTIONAL MATCH (n)-[r]->(nbr)" if include_neighbors else ""
        cypher = f"""
        MATCH (n)
        WHERE elementId(n) = $id
        {optional_match}
        {return_clause}
        """
        try:
            result = _as_list(
                _run_with_optional_timeout(
                    client, cypher, {"id": kg_id}, timeout_s=timeout_s
                )
            )
        except Exception:  # pragma: no cover - defensive fallback
            result = []
    if not result:
        return None
    record = result[0]
    node = _rec_get(record, "n")
    if node is None:
        return None
    labels = _rec_get(record, "labels", []) or []
    if not labels and hasattr(node, "labels"):
        labels = list(node.labels)
    props = (
        dict(node)
        if hasattr(node, "keys")
        else (dict(node) if isinstance(node, dict) else None)
    )
    if props is not None and "neighbors" not in props:
        props["neighbors"] = (
            _rec_get(record, "neighbors", []) if include_neighbors else []
        )
    stable_id = _stable_node_id(node) or None
    element_id = _element_id(node) or None
    return KGNodeSummary(
        kg_id=stable_id or element_id or _node_id(node),
        element_id=element_id,
        label=_coalesce_node_label(
            (props or {}).get("label"),
            (props or {}).get("name"),
            (props or {}).get("title"),
            stable_id or element_id or _node_id(node),
        ),
        node_type=labels[0] if labels else (props or {}).get("type", "Node"),
        score=1.0,
        properties=props,
    )


def related_datasets(
    kg_id: str,
    *,
    limit: int = 10,
    db: Optional[Neo4jGraphDB] = None,
    timeout_s: float | None = None,
) -> list[DatasetSummary]:
    """Return datasets connected to the given KG node."""

    client = db or get_default_db()
    cypher = """
    MATCH (target {id:$id})
    OPTIONAL MATCH (d:Dataset)-[r]-(target)
    OPTIONAL MATCH (d)-[:HAS_TASK]->(t:Task)
    OPTIONAL MATCH (d)-[:HAS_MODALITY]->(m:Modality)
    RETURN d, collect(DISTINCT t.name) AS tasks, collect(DISTINCT m.name) AS modalities,
           coalesce(d.n_subjects, d.num_subjects) AS n_subjects,
           coalesce(d.species, d.population) AS species
    LIMIT $limit
    """
    records = _as_list(
        _run_with_optional_timeout(
            client,
            cypher,
            {"id": kg_id, "limit": int(limit)},
            timeout_s=timeout_s,
        )
    )
    results: list[DatasetSummary] = []
    for record in records:
        d = _rec_get(record, "d")
        if not d:
            continue
        dataset_id = (
            d.get("dataset_id") if hasattr(d, "get") else getattr(d, "dataset_id", None)
        )
        tasks = _rec_get(record, "tasks", []) or []
        modalities = _rec_get(record, "modalities", []) or []
        n_subjects = _rec_get(record, "n_subjects", None)
        species_val = _rec_get(record, "species", None)
        title = None
        if hasattr(d, "get"):
            title = d.get("title") or d.get("name")
        if not title:
            title = getattr(d, "title", None) or getattr(d, "name", None)
        results.append(
            DatasetSummary(
                dataset_id=dataset_id or _node_id(d),
                title=title,
                tasks=[t for t in tasks if t],
                modalities=[m for m in modalities if m],
                n_subjects=n_subjects,
                kg_id=_node_id(d),
                species=species_val,
            )
        )
    return results


def _resolve_behavior_retrieval_seed(
    *,
    seed_id: str | None = None,
    label: str | None = None,
    name: str | None = None,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any] | None:
    client = db or get_default_db()
    if seed_id:
        rows = _as_list(
            client.execute_query(
                """
                MATCH (n {id:$id})
                RETURN {
                  id: coalesce(n.id, elementId(n)),
                  labels: labels(n),
                  properties: n{.*}
                } AS seed
                LIMIT 1
                """,
                {"id": seed_id},
            )
        )
        return rows[0]["seed"] if rows else None

    if label and name:
        allowed_labels = {
            "Task",
            "Experiment",
            "Psych101Experiment",
            "Dataset",
        }
        if label not in allowed_labels:
            raise ValueError(f"Unsupported label: {label}")

        rows = _as_list(
            client.execute_query(
                f"""
                MATCH (n:`{label}`)
                WHERE toLower(coalesce(n.name, n.title, n.display_name, '')) = toLower($name)
                RETURN {{
                  id: coalesce(n.id, elementId(n)),
                  labels: labels(n),
                  properties: n{{.*}}
                }} AS seed
                LIMIT 1
                """,
                {"name": name},
            )
        )
        return rows[0]["seed"] if rows else None

    return None


def _coerce_float_vector(value: Any) -> list[float]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[float] = []
    for item in value:
        try:
            result.append(float(item))
        except Exception:
            return []
    return result


def _cosine_similarity(lhs: Sequence[float], rhs: Sequence[float]) -> float | None:
    if not lhs or not rhs or len(lhs) != len(rhs):
        return None
    lhs_norm = math.sqrt(sum(value * value for value in lhs))
    rhs_norm = math.sqrt(sum(value * value for value in rhs))
    if lhs_norm == 0.0 or rhs_norm == 0.0:
        return None
    dot = sum(float(a) * float(b) for a, b in zip(lhs, rhs))
    return dot / (lhs_norm * rhs_norm)


def _behavior_task_name(task: Mapping[str, Any]) -> str:
    props = dict(task.get("properties") or {})
    return str(
        props.get("name")
        or props.get("canonical_name")
        or props.get("task_paradigm_name")
        or task.get("id")
        or ""
    )


def _normalize_behavior_task_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _is_generic_behavior_task(task: Mapping[str, Any]) -> bool:
    name = _normalize_behavior_task_name(_behavior_task_name(task))
    if not name:
        return False
    if _GENERIC_BEHAVIOR_TASK_RE.fullmatch(name):
        return True
    return name in _GENERIC_BEHAVIOR_TASK_LABELS


def _behavior_seed_task_quality(task: Mapping[str, Any]) -> tuple[int, str]:
    props = dict(task.get("properties") or {})
    score = 0
    if props.get("canonical_task_id"):
        score += 50
    if props.get("ontology_match_method") == "psych101_curated_registry":
        score += 40
    if props.get("subfamily_id"):
        score += 20
    if props.get("family_id"):
        score += 10
    if props.get("canonical_name"):
        score += 5
    if props.get("task_paradigm_name"):
        score += 5
    if _is_generic_behavior_task(task):
        score -= 100
    return score, _normalize_behavior_task_name(_behavior_task_name(task))


def _dedupe_and_rank_behavior_seed_tasks(
    tasks: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for task in tasks:
        task_id = str(task.get("id") or "")
        if not task_id:
            continue
        candidate = dict(task)
        existing = by_id.get(task_id)
        if existing is None:
            by_id[task_id] = candidate
            continue
        if _behavior_seed_task_quality(candidate) > _behavior_seed_task_quality(existing):
            by_id[task_id] = candidate

    ranked = list(by_id.values())
    non_generic = [task for task in ranked if not _is_generic_behavior_task(task)]
    if non_generic:
        ranked = non_generic

    ranked.sort(
        key=lambda task: (
            -_behavior_seed_task_quality(task)[0],
            _behavior_seed_task_quality(task)[1],
            str(task.get("id") or ""),
        )
    )
    return ranked[:4]


def _resolve_seed_tasks_for_behavior(
    seed: Mapping[str, Any],
    *,
    db: Optional[Neo4jGraphDB] = None,
) -> list[dict[str, Any]]:
    labels = {str(label) for label in (seed.get("labels") or [])}
    if "Task" in labels:
        return [dict(seed)]

    if not {"Psych101Experiment", "Experiment"} & labels:
        return []

    client = db or get_default_db()
    rows = _as_list(
        client.execute_query(
            """
            MATCH (seed {id:$seed_id})-[:USES_TASK]->(t:Task)
            OPTIONAL MATCH (t)-[:BELONGS_TO_FAMILY]->(tf:TaskFamily)
            RETURN {
              id: coalesce(t.id, elementId(t)),
              labels: labels(t),
              properties: t{.*,
                family_id: coalesce(tf.id, t.family_id),
                family_name: coalesce(tf.name, t.family_label)
              }
            } AS task
            ORDER BY coalesce(t.name, t.canonical_name, t.id)
            """,
            {"seed_id": seed.get("id")},
        )
    )
    tasks = [dict(row["task"]) for row in rows if row.get("task")]
    return _dedupe_and_rank_behavior_seed_tasks(tasks)


def _behavior_neighbor_tasks(
    source_task: Mapping[str, Any],
    *,
    max_neighbors: int,
    min_similarity: float,
    db: Optional[Neo4jGraphDB] = None,
) -> list[dict[str, Any]]:
    source_props = dict(source_task.get("properties") or {})
    source_vec = _coerce_float_vector(source_props.get("embedding_centaur_behavior_v1"))
    if not source_vec or max_neighbors <= 0:
        return []

    client = db or get_default_db()
    source_family_id = _normalize_behavior_task_name(source_props.get("family_id"))
    rows = _as_list(
        client.execute_query(
            """
            MATCH (t:Task)
            OPTIONAL MATCH (t)-[:BELONGS_TO_FAMILY]->(tf:TaskFamily)
            WHERE coalesce(t.id, '') <> $task_id
              AND t.embedding_centaur_behavior_v1 IS NOT NULL
              AND coalesce(t.id, '') STARTS WITH 'psych101:task:'
            RETURN {
              id: coalesce(t.id, elementId(t)),
              labels: labels(t),
              properties: t{.*,
                family_id: coalesce(tf.id, t.family_id),
                family_name: coalesce(tf.name, t.family_label)
              }
            } AS task
            """,
            {"task_id": source_task.get("id")},
        )
    )

    neighbors: list[dict[str, Any]] = []
    for row in rows:
        task = row.get("task")
        if not isinstance(task, dict):
            continue
        if _is_generic_behavior_task(task):
            continue
        similarity = _cosine_similarity(
            source_vec,
            _coerce_float_vector(
                (task.get("properties") or {}).get("embedding_centaur_behavior_v1")
            ),
        )
        if similarity is None or similarity < float(min_similarity):
            continue
        task_copy = dict(task)
        task_props = dict(task_copy.get("properties") or {})
        task_props["behavior_similarity"] = round(float(similarity), 6)
        task_props["behavior_family_match"] = bool(
            source_family_id
            and _normalize_behavior_task_name(task_props.get("family_id"))
            == source_family_id
        )
        task_copy["properties"] = task_props
        neighbors.append(task_copy)

    neighbors.sort(
        key=lambda item: (
            bool((item.get("properties") or {}).get("behavior_family_match")),
            float((item.get("properties") or {}).get("behavior_similarity") or 0.0),
        ),
        reverse=True,
    )
    return neighbors[: int(max_neighbors)]


def _classify_behavior_retrieval_method(
    *,
    path_nodes: Sequence[Mapping[str, Any]],
    path_relationships: Sequence[Mapping[str, Any]],
    behavior_similarity: float | None,
) -> str:
    rel_types = {
        str(rel.get("type") or "")
        for rel in path_relationships
        if isinstance(rel, Mapping)
    }
    task_count = sum(
        1
        for node in path_nodes
        if "Task" in {str(label) for label in (node.get("labels") or [])}
    )

    if "BELONGS_TO_FAMILY" in rel_types:
        base = "family_bridge"
    elif task_count >= 2:
        base = "canonical_bridge"
    else:
        base = "direct_task"

    if behavior_similarity is not None:
        return f"behavior_similar_{base}"
    return base


def _build_behavior_retrieval_item(
    *,
    path: Mapping[str, Any],
    node_lookup: Mapping[str, Mapping[str, Any]],
    outgoing_edges: Mapping[str, list[dict[str, Any]]],
    incoming_edges: Mapping[str, list[dict[str, Any]]],
    source_task: Mapping[str, Any],
    behavior_similarity: float | None,
) -> dict[str, Any] | None:
    map_id = path.get("map_id")
    if not isinstance(map_id, str) or not map_id:
        return None

    path_nodes = [
        node for node in (path.get("nodes") or []) if isinstance(node, Mapping)
    ]
    path_relationships = [
        rel
        for rel in (path.get("relationships") or [])
        if isinstance(rel, Mapping)
    ]
    method = _classify_behavior_retrieval_method(
        path_nodes=path_nodes,
        path_relationships=path_relationships,
        behavior_similarity=behavior_similarity,
    )

    task_analysis_ids = sorted(
        {
            str(edge.get("end"))
            for edge in outgoing_edges.get(map_id, [])
            if edge.get("type") == "GENERATED_FROM" and edge.get("end")
        }
    )
    contrast_ids = sorted(
        {
            str(edge.get("end"))
            for edge in outgoing_edges.get(map_id, [])
            if edge.get("type") == "DERIVED_FROM" and edge.get("end")
        }
    )
    matched_task_ids = sorted(
        {
            str(edge.get("end"))
            for ta_id in task_analysis_ids
            for edge in outgoing_edges.get(ta_id, [])
            if edge.get("type") == "MAPS_TO" and edge.get("end")
        }
    )
    dataset_ids = sorted(
        {
            str(edge.get("start"))
            for contrast_id in contrast_ids
            for edge in incoming_edges.get(contrast_id, [])
            if edge.get("type") == "HAS_CONTRAST" and edge.get("start")
        }
    )
    brain_regions = []
    for edge in outgoing_edges.get(map_id, []):
        if edge.get("type") != "IN_REGION" or not edge.get("end"):
            continue
        region_id = str(edge["end"])
        region_node = node_lookup.get(region_id) or {}
        region_props = dict(region_node.get("properties") or {})
        brain_regions.append(
            {
                "brain_region_id": region_id,
                "name": region_props.get("name") or region_props.get("label"),
                "weight": edge.get("properties", {}).get("weight"),
            }
        )
    brain_regions.sort(
        key=lambda item: abs(float(item.get("weight") or 0.0)),
        reverse=True,
    )

    matched_task_id = matched_task_ids[0] if matched_task_ids else None
    matched_task_node = node_lookup.get(matched_task_id or "") or {}
    matched_task_props = dict(matched_task_node.get("properties") or {})
    family_id = None
    family_name = None
    if matched_task_id:
        family_edges = [
            edge
            for edge in outgoing_edges.get(matched_task_id, [])
            if edge.get("type") == "BELONGS_TO_FAMILY" and edge.get("end")
        ]
        if family_edges:
            family_id = str(family_edges[0]["end"])
            family_node = node_lookup.get(family_id) or {}
            family_name = (family_node.get("properties") or {}).get("name")
    if not family_id:
        family_id = matched_task_props.get("family_id") or (
            source_task.get("properties") or {}
        ).get("family_id")
        family_name = matched_task_props.get("family_name") or (
            source_task.get("properties") or {}
        ).get("family_name")

    source_family_id = _normalize_behavior_task_name(
        (source_task.get("properties") or {}).get("family_id")
    )
    matched_family_id = _normalize_behavior_task_name(family_id)
    if behavior_similarity is not None and source_family_id and matched_family_id:
        if source_family_id != matched_family_id:
            return None

    base_scores = {
        "direct_task": 1.0,
        "canonical_bridge": 0.94,
        "family_bridge": 0.88,
        "behavior_similar_direct_task": 0.58,
        "behavior_similar_canonical_bridge": 0.48,
        "behavior_similar_family_bridge": 0.4,
    }
    base_score = float(base_scores.get(method, 0.5))
    if behavior_similarity is not None:
        base_score *= max(0.0, min(1.0, float(behavior_similarity)))

    return {
        "item_id": task_analysis_ids[0] if task_analysis_ids else map_id,
        "task_analysis_id": task_analysis_ids[0] if task_analysis_ids else None,
        "matched_task_id": matched_task_id,
        "matched_task_name": matched_task_props.get("name")
        or matched_task_props.get("canonical_name"),
        "family_id": family_id,
        "family_name": family_name,
        "contrast_ids": contrast_ids,
        "dataset_ids": dataset_ids,
        "stats_map_ids": [map_id],
        "brain_regions": brain_regions,
        "retrieval_methods": [method],
        "source_task_ids": [str(source_task.get("id"))],
        "source_task_names": [
            str(
                (source_task.get("properties") or {}).get("name")
                or (source_task.get("properties") or {}).get("canonical_name")
                or source_task.get("id")
            )
        ],
        "behavior_similarity_max": behavior_similarity,
        "score": round(base_score, 6),
    }


def _merge_behavior_retrieval_item(
    existing: dict[str, Any],
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    for key in ("contrast_ids", "dataset_ids", "stats_map_ids", "source_task_ids"):
        existing[key] = sorted(
            {
                str(value)
                for value in (existing.get(key) or [])
                + [str(value) for value in (incoming.get(key) or [])]
                if value
            }
        )

    existing["source_task_names"] = sorted(
        {
            str(value)
            for value in (existing.get("source_task_names") or [])
            + [str(value) for value in (incoming.get("source_task_names") or [])]
            if value
        }
    )
    existing["retrieval_methods"] = sorted(
        {
            str(value)
            for value in (existing.get("retrieval_methods") or [])
            + [str(value) for value in (incoming.get("retrieval_methods") or [])]
            if value
        }
    )
    existing["score"] = max(
        float(existing.get("score") or 0.0),
        float(incoming.get("score") or 0.0),
    )

    incoming_similarity = incoming.get("behavior_similarity_max")
    existing_similarity = existing.get("behavior_similarity_max")
    if incoming_similarity is not None:
        if existing_similarity is None:
            existing["behavior_similarity_max"] = incoming_similarity
        else:
            existing["behavior_similarity_max"] = max(
                float(existing_similarity),
                float(incoming_similarity),
            )

    seen_regions = {
        str(region.get("brain_region_id"))
        for region in existing.get("brain_regions") or []
        if isinstance(region, Mapping)
    }
    for region in incoming.get("brain_regions") or []:
        if not isinstance(region, Mapping):
            continue
        region_id = str(region.get("brain_region_id") or "")
        if not region_id or region_id in seen_regions:
            continue
        seen_regions.add(region_id)
        existing.setdefault("brain_regions", []).append(dict(region))
    existing["brain_regions"] = sorted(
        existing.get("brain_regions") or [],
        key=lambda item: abs(float(item.get("weight") or 0.0)),
        reverse=True,
    )

    for key in ("task_analysis_id", "matched_task_id", "matched_task_name", "family_id", "family_name"):
        if not existing.get(key) and incoming.get(key):
            existing[key] = incoming.get(key)
    return existing


def _summarize_behavior_pack_into_items(
    pack: Mapping[str, Any],
    *,
    source_task: Mapping[str, Any],
    behavior_similarity: float | None,
) -> list[dict[str, Any]]:
    graph = pack.get("graph") or {}
    node_lookup: dict[str, dict[str, Any]] = {}
    outgoing_edges: dict[str, list[dict[str, Any]]] = {}
    incoming_edges: dict[str, list[dict[str, Any]]] = {}

    for node in graph.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id:
            node_lookup[node_id] = dict(node)

    for edge in graph.get("edges") or []:
        if not isinstance(edge, Mapping):
            continue
        start = edge.get("start")
        end = edge.get("end")
        if not isinstance(start, str) or not isinstance(end, str) or not start or not end:
            continue
        edge_copy = {
            "type": edge.get("type"),
            "start": start,
            "end": end,
            "properties": dict(edge.get("properties") or {}),
        }
        outgoing_edges.setdefault(start, []).append(edge_copy)
        incoming_edges.setdefault(end, []).append(edge_copy)

    items: list[dict[str, Any]] = []
    for path in pack.get("paths") or []:
        if not isinstance(path, Mapping):
            continue
        item = _build_behavior_retrieval_item(
            path=path,
            node_lookup=node_lookup,
            outgoing_edges=outgoing_edges,
            incoming_edges=incoming_edges,
            source_task=source_task,
            behavior_similarity=behavior_similarity,
        )
        if item is not None:
            items.append(item)
    return items


def behavior_to_fmri_retrieval(
    *,
    seed_id: str | None = None,
    label: str | None = None,
    name: str | None = None,
    limit: int = 12,
    max_maps: int = 20,
    max_paths: int = 20,
    max_regions_per_map: int = 8,
    max_behavior_neighbors: int = 4,
    min_behavior_similarity: float = 0.0,
    db: Optional[Neo4jGraphDB] = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    del timeout_s  # outer timeout wrapper handles wall-clock enforcement
    client = db or get_default_db()
    seed = _resolve_behavior_retrieval_seed(
        seed_id=seed_id,
        label=label,
        name=name,
        db=client,
    )
    if seed is None:
        return {"error": "seed_not_found"}

    seed_tasks = _resolve_seed_tasks_for_behavior(seed, db=client)
    if not seed_tasks:
        return {
            "error": "unsupported_seed_type",
            "seed": seed,
            "supported_seed_labels": ["Task", "Experiment", "Psych101Experiment"],
        }

    items_by_id: dict[str, dict[str, Any]] = {}
    behavior_neighbor_count = 0

    for source_task in seed_tasks:
        direct_pack = build_evidence_pack(
            client,
            seed_id=str(source_task.get("id")),
            cfg=EvidencePackConfig(
                max_maps=int(max_maps),
                max_paths=int(max_paths),
                max_regions_per_map=int(max_regions_per_map),
                max_similar_tasks=0,
            ),
        )
        for item in _summarize_behavior_pack_into_items(
            direct_pack,
            source_task=source_task,
            behavior_similarity=None,
        ):
            item_id = str(item.get("item_id"))
            existing = items_by_id.get(item_id)
            if existing is None:
                items_by_id[item_id] = item
            else:
                items_by_id[item_id] = _merge_behavior_retrieval_item(existing, item)

        neighbors = _behavior_neighbor_tasks(
            source_task,
            max_neighbors=int(max_behavior_neighbors),
            min_similarity=float(min_behavior_similarity),
            db=client,
        )
        behavior_neighbor_count += len(neighbors)
        for neighbor_task in neighbors:
            neighbor_pack = build_evidence_pack(
                client,
                seed_id=str(neighbor_task.get("id")),
                cfg=EvidencePackConfig(
                    max_maps=int(max_maps),
                    max_paths=int(max_paths),
                    max_regions_per_map=int(max_regions_per_map),
                    max_similar_tasks=0,
                ),
            )
            similarity = (neighbor_task.get("properties") or {}).get(
                "behavior_similarity"
            )
            for item in _summarize_behavior_pack_into_items(
                neighbor_pack,
                source_task=source_task,
                behavior_similarity=float(similarity)
                if similarity is not None
                else None,
            ):
                item_id = str(item.get("item_id"))
                existing = items_by_id.get(item_id)
                if existing is None:
                    items_by_id[item_id] = item
                else:
                    items_by_id[item_id] = _merge_behavior_retrieval_item(
                        existing, item
                    )

    items = sorted(
        items_by_id.values(),
        key=lambda item: (
            -float(item.get("score") or 0.0),
            str(item.get("matched_task_name") or ""),
            str(item.get("task_analysis_id") or item.get("item_id") or ""),
        ),
    )[: max(1, int(limit))]

    retrieval_method_counts: dict[str, int] = {}
    for item in items:
        for method in item.get("retrieval_methods") or []:
            retrieval_method_counts[str(method)] = (
                retrieval_method_counts.get(str(method), 0) + 1
            )

    return {
        "seed": seed,
        "seed_tasks": [
            {
                "task_id": str(task.get("id")),
                "name": (task.get("properties") or {}).get("name")
                or (task.get("properties") or {}).get("canonical_name"),
                "family_id": (task.get("properties") or {}).get("family_id"),
                "family_name": (task.get("properties") or {}).get("family_name"),
                "has_behavior_embedding": bool(
                    _coerce_float_vector(
                        (task.get("properties") or {}).get(
                            "embedding_centaur_behavior_v1"
                        )
                    )
                ),
                "has_text_embedding": bool(
                    _coerce_float_vector(
                        (task.get("properties") or {}).get("embedding_text_v1")
                    )
                ),
            }
            for task in seed_tasks
        ],
        "items": items,
        "summary": {
            "seed_task_count": len(seed_tasks),
            "item_count": len(items),
            "behavior_neighbor_count": behavior_neighbor_count,
            "retrieval_method_counts": retrieval_method_counts,
        },
    }


def neighbors(
    kg_id: str,
    *,
    relation_types: Optional[Sequence[str]] = None,
    direction: str = "both",
    limit: int = 25,
    db: Optional[Neo4jGraphDB] = None,
    timeout_s: float | None = None,
) -> list[dict[str, Any]]:
    """Return neighbor nodes around a KG id with relation metadata."""
    client = db or get_default_db()
    dir_l = (direction or "both").lower()

    if dir_l == "out":
        cypher = """
        MATCH (n {id:$id})-[r]->(nbr)
        WHERE ($rel_types IS NULL OR type(r) IN $rel_types)
        RETURN nbr, labels(nbr) AS labels, type(r) AS rel, 'out' AS direction,
               coalesce(nbr.score, 1.0) AS score
        ORDER BY score DESC, coalesce(nbr.label, nbr.name)
        LIMIT $limit
        """
    elif dir_l == "in":
        cypher = """
        MATCH (nbr)-[r]->(n {id:$id})
        WHERE ($rel_types IS NULL OR type(r) IN $rel_types)
        RETURN nbr, labels(nbr) AS labels, type(r) AS rel, 'in' AS direction,
               coalesce(nbr.score, 1.0) AS score
        ORDER BY score DESC, coalesce(nbr.label, nbr.name)
        LIMIT $limit
        """
    else:
        cypher = """
        MATCH (n {id:$id})-[r]-(nbr)
        WHERE ($rel_types IS NULL OR type(r) IN $rel_types)
        RETURN nbr, labels(nbr) AS labels, type(r) AS rel,
               CASE WHEN startNode(r) = n THEN 'out' ELSE 'in' END AS direction,
               coalesce(nbr.score, 1.0) AS score
        ORDER BY score DESC, coalesce(nbr.label, nbr.name)
        LIMIT $limit
        """

    params = {
        "id": kg_id,
        "rel_types": list(relation_types) if relation_types else None,
        "limit": int(limit),
    }
    records = _as_list(
        _run_with_optional_timeout(client, cypher, params, timeout_s=timeout_s)
    )
    items: list[dict[str, Any]] = []
    for record in records:
        node = _rec_get(record, "nbr")
        if node is None:
            continue
        labels = _rec_get(record, "labels", []) or []
        if not labels and hasattr(node, "labels"):
            labels = list(node.labels)
        node_type = labels[0] if labels else (getattr(node, "type", None) or "Node")
        score = _rec_get(record, "score", 1.0) or 1.0
        label_val = None
        if hasattr(node, "get"):
            label_val = node.get("label") or node.get("name") or node.get("title")
        if not label_val:
            label_val = (
                getattr(node, "label", None)
                or getattr(node, "name", None)
                or getattr(node, "title", None)
                or ""
            )
        props = (
            dict(node)
            if hasattr(node, "keys")
            else (dict(node) if isinstance(node, dict) else None)
        )
        items.append(
            {
                "kg_id": _node_id(node),
                "label": label_val,
                "node_type": node_type,
                "score": score,
                "relation": _rec_get(record, "rel"),
                "direction": _rec_get(record, "direction"),
                "properties": props,
            }
        )
    return items


_HYPOTHESIS_STRICTNESS_THRESHOLDS = {
    "conservative": 0.55,
    "balanced": 0.35,
    "high_recall": 0.18,
}
_HYPOTHESIS_PREFERRED_ENTITY_TYPES = {
    "BrainRegion",
    "Concept",
    "CognitiveConcept",
    "Dataset",
    "DiseaseTrait",
    "Gene",
    "Method",
    "Modality",
    "OntologyConcept",
    "RiskLocus",
    "Task",
    "TaskFamily",
    "Tool",
}
_HYPOTHESIS_DISCOURAGED_ENTITY_TYPES = {
    "Collection",
    "Coordinate",
    "Paper",
    "Publication",
    "Study",
    "Term",
}
_EVIDENCE_QUALITY_LABEL_SCORES = {
    "low": 0.35,
    "medium": 0.60,
    "high": 0.85,
}
_HYPOTHESIS_SPLIT_RE = re.compile(
    r"\b(?:is|are|was|were|involved in|associated with|related to|linked to|"
    r"connects?|between|and|vs|versus|for|in)\b",
    re.IGNORECASE,
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalize_hypothesis_strictness(value: str | None) -> str:
    normalized = (value or "high_recall").strip().lower()
    if normalized in _HYPOTHESIS_STRICTNESS_THRESHOLDS:
        return normalized
    aliases = {
        "high-recall": "high_recall",
        "recall": "high_recall",
        "strict": "conservative",
        "default": "high_recall",
    }
    return aliases.get(normalized, "high_recall")


def _normalize_claim_polarity(value: Any) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "supports": "supports",
        "support": "supports",
        "positive": "supports",
        "refutes": "refutes",
        "refute": "refutes",
        "contradicts": "refutes",
        "negative": "refutes",
        "mixed": "mixed",
        "uncertain": "uncertain",
        "neutral": "uncertain",
    }
    return mapping.get(text, "uncertain")


def _normalize_confidence_scoring_version(value: str | None) -> str:
    version = str(value or "v2").strip().lower()
    if version in {"v1", "legacy"}:
        return "v1"
    return "v2"


def _infer_source_reliability_from_evidence_item(item: dict[str, Any]) -> float:
    publication = item.get("publication") or {}
    publication_props = publication.get("properties") or {}
    source_tokens = " ".join(
        [
            str(publication_props.get("source_class") or ""),
            str(publication_props.get("prov_source") or ""),
            str(publication_props.get("source") or ""),
            str(publication_props.get("journal") or ""),
            str(publication_props.get("pmid") or ""),
            str(publication_props.get("doi") or ""),
        ]
    ).lower()
    if any(
        token in source_tokens
        for token in {"official_spec", "major_ontology", "guideline", "consensus"}
    ):
        return 0.95
    if any(
        token in source_tokens
        for token in {"peer_reviewed", "pubmed", "pmid", "doi", "journal"}
    ):
        return 0.90
    if any(
        token in source_tokens
        for token in {
            "aggregator",
            "openalex",
            "semanticscholar",
            "neurosynth",
            "openneuro",
        }
    ):
        return 0.80
    if any(token in source_tokens for token in {"scraped", "web", "forum", "blog"}):
        return 0.65
    return 0.75


def _legacy_hypothesis_confidence(
    *,
    support_score: float,
    conflict_score: float,
    max_evidence: int,
    has_mixed_evidence: bool,
) -> tuple[float, dict[str, float | str]]:
    signal_score = support_score + conflict_score
    if signal_score <= 0:
        confidence = 0.0
        coverage = 0.0
        dominance = 0.0
    else:
        dominance = abs(support_score - conflict_score) / max(signal_score, 1e-6)
        coverage = min(1.0, signal_score / max(1.0, float(max_evidence) * 0.35))
        confidence = 0.55 * coverage + 0.45 * dominance
        if has_mixed_evidence:
            confidence *= 0.8
        confidence = round(_clip01(confidence), 2)

    return confidence, {
        "scoring_version": "v1",
        "coverage": round(coverage, 4),
        "dominance": round(dominance, 4),
        "support_strength": round(support_score, 4),
        "conflict_strength": round(conflict_score, 4),
    }


def _node_type_from_node(node: Any, fallback: str = "Node") -> str:
    labels: list[str] = []
    if isinstance(node, dict):
        labels = [str(label) for label in node.get("labels", []) if label]
    elif hasattr(node, "labels"):
        try:
            labels = [str(label) for label in list(node.labels) if label]
        except Exception:
            labels = []
    if labels:
        return labels[0]
    if isinstance(node, dict):
        return str(node.get("type") or fallback)
    return str(getattr(node, "type", fallback) or fallback)


def _normalize_graph_node(node: Any, *, default_type: str = "Node") -> dict[str, Any]:
    if node is None:
        return {}
    props = (
        dict(node)
        if hasattr(node, "keys")
        else (dict(node) if isinstance(node, dict) else {})
    )
    node_props = (
        dict(props.get("properties"))
        if isinstance(props, dict) and isinstance(props.get("properties"), dict)
        else (props if isinstance(props, dict) else {})
    )
    label = (
        (
            props.get("label")
            or props.get("name")
            or props.get("title")
            or node_props.get("label")
            or node_props.get("name")
            or node_props.get("title")
        )
        if isinstance(props, dict)
        else ""
    )
    if not label and hasattr(node, "get"):
        label = node.get("label") or node.get("name") or node.get("title") or ""
    kg_id = (
        (props.get("kg_id") if isinstance(props, dict) else None)
        or node_props.get("kg_id")
        or _identifier_value_from_props(node_props)
        or _identifier_value_from_props(props if isinstance(props, dict) else None)
        or _stable_node_id(node)
        or _element_id(node)
        or _node_id(node)
    )
    return {
        "kg_id": str(kg_id or ""),
        "label": str(label or ""),
        "node_type": _node_type_from_node(node, fallback=default_type),
        "properties": node_props if isinstance(node_props, dict) else {},
    }


def _coerce_entity_hints(entity_hints: Any) -> list[str]:
    if entity_hints is None:
        return []
    hints: list[str] = []
    if isinstance(entity_hints, str):
        hints = [entity_hints]
    elif isinstance(entity_hints, list):
        for item in entity_hints:
            if isinstance(item, str):
                hints.append(item)
            elif isinstance(item, dict):
                candidate = item.get("kg_id") or item.get("label") or item.get("id")
                if candidate:
                    hints.append(str(candidate))
            elif item is not None:
                hints.append(str(item))
    else:
        hints = [str(entity_hints)]
    cleaned: list[str] = []
    seen: set[str] = set()
    for hint in hints:
        value = str(hint).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    return cleaned


def _extract_hypothesis_terms(hypothesis: str, entity_hints: Any = None) -> list[str]:
    text = (hypothesis or "").strip()
    terms: list[str] = []
    seen: set[str] = set()

    def _add(term: str | None) -> None:
        if term is None:
            return
        cleaned = re.sub(r"\s+", " ", str(term)).strip(" \t\r\n'\".,;:()[]{}")
        if len(cleaned) < 2:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        terms.append(cleaned)

    for hint in _coerce_entity_hints(entity_hints):
        _add(hint)
    _add(text)
    for quoted in re.findall(r'"([^"]+)"|\'([^\']+)\'', text):
        _add(quoted[0] or quoted[1])

    for chunk in _HYPOTHESIS_SPLIT_RE.split(text):
        _add(chunk)

    words = [token for token in re.findall(r"[A-Za-z0-9:_./-]+", text) if token]
    for width in (2, 3):
        if len(words) < width:
            continue
        for start in range(0, len(words) - width + 1):
            _add(" ".join(words[start : start + width]))

    return terms[:16]


def _hypothesis_query_tokens(search_terms: Sequence[str]) -> set[str]:
    tokens: set[str] = set()
    for term in search_terms:
        for token in _tokenize_query(term):
            tokens.add(token)
    return tokens


def _hypothesis_entity_overlap_count(
    entity: KGNodeSummary,
    *,
    query_tokens: set[str],
) -> int:
    if not query_tokens:
        return 0
    label = _coalesce_node_label(
        entity.label,
        (entity.properties or {}).get("name") if entity.properties else None,
        (entity.properties or {}).get("title") if entity.properties else None,
        entity.kg_id,
    )
    label_tokens = set(_tokenize_ood_label(label))
    return len(label_tokens.intersection(query_tokens))


def _match_seed_entity_to_hint(
    seed_entities: Sequence[KGNodeSummary],
    *,
    hint: str,
    exclude_ids: set[str] | None = None,
) -> KGNodeSummary | None:
    hint_tokens = set(_tokenize_query(hint))
    hint_lookup_terms = set(_build_lookup_terms(hint))
    if not hint_tokens and not hint_lookup_terms:
        return None

    ranked: list[tuple[float, KGNodeSummary]] = []
    excluded = exclude_ids or set()
    for entity in seed_entities:
        kg_id = str(entity.kg_id or "").strip()
        if not kg_id or kg_id in excluded:
            continue
        entity_lookup_terms = set(_entity_lookup_terms(entity))
        overlap = _hypothesis_entity_overlap_count(entity, query_tokens=hint_tokens)
        exact_term_hit = bool(entity_lookup_terms.intersection(hint_lookup_terms))
        if overlap <= 0 and not exact_term_hit:
            continue
        score = (
            (3.0 if exact_term_hit else 0.0)
            + float(overlap)
            + (0.05 * _hypothesis_entity_type_priority(entity.node_type))
            + (0.01 * _safe_float(entity.score, 0.0))
        )
        ranked.append((score, entity))

    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], str(item[1].kg_id or "")))
    return ranked[0][1]


def _filter_candidate_lane_rows(
    rows: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    filtered = 0
    for row in rows:
        if _row_is_candidate_lane(row):
            filtered += 1
            continue
        kept.append(row)
    return kept, filtered


def _hypothesis_entity_type_priority(node_type: str | None) -> float:
    canonical = _canonical_ood_node_type(node_type)
    return {
        "BrainRegion": 5.0,
        "Task": 4.9,
        "TaskFamily": 4.7,
        "DiseaseTrait": 4.65,
        "Concept": 4.6,
        "Modality": 4.3,
        "Gene": 4.15,
        "Dataset": 3.8,
        "RiskLocus": 3.7,
        "Method": 3.5,
        "Tool": 3.0,
        "Atlas": 2.6,
        "Publication": 1.0,
        "Paper": 1.0,
        "Study": 1.0,
        "Collection": 0.8,
        "Term": 0.4,
        "Coordinate": 0.2,
    }.get(canonical, 1.5)


def _resolve_hypothesis_seed_entities(
    seed_entities: Sequence[KGNodeSummary],
    *,
    search_terms: Sequence[str],
    client: Neo4jGraphDB,
    exact_hint_ids: Sequence[str] | None = None,
) -> tuple[list[KGNodeSummary], list[str]]:
    warnings: list[str] = []
    if not seed_entities:
        return [], warnings

    query_tokens = _hypothesis_query_tokens(search_terms)
    preferred_exact_ids = {
        str(item or "").strip().lower()
        for item in (exact_hint_ids or [])
        if str(item or "").strip()
    }
    raw_by_id = {
        str(entity.kg_id or "").strip(): entity
        for entity in seed_entities
        if str(entity.kg_id or "").strip()
    }
    semantic_context = _resolve_semantic_seed_context(
        list(raw_by_id.keys()),
        db=client,
        relation_types=[
            "ABOUT",
            "IN_ONVOC",
            "MEASURES",
            "RELATED_TO",
            "SUPPORTS_MODALITY",
            "USES_TASK",
            "HAS_TASK",
        ],
        neighbor_limit=12,
    )
    warnings.extend(semantic_context.get("warnings") or [])

    candidate_map: dict[str, tuple[KGNodeSummary, list[str]]] = {}

    def _add_candidate(entity: KGNodeSummary, provenance: list[str]) -> None:
        kg_id = str(entity.kg_id or "").strip()
        if not kg_id:
            return
        canonical = _canonical_ood_node_type(entity.node_type)
        if canonical not in {
            _canonical_ood_node_type(value)
            for value in _HYPOTHESIS_PREFERRED_ENTITY_TYPES
        }:
            return
        label = _coalesce_node_label(
            entity.label,
            (entity.properties or {}).get("name") if entity.properties else None,
            (entity.properties or {}).get("title") if entity.properties else None,
            kg_id,
        )
        rejected, _ = _looks_like_noise_candidate(label, node_type=canonical)
        if rejected:
            return
        if kg_id not in candidate_map:
            candidate_map[kg_id] = (entity, list(provenance))
            return
        existing_entity, existing_prov = candidate_map[kg_id]
        if _safe_float(entity.score, 0.0) > _safe_float(existing_entity.score, 0.0):
            candidate_map[kg_id] = (entity, list(provenance))
            return
        merged = list(dict.fromkeys(existing_prov + list(provenance)))
        candidate_map[kg_id] = (existing_entity, merged)

    for entity in seed_entities:
        provenance = ["raw_search"]
        if _canonical_ood_node_type(entity.node_type) in {
            _canonical_ood_node_type(value)
            for value in _HYPOTHESIS_PREFERRED_ENTITY_TYPES
        }:
            provenance = ["direct"]
        _add_candidate(entity, provenance)

    semantic_labels = semantic_context.get("semantic_seed_labels") or {}
    semantic_types = semantic_context.get("semantic_seed_types") or {}
    semantic_provenance = semantic_context.get("seed_provenance") or {}
    for seed_id in semantic_context.get("seed_kg_ids") or []:
        seed_id_str = str(seed_id or "").strip()
        if not seed_id_str:
            continue
        detail = node_details(seed_id_str, db=client)
        if detail is None:
            detail = KGNodeSummary(
                kg_id=seed_id_str,
                label=str(semantic_labels.get(seed_id_str) or seed_id_str),
                node_type=str(semantic_types.get(seed_id_str) or "Node"),
                score=1.0,
            )
        provenance = list(semantic_provenance.get(seed_id_str) or ["expanded"])
        _add_candidate(detail, provenance)

    if not candidate_map:
        warnings.append(
            "No semantic seed entities could be resolved; using raw seed ranking."
        )
        ranked_raw = sorted(
            seed_entities,
            key=lambda item: (
                -_safe_float(item.score, 0.0),
                str(item.kg_id or ""),
            ),
        )
        return ranked_raw, warnings

    scored: list[tuple[float, int, KGNodeSummary]] = []
    for entity, provenance in candidate_map.values():
        overlap = _hypothesis_entity_overlap_count(entity, query_tokens=query_tokens)
        provenance_bonus = 0.0
        if any(str(item).startswith("direct") for item in provenance):
            provenance_bonus = 0.8
        elif any(str(item).startswith("expanded_from") for item in provenance):
            provenance_bonus = 0.4
        exact_hint_bonus = (
            3.0
            if str(entity.kg_id or "").strip().lower() in preferred_exact_ids
            else 0.0
        )
        score = (
            _hypothesis_entity_type_priority(entity.node_type)
            + 0.45 * overlap
            + provenance_bonus
            + exact_hint_bonus
            + 0.05 * _safe_float(entity.score, 0.0)
        )
        scored.append((score, overlap, entity))

    scored.sort(
        key=lambda item: (
            -(1 if item[1] > 0 else 0),
            -item[0],
            str(item[2].kg_id or ""),
        )
    )
    return [entity for _, _, entity in scored], warnings


def _node_summary_payload(node: KGNodeSummary) -> dict[str, Any]:
    payload = {
        "kg_id": node.kg_id,
        "label": node.label,
        "node_type": node.node_type,
    }
    if node.element_id:
        payload["element_id"] = node.element_id
    return payload


def _entity_lookup_terms(entity: KGNodeSummary) -> list[str]:
    terms: list[str] = []
    props = entity.properties or {}
    candidates: list[Any] = [
        entity.kg_id,
        entity.element_id,
        entity.label,
        props.get("id"),
        props.get("dataset_id"),
        props.get("uid"),
        props.get("identifier"),
        props.get("task_id"),
        props.get("concept_id"),
        props.get("region_id"),
        props.get("study_id"),
        props.get("source_repo_id"),
        props.get("source_version"),
        props.get("primary_url"),
        props.get("name"),
        props.get("title"),
    ]
    for alias_key in ("aliases", "synonyms", "keywords"):
        candidates.extend(props.get(alias_key) or [])
    for candidate in candidates:
        if candidate:
            terms.extend(_build_lookup_terms(str(candidate)))
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        key = term.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _dataset_publication_lookup_terms(entity: KGNodeSummary) -> list[str]:
    if not _is_dataset_like_entity(entity):
        return []
    terms: list[str] = []
    for candidate in _coalesce_dataset_property_values(entity):
        terms.extend(_build_lookup_terms(candidate))
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        key = str(term or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _publication_anchor_lookup_terms(entity: KGNodeSummary) -> list[str]:
    terms = list(_dataset_publication_lookup_terms(entity))
    if _canonical_ood_node_type(entity.node_type) in {"Publication", "Paper", "Study"}:
        terms.extend(_entity_lookup_terms(entity))
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        key = str(term or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _normalize_publication_anchor_record(
    record: Any,
    *,
    entity: KGNodeSummary,
) -> dict[str, Any] | None:
    publication = _normalize_graph_node(
        _rec_get(record, "p"), default_type="Publication"
    )
    if not publication.get("kg_id"):
        return None
    claim = _normalize_graph_node(_rec_get(record, "c"), default_type="Claim")
    if not claim.get("kg_id"):
        claim = {}
    evidence_span = _normalize_graph_node(
        _rec_get(record, "e"), default_type="EvidenceSpan"
    )
    if not evidence_span.get("kg_id"):
        evidence_span = {}
    return {
        "publication": publication,
        "matched_entity": _node_summary_payload(entity),
        "mention_type": str(_rec_get(record, "mention_type") or "DATASET_PUBLICATION"),
        "mention_props": _rec_get(record, "mention_props", {}) or {},
        "claim": claim,
        "claim_edge_props": _rec_get(record, "claim_edge_props", {}) or {},
        "evidence_span": evidence_span,
        "support_edge_props": _rec_get(record, "support_edge_props", {}) or {},
        "evidence_anchor_scope": "direct",
    }


def _collect_dataset_publication_anchor_evidence(
    entity: KGNodeSummary,
    *,
    limit: int,
    client: Neo4jGraphDB,
) -> list[dict[str, Any]]:
    lookup_terms = _dataset_publication_lookup_terms(entity)
    if not lookup_terms:
        return []

    cypher = f"""
    MATCH (p:Publication)
    WHERE any(term IN $lookup_terms WHERE
      {_publication_anchor_match_clause("p")} OR
      toLower(coalesce(toString(p.label), '')) = term OR
      toLower(coalesce(toString(p.name), '')) = term OR
      toLower(coalesce(toString(p.title), '')) = term OR
      any(alias IN coalesce(p.aliases, []) WHERE toLower(alias) = term)
    )
    OPTIONAL MATCH (p)-[rc:REPORTS_CLAIM]->(c:Claim)
    OPTIONAL MATCH (e:EvidenceSpan)-[sup:SUPPORTS]->(c)
    RETURN
      p AS p,
      'DATASET_PUBLICATION_ANCHOR' AS mention_type,
      {{
        dataset_publication_anchor: true,
        evidence_quality: 'medium'
      }} AS mention_props,
      c AS c,
      properties(rc) AS claim_edge_props,
      e AS e,
      properties(sup) AS support_edge_props
    LIMIT $limit
    """
    records = _as_list(
        client._run(
            cypher,
            {
                "lookup_terms": lookup_terms,
                "publication_identifier_keys": list(_PUBLICATION_IDENTIFIER_FIELDS),
                "limit": int(limit),
            },
        )
    )
    rows: list[dict[str, Any]] = []
    for record in records:
        row = _normalize_publication_anchor_record(record, entity=entity)
        if row is not None:
            rows.append(row)
    return rows


def _collect_publication_evidence_for_entity(
    entity: KGNodeSummary,
    *,
    limit: int,
    client: Neo4jGraphDB,
) -> list[dict[str, Any]]:
    lookup_terms = _entity_lookup_terms(entity)
    if not lookup_terms:
        return []

    cypher = f"""
    MATCH (p)
    WHERE any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper', 'Study'])
    MATCH (p)-[m]->(ent)
    WHERE type(m) IN ['MENTIONS', 'MENTIONS_REGION']
      AND any(term IN $lookup_terms WHERE
        {_identifier_exact_match_clause("ent")} OR
        toLower(coalesce(toString(ent.label), '')) = term OR
        toLower(coalesce(toString(ent.name), '')) = term OR
        toLower(elementId(ent)) = term
      )
    OPTIONAL MATCH (p)-[rc:REPORTS_CLAIM]->(c:Claim)
    OPTIONAL MATCH (e:EvidenceSpan)-[sup:SUPPORTS]->(c)
    RETURN
      p AS p,
      ent AS ent,
      CASE
        WHEN any(lbl IN labels(p) WHERE lbl = 'Study')
          THEN coalesce(toString(p.id), elementId(p))
        ELSE head([
          (p)-[:ALIGNS_WITH]->(aligned_study:Study) |
          coalesce(toString(aligned_study.id), elementId(aligned_study))
        ])
      END AS aligned_study_id,
      CASE
        WHEN any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper'])
          THEN coalesce(
            toString(p.id),
            toString(p.pmid),
            toString(p.doi),
            elementId(p)
          )
        ELSE head([
          (aligned_publication)-[:ALIGNS_WITH]->(p)
          WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
          coalesce(
            toString(aligned_publication.id),
            toString(aligned_publication.pmid),
            toString(aligned_publication.doi),
            elementId(aligned_publication)
          )
        ])
      END AS aligned_publication_id,
      type(m) AS mention_type,
      properties(m) AS mention_props,
      c AS c,
      properties(rc) AS claim_edge_props,
      e AS e,
      properties(sup) AS support_edge_props
    LIMIT $limit
    """
    records = _as_list(
        client._run(
            cypher,
            {
                "lookup_terms": lookup_terms,
                "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
                "limit": int(limit),
            },
        )
    )

    rows: list[dict[str, Any]] = []
    for record in records:
        publication = _normalize_graph_node(
            _rec_get(record, "p"), default_type="Publication"
        )
        if not publication.get("kg_id"):
            continue
        aligned_study_id = str(_rec_get(record, "aligned_study_id") or "").strip()
        if aligned_study_id:
            publication["aligned_study_id"] = aligned_study_id
        aligned_publication_id = str(
            _rec_get(record, "aligned_publication_id") or ""
        ).strip()
        if aligned_publication_id:
            publication["aligned_publication_id"] = aligned_publication_id
        matched = _normalize_graph_node(
            _rec_get(record, "ent"), default_type=entity.node_type
        )
        claim = _normalize_graph_node(_rec_get(record, "c"), default_type="Claim")
        if not claim.get("kg_id"):
            claim = {}
        evidence_span = _normalize_graph_node(
            _rec_get(record, "e"), default_type="EvidenceSpan"
        )
        if not evidence_span.get("kg_id"):
            evidence_span = {}
        rows.append(
            {
                "publication": publication,
                "matched_entity": matched or _node_summary_payload(entity),
                "mention_type": str(_rec_get(record, "mention_type") or "MENTIONS"),
                "mention_props": _rec_get(record, "mention_props", {}) or {},
                "claim": claim,
                "claim_edge_props": _rec_get(record, "claim_edge_props", {}) or {},
                "evidence_span": evidence_span,
                "support_edge_props": _rec_get(record, "support_edge_props", {}) or {},
                "evidence_anchor_scope": "direct",
            }
        )
    if _is_onvoc_like_entity(entity):
        mediated_records = _as_list(
            client._run(
                f"""
                MATCH (d:Dataset)
                WHERE EXISTS {{
                  MATCH (d)-[r]-(o)
                  WHERE type(r) IN ['IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                    AND any(lbl IN labels(o) WHERE lbl IN ['Concept', 'OnvocClass', 'OntologyConcept', 'LegacyOnvocTag'])
                    AND (
                      toUpper(coalesce(o.scheme, '')) IN ['ONVOC', 'ONVOC_LEGACY']
                      OR toUpper(coalesce(o.id, '')) STARTS WITH 'ONVOC_'
                      OR toUpper(coalesce(o.id, '')) STARTS WITH 'ONVOC:'
                      OR toLower(coalesce(o.id, '')) STARTS WITH 'legacy_onvoc:'
                    )
                    AND any(term IN $lookup_terms WHERE
                      {_identifier_exact_match_clause("o")} OR
                      toLower(coalesce(toString(o.label), '')) = term OR
                      toLower(coalesce(toString(o.name), '')) = term
                    )
                }}
                MATCH (d)-[:CITED_BY]->(p)
                WHERE any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper', 'Study'])
                OPTIONAL MATCH (p)-[rc:REPORTS_CLAIM]->(c:Claim)
                OPTIONAL MATCH (e:EvidenceSpan)-[sup:SUPPORTS]->(c)
                RETURN
                  p AS p,
                  d AS d,
                  CASE
                    WHEN any(lbl IN labels(p) WHERE lbl = 'Study')
                      THEN coalesce(toString(p.id), elementId(p))
                    ELSE head([
                      (p)-[:ALIGNS_WITH]->(aligned_study:Study) |
                      coalesce(toString(aligned_study.id), elementId(aligned_study))
                    ])
                  END AS aligned_study_id,
                  CASE
                    WHEN any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper'])
                      THEN coalesce(
                        toString(p.id),
                        toString(p.pmid),
                        toString(p.doi),
                        elementId(p)
                      )
                    ELSE head([
                      (aligned_publication)-[:ALIGNS_WITH]->(p)
                      WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
                      coalesce(
                        toString(aligned_publication.id),
                        toString(aligned_publication.pmid),
                        toString(aligned_publication.doi),
                        elementId(aligned_publication)
                      )
                    ])
                  END AS aligned_publication_id,
                  'DATASET_MEDIATED' AS mention_type,
                  {{dataset_mediated: true}} AS mention_props,
                  c AS c,
                  properties(rc) AS claim_edge_props,
                  e AS e,
                  properties(sup) AS support_edge_props
                LIMIT $limit
                """,
                {
                    "lookup_terms": lookup_terms,
                    "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
                    "limit": int(limit),
                },
            )
        )
        for record in mediated_records:
            publication = _normalize_graph_node(
                _rec_get(record, "p"), default_type="Publication"
            )
            if not publication.get("kg_id"):
                continue
            aligned_study_id = str(_rec_get(record, "aligned_study_id") or "").strip()
            if aligned_study_id:
                publication["aligned_study_id"] = aligned_study_id
            aligned_publication_id = str(
                _rec_get(record, "aligned_publication_id") or ""
            ).strip()
            if aligned_publication_id:
                publication["aligned_publication_id"] = aligned_publication_id
            matched = _normalize_graph_node(
                _rec_get(record, "d"), default_type="Dataset"
            )
            claim = _normalize_graph_node(_rec_get(record, "c"), default_type="Claim")
            if not claim.get("kg_id"):
                claim = {}
            evidence_span = _normalize_graph_node(
                _rec_get(record, "e"), default_type="EvidenceSpan"
            )
            if not evidence_span.get("kg_id"):
                evidence_span = {}
            rows.append(
                {
                    "publication": publication,
                    "matched_entity": matched or _node_summary_payload(entity),
                    "mention_type": str(
                        _rec_get(record, "mention_type") or "DATASET_MEDIATED"
                    ),
                    "mention_props": _rec_get(record, "mention_props", {}) or {},
                    "claim": claim,
                    "claim_edge_props": _rec_get(record, "claim_edge_props", {}) or {},
                    "evidence_span": evidence_span,
                    "support_edge_props": _rec_get(record, "support_edge_props", {}) or {},
                    "evidence_anchor_scope": "dataset_mediated",
                }
            )
    deduped_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        publication = row.get("publication") or {}
        matched = row.get("matched_entity") or {}
        key = (
            _publication_identity_key(publication),
            str(matched.get("kg_id") or matched.get("id") or ""),
            str(row.get("mention_type") or ""),
        )
        existing = deduped_rows.get(key)
        if existing is None or _publication_row_priority(row) < _publication_row_priority(
            existing
        ):
            deduped_rows[key] = row
    ordered_rows = list(deduped_rows.values())
    if ordered_rows or not _is_dataset_like_entity(entity):
        return ordered_rows
    return _collect_dataset_publication_anchor_evidence(
        entity,
        limit=limit,
        client=client,
    )


def _publication_entity_match_clause(
    publication_var: str,
    mention_var: str,
    entity_var: str,
    *,
    entity_terms_param: str,
    publication_terms_param: str,
) -> str:
    return f"""
    (
      EXISTS {{
        MATCH ({publication_var})-[{mention_var}]->({entity_var})
        WHERE type({mention_var}) IN ['MENTIONS', 'MENTIONS_REGION']
          AND any(term IN ${entity_terms_param} WHERE
            {_identifier_exact_match_clause(entity_var)} OR
            toLower(coalesce(toString({entity_var}.label), '')) = term OR
            toLower(coalesce(toString({entity_var}.name), '')) = term OR
            toLower(elementId({entity_var})) = term
          )
      }}
      OR any(term IN ${publication_terms_param} WHERE
        {_publication_anchor_match_clause(publication_var)} OR
        toLower(coalesce(toString({publication_var}.label), '')) = term OR
        toLower(coalesce(toString({publication_var}.name), '')) = term OR
        toLower(coalesce(toString({publication_var}.title), '')) = term OR
        any(alias IN coalesce({publication_var}.aliases, []) WHERE toLower(alias) = term)
      )
    )
    """


def _collect_coordinate_overlap_evidence(
    subject: KGNodeSummary,
    obj: KGNodeSummary,
    *,
    limit: int,
    client: Neo4jGraphDB,
) -> list[dict[str, Any]]:
    subject_terms = _entity_lookup_terms(subject)
    object_terms = _entity_lookup_terms(obj)
    subject_pub_terms = _publication_anchor_lookup_terms(subject)
    object_pub_terms = _publication_anchor_lookup_terms(obj)
    if not subject_terms or not object_terms:
        return []
    subject_match_clause = _publication_entity_match_clause(
        "p_a",
        "m_a",
        "ent_a",
        entity_terms_param="subject_terms",
        publication_terms_param="subject_publication_terms",
    )
    object_match_clause = _publication_entity_match_clause(
        "p_b",
        "m_b",
        "ent_b",
        entity_terms_param="object_terms",
        publication_terms_param="object_publication_terms",
    )

    cypher = f"""
    MATCH (p_a:Publication)-[:HAS_COORDINATE]->(coord)<-[:HAS_COORDINATE]-(p_b:Publication)
    WHERE p_a <> p_b
      AND {subject_match_clause}
      AND {object_match_clause}
    WITH p_a, p_b, collect(coord) AS coords, count(coord) AS shared_coordinate_count
    RETURN
      p_a AS p_a,
      p_b AS p_b,
      coords[0] AS coord,
      shared_coordinate_count AS shared_coordinate_count
    ORDER BY shared_coordinate_count DESC,
      coalesce(p_a.year, 0) DESC,
      coalesce(p_b.year, 0) DESC
    LIMIT $limit
    """
    records = _as_list(
        client._run(
            cypher,
            {
                "subject_terms": subject_terms,
                "object_terms": object_terms,
                "subject_publication_terms": subject_pub_terms,
                "object_publication_terms": object_pub_terms,
                "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
                "publication_identifier_keys": list(_PUBLICATION_IDENTIFIER_FIELDS),
                "limit": int(limit),
            },
        )
    )

    rows: list[dict[str, Any]] = []
    for record in records:
        pub_a = _normalize_graph_node(
            _rec_get(record, "p_a"), default_type="Publication"
        )
        pub_b = _normalize_graph_node(
            _rec_get(record, "p_b"), default_type="Publication"
        )
        coord = _normalize_graph_node(
            _rec_get(record, "coord"), default_type="Coordinate"
        )
        if not pub_a.get("kg_id") or not pub_b.get("kg_id"):
            continue
        shared_count = max(1, int(_rec_get(record, "shared_coordinate_count", 1) or 1))
        rows.append(
            {
                "publication": pub_a,
                "secondary_publication": pub_b,
                "matched_entity": _node_summary_payload(subject),
                "secondary_matched_entity": _node_summary_payload(obj),
                "mention_type": "COORDINATE_OVERLAP",
                "mention_props": {
                    "typed_path_kind": "coordinate_overlap",
                    "shared_coordinate_count": shared_count,
                    "claim_polarity": "supports",
                    "claim_strength": round(min(0.95, 0.45 + 0.08 * shared_count), 3),
                    "mention_strength": round(min(0.95, 0.45 + 0.08 * shared_count), 3),
                    "method_rigor": 0.63,
                    "evidence_quality": "high",
                    "provenance_completeness": 0.74,
                },
                "secondary_mention_props": {
                    "mention_strength": round(min(0.95, 0.42 + 0.08 * shared_count), 3),
                },
                "claim": {},
                "claim_edge_props": {},
                "evidence_span": {},
                "support_edge_props": {},
                "shared_coordinate": coord,
                "typed_path_kind": "coordinate_overlap",
                "evidence_anchor_scope": "typed_path",
            }
        )
    return rows


def _collect_citation_bridge_evidence(
    subject: KGNodeSummary,
    obj: KGNodeSummary,
    *,
    limit: int,
    client: Neo4jGraphDB,
) -> list[dict[str, Any]]:
    subject_terms = _entity_lookup_terms(subject)
    object_terms = _entity_lookup_terms(obj)
    subject_pub_terms = _publication_anchor_lookup_terms(subject)
    object_pub_terms = _publication_anchor_lookup_terms(obj)
    if not subject_terms or not object_terms:
        return []
    subject_match_clause = _publication_entity_match_clause(
        "p_a",
        "m_a",
        "ent_a",
        entity_terms_param="subject_terms",
        publication_terms_param="subject_publication_terms",
    )
    object_match_clause = _publication_entity_match_clause(
        "p_b",
        "m_b",
        "ent_b",
        entity_terms_param="object_terms",
        publication_terms_param="object_publication_terms",
    )

    cypher = f"""
    CALL {{
      MATCH (p_a:Publication)-[cite:CITES]->(p_b:Publication)
      WHERE p_a <> p_b
        AND {subject_match_clause}
        AND {object_match_clause}
      RETURN
        p_a AS p_a,
        p_b AS p_b,
        properties(cite) AS cite_props,
        'subject_to_object' AS citation_direction
      UNION
      MATCH (p_b:Publication)-[cite:CITES]->(p_a:Publication)
      WHERE p_a <> p_b
        AND {subject_match_clause}
        AND {object_match_clause}
      RETURN
        p_a AS p_a,
        p_b AS p_b,
        properties(cite) AS cite_props,
        'object_to_subject' AS citation_direction
    }}
    RETURN
      p_a AS p_a,
      p_b AS p_b,
      cite_props AS cite_props,
      citation_direction AS citation_direction
    ORDER BY
      coalesce(p_a.year, 0) DESC,
      coalesce(p_b.year, 0) DESC
    LIMIT $limit
    """
    records = _as_list(
        client._run(
            cypher,
            {
                "subject_terms": subject_terms,
                "object_terms": object_terms,
                "subject_publication_terms": subject_pub_terms,
                "object_publication_terms": object_pub_terms,
                "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
                "publication_identifier_keys": list(_PUBLICATION_IDENTIFIER_FIELDS),
                "limit": int(limit),
            },
        )
    )

    rows: list[dict[str, Any]] = []
    for record in records:
        pub_a = _normalize_graph_node(
            _rec_get(record, "p_a"), default_type="Publication"
        )
        pub_b = _normalize_graph_node(
            _rec_get(record, "p_b"), default_type="Publication"
        )
        if not pub_a.get("kg_id") or not pub_b.get("kg_id"):
            continue
        citation_direction = str(
            _rec_get(record, "citation_direction") or "subject_to_object"
        ).strip()
        cite_props = _rec_get(record, "cite_props", {}) or {}
        rows.append(
            {
                "publication": pub_a,
                "secondary_publication": pub_b,
                "matched_entity": _node_summary_payload(subject),
                "secondary_matched_entity": _node_summary_payload(obj),
                "mention_type": "CITATION_BRIDGE",
                "mention_props": {
                    "typed_path_kind": "citation_bridge",
                    "citation_direction": citation_direction,
                    "claim_polarity": "supports",
                    "claim_strength": 0.58,
                    "mention_strength": 0.58,
                    "method_rigor": 0.57,
                    "evidence_quality": "medium",
                    "provenance_completeness": 0.66,
                },
                "secondary_mention_props": {
                    "mention_strength": 0.55,
                },
                "claim": {},
                "claim_edge_props": {},
                "evidence_span": {},
                "support_edge_props": {},
                "citation_edge_props": cite_props,
                "typed_path_kind": "citation_bridge",
                "evidence_anchor_scope": "typed_path",
            }
        )
    return rows


def _collect_shared_reference_overlap_evidence(
    subject: KGNodeSummary,
    obj: KGNodeSummary,
    *,
    limit: int,
    client: Neo4jGraphDB,
) -> list[dict[str, Any]]:
    subject_terms = _entity_lookup_terms(subject)
    object_terms = _entity_lookup_terms(obj)
    subject_pub_terms = _publication_anchor_lookup_terms(subject)
    object_pub_terms = _publication_anchor_lookup_terms(obj)
    if not subject_terms or not object_terms:
        return []
    subject_match_clause = _publication_entity_match_clause(
        "p_a",
        "m_a",
        "ent_a",
        entity_terms_param="subject_terms",
        publication_terms_param="subject_publication_terms",
    )
    object_match_clause = _publication_entity_match_clause(
        "p_b",
        "m_b",
        "ent_b",
        entity_terms_param="object_terms",
        publication_terms_param="object_publication_terms",
    )

    cypher = f"""
    MATCH (p_a:Publication)-[:CITES]->(ref:Publication)<-[:CITES]-(p_b:Publication)
    WHERE p_a <> p_b
      AND {subject_match_clause}
      AND {object_match_clause}
    WITH p_a, p_b, collect(ref) AS refs, count(DISTINCT ref) AS shared_reference_count
    RETURN
      p_a AS p_a,
      p_b AS p_b,
      refs[0] AS ref,
      shared_reference_count AS shared_reference_count
    ORDER BY shared_reference_count DESC,
      coalesce(p_a.year, 0) DESC,
      coalesce(p_b.year, 0) DESC
    LIMIT $limit
    """
    records = _as_list(
        client._run(
            cypher,
            {
                "subject_terms": subject_terms,
                "object_terms": object_terms,
                "subject_publication_terms": subject_pub_terms,
                "object_publication_terms": object_pub_terms,
                "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
                "publication_identifier_keys": list(_PUBLICATION_IDENTIFIER_FIELDS),
                "limit": int(limit),
            },
        )
    )

    rows: list[dict[str, Any]] = []
    for record in records:
        pub_a = _normalize_graph_node(
            _rec_get(record, "p_a"), default_type="Publication"
        )
        pub_b = _normalize_graph_node(
            _rec_get(record, "p_b"), default_type="Publication"
        )
        ref = _normalize_graph_node(_rec_get(record, "ref"), default_type="Publication")
        if not pub_a.get("kg_id") or not pub_b.get("kg_id") or not ref.get("kg_id"):
            continue
        shared_count = max(1, int(_rec_get(record, "shared_reference_count", 1) or 1))
        rows.append(
            {
                "publication": pub_a,
                "secondary_publication": pub_b,
                "matched_entity": _node_summary_payload(subject),
                "secondary_matched_entity": _node_summary_payload(obj),
                "mention_type": "SHARED_REFERENCE_OVERLAP",
                "mention_props": {
                    "typed_path_kind": "shared_reference_overlap",
                    "shared_reference_count": shared_count,
                    "claim_polarity": "supports",
                    "claim_strength": round(min(0.9, 0.44 + 0.06 * shared_count), 3),
                    "mention_strength": round(min(0.9, 0.44 + 0.06 * shared_count), 3),
                    "method_rigor": 0.56,
                    "evidence_quality": "medium",
                    "provenance_completeness": 0.69,
                },
                "secondary_mention_props": {
                    "mention_strength": round(min(0.9, 0.42 + 0.06 * shared_count), 3),
                },
                "claim": {},
                "claim_edge_props": {},
                "evidence_span": {},
                "support_edge_props": {},
                "shared_reference": ref,
                "typed_path_kind": "shared_reference_overlap",
                "evidence_anchor_scope": "typed_path",
            }
        )
    return rows


def _publication_value(
    publication: Mapping[str, Any] | None,
    key: str,
) -> str:
    if not isinstance(publication, Mapping):
        return ""
    value = publication.get(key)
    if value in (None, ""):
        props = publication.get("properties")
        if isinstance(props, Mapping):
            value = props.get(key)
    return str(value or "").strip()


def _normalize_paper_like_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[-_/]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _publication_identity_key(publication: Mapping[str, Any] | None) -> str:
    aligned_study_id = _publication_value(publication, "aligned_study_id").lower()
    if aligned_study_id:
        return f"aligned_study:{aligned_study_id}"
    aligned_publication_id = _publication_value(
        publication, "aligned_publication_id"
    ).lower()
    if aligned_publication_id:
        return f"aligned_publication:{aligned_publication_id}"
    pmid = _publication_value(publication, "pmid").lower()
    if pmid:
        return f"pmid:{pmid}"
    doi = _publication_value(publication, "doi").lower()
    if doi:
        return f"doi:{doi}"
    title = _normalize_paper_like_text(
        _publication_value(publication, "title")
        or _publication_value(publication, "label")
    )
    if title:
        return f"title:{title}"
    kg_id = _publication_value(publication, "kg_id").lower()
    if kg_id:
        return f"id:{kg_id}"
    return ""


def _publication_row_priority(row: Mapping[str, Any]) -> tuple[int, int, int]:
    publication = row.get("publication") or {}
    node_type = str((publication or {}).get("node_type") or "").strip().lower()
    source_rank = 0 if node_type in {"publication", "paper"} else 1
    claim_rank = 0 if (row.get("claim") or {}).get("kg_id") else 1
    scope_rank = 0 if str(row.get("evidence_anchor_scope") or "") == "direct" else 1
    return (source_rank, claim_rank, scope_rank)


def _publication_ids_from_rows(rows: Sequence[dict[str, Any]]) -> set[str]:
    pub_ids: set[str] = set()
    for row in rows:
        publication_id = _publication_identity_key(row.get("publication") or {})
        if publication_id:
            pub_ids.add(publication_id)
    return pub_ids


def _normalize_candidate_lane_mode(
    mode: str | None,
    *,
    warnings: list[str] | None = None,
) -> str:
    normalized = str(mode or "broad").strip().lower()
    if normalized in {"", "default"}:
        return "broad"
    if normalized in {"broad", "strict"}:
        return normalized
    if warnings is not None:
        warnings.append(f"Unsupported candidate_lane_mode '{mode}'; using 'broad'")
    return "broad"


def _candidate_lane_flag(props: Mapping[str, Any] | None) -> bool:
    if not isinstance(props, Mapping):
        return False
    value = props.get("candidate_lane_present")
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "t", "yes", "y"}


def _row_is_candidate_lane(row: Mapping[str, Any]) -> bool:
    claim_props = ((row.get("claim") or {}).get("properties") or {}) or {}
    evidence_props = ((row.get("evidence_span") or {}).get("properties") or {}) or {}
    claim_edge_props = (row.get("claim_edge_props") or {}) or {}
    support_edge_props = (row.get("support_edge_props") or {}) or {}
    mention_props = (row.get("mention_props") or {}) or {}

    if any(
        _candidate_lane_flag(props)
        for props in (
            claim_props,
            evidence_props,
            claim_edge_props,
            support_edge_props,
        )
    ):
        return True

    claim_id = str((row.get("claim") or {}).get("kg_id") or "").strip()
    evidence_id = str((row.get("evidence_span") or {}).get("kg_id") or "").strip()
    return not claim_id and not evidence_id and _candidate_lane_flag(mention_props)


def _build_candidate_lane_payload(
    row: Mapping[str, Any],
    *,
    mode: str,
) -> dict[str, Any] | None:
    if not _row_is_candidate_lane(row):
        return None

    source_props: list[tuple[str, Mapping[str, Any]]] = []
    for source_name, props in (
        ("claim", ((row.get("claim") or {}).get("properties") or {}) or {}),
        (
            "evidence_span",
            ((row.get("evidence_span") or {}).get("properties") or {}) or {},
        ),
        ("claim_edge", (row.get("claim_edge_props") or {}) or {}),
        ("support_edge", (row.get("support_edge_props") or {}) or {}),
        ("mention", (row.get("mention_props") or {}) or {}),
    ):
        if _candidate_lane_flag(props):
            source_props.append((source_name, props))

    if not source_props:
        return None

    def _pick(key: str) -> Any:
        for _source_name, props in source_props:
            value = props.get(key)
            if isinstance(value, str):
                if value.strip():
                    return value.strip()
                continue
            if isinstance(value, list):
                if value:
                    return value
                continue
            if value is not None:
                return value
        return None

    review_reasons = _pick("candidate_lane_review_reasons")
    if isinstance(review_reasons, list):
        review_reasons = [
            str(reason).strip() for reason in review_reasons if str(reason).strip()
        ]
    else:
        review_reasons = []

    target_id = str(_pick("candidate_lane_target_id") or "").strip()
    target_label = str(_pick("candidate_lane_target_label") or "").strip()
    target = None
    if target_id or target_label:
        target = {}
        if target_id:
            target["id"] = target_id
        if target_label:
            target["label"] = target_label

    payload: dict[str, Any] = {
        "present": True,
        "mode": str(mode or "broad"),
        "provenance_sources": [source_name for source_name, _ in source_props],
    }
    for output_key, source_key in (
        ("promoted_at", "candidate_lane_promoted_at"),
        ("source_quality_profile", "candidate_lane_source_quality_profile"),
        ("bucket", "candidate_lane_bucket"),
        ("policy", "candidate_lane_policy"),
        ("trigger_reason", "candidate_lane_trigger_reason"),
        ("source_review_bucket", "candidate_lane_source_review_bucket"),
        ("source_bucket_reason", "candidate_lane_source_bucket_reason"),
        ("queue_path", "candidate_lane_queue_path"),
    ):
        value = _pick(source_key)
        if isinstance(value, str):
            value = value.strip()
        if value not in (None, "", []):
            payload[output_key] = value

    if review_reasons:
        payload["review_reasons"] = review_reasons
    if target is not None:
        payload["target"] = target
    return payload


def _normalize_external_literature_query(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text or None


def _normalize_external_literature_exclude_domains(
    value: Sequence[str] | None,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in value or []:
        text = str(raw or "").strip().lower()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _build_external_literature_query(
    *,
    hypothesis: str,
    subject: KGNodeSummary | None,
    obj: KGNodeSummary | None,
    external_literature_query: str | None,
) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for raw in (
        _normalize_external_literature_query(external_literature_query),
        _normalize_external_literature_query(hypothesis),
        _normalize_external_literature_query(subject.label if subject else None),
        _normalize_external_literature_query(obj.label if obj else None),
    ):
        if not raw:
            continue
        key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(raw)
    return " ".join(parts)


def _external_literature_score_from_document(doc: Mapping[str, Any]) -> float:
    source_type = str(doc.get("source_type") or "").strip().lower()
    source_host = str(doc.get("source_host") or "").strip().lower()
    title = str(doc.get("title") or "").strip().lower()
    base = 0.38
    if source_type == "paper":
        base = 0.56
    elif source_type == "dataset":
        base = 0.44
    if any(token in f"{source_host} {title}" for token in {"pubmed", "doi", "journal"}):
        base = max(base, 0.62)
    return round(_clip01(base), 2)


def _build_external_literature_evidence_items(
    *,
    research_result: Mapping[str, Any],
    literature_query: str,
    subject: KGNodeSummary | None,
    obj: KGNodeSummary | None,
    max_items: int,
) -> list[dict[str, Any]]:
    report = (
        dict(research_result.get("result"))
        if isinstance(research_result.get("result"), Mapping)
        else {}
    )
    documents = report.get("documents")
    if not isinstance(documents, list):
        return []

    matched_entities = [
        _node_summary_payload(entity) for entity in (subject, obj) if entity is not None
    ]
    idempotency_key = str(research_result.get("idempotency_key") or "").strip()
    status = str(report.get("status") or research_result.get("status") or "").strip()
    items: list[dict[str, Any]] = []
    for idx, raw_doc in enumerate(documents[:max_items], start=1):
        if not isinstance(raw_doc, Mapping):
            continue
        url = str(raw_doc.get("url") or raw_doc.get("raw_url") or "").strip()
        if not url:
            continue
        title = str(raw_doc.get("title") or raw_doc.get("display_url") or url).strip()
        snippets = raw_doc.get("snippets")
        snippet = ""
        if isinstance(snippets, list):
            snippet = next(
                (
                    str(item or "").strip()
                    for item in snippets
                    if str(item or "").strip()
                ),
                "",
            )
        evidence_id = str(raw_doc.get("doc_id") or "").strip() or (
            f"external_literature:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]}"
        )
        score = _external_literature_score_from_document(raw_doc)
        quality = {
            "claim_strength": 0.0,
            "method_rigor": 0.0,
            "evidence_quality_score": score,
            "provenance_completeness": 0.55,
        }
        items.append(
            {
                "evidence_id": evidence_id,
                "publication": {
                    "kg_id": evidence_id,
                    "label": title,
                    "node_type": "Publication",
                    "properties": {
                        "source_class": "peer_reviewed"
                        if str(raw_doc.get("source_type") or "").strip().lower()
                        == "paper"
                        else "web",
                        "source": "external_literature",
                        "journal": raw_doc.get("publisher"),
                        "year": raw_doc.get("published_at"),
                        "url": url,
                    },
                },
                "claim": None,
                "evidence_span": {
                    "kg_id": f"{evidence_id}:span:{idx}",
                    "quote": snippet or report.get("summary") or title,
                    "section": "external_literature",
                },
                "matched_entity": matched_entities[0] if matched_entities else {},
                "matched_entities": matched_entities,
                "polarity": "uncertain",
                "score": score,
                "quality": quality,
                "evidence_anchor_scope": "external_literature",
                "external_literature": {
                    "query": literature_query,
                    "status": status,
                    "idempotency_key": idempotency_key or None,
                    "url": url,
                    "source_host": raw_doc.get("source_host"),
                    "source_type": raw_doc.get("source_type"),
                    "publisher": raw_doc.get("publisher"),
                    "published_at": raw_doc.get("published_at"),
                },
            }
        )
    return items


def _resolve_task_family_fallback_entities(
    entity: KGNodeSummary,
    *,
    client: Neo4jGraphDB,
    limit: int = 3,
) -> list[KGNodeSummary]:
    if _canonical_ood_node_type(entity.node_type) != "Task":
        return []
    family_hits = neighbors(
        entity.kg_id,
        relation_types=["BELONGS_TO_FAMILY"],
        direction="both",
        limit=max(3, limit),
        db=client,
    )
    families: list[KGNodeSummary] = []
    seen: set[str] = set()
    for hit in family_hits:
        kg_id = str(hit.get("kg_id") or "").strip()
        if not kg_id or kg_id in seen:
            continue
        if _canonical_ood_node_type(hit.get("node_type")) != "TaskFamily":
            continue
        seen.add(kg_id)
        families.append(
            KGNodeSummary(
                kg_id=kg_id,
                label=str(hit.get("label") or kg_id),
                node_type=str(hit.get("node_type") or "TaskFamily"),
                score=_safe_float(hit.get("score"), 0.0),
                properties=hit.get("properties"),
            )
        )
        if len(families) >= limit:
            break
    families.sort(key=lambda item: (-_safe_float(item.score, 0.0), item.kg_id))
    return families[:limit]


def _row_polarity_and_score(
    row: dict[str, Any],
    *,
    ignore_mention_fallback: bool = False,
) -> tuple[str, float, dict[str, float | str]]:
    mention_props = row.get("mention_props") or {}
    claim_props = (row.get("claim") or {}).get("properties", {}) or {}
    claim_edge_props = row.get("claim_edge_props") or {}
    evidence_props = (row.get("evidence_span") or {}).get("properties", {}) or {}
    support_props = row.get("support_edge_props") or {}

    polarity = _normalize_claim_polarity(
        claim_props.get("claim_polarity")
        or claim_edge_props.get("claim_polarity")
        or (None if ignore_mention_fallback else mention_props.get("claim_polarity"))
    )
    claim_strength = _clip01(
        max(
            _safe_float(claim_props.get("claim_strength"), 0.0),
            _safe_float(claim_edge_props.get("claim_strength"), 0.0),
            (
                0.0
                if ignore_mention_fallback
                else _safe_float(mention_props.get("claim_strength"), 0.0)
            ),
            (
                0.0
                if ignore_mention_fallback
                else _safe_float(mention_props.get("mention_strength"), 0.0)
            ),
        )
    )
    method_rigor = _clip01(
        max(
            _safe_float(claim_props.get("method_rigor"), 0.0),
            _safe_float(claim_edge_props.get("method_rigor"), 0.0),
            _safe_float(evidence_props.get("method_rigor"), 0.0),
            (
                0.0
                if ignore_mention_fallback
                else _safe_float(mention_props.get("method_rigor"), 0.0)
            ),
        )
    )
    quality_score = _clip01(
        max(
            _safe_float(evidence_props.get("evidence_quality_score"), 0.0),
            _safe_float(support_props.get("evidence_quality_score"), 0.0),
        )
    )
    if quality_score <= 0.0:
        quality_label = (
            str(
                evidence_props.get("evidence_quality")
                or support_props.get("evidence_quality")
                or (
                    None
                    if ignore_mention_fallback
                    else mention_props.get("evidence_quality")
                )
                or "medium"
            )
            .strip()
            .lower()
        )
        quality_score = _EVIDENCE_QUALITY_LABEL_SCORES.get(quality_label, 0.60)
    provenance = _clip01(
        max(
            _safe_float(claim_props.get("provenance_completeness"), 0.0),
            _safe_float(claim_edge_props.get("provenance_completeness"), 0.0),
            _safe_float(evidence_props.get("provenance_completeness"), 0.0),
            _safe_float(support_props.get("provenance_completeness"), 0.0),
            (
                0.0
                if ignore_mention_fallback
                else _safe_float(mention_props.get("provenance_completeness"), 0.0)
            ),
        )
    )
    score = (
        0.35 * claim_strength
        + 0.25 * method_rigor
        + 0.25 * quality_score
        + 0.15 * provenance
    )
    score = round(_clip01(score), 3)
    return (
        polarity,
        score,
        {
            "claim_strength": round(claim_strength, 3),
            "method_rigor": round(method_rigor, 3),
            "evidence_quality_score": round(quality_score, 3),
            "provenance_completeness": round(provenance, 3),
        },
    )


def _row_path_bundle(
    row: dict[str, Any],
    *,
    matched_entities: list[dict[str, Any]],
    suppress_direct_mentions: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()

    def _add_node(node: dict[str, Any], fallback_label: str = "") -> None:
        kg_id = str(node.get("kg_id") or "").strip()
        if not kg_id or kg_id in seen_nodes:
            return
        seen_nodes.add(kg_id)
        payload = {
            "kg_id": kg_id,
            "label": str(node.get("label") or fallback_label or kg_id),
            "node_type": str(node.get("node_type") or "Node"),
        }
        nodes.append(payload)

    def _add_edge(
        source: str, target: str, edge_type: str, props: dict[str, Any] | None = None
    ) -> None:
        source_id = str(source or "").strip()
        target_id = str(target or "").strip()
        if not source_id or not target_id:
            return
        edges.append(
            {
                "source": source_id,
                "target": target_id,
                "type": edge_type,
                "properties": props or {},
            }
        )

    publication = row.get("publication") or {}
    publication_id = str(publication.get("kg_id") or "").strip()
    _add_node(publication, fallback_label="Publication")

    secondary_publication = row.get("secondary_publication") or {}
    secondary_publication_id = str(secondary_publication.get("kg_id") or "").strip()
    if secondary_publication_id:
        _add_node(secondary_publication, fallback_label="Publication")

    for entity in matched_entities:
        _add_node(entity)
        entity_id = str(entity.get("kg_id") or "").strip()
        if publication_id and entity_id and not suppress_direct_mentions:
            _add_edge(
                publication_id, entity_id, "MENTIONS", row.get("mention_props") or {}
            )
        if secondary_publication_id and entity_id and not suppress_direct_mentions:
            secondary_props = row.get("secondary_mention_props") or {}
            _add_edge(secondary_publication_id, entity_id, "MENTIONS", secondary_props)

    claim = row.get("claim") or {}
    claim_id = str(claim.get("kg_id") or "").strip()
    if claim_id:
        _add_node(claim, fallback_label="Claim")
        if publication_id:
            _add_edge(
                publication_id,
                claim_id,
                "REPORTS_CLAIM",
                row.get("claim_edge_props") or {},
            )

    evidence_span = row.get("evidence_span") or {}
    evidence_id = str(evidence_span.get("kg_id") or "").strip()
    if evidence_id:
        _add_node(evidence_span, fallback_label="EvidenceSpan")
        if claim_id:
            _add_edge(
                evidence_id, claim_id, "SUPPORTS", row.get("support_edge_props") or {}
            )

    typed_path_kind = str(row.get("typed_path_kind") or "").strip().lower()
    if typed_path_kind == "coordinate_overlap":
        coord = row.get("shared_coordinate") or {}
        coord_id = str(coord.get("kg_id") or "").strip()
        if coord_id:
            _add_node(coord, fallback_label="Coordinate")
            if publication_id:
                _add_edge(
                    publication_id,
                    coord_id,
                    "HAS_COORDINATE",
                    {
                        "shared_coordinate_count": (row.get("mention_props") or {}).get(
                            "shared_coordinate_count"
                        )
                    },
                )
    elif typed_path_kind == "citation_bridge":
        citation_props = row.get("citation_edge_props") or {}
        citation_direction = str(
            (row.get("mention_props") or {}).get("citation_direction")
            or citation_props.get("direction")
            or "subject_to_object"
        ).strip()
        if publication_id and secondary_publication_id:
            if citation_direction == "object_to_subject":
                _add_edge(
                    secondary_publication_id,
                    publication_id,
                    "CITES",
                    citation_props,
                )
            else:
                _add_edge(
                    publication_id,
                    secondary_publication_id,
                    "CITES",
                    citation_props,
                )
    elif typed_path_kind == "shared_reference_overlap":
        ref = row.get("shared_reference") or {}
        ref_id = str(ref.get("kg_id") or "").strip()
        shared_props = {
            "shared_reference_count": (row.get("mention_props") or {}).get(
                "shared_reference_count"
            )
        }
        if ref_id:
            _add_node(ref, fallback_label="Publication")
            if publication_id:
                _add_edge(publication_id, ref_id, "CITES", shared_props)
            if secondary_publication_id:
                _add_edge(secondary_publication_id, ref_id, "CITES", shared_props)

    return {"nodes": nodes, "edges": edges}


def _path_preview_from_bundle(bundle: dict[str, Any]) -> str:
    labels = [
        str(node.get("label") or node.get("kg_id") or "")
        for node in (bundle.get("nodes") or [])
        if isinstance(node, dict)
    ]
    labels = [label for label in labels if label][:5]
    if len(labels) >= 2:
        return " -> ".join(labels)
    if labels:
        return labels[0]
    return ""


def _infer_hypothesis_predicate(hypothesis: str) -> str:
    text = (hypothesis or "").lower()
    if "involved" in text:
        return "involved_in"
    if "activat" in text:
        return "activates"
    if "associated" in text or "related" in text or "linked" in text:
        return "associated_with"
    return "related_to"


def verify_hypothesis(
    hypothesis: str,
    *,
    entity_hints: list[str] | None = None,
    allowed_node_types: list[str] | None = None,
    max_evidence: int = 60,
    max_paths: int = 60,
    strictness: str = "high_recall",
    min_evidence_score: float | None = None,
    include_subgraph: bool = True,
    include_path_details: bool = True,
    confidence_scoring_version: str = "v2",
    evidence_control: str = "default",
    candidate_lane_mode: str = "broad",
    use_external_literature: bool = False,
    external_literature_query: str | None = None,
    external_literature_top_k: int = 5,
    external_literature_recency_days: int = 365,
    external_literature_exclude_domains: Sequence[str] | None = None,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    """Verify a hypothesis against KG evidence with support/conflict alignment."""
    started = time.perf_counter()
    warnings: list[str] = []
    timings = {
        "entity_resolution": 0.0,
        "semantic_rerank": 0.0,
        "direct_evidence_collection": 0.0,
        "typed_path_evidence_collection": 0.0,
        "family_fallback_lookup": 0.0,
        "family_fallback_evidence_collection": 0.0,
        "external_literature_search": 0.0,
        "aggregation": 0.0,
        "total": 0.0,
    }
    strictness_norm = _normalize_hypothesis_strictness(strictness)
    scoring_version = _normalize_confidence_scoring_version(confidence_scoring_version)
    max_evidence_i = _coerce_bounded_int(
        max_evidence,
        default=60,
        min_value=5,
        max_value=200,
        field_name="max_evidence",
        warnings=warnings,
    )
    max_paths_i = _coerce_bounded_int(
        max_paths,
        default=60,
        min_value=1,
        max_value=200,
        field_name="max_paths",
        warnings=warnings,
    )
    threshold = (
        _safe_float(
            min_evidence_score, _HYPOTHESIS_STRICTNESS_THRESHOLDS[strictness_norm]
        )
        if min_evidence_score is not None
        else _HYPOTHESIS_STRICTNESS_THRESHOLDS[strictness_norm]
    )
    threshold = _clip01(threshold)
    evidence_control_norm = str(evidence_control or "default").strip().lower()
    if evidence_control_norm not in {"default", "claim_only"}:
        warnings.append(
            f"Unsupported evidence_control '{evidence_control}'; using 'default'"
        )
        evidence_control_norm = "default"
    claim_only_control = evidence_control_norm == "claim_only"
    candidate_lane_mode_norm = _normalize_candidate_lane_mode(
        candidate_lane_mode,
        warnings=warnings,
    )
    external_literature_top_k_i = _coerce_bounded_int(
        external_literature_top_k,
        default=5,
        min_value=1,
        max_value=20,
        field_name="external_literature_top_k",
        warnings=warnings,
    )
    external_literature_recency_days_i = _coerce_bounded_int(
        external_literature_recency_days,
        default=365,
        min_value=0,
        max_value=3650,
        field_name="external_literature_recency_days",
        warnings=warnings,
    )
    external_literature_exclude_domains_norm = (
        _normalize_external_literature_exclude_domains(
            external_literature_exclude_domains
        )
    )
    client = db or get_default_db()
    search_terms = _extract_hypothesis_terms(hypothesis, entity_hints=entity_hints)
    expanded_node_types = _expand_types(allowed_node_types)
    coerced_hints = _coerce_entity_hints(entity_hints)
    raw_seed_entities: list[KGNodeSummary] = []
    seed_entities: list[KGNodeSummary] = []
    exact_hint_ids: set[str] = set()
    exact_hint_entities_ordered: list[KGNodeSummary] = []
    resolution_mode = "search_expansion"

    def _empty_result(extra_warning: str) -> dict[str, Any]:
        timings["total"] = round(
            max(time.perf_counter() - started, timings["entity_resolution"]), 4
        )
        summary = {
            "n_seed_entities": len(seed_entities),
            "n_candidate_publications": 0,
            "n_supporting": 0,
            "n_conflicting": 0,
            "n_uncertain": 0,
            "n_neutral": 0,
            "n_candidate_lane_supporting": 0,
            "n_candidate_lane_conflicting": 0,
            "n_candidate_lane_uncertain": 0,
            "n_candidate_lane_neutral": 0,
            "n_external_literature_supporting": 0,
            "n_external_literature_conflicting": 0,
            "n_external_literature_uncertain": 0,
            "n_external_literature_neutral": 0,
            "evidence_scope": "none",
            "evidence_source_scope": "direct",
            "evidence_control": evidence_control_norm,
            "candidate_lane_mode": candidate_lane_mode_norm,
            "candidate_lane_filtered": 0,
            "external_literature_requested": bool(use_external_literature),
            "timings_s": dict(timings),
            "query_time_s": timings["total"],
        }
        return {
            "hypothesis": hypothesis,
            "normalized_claim": {
                "subject": _node_summary_payload(seed_entities[0])
                if seed_entities
                else None,
                "object": _node_summary_payload(seed_entities[1])
                if len(seed_entities) > 1
                else None,
                "predicate": _infer_hypothesis_predicate(hypothesis),
                "raw": hypothesis,
            },
            "verdict": "insufficient_evidence",
            "confidence": 0.0,
            "strictness": strictness_norm,
            "evidence_control": evidence_control_norm,
            "candidate_lane_mode": candidate_lane_mode_norm,
            "evidence_mode": "none",
            "evidence_source_scope": "direct",
            "summary": summary,
            "supporting_evidence": [],
            "conflicting_evidence": [],
            "uncertain_evidence": [],
            "neutral_evidence": [],
            "confidence_signals": {
                "scoring_version": scoring_version,
                "confidence": 0.0,
            },
            "top_paths": [],
            "subgraph": {"nodes": [], "edges": []},
            "warnings": warnings + [extra_warning],
            "provenance": [
                {
                    "stage": "entity_resolution",
                    "resolution_mode": resolution_mode,
                    "search_terms": search_terms,
                    "allowed_node_types": expanded_node_types,
                    "raw_seed_entities": [
                        _node_summary_payload(entity)
                        for entity in raw_seed_entities[:8]
                    ],
                    "seed_entities": [
                        _node_summary_payload(entity) for entity in seed_entities[:8]
                    ],
                    "timings_s": dict(timings),
                },
                {
                    "stage": "evidence_collection",
                    "strictness": strictness_norm,
                    "min_evidence_score": round(threshold, 3),
                    "confidence_scoring_version": scoring_version,
                    "evidence_control": evidence_control_norm,
                    "candidate_lane_mode": candidate_lane_mode_norm,
                    "selected_entities": [
                        _node_summary_payload(entity) for entity in seed_entities[:2]
                    ],
                    "max_evidence": max_evidence_i,
                    "entity_expansions": [],
                    "timings_s": {
                        "direct_evidence_collection": timings[
                            "direct_evidence_collection"
                        ],
                        "typed_path_evidence_collection": timings[
                            "typed_path_evidence_collection"
                        ],
                        "family_fallback_lookup": timings["family_fallback_lookup"],
                        "family_fallback_evidence_collection": timings[
                            "family_fallback_evidence_collection"
                        ],
                        "aggregation": timings["aggregation"],
                        "total": timings["total"],
                    },
                },
            ],
            "timings_s": dict(timings),
        }

    entity_resolution_started = time.perf_counter()
    exact_entities: list[KGNodeSummary] = []
    can_exact_fast_path = bool(coerced_hints)
    for hint in coerced_hints:
        entity = _resolve_exact_hint_entity(
            hint,
            client=client,
            allowed_node_types=expanded_node_types,
        )
        if entity is None:
            can_exact_fast_path = False
            continue
        kg_id = str(entity.kg_id or "").strip()
        if kg_id and kg_id not in exact_hint_ids:
            exact_hint_ids.add(kg_id)
            exact_entities.append(entity)
            exact_hint_entities_ordered.append(entity)
    timings["entity_resolution"] = round(
        time.perf_counter() - entity_resolution_started, 4
    )

    if can_exact_fast_path and exact_entities:
        resolution_mode = "exact_id_fast_path"
        raw_seed_entities = list(exact_entities)
        seed_entities = list(exact_entities)
    else:
        resolution_mode = "search_expansion"
        seed_entities = []
        seen_seed_ids: set[str] = set()
        search_started = time.perf_counter()
        for term in search_terms:
            if len(seed_entities) >= 8:
                break
            detail = node_details(term, db=client)
            if detail and detail.kg_id and detail.kg_id not in seen_seed_ids:
                seed_entities.append(detail)
                seen_seed_ids.add(detail.kg_id)
                if len(seed_entities) >= 8:
                    break
            semantic_types = expanded_node_types or sorted(
                {
                    _canonical_ood_node_type(value)
                    for value in _HYPOTHESIS_PREFERRED_ENTITY_TYPES
                    if _canonical_ood_node_type(value) != "Modality"
                }
            )
            hits = search_nodes(
                term,
                node_types=semantic_types,
                limit=6,
                db=client,
                infer_types=True,
            )
            if not hits and expanded_node_types:
                hits = search_nodes(
                    term,
                    node_types=expanded_node_types,
                    limit=6,
                    db=client,
                    infer_types=True,
                )
            if not hits:
                hits = search_nodes(
                    term,
                    node_types=None,
                    limit=6,
                    db=client,
                    infer_types=True,
                )
            for hit in hits:
                if not hit.kg_id or hit.kg_id in seen_seed_ids:
                    continue
                seed_entities.append(hit)
                seen_seed_ids.add(hit.kg_id)
                if len(seed_entities) >= 8:
                    break
        raw_seed_entities = list(seed_entities)
        timings["entity_resolution"] = round(
            timings["entity_resolution"] + (time.perf_counter() - search_started), 4
        )
        if seed_entities:
            rerank_started = time.perf_counter()
            reranked, semantic_warnings = _resolve_hypothesis_seed_entities(
                raw_seed_entities,
                search_terms=search_terms,
                client=client,
                exact_hint_ids=sorted(exact_hint_ids),
            )
            warnings.extend(semantic_warnings)
            if reranked:
                seed_entities = reranked
            timings["semantic_rerank"] = round(time.perf_counter() - rerank_started, 4)

    if not seed_entities:
        return _empty_result("No seed entities resolved from hypothesis")

    query_tokens = _hypothesis_query_tokens(search_terms)
    seed_entities_by_id = {
        str(entity.kg_id or "").strip(): entity
        for entity in seed_entities
        if str(entity.kg_id or "").strip()
    }
    ordered_exact_entities: list[KGNodeSummary] = []
    seen_exact_ids: set[str] = set()
    for entity in exact_hint_entities_ordered:
        kg_id = str(entity.kg_id or "").strip()
        canonical = seed_entities_by_id.get(kg_id)
        if not kg_id or canonical is None or kg_id in seen_exact_ids:
            continue
        ordered_exact_entities.append(canonical)
        seen_exact_ids.add(kg_id)

    subject = ordered_exact_entities[0] if ordered_exact_entities else seed_entities[0]
    obj = None
    if not ordered_exact_entities:
        non_exact_hints = [
            hint
            for hint in coerced_hints
            if hint and not _is_exact_identifier_hint(hint)
        ]
        matched_subject = (
            _match_seed_entity_to_hint(seed_entities, hint=non_exact_hints[0])
            if non_exact_hints
            else None
        )
        if matched_subject is not None:
            subject = matched_subject
    subject_lookup_terms = set(_entity_lookup_terms(subject))
    exact_subject_alias_only = bool(
        len(ordered_exact_entities) == 1
        and coerced_hints
        and subject_lookup_terms
        and all(
            bool(
                set(_build_lookup_terms(str(hint or "").strip())).intersection(
                    subject_lookup_terms
                )
            )
            for hint in coerced_hints
            if str(hint or "").strip()
        )
    )
    if len(ordered_exact_entities) >= 2:
        for candidate in ordered_exact_entities[1:]:
            if str(candidate.kg_id or "").strip() != str(subject.kg_id or "").strip():
                obj = candidate
                break
    if obj is None and not ordered_exact_entities:
        non_exact_hints = [
            hint
            for hint in coerced_hints
            if hint and not _is_exact_identifier_hint(hint)
        ]
        if len(non_exact_hints) >= 2:
            matched_object = _match_seed_entity_to_hint(
                seed_entities,
                hint=non_exact_hints[1],
                exclude_ids={str(subject.kg_id or "").strip()},
            )
            if matched_object is not None:
                obj = matched_object
    if obj is None and not exact_subject_alias_only:
        for candidate in seed_entities[1:]:
            if str(candidate.kg_id or "").strip() == str(subject.kg_id or "").strip():
                continue
            if not query_tokens or (
                _hypothesis_entity_overlap_count(candidate, query_tokens=query_tokens)
                > 0
            ):
                obj = candidate
                break
    selected_entities = [subject] + ([obj] if obj else [])
    if not obj:
        warnings.append(
            "Only one semantically aligned seed entity found; validating single-entity evidence"
        )

    evidence_started = time.perf_counter()
    entity_rows: dict[str, list[dict[str, Any]]] = {}
    for entity in selected_entities:
        try:
            entity_rows[entity.kg_id] = _collect_publication_evidence_for_entity(
                entity,
                limit=max_evidence_i,
                client=client,
            )
        except Exception as exc:
            warnings.append(
                f"Evidence collection failed for '{entity.label or entity.kg_id}': {exc}"
            )
            entity_rows[entity.kg_id] = []
    timings["direct_evidence_collection"] = round(
        time.perf_counter() - evidence_started, 4
    )

    entity_expansions: list[dict[str, Any]] = []
    direct_shared_pub_ids: set[str] = set()
    if obj:
        direct_shared_pub_ids = _publication_ids_from_rows(
            entity_rows.get(subject.kg_id, [])
        ).intersection(_publication_ids_from_rows(entity_rows.get(obj.kg_id, [])))

    family_lookup_elapsed = 0.0
    family_collect_elapsed = 0.0
    for entity in selected_entities:
        direct_pub_ids = _publication_ids_from_rows(entity_rows.get(entity.kg_id, []))
        expansion = {
            "entity": _node_summary_payload(entity),
            "direct_publication_count": len(direct_pub_ids),
            "fallback_triggered": False,
            "trigger_reason": None,
            "family_candidates": [],
            "fallback_publication_count": 0,
        }
        trigger_reason = None
        if _canonical_ood_node_type(entity.node_type) == "Task":
            if len(direct_pub_ids) == 0:
                trigger_reason = "zero_direct_publications"
            elif obj and not direct_shared_pub_ids:
                trigger_reason = "no_shared_publications"
        if trigger_reason:
            lookup_started = time.perf_counter()
            families = _resolve_task_family_fallback_entities(
                entity,
                client=client,
                limit=3,
            )
            family_lookup_elapsed += time.perf_counter() - lookup_started
            expansion["family_candidates"] = [
                _node_summary_payload(family) for family in families
            ]
            if families:
                family_rows: list[dict[str, Any]] = []
                collect_started = time.perf_counter()
                for family in families:
                    family_rows.extend(
                        _collect_publication_evidence_for_entity(
                            family,
                            limit=max_evidence_i,
                            client=client,
                        )
                    )
                family_collect_elapsed += time.perf_counter() - collect_started
                if family_rows:
                    for row in family_rows:
                        row["evidence_anchor_scope"] = "expanded_family"
                    entity_rows[entity.kg_id] = family_rows
                    expansion["fallback_triggered"] = True
                    expansion["trigger_reason"] = trigger_reason
                    expansion["fallback_publication_count"] = len(
                        _publication_ids_from_rows(family_rows)
                    )
        entity_expansions.append(expansion)
    timings["family_fallback_lookup"] = round(family_lookup_elapsed, 4)
    timings["family_fallback_evidence_collection"] = round(family_collect_elapsed, 4)

    typed_rows: list[dict[str, Any]] = []
    if obj and not claim_only_control:
        typed_started = time.perf_counter()
        typed_rows = []
        try:
            typed_rows.extend(
                _collect_coordinate_overlap_evidence(
                    subject,
                    obj,
                    limit=max_evidence_i,
                    client=client,
                )
            )
        except Exception as exc:
            warnings.append(f"Coordinate overlap evidence collection failed: {exc}")
        try:
            typed_rows.extend(
                _collect_citation_bridge_evidence(
                    subject,
                    obj,
                    limit=max_evidence_i,
                    client=client,
                )
            )
        except Exception as exc:
            warnings.append(f"Citation bridge evidence collection failed: {exc}")
        try:
            typed_rows.extend(
                _collect_shared_reference_overlap_evidence(
                    subject,
                    obj,
                    limit=max_evidence_i,
                    client=client,
                )
            )
        except Exception as exc:
            warnings.append(f"Shared reference evidence collection failed: {exc}")
        timings["typed_path_evidence_collection"] = round(
            time.perf_counter() - typed_started, 4
        )

    aggregation_started = time.perf_counter()
    subject_rows = entity_rows.get(subject.kg_id, [])
    object_rows = entity_rows.get(obj.kg_id, []) if obj else []
    candidate_lane_filtered = 0
    if candidate_lane_mode_norm == "strict":
        subject_rows, filtered = _filter_candidate_lane_rows(subject_rows)
        candidate_lane_filtered += filtered
        if obj:
            object_rows, filtered = _filter_candidate_lane_rows(object_rows)
            candidate_lane_filtered += filtered
        typed_rows, filtered = _filter_candidate_lane_rows(typed_rows)
        candidate_lane_filtered += filtered
    candidate_rows: list[dict[str, Any]] = []
    candidate_publications: set[str] = set()
    evidence_mode = "none"
    evidence_source_scope = "none"

    if obj:
        subject_pub_ids = _publication_ids_from_rows(subject_rows)
        object_pub_ids = _publication_ids_from_rows(object_rows)
        shared_pub_ids = {
            pub_id for pub_id in subject_pub_ids.intersection(object_pub_ids) if pub_id
        }
        if shared_pub_ids:
            evidence_mode = "shared"
            candidate_rows = []
            for row in subject_rows + object_rows:
                publication_id = str(
                    (row.get("publication") or {}).get("kg_id") or ""
                ).strip()
                if publication_id and publication_id in shared_pub_ids:
                    row_copy = dict(row)
                    row_copy["matched_entities"] = [
                        _node_summary_payload(subject),
                        _node_summary_payload(obj),
                    ]
                    candidate_rows.append(row_copy)
                    candidate_publications.add(publication_id)
        elif typed_rows:
            evidence_mode = "shared"
            candidate_rows = []
            for row in typed_rows:
                row_copy = dict(row)
                row_copy["matched_entities"] = [
                    _node_summary_payload(subject),
                    _node_summary_payload(obj),
                ]
                candidate_rows.append(row_copy)
                candidate_publications.add(
                    str((row.get("publication") or {}).get("kg_id") or "").strip()
                )
                candidate_publications.add(
                    str(
                        (row.get("secondary_publication") or {}).get("kg_id") or ""
                    ).strip()
                )
            evidence_source_scope = "typed_path"
        elif subject_rows or object_rows:
            evidence_mode = "union"
            warnings.append(
                "No shared publications mention both top entities; falling back to union evidence"
            )
            for row in subject_rows + object_rows:
                row_copy = dict(row)
                row_copy["matched_entities"] = [
                    _node_summary_payload(subject),
                    _node_summary_payload(obj),
                ]
                candidate_rows.append(row_copy)
                candidate_publications.update(_publication_ids_from_rows([row]))
        else:
            evidence_mode = "none"
    else:
        if subject_rows:
            evidence_mode = "single_entity"
            for row in subject_rows:
                row_copy = dict(row)
                row_copy["matched_entities"] = [_node_summary_payload(subject)]
                candidate_rows.append(row_copy)
                candidate_publications.update(_publication_ids_from_rows([row]))
        else:
            evidence_mode = "none"

    if evidence_source_scope == "none" and candidate_rows:
        if any(
            str(row.get("evidence_anchor_scope") or "").strip().lower()
            in _VERIFY_TYPED_PATH_SCOPES
            for row in candidate_rows
        ):
            evidence_source_scope = "typed_path"
        elif any(
            str(row.get("evidence_anchor_scope") or "").strip().lower()
            == "expanded_family"
            for row in candidate_rows
        ):
            evidence_source_scope = "expanded_family"
        else:
            evidence_source_scope = "direct"

    deduped_rows: list[dict[str, Any]] = []
    dedupe_keys: set[tuple[str, str, str, str, str, str]] = set()
    for row in candidate_rows:
        publication = row.get("publication") or {}
        claim = row.get("claim") or {}
        evidence_span = row.get("evidence_span") or {}
        matched = row.get("matched_entity") or {}
        secondary_publication = row.get("secondary_publication") or {}
        dedupe_key = (
            str(publication.get("kg_id") or ""),
            str(secondary_publication.get("kg_id") or ""),
            str(claim.get("kg_id") or ""),
            str(evidence_span.get("kg_id") or ""),
            str(matched.get("kg_id") or ""),
            str(row.get("typed_path_kind") or ""),
        )
        if dedupe_key in dedupe_keys:
            continue
        dedupe_keys.add(dedupe_key)
        deduped_rows.append(row)

    if candidate_lane_filtered:
        warnings.append(
            f"{candidate_lane_filtered} candidate-lane evidence row(s) were suppressed by candidate_lane_mode=strict"
        )
    candidate_publications = _publication_ids_from_rows(deduped_rows)
    if candidate_lane_mode_norm == "strict" and not deduped_rows and candidate_rows:
        evidence_source_scope = "none"

    if claim_only_control:
        claim_only_rows: list[dict[str, Any]] = []
        claim_only_filtered = 0
        for row in deduped_rows:
            claim_id = str((row.get("claim") or {}).get("kg_id") or "").strip()
            evidence_id = str(
                (row.get("evidence_span") or {}).get("kg_id") or ""
            ).strip()
            if claim_id and evidence_id:
                claim_only_rows.append(row)
            else:
                claim_only_filtered += 1
        deduped_rows = claim_only_rows
        candidate_publications = _publication_ids_from_rows(deduped_rows)
        if claim_only_filtered:
            warnings.append(
                f"{claim_only_filtered} mention-anchored evidence row(s) were suppressed by evidence_control=claim_only"
            )
        if not deduped_rows and candidate_rows:
            evidence_source_scope = "none"

    supporting: list[dict[str, Any]] = []
    conflicting: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    neutral: list[dict[str, Any]] = []
    candidate_lane_supporting = 0
    candidate_lane_conflicting = 0
    candidate_lane_uncertain = 0
    candidate_lane_neutral = 0
    external_literature_supporting = 0
    external_literature_conflicting = 0
    external_literature_uncertain = 0
    external_literature_neutral = 0
    filtered_out = 0
    subgraph_nodes: dict[str, dict[str, Any]] = {}
    subgraph_edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    for row in deduped_rows:
        polarity, score, quality = _row_polarity_and_score(
            row,
            ignore_mention_fallback=claim_only_control,
        )
        if score < threshold:
            filtered_out += 1
            continue

        matched_entities = row.get("matched_entities") or []
        path_bundle = _row_path_bundle(
            row,
            matched_entities=matched_entities,
            suppress_direct_mentions=claim_only_control,
        )
        publication = row.get("publication") or {}
        secondary_publication = row.get("secondary_publication") or {}
        claim = row.get("claim") or {}
        evidence_span = row.get("evidence_span") or {}
        matched_entity = row.get("matched_entity") or {}
        evidence_id = (
            f"{publication.get('kg_id') or 'pub'}:"
            f"{secondary_publication.get('kg_id') or 'nosecond'}:"
            f"{claim.get('kg_id') or 'noclaim'}:"
            f"{evidence_span.get('kg_id') or matched_entity.get('kg_id') or 'none'}"
        )
        payload = {
            "evidence_id": evidence_id,
            "publication": {
                "kg_id": publication.get("kg_id"),
                "label": publication.get("label"),
                "node_type": publication.get("node_type"),
                "pmid": (publication.get("properties") or {}).get("pmid"),
                "doi": (publication.get("properties") or {}).get("doi"),
                "year": (publication.get("properties") or {}).get("year"),
            },
            "claim": {
                "kg_id": claim.get("kg_id"),
                "text": (claim.get("properties") or {}).get("text"),
                "target_id": (claim.get("properties") or {}).get("target_id"),
            }
            if claim
            else None,
            "evidence_span": {
                "kg_id": evidence_span.get("kg_id"),
                "quote": (evidence_span.get("properties") or {}).get("quote"),
                "section": (evidence_span.get("properties") or {}).get("section"),
            }
            if evidence_span
            else None,
            "matched_entity": {
                "kg_id": matched_entity.get("kg_id"),
                "label": matched_entity.get("label"),
                "node_type": matched_entity.get("node_type"),
            },
            "matched_entities": matched_entities,
            "polarity": polarity,
            "score": score,
            "quality": quality,
            "evidence_anchor_scope": str(
                row.get("evidence_anchor_scope") or evidence_source_scope or "direct"
            ),
        }
        candidate_lane_payload = _build_candidate_lane_payload(
            row,
            mode=candidate_lane_mode_norm,
        )
        if candidate_lane_payload is not None and candidate_lane_mode_norm == "broad":
            payload["candidate_lane"] = candidate_lane_payload
        if secondary_publication:
            payload["secondary_publication"] = {
                "kg_id": secondary_publication.get("kg_id"),
                "label": secondary_publication.get("label"),
                "node_type": secondary_publication.get("node_type"),
                "pmid": (secondary_publication.get("properties") or {}).get("pmid"),
                "doi": (secondary_publication.get("properties") or {}).get("doi"),
                "year": (secondary_publication.get("properties") or {}).get("year"),
            }
        if row.get("typed_path_kind") == "coordinate_overlap":
            payload["typed_path"] = {
                "kind": "coordinate_overlap",
                "shared_coordinate_count": int(
                    (
                        (row.get("mention_props") or {}).get("shared_coordinate_count")
                        or 0
                    )
                ),
                "shared_coordinate": _normalize_graph_node(
                    row.get("shared_coordinate"),
                    default_type="Coordinate",
                ),
            }
        elif row.get("typed_path_kind") == "citation_bridge":
            payload["typed_path"] = {
                "kind": "citation_bridge",
                "citation_direction": str(
                    (row.get("mention_props") or {}).get("citation_direction")
                    or "subject_to_object"
                ),
                "citation_edge_props": row.get("citation_edge_props") or {},
            }
        elif row.get("typed_path_kind") == "shared_reference_overlap":
            payload["typed_path"] = {
                "kind": "shared_reference_overlap",
                "shared_reference_count": int(
                    (
                        (row.get("mention_props") or {}).get("shared_reference_count")
                        or 0
                    )
                ),
                "shared_reference": _normalize_graph_node(
                    row.get("shared_reference"),
                    default_type="Publication",
                ),
            }
        if include_path_details:
            payload["path"] = path_bundle

        if polarity == "supports":
            supporting.append(payload)
            if candidate_lane_payload is not None:
                candidate_lane_supporting += 1
        elif polarity == "refutes":
            conflicting.append(payload)
            if candidate_lane_payload is not None:
                candidate_lane_conflicting += 1
        elif polarity in {"uncertain", "mixed"}:
            uncertain.append(payload)
            if candidate_lane_payload is not None:
                candidate_lane_uncertain += 1
        else:
            neutral.append(payload)
            if candidate_lane_payload is not None:
                candidate_lane_neutral += 1

        for node in path_bundle.get("nodes", []):
            node_id = str(node.get("kg_id") or "").strip()
            if node_id:
                subgraph_nodes[node_id] = node
        for edge in path_bundle.get("edges", []):
            sig = (
                str(edge.get("source") or "").strip(),
                str(edge.get("target") or "").strip(),
                str(edge.get("type") or "").strip(),
            )
            if sig[0] and sig[1] and sig[2]:
                subgraph_edges[sig] = edge

    external_literature_evidence: list[dict[str, Any]] = []
    literature_query = ""
    if use_external_literature and (
        not supporting
        and not conflicting
        and evidence_mode in {"none", "union", "single_entity", "shared"}
    ):
        literature_query = _build_external_literature_query(
            hypothesis=hypothesis,
            subject=subject,
            obj=obj,
            external_literature_query=external_literature_query,
        )
        if literature_query:
            external_started = time.perf_counter()
            deep_result = _deep_research_sync(
                {
                    "query": literature_query,
                    "intent": "hypothesis_verification",
                    "recency_days": external_literature_recency_days_i,
                    "top_k": external_literature_top_k_i,
                    "exclude_domains": external_literature_exclude_domains_norm,
                }
            )
            timings["external_literature_search"] = round(
                time.perf_counter() - external_started,
                4,
            )
            if str(deep_result.get("status") or "").strip().lower() == "error":
                warnings.append(
                    "External literature search failed: "
                    f"{deep_result.get('error') or deep_result.get('message') or 'unknown_error'}"
                )
            else:
                external_literature_evidence = (
                    _build_external_literature_evidence_items(
                        research_result=deep_result,
                        literature_query=literature_query,
                        subject=subject,
                        obj=obj,
                        max_items=external_literature_top_k_i,
                    )
                )
                uncertain.extend(external_literature_evidence)
                external_literature_uncertain = len(external_literature_evidence)
                candidate_publications.update(
                    {
                        str((item.get("publication") or {}).get("kg_id") or "").strip()
                        for item in external_literature_evidence
                        if str(
                            (item.get("publication") or {}).get("kg_id") or ""
                        ).strip()
                    }
                )
                if external_literature_evidence:
                    if evidence_source_scope == "none":
                        evidence_source_scope = "external_literature"
                    elif evidence_source_scope != "external_literature":
                        evidence_source_scope = "hybrid_kg_literature"
        else:
            warnings.append(
                "External literature search was requested but no literature query could be constructed"
            )

    supporting.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    conflicting.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    uncertain.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    neutral.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)

    support_score = sum(float(item.get("score") or 0.0) for item in supporting)
    conflict_score = sum(float(item.get("score") or 0.0) for item in conflicting)
    confidence_signals: dict[str, Any]
    if scoring_version == "v1":
        confidence, confidence_signals = _legacy_hypothesis_confidence(
            support_score=support_score,
            conflict_score=conflict_score,
            max_evidence=max_evidence_i,
            has_mixed_evidence=bool(supporting and conflicting),
        )
    else:
        confidence_inputs: list[EvidenceSignal] = []
        for collection_name, direction in (
            (supporting, "support"),
            (conflicting, "conflict"),
            (uncertain, "uncertain"),
            (neutral, "neutral"),
        ):
            for item in collection_name:
                quality = _safe_float(
                    (item.get("quality") or {}).get("evidence_quality_score"), 0.0
                )
                confidence_inputs.append(
                    EvidenceSignal(
                        direction=direction,
                        strength=_safe_float(item.get("score"), 0.0),
                        quality=quality,
                        source_reliability=_infer_source_reliability_from_evidence_item(
                            item
                        ),
                    )
                )
        confidence_calc = compute_confidence_v2(confidence_inputs)
        confidence = round(_clip01(confidence_calc.confidence), 2)
        confidence_signals = confidence_calc.as_dict()

    if evidence_source_scope == "expanded_family":
        confidence = round(_clip01(confidence * 0.85), 2)
        confidence_signals["source_scope_penalty"] = 0.85
    if evidence_mode == "union":
        cap = 0.25 if evidence_source_scope == "expanded_family" else 0.45
        confidence = round(min(confidence, cap), 2)
        confidence_signals["union_confidence_cap"] = cap
        if cap == 0.25:
            warnings.append(
                "Evidence is family-expanded and union-aggregated; confidence was capped conservatively"
            )
        else:
            warnings.append(
                "Subject/object were supported only by separate evidence chains; confidence was conservatively downgraded and capped"
            )
    if evidence_mode == "none":
        confidence = 0.0

    if evidence_mode == "union":
        if (
            external_literature_evidence
            and not supporting
            and not conflicting
            and uncertain
        ):
            verdict = "uncertain"
        else:
            verdict = "insufficient_evidence"
    elif evidence_mode == "none":
        if supporting and conflicting:
            verdict = "mixed"
        elif supporting:
            verdict = "supported"
        elif conflicting:
            verdict = "conflicting"
        elif uncertain:
            verdict = "uncertain"
        else:
            verdict = "insufficient_evidence"
    elif supporting and conflicting:
        verdict = "mixed"
    elif supporting:
        verdict = "supported"
    elif conflicting:
        verdict = "conflicting"
    elif uncertain:
        verdict = "uncertain"
    else:
        verdict = "insufficient_evidence"

    if filtered_out:
        warnings.append(
            f"{filtered_out} evidence item(s) below threshold {threshold:.2f} were filtered out"
        )

    ranked_for_paths = (supporting + conflicting + uncertain + neutral)[
        : max_paths_i * 2
    ]
    top_paths: list[dict[str, Any]] = []
    for evidence_item in ranked_for_paths:
        bundle = evidence_item.get("path")
        if not isinstance(bundle, dict):
            matched = evidence_item.get("matched_entities") or []
            bundle = _row_path_bundle(
                {
                    "publication": evidence_item.get("publication") or {},
                    "secondary_publication": evidence_item.get("secondary_publication")
                    or {},
                    "claim": evidence_item.get("claim") or {},
                    "evidence_span": evidence_item.get("evidence_span") or {},
                    "mention_props": {},
                    "typed_path_kind": (
                        (evidence_item.get("typed_path") or {}).get("kind") or ""
                    ),
                    "shared_coordinate": (
                        (evidence_item.get("typed_path") or {}).get("shared_coordinate")
                        or {}
                    ),
                    "shared_reference": (
                        (evidence_item.get("typed_path") or {}).get("shared_reference")
                        or {}
                    ),
                },
                matched_entities=matched if isinstance(matched, list) else [],
                suppress_direct_mentions=claim_only_control,
            )
        preview = _path_preview_from_bundle(bundle)
        if not preview:
            continue
        top_paths.append(
            {
                "preview": preview,
                "score": evidence_item.get("score"),
                "polarity": evidence_item.get("polarity"),
                "publication_id": (evidence_item.get("publication") or {}).get("kg_id"),
                "evidence_id": evidence_item.get("evidence_id"),
            }
        )
        if len(top_paths) >= max_paths_i:
            break

    timings["aggregation"] = round(time.perf_counter() - aggregation_started, 4)
    timings["total"] = round(time.perf_counter() - started, 3)

    return {
        "hypothesis": hypothesis,
        "normalized_claim": {
            "subject": _node_summary_payload(subject),
            "object": _node_summary_payload(obj) if obj else None,
            "predicate": _infer_hypothesis_predicate(hypothesis),
            "raw": hypothesis,
        },
        "verdict": verdict,
        "confidence": confidence,
        "strictness": strictness_norm,
        "evidence_control": evidence_control_norm,
        "candidate_lane_mode": candidate_lane_mode_norm,
        "evidence_mode": evidence_mode,
        "evidence_source_scope": evidence_source_scope,
        "summary": {
            "n_seed_entities": len(seed_entities),
            "n_candidate_publications": len(
                {pub for pub in candidate_publications if pub}
            ),
            "n_supporting": len(supporting),
            "n_conflicting": len(conflicting),
            "n_uncertain": len(uncertain),
            "n_neutral": len(neutral),
            "n_candidate_lane_supporting": candidate_lane_supporting,
            "n_candidate_lane_conflicting": candidate_lane_conflicting,
            "n_candidate_lane_uncertain": candidate_lane_uncertain,
            "n_candidate_lane_neutral": candidate_lane_neutral,
            "n_external_literature_supporting": external_literature_supporting,
            "n_external_literature_conflicting": external_literature_conflicting,
            "n_external_literature_uncertain": external_literature_uncertain,
            "n_external_literature_neutral": external_literature_neutral,
            "evidence_scope": evidence_mode,
            "evidence_source_scope": evidence_source_scope,
            "evidence_control": evidence_control_norm,
            "candidate_lane_mode": candidate_lane_mode_norm,
            "candidate_lane_filtered": candidate_lane_filtered,
            "external_literature_requested": bool(use_external_literature),
            "timings_s": dict(timings),
            "query_time_s": timings["total"],
        },
        "supporting_evidence": supporting[:max_evidence_i],
        "conflicting_evidence": conflicting[:max_evidence_i],
        "uncertain_evidence": uncertain[:max_evidence_i],
        "neutral_evidence": neutral[:max_evidence_i],
        "confidence_signals": confidence_signals,
        "top_paths": top_paths,
        "subgraph": {
            "nodes": list(subgraph_nodes.values()),
            "edges": list(subgraph_edges.values()),
        }
        if include_subgraph
        else {"nodes": [], "edges": []},
        "warnings": warnings,
        "provenance": [
            {
                "stage": "entity_resolution",
                "resolution_mode": resolution_mode,
                "search_terms": search_terms,
                "allowed_node_types": expanded_node_types,
                "raw_seed_entities": [
                    _node_summary_payload(entity) for entity in raw_seed_entities[:8]
                ],
                "seed_entities": [
                    _node_summary_payload(entity) for entity in seed_entities[:8]
                ],
                "timings_s": dict(timings),
            },
            {
                "stage": "evidence_collection",
                "strictness": strictness_norm,
                "min_evidence_score": round(threshold, 3),
                "confidence_scoring_version": scoring_version,
                "evidence_control": evidence_control_norm,
                "candidate_lane_mode": candidate_lane_mode_norm,
                "selected_entities": [
                    _node_summary_payload(entity) for entity in selected_entities
                ],
                "max_evidence": max_evidence_i,
                "use_external_literature": bool(use_external_literature),
                "external_literature_query": literature_query or None,
                "external_literature_top_k": external_literature_top_k_i,
                "external_literature_recency_days": external_literature_recency_days_i,
                "entity_expansions": entity_expansions,
                "timings_s": {
                    "direct_evidence_collection": timings["direct_evidence_collection"],
                    "typed_path_evidence_collection": timings[
                        "typed_path_evidence_collection"
                    ],
                    "family_fallback_lookup": timings["family_fallback_lookup"],
                    "family_fallback_evidence_collection": timings[
                        "family_fallback_evidence_collection"
                    ],
                    "external_literature_search": timings["external_literature_search"],
                    "aggregation": timings["aggregation"],
                    "total": timings["total"],
                },
            },
        ],
        "timings_s": dict(timings),
    }


def _normalize_traversal_mode(mode: str | None) -> tuple[str, str | None]:
    raw_mode = (mode or "breadth_first").strip().lower()
    aliases = {
        "breadth_first": "bfs",
        "bfs": "bfs",
        "depth_first": "dfs",
        "dfs": "dfs",
        "shortest_path": "shortest",
        "shortest": "shortest",
        "weighted_path": "weighted",
        "weighted": "weighted",
        "bidirectional": "bidirectional",
        "bi_directional": "bidirectional",
        "pattern_match": "pattern",
        "pattern": "pattern",
    }
    normalized = aliases.get(raw_mode)
    if normalized:
        return normalized, None
    return "bfs", f"Unsupported mode '{mode}'; using 'breadth_first'"


def _coerce_bounded_int(
    value: Any,
    *,
    default: int,
    min_value: int,
    max_value: int,
    field_name: str,
    warnings: list[str],
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        warnings.append(f"Invalid {field_name}='{value}'; using default {default}")
        return default

    if parsed < min_value:
        warnings.append(
            f"{field_name}={parsed} below {min_value}; clamped to {min_value}"
        )
        return min_value
    if parsed > max_value:
        warnings.append(
            f"{field_name}={parsed} above {max_value}; clamped to {max_value}"
        )
        return max_value
    return parsed


def _resolve_traversal_kg_id(kg_id: str, client: Neo4jGraphDB) -> str:
    if not kg_id:
        return kg_id

    if _looks_like_element_id(kg_id):
        cypher = """
        MATCH (n)
        WHERE elementId(n) = $id
        RETURN coalesce(
          n.id, n.concept_id, n.task_id, n.region_id, n.dataset_id, n.uid,
          n.identifier, elementId(n)
        ) AS resolved
        LIMIT 1
        """
        records = _as_list(client._run(cypher, {"id": kg_id}))
        if records:
            resolved = _rec_get(records[0], "resolved")
            if resolved:
                return str(resolved)

    cypher = """
    MATCH (n)
    WHERE n.id = $id
      OR n.concept_id = $id
      OR n.task_id = $id
      OR n.region_id = $id
      OR n.dataset_id = $id
      OR n.uid = $id
      OR n.identifier = $id
      OR elementId(n) = $id
    RETURN coalesce(
      n.id, n.concept_id, n.task_id, n.region_id, n.dataset_id, n.uid,
      n.identifier, elementId(n)
    ) AS resolved
    LIMIT 1
    """
    try:
        records = _as_list(client._run(cypher, {"id": kg_id}))
    except Exception:  # pragma: no cover - defensive
        records = []

    if records:
        resolved = _rec_get(records[0], "resolved")
        if resolved:
            return str(resolved)
    return kg_id


def _path_node_identifier(node: Any, *, path_index: int, node_index: int) -> str:
    if isinstance(node, dict):
        for key in (
            "id",
            "concept_id",
            "task_id",
            "region_id",
            "dataset_id",
            "uid",
            "identifier",
        ):
            val = node.get(key)
            if val:
                return str(val)
    return f"path_{path_index}_node_{node_index}"


def multi_hop_traverse(
    start_kg_ids: list[str],
    *,
    max_hops: int = 3,
    allowed_edge_types: list[str] | None = None,
    target_kg_id: str | None = None,
    mode: str = "breadth_first",
    max_results: int = 50,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    """Traverse BR-KG with the in-process MultiHopQueryEngine.

    Returns a structured payload with paths, derived subgraph, provenance, and
    warnings. This function is defensive and never raises uncaught exceptions.
    """

    warnings: list[str] = []
    start_ids = [
        str(node_id).strip()
        for node_id in (start_kg_ids or [])
        if node_id is not None and str(node_id).strip()
    ]
    start_ids = list(dict.fromkeys(start_ids))

    normalized_mode, mode_warning = _normalize_traversal_mode(mode)
    if mode_warning:
        warnings.append(mode_warning)

    max_hops_i = _coerce_bounded_int(
        max_hops,
        default=3,
        min_value=1,
        max_value=5,
        field_name="max_hops",
        warnings=warnings,
    )
    max_results_i = _coerce_bounded_int(
        max_results,
        default=50,
        min_value=1,
        max_value=500,
        field_name="max_results",
        warnings=warnings,
    )
    per_query_timeout_ms = _coerce_bounded_int(
        os.getenv("BR_KG_MULTIHOP_QUERY_TIMEOUT_MS", "12000"),
        default=12000,
        min_value=250,
        max_value=120000,
        field_name="query_timeout_ms",
        warnings=warnings,
    )
    total_budget_ms = _coerce_bounded_int(
        os.getenv("BR_KG_MULTIHOP_TOTAL_TIMEOUT_MS", "30000"),
        default=30000,
        min_value=1000,
        max_value=300000,
        field_name="total_timeout_ms",
        warnings=warnings,
    )

    normalized_edges: list[str] | None = None
    if allowed_edge_types:
        normalized_edges = [
            edge.strip()
            for edge in allowed_edge_types
            if isinstance(edge, str) and edge.strip()
        ]
        normalized_edges = list(dict.fromkeys(normalized_edges))
        if not normalized_edges:
            normalized_edges = None

    empty_result = {
        "start_kg_ids": start_ids,
        "resolved_start_kg_ids": [],
        "target_kg_id": target_kg_id,
        "resolved_target_kg_id": None,
        "mode": normalized_mode,
        "max_hops": max_hops_i,
        "max_results": max_results_i,
        "paths": [],
        "subgraph": {"nodes": [], "edges": []},
        "provenance": [],
        "statistics": {
            "total_paths_found": 0,
            "n_seed_nodes": len(start_ids),
            "n_unique_nodes": 0,
            "n_unique_edges": 0,
            "execution_time_ms": 0.0,
        },
        "warnings": warnings,
    }

    if not start_ids:
        warnings.append("No valid start_kg_ids provided")
        return empty_result

    try:
        from brain_researcher.services.neurokg.traversal.multi_hop_queries import (
            MultiHopQueryEngine,
            TraversalConstraints,
            TraversalMode,
        )
    except Exception as exc:
        warnings.append(f"Failed to import traversal engine: {exc}")
        payload = dict(empty_result)
        payload["error"] = str(exc)
        return payload

    mode_map = {
        "bfs": TraversalMode.BREADTH_FIRST,
        "dfs": TraversalMode.DEPTH_FIRST,
        "shortest": TraversalMode.SHORTEST_PATH,
        "weighted": TraversalMode.WEIGHTED_PATH,
        "bidirectional": TraversalMode.BIDIRECTIONAL,
        "pattern": TraversalMode.PATTERN_MATCH,
    }
    traversal_mode = mode_map.get(normalized_mode, TraversalMode.BREADTH_FIRST)

    try:
        client = db or get_default_db()
    except Exception as exc:
        warnings.append(f"Neo4j client initialization failed: {exc}")
        payload = dict(empty_result)
        payload["error"] = str(exc)
        return payload

    engine_db = client
    if not hasattr(client, "session"):

        class _TraversalSessionAdapter:
            def __init__(self, client_obj: Neo4jGraphDB):
                self._client_obj = client_obj

            def session(self):
                driver = getattr(self._client_obj, "_driver", None)
                if driver is None:
                    raise RuntimeError("Neo4j driver is not initialized")
                return driver.session(
                    database=getattr(self._client_obj, "_database", None)
                )

        engine_db = _TraversalSessionAdapter(client)

    engine = MultiHopQueryEngine(neo4j_db=engine_db)

    resolved_target = None
    if target_kg_id:
        try:
            resolved_target = _resolve_traversal_kg_id(target_kg_id, client)
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(f"Failed to resolve target_kg_id '{target_kg_id}': {exc}")
            resolved_target = target_kg_id

    combined_paths: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    resolved_start_ids: list[str] = []
    total_execution_ms = 0.0
    traversal_started = time.monotonic()

    for start_id in start_ids:
        elapsed_ms = (time.monotonic() - traversal_started) * 1000.0
        if elapsed_ms >= float(total_budget_ms):
            warnings.append(
                "Traversal budget exhausted at "
                f"{elapsed_ms:.1f}ms (limit={total_budget_ms}ms); returning partial results"
            )
            break

        if len(combined_paths) >= max_results_i:
            break

        try:
            resolved_start = _resolve_traversal_kg_id(start_id, client)
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(f"Failed to resolve start_kg_id '{start_id}': {exc}")
            resolved_start = start_id

        if resolved_start != start_id:
            warnings.append(
                f"Resolved start_kg_id '{start_id}' to '{resolved_start}' for traversal"
            )
        resolved_start_ids.append(resolved_start)

        constraints = TraversalConstraints(
            max_depth=max_hops_i,
            max_results=max(1, max_results_i - len(combined_paths)),
            allowed_edge_types=set(normalized_edges) if normalized_edges else None,
            query_timeout_ms=min(
                per_query_timeout_ms,
                max(250, int(total_budget_ms - elapsed_ms)),
            ),
        )

        try:
            traversal_result = engine.traverse_from_node(
                start_node_id=resolved_start,
                constraints=constraints,
                mode=traversal_mode,
                target_node_id=resolved_target,
            )
        except Exception as exc:
            warnings.append(f"Traversal failed for start_kg_id '{start_id}': {exc}")
            continue

        total_execution_ms += float(
            getattr(traversal_result, "execution_time_ms", 0.0) or 0.0
        )
        provenance.append(
            {
                "start_kg_id": start_id,
                "resolved_start_kg_id": resolved_start,
                "target_kg_id": target_kg_id,
                "resolved_target_kg_id": resolved_target,
                "query_id": getattr(traversal_result, "query_id", None),
                "execution_time_ms": getattr(
                    traversal_result, "execution_time_ms", None
                ),
                "paths_found": getattr(traversal_result, "total_paths_found", 0),
                "mode": traversal_mode.value,
                "statistics": getattr(traversal_result, "statistics", {}) or {},
            }
        )

        for path in getattr(traversal_result, "paths", []) or []:
            try:
                path_dict = path.to_dict() if hasattr(path, "to_dict") else dict(path)
            except Exception:
                continue
            path_dict["start_kg_id"] = start_id
            path_dict["resolved_start_kg_id"] = resolved_start
            combined_paths.append(path_dict)
            if len(combined_paths) >= max_results_i:
                break

    subgraph_nodes: dict[str, dict[str, Any]] = {}
    subgraph_edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str, str]] = set()

    for path_index, path in enumerate(combined_paths):
        path_nodes = path.get("nodes") or []
        path_edges = path.get("edges") or []
        node_ids: list[str] = []

        for node_index, node in enumerate(path_nodes):
            node_dict = dict(node) if isinstance(node, dict) else {}
            node_id = _path_node_identifier(
                node_dict, path_index=path_index, node_index=node_index
            )
            node_ids.append(node_id)
            if node_id not in subgraph_nodes:
                node_payload = dict(node_dict)
                node_payload.setdefault("kg_id", node_id)
                if "label" not in node_payload and node_payload.get("name"):
                    node_payload["label"] = node_payload.get("name")
                subgraph_nodes[node_id] = node_payload

        for edge_index, edge in enumerate(path_edges):
            if edge_index + 1 >= len(node_ids):
                continue
            edge_dict = dict(edge) if isinstance(edge, dict) else {}
            source_id = node_ids[edge_index]
            target_id_local = node_ids[edge_index + 1]
            edge_type = str(
                edge_dict.get("type")
                or edge_dict.get("relation")
                or edge_dict.get("rel")
                or edge_dict.get("label")
                or "RELATED_TO"
            )
            edge_sig = (
                source_id,
                target_id_local,
                edge_type,
                json.dumps(edge_dict, sort_keys=True, default=str),
            )
            if edge_sig in seen_edges:
                continue
            seen_edges.add(edge_sig)
            subgraph_edges.append(
                {
                    "source": source_id,
                    "target": target_id_local,
                    "type": edge_type,
                    "properties": edge_dict,
                }
            )

    return {
        "start_kg_ids": start_ids,
        "resolved_start_kg_ids": resolved_start_ids,
        "target_kg_id": target_kg_id,
        "resolved_target_kg_id": resolved_target,
        "mode": traversal_mode.value,
        "max_hops": max_hops_i,
        "max_results": max_results_i,
        "paths": combined_paths,
        "subgraph": {
            "nodes": list(subgraph_nodes.values()),
            "edges": subgraph_edges,
        },
        "provenance": provenance,
        "statistics": {
            "total_paths_found": len(combined_paths),
            "n_seed_nodes": len(start_ids),
            "n_unique_nodes": len(subgraph_nodes),
            "n_unique_edges": len(subgraph_edges),
            "execution_time_ms": total_execution_ms,
        },
        "warnings": warnings,
    }


def _normalize_taste_scoring(
    taste: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize taste-scoring configuration with novelty-first defaults."""
    raw = taste if isinstance(taste, dict) else {}
    mode = (
        str(raw.get("mode") or raw.get("strategy") or "novelty_first").strip().lower()
    )

    defaults_by_mode: dict[str, dict[str, float]] = {
        "novelty_first": {"novelty": 0.7, "contradiction": 0.2, "evidence": 0.1},
        "balanced": {"novelty": 0.4, "contradiction": 0.3, "evidence": 0.3},
        "evidence_first": {"novelty": 0.2, "contradiction": 0.2, "evidence": 0.6},
    }
    if mode not in defaults_by_mode:
        mode = "novelty_first"

    weights = dict(defaults_by_mode[mode])
    raw_weights = raw.get("weights")
    if isinstance(raw_weights, dict):
        for key in ("novelty", "contradiction", "evidence"):
            if key in raw_weights:
                weights[key] = max(0.0, _safe_float(raw_weights.get(key), weights[key]))

    total = sum(weights.values())
    if total <= 0:
        weights = dict(defaults_by_mode["novelty_first"])
        total = sum(weights.values())
    normalized_weights = {
        key: round(float(value) / float(total), 6) for key, value in weights.items()
    }

    max_candidates = int(
        _coerce_bounded_int(
            raw.get("max_candidates", raw.get("limit", 50)),
            default=50,
            min_value=1,
            max_value=500,
            field_name="taste.max_candidates",
            warnings=[],
        )
    )
    return {
        "mode": mode,
        "weights": normalized_weights,
        "max_candidates": max_candidates,
    }


def _stable_taste_patch_id(
    *,
    seed_kg_ids: list[str],
    reason: str,
    scoring: dict[str, Any],
) -> str:
    payload = {
        "seed_kg_ids": sorted(seed_kg_ids),
        "reason": str(reason or "").strip().lower(),
        "scoring": scoring,
    }
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]
    return f"taste_patch_{digest}"


def _clean_seed_ids(seed_kg_ids: Sequence[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in seed_kg_ids or []:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    return cleaned


_OOD_EMITTABLE_NODE_TYPES = {
    "BrainRegion",
    "CognitiveConcept",
    "Concept",
    "Dataset",
    "DiseaseTrait",
    "Gene",
    "Method",
    "OntologyConcept",
    "RiskLocus",
    "Task",
    "TaskFamily",
}
_OOD_EXPAND_ONLY_NODE_TYPES = {
    "Collection",
    "Coordinate",
    "Modality",
    "Paper",
    "Population",
    "Publication",
    "Software",
    "Study",
    "Term",
    "Tool",
}
_OOD_HYPOTHESIS_OUTPUT_NODE_TYPES = {
    "BrainRegion",
    "Concept",
    "Dataset",
    "DiseaseTrait",
    "Gene",
    "Method",
    "Task",
    "TaskFamily",
}
_OOD_RELATION_BLACKLIST = {
    "BELONGS_TO",
    "CLASSIFIED_UNDER",
    "HAS_COORDINATE",
    "HAS_MODALITY",
    "HAS_IMAGE_EMBEDDING",
    "HOSTED_AT",
    "HAS_TERM",
    "HAS_TEXT_EMBEDDING",
    "INVOLVES_SPECIES",
}
_OOD_RELATION_PREFERRED = {
    "ABOUT",
    "ASSOCIATED_WITH",
    "BELONGS_TO_FAMILY",
    "HAS_LEAD_LOCUS",
    "HAS_POPULATION",
    "HAS_TASK",
    "IMPLICATES_GENE",
    "IMPLEMENTS_FAMILY",
    "IN_ONVOC",
    "MAPS_TO",
    "MEASURES",
    "RELATED_TO",
    "STUDIES",
    "SUPPORTS_MODALITY",
    "USES_TASK",
}
_OOD_GENERIC_LABEL_BLACKLIST = {
    "analysis",
    "article",
    "better",
    "brain",
    "contains",
    "contain",
    "cue",
    "decoding",
    "effect",
    "evidence",
    "experiment",
    "extracted",
    "finding",
    "humans",
    "paper",
    "results",
    "signal",
    "study",
}
_OOD_DIRECT_PRIOR_ART_MARKERS = (
    "decode",
    "decoding",
    "decoder",
    "classification",
    "classifier",
    "predict",
    "prediction",
    "represent",
    "representation",
    "transfer",
    "generalize",
    "generalization",
)
_OOD_CONTRADICTION_MARKERS = (
    "no evidence",
    "not associated",
    "did not",
    "failed to",
    "null result",
    "unable to",
    "inconsistent",
    "contradict",
)
_OOD_CONFOUND_MARKERS = (
    "artifact",
    "artifactual",
    "confound",
    "confounded",
    "measurement noise",
    "head motion",
    "motion artifact",
    "vascular",
    "physiological noise",
    "nuisance",
)
_OOD_NEURO_CONTEXT_MARKERS = (
    "brain",
    "fmri",
    "bold",
    "neural",
    "neuroscience",
    "cortex",
    "hippocampus",
    "decoding",
    "representation",
    "task",
)


def _coalesce_node_label(
    label: Any = None,
    name: Any = None,
    title: Any = None,
    fallback: Any = None,
) -> str:
    for value in (label, name, title, fallback):
        text = str(value or "").strip()
        if text:
            return text
    return ""


@functools.lru_cache(maxsize=1)
def _load_ood_stopwords() -> set[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "study",
        "task",
        "test",
        "the",
        "to",
        "with",
    }
    config_path = (
        Path(__file__).resolve().parents[4]
        / "configs"
        / "neurokg"
        / "string_normalization.yaml"
    )
    try:
        import yaml  # type: ignore

        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        raw_stopwords = payload.get("stopwords") or {}
        for key in ("generic", "task_names", "publication_titles"):
            values = raw_stopwords.get(key) or []
            for value in values:
                text = str(value or "").strip().lower()
                if text:
                    stopwords.add(text)
    except Exception:  # pragma: no cover - best effort
        pass
    return stopwords


def _tokenize_ood_label(text: str) -> list[str]:
    stopwords = _load_ood_stopwords()
    tokens = [
        token
        for token in re.split(r"[^A-Za-z0-9]+", str(text or "").lower())
        if len(token) >= 3
    ]
    return [token for token in tokens if token not in stopwords]


def _canonical_ood_node_type(node_type: str | None) -> str:
    normalized = str(node_type or "").strip()
    if not normalized:
        return "Node"
    aliases = {
        "CognitiveConcept": "Concept",
        "OntologyConcept": "Concept",
        "Parcel": "BrainRegion",
        "Region": "BrainRegion",
        "Software": "Tool",
    }
    return aliases.get(normalized, normalized)


def _is_semantic_ood_node_type(node_type: str | None) -> bool:
    return _canonical_ood_node_type(node_type) in {
        _canonical_ood_node_type(value) for value in _OOD_EMITTABLE_NODE_TYPES
    }


def _looks_like_noise_candidate(
    label: str, *, node_type: str | None
) -> tuple[bool, str]:
    normalized_label = str(label or "").strip()
    if not normalized_label:
        return True, "blank_label"
    if _looks_like_element_id(normalized_label):
        return True, "opaque_identifier"
    if normalized_label.lower() in _OOD_GENERIC_LABEL_BLACKLIST:
        return True, "generic_label"
    tokens = _tokenize_ood_label(normalized_label)
    if not tokens:
        return True, "generic_label"
    if (
        _canonical_ood_node_type(node_type) == "Concept"
        and len(tokens) == 1
        and tokens[0] in _OOD_GENERIC_LABEL_BLACKLIST
    ):
        return True, "generic_label"
    return False, ""


def _label_quality_score(label: str, *, node_type: str | None) -> float:
    tokens = _tokenize_ood_label(label)
    canonical_type = _canonical_ood_node_type(node_type)
    token_score = min(1.0, len(tokens) / 4.0)
    multiword_bonus = 0.15 if len(tokens) >= 2 else 0.0
    type_bonus = {
        "Task": 0.25,
        "Concept": 0.22,
        "BrainRegion": 0.20,
        "Dataset": 0.16,
        "Tool": 0.14,
        "Method": 0.14,
    }.get(canonical_type, 0.05)
    return _clip01(0.25 + 0.35 * token_score + multiword_bonus + type_bonus)


def _relation_quality_score(relations: Sequence[str]) -> float:
    rels = [
        str(rel or "").strip().upper() for rel in relations if str(rel or "").strip()
    ]
    if not rels:
        return 0.35
    if all(rel in _OOD_RELATION_BLACKLIST for rel in rels):
        return 0.0
    preferred_hits = sum(1 for rel in rels if rel in _OOD_RELATION_PREFERRED)
    blacklisted_hits = sum(1 for rel in rels if rel in _OOD_RELATION_BLACKLIST)
    base = 0.45 + 0.18 * preferred_hits - 0.12 * blacklisted_hits
    return _clip01(base)


def _resolve_semantic_seed_context(
    seed_kg_ids: Sequence[str] | None,
    *,
    db: Optional[Neo4jGraphDB] = None,
    relation_types: Sequence[str] | None = None,
    neighbor_limit: int = 20,
) -> dict[str, Any]:
    client = db or get_default_db()
    input_seed_ids = _clean_seed_ids(seed_kg_ids)
    semantic_seed_ids: list[str] = []
    semantic_seed_labels: dict[str, str] = {}
    semantic_seed_types: dict[str, str] = {}
    semantic_seed_scores: dict[str, float] = {}
    seed_provenance: dict[str, list[str]] = {}
    seed_input_details: dict[str, tuple[str, str]] = {}
    warnings: list[str] = []
    seen: set[str] = set()
    rel_filter = list(relation_types) if relation_types else None

    def _add_seed(
        seed_id: str,
        label: str,
        node_type: str,
        provenance: str,
        score: float = 1.0,
    ) -> None:
        normalized_id = str(seed_id or "").strip()
        if not normalized_id:
            return
        key = normalized_id.lower()
        if key not in seen:
            seen.add(key)
            semantic_seed_ids.append(normalized_id)
        semantic_seed_labels[normalized_id] = label
        semantic_seed_types[normalized_id] = node_type
        semantic_seed_scores[normalized_id] = max(
            _safe_float(score, 0.0),
            _safe_float(semantic_seed_scores.get(normalized_id), 0.0),
        )
        seed_provenance.setdefault(normalized_id, [])
        if provenance not in seed_provenance[normalized_id]:
            seed_provenance[normalized_id].append(provenance)

    for raw_seed in input_seed_ids:
        detail = node_details(raw_seed, db=client, include_neighbors=False)
        if detail is None:
            warnings.append(f"Seed normalization could not resolve '{raw_seed}'")
            continue

        canonical_seed_id = str(detail.kg_id or raw_seed).strip() or raw_seed
        detail_label = _coalesce_node_label(
            detail.label,
            (detail.properties or {}).get("name") if detail.properties else None,
            (detail.properties or {}).get("title") if detail.properties else None,
            canonical_seed_id,
        )
        detail_type = str(detail.node_type or "Node")
        seed_input_details[raw_seed] = (detail_label, detail_type)

        if _is_semantic_ood_node_type(detail_type):
            rejected, reason = _looks_like_noise_candidate(
                detail_label,
                node_type=detail_type,
            )
            if not rejected:
                _add_seed(
                    canonical_seed_id,
                    detail_label,
                    detail_type,
                    "direct",
                    score=_safe_float(detail.score, 1.0),
                )

        should_expand = (
            detail_type in _OOD_EXPAND_ONLY_NODE_TYPES
            or detail_type == "Dataset"
            or not _is_semantic_ood_node_type(detail_type)
        )

        neighbor_rows: list[dict[str, Any]] = []
        neighbor_additions = 0
        if should_expand:
            lookup_ids = [canonical_seed_id]
            if canonical_seed_id.lower() != raw_seed.lower():
                lookup_ids.append(raw_seed)
            for lookup_id in lookup_ids:
                try:
                    neighbor_rows = neighbors(
                        lookup_id,
                        relation_types=rel_filter,
                        direction="both",
                        limit=neighbor_limit,
                        db=client,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    warnings.append(
                        f"Seed normalization neighbor lookup failed for '{lookup_id}': {exc}"
                    )
                    continue
                if neighbor_rows:
                    break

            for row in neighbor_rows:
                candidate_id = str(row.get("kg_id") or "").strip()
                candidate_type = str(row.get("node_type") or "Node")
                if not candidate_id or not _is_semantic_ood_node_type(candidate_type):
                    continue
                relation = str(row.get("relation") or "").strip().upper()
                if relation in _OOD_RELATION_BLACKLIST:
                    continue
                props = row.get("properties") or {}
                candidate_label = _coalesce_node_label(
                    row.get("label"),
                    props.get("name") if isinstance(props, dict) else None,
                    props.get("title") if isinstance(props, dict) else None,
                    candidate_id,
                )
                rejected, _ = _looks_like_noise_candidate(
                    candidate_label,
                    node_type=candidate_type,
                )
                if rejected:
                    continue
                provenance = f"expanded_from:{raw_seed}:{relation or 'neighbor'}"
                _add_seed(
                    candidate_id,
                    candidate_label,
                    candidate_type,
                    provenance,
                    score=_safe_float(row.get("score"), 0.75),
                )
                neighbor_additions += 1

        should_search_expand = neighbor_additions == 0
        if should_search_expand and detail_label:
            focus_terms = _ood_focus_terms(detail_label, limit=4)
            search_queries: list[str] = []
            if focus_terms:
                search_queries.append(" ".join(focus_terms[:4]))
                if len(focus_terms) >= 2:
                    search_queries.append(" ".join(focus_terms[:2]))
            elif len(detail_label.split()) <= 8:
                search_queries.append(detail_label)
            for query in list(dict.fromkeys(search_queries)):
                if not query:
                    continue
                try:
                    hits = search_nodes(
                        query,
                        node_types=sorted(_OOD_HYPOTHESIS_OUTPUT_NODE_TYPES),
                        limit=6,
                        db=client,
                        infer_types=False,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    warnings.append(
                        f"Seed normalization semantic search failed for '{raw_seed}': {exc}"
                    )
                    continue
                for hit in hits:
                    candidate_id = str(hit.kg_id or "").strip()
                    candidate_type = str(hit.node_type or "Node")
                    if not candidate_id or not _is_output_ood_node_type(candidate_type):
                        continue
                    candidate_label = _coalesce_node_label(
                        hit.label,
                        (hit.properties or {}).get("name") if hit.properties else None,
                        (hit.properties or {}).get("title") if hit.properties else None,
                        candidate_id,
                    )
                    rejected, _ = _looks_like_noise_candidate(
                        candidate_label,
                        node_type=candidate_type,
                    )
                    if rejected:
                        continue
                    if candidate_id.lower() == canonical_seed_id.lower():
                        continue
                    allowed, _ = _search_expanded_exact_anchor_ok(
                        raw_seed_id=raw_seed,
                        raw_seed_label=detail_label,
                        raw_seed_type=detail_type,
                        candidate_id=candidate_id,
                        candidate_label=candidate_label,
                        candidate_type=candidate_type,
                        focus_terms=focus_terms,
                    )
                    if not allowed:
                        continue
                    provenance = f"search_expanded_from:{raw_seed}"
                    _add_seed(
                        candidate_id,
                        candidate_label,
                        candidate_type,
                        provenance,
                        score=_safe_float(hit.score, 0.55),
                    )

    domain_tokens: set[str] = set()
    for label in semantic_seed_labels.values():
        domain_tokens.update(_tokenize_ood_label(label))

    if not semantic_seed_ids and input_seed_ids:
        warnings.append(
            "No semantic seed anchors found; falling back to input seed IDs with low confidence."
        )
        for raw_seed in input_seed_ids:
            if raw_seed not in semantic_seed_labels:
                detail_label, detail_type = seed_input_details.get(
                    raw_seed, (raw_seed, "Node")
                )
                semantic_seed_labels[raw_seed] = detail_label or raw_seed
                semantic_seed_types[raw_seed] = detail_type or "Node"
                seed_provenance.setdefault(raw_seed, ["fallback"])
        semantic_seed_ids = list(input_seed_ids)

    return {
        "input_seed_kg_ids": input_seed_ids,
        "seed_kg_ids": semantic_seed_ids,
        "semantic_seed_labels": semantic_seed_labels,
        "semantic_seed_types": semantic_seed_types,
        "semantic_seed_scores": semantic_seed_scores,
        "seed_provenance": seed_provenance,
        "domain_tokens": sorted(domain_tokens),
        "warnings": warnings,
    }


def _search_expanded_exact_anchor_ok(
    *,
    raw_seed_id: str,
    raw_seed_label: str,
    raw_seed_type: str,
    candidate_id: str,
    candidate_label: str,
    candidate_type: str,
    focus_terms: Sequence[str],
) -> tuple[bool, str]:
    del raw_seed_id, raw_seed_label
    canonical_seed_type = _canonical_ood_node_type(raw_seed_type)
    canonical_candidate_type = _canonical_ood_node_type(candidate_type)

    if _looks_like_element_id(candidate_id):
        return False, "opaque_candidate_id"

    if canonical_candidate_type == "Dataset" and canonical_seed_type != "Dataset":
        return False, "dataset_search_expansion_rejected"

    candidate_tokens = set(_tokenize_ood_label(candidate_label))
    focus_token_set = {
        str(token or "").strip().lower()
        for token in focus_terms
        if str(token or "").strip()
    }
    if focus_token_set and not candidate_tokens.intersection(focus_token_set):
        return False, "focus_overlap_missing"

    return True, ""


def _select_traversal_seeds(
    seeds: Sequence[str],
    *,
    input_seed_ids: Sequence[str],
    seed_scores: dict[str, Any],
    seed_provenance: dict[str, list[str]],
    max_traversal_seeds: int,
) -> list[str]:
    """Prefer direct semantic seeds while bounding repeated neighbor traversals."""

    input_seed_set = {str(seed or "").strip().lower() for seed in input_seed_ids}
    ranked: list[tuple[tuple[int, float, str], str]] = []
    for seed in seeds:
        seed_id = str(seed or "").strip()
        if not seed_id:
            continue
        provenance_entries = [
            str(item or "") for item in seed_provenance.get(seed_id) or []
        ]
        if any(
            entry.startswith("search_expanded_from:") for entry in provenance_entries
        ):
            continue
        priority = 2
        if seed_id.lower() in input_seed_set:
            priority = 0
        elif any(entry == "direct" for entry in provenance_entries):
            priority = 1
        ranked.append(
            (
                (
                    priority,
                    -_safe_float(seed_scores.get(seed_id), 0.0),
                    seed_id,
                ),
                seed_id,
            )
        )

    ordered = [seed_id for _, seed_id in sorted(ranked)]
    if max_traversal_seeds <= 0:
        return ordered
    return ordered[:max_traversal_seeds]


def _candidate_quality_assessment(
    *,
    kg_id: str,
    label: str,
    node_type: str,
    relations: Sequence[str],
    seed_domain_tokens: Sequence[str],
) -> dict[str, Any]:
    reasons: list[str] = []
    canonical_type = _canonical_ood_node_type(node_type)

    if not _is_semantic_ood_node_type(canonical_type):
        reasons.append("node_type_filtered")

    rejected, reject_reason = _looks_like_noise_candidate(
        label, node_type=canonical_type
    )
    if rejected:
        reasons.append(reject_reason)

    relation_quality = _relation_quality_score(relations)
    if relation_quality <= 0.0:
        reasons.append("relation_filtered")

    label_tokens = _tokenize_ood_label(label)
    seed_tokens = {
        str(token or "").strip().lower()
        for token in seed_domain_tokens
        if str(token or "").strip()
    }
    overlap = seed_tokens.intersection(label_tokens)
    domain_overlap = (
        float(len(overlap)) / float(max(1, len(label_tokens))) if label_tokens else 0.0
    )
    label_quality = _label_quality_score(label, node_type=canonical_type)

    return {
        "ok": not reasons,
        "reasons": reasons,
        "quality_flags": sorted(
            set(
                [
                    f"type:{canonical_type}",
                    *(
                        f"rel:{str(rel).strip().upper()}"
                        for rel in relations
                        if str(rel).strip()
                    ),
                    *(f"token:{token}" for token in sorted(overlap)[:3]),
                ]
            )
        ),
        "candidate_type": canonical_type,
        "label_quality": round(label_quality, 6),
        "relation_quality": round(relation_quality, 6),
        "domain_overlap": round(_clip01(domain_overlap), 6),
        "label_tokens": label_tokens,
    }


def _is_output_ood_node_type(node_type: str | None) -> bool:
    return _canonical_ood_node_type(node_type) in {
        _canonical_ood_node_type(value) for value in _OOD_HYPOTHESIS_OUTPUT_NODE_TYPES
    }


def _ood_focus_terms(label: str, *, limit: int = 3) -> list[str]:
    tokens = _tokenize_ood_label(label)
    if not tokens:
        return []
    ranked = sorted(set(tokens), key=lambda token: (-len(token), token))
    return ranked[:limit]


def _ood_compact_label(label: str, *, max_words: int = 8) -> str:
    text = re.sub(r"\s+", " ", str(label or "").strip())
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(" ,;:") + "..."


_OOD_DUPLICATE_LABEL_TOKENS = {
    "candidate",
    "candidates",
    "task",
    "tasks",
    "test",
    "tests",
    "scale",
    "scales",
    "battery",
    "inventory",
    "questionnaire",
    "questionnaires",
    "measure",
    "measures",
    "assessment",
    "assessments",
}


def _ood_candidate_family_tokens(label: str) -> set[str]:
    return {
        token
        for token in _tokenize_ood_label(label)
        if token not in _OOD_DUPLICATE_LABEL_TOKENS
    }


def _ood_labels_are_near_duplicates(label_a: str, label_b: str) -> bool:
    compact_a = _ood_compact_label(label_a, max_words=12).lower()
    compact_b = _ood_compact_label(label_b, max_words=12).lower()
    if compact_a and compact_b and compact_a == compact_b:
        return True
    if compact_a and compact_b and (compact_a in compact_b or compact_b in compact_a):
        return True

    tokens_a = _ood_candidate_family_tokens(label_a)
    tokens_b = _ood_candidate_family_tokens(label_b)
    if not tokens_a or not tokens_b:
        return False

    shared = tokens_a.intersection(tokens_b)
    if not shared:
        return False
    overlap = float(len(shared)) / float(max(1, min(len(tokens_a), len(tokens_b))))
    if overlap >= 0.75:
        return True
    return len(shared) >= 4 and min(len(tokens_a), len(tokens_b)) >= 4


def _collapse_ood_candidate_clusters(
    leverage_rows: Sequence[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    collapsed: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []

    for raw_item in leverage_rows or []:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        candidate_label = str(item.get("label") or item.get("kg_id") or "").strip()
        candidate_type = _canonical_ood_node_type(
            item.get("candidate_type") or item.get("node_type")
        )
        matched_representative: dict[str, Any] | None = None
        for representative in collapsed:
            representative_type = _canonical_ood_node_type(
                representative.get("candidate_type") or representative.get("node_type")
            )
            if representative_type != candidate_type:
                continue
            if _ood_labels_are_near_duplicates(
                candidate_label,
                str(
                    representative.get("label") or representative.get("kg_id") or ""
                ).strip(),
            ):
                matched_representative = representative
                break

        if matched_representative is None:
            item.setdefault("collapsed_candidate_ids", [])
            item.setdefault("collapsed_candidate_labels", [])
            collapsed.append(item)
            continue

        matched_representative.setdefault("collapsed_candidate_ids", []).append(
            str(item.get("kg_id") or "").strip()
        )
        matched_representative.setdefault("collapsed_candidate_labels", []).append(
            candidate_label
        )
        duplicates.append(
            {
                "item": item,
                "representative_kg_id": str(
                    matched_representative.get("kg_id") or ""
                ).strip(),
                "representative_label": str(
                    matched_representative.get("label")
                    or matched_representative.get("kg_id")
                    or ""
                ).strip(),
            }
        )

    return collapsed, duplicates


def _infer_ood_claim_type(
    *,
    anchor_type: str,
    candidate_type: str,
    relation_hint: str,
    candidate_label: str,
) -> str:
    canonical_anchor = _canonical_ood_node_type(anchor_type)
    canonical_candidate = _canonical_ood_node_type(candidate_type)
    relation = str(relation_hint or "").strip().upper()
    candidate_tokens = set(_tokenize_ood_label(candidate_label))

    if candidate_tokens.intersection({"artifact", "motion", "noise", "confound"}):
        return "confound"
    if canonical_candidate == "BrainRegion":
        return "mechanism"
    if canonical_candidate in {"Task", "TaskFamily", "Dataset"}:
        return "transfer"
    if relation in {"ABOUT", "IN_ONVOC", "RELATED_TO", "ASSOCIATED_WITH"}:
        if canonical_anchor == "Publication":
            return "contradiction_resolution"
        return "bridge"
    if canonical_candidate == "Method":
        return "confound"
    return "bridge"


_OOD_GENERIC_MECHANISM_PATTERNS = (
    "shared latent mechanism",
    "partially shared latent mechanism",
    "shared latent representation",
    "shared task-family demand profile",
    "overlapping task structure",
    "shared ontology-level construct",
    "shared conceptual factor",
)

_OOD_GENERIC_PREDICTED_DIRECTION_PATTERNS = (
    "above matched controls",
    "above matched control",
    "generalize above matched controls",
    "transfer above matched controls",
)

_OOD_IV_CUE_TERMS = (
    "versus",
    "relative to",
    "holding",
    "controlling",
    "isolating",
    "removing",
    "stratifying",
    "training on",
    "testing on",
    "applying",
    "comparing",
)

_OOD_CONTROL_CUE_TERMS = ("control", "baseline", "matched", "shuffled", "comparator")

_OOD_DV_CUE_TERMS = (
    "accuracy",
    "activation",
    "behavior",
    "consistency",
    "connectivity",
    "decoding",
    "effect",
    "metric",
    "performance",
    "signal",
)

_OOD_ABSTRACT_FAMILY_TYPES = frozenset({"TaskFamily"})
_OOD_WEAK_VARIANT_TOKENS = frozenset(
    {
        "activation",
        "analysis",
        "contrast",
        "decoding",
        "effect",
        "fmri",
        "paradigm",
        "real",
        "response",
        "signal",
        "study",
        "test",
        "time",
    }
)


def _ood_normalize_clause(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).rstrip(" .")


def _compose_ood_hypothesis_sentence(
    *,
    mechanism: str,
    independent_variable: str,
    control_condition: str,
    dependent_variable: str,
    predicted_direction: str,
) -> str:
    mechanism_clause = _ood_normalize_clause(mechanism)
    iv_clause = _ood_normalize_clause(independent_variable)
    control_clause = _ood_normalize_clause(control_condition)
    dv_clause = _ood_normalize_clause(dependent_variable)
    direction_clause = _ood_normalize_clause(predicted_direction)
    if not all(
        (
            mechanism_clause,
            iv_clause,
            control_clause,
            dv_clause,
            direction_clause,
        )
    ):
        return ""
    return (
        f"If {mechanism_clause}, then when {iv_clause} is manipulated relative to "
        f"{control_clause}, {dv_clause} {direction_clause}."
    )


def _coerce_ood_candidate_draft(draft: Mapping[str, Any]) -> dict[str, str]:
    normalized = {
        str(key): " ".join(str(value or "").strip().split())
        for key, value in dict(draft).items()
    }
    hypothesis_sentence = str(
        normalized.get("hypothesis_sentence") or normalized.get("statement") or ""
    ).strip()
    predicted_direction = str(
        normalized.get("predicted_direction") or normalized.get("prediction") or ""
    ).strip()
    if not hypothesis_sentence:
        hypothesis_sentence = _compose_ood_hypothesis_sentence(
            mechanism=normalized.get("mechanism", ""),
            independent_variable=normalized.get("independent_variable", ""),
            control_condition=normalized.get("control_condition", ""),
            dependent_variable=normalized.get("dependent_variable", ""),
            predicted_direction=predicted_direction,
        )
    if not predicted_direction:
        predicted_direction = _ood_normalize_clause(normalized.get("prediction"))
    normalized["hypothesis_sentence"] = hypothesis_sentence
    normalized["statement"] = hypothesis_sentence or " ".join(
        str(normalized.get("statement") or "").strip().split()
    )
    normalized["predicted_direction"] = predicted_direction
    normalized["prediction"] = predicted_direction or " ".join(
        str(normalized.get("prediction") or "").strip().split()
    )
    return {key: str(value) for key, value in normalized.items()}


def _ood_family_overlap_stats(
    anchor_label: str,
    candidate_label: str,
) -> tuple[set[str], set[str], set[str], float]:
    anchor_tokens = _ood_candidate_family_tokens(anchor_label)
    candidate_tokens = _ood_candidate_family_tokens(candidate_label)
    if not anchor_tokens or not candidate_tokens:
        return anchor_tokens, candidate_tokens, set(), 0.0
    shared = anchor_tokens.intersection(candidate_tokens)
    overlap = float(len(shared)) / float(
        max(1, min(len(anchor_tokens), len(candidate_tokens)))
    )
    return anchor_tokens, candidate_tokens, shared, overlap


def _ood_distinctive_candidate_tokens(
    anchor_label: str,
    candidate_label: str,
) -> set[str]:
    anchor_tokens, candidate_tokens, _, _ = _ood_family_overlap_stats(
        anchor_label,
        candidate_label,
    )
    return {
        token
        for token in candidate_tokens.difference(anchor_tokens)
        if token not in _OOD_WEAK_VARIANT_TOKENS
    }


def _triage_ood_candidate_semantics(
    *,
    anchor_id: str,
    candidate_id: str,
    anchor_label: str,
    candidate_label: str,
    anchor_type: str | None,
    candidate_type: str | None,
    claim_type: str,
    mechanism: str,
) -> dict[str, Any]:
    canonical_anchor_type = _canonical_ood_node_type(anchor_type)
    canonical_candidate_type = _canonical_ood_node_type(candidate_type)
    _, _, shared_family_tokens, family_overlap = _ood_family_overlap_stats(
        anchor_label,
        candidate_label,
    )
    distinctive_tokens = _ood_distinctive_candidate_tokens(
        anchor_label,
        candidate_label,
    )
    mechanism_text = str(mechanism or "").strip().lower()
    generic_same_family_mechanism = (
        any(pattern in mechanism_text for pattern in _OOD_GENERIC_MECHANISM_PATTERNS)
        or "representation-carrying bottleneck" in mechanism_text
    )
    same_node = (
        bool(anchor_id)
        and bool(candidate_id)
        and str(anchor_id).strip().lower() == str(candidate_id).strip().lower()
    )

    if same_node:
        return {
            "decision": "kill",
            "reasons": ["self_anchor_echo"],
            "penalty": 1.0,
        }
    if claim_type == "transfer" and canonical_candidate_type in _OOD_ABSTRACT_FAMILY_TYPES:
        return {
            "decision": "kill",
            "reasons": ["abstract_family_substitution"],
            "penalty": 1.0,
        }
    if canonical_candidate_type == "Concept" and _ood_labels_are_near_duplicates(
        anchor_label,
        candidate_label,
    ):
        return {
            "decision": "kill",
            "reasons": ["abstract_anchor_echo"],
            "penalty": 1.0,
        }
    if (
        canonical_anchor_type == canonical_candidate_type
        and _ood_labels_are_near_duplicates(anchor_label, candidate_label)
        and not distinctive_tokens
    ):
        return {
            "decision": "kill",
            "reasons": ["self_anchor_echo"],
            "penalty": 1.0,
        }
    if (
        claim_type == "transfer"
        and len(shared_family_tokens) >= 2
        and family_overlap >= 0.66
    ):
        if distinctive_tokens:
            return {
                "decision": "downrank",
                "reasons": ["same_family_variant"],
                "penalty": 0.18,
            }
        if generic_same_family_mechanism:
            return {
                "decision": "kill",
                "reasons": ["same_family_near_duplicate"],
                "penalty": 1.0,
            }
        return {
            "decision": "downrank",
            "reasons": ["same_family_variant"],
            "penalty": 0.12,
        }
    if (
        canonical_anchor_type in {"BrainRegion", "Concept"}
        and canonical_candidate_type == "Task"
        and shared_family_tokens
        and not distinctive_tokens
    ):
        return {
            "decision": "downrank",
            "reasons": ["anchor_labeled_variant"],
            "penalty": 0.12,
        }
    return {"decision": "pass", "reasons": [], "penalty": 0.0}


def _assess_ood_hypothesis_draft(
    draft: dict[str, Any],
    *,
    anchor_label: str,
    candidate_label: str,
) -> tuple[bool, list[str]]:
    draft = _coerce_ood_candidate_draft(draft)
    reasons: list[str] = []
    required_fields = (
        "claim_type",
        "statement",
        "hypothesis_sentence",
        "mechanism",
        "independent_variable",
        "dependent_variable",
        "control_condition",
        "predicted_direction",
        "prediction",
        "minimal_test",
        "falsifier",
    )
    for field_name in required_fields:
        if not str(draft.get(field_name) or "").strip():
            reasons.append(f"missing_{field_name}")

    statement = str(draft.get("statement") or "").strip().lower()
    hypothesis_sentence = str(draft.get("hypothesis_sentence") or "").strip().lower()
    mechanism = str(draft.get("mechanism") or "").strip().lower()
    independent_variable = str(draft.get("independent_variable") or "").strip().lower()
    dependent_variable = str(draft.get("dependent_variable") or "").strip().lower()
    control_condition = str(draft.get("control_condition") or "").strip().lower()
    predicted_direction = str(draft.get("predicted_direction") or "").strip().lower()
    minimal_test = str(draft.get("minimal_test") or "").strip().lower()
    falsifier = str(draft.get("falsifier") or "").strip().lower()
    anchor_terms = _ood_focus_terms(anchor_label, limit=2)
    candidate_terms = _ood_focus_terms(candidate_label, limit=2)
    if "via " in statement and "relation" in statement:
        reasons.append("template_statement")
    if "out-of-distribution coupling" in statement:
        reasons.append("template_statement")
    if not any(term in hypothesis_sentence for term in anchor_terms) and anchor_terms:
        reasons.append("anchor_not_bound")
    if not any(term in hypothesis_sentence for term in candidate_terms) and candidate_terms:
        reasons.append("candidate_not_bound")
    if not any(term in mechanism for term in candidate_terms) and candidate_terms:
        reasons.append("candidate_missing_in_mechanism")
    if not any(term in minimal_test for term in candidate_terms) and candidate_terms:
        reasons.append("candidate_missing_in_minimal_test")
    if not any(term in falsifier for term in candidate_terms) and candidate_terms:
        reasons.append("candidate_missing_in_falsifier")
    if "if " not in hypothesis_sentence or " then " not in hypothesis_sentence:
        reasons.append("missing_if_then_hypothesis")
    if not any(term in independent_variable for term in _OOD_IV_CUE_TERMS):
        reasons.append("independent_variable_not_manipulable")
    if not any(term in control_condition for term in _OOD_CONTROL_CUE_TERMS):
        reasons.append("missing_control_condition")
    if not any(term in dependent_variable for term in _OOD_DV_CUE_TERMS):
        reasons.append("dependent_variable_not_measurable")
    if any(pattern in mechanism for pattern in _OOD_GENERIC_MECHANISM_PATTERNS):
        reasons.append("generic_mechanism")
    if any(
        pattern in predicted_direction
        for pattern in _OOD_GENERIC_PREDICTED_DIRECTION_PATTERNS
    ):
        reasons.append("generic_predicted_direction")

    return (not reasons), reasons


def _build_ood_candidate_draft(
    *,
    anchor_label: str,
    anchor_type: str,
    candidate_label: str,
    candidate_type: str,
    relation_hint: str,
    score_breakdown: dict[str, Any],
) -> dict[str, str]:
    claim_type = _infer_ood_claim_type(
        anchor_type=anchor_type,
        candidate_type=candidate_type,
        relation_hint=relation_hint,
        candidate_label=candidate_label,
    )
    anchor_short = _ood_compact_label(anchor_label)
    candidate_short = _ood_compact_label(candidate_label)
    canonical_type = _canonical_ood_node_type(candidate_type)
    if claim_type == "confound":
        mechanism = (
            f"{candidate_short} may act as a structured confound that inflates the "
            f"apparent decoding effect anchored on {anchor_short}."
        )
        independent_variable = (
            f"Explicitly controlling, stratifying, or balancing {candidate_short} "
            f"versus leaving it uncontrolled in the {anchor_short} analysis"
        )
        dependent_variable = (
            f"The preregistered decoding metric associated with {anchor_short}"
        )
        control_condition = (
            f"the matched baseline decoder that leaves {candidate_short} uncontrolled"
        )
        predicted_direction = (
            f"should drop toward the baseline when {candidate_short} is controlled"
        )
        minimal_test = (
            f"Re-fit the decoder for {anchor_short} with a matched control that "
            f"regresses, stratifies, or balances {candidate_short}."
        )
        falsifier = (
            f"Reject this confound hypothesis if the decoding effect for {anchor_short} "
            f"remains stable after controlling for {candidate_short}."
        )
    elif claim_type == "mechanism":
        mechanism = (
            f"{candidate_short} may carry information required for the decoding effect "
            f"anchored on {anchor_short}, rather than reflecting a passive correlate."
        )
        independent_variable = (
            f"isolating versus removing signal attributed to {candidate_short} while "
            f"holding the {anchor_short} contrast fixed"
        )
        dependent_variable = (
            f"the preregistered decoding or neural signal metric for {anchor_short}"
        )
        control_condition = (
            f"the matched control analysis that preserves preprocessing and label "
            f"balance without isolating {candidate_short}"
        )
        predicted_direction = (
            f"should stay above the control condition when {candidate_short} is "
            "isolated and drop toward the control condition when it is removed"
        )
        minimal_test = (
            f"Run an ROI- or feature-restricted decoding analysis that isolates "
            f"{candidate_short} when testing {anchor_short}."
        )
        falsifier = (
            f"Reject this mechanism hypothesis if isolating {candidate_short} does not "
            f"change decoding behavior for {anchor_short} relative to matched controls."
        )
    elif claim_type == "transfer":
        mechanism = (
            f"{anchor_short} and {candidate_short} may rely on the same "
            "representation-carrying bottleneck rather than only sharing a task family."
        )
        independent_variable = (
            f"training on {anchor_short} and evaluating on {candidate_short} versus "
            "training on the same anchor and evaluating on task-mismatched controls"
        )
        dependent_variable = (
            f"cross-condition decoding accuracy anchored on {anchor_short}"
        )
        control_condition = "the task-mismatched or label-shuffled transfer baseline"
        predicted_direction = (
            "should remain above the transfer baseline only when the shared bottleneck "
            "is present"
        )
        minimal_test = (
            f"Train on {anchor_short}, test on {candidate_short}, and compare transfer "
            "accuracy against a label-shuffled or task-mismatched baseline."
        )
        falsifier = (
            f"Reject this transfer hypothesis if cross-condition performance between "
            f"{anchor_short} and {candidate_short} stays at control levels."
        )
    elif claim_type == "contradiction_resolution":
        mechanism = (
            f"{candidate_short} may be the hidden condition that explains why findings "
            f"around {anchor_short} appear contradictory."
        )
        independent_variable = (
            f"stratifying studies of {anchor_short} by the presence versus absence of "
            f"{candidate_short}"
        )
        dependent_variable = f"the direction and consistency of the effect around {anchor_short}"
        control_condition = (
            f"the pooled analysis that ignores stratification by {candidate_short}"
        )
        predicted_direction = (
            "should become more internally consistent after stratification than in the "
            "pooled control analysis"
        )
        minimal_test = (
            f"Re-analyze {anchor_short} with an explicit split or moderator term for "
            f"{candidate_short}."
        )
        falsifier = (
            f"Reject this contradiction-resolution hypothesis if stratifying by "
            f"{candidate_short} does not reduce inconsistency in the observed effect."
        )
    elif canonical_type == "Task":
        mechanism = (
            f"{candidate_short} may preserve the control demand that carries decoding "
            f"for {anchor_short}, rather than only co-occurring with it."
        )
        independent_variable = (
            f"running the {candidate_short} task versus a task-mismatched control while "
            f"holding the {anchor_short} decoder fixed"
        )
        dependent_variable = f"the transfer-ready decoding metric anchored on {anchor_short}"
        control_condition = "the matched task-mismatched baseline"
        predicted_direction = (
            "should remain above the task-mismatched baseline only when the control "
            "demand is preserved"
        )
        minimal_test = (
            f"Evaluate cross-task transfer from {anchor_short} to {candidate_short} "
            "with matched preprocessing and baseline controls."
        )
        falsifier = (
            f"Reject this task-transfer hypothesis if {candidate_short} offers no "
            f"measurable transfer gain over controls for {anchor_short}."
        )
    else:
        mechanism = (
            f"{candidate_short} may act as the missing mediator that links "
            f"{anchor_short} to a held-out decoding setting."
        )
        independent_variable = (
            f"explicitly modeling or stratifying {candidate_short} versus leaving it "
            f"unmodeled in analyses anchored on {anchor_short}"
        )
        dependent_variable = f"held-out decoding behavior for {anchor_short}"
        control_condition = (
            f"the matched baseline analysis that omits {candidate_short}"
        )
        predicted_direction = (
            "should shift selectively relative to the matched baseline when the "
            "mediator is modeled"
        )
        minimal_test = (
            f"Run a low-cost ablation or stratified analysis on {anchor_short} that "
            f"explicitly models {candidate_short}."
        )
        falsifier = (
            f"Reject this bridge hypothesis if modeling {candidate_short} has no "
            f"selective effect on decoding outcomes for {anchor_short}."
        )

    hypothesis_sentence = _compose_ood_hypothesis_sentence(
        mechanism=mechanism,
        independent_variable=independent_variable,
        control_condition=control_condition,
        dependent_variable=dependent_variable,
        predicted_direction=predicted_direction,
    )
    return _coerce_ood_candidate_draft(
        {
            "claim_type": claim_type,
            "statement": hypothesis_sentence,
            "hypothesis_sentence": hypothesis_sentence,
            "mechanism": mechanism,
            "independent_variable": independent_variable,
            "dependent_variable": dependent_variable,
            "control_condition": control_condition,
            "predicted_direction": predicted_direction,
            "prediction": predicted_direction,
            "minimal_test": minimal_test,
            "falsifier": falsifier,
        }
    )


@functools.lru_cache(maxsize=1)
def _get_ood_llm_router() -> Any | None:
    if os.getenv("BR_KG_OOD_LLM_REWRITE", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None
    try:
        from brain_researcher.services.agent.router import LLMRouter

        return LLMRouter()
    except Exception:  # pragma: no cover - best effort
        return None


def _maybe_llm_rewrite_ood_candidate(
    draft: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    router = _get_ood_llm_router()
    if router is None:
        return _coerce_ood_candidate_draft(draft), "heuristic"

    prompt = (
        "Rewrite the following neuroscience hypothesis candidate as strict JSON. "
        "Return keys claim_type, statement, hypothesis_sentence, mechanism, "
        "independent_variable, dependent_variable, control_condition, "
        "predicted_direction, prediction, minimal_test, falsifier. "
        "Requirements: the mechanism cannot be a family/ontology label alone; the "
        "independent variable must be manipulable; the dependent variable must be "
        "measurable; the control_condition must name a matched baseline/comparator; "
        "predicted_direction must be directional or dissociative; hypothesis_sentence "
        "must use an explicit if/then structure. Keep it concise and testable.\n\n"
        f"{json.dumps(_coerce_ood_candidate_draft(draft), sort_keys=True)}"
    )
    try:
        response = router.route_chat(
            prompt=prompt,
            model_hint=os.getenv("BR_KG_OOD_LLM_MODEL")
            or os.getenv("DEFAULT_LLM_MODEL")
            or "gemini-3-flash-preview",
            task_type="chat",
            strict_json=True,
        )
        text = str(getattr(response, "text", "") or "").strip()
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            out = dict(draft)
            for key in (
                "claim_type",
                "statement",
                "hypothesis_sentence",
                "mechanism",
                "independent_variable",
                "dependent_variable",
                "control_condition",
                "predicted_direction",
                "prediction",
                "minimal_test",
                "falsifier",
            ):
                value = str(parsed.get(key) or "").strip()
                if value:
                    out[key] = value
            return _coerce_ood_candidate_draft(out), "llm"
    except Exception:  # pragma: no cover - fail open
        pass
    return _coerce_ood_candidate_draft(draft), "heuristic"


def _resolve_ood_paper_store_override() -> str | None:
    ordered = route_gfs_stores("papers neuroscience decoding evidence")
    paper_stores = [
        store for store in ordered if classify_store_kind(store) == "papers"
    ]
    if paper_stores:
        return ",".join(paper_stores)
    return None


def _resolve_ood_verification_settings() -> dict[str, int]:
    warnings: list[str] = []
    return {
        "total_timeout_ms": _coerce_bounded_int(
            os.getenv("BR_KG_OOD_TOTAL_TIMEOUT_MS", "30000"),
            default=30000,
            min_value=1000,
            max_value=300000,
            field_name="BR_KG_OOD_TOTAL_TIMEOUT_MS",
            warnings=warnings,
        ),
        "search_timeout_ms": _coerce_bounded_int(
            os.getenv("BR_KG_OOD_GFS_SEARCH_TIMEOUT_MS", "8000"),
            default=8000,
            min_value=250,
            max_value=120000,
            field_name="BR_KG_OOD_GFS_SEARCH_TIMEOUT_MS",
            warnings=warnings,
        ),
        "max_stores": _coerce_bounded_int(
            os.getenv("BR_KG_OOD_GFS_MAX_STORES", "1"),
            default=1,
            min_value=1,
            max_value=20,
            field_name="BR_KG_OOD_GFS_MAX_STORES",
            warnings=warnings,
        ),
        "pair_top_k": _coerce_bounded_int(
            os.getenv("BR_KG_OOD_GFS_PAIR_TOP_K", "5"),
            default=5,
            min_value=1,
            max_value=20,
            field_name="BR_KG_OOD_GFS_PAIR_TOP_K",
            warnings=warnings,
        ),
        "context_top_k": _coerce_bounded_int(
            os.getenv("BR_KG_OOD_GFS_CONTEXT_TOP_K", "3"),
            default=3,
            min_value=1,
            max_value=20,
            field_name="BR_KG_OOD_GFS_CONTEXT_TOP_K",
            warnings=warnings,
        ),
    }


def _ood_budget_exhausted(deadline_monotonic: float | None) -> bool:
    if deadline_monotonic is None:
        return False
    return time.monotonic() >= deadline_monotonic


def _compact_gfs_diagnostics(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    compact: dict[str, Any] = {
        "status": str(result.get("status") or ""),
        "stores_hit": list(result.get("stores_hit") or []),
        "stores_attempted": list(result.get("stores_attempted") or []),
        "call_count": int(result.get("call_count") or 0),
        "latency_ms": round(_safe_float(result.get("latency_ms"), 0.0), 3),
        "raw_hit_count": int(result.get("raw_hit_count") or 0),
        "n_docs_hit": int(result.get("n_docs_hit") or 0),
    }
    store_errors = result.get("store_errors") or []
    if isinstance(store_errors, list) and store_errors:
        compact["store_errors"] = [
            dict(item) for item in store_errors if isinstance(item, dict)
        ]
    error_text = str(result.get("error") or "").strip()
    if error_text:
        compact["error"] = error_text
    return compact


def _build_ood_candidate_audit_row(
    item: dict[str, Any],
    *,
    verification_status: str,
    verification_reason: str,
    candidate_label: str | None = None,
    candidate_type: str | None = None,
) -> dict[str, Any]:
    score_breakdown = dict(item.get("score_breakdown") or {})
    kg_id = str(item.get("kg_id") or "").strip()
    return {
        "candidate_kg_id": kg_id,
        "candidate_label": str(candidate_label or item.get("label") or kg_id),
        "candidate_type": str(
            candidate_type
            or item.get("candidate_type")
            or item.get("node_type")
            or "Concept"
        ),
        "rank_before_rerank": int(
            _safe_float(item.get("rank_before_rerank"), 0.0) or 0
        ),
        "rank_after_rerank": int(_safe_float(item.get("rank_after_rerank"), 0.0) or 0),
        "leverage_score": round(
            _clip01(_safe_float(item.get("leverage_score"), 0.0)), 6
        ),
        "novelty_score": round(_clip01(_safe_float(item.get("novelty_score"), 0.0)), 6),
        "coherence_score": round(
            _clip01(_safe_float(item.get("coherence_score"), 0.0)),
            6,
        ),
        "feasibility_score": round(
            _clip01(_safe_float(item.get("feasibility_score"), 0.0)),
            6,
        ),
        "contradiction_score": round(
            _clip01(_safe_float(item.get("contradiction_score"), 0.0)),
            6,
        ),
        "bridge_score": round(
            _clip01(
                _safe_float(
                    item.get("bridge_score"),
                    _safe_float(score_breakdown.get("bridge_score"), 0.0),
                )
            ),
            6,
        ),
        "domain_overlap_score": round(
            _clip01(_safe_float(score_breakdown.get("domain_overlap_score"), 0.0)),
            6,
        ),
        "principle_score": (
            round(_safe_float(item.get("principle_score"), 0.0), 6)
            if item.get("principle_score") is not None
            else None
        ),
        "active_principle_id": str(item.get("active_principle_id") or "").strip()
        or None,
        "selection_reason": str(item.get("selection_reason") or "").strip() or None,
        "semantic_triage_decision": str(item.get("semantic_triage_decision") or "")
        .strip()
        or None,
        "semantic_triage_reasons": list(item.get("semantic_triage_reasons") or []),
        "semantic_penalty": round(_safe_float(item.get("semantic_penalty"), 0.0), 6),
        "verification_status": str(verification_status or "unknown"),
        "verification_reason": str(verification_reason or "unknown"),
    }


def _extract_ood_hit_evidence(
    hits: Sequence[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        evidence.append(
            {
                "title": str(hit.get("title") or "").strip(),
                "doi": str(hit.get("doi") or "").strip() or None,
                "pmid": str(hit.get("pmid") or "").strip() or None,
                "pmcid": str(hit.get("pmcid") or "").strip() or None,
                "score": round(_safe_float(hit.get("score"), 0.0), 6),
                "snippet": str(hit.get("snippet") or "").strip()[:240],
            }
        )
    return evidence


def _text_mentions_any(text: str, markers: Sequence[str]) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in markers)


def _count_shared_context_hits(
    hits: Sequence[dict[str, Any]] | None,
    *,
    anchor_terms: Sequence[str],
    candidate_terms: Sequence[str],
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        haystack = " ".join(
            [
                str(hit.get("title") or ""),
                str(hit.get("snippet") or ""),
                str(hit.get("text") or "")[:400],
            ]
        ).lower()
        has_anchor = any(term in haystack for term in anchor_terms)
        has_candidate = any(term in haystack for term in candidate_terms)
        if has_anchor and has_candidate:
            matched.append(hit)
    return matched


def _build_ood_verification_query(
    *,
    anchor_label: str,
    candidate_label: str,
    claim_type: str,
) -> str:
    anchor_terms = _ood_focus_terms(anchor_label, limit=4)
    candidate_terms = _ood_focus_terms(candidate_label, limit=4)
    claim_terms = {
        "transfer": ["transfer", "generalization", "decoding"],
        "mechanism": ["representation", "mechanism", "decoding"],
        "bridge": ["representation", "latent", "decoding"],
        "confound": ["artifact", "confound", "decoding"],
        "contradiction_resolution": ["contradiction", "replication", "decoding"],
    }.get(claim_type, ["decoding", "representation"])
    merged = list(dict.fromkeys([*anchor_terms, *candidate_terms, *claim_terms]))
    return " ".join(merged[:10])


def _build_ood_context_query(candidate_label: str) -> str:
    candidate_terms = _ood_focus_terms(candidate_label, limit=4)
    merged = list(dict.fromkeys([*candidate_terms, *_OOD_NEURO_CONTEXT_MARKERS]))
    return " ".join(merged[:10])


def _verify_ood_candidate_with_gfs(
    *,
    anchor_label: str,
    candidate_label: str,
    candidate_type: str,
    claim_type: str,
    score_breakdown: dict[str, Any],
    deadline_monotonic: float | None = None,
    max_stores: int | None = None,
    search_timeout_ms: int | None = None,
    pair_top_k: int = 5,
    context_top_k: int = 3,
) -> dict[str, Any]:
    paper_store_override = _resolve_ood_paper_store_override()
    paper_stores = _resolve_stores(paper_store_override) if paper_store_override else []
    diagnostics: dict[str, Any] = {
        "paper_stores": list(paper_stores),
        "pair_search": {},
        "context_search": {},
    }

    if os.getenv("BR_KG_OOD_GFS_VERIFY_ENABLED", "true").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return {
            "verification_status": "unverified",
            "verification_reason": "gfs_disabled",
            "verification_evidence": {
                "prior_art_hits": [],
                "contradiction_hits": [],
                "confound_hits": [],
                "shared_context_hits": [],
            },
            "verification_diagnostics": diagnostics,
        }

    if not paper_store_override or not paper_stores:
        return {
            "verification_status": "unverified",
            "verification_reason": "gfs_paper_store_unconfigured",
            "verification_evidence": {
                "prior_art_hits": [],
                "contradiction_hits": [],
                "confound_hits": [],
                "shared_context_hits": [],
            },
            "verification_diagnostics": diagnostics,
        }

    if _ood_budget_exhausted(deadline_monotonic):
        return {
            "verification_status": "unverified",
            "verification_reason": "gfs_budget_exhausted",
            "verification_evidence": {
                "prior_art_hits": [],
                "contradiction_hits": [],
                "confound_hits": [],
                "shared_context_hits": [],
            },
            "verification_diagnostics": diagnostics,
        }

    pair_query = _build_ood_verification_query(
        anchor_label=anchor_label,
        candidate_label=candidate_label,
        claim_type=claim_type,
    )
    try:
        pair_result = search_gfs(
            pair_query,
            top_k=pair_top_k,
            store=paper_store_override,
            timeout_ms=search_timeout_ms,
            max_stores=max_stores,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "verification_status": "unverified",
            "verification_reason": "gfs_error",
            "verification_evidence": {"error": str(exc)},
            "verification_diagnostics": diagnostics,
        }
    diagnostics["pair_search"] = _compact_gfs_diagnostics(pair_result)
    pair_error = str(pair_result.get("error") or "").strip()
    pair_store_errors = pair_result.get("store_errors") or []
    pair_timed_out = any(
        "timed out" in str(item.get("error") or "").lower()
        for item in pair_store_errors
        if isinstance(item, dict)
    )
    if pair_result.get("status") not in {"ok", "empty"}:
        return {
            "verification_status": "unverified",
            "verification_reason": "gfs_timeout" if pair_timed_out else "gfs_error",
            "verification_evidence": {
                "pair_query": pair_query,
                "context_query": "",
                "error": pair_error or "pair_query_failed",
            },
            "verification_diagnostics": diagnostics,
        }
    pair_hits = (
        pair_result.get("hits")
        if isinstance(pair_result, dict) and pair_result.get("status") == "ok"
        else []
    )
    anchor_terms = _ood_focus_terms(anchor_label, limit=3)
    candidate_terms = _ood_focus_terms(candidate_label, limit=3)
    shared_hits = _count_shared_context_hits(
        pair_hits, anchor_terms=anchor_terms, candidate_terms=candidate_terms
    )
    prior_art_hits = [
        hit
        for hit in shared_hits
        if _text_mentions_any(
            " ".join(
                [
                    str(hit.get("title") or ""),
                    str(hit.get("snippet") or ""),
                ]
            ),
            _OOD_DIRECT_PRIOR_ART_MARKERS,
        )
    ]
    contradiction_hits = [
        hit
        for hit in shared_hits
        if _text_mentions_any(
            " ".join(
                [
                    str(hit.get("title") or ""),
                    str(hit.get("snippet") or ""),
                ]
            ),
            _OOD_CONTRADICTION_MARKERS,
        )
    ]
    confound_hits = [
        hit
        for hit in shared_hits
        if _text_mentions_any(
            " ".join(
                [
                    str(hit.get("title") or ""),
                    str(hit.get("snippet") or ""),
                ]
            ),
            _OOD_CONFOUND_MARKERS,
        )
    ]

    context_query = _build_ood_context_query(candidate_label)
    if _ood_budget_exhausted(deadline_monotonic):
        return {
            "verification_status": "unverified",
            "verification_reason": "gfs_budget_exhausted",
            "verification_evidence": {
                "pair_query": pair_query,
                "context_query": context_query,
                "prior_art_hits": _extract_ood_hit_evidence(prior_art_hits),
                "contradiction_hits": _extract_ood_hit_evidence(contradiction_hits),
                "confound_hits": _extract_ood_hit_evidence(confound_hits),
                "shared_context_hits": _extract_ood_hit_evidence(shared_hits),
                "context_hits": [],
            },
            "verification_diagnostics": diagnostics,
        }
    try:
        context_result = search_gfs(
            context_query,
            top_k=context_top_k,
            store=paper_store_override,
            timeout_ms=search_timeout_ms,
            max_stores=max_stores,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "verification_status": "unverified",
            "verification_reason": "gfs_error",
            "verification_evidence": {
                "pair_query": pair_query,
                "context_query": context_query,
                "error": str(exc),
            },
            "verification_diagnostics": diagnostics,
        }
    diagnostics["context_search"] = _compact_gfs_diagnostics(context_result)
    context_error = str(context_result.get("error") or "").strip()
    context_store_errors = context_result.get("store_errors") or []
    context_timed_out = any(
        "timed out" in str(item.get("error") or "").lower()
        for item in context_store_errors
        if isinstance(item, dict)
    )
    if context_result.get("status") not in {"ok", "empty"}:
        return {
            "verification_status": "unverified",
            "verification_reason": "gfs_timeout" if context_timed_out else "gfs_error",
            "verification_evidence": {
                "pair_query": pair_query,
                "context_query": context_query,
                "error": context_error or "context_query_failed",
            },
            "verification_diagnostics": diagnostics,
        }
    context_hits = (
        context_result.get("hits")
        if isinstance(context_result, dict) and context_result.get("status") == "ok"
        else []
    )
    neuroscience_context_hits = [
        hit
        for hit in context_hits
        if _text_mentions_any(
            " ".join(
                [
                    str(hit.get("title") or ""),
                    str(hit.get("snippet") or ""),
                ]
            ),
            _OOD_NEURO_CONTEXT_MARKERS,
        )
    ]

    verification_evidence = {
        "pair_query": pair_query,
        "context_query": context_query,
        "prior_art_hits": _extract_ood_hit_evidence(prior_art_hits),
        "contradiction_hits": _extract_ood_hit_evidence(contradiction_hits),
        "confound_hits": _extract_ood_hit_evidence(confound_hits),
        "shared_context_hits": _extract_ood_hit_evidence(shared_hits),
        "context_hits": _extract_ood_hit_evidence(neuroscience_context_hits),
    }
    domain_overlap = _safe_float(score_breakdown.get("domain_overlap_score"), 0.0)
    if prior_art_hits:
        return {
            "verification_status": "vetoed",
            "verification_reason": "direct_prior_art",
            "verification_evidence": verification_evidence,
            "verification_diagnostics": diagnostics,
        }
    if contradiction_hits:
        return {
            "verification_status": "vetoed",
            "verification_reason": "literature_contradiction",
            "verification_evidence": verification_evidence,
            "verification_diagnostics": diagnostics,
        }
    if confound_hits:
        return {
            "verification_status": "vetoed",
            "verification_reason": "methodological_confound",
            "verification_evidence": verification_evidence,
            "verification_diagnostics": diagnostics,
        }
    if (
        not shared_hits
        and not neuroscience_context_hits
        and domain_overlap <= 0.05
        and _canonical_ood_node_type(candidate_type) in {"Concept", "Dataset", "Method"}
    ):
        return {
            "verification_status": "vetoed",
            "verification_reason": "no_shared_research_context",
            "verification_evidence": verification_evidence,
            "verification_diagnostics": diagnostics,
        }
    if not pair_hits and not context_hits:
        return {
            "verification_status": "unverified",
            "verification_reason": "no_gfs_hits",
            "verification_evidence": verification_evidence,
            "verification_diagnostics": diagnostics,
        }
    return {
        "verification_status": "survived",
        "verification_reason": "no_hard_veto",
        "verification_evidence": verification_evidence,
        "verification_diagnostics": diagnostics,
    }


def _parse_seed_provenance_entry(provenance: str) -> tuple[str | None, str | None]:
    text = str(provenance or "").strip()
    if not text:
        return None, None
    if text.startswith("search_expanded_from:"):
        return text.removeprefix("search_expanded_from:") or None, "SEARCH_EXPANDED"
    if text.startswith("expanded_from:"):
        tail = text.removeprefix("expanded_from:")
        if ":" not in tail:
            return tail or None, "EXPANDED"
        source_id, relation = tail.rsplit(":", 1)
        return source_id or None, relation or "EXPANDED"
    return None, None


def _coerce_precomputed_leverage_context(
    leverage_context: Mapping[str, Any] | None,
    leverage_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize optional semantic seed context for precomputed leverage rows."""

    merged_seed_ids: list[str] = []
    semantic_seed_labels: dict[str, str] = {}
    semantic_seed_types: dict[str, str] = {}
    semantic_seed_scores: dict[str, float] = {}
    seed_provenance: dict[str, list[str]] = {}
    rejections: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    seen_seed_ids: set[str] = set()

    def _append_seed_id(seed_id: str) -> str:
        normalized = str(seed_id or "").strip()
        if not normalized:
            return ""
        lowered = normalized.lower()
        if lowered not in seen_seed_ids:
            seen_seed_ids.add(lowered)
            merged_seed_ids.append(normalized)
        return normalized

    def _merge_context(source: Mapping[str, Any] | None) -> None:
        if not isinstance(source, Mapping):
            return

        for seed_id in _clean_seed_ids(source.get("seed_kg_ids")):
            _append_seed_id(seed_id)

        labels = source.get("semantic_seed_labels") or {}
        if isinstance(labels, Mapping):
            for seed_id, label in labels.items():
                normalized_seed = _append_seed_id(str(seed_id or ""))
                if normalized_seed:
                    semantic_seed_labels[normalized_seed] = (
                        str(label or normalized_seed).strip() or normalized_seed
                    )

        types = source.get("semantic_seed_types") or {}
        if isinstance(types, Mapping):
            for seed_id, node_type in types.items():
                normalized_seed = _append_seed_id(str(seed_id or ""))
                if normalized_seed:
                    semantic_seed_types[normalized_seed] = (
                        str(node_type or "Node").strip() or "Node"
                    )

        scores = source.get("semantic_seed_scores") or {}
        if isinstance(scores, Mapping):
            for seed_id, score in scores.items():
                normalized_seed = _append_seed_id(str(seed_id or ""))
                if normalized_seed:
                    semantic_seed_scores[normalized_seed] = max(
                        _safe_float(score, 0.0),
                        _safe_float(semantic_seed_scores.get(normalized_seed), 0.0),
                    )

        provenance_map = source.get("seed_provenance") or {}
        if isinstance(provenance_map, Mapping):
            for seed_id, entries in provenance_map.items():
                normalized_seed = _append_seed_id(str(seed_id or ""))
                if not normalized_seed:
                    continue
                target_entries = seed_provenance.setdefault(normalized_seed, [])
                for entry in entries or []:
                    normalized_entry = str(entry or "").strip()
                    if normalized_entry and normalized_entry not in target_entries:
                        target_entries.append(normalized_entry)

        if not rejections:
            rejections_map = source.get("rejections") or {}
            if isinstance(rejections_map, Mapping):
                rejections.update(dict(rejections_map))
        if not summary:
            summary_map = source.get("summary") or {}
            if isinstance(summary_map, Mapping):
                summary.update(dict(summary_map))

    _merge_context(leverage_context)
    for row in leverage_rows:
        _merge_context(row)

    return {
        "seed_kg_ids": merged_seed_ids,
        "semantic_seed_labels": semantic_seed_labels,
        "semantic_seed_types": semantic_seed_types,
        "semantic_seed_scores": semantic_seed_scores,
        "seed_provenance": seed_provenance,
        "rejections": rejections,
        "summary": summary,
    }


def find_structural_leverage(
    seed_kg_ids: Sequence[str] | None,
    *,
    relation_types: Sequence[str] | None = None,
    direction: str = "both",
    limit: int = 25,
    taste: dict[str, Any] | None = None,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    """Rank candidate nodes by structural leverage around seed nodes."""
    warnings: list[str] = []
    input_seeds = _clean_seed_ids(seed_kg_ids)
    scoring = _normalize_taste_scoring(taste)
    limit_i = _coerce_bounded_int(
        limit,
        default=25,
        min_value=1,
        max_value=500,
        field_name="limit",
        warnings=warnings,
    )

    result: dict[str, Any] = {
        "ok": True,
        "mode": "structural_leverage",
        "input_seed_kg_ids": input_seeds,
        "seed_kg_ids": input_seeds,
        "items": [],
        "summary": {
            "n_input_seeds": len(input_seeds),
            "n_seeds": len(input_seeds),
            "n_candidates": 0,
            "n_quality_passed": 0,
            "n_rejected": 0,
        },
        "taste": scoring,
        "warnings": warnings,
    }

    if not input_seeds:
        warnings.append("No seed_kg_ids provided")
        return result

    client = db or get_default_db()
    rel_filter = list(relation_types) if relation_types else None
    seed_context = _resolve_semantic_seed_context(
        input_seeds,
        db=client,
        relation_types=rel_filter,
        neighbor_limit=min(scoring["max_candidates"], 24),
    )
    seeds = seed_context.get("seed_kg_ids") or input_seeds
    result["seed_kg_ids"] = list(seeds)
    result["semantic_seed_labels"] = dict(
        seed_context.get("semantic_seed_labels") or {}
    )
    result["semantic_seed_types"] = dict(seed_context.get("semantic_seed_types") or {})
    result["semantic_seed_scores"] = dict(
        seed_context.get("semantic_seed_scores") or {}
    )
    result["seed_provenance"] = dict(seed_context.get("seed_provenance") or {})
    result["summary"]["n_seeds"] = len(seeds)
    warnings.extend(seed_context.get("warnings") or [])

    candidates: dict[str, dict[str, Any]] = {}
    seeds_set = {seed.lower() for seed in seeds}
    input_seed_set = {seed.lower() for seed in input_seeds}
    fetch_limit = min(scoring["max_candidates"], max(limit_i * 2, limit_i))
    rejected_counts: dict[str, int] = {}
    seed_domain_tokens = seed_context.get("domain_tokens") or []
    seed_scores = dict(seed_context.get("semantic_seed_scores") or {})
    seed_provenance = dict(seed_context.get("seed_provenance") or {})

    max_traversal_seeds = max(4, min(12, limit_i * 2))
    traversal_seeds = _select_traversal_seeds(
        seeds,
        input_seed_ids=input_seeds,
        seed_scores=seed_scores,
        seed_provenance=seed_provenance,
        max_traversal_seeds=max_traversal_seeds,
    )
    eligible_traversal_seed_count = sum(
        1
        for seed in seeds
        if not any(
            str(entry).startswith("search_expanded_from:")
            for entry in (seed_provenance.get(seed) or [])
        )
    )
    if traversal_seeds and len(traversal_seeds) < eligible_traversal_seed_count:
        warnings.append(
            "Traversal seeds capped to control repeated neighbor scans in leverage ranking."
        )
    if not traversal_seeds:
        fallback_seed_ids = [
            seed for seed in input_seeds if str(seed or "").strip()
        ] or [seed for seed in seeds if str(seed or "").strip()]
        traversal_seeds = fallback_seed_ids[:max_traversal_seeds]
        if traversal_seeds:
            warnings.append(
                "Falling back to capped input seeds because semantic expansion produced only search-expanded anchors."
            )

    for candidate_id in seeds:
        if candidate_id.lower() in input_seed_set:
            continue
        provenance_entries = seed_provenance.get(candidate_id) or []
        has_search_expanded = any(
            str(entry).startswith("search_expanded_from:")
            for entry in provenance_entries
        )
        if not has_search_expanded:
            continue
        source_ids: set[str] = set()
        relations: set[str] = set()
        for entry in provenance_entries:
            source_id, relation = _parse_seed_provenance_entry(str(entry))
            if source_id:
                source_ids.add(source_id)
            if relation:
                relations.add(relation)
        if not source_ids and not provenance_entries:
            continue
        candidate_label = str(
            result["semantic_seed_labels"].get(candidate_id) or candidate_id
        )
        candidate_type = str(result["semantic_seed_types"].get(candidate_id) or "Node")
        assessment = _candidate_quality_assessment(
            kg_id=candidate_id,
            label=candidate_label,
            node_type=candidate_type,
            relations=sorted(relations) or ["SEARCH_EXPANDED"],
            seed_domain_tokens=seed_domain_tokens,
        )
        if not assessment["ok"]:
            for reason in assessment["reasons"]:
                rejected_counts[reason] = rejected_counts.get(reason, 0) + 1
            continue
        item = candidates.setdefault(
            candidate_id,
            {
                "kg_id": candidate_id,
                "label": candidate_label,
                "node_type": candidate_type,
                "seed_hits": set(),
                "relations": set(),
                "base_scores": [],
                "label_quality_scores": [],
                "relation_quality_scores": [],
                "domain_overlap_scores": [],
                "quality_flags": set(),
                "candidate_type": assessment["candidate_type"],
            },
        )
        item["seed_hits"].update(source_ids or traversal_seeds[:1])
        item["relations"].update(sorted(relations) or ["SEARCH_EXPANDED"])
        item["base_scores"].append(_safe_float(seed_scores.get(candidate_id), 0.55))
        item["label_quality_scores"].append(
            _safe_float(assessment["label_quality"], 0.0)
        )
        item["relation_quality_scores"].append(
            _safe_float(assessment["relation_quality"], 0.0)
        )
        item["domain_overlap_scores"].append(
            _safe_float(assessment["domain_overlap"], 0.0)
        )
        item["quality_flags"].update(assessment["quality_flags"])

    for seed in traversal_seeds:
        try:
            rows = neighbors(
                seed,
                relation_types=rel_filter,
                direction=direction,
                limit=fetch_limit,
                db=client,
            )
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(f"Neighbor lookup failed for '{seed}': {exc}")
            rows = []
        for row in rows:
            kg_id = str(row.get("kg_id") or "").strip()
            if not kg_id or kg_id.lower() in seeds_set:
                continue
            props = row.get("properties") or {}
            label = _coalesce_node_label(
                row.get("label"),
                props.get("name") if isinstance(props, dict) else None,
                props.get("title") if isinstance(props, dict) else None,
                kg_id,
            )
            relation = str(row.get("relation") or "").strip().upper()
            assessment = _candidate_quality_assessment(
                kg_id=kg_id,
                label=label,
                node_type=str(row.get("node_type") or "Node"),
                relations=[relation] if relation else [],
                seed_domain_tokens=seed_domain_tokens,
            )
            if not assessment["ok"]:
                for reason in assessment["reasons"]:
                    rejected_counts[reason] = rejected_counts.get(reason, 0) + 1
                continue
            item = candidates.setdefault(
                kg_id,
                {
                    "kg_id": kg_id,
                    "label": label,
                    "node_type": row.get("node_type") or "Node",
                    "seed_hits": set(),
                    "relations": set(),
                    "base_scores": [],
                    "label_quality_scores": [],
                    "relation_quality_scores": [],
                    "domain_overlap_scores": [],
                    "quality_flags": set(),
                    "candidate_type": assessment["candidate_type"],
                },
            )
            item["seed_hits"].add(seed)
            if relation:
                item["relations"].add(relation)
            base_score = _safe_float(row.get("score"), 1.0)
            item["base_scores"].append(base_score)
            item["label_quality_scores"].append(
                _safe_float(assessment["label_quality"], 0.0)
            )
            item["relation_quality_scores"].append(
                _safe_float(assessment["relation_quality"], 0.0)
            )
            item["domain_overlap_scores"].append(
                _safe_float(assessment["domain_overlap"], 0.0)
            )
            item["quality_flags"].update(assessment["quality_flags"])

    ranked: list[dict[str, Any]] = []
    w = scoring["weights"]
    n_seed = max(1, len(traversal_seeds))
    for item in candidates.values():
        base_scores = item.get("base_scores") or [1.0]
        mean_base = sum(base_scores) / float(max(1, len(base_scores)))
        novelty_proxy = _clip01(1.0 - _clip01(mean_base))
        bridge = _clip01(float(len(item["seed_hits"])) / float(n_seed))
        diversity = _clip01(float(len(item["relations"])) / 4.0)
        label_quality = sum(item["label_quality_scores"]) / float(
            max(1, len(item["label_quality_scores"]))
        )
        relation_quality = sum(item["relation_quality_scores"]) / float(
            max(1, len(item["relation_quality_scores"]))
        )
        domain_overlap = sum(item["domain_overlap_scores"]) / float(
            max(1, len(item["domain_overlap_scores"]))
        )
        specificity = _clip01(
            0.25
            + 0.35 * label_quality
            + 0.20 * relation_quality
            + 0.20 * min(1.0, len(_tokenize_ood_label(item["label"])) / 4.0)
        )
        coherence = _clip01(
            0.45 * label_quality + 0.30 * relation_quality + 0.25 * domain_overlap
        )
        feasibility = _clip01(
            0.45 * coherence + 0.35 * bridge + 0.20 * relation_quality
        )
        novelty = _clip01(
            0.40 * novelty_proxy + 0.40 * specificity + 0.20 * (1.0 - domain_overlap)
        )
        leverage_score = _clip01(
            w["novelty"] * novelty
            + w["contradiction"] * diversity
            + w["evidence"] * feasibility
        )
        score_breakdown = {
            "novelty_score": round(novelty, 6),
            "contradiction_score": round(diversity, 6),
            "coherence_score": round(coherence, 6),
            "feasibility_score": round(feasibility, 6),
            "bridge_score": round(bridge, 6),
            "diversity_score": round(diversity, 6),
            "label_quality_score": round(label_quality, 6),
            "relation_quality_score": round(relation_quality, 6),
            "domain_overlap_score": round(domain_overlap, 6),
            "specificity_score": round(specificity, 6),
            "base_novelty_proxy": round(novelty_proxy, 6),
        }
        ranked.append(
            {
                "kg_id": item["kg_id"],
                "label": item["label"],
                "node_type": item["node_type"],
                "candidate_type": item["candidate_type"],
                "seeds_touched": sorted(item["seed_hits"]),
                "relations": sorted(item["relations"]),
                "quality_flags": sorted(item["quality_flags"]),
                "novelty_score": score_breakdown["novelty_score"],
                "contradiction_score": score_breakdown["contradiction_score"],
                "coherence_score": score_breakdown["coherence_score"],
                "feasibility_score": score_breakdown["feasibility_score"],
                "bridge_score": score_breakdown["bridge_score"],
                "diversity_score": score_breakdown["diversity_score"],
                "leverage_score": round(leverage_score, 6),
                "score_breakdown": score_breakdown,
            }
        )

    ranked.sort(
        key=lambda row: (
            -float(row.get("leverage_score") or 0.0),
            -float(row.get("novelty_score") or 0.0),
            str(row.get("kg_id") or ""),
        )
    )
    total_ranked = len(ranked)
    if total_ranked >= 2:
        leverage_scores = [float(row.get("leverage_score") or 0.0) for row in ranked]
        score_spread = max(leverage_scores) - min(leverage_scores)
        result["summary"]["score_spread"] = round(score_spread, 6)
        if score_spread < 0.02:
            warnings.append(
                "Candidate leverage scores are near-identical; ranking confidence is low."
            )
    ranked = ranked[:limit_i]
    result["items"] = ranked
    result["summary"]["n_candidates"] = total_ranked
    result["summary"]["n_quality_passed"] = total_ranked
    result["summary"]["n_returned"] = len(ranked)
    result["summary"]["n_rejected"] = sum(rejected_counts.values())
    if rejected_counts:
        result["rejections"] = rejected_counts
    if not ranked:
        warnings.append("No leverage candidates found for provided seeds")
    return result


def detect_contradiction_motifs(
    *,
    hypothesis: str | None = None,
    seed_kg_ids: Sequence[str] | None = None,
    evidence_items: Sequence[dict[str, Any]] | None = None,
    max_evidence: int = 80,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    """Detect contradiction motifs from evidence polarity patterns."""
    warnings: list[str] = []
    seeds = _clean_seed_ids(seed_kg_ids)
    max_evidence_i = _coerce_bounded_int(
        max_evidence,
        default=80,
        min_value=1,
        max_value=500,
        field_name="max_evidence",
        warnings=warnings,
    )

    evidence: list[dict[str, Any]] = []
    source_mode = "input_evidence"
    if evidence_items is not None:
        evidence = [
            item for item in evidence_items[:max_evidence_i] if isinstance(item, dict)
        ]
    else:
        source_mode = "verify_hypothesis"
        normalized_hypothesis = str(hypothesis or "").strip()
        if not normalized_hypothesis:
            if len(seeds) >= 2:
                normalized_hypothesis = f"{seeds[0]} is related to {seeds[1]}"
            elif len(seeds) == 1:
                normalized_hypothesis = f"{seeds[0]} is related to an unknown target"
            else:
                normalized_hypothesis = ""
        if not normalized_hypothesis:
            warnings.append("No hypothesis/evidence provided for contradiction scan")
        else:
            client = db or get_default_db()
            verified = verify_hypothesis(
                normalized_hypothesis,
                entity_hints=list(seeds) if seeds else None,
                max_evidence=max_evidence_i,
                strictness="high_recall",
                include_subgraph=False,
                include_path_details=False,
                db=client,
            )
            for key in (
                "supporting_evidence",
                "conflicting_evidence",
                "uncertain_evidence",
                "neutral_evidence",
            ):
                rows = verified.get(key) or []
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            evidence.append(row)
            if isinstance(verified.get("warnings"), list):
                warnings.extend(str(w) for w in verified["warnings"])

    grouped: dict[str, dict[str, Any]] = {}
    for row in evidence:
        publication = row.get("publication") or {}
        pub_id = str(publication.get("kg_id") or "").strip()
        if not pub_id:
            continue
        polarity = _normalize_claim_polarity(row.get("polarity"))
        score = _clip01(_safe_float(row.get("score"), 0.0))
        claim = row.get("claim") or {}
        claim_text = str(claim.get("text") or claim.get("kg_id") or "").strip()
        bucket = grouped.setdefault(
            pub_id,
            {
                "publication_id": pub_id,
                "publication_label": str(publication.get("label") or pub_id),
                "support_count": 0,
                "conflict_count": 0,
                "support_score": 0.0,
                "conflict_score": 0.0,
                "claim_texts": set(),
            },
        )
        if claim_text:
            bucket["claim_texts"].add(claim_text)
        if polarity == "supports":
            bucket["support_count"] += 1
            bucket["support_score"] += score
        elif polarity == "refutes":
            bucket["conflict_count"] += 1
            bucket["conflict_score"] += score

    motifs: list[dict[str, Any]] = []
    for bucket in grouped.values():
        if bucket["support_count"] <= 0 or bucket["conflict_count"] <= 0:
            continue
        motif_score = _clip01(
            min(float(bucket["support_score"]), float(bucket["conflict_score"]))
        )
        total_polarized = bucket["support_count"] + bucket["conflict_count"]
        contradiction_density = float(
            min(bucket["support_count"], bucket["conflict_count"])
        ) / float(max(1, total_polarized))
        motifs.append(
            {
                "motif_type": "publication_polarity_conflict",
                "publication_id": bucket["publication_id"],
                "publication_label": bucket["publication_label"],
                "support_count": int(bucket["support_count"]),
                "conflict_count": int(bucket["conflict_count"]),
                "motif_score": round(motif_score, 6),
                "contradiction_density": round(_clip01(contradiction_density), 6),
                "examples": sorted(bucket["claim_texts"])[:3],
            }
        )

    motifs.sort(
        key=lambda item: (
            -float(item.get("motif_score") or 0.0),
            -float(item.get("contradiction_density") or 0.0),
            str(item.get("publication_id") or ""),
        )
    )
    if not motifs:
        warnings.append("No contradiction motifs detected")

    return {
        "ok": True,
        "mode": "contradiction_motifs",
        "source_mode": source_mode,
        "seed_kg_ids": seeds,
        "motifs": motifs,
        "summary": {
            "n_input_evidence": len(evidence),
            "n_motifs": len(motifs),
        },
        "warnings": warnings,
    }


_WOW_METHOD_FAMILY_HINTS: dict[str, tuple[str, ...]] = {
    "reinforcement_learning": (
        "reinforcement learning",
        "policy gradient",
        "actor critic",
        "q learning",
        "rl",
    ),
    "causal_intervention": (
        "causal intervention",
        "causal inference",
        "counterfactual",
        "intervention",
        "do calculus",
    ),
    "control_theory": (
        "control theory",
        "feedback control",
        "optimal control",
        "controller",
    ),
    "graph_prior": (
        "graph prior",
        "graph neural network",
        "graph regularization",
        "graph constraint",
    ),
    "scaling_law": (
        "scaling law",
        "power law",
        "scaling laws",
    ),
}


def _resolve_wow_seed_ids(
    *,
    query: str | None,
    seed_kg_ids: Sequence[str] | None,
    db: Optional[Neo4jGraphDB],
    search_limit: int = 8,
) -> list[str]:
    seeds = _clean_seed_ids(seed_kg_ids)
    if seeds:
        return seeds
    query_text = str(query or "").strip()
    if not query_text:
        return []
    rows = search_nodes(query_text, limit=search_limit, db=db)
    resolved: list[str] = []
    seen: set[str] = set()
    for row in rows:
        kg_id = str(getattr(row, "kg_id", "") or "").strip()
        if not kg_id:
            continue
        key = kg_id.lower()
        if key in seen:
            continue
        seen.add(key)
        resolved.append(kg_id)
    return resolved


def _seed_label_lookup(
    seed_kg_ids: Sequence[str],
    *,
    db: Optional[Neo4jGraphDB],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for seed in _clean_seed_ids(seed_kg_ids):
        detail = node_details(seed, db=db, include_neighbors=False)
        if detail is None:
            out[seed] = seed
            continue
        out[seed] = str(detail.label or seed).strip() or seed
    return out


def _wow_method_families_for_text(text: Any) -> list[str]:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return []
    out: list[str] = []
    for family, hints in _WOW_METHOD_FAMILY_HINTS.items():
        if any(hint in normalized for hint in hints):
            out.append(family)
    return out


def _coerce_candidate_rows(
    payload: Any,
    *,
    keys: Sequence[str],
) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping):
        for key in keys:
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, Mapping)]
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    return []


def find_contradiction_frontiers(
    *,
    query: str | None = None,
    seed_kg_ids: Sequence[str] | None = None,
    relation_types: Sequence[str] | None = None,
    limit: int = 10,
    max_evidence: int = 80,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    """Find contradiction-heavy frontiers around a query/seed neighborhood."""

    warnings: list[str] = []
    client = db or get_default_db()
    limit_i = _coerce_bounded_int(
        limit,
        default=10,
        min_value=1,
        max_value=100,
        field_name="limit",
        warnings=warnings,
    )
    max_evidence_i = _coerce_bounded_int(
        max_evidence,
        default=80,
        min_value=1,
        max_value=500,
        field_name="max_evidence",
        warnings=warnings,
    )
    seeds = _resolve_wow_seed_ids(query=query, seed_kg_ids=seed_kg_ids, db=client)
    seed_labels = _seed_label_lookup(seeds, db=client)

    hypothesis_text = str(query or "").strip()
    if not hypothesis_text and len(seeds) >= 2:
        ordered = list(seed_labels.values())[:2]
        hypothesis_text = f"{ordered[0]} is related to {ordered[1]}"
    elif not hypothesis_text and len(seeds) == 1:
        hypothesis_text = f"{next(iter(seed_labels.values()), seeds[0])} has internally conflicting evidence"

    evidence: list[dict[str, Any]] = []
    source_mode = "verify_hypothesis"
    if hypothesis_text:
        verified = verify_hypothesis(
            hypothesis=hypothesis_text,
            entity_hints=seeds or list(seed_labels.values()) or None,
            max_evidence=max_evidence_i,
            strictness="high_recall",
            include_subgraph=False,
            include_path_details=False,
            db=client,
        )
        for key in (
            "supporting_evidence",
            "conflicting_evidence",
            "uncertain_evidence",
            "neutral_evidence",
        ):
            rows = verified.get(key) or []
            if isinstance(rows, list):
                evidence.extend(row for row in rows if isinstance(row, Mapping))
        if isinstance(verified.get("warnings"), list):
            warnings.extend(str(item) for item in verified["warnings"])
    else:
        source_mode = "neighbor_scan"
        for seed in seeds:
            for row in neighbors(
                seed,
                relation_types=relation_types,
                limit=max(limit_i * 5, 20),
                db=client,
            ):
                if not isinstance(row, Mapping):
                    continue
                props = dict(row.get("properties") or {})
                claim_text = str(
                    props.get("text")
                    or props.get("main_assumption_text")
                    or row.get("label")
                    or row.get("kg_id")
                    or ""
                ).strip()
                if not claim_text:
                    continue
                evidence.append(
                    {
                        "publication": {
                            "kg_id": seed,
                            "label": seed_labels.get(seed, seed),
                        },
                        "polarity": props.get("claim_polarity")
                        or props.get("polarity"),
                        "score": row.get("score"),
                        "claim": {
                            "text": claim_text,
                            "claim_kind": props.get("claim_kind"),
                            "main_assumption_text": props.get("main_assumption_text"),
                            "assumption_type": props.get("assumption_type"),
                            "defaultness_score": props.get("defaultness_score"),
                            "challengeability_score": props.get(
                                "challengeability_score"
                            ),
                        },
                        "relation_type": row.get("relation"),
                    }
                )

    buckets: dict[str, dict[str, Any]] = {}
    for row in evidence:
        publication = (
            row.get("publication")
            if isinstance(row.get("publication"), Mapping)
            else {}
        )
        claim = row.get("claim") if isinstance(row.get("claim"), Mapping) else {}
        claim_text = str(claim.get("text") or "").strip()
        assumption_text = str(
            claim.get("main_assumption_text") or claim.get("assumption_text") or ""
        ).strip()
        bucket_key = (
            assumption_text or claim_text or str(publication.get("kg_id") or "").strip()
        )
        if not bucket_key:
            continue
        polarity = _normalize_claim_polarity(row.get("polarity"))
        relation_type = (
            str(row.get("relation_type") or claim.get("claim_kind") or "")
            .strip()
            .lower()
        )
        score = _clip01(_safe_float(row.get("score"), 0.0))
        bucket = buckets.setdefault(
            bucket_key,
            {
                "frontier_label": bucket_key,
                "claim_text": claim_text or None,
                "broken_default_assumption": assumption_text or None,
                "assumption_type": str(claim.get("assumption_type") or "").strip()
                or None,
                "defaultness_score": _clip01(
                    _safe_float(claim.get("defaultness_score"), 0.0)
                ),
                "challengeability_score": _clip01(
                    _safe_float(claim.get("challengeability_score"), 0.0)
                ),
                "support_count": 0,
                "conflict_count": 0,
                "null_result_count": 0,
                "failed_replication_count": 0,
                "publication_ids": set(),
                "publication_labels": set(),
                "seed_kg_ids": set(),
            },
        )
        pub_id = str(publication.get("kg_id") or "").strip()
        pub_label = str(publication.get("label") or pub_id).strip()
        if pub_id:
            bucket["publication_ids"].add(pub_id)
        if pub_label:
            bucket["publication_labels"].add(pub_label)
        if relation_type in {"failed_replication", "failed_replication_of"}:
            bucket["failed_replication_count"] += 1
        elif relation_type in {"null_result", "null_result_for"}:
            bucket["null_result_count"] += 1
        if polarity == "supports":
            bucket["support_count"] += 1
        elif polarity == "refutes":
            bucket["conflict_count"] += 1
        for seed in seeds:
            if seed and (
                seed == pub_id
                or seed in claim_text
                or seed_labels.get(seed, "") in claim_text
            ):
                bucket["seed_kg_ids"].add(seed)
        bucket["defaultness_score"] = max(
            bucket["defaultness_score"],
            _clip01(_safe_float(claim.get("defaultness_score"), 0.0)),
        )
        bucket["challengeability_score"] = max(
            bucket["challengeability_score"],
            _clip01(_safe_float(claim.get("challengeability_score"), 0.0)),
        )
        bucket.setdefault("_score_accumulator", 0.0)
        bucket["_score_accumulator"] += score

    frontiers: list[dict[str, Any]] = []
    for bucket in buckets.values():
        total_polarized = int(bucket["support_count"]) + int(bucket["conflict_count"])
        contradiction_density = min(
            int(bucket["support_count"]), int(bucket["conflict_count"])
        ) / max(1, total_polarized)
        frontier_score = _clip01(
            (0.45 * contradiction_density)
            + (0.20 * min(1.0, int(bucket["failed_replication_count"])))
            + (0.15 * min(1.0, int(bucket["null_result_count"])))
            + (0.10 * _safe_float(bucket.get("defaultness_score"), 0.0))
            + (0.10 * _safe_float(bucket.get("challengeability_score"), 0.0))
        )
        if frontier_score <= 0.0:
            continue
        contradiction_signature = (
            f"support/conflict={bucket['support_count']}/{bucket['conflict_count']}; "
            f"null={bucket['null_result_count']}; "
            f"failed_replication={bucket['failed_replication_count']}"
        )
        frontiers.append(
            {
                "frontier_label": bucket["frontier_label"],
                "claim_text": bucket.get("claim_text"),
                "broken_default_assumption": bucket.get("broken_default_assumption"),
                "assumption_type": bucket.get("assumption_type"),
                "defaultness_score": round(
                    _safe_float(bucket.get("defaultness_score"), 0.0), 6
                ),
                "challengeability_score": round(
                    _safe_float(bucket.get("challengeability_score"), 0.0), 6
                ),
                "support_count": int(bucket["support_count"]),
                "conflict_count": int(bucket["conflict_count"]),
                "null_result_count": int(bucket["null_result_count"]),
                "failed_replication_count": int(bucket["failed_replication_count"]),
                "publication_count": len(bucket["publication_ids"]),
                "publication_labels": sorted(bucket["publication_labels"])[:5],
                "seed_kg_ids": sorted(bucket["seed_kg_ids"]) or list(seeds),
                "contradiction_density": round(_clip01(contradiction_density), 6),
                "frontier_score": round(frontier_score, 6),
                "contradiction_score": round(frontier_score, 6),
                "contradiction_signature": contradiction_signature,
            }
        )

    frontiers.sort(
        key=lambda item: (
            -_safe_float(item.get("frontier_score"), 0.0),
            -int(item.get("publication_count") or 0),
            str(item.get("frontier_label") or ""),
        )
    )
    if not frontiers:
        warnings.append("No contradiction frontiers detected")

    return {
        "ok": True,
        "mode": "contradiction_frontiers",
        "source_mode": source_mode,
        "seed_kg_ids": seeds,
        "seed_labels": seed_labels,
        "frontiers": frontiers[:limit_i],
        "summary": {
            "n_input_evidence": len(evidence),
            "n_frontiers": min(len(frontiers), limit_i),
        },
        "warnings": warnings,
    }


def mine_assumption_cracks(
    *,
    query: str | None = None,
    seed_kg_ids: Sequence[str] | None = None,
    contradiction_frontiers: Mapping[str, Any]
    | Sequence[Mapping[str, Any]]
    | None = None,
    limit: int = 10,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    """Mine default assumptions that appear challengeable from contradictions."""

    warnings: list[str] = []
    client = db or get_default_db()
    limit_i = _coerce_bounded_int(
        limit,
        default=10,
        min_value=1,
        max_value=100,
        field_name="limit",
        warnings=warnings,
    )
    seeds = _resolve_wow_seed_ids(query=query, seed_kg_ids=seed_kg_ids, db=client)
    seed_labels = _seed_label_lookup(seeds, db=client)
    frontier_rows = _coerce_candidate_rows(
        contradiction_frontiers,
        keys=("frontiers", "items"),
    )
    if not frontier_rows:
        frontier_rows = list(
            find_contradiction_frontiers(
                query=query,
                seed_kg_ids=seeds,
                limit=max(limit_i, 5),
                db=client,
            ).get("frontiers")
            or []
        )

    cracks: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for row in frontier_rows:
        assumption_text = str(
            row.get("broken_default_assumption")
            or row.get("main_assumption_text")
            or ""
        ).strip()
        if not assumption_text:
            continue
        key = assumption_text.lower()
        if key in seen_texts:
            continue
        seen_texts.add(key)
        assumption_type = (
            str(row.get("assumption_type") or "default").strip() or "default"
        )
        defaultness_score = _clip01(_safe_float(row.get("defaultness_score"), 0.0))
        challengeability_score = _clip01(
            _safe_float(row.get("challengeability_score"), 0.0)
        )
        weakening_evidence = str(
            row.get("contradiction_signature")
            or f"Contradictory evidence accumulates around {row.get('frontier_label') or 'this claim'}."
        ).strip()
        if assumption_type == "sufficiency":
            minimal_test = f"Test whether the claimed effect still holds when {assumption_text.lower()} is explicitly relaxed."
        elif assumption_type == "necessity":
            minimal_test = f"Violate {assumption_text.lower()} and compare whether the main effect disappears."
        elif assumption_type == "measurement_proxy":
            minimal_test = f"Replace the proxy implied by {assumption_text.lower()} with an orthogonal measurement and compare conclusions."
        else:
            topic = str(
                query or next(iter(seed_labels.values()), "the target claim")
            ).strip()
            minimal_test = f"Run a minimal falsification test that breaks {assumption_text.lower()} while keeping the rest of {topic} fixed."
        cracks.append(
            {
                "assumption_text": assumption_text,
                "assumption_type": assumption_type,
                "defaultness_score": round(defaultness_score, 6),
                "challengeability_score": round(challengeability_score, 6),
                "assumption_crack_score": round(
                    _clip01(
                        (0.45 * defaultness_score)
                        + (0.35 * challengeability_score)
                        + (0.20 * _safe_float(row.get("frontier_score"), 0.0))
                    ),
                    6,
                ),
                "why_default": (
                    f"This appears to be a field default because it is embedded in the claim framing around {row.get('frontier_label') or 'the topic'}."
                ),
                "weakening_evidence": weakening_evidence,
                "minimal_falsification_test": minimal_test,
                "publication_count": int(row.get("publication_count") or 0),
                "seed_kg_ids": list(row.get("seed_kg_ids") or seeds),
                "touched_domains": [
                    label for label in list(seed_labels.values())[:3] if label
                ],
                "supporting_nodes": [
                    {"node_type": "Publication", "label": label}
                    for label in list(row.get("publication_labels") or [])[:3]
                ],
                "broken_default_assumption": assumption_text,
                "contradiction_signature": str(
                    row.get("contradiction_signature") or ""
                ).strip()
                or None,
            }
        )

    if not cracks:
        warnings.append("No assumption cracks detected")

    cracks.sort(
        key=lambda item: (
            -_safe_float(item.get("assumption_crack_score"), 0.0),
            -_safe_float(item.get("challengeability_score"), 0.0),
            str(item.get("assumption_text") or ""),
        )
    )
    return {
        "ok": True,
        "mode": "assumption_cracks",
        "seed_kg_ids": seeds,
        "seed_labels": seed_labels,
        "cracks": cracks[:limit_i],
        "summary": {
            "n_cracks": min(len(cracks), limit_i),
        },
        "warnings": warnings,
    }


def find_analogy_transfers(
    *,
    query: str | None = None,
    seed_kg_ids: Sequence[str] | None = None,
    relation_types: Sequence[str] | None = None,
    limit: int = 10,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    """Find method-family transfers that appear absent in the target neighborhood."""

    warnings: list[str] = []
    client = db or get_default_db()
    limit_i = _coerce_bounded_int(
        limit,
        default=10,
        min_value=1,
        max_value=100,
        field_name="limit",
        warnings=warnings,
    )
    seeds = _resolve_wow_seed_ids(query=query, seed_kg_ids=seed_kg_ids, db=client)
    seed_labels = _seed_label_lookup(seeds, db=client)
    local_nodes: list[dict[str, Any]] = []
    local_families: set[str] = set()
    for seed in seeds:
        detail = node_details(seed, db=client, include_neighbors=False)
        if detail is not None and detail.node_type in {"Method", "Tool", "Workflow"}:
            local_nodes.append(
                {
                    "kg_id": detail.kg_id,
                    "label": detail.label,
                    "node_type": detail.node_type,
                }
            )
            local_families.update(_wow_method_families_for_text(detail.label))
        for row in neighbors(
            seed,
            relation_types=relation_types,
            limit=max(limit_i * 6, 30),
            db=client,
        ):
            if not isinstance(row, Mapping):
                continue
            node_type = str(row.get("node_type") or "").strip()
            if node_type not in {"Method", "Tool", "Workflow"}:
                continue
            local_nodes.append(
                {
                    "kg_id": str(row.get("kg_id") or "").strip(),
                    "label": str(row.get("label") or row.get("kg_id") or "").strip(),
                    "node_type": node_type,
                }
            )
            local_families.update(_wow_method_families_for_text(row.get("label")))

    transfers: list[dict[str, Any]] = []
    local_ids = {str(row.get("kg_id") or "").strip() for row in local_nodes}
    target_context = (
        ", ".join(list(seed_labels.values())[:2])
        or str(query or "the target problem").strip()
    )
    for family, hints in _WOW_METHOD_FAMILY_HINTS.items():
        if family in local_families:
            continue
        hits: list[KGNodeSummary] = []
        seen_hit_ids: set[str] = set()
        for hint in hints[:2]:
            for row in search_nodes(
                hint,
                node_types=["Method", "Tool", "Workflow"],
                limit=5,
                db=client,
            ):
                kg_id = str(row.kg_id or "").strip()
                if not kg_id or kg_id in local_ids or kg_id in seen_hit_ids:
                    continue
                seen_hit_ids.add(kg_id)
                hits.append(row)
            if hits:
                break
        if not hits:
            continue
        source = hits[0]
        family_label = family.replace("_", " ")
        transfers.append(
            {
                "method_family": family,
                "source_kg_id": source.kg_id,
                "source_label": source.label,
                "source_type": source.node_type,
                "target_context": target_context,
                "transfer_signature": (
                    f"{family_label} is present in {source.label} but absent around {target_context}"
                ),
                "minimal_test": (
                    f"Apply a minimal {family_label} baseline to {target_context} and compare against the current default analysis."
                ),
                "falsifier": (
                    f"Reject the transfer if adding {family_label} does not improve explanatory power for {target_context}."
                ),
                "transfer_score": round(
                    _clip01(
                        0.45 + (0.10 * min(len(hits), 3)) + (0.10 if seeds else 0.0)
                    ),
                    6,
                ),
                "supporting_nodes": [
                    {
                        "kg_id": row.kg_id,
                        "label": row.label,
                        "node_type": row.node_type,
                    }
                    for row in hits[:3]
                ],
                "touched_domains": [row.node_type for row in hits[:3]]
                + [label for label in list(seed_labels.values())[:2] if label],
                "seed_kg_ids": list(seeds),
            }
        )

    if not transfers:
        warnings.append("No analogy transfers detected")

    transfers.sort(
        key=lambda item: (
            -_safe_float(item.get("transfer_score"), 0.0),
            str(item.get("method_family") or ""),
        )
    )
    return {
        "ok": True,
        "mode": "analogy_transfers",
        "seed_kg_ids": seeds,
        "seed_labels": seed_labels,
        "transfers": transfers[:limit_i],
        "summary": {
            "n_transfers": min(len(transfers), limit_i),
            "n_local_method_nodes": len(local_nodes),
        },
        "warnings": warnings,
    }


def synthesize_wow_candidate_cards(
    *,
    query: str | None = None,
    seed_kg_ids: Sequence[str] | None = None,
    contradiction_frontiers: Mapping[str, Any]
    | Sequence[Mapping[str, Any]]
    | None = None,
    assumption_cracks: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    analogy_transfers: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Synthesize wow-style candidate cards from contradictions, assumptions, and transfers."""

    warnings: list[str] = []
    limit_i = _coerce_bounded_int(
        limit,
        default=5,
        min_value=1,
        max_value=20,
        field_name="limit",
        warnings=warnings,
    )
    seeds = _clean_seed_ids(seed_kg_ids)
    frontiers = _coerce_candidate_rows(
        contradiction_frontiers, keys=("frontiers", "items")
    )
    cracks = _coerce_candidate_rows(assumption_cracks, keys=("cracks", "items"))
    transfers = _coerce_candidate_rows(analogy_transfers, keys=("transfers", "items"))

    raw_candidates: list[dict[str, Any]] = []
    for idx, row in enumerate(cracks, start=1):
        assumption_text = str(row.get("assumption_text") or "").strip()
        if not assumption_text:
            continue
        minimal_test = str(row.get("minimal_falsification_test") or "").strip()
        raw_candidates.append(
            {
                "card_id": f"wow_assumption_{idx:02d}",
                "title": f"{assumption_text} assumption crack",
                "hypothesis": (
                    f"The field may be overcommitted to the assumption that {assumption_text.lower()}."
                ),
                "taste_axis": "wow_assumption_crack",
                "minimal_discriminating_test": minimal_test,
                "falsifier_hint": minimal_test,
                "minimal_test": minimal_test,
                "falsifier": minimal_test,
                "contradiction_score": row.get("assumption_crack_score"),
                "challengeability_score": row.get("challengeability_score"),
                "defaultness_score": row.get("defaultness_score"),
                "publication_count": row.get("publication_count"),
                "supporting_nodes": row.get("supporting_nodes"),
                "touched_domains": row.get("touched_domains"),
                "seed_kg_ids": row.get("seed_kg_ids") or seeds,
                "broken_default_assumption": row.get("broken_default_assumption")
                or assumption_text,
                "contradiction_signature": row.get("contradiction_signature"),
                "why_this_is_not_just_a_bridge": (
                    f"This directly challenges a default field assumption instead of only connecting neighboring concepts: {assumption_text}."
                ),
                "provenance": {
                    "source_stage": "assumption_cracks",
                    "query": query,
                },
            }
        )
    for idx, row in enumerate(frontiers, start=1):
        signature = str(row.get("contradiction_signature") or "").strip()
        if not signature:
            continue
        label = str(row.get("frontier_label") or f"frontier_{idx}").strip()
        minimal_test = f"Discriminate between competing explanations around {label} using a targeted replication or intervention."
        raw_candidates.append(
            {
                "card_id": f"wow_contradiction_{idx:02d}",
                "title": f"{label} contradiction frontier",
                "hypothesis": (
                    f"The contradictory evidence around {label} may reflect a broken hidden assumption rather than ordinary noise."
                ),
                "taste_axis": "wow_contradiction",
                "minimal_discriminating_test": minimal_test,
                "falsifier_hint": minimal_test,
                "minimal_test": minimal_test,
                "falsifier": minimal_test,
                "contradiction_score": row.get("frontier_score"),
                "publication_count": row.get("publication_count"),
                "supporting_nodes": [
                    {"node_type": "Publication", "label": label}
                    for label in list(row.get("publication_labels") or [])[:3]
                ],
                "touched_domains": list(row.get("publication_labels") or [])[:2],
                "seed_kg_ids": row.get("seed_kg_ids") or seeds,
                "broken_default_assumption": row.get("broken_default_assumption"),
                "contradiction_signature": signature,
                "why_this_is_not_just_a_bridge": (
                    f"This is anchored in an observed contradiction signature, not a simple neighbor bridge: {signature}."
                ),
                "provenance": {
                    "source_stage": "contradiction_frontiers",
                    "query": query,
                },
            }
        )
    for idx, row in enumerate(transfers, start=1):
        transfer_signature = str(row.get("transfer_signature") or "").strip()
        if not transfer_signature:
            continue
        minimal_test = str(row.get("minimal_test") or "").strip()
        raw_candidates.append(
            {
                "card_id": f"wow_transfer_{idx:02d}",
                "title": f"{str(row.get('method_family') or 'method').replace('_', ' ')} transfer",
                "hypothesis": (
                    f"Apply {str(row.get('method_family') or 'this method').replace('_', ' ')} to {row.get('target_context') or query or 'the target problem'}."
                ),
                "taste_axis": "wow_analogy_transfer",
                "minimal_discriminating_test": minimal_test,
                "falsifier_hint": str(row.get("falsifier") or minimal_test).strip(),
                "minimal_test": minimal_test,
                "falsifier": str(row.get("falsifier") or minimal_test).strip(),
                "transfer_score": row.get("transfer_score"),
                "supporting_nodes": row.get("supporting_nodes"),
                "touched_domains": row.get("touched_domains"),
                "seed_kg_ids": row.get("seed_kg_ids") or seeds,
                "transfer_signature": transfer_signature,
                "why_this_is_not_just_a_bridge": (
                    f"This imports a method family that is absent in the local neighborhood: {transfer_signature}."
                ),
                "provenance": {
                    "source_stage": "analogy_transfers",
                    "query": query,
                },
            }
        )

    if not raw_candidates:
        warnings.append("No wow candidates synthesized")
        return {
            "ok": True,
            "mode": "wow_candidate_cards",
            "seed_kg_ids": seeds,
            "candidate_cards": [],
            "summary": {"n_candidates": 0},
            "warnings": warnings,
        }

    ranked = _rank_wow_candidates(raw_candidates)
    candidate_cards = ranked[:limit_i]
    return {
        "ok": True,
        "mode": "wow_candidate_cards",
        "seed_kg_ids": seeds,
        "candidate_cards": candidate_cards,
        "summary": {
            "n_candidates": len(candidate_cards),
            "n_vetoed": sum(1 for row in ranked if row.get("vetoed")),
        },
        "warnings": warnings,
    }


def sample_ood_hypothesis(
    seed_kg_ids: Sequence[str] | None,
    *,
    relation_types: Sequence[str] | None = None,
    limit: int = 5,
    taste: dict[str, Any] | None = None,
    leverage_items: Sequence[dict[str, Any]] | None = None,
    leverage_context: dict[str, Any] | None = None,
    principle_state: dict[str, Any] | None = None,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    """Generate deterministic OOD hypothesis candidates from leverage ranking."""
    warnings: list[str] = []
    input_seeds = _clean_seed_ids(seed_kg_ids)
    scoring = _normalize_taste_scoring(taste)
    verification_settings = _resolve_ood_verification_settings()
    limit_i = _coerce_bounded_int(
        limit,
        default=5,
        min_value=1,
        max_value=100,
        field_name="limit",
        warnings=warnings,
    )

    result: dict[str, Any] = {
        "ok": True,
        "mode": "ood_hypothesis_sampling",
        "input_seed_kg_ids": input_seeds,
        "seed_kg_ids": input_seeds,
        "hypotheses": [],
        "vetoed_candidates": [],
        "summary": {
            "n_input_seeds": len(input_seeds),
            "n_requested": limit_i,
            "n_hypotheses": 0,
            "n_returned": 0,
            "n_quality_passed": 0,
            "n_rejected_pre_synthesis": 0,
            "n_rejected_post_synthesis": 0,
            "n_rewrite_failed": 0,
            "n_vetoed": 0,
            "n_collapsed_duplicate_candidates": 0,
        },
        "taste": scoring,
        "diagnostics": {
            "candidate_collapse": {
                "duplicates_removed": 0,
                "clusters_collapsed": 0,
            },
            "ood_verification": {
                "budget_ms": int(verification_settings["total_timeout_ms"]),
                "search_timeout_ms": int(verification_settings["search_timeout_ms"]),
                "max_stores": int(verification_settings["max_stores"]),
                "pair_top_k": int(verification_settings["pair_top_k"]),
                "context_top_k": int(verification_settings["context_top_k"]),
                "partial_return": False,
                "stop_reason": None,
                "candidates_considered": 0,
                "candidates_verified": 0,
                "gfs_calls_total": 0,
                "gfs_latency_ms_total": 0.0,
                "verification_status_counts": {},
                "verification_reason_counts": {},
            },
        },
        "warnings": warnings,
    }

    if not input_seeds:
        warnings.append("No seed_kg_ids provided")
        return result

    client = db or get_default_db()
    leverage: dict[str, Any] | None = None
    leverage_rows = [
        dict(item) for item in (leverage_items or []) if isinstance(item, dict)
    ]
    precomputed_context = _coerce_precomputed_leverage_context(
        leverage_context,
        leverage_rows,
    )
    if leverage_rows:
        result["seed_kg_ids"] = list(
            precomputed_context.get("seed_kg_ids") or input_seeds
        )
        if precomputed_context.get("semantic_seed_labels"):
            result["semantic_seed_labels"] = dict(
                precomputed_context.get("semantic_seed_labels") or {}
            )
        if precomputed_context.get("semantic_seed_types"):
            result["semantic_seed_types"] = dict(
                precomputed_context.get("semantic_seed_types") or {}
            )
        if precomputed_context.get("semantic_seed_scores"):
            result["semantic_seed_scores"] = dict(
                precomputed_context.get("semantic_seed_scores") or {}
            )
        if precomputed_context.get("seed_provenance"):
            result["seed_provenance"] = dict(
                precomputed_context.get("seed_provenance") or {}
            )
        if precomputed_context.get("rejections"):
            result["rejections"] = dict(precomputed_context.get("rejections") or {})
        result["summary"]["n_rejected_pre_synthesis"] = int(
            (precomputed_context.get("summary") or {}).get("n_rejected") or 0
        )
    else:
        leverage = find_structural_leverage(
            input_seeds,
            relation_types=relation_types,
            limit=max(limit_i * 3, limit_i),
            taste=scoring,
            db=client,
        )
        warnings.extend(leverage.get("warnings") or [])
        result["seed_kg_ids"] = list(leverage.get("seed_kg_ids") or input_seeds)
        if leverage.get("semantic_seed_labels"):
            result["semantic_seed_labels"] = dict(
                leverage.get("semantic_seed_labels") or {}
            )
        if leverage.get("semantic_seed_types"):
            result["semantic_seed_types"] = dict(
                leverage.get("semantic_seed_types") or {}
            )
        if leverage.get("seed_provenance"):
            result["seed_provenance"] = dict(leverage.get("seed_provenance") or {})
        if leverage.get("rejections"):
            result["rejections"] = dict(leverage.get("rejections") or {})
        result["summary"]["n_rejected_pre_synthesis"] = int(
            (leverage.get("summary") or {}).get("n_rejected") or 0
        )
        leverage_rows = list(leverage.get("items") or [])

    if not leverage_rows:
        warnings.append("No leverage items available for OOD sampling")
        return result

    for rank_before, row in enumerate(leverage_rows, start=1):
        if isinstance(row, dict):
            row["rank_before_rerank"] = rank_before

    reranked_leverage, principle_metadata = _rerank_leverage_items(
        principle_state,
        leverage_rows,
    )
    if reranked_leverage:
        leverage_rows = reranked_leverage
    for rank_after, row in enumerate(leverage_rows, start=1):
        if isinstance(row, dict):
            row["rank_after_rerank"] = rank_after
    leverage_rows, duplicate_rows = _collapse_ood_candidate_clusters(leverage_rows)
    if duplicate_rows:
        collapse_diagnostics = (
            result.get("diagnostics", {}).get("candidate_collapse")
            if isinstance(result.get("diagnostics"), dict)
            else None
        )
        if isinstance(collapse_diagnostics, dict):
            collapse_diagnostics["duplicates_removed"] = len(duplicate_rows)
            collapse_diagnostics["clusters_collapsed"] = len(
                {
                    str(row.get("representative_kg_id") or "").strip()
                    for row in duplicate_rows
                    if str(row.get("representative_kg_id") or "").strip()
                }
            )
        result["summary"]["n_collapsed_duplicate_candidates"] = len(duplicate_rows)
    if principle_metadata:
        result.update(principle_metadata)
    anomaly_flags = []
    if principle_state and isinstance(principle_state.get("anomaly_flags"), list):
        anomaly_flags = list(principle_state.get("anomaly_flags") or [])
        result["anomaly_flags"] = anomaly_flags

    seed_context = leverage or precomputed_context
    seeds = list((seed_context or {}).get("seed_kg_ids") or input_seeds)
    seed_labels: dict[str, str] = dict(
        (seed_context or {}).get("semantic_seed_labels") or {}
    )
    seed_types: dict[str, str] = dict(
        (seed_context or {}).get("semantic_seed_types") or {}
    )
    for seed in seeds:
        detail = node_details(seed, db=client, include_neighbors=False)
        if detail is None:
            continue
        resolved_label = _coalesce_node_label(
            detail.label,
            (detail.properties or {}).get("name") if detail.properties else None,
            (detail.properties or {}).get("title") if detail.properties else None,
            seed,
        )
        existing_label = str(seed_labels.get(seed) or "").strip()
        existing_type = str(seed_types.get(seed) or "").strip()
        label_is_noise = False
        if existing_label:
            label_is_noise, _ = _looks_like_noise_candidate(
                existing_label,
                node_type=existing_type or str(detail.node_type or "Node"),
            )
        if not existing_label or existing_label == seed or label_is_noise:
            seed_labels[seed] = resolved_label
        seed_types.setdefault(seed, str(detail.node_type or "Node"))

    hypotheses: list[dict[str, Any]] = []
    vetoed_candidates: list[dict[str, Any]] = []
    candidates_ordered: list[dict[str, Any]] = []
    for duplicate in duplicate_rows:
        if not isinstance(duplicate, dict):
            continue
        item = duplicate.get("item")
        if not isinstance(item, dict):
            continue
        audit_row = _build_ood_candidate_audit_row(
            item,
            candidate_label=str(item.get("label") or item.get("kg_id") or "").strip(),
            candidate_type=str(
                item.get("candidate_type") or item.get("node_type") or "Concept"
            ),
            verification_status="collapsed",
            verification_reason="duplicate_cluster_filtered",
        )
        representative_kg_id = str(duplicate.get("representative_kg_id") or "").strip()
        representative_label = str(duplicate.get("representative_label") or "").strip()
        if representative_kg_id:
            audit_row["cluster_representative_kg_id"] = representative_kg_id
        if representative_label:
            audit_row["cluster_representative_label"] = representative_label
        candidates_ordered.append(audit_row)
    post_synthesis_rejections = 0
    semantic_downranked = 0
    verification_diagnostics = (
        result.get("diagnostics", {}).get("ood_verification")
        if isinstance(result.get("diagnostics"), dict)
        else None
    )
    verification_deadline = time.monotonic() + (
        float(verification_settings["total_timeout_ms"]) / 1000.0
    )
    for idx, item in enumerate(leverage_rows, start=1):
        if len(hypotheses) >= limit_i:
            break
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("kg_id") or "").strip()
        if not candidate_id:
            continue
        candidate_type = str(
            item.get("candidate_type") or item.get("node_type") or "Concept"
        )
        if not _is_output_ood_node_type(candidate_type):
            post_synthesis_rejections += 1
            candidates_ordered.append(
                _build_ood_candidate_audit_row(
                    item,
                    candidate_label=str(item.get("label") or candidate_id),
                    candidate_type=candidate_type,
                    verification_status="rejected",
                    verification_reason="candidate_type_filtered",
                )
            )
            continue
        touched = item.get("seeds_touched") or seeds
        anchor_seed = str(touched[0] if touched else seeds[0])
        verification_support_seed = _select_ood_verification_support_seed(
            touched_seeds=touched,
            fallback_seeds=seeds,
            seed_types=seed_types,
            seed_labels=seed_labels,
            candidate_type=candidate_type,
            exclude_ids={anchor_seed, candidate_id},
        )
        anchor_label = seed_labels.get(anchor_seed, anchor_seed)
        anchor_type = seed_types.get(anchor_seed, "Node")
        if not anchor_label or anchor_label == anchor_seed or anchor_type == "Node":
            anchor_detail = node_details(
                anchor_seed, db=client, include_neighbors=False
            )
            if anchor_detail is not None:
                anchor_label = _coalesce_node_label(
                    anchor_detail.label,
                    (anchor_detail.properties or {}).get("name")
                    if anchor_detail.properties
                    else None,
                    (anchor_detail.properties or {}).get("title")
                    if anchor_detail.properties
                    else None,
                    anchor_seed,
                )
                anchor_type = str(anchor_detail.node_type or anchor_type or "Node")
                seed_labels[anchor_seed] = anchor_label
                seed_types[anchor_seed] = anchor_type
        verification_anchor_nodes = [
            {"kg_id": anchor_seed, "label": anchor_label, "node_type": anchor_type}
        ]
        if verification_support_seed:
            support_label = str(
                seed_labels.get(verification_support_seed) or verification_support_seed
            ).strip()
            support_type = (
                str(
                    seed_types.get(verification_support_seed)
                    or _infer_ood_hint_node_type(verification_support_seed)
                ).strip()
                or "Node"
            )
            verification_anchor_nodes.append(
                {
                    "kg_id": verification_support_seed,
                    "label": support_label,
                    "node_type": support_type,
                }
            )
        candidate_label = str(item.get("label") or candidate_id)
        relations = item.get("relations") or []
        relation_hint = str(relations[0] if relations else "RELATED_TO")
        novelty = _safe_float(item.get("novelty_score"), 0.0)
        leverage_score = _safe_float(item.get("leverage_score"), 0.0)
        score_breakdown = dict(item.get("score_breakdown") or {})
        draft = _build_ood_candidate_draft(
            anchor_label=anchor_label,
            anchor_type=anchor_type,
            candidate_label=candidate_label,
            candidate_type=candidate_type,
            relation_hint=relation_hint,
            score_breakdown=score_breakdown,
        )
        draft_ok, draft_reasons = _assess_ood_hypothesis_draft(
            draft,
            anchor_label=anchor_label,
            candidate_label=candidate_label,
        )
        if not draft_ok:
            post_synthesis_rejections += 1
            candidates_ordered.append(
                _build_ood_candidate_audit_row(
                    item,
                    candidate_label=candidate_label,
                    candidate_type=candidate_type,
                    verification_status="rejected",
                    verification_reason="pre_synthesis_quality_gate",
                )
            )
            continue
        rewritten, rewrite_mode = _maybe_llm_rewrite_ood_candidate(draft)
        rewritten_ok, rewritten_reasons = _assess_ood_hypothesis_draft(
            rewritten,
            anchor_label=anchor_label,
            candidate_label=candidate_label,
        )
        if not rewritten_ok:
            post_synthesis_rejections += 1
            vetoed_candidates.append(
                {
                    "candidate_kg_id": candidate_id,
                    "candidate_label": candidate_label,
                    "verification_status": "vetoed",
                    "verification_reason": "post_synthesis_quality_gate",
                    "quality_reasons": rewritten_reasons or draft_reasons,
                }
            )
            candidates_ordered.append(
                _build_ood_candidate_audit_row(
                    item,
                    candidate_label=candidate_label,
                    candidate_type=candidate_type,
                    verification_status="vetoed",
                    verification_reason="post_synthesis_quality_gate",
                )
            )
            continue
        semantic_triage = _triage_ood_candidate_semantics(
            anchor_id=anchor_seed,
            candidate_id=candidate_id,
            anchor_label=anchor_label,
            candidate_label=candidate_label,
            anchor_type=anchor_type,
            candidate_type=candidate_type,
            claim_type=str(
                rewritten.get("claim_type") or draft.get("claim_type") or ""
            ),
            mechanism=str(rewritten.get("mechanism") or draft.get("mechanism") or ""),
        )
        item = dict(item)
        item["semantic_triage_decision"] = str(
            semantic_triage.get("decision") or "pass"
        ).strip()
        item["semantic_triage_reasons"] = list(semantic_triage.get("reasons") or [])
        item["semantic_penalty"] = round(
            _safe_float(semantic_triage.get("penalty"), 0.0),
            6,
        )
        triage_decision = str(semantic_triage.get("decision") or "pass").strip()
        semantic_penalty = _clip01(_safe_float(semantic_triage.get("penalty"), 0.0))
        if triage_decision == "kill":
            post_synthesis_rejections += 1
            candidates_ordered.append(
                _build_ood_candidate_audit_row(
                    item,
                    candidate_label=candidate_label,
                    candidate_type=candidate_type,
                    verification_status="rejected",
                    verification_reason="pre_synthesis_semantic_veto",
                )
            )
            continue
        if triage_decision == "downrank" and semantic_penalty > 0.0:
            semantic_downranked += 1
            item["leverage_score"] = round(
                _clip01(_safe_float(item.get("leverage_score"), 0.0) - semantic_penalty),
                6,
            )
            item["novelty_score"] = round(
                _clip01(
                    _safe_float(item.get("novelty_score"), 0.0)
                    - (semantic_penalty * 0.5)
                ),
                6,
            )
            if item.get("principle_score") is not None:
                item["principle_score"] = round(
                    _clip01(
                        _safe_float(item.get("principle_score"), 0.0)
                        - semantic_penalty
                    ),
                    6,
                )
            score_breakdown["semantic_penalty"] = round(semantic_penalty, 6)
            score_breakdown["semantic_triage_decision"] = triage_decision
            score_breakdown["semantic_triage_reasons"] = list(
                semantic_triage.get("reasons") or []
            )
        if rewrite_mode != "llm" and os.getenv(
            "BR_KG_OOD_LLM_REWRITE", ""
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            result["summary"]["n_rewrite_failed"] = (
                int(result["summary"].get("n_rewrite_failed") or 0) + 1
            )
        if isinstance(verification_diagnostics, dict):
            verification_diagnostics["candidates_considered"] = (
                int(verification_diagnostics.get("candidates_considered") or 0) + 1
            )
        if _ood_budget_exhausted(verification_deadline):
            warnings.append(
                "OOD verification budget exhausted; returning partial sampled hypotheses"
            )
            if isinstance(verification_diagnostics, dict):
                verification_diagnostics["partial_return"] = True
                verification_diagnostics["stop_reason"] = "budget_exhausted"
            candidates_ordered.append(
                _build_ood_candidate_audit_row(
                    item,
                    candidate_label=candidate_label,
                    candidate_type=candidate_type,
                    verification_status="unverified",
                    verification_reason="gfs_budget_exhausted",
                )
            )
            break
        verification = _verify_ood_candidate_with_gfs(
            anchor_label=anchor_label,
            candidate_label=candidate_label,
            candidate_type=candidate_type,
            claim_type=str(
                rewritten.get("claim_type") or draft.get("claim_type") or ""
            ),
            score_breakdown=score_breakdown,
            deadline_monotonic=verification_deadline,
            max_stores=int(verification_settings["max_stores"]),
            search_timeout_ms=int(verification_settings["search_timeout_ms"]),
            pair_top_k=int(verification_settings["pair_top_k"]),
            context_top_k=int(verification_settings["context_top_k"]),
        )
        verification_status = str(
            verification.get("verification_status") or "unverified"
        )
        verification_reason = str(verification.get("verification_reason") or "unknown")
        verification_meta = verification.get("verification_diagnostics") or {}
        stop_after_candidate = verification_reason == "gfs_budget_exhausted"
        if isinstance(verification_diagnostics, dict):
            verification_diagnostics["candidates_verified"] = (
                int(verification_diagnostics.get("candidates_verified") or 0) + 1
            )
            verification_diagnostics["gfs_calls_total"] = int(
                verification_diagnostics.get("gfs_calls_total") or 0
            ) + int(
                _safe_float(
                    ((verification_meta.get("pair_search") or {}).get("call_count")),
                    0.0,
                )
                + _safe_float(
                    ((verification_meta.get("context_search") or {}).get("call_count")),
                    0.0,
                )
            )
            verification_diagnostics["gfs_latency_ms_total"] = round(
                _safe_float(
                    verification_diagnostics.get("gfs_latency_ms_total"),
                    0.0,
                )
                + _safe_float(
                    ((verification_meta.get("pair_search") or {}).get("latency_ms")),
                    0.0,
                )
                + _safe_float(
                    ((verification_meta.get("context_search") or {}).get("latency_ms")),
                    0.0,
                ),
                3,
            )
            status_counts = verification_diagnostics.setdefault(
                "verification_status_counts", {}
            )
            status_counts[verification_status] = (
                int(_safe_float(status_counts.get(verification_status), 0.0)) + 1
            )
            reason_counts = verification_diagnostics.setdefault(
                "verification_reason_counts", {}
            )
            reason_counts[verification_reason] = (
                int(_safe_float(reason_counts.get(verification_reason), 0.0)) + 1
            )
        if verification.get("verification_status") == "vetoed":
            vetoed_candidates.append(
                {
                    "candidate_kg_id": candidate_id,
                    "candidate_label": candidate_label,
                    "claim_type": str(
                        rewritten.get("claim_type") or draft.get("claim_type") or ""
                    ),
                    "verification_status": "vetoed",
                    "verification_reason": verification_reason,
                    "verification_evidence": verification.get("verification_evidence")
                    or {},
                    "verification_diagnostics": verification_meta,
                }
            )
            candidates_ordered.append(
                _build_ood_candidate_audit_row(
                    item,
                    candidate_label=candidate_label,
                    candidate_type=candidate_type,
                    verification_status="vetoed",
                    verification_reason=verification_reason,
                )
            )
            continue
        verification_hints = _build_hypothesis_testing_hint_bundle(
            {
                "seed_kg_id": anchor_seed,
                "anchor_label": anchor_label,
                "anchor_type": anchor_type,
                "candidate_kg_id": candidate_id,
                "candidate_label": candidate_label,
                "candidate_type": candidate_type,
                "anchor_nodes": [
                    *verification_anchor_nodes,
                    {
                        "kg_id": candidate_id,
                        "label": candidate_label,
                        "node_type": candidate_type,
                    },
                ],
            }
        )
        hypotheses.append(
            {
                "rank": idx,
                "seed_kg_id": anchor_seed,
                "anchor_label": anchor_label,
                "anchor_type": anchor_type,
                "candidate_kg_id": candidate_id,
                "candidate_label": candidate_label,
                "candidate_type": candidate_type,
                "claim_type": str(
                    rewritten.get("claim_type") or draft.get("claim_type") or "bridge"
                ),
                "statement": rewritten["statement"],
                "hypothesis_sentence": rewritten.get("hypothesis_sentence")
                or rewritten["statement"],
                "mechanism": rewritten["mechanism"],
                "independent_variable": rewritten.get("independent_variable") or "",
                "dependent_variable": rewritten.get("dependent_variable") or "",
                "control_condition": rewritten.get("control_condition") or "",
                "predicted_direction": rewritten.get("predicted_direction")
                or rewritten["prediction"],
                "prediction": rewritten["prediction"],
                "minimal_test": rewritten["minimal_test"],
                "falsifier": rewritten["falsifier"],
                "rewrite_mode": rewrite_mode,
                "relation_hint": relation_hint,
                "verification_status": verification_status,
                "verification_reason": verification_reason,
                "verification_evidence": verification.get("verification_evidence")
                or {},
                "verification_diagnostics": verification_meta,
                "anchor_nodes": [
                    {"kg_id": anchor_seed, "label": anchor_label},
                    {"kg_id": candidate_id, "label": candidate_label},
                ],
                "quality_flags": item.get("quality_flags") or [],
                "novelty_score": round(_clip01(novelty), 6),
                "contradiction_score": round(
                    _clip01(_safe_float(item.get("contradiction_score"), 0.0)),
                    6,
                ),
                "coherence_score": round(
                    _clip01(_safe_float(item.get("coherence_score"), 0.0)),
                    6,
                ),
                "feasibility_score": round(
                    _clip01(_safe_float(item.get("feasibility_score"), 0.0)),
                    6,
                ),
                "ood_score": round(_clip01(leverage_score), 6),
                "score_breakdown": score_breakdown,
                "principle_score": item.get("principle_score"),
                "semantic_triage_decision": item.get("semantic_triage_decision"),
                "semantic_triage_reasons": item.get("semantic_triage_reasons") or [],
                "semantic_penalty": round(
                    _safe_float(item.get("semantic_penalty"), 0.0),
                    6,
                ),
                "principle_session_key": result.get("principle_session_key"),
                "active_principle_id": result.get("active_principle_id"),
                "selection_reason": result.get("selection_reason"),
                "anomaly_flags": list(anomaly_flags),
                "verification_hints": verification_hints,
            }
        )
        candidates_ordered.append(
            _build_ood_candidate_audit_row(
                item,
                candidate_label=candidate_label,
                candidate_type=candidate_type,
                verification_status=verification_status,
                verification_reason=verification_reason,
            )
        )
        if stop_after_candidate:
            warnings.append(
                "OOD verification budget exhausted mid-candidate; returning partial sampled hypotheses"
            )
            if isinstance(verification_diagnostics, dict):
                verification_diagnostics["partial_return"] = True
                verification_diagnostics["stop_reason"] = "budget_exhausted"
            break

    hypotheses.sort(
        key=lambda item: (
            -float(item.get("principle_score") or 0.0),
            -float(item.get("ood_score") or 0.0),
            -float(item.get("novelty_score") or 0.0),
            str(item.get("candidate_kg_id") or ""),
        )
    )
    for idx, item in enumerate(hypotheses, start=1):
        item["rank"] = idx

    result["hypotheses"] = hypotheses
    result["vetoed_candidates"] = vetoed_candidates
    candidates_ordered.sort(
        key=lambda item: (
            int(item.get("rank_after_rerank") or 0),
            int(item.get("rank_before_rerank") or 0),
            str(item.get("candidate_kg_id") or ""),
        )
    )
    result["candidates_ordered"] = candidates_ordered
    result["summary"]["n_hypotheses"] = len(hypotheses)
    result["summary"]["n_returned"] = len(hypotheses)
    result["summary"]["n_quality_passed"] = len(hypotheses)
    result["summary"]["n_rejected_post_synthesis"] = post_synthesis_rejections
    result["summary"]["n_semantic_downranked"] = semantic_downranked
    result["summary"]["n_vetoed"] = len(vetoed_candidates)
    if isinstance(verification_diagnostics, dict):
        result["summary"]["gfs_calls_total"] = int(
            verification_diagnostics.get("gfs_calls_total") or 0
        )
        result["summary"]["verification_status_counts"] = dict(
            verification_diagnostics.get("verification_status_counts") or {}
        )
        result["summary"]["verification_reason_counts"] = dict(
            verification_diagnostics.get("verification_reason_counts") or {}
        )
    if not hypotheses:
        warnings.append("No OOD hypotheses generated")
    return result


def _build_hypothesis_testing_hint_bundle(candidate: dict[str, Any]) -> dict[str, Any]:
    exact_candidates: list[dict[str, Any]] = []
    anchor_exact_ids: list[str] = []
    label_candidates: list[tuple[str, str]] = []
    seed_kg_id = str(candidate.get("seed_kg_id") or "").strip()
    candidate_kg_id = str(candidate.get("candidate_kg_id") or "").strip()
    candidate_type = str(candidate.get("candidate_type") or "").strip()

    def _append_label_hint(value: Any, node_type: Any = None) -> None:
        text = str(value or "").strip()
        if not text:
            return
        canonical_type = _canonical_ood_node_type(node_type)
        label_candidates.append((text, canonical_type))

    typed_exact_fields = (
        ("seed_kg_id", "anchor_type", "anchor_label", "seed"),
        ("candidate_kg_id", "candidate_type", "candidate_label", "candidate"),
    )
    for id_key, type_key, label_key, source in typed_exact_fields:
        value = str(candidate.get(id_key) or "").strip()
        node_type = _infer_ood_hint_node_type(value, candidate.get(type_key))
        if value:
            anchor_exact_ids.append(value)
            if (
                node_type in _VERIFY_EXACT_FAST_PATH_TYPES
                and not _is_publication_like_entity_hint(value)
            ):
                exact_candidates.append(
                    {
                        "value": value,
                        "node_type": node_type,
                        "source": source,
                        "source_rank": 0 if source == "seed" else 1,
                        "ordinal": 0,
                        "dataset_like": _is_dataset_like_entity_hint(value, node_type),
                        "partner_rank": _rank_ood_verification_partner(
                            value=value,
                            node_type=node_type,
                            candidate_type=candidate_type,
                            has_label=bool(str(candidate.get(label_key) or "").strip()),
                        ),
                    }
                )
        _append_label_hint(candidate.get(label_key), node_type)

    for ordinal, node in enumerate(candidate.get("anchor_nodes") or []):
        if not isinstance(node, dict):
            continue
        kg_id = str(node.get("kg_id") or "").strip()
        node_type = _infer_ood_hint_node_type(kg_id, node.get("node_type"))
        if kg_id:
            anchor_exact_ids.append(kg_id)
            if (
                node_type in _VERIFY_EXACT_FAST_PATH_TYPES
                and not _is_publication_like_entity_hint(kg_id)
            ):
                exact_candidates.append(
                    {
                        "value": kg_id,
                        "node_type": node_type,
                        "source": "anchor",
                        "source_rank": 2,
                        "ordinal": ordinal,
                        "dataset_like": _is_dataset_like_entity_hint(kg_id, node_type),
                        "partner_rank": _rank_ood_verification_partner(
                            value=kg_id,
                            node_type=node_type,
                            candidate_type=candidate_type,
                            has_label=bool(str(node.get("label") or "").strip()),
                        ),
                    }
                )
        label = str(node.get("label") or "").strip()
        if label and label.lower() != kg_id.lower():
            _append_label_hint(label, node_type)

    exact_entries: list[dict[str, Any]] = []
    seen_exact_values: set[str] = set()
    for entry in exact_candidates:
        value = str(entry.get("value") or "").strip()
        if not value or value in seen_exact_values:
            continue
        seen_exact_values.add(value)
        exact_entries.append(entry)

    exact_ids = [str(entry.get("value") or "") for entry in exact_entries]
    exact_types: list[str] = []
    seen_exact_types: set[str] = set()
    for entry in exact_entries:
        node_type = str(entry.get("node_type") or "").strip()
        if node_type in {"", "Node"}:
            continue
        if node_type not in seen_exact_types:
            seen_exact_types.add(node_type)
            exact_types.append(node_type)

    label_hints = _clean_seed_ids([value for value, _ in label_candidates])
    label_types: list[str] = []
    seen_label_types: set[str] = set()
    for _, node_type in label_candidates:
        if node_type in {"", "Node"}:
            continue
        if node_type not in seen_label_types:
            seen_label_types.add(node_type)
            label_types.append(node_type)

    anchor_exact_cleaned = _clean_seed_ids(anchor_exact_ids)
    non_publication_anchor_ids = [
        exact_id
        for exact_id in anchor_exact_cleaned
        if not _is_publication_like_entity_hint(exact_id)
    ]
    non_publication_non_dataset_anchor_ids = [
        exact_id
        for exact_id in non_publication_anchor_ids
        if not _is_dataset_like_entity_hint(exact_id)
    ]

    candidate_exact_entry = next(
        (entry for entry in exact_entries if entry.get("value") == candidate_kg_id),
        None,
    )
    seed_exact_entry = next(
        (entry for entry in exact_entries if entry.get("value") == seed_kg_id),
        None,
    )
    support_exact_entries = [
        entry
        for entry in exact_entries
        if entry.get("value") not in {candidate_kg_id, seed_kg_id}
    ]
    support_exact_entries.sort(
        key=lambda entry: (
            tuple(entry.get("partner_rank") or (99, 99, 99)),
            int(entry.get("source_rank") or 99),
            int(entry.get("ordinal") or 0),
        )
    )
    preferred_support_entry = (
        support_exact_entries[0] if support_exact_entries else None
    )

    preferred_pair_entries: list[dict[str, Any]] | None = None
    if (
        candidate_exact_entry
        and preferred_support_entry
        and not bool(preferred_support_entry.get("dataset_like"))
    ):
        preferred_pair_entries = [candidate_exact_entry, preferred_support_entry]
    elif (
        candidate_exact_entry
        and seed_exact_entry
        and not bool(seed_exact_entry.get("dataset_like"))
    ):
        preferred_pair_entries = [seed_exact_entry, candidate_exact_entry]
    elif candidate_exact_entry and preferred_support_entry:
        preferred_pair_entries = [candidate_exact_entry, preferred_support_entry]
    elif candidate_exact_entry and seed_exact_entry:
        preferred_pair_entries = [seed_exact_entry, candidate_exact_entry]

    entity_hints: list[str]
    allowed_node_types: list[str]
    quality = "none"
    strategy = "empty"

    if preferred_pair_entries and len(preferred_pair_entries) >= 2:
        entity_hints = _clean_seed_ids(
            [str(entry.get("value") or "") for entry in preferred_pair_entries]
        )
        allowed_node_types = _clean_seed_ids(
            [
                str(entry.get("node_type") or "")
                for entry in preferred_pair_entries
                if str(entry.get("node_type") or "").strip() not in {"", "Node"}
            ]
        )
        quality = "exact_pair"
        strategy = "exact_fast_path"
    elif len(exact_ids) >= 2:
        entity_hints = exact_ids[:2]
        allowed_node_types = _clean_seed_ids(exact_types[:2])
        quality = "exact_pair"
        strategy = "exact_fast_path"
    elif len(non_publication_non_dataset_anchor_ids) >= 2:
        entity_hints = non_publication_non_dataset_anchor_ids[:2]
        allowed_node_types = exact_types
        quality = "exact_pair_untyped"
        strategy = "anchor_exact_ids"
    elif len(non_publication_anchor_ids) >= 2:
        entity_hints = non_publication_anchor_ids[:2]
        allowed_node_types = exact_types
        quality = "exact_pair_untyped"
        strategy = "anchor_exact_ids"
    elif exact_ids:
        entity_hints = exact_ids
        allowed_node_types = exact_types
        quality = "exact_single"
        strategy = "single_exact_id"
    elif len(label_hints) >= 2:
        entity_hints = label_hints
        allowed_node_types = label_types
        quality = "label_pair"
        strategy = "label_pair"
    elif label_hints:
        entity_hints = label_hints
        allowed_node_types = label_types
        quality = "label_single"
        strategy = "label_single"
    else:
        entity_hints = []
        allowed_node_types = []

    return {
        "entity_hints": entity_hints,
        "allowed_node_types": allowed_node_types,
        "quality": quality,
        "quality_score": _ENTITY_HINT_QUALITY_SCORES[quality],
        "strategy": strategy,
        "entity_hint_count": len(entity_hints),
        "exact_hint_count": len(exact_ids),
        "label_hint_count": len(label_hints),
    }


def _build_hypothesis_testing_entity_hints(candidate: dict[str, Any]) -> list[str]:
    return list(
        _build_hypothesis_testing_hint_bundle(candidate).get("entity_hints") or []
    )


def verify_sampled_hypotheses(
    sampled_hypotheses: Sequence[dict[str, Any]] | None,
    *,
    query: str | None = None,
    seed_kg_ids: Sequence[str] | None = None,
    verify_top_k: int | None = None,
    strictness: str = "high_recall",
    allowed_node_types: Sequence[str] | None = None,
    max_evidence: int = 60,
    max_paths: int = 60,
    min_evidence_score: float | None = None,
    include_subgraph: bool = False,
    include_path_details: bool = False,
    confidence_scoring_version: str = "v2",
    candidate_lane_mode: str = "broad",
    use_external_literature: bool = False,
    external_literature_top_k: int = 5,
    external_literature_recency_days: int = 365,
    external_literature_exclude_domains: Sequence[str] | None = None,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    started = time.perf_counter()
    trace_enabled = os.getenv("BR_KG_VERIFY_TRACE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    } or os.getenv("BR_GRANDMASTER_STEP_TRACE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    cleaned_seeds = _clean_seed_ids(seed_kg_ids)
    verify_limit_i = _coerce_bounded_int(
        verify_top_k if verify_top_k is not None else len(sampled_hypotheses or []),
        default=max(1, len(sampled_hypotheses or [])),
        min_value=1,
        max_value=100,
        field_name="verify_top_k",
        warnings=warnings,
    )
    max_evidence_i = _coerce_bounded_int(
        max_evidence,
        default=60,
        min_value=1,
        max_value=200,
        field_name="max_evidence",
        warnings=warnings,
    )
    result: dict[str, Any] = {
        "ok": True,
        "mode": "verify_sampled_hypotheses",
        "query": str(query or "").strip() or None,
        "input_seed_kg_ids": cleaned_seeds,
        "seed_kg_ids": cleaned_seeds,
        "candidate_lane_mode": _normalize_candidate_lane_mode(candidate_lane_mode),
        "tested_hypotheses": [],
        "evidence_items": [],
        "diagnostics": {
            "total_duration_s": 0.0,
            "candidate_wall_clock_s_total": 0.0,
            "phase_totals_s": {
                "entity_resolution": 0.0,
                "semantic_rerank": 0.0,
                "direct_evidence_collection": 0.0,
                "typed_path_evidence_collection": 0.0,
                "family_fallback_lookup": 0.0,
                "family_fallback_evidence_collection": 0.0,
                "aggregation": 0.0,
                "total": 0.0,
            },
            "per_hypothesis": [],
        },
        "summary": {
            "n_input_hypotheses": len(sampled_hypotheses or []),
            "n_tested": 0,
            "n_verify_failed": 0,
            "n_supported": 0,
            "n_mixed": 0,
            "n_insufficient_evidence": 0,
            "n_conflicting": 0,
            "n_uncertain": 0,
            "entity_hint_quality_counts": {},
            "mean_entity_hint_quality_score": 0.0,
            "mean_evidence_item_count": 0.0,
            "external_literature_requested": bool(use_external_literature),
        },
        "warnings": warnings,
    }
    if not sampled_hypotheses:
        warnings.append("No sampled_hypotheses provided")
        result["diagnostics"]["total_duration_s"] = round(
            time.perf_counter() - started,
            4,
        )
        return result

    client = db or get_default_db()
    aggregated_evidence: list[dict[str, Any]] = []
    hint_quality_scores: list[float] = []
    evidence_item_counts: list[int] = []
    hint_quality_counts: dict[str, int] = {}
    diagnostics = result["diagnostics"]
    phase_totals = diagnostics["phase_totals_s"]
    for candidate in list(sampled_hypotheses)[:verify_limit_i]:
        if not isinstance(candidate, dict):
            continue
        candidate_started = time.perf_counter()
        candidate_id = (
            str(
                candidate.get("candidate_kg_id")
                or candidate.get("candidate_label")
                or ""
            ).strip()
            or "<unknown>"
        )
        hint_bundle = (
            dict(candidate.get("verification_hints"))
            if isinstance(candidate.get("verification_hints"), Mapping)
            else _build_hypothesis_testing_hint_bundle(candidate)
        )
        entity_hints = list(hint_bundle.get("entity_hints") or [])
        derived_allowed_types = _clean_seed_ids(
            [str(value) for value in (hint_bundle.get("allowed_node_types") or [])]
        )
        merged_allowed_types = _clean_seed_ids(
            [
                *derived_allowed_types,
                *(list(allowed_node_types) if allowed_node_types else []),
            ]
        )
        hint_quality = str(hint_bundle.get("quality") or "none").strip() or "none"
        hint_quality_score = float(
            _safe_float(
                hint_bundle.get("quality_score"),
                _ENTITY_HINT_QUALITY_SCORES.get(hint_quality, 0.0),
            )
        )
        hypothesis_text = str(
            candidate.get("statement")
            or candidate.get("hypothesis")
            or candidate.get("text")
            or ""
        ).strip()
        if trace_enabled:
            logger.info(
                "verify_sampled_hypotheses.candidate.start candidate=%s rank=%s hint_quality=%s text_len=%s",
                candidate_id,
                candidate.get("rank"),
                hint_quality,
                len(hypothesis_text),
            )
        if not hypothesis_text:
            result["summary"]["n_verify_failed"] = (
                int(result["summary"].get("n_verify_failed") or 0) + 1
            )
            warnings.append("Skipped sampled hypothesis without statement text")
            candidate_wall = round(time.perf_counter() - candidate_started, 4)
            diagnostics["candidate_wall_clock_s_total"] = round(
                _safe_float(diagnostics.get("candidate_wall_clock_s_total"), 0.0)
                + candidate_wall,
                4,
            )
            diagnostics["per_hypothesis"].append(
                {
                    "rank": candidate.get("rank"),
                    "candidate_kg_id": candidate.get("candidate_kg_id"),
                    "candidate_label": candidate.get("candidate_label"),
                    "status": "error",
                    "entity_hint_quality": hint_quality,
                    "entity_hint_quality_score": round(hint_quality_score, 6),
                    "entity_hints_used_count": len(entity_hints),
                    "allowed_node_types_count": len(merged_allowed_types),
                    "wall_clock_s": candidate_wall,
                    "verification_error": "missing_statement_text",
                }
            )
            if trace_enabled:
                logger.info(
                    "verify_sampled_hypotheses.candidate.finish candidate=%s status=error wall_clock_s=%.4f error=%s",
                    candidate_id,
                    candidate_wall,
                    "missing_statement_text",
                )
            continue
        try:
            verification = verify_hypothesis(
                hypothesis=hypothesis_text,
                entity_hints=entity_hints or None,
                allowed_node_types=merged_allowed_types or None,
                max_evidence=max_evidence,
                max_paths=max_paths,
                strictness=strictness,
                min_evidence_score=min_evidence_score,
                include_subgraph=include_subgraph,
                include_path_details=include_path_details,
                confidence_scoring_version=confidence_scoring_version,
                candidate_lane_mode=candidate_lane_mode,
                use_external_literature=use_external_literature,
                external_literature_query=query,
                external_literature_top_k=external_literature_top_k,
                external_literature_recency_days=external_literature_recency_days,
                external_literature_exclude_domains=external_literature_exclude_domains,
                db=client,
            )
        except Exception as exc:
            result["summary"]["n_verify_failed"] = (
                int(result["summary"].get("n_verify_failed") or 0) + 1
            )
            warnings.append(
                f"verify_hypothesis failed for {candidate.get('candidate_kg_id') or candidate.get('candidate_label') or 'candidate'}: {exc}"
            )
            candidate_wall = round(time.perf_counter() - candidate_started, 4)
            diagnostics["candidate_wall_clock_s_total"] = round(
                _safe_float(diagnostics.get("candidate_wall_clock_s_total"), 0.0)
                + candidate_wall,
                4,
            )
            diagnostics["per_hypothesis"].append(
                {
                    "rank": candidate.get("rank"),
                    "candidate_kg_id": candidate.get("candidate_kg_id"),
                    "candidate_label": candidate.get("candidate_label"),
                    "status": "error",
                    "entity_hint_quality": hint_quality,
                    "entity_hint_quality_score": round(hint_quality_score, 6),
                    "entity_hints_used_count": len(entity_hints),
                    "allowed_node_types_count": len(merged_allowed_types),
                    "wall_clock_s": candidate_wall,
                    "verification_error": str(exc),
                }
            )
            result["tested_hypotheses"].append(
                {
                    "rank": candidate.get("rank"),
                    "candidate_kg_id": candidate.get("candidate_kg_id"),
                    "hypothesis": candidate,
                    "entity_hints_used": entity_hints,
                    "entity_hint_quality": hint_quality,
                    "entity_hint_quality_score": round(hint_quality_score, 6),
                    "entity_hint_strategy": str(hint_bundle.get("strategy") or "empty"),
                    "allowed_node_types_used": merged_allowed_types,
                    "kg_verification": None,
                    "verification_error": str(exc),
                }
            )
            if trace_enabled:
                logger.info(
                    "verify_sampled_hypotheses.candidate.finish candidate=%s status=error wall_clock_s=%.4f error=%s",
                    candidate_id,
                    candidate_wall,
                    str(exc),
                )
            continue

        verdict = str(verification.get("verdict") or "").strip().lower()
        verdict_key = (
            verdict
            if verdict
            in {
                "supported",
                "mixed",
                "insufficient_evidence",
                "conflicting",
                "uncertain",
            }
            else None
        )
        if verdict_key:
            summary_key = f"n_{verdict_key}"
            result["summary"][summary_key] = (
                int(result["summary"].get(summary_key) or 0) + 1
            )
        for evidence_key in (
            "supporting_evidence",
            "conflicting_evidence",
            "uncertain_evidence",
            "neutral_evidence",
        ):
            rows = verification.get(evidence_key) or []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict):
                    aggregated_evidence.append(row)
        evidence_item_count = sum(
            len(verification.get(evidence_key) or [])
            for evidence_key in (
                "supporting_evidence",
                "conflicting_evidence",
                "uncertain_evidence",
                "neutral_evidence",
            )
            if isinstance(verification.get(evidence_key), list)
        )
        verification["entity_hint_quality"] = hint_quality
        verification["entity_hint_quality_score"] = round(hint_quality_score, 6)
        verification["entity_hint_strategy"] = str(
            hint_bundle.get("strategy") or "empty"
        )
        verification["entity_hint_count"] = len(entity_hints)
        verification["allowed_node_types_used"] = merged_allowed_types
        verification["evidence_item_count"] = evidence_item_count
        verification_summary = dict(verification.get("summary") or {})
        verification_summary["entity_hint_quality"] = hint_quality
        verification_summary["entity_hint_quality_score"] = round(
            hint_quality_score,
            6,
        )
        verification_summary["entity_hint_count"] = len(entity_hints)
        verification_summary["allowed_node_types_count"] = len(merged_allowed_types)
        verification_summary["evidence_item_count"] = evidence_item_count
        verification["summary"] = verification_summary
        hint_quality_scores.append(hint_quality_score)
        evidence_item_counts.append(evidence_item_count)
        hint_quality_counts[hint_quality] = hint_quality_counts.get(hint_quality, 0) + 1
        verification_timings = (
            dict(verification.get("timings_s") or {})
            if isinstance(verification.get("timings_s"), Mapping)
            else {}
        )
        candidate_wall = round(time.perf_counter() - candidate_started, 4)
        diagnostics["candidate_wall_clock_s_total"] = round(
            _safe_float(diagnostics.get("candidate_wall_clock_s_total"), 0.0)
            + candidate_wall,
            4,
        )
        for field_name in phase_totals:
            phase_totals[field_name] = round(
                _safe_float(phase_totals.get(field_name), 0.0)
                + _safe_float(verification_timings.get(field_name), 0.0),
                4,
            )
        diagnostics["per_hypothesis"].append(
            {
                "rank": candidate.get("rank"),
                "candidate_kg_id": candidate.get("candidate_kg_id"),
                "candidate_label": candidate.get("candidate_label"),
                "status": "success",
                "verdict": verdict or None,
                "entity_hint_quality": hint_quality,
                "entity_hint_quality_score": round(hint_quality_score, 6),
                "entity_hints_used_count": len(entity_hints),
                "allowed_node_types_count": len(merged_allowed_types),
                "evidence_item_count": evidence_item_count,
                "n_candidate_publications": int(
                    verification_summary.get("n_candidate_publications") or 0
                ),
                "n_supporting": int(verification_summary.get("n_supporting") or 0),
                "n_conflicting": int(verification_summary.get("n_conflicting") or 0),
                "n_uncertain": int(verification_summary.get("n_uncertain") or 0),
                "n_neutral": int(verification_summary.get("n_neutral") or 0),
                "wall_clock_s": candidate_wall,
                "timings_s": {
                    key: round(_safe_float(verification_timings.get(key), 0.0), 4)
                    for key in (
                        "entity_resolution",
                        "semantic_rerank",
                        "direct_evidence_collection",
                        "typed_path_evidence_collection",
                        "family_fallback_lookup",
                        "family_fallback_evidence_collection",
                        "aggregation",
                        "total",
                    )
                    if verification_timings.get(key) is not None
                },
            }
        )
        result["tested_hypotheses"].append(
            {
                "rank": candidate.get("rank"),
                "candidate_kg_id": candidate.get("candidate_kg_id"),
                "hypothesis": candidate,
                "entity_hints_used": entity_hints,
                "entity_hint_quality": hint_quality,
                "entity_hint_quality_score": round(hint_quality_score, 6),
                "entity_hint_strategy": str(hint_bundle.get("strategy") or "empty"),
                "allowed_node_types_used": merged_allowed_types,
                "evidence_item_count": evidence_item_count,
                "kg_verification": verification,
            }
        )
        if trace_enabled:
            logger.info(
                "verify_sampled_hypotheses.candidate.finish candidate=%s status=success verdict=%s wall_clock_s=%.4f verify_total_s=%.4f",
                candidate_id,
                verdict or "unknown",
                candidate_wall,
                _safe_float(verification_timings.get("total"), 0.0),
            )

    result["summary"]["n_tested"] = len(result["tested_hypotheses"])
    result["evidence_items"] = aggregated_evidence[:max_evidence_i]
    result["summary"]["entity_hint_quality_counts"] = hint_quality_counts
    if hint_quality_scores:
        result["summary"]["mean_entity_hint_quality_score"] = round(
            sum(hint_quality_scores) / len(hint_quality_scores),
            6,
        )
    if evidence_item_counts:
        result["summary"]["mean_evidence_item_count"] = round(
            sum(evidence_item_counts) / len(evidence_item_counts),
            6,
        )
    diagnostics["total_duration_s"] = round(time.perf_counter() - started, 4)
    result["summary"]["verify_wall_clock_s"] = diagnostics["total_duration_s"]
    if not result["tested_hypotheses"]:
        warnings.append("No sampled hypotheses were verified")
    return result


def sample_and_verify_hypotheses(
    seed_kg_ids: Sequence[str] | None,
    *,
    query: str | None = None,
    relation_types: Sequence[str] | None = None,
    sample_limit: int = 5,
    verify_top_k: int | None = None,
    taste: dict[str, Any] | None = None,
    strictness: str = "high_recall",
    allowed_node_types: Sequence[str] | None = None,
    max_evidence: int = 60,
    max_paths: int = 60,
    min_evidence_score: float | None = None,
    include_subgraph: bool = False,
    include_path_details: bool = False,
    confidence_scoring_version: str = "v2",
    candidate_lane_mode: str = "broad",
    use_external_literature: bool = False,
    external_literature_top_k: int = 5,
    external_literature_recency_days: int = 365,
    external_literature_exclude_domains: Sequence[str] | None = None,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    """Generate structured hypotheses from exact-ID seeds and verify them with KG evidence."""
    warnings: list[str] = []
    cleaned_seeds = _clean_seed_ids(seed_kg_ids)
    sample_limit_i = _coerce_bounded_int(
        sample_limit,
        default=5,
        min_value=1,
        max_value=100,
        field_name="sample_limit",
        warnings=warnings,
    )
    verify_limit_i = _coerce_bounded_int(
        verify_top_k if verify_top_k is not None else sample_limit_i,
        default=sample_limit_i,
        min_value=1,
        max_value=100,
        field_name="verify_top_k",
        warnings=warnings,
    )

    result: dict[str, Any] = {
        "ok": True,
        "mode": "hypothesis_testing",
        "query": str(query or "").strip() or None,
        "input_seed_kg_ids": cleaned_seeds,
        "seed_kg_ids": cleaned_seeds,
        "candidate_lane_mode": _normalize_candidate_lane_mode(candidate_lane_mode),
        "sampled_hypotheses": [],
        "tested_hypotheses": [],
        "summary": {
            "n_input_seeds": len(cleaned_seeds),
            "n_sampled": 0,
            "n_returned": 0,
            "n_tested": 0,
            "n_verify_failed": 0,
            "n_supported": 0,
            "n_mixed": 0,
            "n_insufficient_evidence": 0,
            "n_conflicting": 0,
            "n_uncertain": 0,
        },
        "warnings": warnings,
    }
    if not cleaned_seeds:
        warnings.append("No seed_kg_ids provided")
        return result

    client = db or get_default_db()
    sampled = sample_ood_hypothesis(
        cleaned_seeds,
        relation_types=relation_types,
        limit=sample_limit_i,
        taste=taste,
        db=client,
    )
    result["seed_kg_ids"] = list(sampled.get("seed_kg_ids") or cleaned_seeds)
    result["sampled_hypotheses"] = list(sampled.get("hypotheses") or [])
    result["sampled_summary"] = dict(sampled.get("summary") or {})
    if sampled.get("vetoed_candidates"):
        result["vetoed_candidates"] = list(sampled.get("vetoed_candidates") or [])
    warnings.extend(sampled.get("warnings") or [])
    result["summary"]["n_sampled"] = len(result["sampled_hypotheses"])
    result["summary"]["n_returned"] = len(result["sampled_hypotheses"])
    verify_result = verify_sampled_hypotheses(
        list(result["sampled_hypotheses"]),
        query=query,
        seed_kg_ids=result["seed_kg_ids"],
        verify_top_k=verify_limit_i,
        strictness=strictness,
        allowed_node_types=allowed_node_types,
        max_evidence=max_evidence,
        max_paths=max_paths,
        min_evidence_score=min_evidence_score,
        include_subgraph=include_subgraph,
        include_path_details=include_path_details,
        confidence_scoring_version=confidence_scoring_version,
        candidate_lane_mode=candidate_lane_mode,
        use_external_literature=use_external_literature,
        external_literature_top_k=external_literature_top_k,
        external_literature_recency_days=external_literature_recency_days,
        external_literature_exclude_domains=external_literature_exclude_domains,
        db=client,
    )
    result["tested_hypotheses"] = list(verify_result.get("tested_hypotheses") or [])
    warnings.extend(verify_result.get("warnings") or [])
    for key, value in (verify_result.get("summary") or {}).items():
        if key.startswith("n_"):
            result["summary"][key] = value
    return result


def _parse_topology_update_reason(update_reason: str | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for chunk in str(update_reason or "").split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        key_norm = str(key or "").strip().lower()
        value_norm = str(value or "").strip()
        if not key_norm or not value_norm or value_norm.lower() == "na":
            continue
        parsed[key_norm] = value_norm
    return parsed


def _derive_topology_seed_ids_from_context(
    update_reason: str | None,
    *,
    client: Neo4jGraphDB,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    context = _parse_topology_update_reason(update_reason)
    if not context:
        return [], warnings

    raw_candidates: list[str] = []
    for key in ("baseline", "current", "scope"):
        value = context.get(key)
        if not value:
            continue
        detail = node_details(value, db=client)
        if detail is not None and detail.kg_id:
            raw_candidates.append(str(detail.kg_id))
            continue
        hits = search_nodes(value, limit=6, db=client, infer_types=True)
        raw_candidates.extend(
            str(hit.kg_id or "").strip() for hit in hits if str(hit.kg_id or "").strip()
        )

    cleaned_candidates = _clean_seed_ids(raw_candidates)
    if not cleaned_candidates:
        warnings.append("No topology context seeds resolved from update_reason")
        return [], warnings

    semantic_context = _resolve_semantic_seed_context(
        cleaned_candidates,
        db=client,
        relation_types=[
            "ABOUT",
            "IN_ONVOC",
            "MEASURES",
            "RELATED_TO",
            "SUPPORTS_MODALITY",
            "USES_TASK",
            "HAS_TASK",
        ],
        neighbor_limit=10,
    )
    warnings.extend(semantic_context.get("warnings") or [])
    derived = _clean_seed_ids(semantic_context.get("seed_kg_ids") or cleaned_candidates)
    if derived:
        warnings.append(
            f"Derived {len(derived)} topology seed(s) from baseline/current/scope context"
        )
    return derived, warnings


def detect_topology_shifts(
    seed_kg_ids: Sequence[str] | None = None,
    *,
    limit: int = 50,
    taste: dict[str, Any] | None = None,
    mode: str = "proposal",
    patch_id: str | None = None,
    update_reason: str | None = None,
    now_iso: str | None = None,
    db: Optional[Neo4jGraphDB] = None,
) -> dict[str, Any]:
    """Propose/apply read-safe edge-overlay taste-weight updates."""
    warnings: list[str] = []
    started = time.perf_counter()
    trace_enabled = os.getenv("BR_KG_TOPOLOGY_TRACE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    } or os.getenv("BR_GRANDMASTER_STEP_TRACE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    seeds = _clean_seed_ids(seed_kg_ids)
    scoring = _normalize_taste_scoring(taste)
    limit_i = _coerce_bounded_int(
        limit,
        default=50,
        min_value=1,
        max_value=500,
        field_name="limit",
        warnings=warnings,
    )

    mode_norm = str(mode or "proposal").strip().lower()
    if mode_norm not in {"proposal", "apply"}:
        warnings.append(f"Unsupported mode '{mode}', using proposal")
        mode_norm = "proposal"

    client = db or get_default_db()
    diagnostics: dict[str, Any] = {
        "total_duration_s": 0.0,
        "phase_totals_s": {
            "seed_derivation": 0.0,
            "scan_query": 0.0,
            "proposal_build": 0.0,
            "apply_writes": 0.0,
            "total": 0.0,
        },
        "scan_record_count": 0,
        "per_proposal": [],
    }
    if not seeds and update_reason:
        derive_started = time.perf_counter()
        derived_seeds, derived_warnings = _derive_topology_seed_ids_from_context(
            update_reason,
            client=client,
        )
        diagnostics["phase_totals_s"]["seed_derivation"] = round(
            time.perf_counter() - derive_started,
            4,
        )
        warnings.extend(derived_warnings)
        if derived_seeds:
            seeds = derived_seeds
    seed_filter = seeds or None
    if trace_enabled:
        logger.info(
            "detect_topology_shifts.start mode=%s seed_count=%s limit=%s",
            mode_norm,
            len(seeds),
            limit_i,
        )

    scan_cypher = """
    MATCH (a)-[r]->(b)
    WHERE ($seed_ids IS NULL OR
      coalesce(a.id, a.dataset_id, a.uid, a.identifier, elementId(a)) IN $seed_ids OR
      coalesce(b.id, b.dataset_id, b.uid, b.identifier, elementId(b)) IN $seed_ids)
    RETURN
      coalesce(a.id, a.dataset_id, a.uid, a.identifier, elementId(a)) AS source_id,
      coalesce(b.id, b.dataset_id, b.uid, b.identifier, elementId(b)) AS target_id,
      type(r) AS rel_type,
      coalesce(r.taste_weight, 0.5) AS taste_weight,
      coalesce(r.novelty_score, r.novelty, 0.5) AS novelty_score,
      coalesce(r.contradiction_score, r.contradiction, 0.0) AS contradiction_score,
      coalesce(r.evidence_quality_score, r.evidence_quality, 0.5) AS evidence_quality
    ORDER BY source_id, rel_type, target_id
    LIMIT $limit
    """

    try:
        scan_started = time.perf_counter()
        records = _as_list(
            client._run(
                scan_cypher,
                {
                    "seed_ids": seed_filter,
                    "limit": int(limit_i),
                },
            )
        )
        diagnostics["phase_totals_s"]["scan_query"] = round(
            time.perf_counter() - scan_started,
            4,
        )
    except Exception as exc:  # pragma: no cover - defensive
        diagnostics["phase_totals_s"]["scan_query"] = round(
            time.perf_counter() - scan_started,
            4,
        )
        warnings.append(f"Topology scan failed: {exc}")
        records = []
    diagnostics["scan_record_count"] = len(records)
    if trace_enabled:
        logger.info(
            "detect_topology_shifts.scan.finish mode=%s records=%s scan_query_s=%.4f",
            mode_norm,
            len(records),
            _safe_float(diagnostics["phase_totals_s"].get("scan_query"), 0.0),
        )

    proposals: list[dict[str, Any]] = []
    if records:
        proposal_started = time.perf_counter()
        w = scoring["weights"]
        for record in records:
            source_id = str(_rec_get(record, "source_id") or "").strip()
            target_id = str(_rec_get(record, "target_id") or "").strip()
            rel_type = str(_rec_get(record, "rel_type") or "").strip()
            if not source_id or not target_id or not rel_type:
                continue
            current_weight = _clip01(_safe_float(_rec_get(record, "taste_weight"), 0.5))
            novelty_score = _clip01(_safe_float(_rec_get(record, "novelty_score"), 0.5))
            contradiction_score = _clip01(
                _safe_float(_rec_get(record, "contradiction_score"), 0.0)
            )
            evidence_quality = _clip01(
                _safe_float(_rec_get(record, "evidence_quality"), 0.5)
            )
            target_weight = _clip01(
                w["novelty"] * novelty_score
                + w["contradiction"] * contradiction_score
                + w["evidence"] * evidence_quality
            )
            delta = round(target_weight - current_weight, 6)
            proposals.append(
                {
                    "edge": {
                        "source_id": source_id,
                        "target_id": target_id,
                        "rel_type": rel_type,
                    },
                    "current_weight": round(current_weight, 6),
                    "target_weight": round(target_weight, 6),
                    "delta": delta,
                    "signals": {
                        "novelty_score": round(novelty_score, 6),
                        "contradiction_score": round(contradiction_score, 6),
                        "evidence_quality": round(evidence_quality, 6),
                    },
                }
            )
        diagnostics["phase_totals_s"]["proposal_build"] = round(
            time.perf_counter() - proposal_started,
            4,
        )
    else:
        diagnostics["phase_totals_s"]["proposal_build"] = 0.0

    proposals.sort(
        key=lambda row: (
            -abs(_safe_float(row.get("delta"), 0.0)),
            -_safe_float(row.get("target_weight"), 0.0),
            str((row.get("edge") or {}).get("source_id") or ""),
            str((row.get("edge") or {}).get("rel_type") or ""),
            str((row.get("edge") or {}).get("target_id") or ""),
        )
    )
    proposals = proposals[:limit_i]
    diagnostics["per_proposal"] = [
        {
            "source_id": str((proposal.get("edge") or {}).get("source_id") or ""),
            "target_id": str((proposal.get("edge") or {}).get("target_id") or ""),
            "rel_type": str((proposal.get("edge") or {}).get("rel_type") or ""),
            "delta": round(_safe_float(proposal.get("delta"), 0.0), 6),
            "status": "proposal",
            "write_wall_clock_s": 0.0,
            "error": None,
        }
        for proposal in proposals
        if isinstance(proposal, dict)
    ]

    result: dict[str, Any] = {
        "ok": True,
        "mode": mode_norm,
        "seed_kg_ids": seeds,
        "taste": scoring,
        "proposals": proposals,
        "applied_count": 0,
        "summary": {
            "n_scanned": len(records),
            "n_proposals": len(proposals),
        },
        "diagnostics": diagnostics,
        "warnings": warnings,
    }
    if trace_enabled:
        logger.info(
            "detect_topology_shifts.proposals.finish mode=%s proposals=%s proposal_build_s=%.4f",
            mode_norm,
            len(proposals),
            _safe_float(diagnostics["phase_totals_s"].get("proposal_build"), 0.0),
        )

    if not proposals:
        warnings.append("No topology shift proposals generated")
        diagnostics["phase_totals_s"]["total"] = round(time.perf_counter() - started, 4)
        diagnostics["total_duration_s"] = diagnostics["phase_totals_s"]["total"]
        return result

    if mode_norm != "apply":
        diagnostics["phase_totals_s"]["total"] = round(time.perf_counter() - started, 4)
        diagnostics["total_duration_s"] = diagnostics["phase_totals_s"]["total"]
        return result

    reason = str(update_reason or "taste_overlay_topology_shift").strip()
    stable_patch_id = str(
        patch_id
        or _stable_taste_patch_id(
            seed_kg_ids=seeds,
            reason=reason,
            scoring=scoring,
        )
    )
    updated_at = str(now_iso or "1970-01-01T00:00:00Z")

    apply_cypher = """
    MATCH (a)-[r]->(b)
    WHERE coalesce(a.id, a.dataset_id, a.uid, a.identifier, elementId(a)) = $source_id
      AND coalesce(b.id, b.dataset_id, b.uid, b.identifier, elementId(b)) = $target_id
      AND type(r) = $rel_type
    SET
      r.taste_prev_weight = coalesce(r.taste_weight, $current_weight),
      r.taste_weight = $new_weight,
      r.taste_patch_id = $patch_id,
      r.taste_updated_at = $updated_at,
      r.taste_update_reason = $update_reason
    RETURN 1 AS updated
    """

    applied_count = 0
    diagnostics["per_proposal"] = []
    apply_started = time.perf_counter()
    for proposal in proposals:
        edge = proposal.get("edge") or {}
        params = {
            "source_id": str(edge.get("source_id") or ""),
            "target_id": str(edge.get("target_id") or ""),
            "rel_type": str(edge.get("rel_type") or ""),
            "current_weight": _clip01(_safe_float(proposal.get("current_weight"), 0.5)),
            "new_weight": _clip01(_safe_float(proposal.get("target_weight"), 0.5)),
            "patch_id": stable_patch_id,
            "updated_at": updated_at,
            "update_reason": reason,
        }
        if not params["source_id"] or not params["target_id"] or not params["rel_type"]:
            continue
        proposal_started = time.perf_counter()
        proposal_status = "skipped"
        proposal_error = None
        try:
            update_res = _as_list(client._run(apply_cypher, params))
            updated = False
            if update_res:
                updated = bool(_safe_float(_rec_get(update_res[0], "updated"), 0.0) > 0)
            else:
                # Some drivers may not return rows for successful writes.
                updated = True
            if updated:
                applied_count += 1
                proposal_status = "applied"
            else:
                proposal_status = "no_write"
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(
                "Failed to apply topology shift for "
                f"{params['source_id']} -[{params['rel_type']}]-> {params['target_id']}: {exc}"
            )
            proposal_status = "error"
            proposal_error = str(exc)
        proposal_wall = round(time.perf_counter() - proposal_started, 4)
        diagnostics["per_proposal"].append(
            {
                "source_id": params["source_id"],
                "target_id": params["target_id"],
                "rel_type": params["rel_type"],
                "delta": round(_safe_float(proposal.get("delta"), 0.0), 6),
                "status": proposal_status,
                "write_wall_clock_s": proposal_wall,
                "error": proposal_error,
            }
        )
        if trace_enabled:
            logger.info(
                "detect_topology_shifts.apply.finish source=%s rel=%s target=%s status=%s write_wall_clock_s=%.4f",
                params["source_id"],
                params["rel_type"],
                params["target_id"],
                proposal_status,
                proposal_wall,
            )
    diagnostics["phase_totals_s"]["apply_writes"] = round(
        time.perf_counter() - apply_started,
        4,
    )

    result["applied_count"] = applied_count
    result["patch"] = {
        "patch_id": stable_patch_id,
        "updated_at": updated_at,
        "update_reason": reason,
    }
    diagnostics["phase_totals_s"]["total"] = round(time.perf_counter() - started, 4)
    diagnostics["total_duration_s"] = diagnostics["phase_totals_s"]["total"]
    if trace_enabled:
        logger.info(
            "detect_topology_shifts.finish mode=%s proposals=%s applied=%s total_s=%.4f",
            mode_norm,
            len(proposals),
            applied_count,
            diagnostics["total_duration_s"],
        )
    return result


__all__ = [
    "DatasetResourceSummary",
    "DatasetOnvocLinkSummary",
    "DatasetSummary",
    "KGNodeSummary",
    "dataset_resources",
    "behavior_to_fmri_retrieval",
    "get_default_db",
    "list_dataset_onvoc_links",
    "node_details",
    "related_datasets",
    "neighbors",
    "search_datasets",
    "search_nodes",
    "multi_hop_traverse",
    "verify_hypothesis",
    "find_structural_leverage",
    "detect_contradiction_motifs",
    "find_contradiction_frontiers",
    "mine_assumption_cracks",
    "find_analogy_transfers",
    "synthesize_wow_candidate_cards",
    "sample_ood_hypothesis",
    "sample_and_verify_hypotheses",
    "detect_topology_shifts",
    "search_tools_structured",
    "resolve_tool_structured",
    "get_effect_size_priors",
    "get_method_compatibility",
    "QueryService",
]


# ---------------------------------------------------------------------------
# Service Wrapper
# ---------------------------------------------------------------------------


class QueryService:
    """Wrapper class for BR-KG query functions to satisfy tool dependencies."""

    def __init__(self, db: Optional[Neo4jGraphDB] = None):
        self._db = db

    @property
    def client(self) -> Neo4jGraphDB:
        return self._db or get_default_db()

    def execute_cypher(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[Any]:
        """Execute a raw Cypher query safely."""
        try:
            return _as_list(self.client._run(query, params or {}))
        except Exception as e:
            logger.error(f"Cypher execution failed: {e}")
            raise

    def search_nodes(
        self,
        query: str,
        *,
        node_types: Optional[Sequence[str]] = None,
        limit: int = 20,
        infer_types: bool = True,
        timeout_s: float | None = None,
    ) -> list[KGNodeSummary]:
        if timeout_s is None:
            return search_nodes(
                query,
                node_types=node_types,
                limit=limit,
                db=self._db,
                infer_types=infer_types,
            )
        try:
            return search_nodes(
                query,
                node_types=node_types,
                limit=limit,
                db=self._db,
                infer_types=infer_types,
                timeout_s=timeout_s,
            )
        except TypeError as exc:
            if "timeout_s" not in str(exc):
                raise
            return search_nodes(
                query,
                node_types=node_types,
                limit=limit,
                db=self._db,
                infer_types=infer_types,
            )

    def neighbors(
        self,
        kg_id: str,
        *,
        relation_types: Optional[Sequence[str]] = None,
        direction: str = "both",
        limit: int = 25,
        timeout_s: float | None = None,
    ) -> list[dict[str, Any]]:
        if timeout_s is None:
            return neighbors(
                kg_id,
                relation_types=relation_types,
                direction=direction,
                limit=limit,
                db=self._db,
            )
        try:
            return neighbors(
                kg_id,
                relation_types=relation_types,
                direction=direction,
                limit=limit,
                db=self._db,
                timeout_s=timeout_s,
            )
        except TypeError as exc:
            if "timeout_s" not in str(exc):
                raise
            return neighbors(
                kg_id,
                relation_types=relation_types,
                direction=direction,
                limit=limit,
                db=self._db,
            )

    def search_datasets(
        self,
        *,
        text: str | None = None,
        task_ids: Optional[Sequence[str]] = None,
        modality: str | None = None,
        min_subjects: int | None = None,
        species: str | None = None,
        limit: int = 20,
        infer_from_text: bool = True,
        timeout_s: float | None = None,
    ) -> list[DatasetSummary]:
        if timeout_s is None:
            return search_datasets(
                text=text,
                task_ids=task_ids,
                modality=modality,
                min_subjects=min_subjects,
                species=species,
                limit=limit,
                db=self._db,
                infer_from_text=infer_from_text,
            )
        try:
            return search_datasets(
                text=text,
                task_ids=task_ids,
                modality=modality,
                min_subjects=min_subjects,
                species=species,
                limit=limit,
                db=self._db,
                infer_from_text=infer_from_text,
                timeout_s=timeout_s,
            )
        except TypeError as exc:
            if "timeout_s" not in str(exc):
                raise
            return search_datasets(
                text=text,
                task_ids=task_ids,
                modality=modality,
                min_subjects=min_subjects,
                species=species,
                limit=limit,
                db=self._db,
                infer_from_text=infer_from_text,
            )

    def related_datasets(
        self,
        kg_id: str,
        *,
        limit: int = 10,
        timeout_s: float | None = None,
    ) -> list[DatasetSummary]:
        if timeout_s is None:
            return related_datasets(kg_id, limit=limit, db=self._db)
        try:
            return related_datasets(
                kg_id,
                limit=limit,
                db=self._db,
                timeout_s=timeout_s,
            )
        except TypeError as exc:
            if "timeout_s" not in str(exc):
                raise
            return related_datasets(kg_id, limit=limit, db=self._db)

    def behavior_to_fmri_retrieval(
        self,
        *,
        seed_id: str | None = None,
        label: str | None = None,
        name: str | None = None,
        limit: int = 12,
        max_maps: int = 20,
        max_paths: int = 20,
        max_regions_per_map: int = 8,
        max_behavior_neighbors: int = 4,
        min_behavior_similarity: float = 0.0,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        return behavior_to_fmri_retrieval(
            seed_id=seed_id,
            label=label,
            name=name,
            limit=limit,
            max_maps=max_maps,
            max_paths=max_paths,
            max_regions_per_map=max_regions_per_map,
            max_behavior_neighbors=max_behavior_neighbors,
            min_behavior_similarity=min_behavior_similarity,
            db=self._db,
            timeout_s=timeout_s,
        )

    def list_dataset_onvoc_links(
        self,
        *,
        onvoc_id: str | None = None,
        page: int = 1,
        page_size: int = 100,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        if timeout_s is None:
            return list_dataset_onvoc_links(
                onvoc_id=onvoc_id,
                page=page,
                page_size=page_size,
                db=self._db,
            )
        try:
            return list_dataset_onvoc_links(
                onvoc_id=onvoc_id,
                page=page,
                page_size=page_size,
                db=self._db,
                timeout_s=timeout_s,
            )
        except TypeError as exc:
            if "timeout_s" not in str(exc):
                raise
            return list_dataset_onvoc_links(
                onvoc_id=onvoc_id,
                page=page,
                page_size=page_size,
                db=self._db,
            )

    def node_details(
        self, kg_id: str, *, timeout_s: float | None = None
    ) -> Optional[KGNodeSummary]:
        if timeout_s is None:
            return node_details(kg_id, db=self._db)
        try:
            return node_details(kg_id, db=self._db, timeout_s=timeout_s)
        except TypeError as exc:
            if "timeout_s" not in str(exc):
                raise
            return node_details(kg_id, db=self._db)

    def multi_hop_traverse(
        self,
        start_kg_ids: list[str],
        *,
        max_hops: int = 3,
        allowed_edge_types: list[str] | None = None,
        target_kg_id: str | None = None,
        mode: str = "breadth_first",
        max_results: int = 50,
        db: Optional[Neo4jGraphDB] = None,
    ) -> dict[str, Any]:
        return multi_hop_traverse(
            start_kg_ids,
            max_hops=max_hops,
            allowed_edge_types=allowed_edge_types,
            target_kg_id=target_kg_id,
            mode=mode,
            max_results=max_results,
            db=db or self._db,
        )

    def verify_hypothesis(
        self,
        hypothesis: str,
        *,
        entity_hints: list[str] | None = None,
        allowed_node_types: list[str] | None = None,
        max_evidence: int = 60,
        max_paths: int = 60,
        strictness: str = "high_recall",
        min_evidence_score: float | None = None,
        include_subgraph: bool = True,
        include_path_details: bool = True,
        confidence_scoring_version: str = "v2",
        candidate_lane_mode: str = "broad",
        use_external_literature: bool = False,
        external_literature_query: str | None = None,
        external_literature_top_k: int = 5,
        external_literature_recency_days: int = 365,
        external_literature_exclude_domains: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        return verify_hypothesis(
            hypothesis,
            entity_hints=entity_hints,
            allowed_node_types=allowed_node_types,
            max_evidence=max_evidence,
            max_paths=max_paths,
            strictness=strictness,
            min_evidence_score=min_evidence_score,
            include_subgraph=include_subgraph,
            include_path_details=include_path_details,
            confidence_scoring_version=confidence_scoring_version,
            candidate_lane_mode=candidate_lane_mode,
            use_external_literature=use_external_literature,
            external_literature_query=external_literature_query,
            external_literature_top_k=external_literature_top_k,
            external_literature_recency_days=external_literature_recency_days,
            external_literature_exclude_domains=external_literature_exclude_domains,
            db=self._db,
        )

    def find_structural_leverage(
        self,
        seed_kg_ids: Sequence[str] | None,
        *,
        relation_types: Sequence[str] | None = None,
        direction: str = "both",
        limit: int = 25,
        taste: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return find_structural_leverage(
            seed_kg_ids,
            relation_types=relation_types,
            direction=direction,
            limit=limit,
            taste=taste,
            db=self._db,
        )

    def detect_contradiction_motifs(
        self,
        *,
        hypothesis: str | None = None,
        seed_kg_ids: Sequence[str] | None = None,
        evidence_items: Sequence[dict[str, Any]] | None = None,
        max_evidence: int = 80,
    ) -> dict[str, Any]:
        return detect_contradiction_motifs(
            hypothesis=hypothesis,
            seed_kg_ids=seed_kg_ids,
            evidence_items=evidence_items,
            max_evidence=max_evidence,
            db=self._db,
        )

    def find_contradiction_frontiers(
        self,
        *,
        query: str | None = None,
        seed_kg_ids: Sequence[str] | None = None,
        relation_types: Sequence[str] | None = None,
        limit: int = 10,
        max_evidence: int = 80,
    ) -> dict[str, Any]:
        return find_contradiction_frontiers(
            query=query,
            seed_kg_ids=seed_kg_ids,
            relation_types=relation_types,
            limit=limit,
            max_evidence=max_evidence,
            db=self._db,
        )

    def mine_assumption_cracks(
        self,
        *,
        query: str | None = None,
        seed_kg_ids: Sequence[str] | None = None,
        contradiction_frontiers: Mapping[str, Any]
        | Sequence[Mapping[str, Any]]
        | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        return mine_assumption_cracks(
            query=query,
            seed_kg_ids=seed_kg_ids,
            contradiction_frontiers=contradiction_frontiers,
            limit=limit,
            db=self._db,
        )

    def find_analogy_transfers(
        self,
        *,
        query: str | None = None,
        seed_kg_ids: Sequence[str] | None = None,
        relation_types: Sequence[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        return find_analogy_transfers(
            query=query,
            seed_kg_ids=seed_kg_ids,
            relation_types=relation_types,
            limit=limit,
            db=self._db,
        )

    def synthesize_wow_candidate_cards(
        self,
        *,
        query: str | None = None,
        seed_kg_ids: Sequence[str] | None = None,
        contradiction_frontiers: Mapping[str, Any]
        | Sequence[Mapping[str, Any]]
        | None = None,
        assumption_cracks: Mapping[str, Any]
        | Sequence[Mapping[str, Any]]
        | None = None,
        analogy_transfers: Mapping[str, Any]
        | Sequence[Mapping[str, Any]]
        | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        return synthesize_wow_candidate_cards(
            query=query,
            seed_kg_ids=seed_kg_ids,
            contradiction_frontiers=contradiction_frontiers,
            assumption_cracks=assumption_cracks,
            analogy_transfers=analogy_transfers,
            limit=limit,
        )

    def sample_ood_hypothesis(
        self,
        seed_kg_ids: Sequence[str] | None,
        *,
        relation_types: Sequence[str] | None = None,
        limit: int = 5,
        taste: dict[str, Any] | None = None,
        leverage_items: Sequence[dict[str, Any]] | None = None,
        leverage_context: dict[str, Any] | None = None,
        principle_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return sample_ood_hypothesis(
            seed_kg_ids,
            relation_types=relation_types,
            limit=limit,
            taste=taste,
            leverage_items=leverage_items,
            leverage_context=leverage_context,
            principle_state=principle_state,
            db=self._db,
        )

    def sample_and_verify_hypotheses(
        self,
        seed_kg_ids: Sequence[str] | None,
        *,
        query: str | None = None,
        relation_types: Sequence[str] | None = None,
        sample_limit: int = 5,
        verify_top_k: int | None = None,
        taste: dict[str, Any] | None = None,
        strictness: str = "high_recall",
        allowed_node_types: Sequence[str] | None = None,
        max_evidence: int = 60,
        max_paths: int = 60,
        min_evidence_score: float | None = None,
        include_subgraph: bool = False,
        include_path_details: bool = False,
        confidence_scoring_version: str = "v2",
        candidate_lane_mode: str = "broad",
        use_external_literature: bool = False,
        external_literature_top_k: int = 5,
        external_literature_recency_days: int = 365,
        external_literature_exclude_domains: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        return sample_and_verify_hypotheses(
            seed_kg_ids,
            query=query,
            relation_types=relation_types,
            sample_limit=sample_limit,
            verify_top_k=verify_top_k,
            taste=taste,
            strictness=strictness,
            allowed_node_types=allowed_node_types,
            max_evidence=max_evidence,
            max_paths=max_paths,
            min_evidence_score=min_evidence_score,
            include_subgraph=include_subgraph,
            include_path_details=include_path_details,
            confidence_scoring_version=confidence_scoring_version,
            candidate_lane_mode=candidate_lane_mode,
            use_external_literature=use_external_literature,
            external_literature_top_k=external_literature_top_k,
            external_literature_recency_days=external_literature_recency_days,
            external_literature_exclude_domains=external_literature_exclude_domains,
            db=self._db,
        )

    def verify_sampled_hypotheses(
        self,
        sampled_hypotheses: Sequence[dict[str, Any]] | None,
        *,
        query: str | None = None,
        seed_kg_ids: Sequence[str] | None = None,
        verify_top_k: int | None = None,
        strictness: str = "high_recall",
        allowed_node_types: Sequence[str] | None = None,
        max_evidence: int = 60,
        max_paths: int = 60,
        min_evidence_score: float | None = None,
        include_subgraph: bool = False,
        include_path_details: bool = False,
        confidence_scoring_version: str = "v2",
        candidate_lane_mode: str = "broad",
        use_external_literature: bool = False,
        external_literature_top_k: int = 5,
        external_literature_recency_days: int = 365,
        external_literature_exclude_domains: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        return verify_sampled_hypotheses(
            sampled_hypotheses,
            query=query,
            seed_kg_ids=seed_kg_ids,
            verify_top_k=verify_top_k,
            strictness=strictness,
            allowed_node_types=allowed_node_types,
            max_evidence=max_evidence,
            max_paths=max_paths,
            min_evidence_score=min_evidence_score,
            include_subgraph=include_subgraph,
            include_path_details=include_path_details,
            confidence_scoring_version=confidence_scoring_version,
            candidate_lane_mode=candidate_lane_mode,
            use_external_literature=use_external_literature,
            external_literature_top_k=external_literature_top_k,
            external_literature_recency_days=external_literature_recency_days,
            external_literature_exclude_domains=external_literature_exclude_domains,
            db=self._db,
        )

    def detect_topology_shifts(
        self,
        seed_kg_ids: Sequence[str] | None = None,
        *,
        limit: int = 50,
        taste: dict[str, Any] | None = None,
        mode: str = "proposal",
        patch_id: str | None = None,
        update_reason: str | None = None,
        now_iso: str | None = None,
    ) -> dict[str, Any]:
        return detect_topology_shifts(
            seed_kg_ids,
            limit=limit,
            taste=taste,
            mode=mode,
            patch_id=patch_id,
            update_reason=update_reason,
            now_iso=now_iso,
            db=self._db,
        )
