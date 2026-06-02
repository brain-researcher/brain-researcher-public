"""
Tool Specification System for Enhanced Discovery

This module provides a unified way to expose complete tool parameter schemas,
examples, and metadata to LLMs for proper function calling.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from brain_researcher.services.tools.metadata_schema import normalize_tags

logger = logging.getLogger(__name__)

# Type definitions for unified tool system
Backend = Literal["niwrap", "python", "external_api"]
Kind = Literal["imaging", "kg", "viz", "meta", "data", "analysis"]
ToolPhase = Literal["explore", "plan", "execute", "admin"]
ApprovalLevel = Literal["none", "confirm", "admin"]

_TOOL_PHASE_ORDER: tuple[ToolPhase, ...] = ("explore", "plan", "execute", "admin")
_APPROVAL_ORDER: dict[str, int] = {"none": 0, "confirm": 1, "admin": 2}
_ADMIN_TOOL_IDS = {"pipeline_execute", "tool_execute"}
_READ_ONLY_DISCOVERY_TOKENS = {
    "dataset",
    "datasets",
    "describe",
    "discovery",
    "fetch",
    "find",
    "get",
    "graph",
    "kg",
    "knowledge",
    "list",
    "lookup",
    "neighbor",
    "neighbors",
    "openneuro",
    "probe",
    "question",
    "read",
    "resolve",
    "resource",
    "resources",
    "search",
}
_PLAN_ONLY_TOKENS = {
    "execution",
    "pipeline",
    "planner",
    "planning",
    "recipe",
    "workflow",
}


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def _tokenize_metadata(value: Any) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+", _normalize_text(value).replace("_", " ")):
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _normalize_search_hint(
    value: Any,
    *,
    name: str,
    description: str,
    category: str | None,
    kind: Kind | None,
    modalities: list[str],
    intents: list[str],
    tags: list[str],
) -> str | None:
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())[:240]

    fragments: list[str] = []
    fragments.extend(_tokenize_metadata(name))
    if category:
        fragments.extend(_tokenize_metadata(category))
    if kind:
        fragments.extend(_tokenize_metadata(kind))
    for modality in modalities[:4]:
        fragments.extend(_tokenize_metadata(modality))
    for intent in intents[:8]:
        fragments.extend(_tokenize_metadata(intent))
    for tag in tags[:8]:
        fragments.extend(_tokenize_metadata(tag))
    if description:
        fragments.extend(_tokenize_metadata(description)[:16])

    if not fragments:
        return None

    seen: set[str] = set()
    deduped: list[str] = []
    for fragment in fragments:
        if fragment in seen:
            continue
        seen.add(fragment)
        deduped.append(fragment)

    return " ".join(deduped[:24]) or None


def _normalize_allowed_phases(
    value: Any,
    *,
    name: str,
    backend: Backend,
    kind: Kind | None,
    category: str | None,
    intents: list[str],
    side_effects: list[str],
    dangerous: bool,
    cost_hint: str | None,
    execution_capabilities: "ToolExecutionCapabilities | None",
) -> list[ToolPhase]:
    if isinstance(value, list):
        normalized: list[ToolPhase] = []
        for item in value:
            candidate = _normalize_text(item)
            if candidate in _TOOL_PHASE_ORDER and candidate not in normalized:
                normalized.append(candidate)  # type: ignore[arg-type]
        if normalized:
            return normalized

    normalized_name = _normalize_text(name)
    metadata_tokens = set(
        _tokenize_metadata(name)
        + _tokenize_metadata(category or "")
        + _tokenize_metadata(" ".join(intents))
    )
    side_effect_tokens = {_normalize_text(item) for item in side_effects if item}
    writes_files = (
        bool(execution_capabilities and execution_capabilities.writes_files is True)
        or "writes_files" in side_effect_tokens
    )
    is_workflow = normalized_name.startswith("workflow_")
    is_admin = normalized_name in _ADMIN_TOOL_IDS
    is_plan_only = (
        is_workflow
        or normalized_name == "pipeline.search"
        or "pipeline_search" in intents
        or ("workflow" in metadata_tokens and "search" in metadata_tokens)
        or ("recipe" in metadata_tokens and not writes_files)
        or (
            bool(_PLAN_ONLY_TOKENS & metadata_tokens)
            and "search" in metadata_tokens
            and not writes_files
        )
    )
    is_read_only_discovery = (
        not writes_files
        and not dangerous
        and backend != "niwrap"
        and (
            kind == "kg"
            or bool(_READ_ONLY_DISCOVERY_TOKENS & metadata_tokens)
            or normalized_name.startswith(("datasets.", "br_kg.", "openneuro."))
        )
    )

    if is_admin:
        return ["admin"]
    if is_plan_only:
        return ["plan"]
    if is_read_only_discovery:
        return ["explore", "plan"]
    if dangerous or writes_files or backend == "niwrap" or cost_hint == "expensive":
        return ["execute"]
    return ["execute"]


def _normalize_approval_level(
    value: Any,
    *,
    allowed_phases: list[ToolPhase],
    backend: Backend,
    dangerous: bool,
    side_effects: list[str],
    cost_hint: str | None,
    execution_capabilities: "ToolExecutionCapabilities | None",
) -> ApprovalLevel:
    candidate = _normalize_text(value)
    if candidate in _APPROVAL_ORDER and not (
        candidate == "none" and "execute" in allowed_phases
    ):
        return candidate  # type: ignore[return-value]

    side_effect_tokens = {_normalize_text(item) for item in side_effects if item}
    writes_files = (
        bool(execution_capabilities and execution_capabilities.writes_files is True)
        or "writes_files" in side_effect_tokens
    )

    if "admin" in allowed_phases:
        return "admin"
    if "execute" in allowed_phases:
        return "confirm"
    if dangerous or writes_files or backend == "niwrap" or cost_hint == "expensive":
        return "confirm"
    return "none"


def normalize_implementation_level(value: Any, default: str = "production") -> str:
    """Normalize implementation-level metadata for consistent MCP responses."""
    if not isinstance(value, str):
        return default
    normalized = value.strip().lower()
    return normalized or default


def infer_requires_runtime(
    value: Any = None,
    *,
    backend: Backend | str | None = None,
    runtime_kind: str | None = None,
) -> str:
    """Infer runtime requirement in a card-friendly string form."""
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    if isinstance(value, bool):
        return "python" if value else "none"

    rk = (runtime_kind or "").strip().lower()
    be = (backend or "").strip().lower()
    if rk == "container" or be == "niwrap":
        return "container"
    if rk == "mcp" or be == "external_api":
        return "network"
    return "python"


def normalize_hard_dependencies(value: Any) -> List[str]:
    """Normalize hard dependency metadata to a stable list[str]."""
    if isinstance(value, str):
        dep = value.strip()
        return [dep] if dep else []
    if not isinstance(value, list):
        return []
    normalized: List[str] = []
    for item in value:
        dep = str(item).strip()
        if dep:
            normalized.append(dep)
    return normalized


def normalize_qc_spec(value: Any) -> Optional[ToolQCSpec]:
    """Normalize semantic QC metadata into a structured ToolQCSpec."""

    if value is None:
        return None
    if isinstance(value, ToolQCSpec):
        return value
    if not isinstance(value, dict):
        return None

    payload = dict(value)

    judge = payload.get("judge")
    if not isinstance(judge, dict):
        judge = {}

    legacy_judge_keys = {
        "cheap_model",
        "uncertain_model",
        "uncertainty_confidence_threshold",
    }
    for key in list(payload.keys()):
        if key in legacy_judge_keys:
            judge[key] = payload.pop(key)
    if judge:
        payload["judge"] = judge

    render_contract = payload.get("render_contract")
    if isinstance(render_contract, dict):
        payload["render_contract"] = ToolQCRenderContract(**render_contract)

    prechecks = payload.get("prechecks")
    if isinstance(prechecks, dict):
        payload["prechecks"] = ToolQCPrecheckConfig(**prechecks)

    retry_rules = payload.get("retry_rules")
    if isinstance(retry_rules, list):
        normalized_rules: List[ToolQCRetryRule] = []
        for rule in retry_rules:
            if isinstance(rule, ToolQCRetryRule):
                normalized_rules.append(rule)
            elif isinstance(rule, dict):
                normalized_rules.append(ToolQCRetryRule(**rule))
        payload["retry_rules"] = normalized_rules

    try:
        return ToolQCSpec(**payload)
    except Exception:
        return None


class ToolExample(BaseModel):
    """Example of tool usage with query and parameters."""

    user_query: str = Field(description="Natural language query from user")
    params: Dict[str, Any] = Field(description="Parameters that should be used")
    notes: Optional[str] = Field(
        default=None, description="Additional context or explanation"
    )


class ToolExecutionCapabilities(BaseModel):
    """Declarative runtime capabilities/policy requirements for a tool."""

    needs_network: Optional[bool] = Field(
        default=None,
        description="Whether this tool requires network access to function correctly",
    )
    allowed_domains: List[str] = Field(
        default_factory=list,
        description="Optional allowlist of domains the tool may contact",
    )
    writes_files: Optional[bool] = Field(
        default=None,
        description="Whether this tool writes files (beyond its designated output_dir)",
    )
    allowed_paths: List[str] = Field(
        default_factory=list,
        description="Optional allowlist of filesystem paths the tool may access",
    )
    needs_secrets: List[str] = Field(
        default_factory=list,
        description="Names of required secrets/env vars (values are never stored)",
    )


class ToolQCJudgeConfig(BaseModel):
    """Model routing configuration for semantic QC judging."""

    cheap_model: str = Field(
        default="gemini-2.5-flash-lite",
        description="Primary low-cost model used for QC image judging",
    )
    uncertain_model: str = Field(
        default="gemini-2.5-flash",
        description="Escalation model used when the cheap judge is uncertain",
    )
    uncertainty_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Escalate when confidence falls below this threshold",
    )


class ToolQCRetryRule(BaseModel):
    """Deterministic retry/fallback rule triggered by semantic QC failure codes."""

    match_any_failure_modes: List[str] = Field(
        default_factory=list,
        description="Apply this rule when any listed failure mode is present",
    )
    min_attempt: int = Field(
        default=0,
        ge=0,
        description="Minimum zero-based QC retry attempt index this rule applies to",
    )
    max_attempt: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional maximum zero-based QC retry attempt index this rule applies to",
    )
    param_updates: Dict[str, Any] = Field(
        default_factory=dict,
        description="Deterministic parameter updates to apply before re-running the same tool",
    )
    fallback_tool: Optional[str] = Field(
        default=None,
        description="Optional fallback tool to switch to when this rule matches",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Human-readable explanation for the rule",
    )


class ToolQCRenderContract(BaseModel):
    """Metadata describing how QC visualizations should be rendered."""

    kind: Optional[str] = Field(
        default=None,
        description="High-level visualization kind, for example mask_overlay or checkerboard",
    )
    layout: Optional[str] = Field(
        default=None,
        description="Layout policy, for example tri_planar_montage",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Short operator-facing note about how to interpret the QC image",
    )


class ToolQCPrecheckConfig(BaseModel):
    """Deterministic checks that run before the vision judge."""

    required_outputs: Dict[str, str] = Field(
        default_factory=dict,
        description="Map output keys to failure modes when the expected output is missing",
    )
    required_artifacts: Dict[str, str] = Field(
        default_factory=dict,
        description="Map artifact keys to failure modes when the expected artifact is missing",
    )


class ToolQCSpec(BaseModel):
    """Per-tool semantic QC configuration executed after a step succeeds."""

    enabled: bool = Field(default=True, description="Whether semantic QC is enabled")
    artifact_output_keys: List[str] = Field(
        default_factory=list,
        description="Output artifact keys expected to contain QC image paths",
    )
    checklist: List[str] = Field(
        default_factory=list,
        description="Domain-specific checklist injected into the QC judge prompt",
    )
    failure_modes: List[str] = Field(
        default_factory=list,
        description="Allowed structured semantic QC failure codes",
    )
    judge: Optional[ToolQCJudgeConfig] = Field(
        default=None,
        description="Vision model selection policy for QC judgment",
    )
    render_contract: Optional[ToolQCRenderContract] = Field(
        default=None,
        description="Metadata describing the expected QC visualization contract",
    )
    prechecks: Optional[ToolQCPrecheckConfig] = Field(
        default=None,
        description="Deterministic pre-judge checks for required outputs and artifacts",
    )
    retry_rules: List[ToolQCRetryRule] = Field(
        default_factory=list,
        description="Ordered deterministic retry/fallback rules keyed by failure modes",
    )


class ToolSpec(BaseModel):
    """
    Complete specification for a tool including schema, examples, and metadata.

    This is what the LLM sees to understand how to properly call the tool.
    Unified model for both NiWrap-backed and pure Python tools.
    """

    # Core identity
    name: str = Field(
        description="Tool identifier (canonical runtime ID like 'fsl_bet' or namespaced public ID like 'br_kg.client')"
    )
    description: str = Field(description="Clear description of what the tool does")
    json_schema: Dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema from Pydantic model"
    )

    # Execution backend
    backend: Backend = Field(
        default="python",
        description="Execution backend: niwrap, python, or external_api",
    )
    python_class: Optional[str] = Field(
        default=None, description="Python import path for wrapper class"
    )
    niwrap_id: Optional[str] = Field(
        default=None,
        description="Adapter-private NiWrap descriptor ID (for example 'fsl.bet.run')",
    )

    # Routing metadata
    modalities: List[str] = Field(
        default_factory=list,
        description="Supported imaging modalities: fmri, smri, dmri, etc",
    )
    intents: List[str] = Field(
        default_factory=list,
        description="Task intents: skull_strip_mri, registration, etc",
    )
    kind: Optional[Kind] = Field(
        default=None,
        description="Coarse tool category: imaging, kg, viz, meta, data, analysis",
    )
    search_hint: Optional[str] = Field(
        default=None,
        description="Short retrieval-oriented phrase used for tool discovery and routing",
    )
    allowed_phases: List[ToolPhase] = Field(
        default_factory=list,
        description="Planning phases in which this tool should be considered",
    )
    approval_level: ApprovalLevel = Field(
        default="none",
        description="Human-approval level expected before this tool executes",
    )

    # I/O types
    consumes: List[str] = Field(
        default_factory=list, description="Input resource types this tool accepts"
    )
    produces: List[str] = Field(
        default_factory=list, description="Output resource types this tool produces"
    )

    # Legacy fields (preserved for compatibility)
    required: List[str] = Field(
        default_factory=list, description="Required parameter names"
    )
    defaults: Dict[str, Any] = Field(
        default_factory=dict, description="Default values for optional params"
    )
    synonyms: Dict[str, List[str]] = Field(
        default_factory=dict, description="Parameter name synonyms"
    )
    examples: List[ToolExample] = Field(
        default_factory=list, description="Usage examples"
    )
    safety_constraints: List[str] = Field(
        default_factory=list, description="Resource/safety limits"
    )
    category: Optional[str] = Field(
        default=None, description="Tool category (e.g., 'glm', 'connectivity')"
    )
    tags: List[str] = Field(
        default_factory=list, description="Lightweight tags for routing/filters"
    )
    dangerous: bool = Field(
        default=False, description="Whether this tool is unsafe for chat/direct calls"
    )
    cost_hint: Optional[str] = Field(
        default=None, description="Rough cost hint: cheap|normal|expensive"
    )
    device: str = Field(default="cpu", description="Required device: cpu or gpu")
    timeout_s: Optional[float] = Field(
        default=None,
        description="Max execution time (seconds) for a single tool call",
    )
    retry_policy: Optional[str] = Field(
        default=None,
        description="Retry policy label (e.g., none|transient|aggressive)",
    )
    idempotent: Optional[bool] = Field(
        default=None, description="Whether repeated calls are safe"
    )
    side_effects: List[str] = Field(
        default_factory=list,
        description="Declared side effects (e.g., writes_files, network, external_state)",
    )
    implementation_level: str = Field(
        default="production",
        description="Implementation maturity level (e.g., production, beta, stub)",
    )
    requires_runtime: Optional[str] = Field(
        default=None,
        description="Primary runtime needed to execute this tool (python|container|network|none)",
    )
    hard_dependencies: List[str] = Field(
        default_factory=list,
        description="Optional hard runtime/library dependencies for this tool",
    )
    execution_capabilities: Optional[ToolExecutionCapabilities] = Field(
        default=None,
        description="Declarative runtime capabilities and policy requirements",
    )
    qc_spec: Optional[ToolQCSpec] = Field(
        default=None,
        description="Optional semantic QC configuration executed after successful tool runs",
    )

    @model_validator(mode="after")
    def _populate_agent_routing_metadata(self) -> "ToolSpec":
        self.search_hint = _normalize_search_hint(
            self.search_hint,
            name=self.name,
            description=self.description,
            category=self.category,
            kind=self.kind,
            modalities=list(self.modalities or []),
            intents=list(self.intents or []),
            tags=list(self.tags or []),
        )
        self.allowed_phases = _normalize_allowed_phases(
            self.allowed_phases,
            name=self.name,
            backend=self.backend,
            kind=self.kind,
            category=self.category,
            intents=list(self.intents or []),
            side_effects=list(self.side_effects or []),
            dangerous=bool(self.dangerous),
            cost_hint=self.cost_hint,
            execution_capabilities=self.execution_capabilities,
        )
        self.approval_level = _normalize_approval_level(
            self.approval_level,
            allowed_phases=list(self.allowed_phases or []),
            backend=self.backend,
            dangerous=bool(self.dangerous),
            side_effects=list(self.side_effects or []),
            cost_hint=self.cost_hint,
            execution_capabilities=self.execution_capabilities,
        )
        return self

    def to_prompt_format(
        self, include_examples: bool = True, max_examples: int = 2
    ) -> str:
        """
        Convert to a concise format for LLM prompts.

        Args:
            include_examples: Whether to include usage examples
            max_examples: Maximum number of examples to include

        Returns:
            Formatted string for inclusion in prompts
        """
        lines = [
            f"Tool: {self.name}",
            f"Description: {self.description}",
            f"Required params: {', '.join(self.required) if self.required else 'none'}",
        ]

        # Add parameter details
        if self.json_schema.get("properties"):
            lines.append("Parameters:")
            for param_name, param_info in self.json_schema["properties"].items():
                param_desc = param_info.get("description", "No description")
                param_type = param_info.get("type", "any")
                required_mark = "*" if param_name in self.required else ""
                default_val = self.defaults.get(param_name)
                default_str = (
                    f" (default: {default_val})" if default_val is not None else ""
                )
                lines.append(
                    f"  - {param_name}{required_mark} ({param_type}): {param_desc}{default_str}"
                )

        # Add synonyms if present
        if self.synonyms:
            synonym_strs = [f"{k}: {', '.join(v)}" for k, v in self.synonyms.items()]
            lines.append(f"Synonyms: {'; '.join(synonym_strs)}")

        # Add examples
        if include_examples and self.examples:
            lines.append("Examples:")
            for i, example in enumerate(self.examples[:max_examples]):
                lines.append(f'  {i + 1}. Query: "{example.user_query}"')
                lines.append(f"     Params: {example.params}")
                if example.notes:
                    lines.append(f"     Note: {example.notes}")

        # Add safety constraints
        if self.safety_constraints:
            lines.append(f"Constraints: {', '.join(self.safety_constraints)}")

        return "\n".join(lines)

    def to_json_function_declaration(self) -> Dict[str, Any]:
        """
        Convert to OpenAI/Gemini function calling format.

        Returns:
            Dict suitable for function_declarations parameter
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.json_schema.get("properties", {}),
                "required": self.required,
            },
        }

    def to_routing_summary(self) -> str:
        """
        Convert to a compact format for LLM routing/candidate selection.

        Returns:
            Concise string with essential routing info
        """
        parts = [f"**{self.name}**: {self.description[:200]}"]
        if self.modalities:
            parts.append(f"  modalities: {self.modalities}")
        if self.intents:
            parts.append(f"  intents: {self.intents}")
        if self.kind:
            parts.append(f"  kind: {self.kind}")
        if self.backend != "python":
            parts.append(f"  backend: {self.backend}")
        return "\n".join(parts)


def spec_from_tool(tool) -> Optional[ToolSpec]:
    """
    Extract ToolSpec from a tool instance.

    Args:
        tool: Tool instance with get_tool_name(), get_tool_description(), get_args_schema()

    Returns:
        ToolSpec or None if extraction fails
    """
    try:
        # Get basic info
        name = tool.get_tool_name()
        description = tool.get_tool_description()
        template_spec = getattr(tool, "TOOL_SPEC", None)
        if template_spec is None:
            module = inspect.getmodule(tool)
            if module is not None:
                template_spec = getattr(module, "TOOL_SPEC", None)

        # Get schema from Pydantic model
        schema_class = tool.get_args_schema()
        if hasattr(schema_class, "model_json_schema"):
            json_schema = schema_class.model_json_schema()
        elif hasattr(schema_class, "schema"):
            json_schema = schema_class.schema()
        else:
            json_schema = {}

        # Extract required fields
        required = json_schema.get("required", [])

        # Extract defaults from schema
        defaults = {}
        if "properties" in json_schema:
            for field_name, field_info in json_schema["properties"].items():
                if "default" in field_info:
                    defaults[field_name] = field_info["default"]

        # Get tool-specific metadata if available
        synonyms = getattr(tool, "ARG_SYNONYMS", {})
        examples = getattr(tool, "EXAMPLES", [])
        safety = getattr(tool, "SAFETY", [])
        category = getattr(tool, "CATEGORY", None) or getattr(
            template_spec, "category", None
        )
        tags = getattr(tool, "TAGS", []) or getattr(tool, "tags", []) or []
        # Pull catalog metadata if attached to tool
        meta = getattr(tool, "metadata", {}) or getattr(tool, "META", {}) or {}
        domain = meta.get("domain")
        function = meta.get("function")
        runtime_kind = meta.get("runtime_kind")
        risk = meta.get("risk")
        implementation_level = normalize_implementation_level(
            meta.get("implementation_level")
            or getattr(tool, "IMPLEMENTATION_LEVEL", None),
            default="production",
        )
        requires_runtime = infer_requires_runtime(
            meta.get("requires_runtime") or getattr(tool, "REQUIRES_RUNTIME", None),
            runtime_kind=str(runtime_kind) if runtime_kind else None,
        )
        hard_dependencies = normalize_hard_dependencies(
            meta.get("hard_dependencies") or getattr(tool, "HARD_DEPENDENCIES", None)
        )

        # Normalize tags to include core metadata
        tags = normalize_tags(
            {
                "domain": domain,
                "function": function,
                "runtime_kind": runtime_kind,
                "risk": risk,
                "tags": tags,
            }
        )
        dangerous = bool(
            getattr(tool, "DANGEROUS", False)
            or getattr(tool, "dangerous", False)
            or getattr(template_spec, "dangerous", False)
        )
        cost_hint = getattr(tool, "COST_HINT", None) or getattr(
            template_spec, "cost_hint", None
        )
        timeout_s = getattr(tool, "TIMEOUT_S", None) or getattr(
            template_spec, "timeout_s", None
        )
        retry_policy = getattr(tool, "RETRY_POLICY", None) or getattr(
            template_spec, "retry_policy", None
        )
        idempotent = getattr(tool, "IDEMPOTENT", None)
        if idempotent is None:
            idempotent = getattr(template_spec, "idempotent", None)
        side_effects = getattr(tool, "SIDE_EFFECTS", None) or []
        if isinstance(side_effects, str):
            side_effects = [side_effects]
        elif not isinstance(side_effects, list):
            side_effects = []
        if not side_effects and getattr(template_spec, "side_effects", None):
            side_effects = list(getattr(template_spec, "side_effects"))

        # Extract execution capabilities
        execution_capabilities = None
        raw_caps = (
            getattr(tool, "EXECUTION_CAPABILITIES", None)
            or getattr(tool, "RUNTIME_CAPABILITIES", None)
            or getattr(tool, "execution_capabilities", None)
            or meta.get("execution_capabilities")
            or getattr(template_spec, "execution_capabilities", None)
        )
        try:
            if isinstance(raw_caps, ToolExecutionCapabilities):
                execution_capabilities = raw_caps
            elif isinstance(raw_caps, dict):
                execution_capabilities = ToolExecutionCapabilities(**raw_caps)
        except Exception:
            execution_capabilities = None

        qc_spec = normalize_qc_spec(
            meta.get("qc_spec")
            or getattr(tool, "QC_SPEC", None)
            or getattr(tool, "qc_spec", None)
            or getattr(template_spec, "qc_spec", None)
        )
        search_hint = (
            meta.get("search_hint")
            or getattr(tool, "SEARCH_HINT", None)
            or getattr(tool, "search_hint", None)
            or getattr(template_spec, "search_hint", None)
        )
        allowed_phases = (
            meta.get("allowed_phases")
            or getattr(tool, "ALLOWED_PHASES", None)
            or getattr(tool, "allowed_phases", None)
            or getattr(template_spec, "allowed_phases", None)
            or []
        )
        approval_level = (
            meta.get("approval_level")
            or getattr(tool, "APPROVAL_LEVEL", None)
            or getattr(tool, "approval_level", None)
            or getattr(template_spec, "approval_level", None)
            or "none"
        )

        # Heuristic cost/danger if not provided
        if cost_hint is None:
            heavy_patterns = (
                "fmriprep",
                "qsiprep",
                "xcpd",
                "cpac",
                "mriqc",
                "ants",
                "freesurfer",
                "afni",
                "feat",
                "melodic",
                "bedpostx",
                "palm",
                "fix",
            )
            name_l = name.lower()
            if any(p in name_l for p in heavy_patterns):
                cost_hint = "expensive"
                dangerous = dangerous or True

        # Convert examples to ToolExample objects if needed
        if examples and isinstance(examples[0], dict):
            examples = [ToolExample(**ex) for ex in examples]

        return ToolSpec(
            name=name,
            description=description[:500],  # Limit description length
            json_schema=json_schema,
            required=required,
            defaults=defaults,
            synonyms=synonyms,
            examples=examples,
            safety_constraints=safety,
            category=category,
            tags=tags,
            search_hint=search_hint,
            allowed_phases=allowed_phases,
            approval_level=approval_level,
            dangerous=dangerous,
            cost_hint=cost_hint,
            timeout_s=timeout_s,
            retry_policy=retry_policy,
            idempotent=idempotent,
            side_effects=side_effects,
            implementation_level=implementation_level,
            requires_runtime=requires_runtime,
            hard_dependencies=hard_dependencies,
            execution_capabilities=execution_capabilities,
            qc_spec=qc_spec,
        )

    except Exception as e:
        logger.warning(f"Failed to extract spec from tool {tool}: {e}")
        return None


def compress_schema(schema: Dict[str, Any], max_properties: int = 10) -> Dict[str, Any]:
    """
    Compress a JSON schema to reduce token usage.

    Args:
        schema: Original JSON schema
        max_properties: Maximum number of properties to include

    Returns:
        Compressed schema
    """
    compressed = schema.copy()

    # Limit number of properties
    if "properties" in compressed and len(compressed["properties"]) > max_properties:
        # Keep required fields and most important optional ones
        required = set(compressed.get("required", []))
        properties = compressed["properties"]

        # Sort properties: required first, then by name
        sorted_props = sorted(
            properties.items(), key=lambda x: (x[0] not in required, x[0])
        )

        compressed["properties"] = dict(sorted_props[:max_properties])
        compressed["additional_properties_count"] = len(properties) - max_properties

    # Remove verbose descriptions if too long
    if "properties" in compressed:
        for prop_name, prop_info in compressed["properties"].items():
            if "description" in prop_info and len(prop_info["description"]) > 100:
                prop_info["description"] = prop_info["description"][:97] + "..."

    return compressed


# Global parameter synonyms used across multiple tools
GLOBAL_SYNONYMS = {
    "t_r": ["TR", "repetition_time", "tr"],
    "fwhm": ["smoothing_fwhm", "smooth", "kernel_size"],
    "mask_img": ["mask", "brain_mask", "mask_file"],
    "confounds": ["regressors", "nuisance", "confound_regressors"],
    "standardize": ["zscore", "normalize", "z_score"],
    "detrend": ["remove_trend", "detrending"],
    "high_pass": ["hp_filter", "highpass", "hp"],
    "low_pass": ["lp_filter", "lowpass", "lp"],
    "n_jobs": ["n_cpus", "n_cores", "parallel"],
    "verbose": ["verbosity", "debug", "log_level"],
    "img": ["image", "input_image", "bold_img", "fmri_img"],
    "events": ["events_file", "paradigm", "timing_file"],
    "output_dir": ["out_dir", "output", "results_dir"],
    "subject": ["sub", "subject_id", "participant"],
    "session": ["ses", "session_id"],
    "task": ["task_name", "task_label"],
    "run": ["run_id", "run_number"],
}


# BIDS metadata to parameter mapping
BIDS_TO_PARAM = {
    "RepetitionTime": "t_r",
    "SliceTiming": "slice_times",
    "TaskName": "task",
    "PhaseEncodingDirection": "pe_dir",
    "TotalReadoutTime": "readout_time",
    "EchoTime": "te",
    "FlipAngle": "flip_angle",
    "ParallelReductionFactorInPlane": "acceleration",
    "EffectiveEchoSpacing": "echo_spacing",
    "BandwidthPerPixelPhaseEncode": "bandwidth",
}


class ToolSpecRegistry:
    """Registry for managing tool specifications."""

    def __init__(self):
        self.specs: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec):
        """Register a tool specification."""
        self.specs[spec.name] = spec
        logger.info(f"Registered tool spec: {spec.name}")

    def get(self, name: str) -> Optional[ToolSpec]:
        """Get a tool specification by name."""
        return self.specs.get(name)

    def search(self, query: str, top_k: int = 8) -> List[ToolSpec]:
        """
        Search for relevant tools based on query.

        Simple keyword matching for now, can be enhanced with embeddings.
        """
        query_lower = query.lower()
        scores = []

        for name, spec in self.specs.items():
            score = 0

            # Check name match
            if name.lower() in query_lower:
                score += 10

            # Check description match
            desc_lower = spec.description.lower()
            for word in query_lower.split():
                if word in desc_lower:
                    score += 1

            # Check category match
            if spec.category and spec.category.lower() in query_lower:
                score += 5

            # Check example matches
            for example in spec.examples:
                if any(
                    word in example.user_query.lower() for word in query_lower.split()
                ):
                    score += 2

            if score > 0:
                scores.append((score, spec))

        # Sort by score and return top-k
        scores.sort(key=lambda x: x[0], reverse=True)
        return [spec for _, spec in scores[:top_k]]
