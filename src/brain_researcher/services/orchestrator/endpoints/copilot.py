"""
Copilot suggestion endpoints.

Provides lightweight, heuristic-based suggestions for parameters and next steps.
In production, this can forward to an Agent service for richer inference.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter
from pydantic import BaseModel, Field

from brain_researcher.config.paths import get_data_root, resolve_from_config
from brain_researcher.services.agent.copilot import CopilotAssistant, CopilotMemory
from brain_researcher.services.tools.tool_registry import ToolRegistry

router = APIRouter(prefix="/copilot", tags=["copilot"])


class CopilotSuggestRequest(BaseModel):
    query: str = Field(..., description="User query text")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    k: int = Field(5, ge=1, le=20, description="Max number of suggestions")
    exposures: Optional[List[str]] = Field(
        default=None,
        description="Preferred exposure levels (chat/pipeline/cli/advanced/internal)",
    )
    domain: Optional[str] = Field(default=None, description="Domain filter")
    function: Optional[str] = Field(default=None, description="Function filter")
    risk: Optional[str] = Field(default=None, description="Risk filter")


class CopilotSuggestion(BaseModel):
    name: str
    description: str
    reason: str
    score: float = Field(1.0, ge=0.0, le=3.0, description="Confidence score (0-3 scale)")
    autocomplete: Optional[Dict[str, Any]] = None


class CopilotMethodParameter(BaseModel):
    name: str
    description: str
    value: Optional[str | float | int | bool] = None


class CopilotMethod(BaseModel):
    id: str
    intent_id: str
    name: str
    description: str
    reason: str
    score: float = Field(1.0, ge=0.0, le=3.0, description="Confidence score (0-3 scale)")
    parameters: List[CopilotMethodParameter] = Field(default_factory=list)


class CopilotSuggestResponse(BaseModel):
    suggestions: List[CopilotSuggestion]
    methods: List[CopilotMethod] = Field(default_factory=list)


class CopilotAutocompleteRequest(BaseModel):
    tool: str = Field(..., description="Tool name to complete parameters for")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class CopilotAutocompleteResponse(BaseModel):
    tool: str
    completed: Dict[str, Any]


class CopilotLearnRequest(BaseModel):
    tool: str = Field(..., description="Selected tool name")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)


class CopilotLearnResponse(BaseModel):
    status: str = Field(default="ok")
    tool: str


FUNCTION_HINTS: Dict[str, List[str]] = {
    "preproc": ["preprocess", "preprocessing", "fmriprep", "mriqc", "motion", "denoise", "qc"],
    "glm": ["glm", "fitlins", "design", "contrast", "stats"],
    "connectivity": ["connectivity", "connectome", "timeseries", "parcellation", "graph"],
    "qc": ["qc", "quality", "mriqc", "preflight"],
    "analysis": ["analysis", "model", "inference"],
    "decoding": ["decoding", "mvpa", "classifier", "prediction"],
    "visualization": ["visual", "plot", "surface", "render"],
    "report": ["report", "summary", "dashboard", "html"],
}

DOMAIN_MODALITY_HINTS: Dict[str, List[str]] = {
    "fmri": ["fmri"],
    "dmri": ["dmri"],
    "eeg": ["eeg", "meg"],
    "ieeg": ["ieeg"],
    "surface": ["smri", "fmri"],
    "datasets": ["fmri", "dmri", "smri", "eeg", "meg", "ieeg", "general"],
    "kg": ["general", "fmri", "dmri", "smri", "eeg", "meg", "ieeg"],
}

INPUT_PARAM_DEFAULTS: Dict[str, tuple[str, str, Optional[str | float | int | bool]]] = {
    "parcellation": ("parcellation", "Atlas / parcellation for ROI definition", "Schaefer2018_200"),
    "parcellation_labels": ("parcellation", "Atlas / parcellation for ROI definition", "Schaefer2018_200"),
    "timeseries": ("bandpass_filter", "Temporal filtering band (Hz)", "0.01-0.1"),
    "design_matrix": ("hrf_model", "Hemodynamic response function model", "spm"),
    "stats_map": ("threshold", "Voxel-wise statistical threshold", 0.001),
    "volume_4d": ("smoothing_fwhm", "Spatial smoothing kernel (FWHM in mm)", 6),
    "bids_root": ("dataset_path", "BIDS dataset root path", None),
}


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_]+", text.lower())
        if len(token) >= 3
    }


@lru_cache(maxsize=1)
def _load_intent_catalog() -> List[Dict[str, Any]]:
    path = resolve_from_config("catalog", "intents.yaml")
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("id") and item.get("name")]


@lru_cache(maxsize=1)
def _get_copilot_assistant() -> CopilotAssistant:
    # Copilot HTTP ownership now lives with Orchestrator; keep the runtime
    # dependency light by skipping full tool auto-discovery for non-suggest paths.
    memory_path = get_data_root() / "copilot" / "memory.json"
    return CopilotAssistant(
        tool_registry=ToolRegistry(auto_discover=False),
        memory=CopilotMemory(storage_path=memory_path),
    )


def _function_matches(intent: Dict[str, Any], function_filter: Optional[str]) -> bool:
    if not function_filter:
        return True
    hints = FUNCTION_HINTS.get(function_filter, [])
    if not hints:
        return True
    haystack = " ".join(
        [
            str(intent.get("id", "")),
            str(intent.get("name", "")),
            str(intent.get("description", "")),
            " ".join([str(v) for v in intent.get("parents", []) if isinstance(v, str)]),
        ]
    ).lower()
    return any(hint in haystack for hint in hints)


def _domain_matches(intent: Dict[str, Any], domain_filter: Optional[str]) -> bool:
    if not domain_filter:
        return True
    modalities = [str(v).lower() for v in intent.get("modalities", []) if isinstance(v, str)]
    hints = DOMAIN_MODALITY_HINTS.get(domain_filter, [])
    if not hints:
        return True
    return bool(set(modalities) & set(hints))


def _score_intent(
    *,
    intent: Dict[str, Any],
    query_tokens: set[str],
    function_filter: Optional[str],
    domain_filter: Optional[str],
) -> float:
    searchable_text = " ".join(
        [
            str(intent.get("id", "")),
            str(intent.get("name", "")),
            str(intent.get("description", "")),
            " ".join([str(v) for v in intent.get("parents", []) if isinstance(v, str)]),
            " ".join([str(v) for v in intent.get("modalities", []) if isinstance(v, str)]),
        ]
    ).lower()
    searchable_tokens = _tokenize(searchable_text)
    overlap = len(query_tokens & searchable_tokens)
    score = 0.6 + (0.3 * overlap)
    if function_filter and _function_matches(intent, function_filter):
        score += 0.8
    if domain_filter and _domain_matches(intent, domain_filter):
        score += 0.6
    return max(0.0, min(3.0, score))


def _build_method_parameters(
    intent: Dict[str, Any],
    metadata: Dict[str, Any],
) -> List[CopilotMethodParameter]:
    inputs = [str(v).lower() for v in intent.get("inputs", []) if isinstance(v, str)]
    params: List[CopilotMethodParameter] = []
    seen: set[str] = set()
    for key in inputs:
        if key in INPUT_PARAM_DEFAULTS:
            name, description, default_value = INPUT_PARAM_DEFAULTS[key]
            value = metadata.get(name, default_value)
            if name in seen:
                continue
            seen.add(name)
            params.append(
                CopilotMethodParameter(
                    name=name,
                    description=description,
                    value=value,
                )
            )
            continue
        if key in seen:
            continue
        seen.add(key)
        params.append(
            CopilotMethodParameter(
                name=key,
                description=f"Input requirement for {intent.get('name', 'method')}",
                value=metadata.get(key),
            )
        )
        if len(params) >= 4:
            break
    return params


def _build_methods(request: CopilotSuggestRequest) -> List[CopilotMethod]:
    intents = _load_intent_catalog()
    if not intents:
        return []
    query_tokens = _tokenize(request.query)
    if not query_tokens:
        query_tokens = {"analysis"}
    scored: List[tuple[float, Dict[str, Any]]] = []
    for intent in intents:
        if not _function_matches(intent, request.function):
            continue
        if not _domain_matches(intent, request.domain):
            continue
        score = _score_intent(
            intent=intent,
            query_tokens=query_tokens,
            function_filter=request.function,
            domain_filter=request.domain,
        )
        if score <= 0:
            continue
        scored.append((score, intent))
    scored.sort(key=lambda item: item[0], reverse=True)

    methods: List[CopilotMethod] = []
    for rank, (score, intent) in enumerate(scored[: request.k]):
        intent_id = str(intent.get("id"))
        reason_parts = ["Matched intent catalog entry for this query"]
        if request.function:
            reason_parts.append(f"function={request.function}")
        if request.domain:
            reason_parts.append(f"domain={request.domain}")
        methods.append(
            CopilotMethod(
                id=f"intent-{intent_id}-{rank}",
                intent_id=intent_id,
                name=str(intent.get("name")),
                description=str(intent.get("description", "")).strip() or str(intent.get("name")),
                reason=", ".join(reason_parts),
                score=score,
                parameters=_build_method_parameters(intent, request.metadata or {}),
            )
        )
    return methods


@router.post("/suggest", response_model=CopilotSuggestResponse)
async def copilot_suggest(request: CopilotSuggestRequest) -> CopilotSuggestResponse:
    q = request.query.lower()
    suggestions: List[CopilotSuggestion] = []

    def add(name: str, description: str, reason: str, score: float, autocomplete: Optional[Dict[str, Any]] = None):
        suggestions.append(CopilotSuggestion(
            name=name,
            description=description,
            reason=reason,
            score=score,
            autocomplete=autocomplete or {}
        ))

    # Heuristic suggestions based on detected intent
    # Apply coarse filters: if domain/function/risk are provided, only include
    # suggestions whose implied function/domain matches. (We only have a few
    # buckets here; keep it simple.)

    def allow(function_hint: Optional[str] = None, domain_hint: Optional[str] = None) -> bool:
        if request.function and function_hint and request.function != function_hint:
            return False
        if request.domain and domain_hint and request.domain != domain_hint:
            return False
        return True
    if re.search(r"\bglm\b|general\s+linear\s+model|z-?map", q) and allow(function_hint="glm", domain_hint="fmri"):
        add(
            name="hrf_model",
            description="Hemodynamic response function model",
            reason="GLM analysis typically requires HRF specification",
            score=2.6,
            autocomplete={"hrf_model": "spm"}
        )
        add(
            name="smoothing_fwhm",
            description="Spatial smoothing kernel (FWHM in mm)",
            reason="Common pre-statistics denoising for fMRI",
            score=2.2,
            autocomplete={"smoothing_fwhm": 6}
        )
        add(
            name="threshold",
            description="Voxel-wise statistical threshold",
            reason="Control false positives in statistical maps",
            score=2.0,
            autocomplete={"threshold": 0.001}
        )

    if re.search(r"connectivity|correlation|resting[-\s]?state", q) and allow(function_hint="connectivity", domain_hint="fmri"):
        add(
            name="parcellation",
            description="Atlas for region definition",
            reason="Connectivity requires ROIs; choose an atlas",
            score=2.4,
            autocomplete={"parcellation": "Schaefer2018_200"}
        )
        add(
            name="bandpass_filter",
            description="Temporal filtering band (Hz)",
            reason="Denoising for resting-state connectivity",
            score=2.0,
            autocomplete={"bandpass_filter": [0.01, 0.1]}
        )
        add(
            name="correlation_threshold",
            description="Edge threshold for graph construction",
            reason="Filter weak or noisy connections",
            score=1.8,
            autocomplete={"correlation_threshold": 0.3}
        )

    # Generic fallbacks
    if not suggestions and allow():
        add(
            name="dataset",
            description="Select a dataset for analysis",
            reason="Most analyses require data selection",
            score=1.5,
            autocomplete={"dataset_id": request.metadata.get("dataset_id") or "motor_task_sample"}
        )
        add(
            name="pipeline",
            description="Choose or infer an analysis pipeline",
            reason="Disambiguate desired analysis flow",
            score=1.4,
            autocomplete={"pipeline": request.metadata.get("pipeline") or "auto"}
        )

    methods = _build_methods(request)
    return CopilotSuggestResponse(
        suggestions=suggestions[: request.k],
        methods=methods,
    )


@router.post("/autocomplete", response_model=CopilotAutocompleteResponse)
async def copilot_autocomplete(
    request: CopilotAutocompleteRequest,
) -> CopilotAutocompleteResponse:
    assistant = _get_copilot_assistant()
    completed = assistant.autocomplete_parameters(
        request.tool,
        request.params or {},
        request.metadata or {},
    )
    return CopilotAutocompleteResponse(tool=request.tool, completed=completed)


@router.post("/learn", response_model=CopilotLearnResponse)
async def copilot_learn(request: CopilotLearnRequest) -> CopilotLearnResponse:
    assistant = _get_copilot_assistant()
    assistant.learn_selection(request.tool, request.params or {})
    return CopilotLearnResponse(tool=request.tool)
