"""Routing view over the core ToolRegistry for chat tool selection.

This module intentionally keeps **no separate registry**. It projects the
already-loaded `services.tools.registry.ToolRegistry` into a lightweight
`RoutingToolSpec` list, applies chat-specific filtering (whitelist + dangerous
block), and scores candidates with a simple lexical heuristic.

Track K+ integration: The router accepts knowledge_evidence from the
KnowledgeAggregator and boosts tools that match evidence items (datasets,
tools, KG nodes).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

import yaml

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.services.agent.dataset_browse_policy import (
    dataset_browse_score_adjustment,
    is_exploratory_dataset_asset_request,
)
from brain_researcher.services.agent.tool_allowlist_loader import (
    is_local_first_blocked_tool,
    load_chat_tools_allowlist,
)
from brain_researcher.services.tools.tool_registry import (
    ToolRegistry as CoreToolRegistry,
)
from brain_researcher.services.tools.spec import ToolSpec, spec_from_tool

if TYPE_CHECKING:
    from brain_researcher.services.agent.knowledge import EvidenceBundle

logger = logging.getLogger(__name__)

CATALOG_DIR = resolve_from_config("catalog")
CHAT_TOOLS_PATH = resolve_from_config("catalog", "chat_tools.yaml")


@dataclass
class ToolFamily:
    id: str
    description: str
    op_param: str
    ops: Dict[str, str]  # op name -> leaf runtime id
    internal: bool = False


@dataclass
class RoutingToolView:
    """Routing surface shown to LLM (family or leaf)."""

    runtime_id: str  # family id or leaf id
    name: str
    description: str
    tags: List[str]
    dangerous: bool = False
    family_id: Optional[str] = None
    family_ops: Optional[List[str]] = None
    op_param: str = "op"

    def is_family(self) -> bool:
        return self.family_id is not None

    def selection_stub(self) -> str:
        tag_str = ",".join(sorted(set(self.tags))) if self.tags else ""
        danger = " (dangerous)" if self.dangerous else ""
        desc = (self.description or "")[:200]
        if self.is_family():
            ops = ", ".join(self.family_ops or [])
            return (
                f"- {self.name} (FAMILY){danger} tags=[{tag_str}] desc={desc} "
                f"ops=[{ops}] param={self.op_param}"
            )
        return f"- {self.runtime_id}{danger} tags=[{tag_str}] desc={desc}"


class RoutingView:
    """Projects the core registry into RoutingToolView objects, applying family folding."""

    HEAVY_PATTERNS = (
        r"fmriprep",
        r"qsiprep",
        r"xcpd",
        r"cpac",
        r"mriqc",
        r"ants",
        r"freesurfer",
        r"afni",
        r"feat",
        r"melodic",
        r"bedpostx",
        r"palm",
        r"fix",
        r"workflow_",
        r"pipeline_execute",
        r"tool_execute",
        r"run_local_script",
        r"neurodesk_command",
        r"openneuro_download",
        r"dandi_download",
        r"prefetch\.openneuro_cache",
    )

    def __init__(
        self,
        core_registry: CoreToolRegistry,
        families: Optional[Dict[str, ToolFamily]] = None,
    ):
        self.core_registry = core_registry
        self.families = families or {}

    def all_tools(self) -> List[RoutingToolView]:
        leaf_views: Dict[str, RoutingToolView] = {}
        for tool in self.core_registry.get_all_tools():
            tool_spec: Optional[ToolSpec] = spec_from_tool(tool)
            if tool_spec:
                dangerous = bool(
                    getattr(tool_spec, "dangerous", False)
                ) or self._heuristic_danger(tool_spec.name)
                leaf_views[tool_spec.name] = RoutingToolView(
                    runtime_id=tool_spec.name,
                    name=tool_spec.name,
                    description=tool_spec.description,
                    tags=tool_spec.tags or [],
                    dangerous=dangerous,
                    family_id=None,
                    family_ops=None,
                )
            else:
                leaf_views[tool.get_tool_name()] = RoutingToolView(
                    runtime_id=tool.get_tool_name(),
                    name=tool.get_tool_name(),
                    description=tool.get_tool_description(),
                    tags=[],
                    dangerous=False,
                    family_id=None,
                    family_ops=None,
                )

        family_views: List[RoutingToolView] = []
        consumed: Set[str] = set()
        for fam in self.families.values():
            valid_ops = {
                op_name: leaf_id
                for op_name, leaf_id in fam.ops.items()
                if leaf_id in leaf_views
            }
            if not valid_ops:
                continue
            sample_descs = [
                leaf_views[lid].description for lid in list(valid_ops.values())[:3]
            ]
            family_dangerous = any(
                leaf_views[leaf_id].dangerous for leaf_id in valid_ops.values()
            )
            desc = fam.description or ""
            if sample_descs:
                desc = (desc + " " + " ".join(sample_descs)).strip()
            tags = ["family"]
            if fam.internal:
                tags.append("internal")
            family_views.append(
                RoutingToolView(
                    runtime_id=fam.id,
                    name=fam.id,
                    description=desc,
                    tags=tags,
                    dangerous=family_dangerous,
                    family_id=fam.id,
                    family_ops=list(valid_ops.keys()),
                    op_param=fam.op_param,
                )
            )
            consumed.update(valid_ops.values())

        remaining_leaf_views = [
            v for leaf_id, v in leaf_views.items() if leaf_id not in consumed
        ]

        return family_views + remaining_leaf_views

    def _heuristic_danger(self, tool_id: str) -> bool:
        tid = tool_id.lower()
        return any(re.search(p, tid) for p in self.HEAVY_PATTERNS)


def load_chat_tools_whitelist(path: Path = CHAT_TOOLS_PATH) -> Set[str]:
    """Load chat-safe whitelist from configs/catalog/chat_tools.yaml."""

    try:
        if path == CHAT_TOOLS_PATH:
            return set(load_chat_tools_allowlist())
        if not path.exists():
            return set()
        data = yaml.safe_load(path.read_text()) or {}
        return set(
            tool_id
            for tool_id in (str(t).strip() for t in (data.get("chat_tools", []) or []))
            if tool_id and not is_local_first_blocked_tool(tool_id)
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load chat_tools whitelist: %s", exc)
        return set()


def load_tool_families(config_path: Optional[Path] = None) -> Dict[str, ToolFamily]:
    """Load tool family definitions."""

    if config_path is None:
        config_path = resolve_from_config("catalog", "tool_families.yaml")
    if not config_path.exists():
        return {}

    data = yaml.safe_load(config_path.read_text()) or {}
    overrides_path = config_path.with_name("tool_families_overrides.yaml")
    if overrides_path.exists():
        overrides = yaml.safe_load(overrides_path.read_text()) or {}
        base_families = {
            f.get("id"): f for f in (data.get("families", []) or []) if f.get("id")
        }
        for override in overrides.get("families", []) or []:
            fam_id = override.get("id")
            if not fam_id:
                continue
            base = base_families.get(fam_id, {"id": fam_id})
            # Shallow merge top-level fields
            for key in ("description", "op_param", "internal"):
                if key in override and override[key] is not None:
                    base[key] = override[key]
            # Merge ops mapping
            base_ops = (base.get("ops") or {}).copy()
            base_ops.update(override.get("ops") or {})
            base["ops"] = base_ops
            base_families[fam_id] = base
        data["families"] = list(base_families.values())
    families: Dict[str, ToolFamily] = {}
    for item in data.get("families", []) or []:
        fam = ToolFamily(
            id=item["id"],
            description=item.get("description", ""),
            op_param=item.get("op_param", "op"),
            ops=item.get("ops", {}) or {},
            internal=bool(item.get("internal", False)),
        )
        families[fam.id] = fam
    return families


class ToolRouter:
    """Tag/whitelist filtered lexical router for chat."""

    def __init__(
        self,
        core_registry: CoreToolRegistry,
        chat_whitelist: Optional[Set[str]] = None,
        max_candidates: int = 30,
        families: Optional[Dict[str, ToolFamily]] = None,
        allow_dangerous: bool = False,
        allow_internal: bool = False,
        exposure_filter: Optional[List[str]] = None,
    ) -> None:
        self.core_registry = core_registry
        self.families = families if families is not None else load_tool_families()
        self.view = RoutingView(core_registry, families=self.families)
        # None means "no whitelist filtering"; an explicit empty set means fail-closed.
        self.chat_whitelist = chat_whitelist
        self.max_candidates = max_candidates
        self.allow_dangerous = allow_dangerous
        self.allow_internal = allow_internal
        self.exposure_filter = (
            [e.lower() for e in exposure_filter] if exposure_filter else None
        )

    def get_candidates(
        self,
        user_msg: str,
        history: Optional[Sequence[Any]] = None,
        ctx: Optional[Dict[str, Any]] = None,
        domain_filter: Optional[List[str]] = None,
        function_filter: Optional[List[str]] = None,
        risk_filter: Optional[List[str]] = None,
    ) -> List[RoutingToolView]:
        """Return filtered + ranked routing specs.

        Filtering order:
        1) chat whitelist (if present)
        2) dangerous tools removed
        3) optional domain/function/risk filters
        3) lexical ranking over name/description
        """

        specs = self.view.all_tools()

        if self.chat_whitelist is not None:
            specs = [s for s in specs if s.runtime_id in self.chat_whitelist]

        if not self.allow_dangerous:
            specs = [s for s in specs if not s.dangerous]

        if not self.allow_internal:
            specs = [s for s in specs if "internal" not in (s.tags or [])]

        if self.exposure_filter:
            ef = set(self.exposure_filter)
            specs = [s for s in specs if ef & {t.lower() for t in (s.tags or [])}]

        # Apply explicit filters via tags
        if domain_filter:
            df = {d.lower() for d in domain_filter}
            specs = [s for s in specs if df & {t.lower() for t in (s.tags or [])}]
        if function_filter:
            ff = {f.lower() for f in function_filter}
            specs = [s for s in specs if ff & {t.lower() for t in (s.tags or [])}]
        if risk_filter:
            rf = {r.lower() for r in risk_filter}
            specs = [s for s in specs if rf & {t.lower() for t in (s.tags or [])}]

        # Optional KG-derived tool candidates: restrict to hinted tools if present.
        if isinstance(ctx, dict):
            tool_candidates = ctx.get("tool_candidates")
            if tool_candidates:
                allowed_ids: Set[str] = set()
                for cand in tool_candidates:
                    tool_id = None
                    if isinstance(cand, dict):
                        tool_id = (
                            cand.get("tool_id")
                            or cand.get("tool_id_raw")
                            or cand.get("id")
                            or cand.get("name")
                        )
                    elif isinstance(cand, str):
                        tool_id = cand
                    else:
                        tool_id = (
                            getattr(cand, "tool_id", None)
                            or getattr(cand, "tool_id_raw", None)
                            or getattr(cand, "id", None)
                        )
                    if tool_id:
                        allowed_ids.add(str(tool_id))
                if allowed_ids:
                    filtered = [s for s in specs if s.runtime_id in allowed_ids]
                    if filtered:
                        specs = filtered

        ranked = self._rank(user_msg, specs, ctx=ctx)
        return ranked[: self.max_candidates]

    # ------------------------------------------------------------------
    # Unified ToolSpec Interface (Phase 2)
    # ------------------------------------------------------------------
    def get_candidates_unified(
        self,
        goal: str,
        modalities: Optional[List[str]] = None,
        kind: Optional[str] = None,
        k: int = 8,
    ) -> List[ToolSpec]:
        """Get candidates using unified ToolSpec system.

        Uses the new catalog_loader-based ToolSpec with modality/intent filtering.
        This is the preferred method for LLM-based routing.

        Args:
            goal: Natural language description of what the user wants to do
            modalities: Optional list of modalities to filter by (fmri, smri, dmri)
            kind: Optional kind to filter by (imaging, kg, viz, meta, data, analysis)
            k: Maximum number of candidates to return

        Returns:
            List of ToolSpec objects ranked by relevance
        """
        from brain_researcher.services.tools.registry import get_candidate_tools

        return get_candidate_tools(goal, modalities, kind, k)

    def build_llm_prompt(
        self,
        goal: str,
        candidates: List[ToolSpec],
        context: str = "",
        verbose: bool = False,
    ) -> str:
        """Build LLM prompt for tool selection.

        Args:
            goal: User's natural language goal
            candidates: List of ToolSpec candidates (from get_candidates_unified)
            context: Optional additional context
            verbose: If True, include more tool details

        Returns:
            Complete prompt string ready for LLM
        """
        from brain_researcher.services.agent.prompts import build_router_prompt

        return build_router_prompt(goal, candidates, context, verbose)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _rank(
        query: str, specs: List[RoutingToolView], ctx: Optional[Dict[str, Any]] = None
    ) -> List[RoutingToolView]:
        if not specs:
            return []

        q = query.lower()
        words = [w for w in re.findall(r"[a-z0-9_]+", q) if len(w) > 2]
        qur = None
        knowledge_evidence: Optional["EvidenceBundle"] = None
        if isinstance(ctx, dict):
            qur = ctx.get("query_understanding")
            knowledge_evidence = ctx.get("knowledge_evidence")

        # Allow both Pydantic and dataclass shapes
        resolved_datasets = getattr(qur, "resolved_datasets", None) or (
            qur.get("resolved_datasets") if isinstance(qur, dict) else []
        )
        kg_nodes = getattr(qur, "kg_nodes", None) or (
            qur.get("kg_nodes") if isinstance(qur, dict) else []
        )
        exploratory_dataset_assets = is_exploratory_dataset_asset_request(
            query,
            query_understanding=qur,
        )
        available_tool_ids = [spec.runtime_id for spec in specs]
        has_dataset = bool(resolved_datasets)
        has_brain_region = False
        has_concept = False
        if kg_nodes:
            for node in kg_nodes:
                node_type_raw = getattr(node, "type", "") or str(node.get("type", ""))
                node_type = node_type_raw.lower()
                if node_type in {"brain_region", "region"}:
                    has_brain_region = True
                if node_type in {"cognitiveconcept", "concept"}:
                    has_concept = True

        # Track K+: Extract tool names and tags from knowledge evidence (EvidenceBundle)
        evidence_tool_names: Set[str] = set()
        evidence_tags: Set[str] = set()
        evidence_has_datasets = False
        evidence_has_kg_nodes = False
        evidence_has_niclip = False
        if knowledge_evidence:
            # Import at runtime to avoid circular imports
            from brain_researcher.services.agent.knowledge import EvidenceSourceType

            for item in knowledge_evidence.items:
                # Be tolerant of mixed shapes (old evidence may not have source_type)
                source_type = getattr(item, "source_type", None)
                source_id = getattr(item, "source_id", None) or getattr(item, "id", "")
                metadata = getattr(item, "metadata", {}) or {}

                if source_type == EvidenceSourceType.TOOL_CATALOG:
                    tool_name = source_id or item.label
                    evidence_tool_names.add(str(tool_name).lower())
                    for tag in metadata.get("tags", []):
                        evidence_tags.add(str(tag).lower())
                elif source_type == EvidenceSourceType.DATASET_CATALOG:
                    evidence_has_datasets = True
                elif source_type in (
                    EvidenceSourceType.KG_GRAPH,
                    EvidenceSourceType.NEUROSTORE,
                ):
                    evidence_has_kg_nodes = True
                elif source_type == EvidenceSourceType.NICLIP:
                    evidence_has_niclip = True
                else:
                    # Fallback for legacy items identified only by source_id string
                    if isinstance(source_id, str):
                        sid = source_id.lower()
                        if "tool" in sid:
                            evidence_tool_names.add(sid)
                        if "dataset" in sid:
                            evidence_has_datasets = True

        scored = []
        for spec in specs:
            text = f"{spec.runtime_id} {spec.name} {spec.description}".lower()
            score = sum(text.count(w) for w in words)
            if score == 0 and spec.tags:
                score += sum(1 for w in words if w in spec.tags)

            # Tag-aware boosts
            spec_tags = {t.lower() for t in (spec.tags or [])}
            if (
                hasattr(qur, "domain")
                and qur.domain
                and qur.domain.lower() in spec_tags
            ):
                score += 3
            if (
                hasattr(qur, "function")
                and qur.function
                and qur.function.lower() in spec_tags
            ):
                score += 2
            # risk-aware: penalize dangerous/high_cost unless explicitly requested
            if "dangerous" in spec_tags and (
                not ctx.get("allow_dangerous") if ctx else False
            ):
                score -= 3
            if "high_cost" in spec_tags:
                score -= 1

            if has_dataset and any(
                tag in ("dataset_catalog", "derivative") for tag in (spec.tags or [])
            ):
                score += 2
                if "inventory" in spec_tags:
                    score += 1
            if (has_brain_region or has_concept) and "br_kg" in (spec.tags or []):
                score += 2

            # Track K+: Boost tools that match knowledge evidence
            if evidence_tool_names:
                if (
                    spec.runtime_id.lower() in evidence_tool_names
                    or spec.name.lower() in evidence_tool_names
                ):
                    score += 5  # Strong boost for exact tool match
                # Check if any evidence tags match spec tags
                spec_tags_lower = {t.lower() for t in (spec.tags or [])}
                matching_tags = spec_tags_lower & evidence_tags
                score += len(matching_tags)  # +1 per matching tag

            if evidence_has_datasets and any(
                tag in ("dataset_catalog", "derivative") for tag in (spec.tags or [])
            ):
                score += 2  # Boost dataset-related tools
                if "inventory" in spec_tags:
                    score += 1
            if evidence_has_kg_nodes and "br_kg" in (spec.tags or []):
                score += 2  # Boost KG-related tools
            if evidence_has_niclip and "br_kg" in (spec.tags or []):
                score += 1  # Smaller boost for NiCLIP-relevant tools

            if exploratory_dataset_assets:
                score += dataset_browse_score_adjustment(
                    spec.runtime_id,
                    available_tool_ids=available_tool_ids,
                )

            scored.append((score, spec))

        scored.sort(key=lambda x: x[0], reverse=True)
        # If all scores are 0, preserve original order
        if scored and scored[0][0] == 0:
            return [spec for _, spec in scored]
        return [spec for score, spec in scored if score >= 0]


def build_default_router(
    core_registry: Optional[CoreToolRegistry] = None,
) -> ToolRouter:
    core_registry = core_registry or CoreToolRegistry()
    # Default router (non-chat) can allow dangerous tools; callers like chat orchestrator
    # instantiate their own router with allow_dangerous=False.
    return ToolRouter(core_registry=core_registry, allow_dangerous=True)


__all__ = [
    "RoutingToolView",
    "ToolFamily",
    "ToolRouter",
    "build_default_router",
    "load_chat_tools_whitelist",
    "load_tool_families",
]
