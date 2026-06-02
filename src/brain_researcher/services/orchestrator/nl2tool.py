"""Lightweight natural-language routing for orchestrator pipelines.

This module blends rule-based heuristics with the MCP tool catalog and an
optional LLM refinement step. The public surface mirrors the previous
implementation so existing callers and tests continue to work, while the
additional metadata (``resolved_tool`` and ``candidates``) lets downstream
systems surface the concrete tool that will execute the request.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # pragma: no cover - optional dependency in slim environments
    from jsonschema import ValidationError
    from jsonschema import validate as jsonschema_validate
except Exception:  # pragma: no cover
    ValidationError = None  # type: ignore
    jsonschema_validate = None  # type: ignore

import httpx

logger = logging.getLogger(__name__)

from .models import PipelineType


# MCP catalog removed; use unified tool registry fallback
def get_global_catalog():
    return None


CATALOG = get_global_catalog()


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class ToolDecision:
    """Decision payload describing the chosen pipeline/tool."""

    pipeline: PipelineType
    tool: str
    confidence: float
    parameters: Dict[str, Any] = field(default_factory=dict)
    rationale: Optional[str] = None
    source: str = "rules"
    resolved_tool: Optional[str] = None
    candidates: List[str] = field(default_factory=list)
    profile: Optional[str] = None

    def to_metadata(self) -> Dict[str, Any]:
        data = {
            "pipeline": (
                self.pipeline.value
                if isinstance(self.pipeline, PipelineType)
                else self.pipeline
            ),
            "tool": self.tool,
            "confidence": self.confidence,
            "parameters": self.parameters,
            "rationale": self.rationale,
            "source": self.source,
        }
        if self.profile:
            data["profile"] = self.profile
        if self.resolved_tool:
            data["resolved_tool"] = self.resolved_tool
        if self.candidates:
            data["candidates"] = self.candidates
        return data


@dataclass(frozen=True)
class _PipelineRule:
    alias: str
    pipeline: PipelineType
    confidence: float
    rationale: str
    patterns: Tuple[str, ...]
    zh_patterns: Tuple[str, ...]
    preferred_tools: Tuple[str, ...]
    preferred_tags: Tuple[str, ...]


# ---------------------------------------------------------------------------
# Rule configuration
# ---------------------------------------------------------------------------


_DATASET_RX = re.compile(r"\b(ds\d{5,6}|ds00\d+|hcp|abcd|ukbb|camcan)\b", re.IGNORECASE)
_CHINESE_RX = re.compile(r"[\u4e00-\u9fff]")
_DATASET_QUERY_RX = re.compile(
    r"\b(list|available|show|find|what)\b[^\n]*\bdatasets?\b", re.IGNORECASE
)
_DATASET_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "what",
    "which",
    "available",
    "here",
    "dataset",
    "datasets",
    "list",
    "show",
    "find",
    "please",
    "tell",
    "me",
    "about",
}

_PLANNING_RX = re.compile(
    r"\b(plan|pipeline|workflow|outline|steps?|roadmap|strategy|design)\b",
    re.IGNORECASE,
)
_EXECUTION_RX = re.compile(
    r"\b(run|execute|compute|calculate|generate|derive|produce|perform)\b",
    re.IGNORECASE,
)

_PIPELINE_RULES: Tuple[_PipelineRule, ...] = (
    # Coding profile rule – only wins when explicitly selected or matched by coding verbs
    _PipelineRule(
        alias="code",
        pipeline=PipelineType.CUSTOM,
        confidence=0.70,
        rationale="coding keywords",
        patterns=(
            r"\b(read|open|edit|patch|apply[_-]?patch|diff|grep|rg|ripgrep|search)\b",
            r"\b(test|pytest|unittest)\b",
            r"\b(endpoint|route|api|handler)\b",
            r"\bbuild|lint|format\b",
        ),
        zh_patterns=("读取", "打开", "补丁", "测试", "接口", "路由"),
        preferred_tools=(
            "fs.read",
            "fs.apply_patch",
        ),
        preferred_tags=("fs", "tests", "write"),
    ),
    _PipelineRule(
        alias="glm",
        pipeline=PipelineType.GLM,
        confidence=0.78,
        rationale="glm keywords",
        patterns=(
            r"\bglm\b",
            r"first[- ]?level",
            r"second[- ]?level",
            r"contrast",
            r"beta",
            r"design matrix",
            r"fitlins",
        ),
        zh_patterns=("广义线性", "一级", "二级", "对比", "回归"),
        preferred_tools=(
            "fitlins.recipe.run",
            "nilearn.glm.first_level.run",
            "nilearn.glm.second_level.run",
            "fsl.feat.run",
        ),
        preferred_tags=("glm", "fitlins", "nilearn", "fsl"),
    ),
    _PipelineRule(
        alias="connectivity",
        pipeline=PipelineType.CONNECTIVITY,
        confidence=0.72,
        rationale="connectivity keywords",
        patterns=(
            r"rest(ing)?[- ]?state",
            r"\bconnectivit(y|ies)\b",
            r"seed[- ]?based",
            r"correlation matrix",
            r"functional connectivity",
        ),
        zh_patterns=("静息态", "连接", "相关矩阵", "种子"),
        preferred_tools=(
            "nilearn.connectivity.matrix.run",
            "nilearn.seed_connectivity.run",
            "dynamic_connectivity.run",
        ),
        preferred_tags=("connectivity", "connectome", "nilearn"),
    ),
    _PipelineRule(
        alias="meta_analysis",
        pipeline=PipelineType.CUSTOM,
        confidence=0.7,
        rationale="meta-analysis keywords",
        patterns=(r"meta[- ]?analysis", r"nimare", r"coordinate[- ]?based", r"ale\b"),
        zh_patterns=("荟萃", "随机效应"),
        preferred_tools=("neurosynth.meta_analysis.run",),
        preferred_tags=("meta_analysis", "nimare", "neurosynth"),
    ),
    _PipelineRule(
        alias="ingest",
        pipeline=PipelineType.PIPELINE_BUILDER,
        confidence=0.68,
        rationale="ingest keywords",
        patterns=(
            "ingest",
            "ingestion",
            "import dataset",
            "load dataset",
            "openneuro",
            "list dataset",
            "list datasets",
            "available dataset",
            "available datasets",
            "what datasets",
            "dataset catalog",
            "dataset list",
        ),
        zh_patterns=("入库", "导入", "抓取", "爬取"),
        preferred_tools=(
            "openneuro_list_files",
            "openneuro_download",
            "dandi_search",
            "dandi_download",
        ),
        preferred_tags=("bids", "ingest", "openneuro", "dandi", "dataset"),
    ),
)

_PIPELINE_ALIAS_TO_RULE = {rule.alias: rule for rule in _PIPELINE_RULES}

_DEFAULT_TOOL_FOR_PIPELINE: Dict[PipelineType, str] = {
    PipelineType.GLM: "glm",
    PipelineType.CONNECTIVITY: "connectivity",
    PipelineType.CUSTOM: "meta_analysis",
    PipelineType.PIPELINE_BUILDER: "ingest",
    PipelineType.CHAT: "chat",
    PipelineType.COPILOT: "copilot",
}


def _is_test_env() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _language_hint(text: str) -> str:
    return "zh" if _CHINESE_RX.search(text) else "en"


def _extract_dataset(text: str) -> Optional[str]:
    match = _DATASET_RX.search(text)
    if match:
        value = match.group(1)
        if value:
            return value.lower()
    return None


def _extract_dataset_search_terms(text: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    keywords = [tok for tok in tokens if tok not in _DATASET_STOPWORDS]
    if keywords:
        return " ".join(keywords)
    return "datasets"


def _coerce_pipeline(value: Optional[str], default: PipelineType) -> PipelineType:
    if not value:
        return default
    for member in PipelineType:
        if member.value == value or member.name.lower() == str(value).lower():
            return member
    return default


def _rule_match(
    prompt: str,
    attachments: Optional[Sequence[str]],
    current_pipeline: Optional[PipelineType],
    profile: Optional[str] = None,
) -> ToolDecision:
    prompt_norm = prompt.strip()
    lang = _language_hint(prompt_norm)

    if current_pipeline and current_pipeline not in {
        PipelineType.CUSTOM,
        PipelineType.CHAT,
        PipelineType.COPILOT,
    }:
        alias = _DEFAULT_TOOL_FOR_PIPELINE.get(current_pipeline, current_pipeline.value)
        rationale = f"pipeline_hint:{current_pipeline.value}"
        return ToolDecision(
            pipeline=current_pipeline,
            tool=alias,
            confidence=0.6,
            rationale=rationale,
            source="hint",
        )

    if profile and profile.lower() == "code":
        return ToolDecision(
            pipeline=PipelineType.CUSTOM,
            tool="code",
            confidence=0.7,
            rationale="profile:code",
            source="rules",
            profile="code",
        )

    if attachments:
        return ToolDecision(
            pipeline=PipelineType.CUSTOM,
            tool="file_qa",
            confidence=0.76,
            rationale="attachments present",
            source="rules",
            profile=profile,
        )

    lowered = prompt_norm.lower()

    planning_intent = bool(_PLANNING_RX.search(prompt_norm))
    execution_intent = bool(_EXECUTION_RX.search(prompt_norm))

    if planning_intent and (
        not execution_intent or (profile and profile.lower() == "analysis")
    ):
        return ToolDecision(
            pipeline=PipelineType.CHAT,
            tool="agent",
            confidence=0.74,
            rationale="planning_intent",
            source="rules",
            profile=profile,
        )

    for rule in _PIPELINE_RULES:
        if any(
            re.search(pattern, prompt_norm, re.IGNORECASE) for pattern in rule.patterns
        ) or (
            lang == "zh" and any(pattern in prompt_norm for pattern in rule.zh_patterns)
        ):
            return ToolDecision(
                pipeline=rule.pipeline,
                tool=rule.alias,
                confidence=rule.confidence,
                rationale=f"matched:{rule.rationale}",
                source="rules",
                profile=profile,
            )

    # Default: generic chat agent
    return ToolDecision(
        pipeline=PipelineType.CHAT,
        tool="agent",
        confidence=0.5,
        rationale="default",
        source="rules",
        profile=profile,
    )


def _top_candidates(
    rule: _PipelineRule, prompt: str, limit: int
) -> List[Dict[str, Any]]:
    if CATALOG:
        candidates = CATALOG.candidates(
            prompt,
            preferred_tags=rule.preferred_tags,
            preferred_tools=rule.preferred_tools,
            limit=limit,
        )
        if candidates:
            return candidates
    if rule.preferred_tools:
        selected = [
            tool for tool in _FALLBACK_TOOLS if tool.get("name") in rule.preferred_tools
        ]
        if selected:
            return selected[:limit]
    if rule.preferred_tags:
        selected = [
            tool
            for tool in _FALLBACK_TOOLS
            if set(rule.preferred_tags).intersection(tool.get("tags") or [])
        ]
        if selected:
            return selected[:limit]
    return list(_FALLBACK_TOOLS[:limit])


def _maybe_run_llm(
    prompt: str, rule: _PipelineRule, candidates: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    if _is_test_env():
        return None

    endpoint = os.getenv("TOOL_SELECTOR_URL")
    timeout = float(os.getenv("TOOL_SELECTOR_TIMEOUT", "6.0"))
    margin = float(os.getenv("TOOL_SELECTOR_MARGIN", "0.15"))

    if endpoint:
        if not candidates:
            return None

        api_key = os.getenv("TOOL_SELECTOR_API_KEY")
        payload = {
            "prompt": prompt,
            "language": _language_hint(prompt),
            "rule_alias": rule.alias,
            "candidates": [
                {
                    "name": tool.get("name"),
                    "tags": tool.get("tags", []),
                    "description": tool.get("description"),
                    "score": idx + 1,
                }
                for idx, tool in enumerate(candidates)
            ],
            "schema_enforced": True,
        }

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network failures
            logger.warning("Tool selector LLM call failed: %s", exc)
            return None

        try:
            data = response.json()
        except json.JSONDecodeError:  # pragma: no cover
            logger.warning("Tool selector response was not valid JSON")
            return None
    else:
        gemini_key = (
            os.getenv("TOOL_SELECTOR_GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )
        if not gemini_key or not candidates:
            return None

        model = (
            os.getenv("TOOL_SELECTOR_GEMINI_MODEL")
            or os.getenv("DEFAULT_LLM_MODEL")
            or "gemini-1.5-flash"
        )
        if "gemini" not in model:
            model = "gemini-1.5-flash"

        options = "\n".join(
            f"- {tool.get('name')} (tags: {', '.join(tool.get('tags', []))})"
            for tool in candidates
        )
        instruction = (
            "You are a routing controller that must choose ONE tool from the allowed list.\n"
            "Return strict JSON with keys: pipeline (string), tool (string), confidence (0-1 float), "
            "parameters (object), rationale (string). The tool must match exactly one of the names provided. "
            "If you are unsure, fall back to the suggested default alias."
        )
        user_prompt = (
            f"User request: {prompt}\n\n"
            f"Suggested default alias: {rule.alias}\n"
            f"Allowed tool names:\n{options}\n"
            "Respond with JSON only."
        )

        request_payload = {
            "systemInstruction": {
                "role": "system",
                "parts": [{"text": instruction}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "topP": 0.0,
                "responseMimeType": "application/json",
            },
        }

        base_url = os.getenv(
            "TOOL_SELECTOR_GEMINI_BASE", "https://generativelanguage.googleapis.com"
        )
        endpoint = f"{base_url}/v1beta/models/{model}:generateContent?key={gemini_key}"

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(endpoint, json=request_payload)
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network failures
            logger.warning("Gemini tool selector request failed: %s", exc)
            return None

        try:
            body = response.json()
            candidate_parts = (
                body.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            )
            data = (
                json.loads(candidate_parts[0].get("text", "{}"))
                if candidate_parts
                else {}
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to parse Gemini selector response: %s", exc)
            return None

    tool_name = data.get("tool")
    if not tool_name:
        return None

    candidate_map = {tool.get("name"): tool for tool in candidates}
    selected = candidate_map.get(tool_name)
    if not selected:
        logger.debug("LLM selected unknown tool %s; ignoring", tool_name)
        return None

    confidence = float(data.get("confidence", 0.0))
    if confidence <= 0:
        return None

    parameters = data.get("parameters") or {}
    if not isinstance(parameters, dict):
        parameters = {}

    if jsonschema_validate and isinstance(selected.get("input_schema"), dict):
        try:
            jsonschema_validate(instance=parameters, schema=selected["input_schema"])
        except ValidationError as exc:  # pragma: no cover - depends on schema
            logger.warning("Tool selector parameters failed validation: %s", exc)
            return None

    pipeline = _coerce_pipeline(data.get("pipeline"), default=rule.pipeline)

    return {
        "tool": tool_name,
        "confidence": confidence,
        "parameters": parameters,
        "rationale": data.get("rationale"),
        "pipeline": pipeline,
        "margin": margin,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_tool(
    prompt: str,
    attachments: Optional[List[str]] = None,
    current_pipeline: Optional[PipelineType] = None,
    max_candidates: int = 6,
    profile: Optional[str] = None,
    validate_schema: bool = True,
) -> ToolDecision:
    """Select the best-fit pipeline/tool for a natural-language prompt.

    Parameters
    ----------
    prompt:
        Raw user prompt.
    attachments:
        Optional filenames associated with the prompt (biases toward file QA).
    current_pipeline:
        Pipeline hint provided by the client (respected when more specific than
        the generic pipelines).
    max_candidates:
        Upper bound on candidates forwarded to the LLM (defaults to six).
    profile:
        User profile hint (e.g., "code", "analysis").
    validate_schema:
        Whether to validate parameters against tool schema.
    """

    decision = _rule_match(prompt, attachments, current_pipeline, profile=profile)
    decision.profile = profile or decision.profile

    parameters = dict(decision.parameters)
    dataset_id = _extract_dataset(prompt)
    if dataset_id:
        parameters.setdefault("dataset_id", dataset_id)
    decision.parameters = parameters

    lowered_prompt = prompt.lower()
    dataset_listing = (
        decision.tool == "ingest"
        and not dataset_id
        and bool(_DATASET_QUERY_RX.search(prompt))
    )
    if dataset_listing:
        search_term = _extract_dataset_search_terms(prompt)
        decision.parameters.setdefault("search_term", search_term)
        decision.parameters.setdefault("max_results", max(5, max_candidates))
        decision.resolved_tool = "dandi_search"
        decision.candidates = ["dandi_search"]
        return decision

    rule = _PIPELINE_ALIAS_TO_RULE.get(decision.tool)
    candidates: List[Dict[str, Any]] = []
    if rule:
        candidates = _top_candidates(rule, prompt, limit=max_candidates)
        decision.candidates = [
            tool.get("name") for tool in candidates if tool.get("name")
        ]
        if candidates:
            decision.resolved_tool = candidates[0].get("name")

        llm_choice = _maybe_run_llm(prompt, rule, candidates)
        if (
            llm_choice
            and llm_choice["confidence"] >= decision.confidence + llm_choice["margin"]
        ):
            decision.pipeline = llm_choice["pipeline"]
            decision.parameters.update(llm_choice["parameters"])
            decision.confidence = llm_choice["confidence"]
            decision.rationale = (
                llm_choice.get("rationale") or decision.rationale or ""
            ).strip()
            decision.source = "llm"
            decision.resolved_tool = llm_choice["tool"]

            alias = _DEFAULT_TOOL_FOR_PIPELINE.get(decision.pipeline)
            if alias:
                decision.tool = alias
            else:
                decision.tool = decision.pipeline.value

    # Validate parameters against tool schema if requested
    if validate_schema and decision.resolved_tool and decision.parameters:
        validation_errors = validate_tool_parameters(
            decision.resolved_tool, decision.parameters
        )
        if validation_errors:
            logger.warning(
                f"Tool parameter validation failed for {decision.resolved_tool}: {validation_errors}"
            )
            # Store validation errors in decision for caller to handle
            if "validation_errors" not in decision.parameters:
                decision.parameters["_validation_errors"] = validation_errors

    return decision


def validate_tool_parameters(tool_name: str, parameters: Dict[str, Any]) -> List[str]:
    """Validate parameters against a tool's input schema.

    Args:
        tool_name: Name of the tool to validate against
        parameters: Parameter dictionary to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    if not jsonschema_validate:
        logger.debug("jsonschema not available, skipping validation")
        return []

    # Get tool definition from catalog
    if not CATALOG:
        logger.debug("Tool catalog unavailable, skipping validation")
        return []

    tool_def = CATALOG.describe(tool_name)
    if not tool_def:
        return [f"Tool '{tool_name}' not found in catalog"]

    input_schema = tool_def.get("input_schema")
    if not input_schema:
        logger.debug(f"No input schema defined for tool '{tool_name}'")
        return []

    # Remove internal parameters before validation
    params_to_validate = {k: v for k, v in parameters.items() if not k.startswith("_")}

    # Perform validation
    try:
        jsonschema_validate(instance=params_to_validate, schema=input_schema)
        return []
    except ValidationError as exc:
        # Extract meaningful error messages
        errors = [str(exc.message)]
        # Add path information if available
        if exc.path:
            path_str = ".".join(str(p) for p in exc.path)
            errors[0] = f"{path_str}: {errors[0]}"
        return errors
    except Exception as exc:
        logger.error(f"Unexpected error during schema validation: {exc}", exc_info=True)
        return [f"Validation error: {str(exc)}"]


__all__ = ["ToolDecision", "select_tool"]
# Fallback catalog used when MCP tool catalog is unavailable inside the runtime
_FALLBACK_TOOLS: Tuple[Dict[str, Any], ...] = (
    {
        "name": "fs.read",
        "tags": ["fs"],
        "description": "Read a file from the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "additionalProperties": True,
        },
    },
    {
        "name": "fs.apply_patch",
        "tags": ["fs", "write"],
        "description": "Apply a unified patch to files in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"patch": {"type": "string"}},
            "additionalProperties": True,
        },
    },
    {
        "name": "nilearn.glm.first_level.run",
        "tags": ["nilearn", "glm", "fmri"],
        "description": "First-level GLM estimation with Nilearn.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
    },
    {
        "name": "nilearn.glm.second_level.run",
        "tags": ["nilearn", "glm", "fmri"],
        "description": "Second-level GLM estimation with Nilearn.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
    },
    {
        "name": "nilearn.connectivity.matrix.run",
        "tags": ["nilearn", "connectivity", "fmri"],
        "description": "Compute connectivity matrices using Nilearn.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
    },
    {
        "name": "nilearn.seed_connectivity.run",
        "tags": ["nilearn", "connectivity", "fmri"],
        "description": "Seed-based connectivity analysis with Nilearn.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
    },
    {
        "name": "neurosynth.meta_analysis.run",
        "tags": ["neurosynth", "meta_analysis"],
        "description": "Coordinate-based meta-analysis using NiMARE/NeuroSynth.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
    },
    {
        "name": "bids.validate",
        "tags": ["bids", "ingest"],
        "description": "Validate BIDS dataset structure.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
    },
)
