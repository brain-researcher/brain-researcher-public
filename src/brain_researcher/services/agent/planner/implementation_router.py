"""Implementation Router: choose a concrete tool for an Operation."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import yaml

from brain_researcher.config.paths import resolve_from_config

from .catalog_loader import ToolCapability, search_by_intent
from .intents import Operation
from .kg_bridge import (
    get_family_stats_for_operation,
    get_preferred_families_for_pipeline,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from brain_researcher.services.agent.tool_retriever import ToolRetriever


@dataclass
class EnvContext:
    """Environment and preference context for implementation selection."""

    available_runtimes: list[str] = field(
        default_factory=lambda: ["python", "container", "mcp"]
    )
    constraints: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    tool_retriever: ToolRetriever | None = None


def _runtime_preference_score(runtime_kind: str, prefs: dict[str, Any]) -> float:
    """Simple runtime preference scoring."""
    # Explicit runtime preference wins
    prefer = prefs.get("prefer_runtime")
    if prefer and runtime_kind == prefer:
        return 1.0
    # NIWRAP prioritization flag (boost container when requested)
    prefer_niwrap = (
        prefs.get("prefer_niwrap")
        or os.environ.get("BR_PLANNER_PREFER_NIWRAP", "").lower() == "true"
    )
    if prefer_niwrap and runtime_kind == "container":
        return 0.95
    # default ordering: python > container > mcp
    if runtime_kind == "python":
        return 0.9
    if runtime_kind == "container":
        return 0.7
    if runtime_kind == "mcp":
        return 0.6
    return 0.5


def _infer_family_id(package: str) -> str:
    pkg = (package or "").lower()
    if pkg.startswith("fsl"):
        return "fsl"
    if pkg.startswith("afni"):
        return "afni"
    if pkg.startswith("mrtrix"):
        return "mrtrix3"
    if pkg.startswith("workbench"):
        return "workbench"
    if pkg.startswith("ants"):
        return "ants"
    if pkg.startswith("freesurfer"):
        return "freesurfer"
    if pkg.startswith("bidsapp"):
        return "bidsapps"
    return "niwrap_generic"


@lru_cache(maxsize=1)
def _load_promoted_spec():
    path = resolve_from_config("kg_promoted_niwrap.yaml")
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text()) or {}
        return data.get("promoted", []) or []
    except Exception:
        return []


def _is_promoted(tool: ToolCapability) -> bool:
    if not getattr(tool, "entrypoint", None):
        return False
    pkg = (tool.package or "").lower()
    ep = (tool.entrypoint or "").lower()
    tid = tool.id.lower()
    for spec in _load_promoted_spec():
        spkg = (spec.get("package") or "").lower()
        sep = (spec.get("entrypoint") or "").lower()
        sid = (spec.get("id") or "").lower()
        if sid and tid == sid:
            return True
        if spkg and sep and pkg == spkg and ep == sep:
            return True
        if spkg and not sep and pkg == spkg:
            return True
    return False


def _score_tools_for_operation(op: Operation, env: EnvContext):
    """Return best tool plus scoring breakdown for debugging."""
    tools = search_by_intent(op.intent.id)
    if not tools:
        return None, []

    # Filter by available runtimes
    tools = [
        t for t in tools if getattr(t, "runtime_kind", None) in env.available_runtimes
    ]
    if not tools:
        return None, []

    # KG hints (preferred families for this op or pipeline)
    kg_use = os.environ.get(
        "BR_PLANNER_USE_KG_HINTS", ""
    ).lower() == "true" or env.preferences.get("use_kg_hints")
    try:
        kg_weight = float(
            env.preferences.get(
                "kg_hint_weight", os.environ.get("BR_PLANNER_KG_HINT_WEIGHT", 1.0)
            )
        )
    except Exception:
        kg_weight = 1.0
    kg_weight = max(0.0, min(kg_weight, 5.0))
    preferred_families = set()
    family_counts = {}
    if kg_use:
        # operation-level stats
        for fid, cnt in get_family_stats_for_operation(op.intent.id):
            family_counts[fid] = cnt
        # pipeline-level preference (if present in preferences)
        pipeline_id = env.preferences.get("pipeline_id")
        if pipeline_id:
            preferred_families.update(get_preferred_families_for_pipeline(pipeline_id))

    # Optional KG tool retriever (query_service/embeddings)
    kg_tool_scores: dict[str, float] = {}
    kg_retriever_pref = env.preferences.get("use_kg_retriever")
    if kg_retriever_pref is None:
        kg_retriever_use = os.environ.get(
            "BR_PLANNER_USE_KG_RETRIEVER", ""
        ).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not kg_retriever_use:
            kg_retriever_use = env.tool_retriever is not None
    else:
        kg_retriever_use = bool(kg_retriever_pref)

    if env.tool_retriever and kg_retriever_use:
        try:
            kg_query_parts = [op.intent.name, op.intent.description, op.intent.id]
            kg_query = (
                " ".join([p for p in kg_query_parts if p]).strip() or op.intent.id
            )
            matches = env.tool_retriever.retrieve_tools(
                query=kg_query, family_ids=None, top_k=20
            )
            if matches:
                raw_scores: dict[str, float] = {}
                for match in matches:
                    tool_id = getattr(match, "id", None)
                    if tool_id is None and isinstance(match, dict):
                        tool_id = match.get("id")
                    score = getattr(match, "score", None)
                    if score is None and isinstance(match, dict):
                        score = match.get("score")
                    if (
                        isinstance(tool_id, str)
                        and tool_id
                        and isinstance(score, int | float)
                    ):
                        raw_scores[tool_id] = float(score)
                if raw_scores:
                    max_score = max(raw_scores.values()) or 1.0
                    kg_tool_scores = {k: v / max_score for k, v in raw_scores.items()}
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("KG tool retriever unavailable: %s", exc)

    # Score and pick best
    scored = []
    debug_rows = []
    promoted_weight = float(os.environ.get("BR_PLANNER_PROMOTED_WEIGHT", 0.05))
    try:
        kg_retriever_weight = float(
            env.preferences.get(
                "kg_retriever_weight",
                os.environ.get("BR_PLANNER_KG_RETRIEVER_WEIGHT", 0.15),
            )
        )
    except Exception:
        kg_retriever_weight = 0.15
    for tool in tools:
        rt = getattr(tool, "runtime_kind", None) or ""
        score = _runtime_preference_score(rt, env.preferences)
        reasons = [f"runtime:{rt}:{score:.3f}"]

        if kg_use:
            fam = _infer_family_id(getattr(tool, "package", "") or "")
            fam_boost = 0.0
            if fam in preferred_families:
                fam_boost += 0.15 * kg_weight
            if fam in family_counts:
                fam_boost += min(0.1, 0.01 * family_counts[fam]) * kg_weight
            score += fam_boost
            reasons.append(f"kg:{fam}:{fam_boost:.3f}")
        if kg_tool_scores:
            kg_score = kg_tool_scores.get(getattr(tool, "id", None))
            if isinstance(kg_score, int | float):
                kg_boost = kg_retriever_weight * float(kg_score)
                score += kg_boost
                reasons.append(f"kg_retriever:{kg_score:.3f}:{kg_boost:.3f}")
        # Mild boost for curated promoted NiWrap tools
        if promoted_weight > 0 and _is_promoted(tool):
            score += promoted_weight
            reasons.append(f"promoted:{promoted_weight:.3f}")
        scored.append((score, tool))
        debug_rows.append((score, tool, reasons))

    scored.sort(key=lambda x: -x[0])
    best = scored[0][1] if scored else None
    if (
        env.preferences.get("log_selection_reason")
        or os.environ.get("BR_PLANNER_LOG_SELECTION", "").lower() == "true"
    ):
        top_rows = sorted(debug_rows, key=lambda x: -x[0])[:5]
        logger.info(
            "planner_selection intent=%s pipeline=%s kg_use=%s kg_weight=%.2f choice=%s top=%s",
            op.intent.id,
            env.preferences.get("pipeline_id"),
            kg_use,
            kg_weight,
            getattr(best, "id", None),
            [
                {
                    "tool": t.id,
                    "score": f"{s:.3f}",
                    "reasons": r,
                }
                for s, t, r in top_rows
            ],
        )
    return best, debug_rows


def choose_tool_for_operation(op: Operation, env: EnvContext) -> ToolCapability | None:
    """Pick a ToolCapability that implements the Operation's intent."""
    best, _ = _score_tools_for_operation(op, env)
    return best


def choose_tool_for_operation_debug(op: Operation, env: EnvContext):
    """Pick a tool and return debug scoring rows."""
    return _score_tools_for_operation(op, env)
    return best
