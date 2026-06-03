"""
Copilot Assistance Module (AGENT-007)

Provides real-time suggestions:
- Suggest tools based on query context
- Auto-complete parameter values from dataset metadata
- Provide example queries for similar tasks
- Learn from user selections to improve ranking
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.services.agent.parameter_inference import (
    ParameterInferenceEngine,
)
from brain_researcher.services.tools.tool_base import BRKGToolWrapper
from brain_researcher.services.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ToolSuggestion:
    name: str
    score: float
    reason: str
    required_params: list[str]
    autocomplete: dict[str, Any]
    examples: list[str]


class CopilotMemory:
    """Simple local memory to learn from user selections."""

    def __init__(self, storage_path: Path | None = None):
        self.storage_path = storage_path or Path(".copilot_memory.json")
        self.data: dict[str, Any] = {"tools": {}, "params": {}}
        self._load()

    def _load(self):
        try:
            if self.storage_path.exists():
                self.data = json.loads(self.storage_path.read_text())
        except Exception as e:
            logger.warning(f"Failed to load copilot memory: {e}")

    def _save(self):
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text(json.dumps(self.data, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save copilot memory: {e}")

    def record_tool_selection(self, tool_name: str):
        tools = self.data.setdefault("tools", {})
        tools[tool_name] = tools.get(tool_name, 0) + 1
        self._save()

    def record_param_acceptance(self, tool_name: str, param_name: str, value: Any):
        params = self.data.setdefault("params", {})
        key = f"{tool_name}:{param_name}:{json.dumps(value, sort_keys=True)}"
        params[key] = params.get(key, 0) + 1
        self._save()

    def tool_score(self, tool_name: str) -> float:
        count = self.data.get("tools", {}).get(tool_name, 0)
        return math.log1p(count)  # 0, 0.69, 1.10, ...


class ExampleDB:
    """Loads and searches example queries for similar tasks."""

    def __init__(self, examples_path: Path | None = None):
        # Copilot examples are repo-owned static config and live under configs/agent.
        self.examples_path = examples_path or resolve_from_config(
            "agent", "copilot_examples.json"
        )
        self.examples: list[dict[str, Any]] = []
        self._load()

    def _load(self):
        try:
            if self.examples_path.exists():
                self.examples = json.loads(self.examples_path.read_text()).get(
                    "examples", []
                )
        except Exception as e:
            logger.warning(f"Failed to load examples: {e}")

    def find_similar(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        q = query.lower()
        scored: list[tuple[float, dict[str, Any]]] = []
        for ex in self.examples:
            score = 0.0
            text = (" ".join(ex.get("queries", [])) + " " + ex.get("task", "")).lower()
            # crude token overlap
            for token in set(q.split()):
                if len(token) > 2 and token in text:
                    score += 1.0
            if score > 0:
                scored.append((score, ex))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [ex for _, ex in scored[:k]]


class CopilotAssistant:
    """Copilot engine for tool suggestions and parameter auto-completion."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        parameter_inference: ParameterInferenceEngine | None = None,
        memory: CopilotMemory | None = None,
        examples: ExampleDB | None = None,
    ):
        self.registry = tool_registry or ToolRegistry.from_env(auto_discover=True)
        self.inferrer = parameter_inference or ParameterInferenceEngine()
        self.memory = memory or CopilotMemory()
        self.examples = examples or ExampleDB()

    def suggest_tools(
        self, query: str, dataset_metadata: dict[str, Any] | None = None, k: int = 5
    ) -> list[ToolSuggestion]:
        tools = self.registry.get_tools_for_task(query, k=k * 2)
        similar = self.examples.find_similar(query, k=3)
        example_tool_boosts = set()
        for s in similar:
            example_tool_boosts.update(s.get("tools", []))

        suggestions: list[ToolSuggestion] = []
        total = max(1, len(tools))
        for idx, tool in enumerate(tools[: k * 2]):
            base_score = (total - idx) / total
            mem_score = self.memory.tool_score(tool.get_tool_name())
            ex_boost = 0.5 if tool.get_tool_name() in example_tool_boosts else 0.0
            score = base_score + mem_score + ex_boost

            required = self._required_params(tool)
            auto = self.autocomplete_parameters(
                tool.get_tool_name(), {}, dataset_metadata or {}
            )
            reason = self._build_reason(query, tool, similar, mem_score, ex_boost)
            examples = self._collect_examples_for_tool(tool, similar)

            suggestions.append(
                ToolSuggestion(
                    name=tool.get_tool_name(),
                    score=round(score, 3),
                    reason=reason,
                    required_params=required,
                    autocomplete={k: auto.get(k) for k in required if k in auto},
                    examples=examples,
                )
            )

        suggestions.sort(key=lambda s: s.score, reverse=True)
        return suggestions[:k]

    def _required_params(self, tool: BRKGToolWrapper) -> list[str]:
        try:
            schema = tool.get_args_schema()
            # pydantic v2
            if hasattr(schema, "model_fields"):
                req = [
                    name
                    for name, fld in schema.model_fields.items()
                    if getattr(fld, "is_required", False)
                ]
            elif hasattr(schema, "__fields__"):
                # pydantic v1 fallback
                req = [
                    name
                    for name, fld in schema.__fields__.items()
                    if getattr(fld, "required", False)
                ]
            else:
                req = []
            return req
        except Exception:
            return []

    def _build_reason(
        self,
        query: str,
        tool: BRKGToolWrapper,
        similar: list[dict[str, Any]],
        mem_score: float,
        ex_boost: float,
    ) -> str:
        parts = []
        # Keyword match from registry already considered in order
        if ex_boost > 0:
            parts.append("similar to example tasks")
        if mem_score > 0:
            parts.append("previously selected")
        if not parts:
            parts.append("matches query keywords")
        return ", ".join(parts)

    def _collect_examples_for_tool(
        self, tool: BRKGToolWrapper, similar: list[dict[str, Any]]
    ) -> list[str]:
        out: list[str] = []
        name = tool.get_tool_name()
        for s in similar:
            if name in s.get("tools", []):
                out.extend(s.get("queries", [])[:2])
        return out[:3]

    def autocomplete_parameters(
        self,
        tool_name: str,
        partial_params: dict[str, Any],
        dataset_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Auto-complete parameters based on dataset metadata and mappings."""
        completed = dict(partial_params)
        # Map generic metadata keys to tool-specific names
        mappings = self.inferrer.parameter_mappings
        # Choose family mapping by heuristic on tool name
        family = None
        for fam in mappings.keys():
            if fam in tool_name.lower():
                family = fam
                break
        if family is None:
            # default to nilearn-like mapping as generic
            family = "nilearn"
        fam_map = mappings.get(family, {})

        # Normalize metadata keys to snake_case similar to inferrer to_dict keys
        meta = {k.lower(): v for k, v in dataset_metadata.items()}
        # Common aliasing
        if "tr" in meta and "repetition_time" not in meta:
            meta["repetition_time"] = meta["tr"]
        if "voxelsize" in meta and "voxel_size" not in meta:
            meta["voxel_size"] = meta["voxelsize"]

        for generic, tool_param in fam_map.items():
            if tool_param not in completed and generic in meta:
                completed[tool_param] = meta[generic]

        # Add some generic defaults
        defaults = {
            "space": "MNI152",
            "normalization_space": "MNI152",
        }
        for k, v in defaults.items():
            if k not in completed:
                completed[k] = v

        return completed

    def learn_selection(
        self, tool_name: str, accepted_params: dict[str, Any] | None = None
    ):
        """Record user selection and accepted parameters to improve ranking."""
        self.memory.record_tool_selection(tool_name)
        if accepted_params:
            for k, v in accepted_params.items():
                self.memory.record_param_acceptance(tool_name, k, v)
