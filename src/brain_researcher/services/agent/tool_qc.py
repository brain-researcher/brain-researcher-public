"""Execution-layer semantic QC helpers."""

from __future__ import annotations

import logging
import mimetypes
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from brain_researcher.services.tools.spec import (
    ToolQCJudgeConfig,
    ToolQCPrecheckConfig,
    ToolQCRenderContract,
    ToolQCSpec,
    normalize_qc_spec,
)

logger = logging.getLogger(__name__)

DEFAULT_QC_PRIMARY_MODEL = "gemini-2.5-flash-lite"
DEFAULT_QC_ESCALATION_MODEL = "gemini-2.5-flash"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class ToolQCJudgeResult(BaseModel):
    """Structured semantic QC verdict returned by the vision judge."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    passed: bool = Field(description="Whether the QC image passes review")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    uncertain: bool = False
    summary: str = Field(default="")
    failure_modes: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("failure_modes", "failure_codes"),
    )
    evidence: list[str] = Field(default_factory=list)
    judge_model: str | None = None


ToolQCVerdict = ToolQCJudgeResult
QCSpec = ToolQCSpec


class QCFailureCode(str, Enum):
    UNDER_STRIP = "under_strip"
    OVER_STRIP = "over_strip"
    MISREGISTRATION = "misregistration"
    MASK_MISSING = "mask_missing"
    OUTPUT_MISSING = "output_missing"
    UNCERTAIN = "uncertain"
    PASS = "pass"


class ToolQCAction(str, Enum):
    ACCEPT = "accept"
    RETRY = "retry"
    FALLBACK = "fallback"
    ESCALATE_JUDGE = "escalate_judge"
    FAIL = "fail"


class QCImageAsset(BaseModel):
    path: str
    source_key: str | None = None
    kind: str = "image"


class QCJudgeRequest(BaseModel):
    model: str
    checklist: list[str] = Field(default_factory=list)
    allowed_failure_modes: list[str] = Field(default_factory=list)
    instruction: str | None = None
    attempt: int = 0
    tool_name: str | None = None
    step_id: str | None = None
    image_paths: list[str] = Field(default_factory=list)
    payload_summary: dict[str, Any] = Field(default_factory=dict)


@dataclass
class ToolQCRetryDecision:
    adjusted_params: dict[str, Any] | None = None
    fallback_tool: str | None = None
    reason: str | None = None


@dataclass
class ToolQCEvaluation:
    status: str
    artifact_paths: list[str] = field(default_factory=list)
    judge_result: ToolQCJudgeResult | None = None
    selected_model: str | None = None
    retry_decision: ToolQCRetryDecision | None = None
    skip_reason: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "artifact_paths": list(self.artifact_paths),
        }
        if self.selected_model:
            payload["selected_model"] = self.selected_model
        if self.skip_reason:
            payload["skip_reason"] = self.skip_reason
        if self.judge_result is not None:
            payload["judge_result"] = self.judge_result.model_dump()
        if self.retry_decision is not None:
            payload["retry_decision"] = {
                "adjusted_params": self.retry_decision.adjusted_params,
                "fallback_tool": self.retry_decision.fallback_tool,
                "reason": self.retry_decision.reason,
            }
        return payload


@dataclass
class ToolQCDecision:
    action: ToolQCAction
    reason: str
    failure_codes: list[str] = field(default_factory=list)
    parameter_patch: dict[str, Any] = field(default_factory=dict)
    fallback_tool: str | None = None
    next_judge_model: str | None = None
    attempt: int = 0
    exhausted: bool = False
    verdict: ToolQCVerdict | None = None
    image_paths: list[QCImageAsset] = field(default_factory=list)


class GeminiToolQCJudge:
    """Minimal Gemini-based image judge for semantic QC."""

    def __init__(self) -> None:
        self._client = None
        self._types = None

    def _load_client(self):
        if self._client is not None and self._types is not None:
            return self._client, self._types
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("missing_google_api_key")
        try:
            from google import genai
            from google.genai import types
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(f"google_genai_unavailable:{exc}") from exc
        self._client = genai.Client(api_key=api_key)
        self._types = types
        return self._client, self._types

    def judge(
        self,
        *,
        model: str,
        tool_name: str,
        qc_spec: ToolQCSpec,
        image_paths: Sequence[str],
        attempt_index: int,
    ) -> ToolQCJudgeResult:
        client, types = self._load_client()
        contents: list[Any] = [
            self._build_prompt(
                tool_name=tool_name,
                qc_spec=qc_spec,
                attempt_index=attempt_index,
            )
        ]
        for image_path in image_paths:
            mime_type = mimetypes.guess_type(image_path)[0] or "image/png"
            contents.append(
                types.Part.from_bytes(
                    data=Path(image_path).read_bytes(),
                    mime_type=mime_type,
                )
            )
        config = types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=1024,
            response_mime_type="application/json",
            response_json_schema=ToolQCJudgeResult.model_json_schema(),
        )
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        response_text = getattr(response, "text", None)
        if not response_text:
            raise RuntimeError("empty_qc_judge_response")
        parsed = ToolQCJudgeResult.model_validate_json(response_text)
        parsed.judge_model = model
        allowed_modes = set(qc_spec.failure_modes or [])
        parsed.failure_modes = [
            str(mode).strip()
            for mode in parsed.failure_modes
            if str(mode).strip()
            and (not allowed_modes or str(mode).strip() in allowed_modes)
        ]
        if parsed.passed:
            parsed.failure_modes = []
        elif (
            parsed.uncertain
            and not parsed.failure_modes
            and QCFailureCode.UNCERTAIN.value in allowed_modes
        ):
            parsed.failure_modes = [QCFailureCode.UNCERTAIN.value]
        return parsed

    @staticmethod
    def _build_prompt(
        *,
        tool_name: str,
        qc_spec: ToolQCSpec,
        attempt_index: int,
    ) -> str:
        checklist = "\n".join(f"- {item}" for item in (qc_spec.checklist or []))
        failure_modes = "\n".join(f"- {item}" for item in (qc_spec.failure_modes or []))
        return (
            "You are a strict neuroimaging quality-control judge.\n"
            f"Tool: {tool_name}\n"
            f"Attempt index: {attempt_index}\n"
            "Review the provided QC PNGs and return only JSON matching the schema.\n"
            "Use only the allowed failure modes.\n"
            "Mark passed=true only when the image clearly satisfies the checklist.\n\n"
            f"Checklist:\n{checklist or '- No checklist provided'}\n\n"
            f"Allowed failure modes:\n{failure_modes or '- none'}\n"
        )


def _merge_unique(base: Sequence[str], extra: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for item in list(base) + list(extra):
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


def _merge_judge_config(
    base: ToolQCJudgeConfig | None,
    override: ToolQCJudgeConfig | None,
) -> ToolQCJudgeConfig | None:
    if base is None:
        return override
    if override is None:
        return base
    merged = base.model_dump()
    override_keys = set(getattr(override, "model_fields_set", set())) or set(
        override.model_dump(exclude_defaults=True).keys()
    )
    override_data = override.model_dump()
    for key in override_keys:
        merged[key] = override_data.get(key)
    return ToolQCJudgeConfig.model_validate(merged)


def _merge_render_contract(
    base: ToolQCRenderContract | None,
    override: ToolQCRenderContract | None,
) -> ToolQCRenderContract | None:
    if base is None:
        return override
    if override is None:
        return base
    merged = base.model_dump()
    override_keys = set(getattr(override, "model_fields_set", set())) or set(
        override.model_dump(exclude_defaults=True).keys()
    )
    override_data = override.model_dump()
    for key in override_keys:
        merged[key] = override_data.get(key)
    return ToolQCRenderContract.model_validate(merged)


def _merge_prechecks(
    base: ToolQCPrecheckConfig | None,
    override: ToolQCPrecheckConfig | None,
) -> ToolQCPrecheckConfig | None:
    if base is None:
        return override
    if override is None:
        return base
    merged = base.model_dump()
    override_data = override.model_dump()
    merged["required_outputs"] = {
        **merged.get("required_outputs", {}),
        **override_data.get("required_outputs", {}),
    }
    merged["required_artifacts"] = {
        **merged.get("required_artifacts", {}),
        **override_data.get("required_artifacts", {}),
    }
    return ToolQCPrecheckConfig.model_validate(merged)


def merge_qc_spec(base: ToolQCSpec, override: ToolQCSpec) -> ToolQCSpec:
    merged = base.model_dump()
    override_keys = set(getattr(override, "model_fields_set", set())) or set(
        override.model_dump(exclude_defaults=True).keys()
    )
    override_data = override.model_dump()
    for key in override_keys:
        value = override_data.get(key)
        if key in {"artifact_output_keys", "checklist", "failure_modes"}:
            merged[key] = _merge_unique(merged.get(key, []), value or [])
        elif key == "retry_rules" and value:
            merged[key] = [*merged.get(key, []), *value]
        elif key == "judge":
            merged[key] = _merge_judge_config(base.judge, override.judge)
        elif key == "render_contract":
            merged[key] = _merge_render_contract(
                base.render_contract, override.render_contract
            )
        elif key == "prechecks":
            merged[key] = _merge_prechecks(base.prechecks, override.prechecks)
        else:
            merged[key] = value
    return ToolQCSpec.model_validate(merged)


def resolve_qc_spec(
    tool_spec: Any = None, step_metadata: Any = None
) -> ToolQCSpec | None:
    tool_candidate = None
    if isinstance(tool_spec, Mapping):
        tool_candidate = tool_spec.get("qc_spec")
    else:
        tool_candidate = getattr(tool_spec, "qc_spec", None)
        if tool_candidate is None:
            meta = getattr(tool_spec, "metadata", None)
            if isinstance(meta, Mapping):
                tool_candidate = meta.get("qc_spec")

    step_candidate = None
    if isinstance(step_metadata, Mapping):
        step_candidate = (
            step_metadata.get("qc_spec")
            or step_metadata.get("qc")
            or step_metadata.get("qc_overrides")
        )

    base = normalize_qc_spec(tool_candidate)
    override = normalize_qc_spec(step_candidate)
    if base is None:
        return override
    if override is None:
        return base
    return merge_qc_spec(base, override)


def _flatten_payload_nodes(payload: Any) -> Iterable[tuple[str | None, Any]]:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            yield key, value
            yield from _flatten_payload_nodes(value)
    elif isinstance(payload, list | tuple | set):
        for item in payload:
            yield None, item
            yield from _flatten_payload_nodes(item)


def collect_qc_image_paths(
    payload: Any,
    *,
    qc_spec: ToolQCSpec | None = None,
    require_exists: bool = False,
) -> list[QCImageAsset]:
    explicit_keys = set(qc_spec.artifact_output_keys if qc_spec else [])
    recognized_keys = explicit_keys.union(
        {
            "qc_png",
            "qc_pngs",
            "qc_image",
            "qc_images",
            "preview_images",
            "image",
            "images",
            "figure",
            "figures",
            "artifact",
            "artifacts",
            "overlay",
        }
    )
    assets: list[QCImageAsset] = []
    seen: set[str] = set()

    def add_path(path: Any, source_key: str | None) -> None:
        if not isinstance(path, str):
            return
        candidate = Path(path).expanduser()
        if require_exists and not candidate.exists():
            return
        suffix = candidate.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
            return
        text = str(candidate)
        if text in seen:
            return
        seen.add(text)
        assets.append(QCImageAsset(path=text, source_key=source_key))

    for key, value in _flatten_payload_nodes(payload):
        if isinstance(value, str):
            if key in recognized_keys:
                add_path(value, key)
        elif isinstance(value, Mapping):
            if key not in recognized_keys:
                continue
            for nested_key in ("path", "file", "filepath", "image", "figure", "png"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, str):
                    add_path(nested_value, key or nested_key)
        elif isinstance(value, list | tuple | set) and key in recognized_keys:
            for item in value:
                if isinstance(item, Mapping):
                    for nested_key in (
                        "path",
                        "file",
                        "filepath",
                        "image",
                        "figure",
                        "png",
                    ):
                        nested_value = item.get(nested_key)
                        if isinstance(nested_value, str):
                            add_path(nested_value, key or nested_key)
                else:
                    add_path(item, key)

    return assets


def _value_is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return False
        candidate = Path(text).expanduser()
        if candidate.exists():
            return True
        return not any(sep in text for sep in (os.sep, "/", "\\"))
    if isinstance(value, Mapping):
        return any(_value_is_present(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(_value_is_present(item) for item in value)
    return True


def _collect_output_values(payload: Any, target_key: str) -> list[Any]:
    matches: list[Any] = []
    if isinstance(payload, Mapping):
        outputs = payload.get("outputs")
        if isinstance(outputs, Mapping) and target_key in outputs:
            matches.append(outputs.get(target_key))
        for value in payload.values():
            matches.extend(_collect_output_values(value, target_key))
    elif isinstance(payload, Sequence) and not isinstance(
        payload, str | bytes | bytearray
    ):
        for item in payload:
            matches.extend(_collect_output_values(item, target_key))
    return matches


def _collect_artifact_values(payload: Any, target_key: str) -> list[Any]:
    matches: list[Any] = []
    if isinstance(payload, Mapping):
        if target_key in payload:
            matches.append(payload.get(target_key))
        for value in payload.values():
            matches.extend(_collect_artifact_values(value, target_key))
    elif isinstance(payload, Sequence) and not isinstance(
        payload, str | bytes | bytearray
    ):
        for item in payload:
            matches.extend(_collect_artifact_values(item, target_key))
    return matches


def _run_deterministic_prechecks(
    *,
    payload: Mapping[str, Any],
    qc_spec: ToolQCSpec,
) -> ToolQCJudgeResult | None:
    prechecks = qc_spec.prechecks
    if prechecks is None:
        return None

    failure_modes: list[str] = []
    evidence: list[str] = []

    for output_key, failure_mode in prechecks.required_outputs.items():
        values = _collect_output_values(payload, output_key)
        if any(_value_is_present(value) for value in values):
            continue
        normalized_mode = str(failure_mode).strip() or QCFailureCode.OUTPUT_MISSING.value
        failure_modes.append(normalized_mode)
        evidence.append(f"missing required output:{output_key}")

    for artifact_key, failure_mode in prechecks.required_artifacts.items():
        values = _collect_artifact_values(payload, artifact_key)
        if any(_value_is_present(value) for value in values):
            continue
        normalized_mode = str(failure_mode).strip() or QCFailureCode.OUTPUT_MISSING.value
        failure_modes.append(normalized_mode)
        evidence.append(f"missing required artifact:{artifact_key}")

    if not failure_modes:
        return None

    deduped_modes = _merge_unique([], failure_modes)
    return ToolQCJudgeResult(
        passed=False,
        confidence=1.0,
        uncertain=False,
        summary="deterministic precheck failed",
        failure_modes=deduped_modes,
        evidence=evidence,
        judge_model="deterministic_precheck",
    )


def _model_routing(
    qc_spec: ToolQCSpec,
    context: Mapping[str, Any] | None,
) -> tuple[str, str, float]:
    judge = qc_spec.judge or ToolQCJudgeConfig()
    context = context or {}

    cheap_model = (
        str(context.get("semantic_qc_cheap_model") or "").strip()
        or os.getenv("BR_TOOL_QC_CHEAP_MODEL")
        or judge.cheap_model
        or DEFAULT_QC_PRIMARY_MODEL
    )
    uncertain_model = (
        str(context.get("semantic_qc_uncertain_model") or "").strip()
        or os.getenv("BR_TOOL_QC_UNCERTAIN_MODEL")
        or judge.uncertain_model
        or DEFAULT_QC_ESCALATION_MODEL
    )
    threshold_raw = (
        context.get("semantic_qc_confidence_threshold")
        or os.getenv("BR_TOOL_QC_CONFIDENCE_THRESHOLD")
        or judge.uncertainty_confidence_threshold
    )
    try:
        threshold = float(threshold_raw)
    except Exception:
        threshold = judge.uncertainty_confidence_threshold
    return cheap_model, uncertain_model, threshold


def _coerce_verdict(raw_verdict: Any, *, model: str) -> ToolQCJudgeResult:
    verdict = (
        raw_verdict
        if isinstance(raw_verdict, ToolQCJudgeResult)
        else ToolQCJudgeResult.model_validate(raw_verdict)
    )
    verdict.judge_model = verdict.judge_model or model
    verdict.failure_modes = [
        str(mode).strip() for mode in verdict.failure_modes if str(mode).strip()
    ]
    if verdict.passed:
        verdict.failure_modes = []
    return verdict


def _build_qc_request(
    *,
    tool_name: str,
    step_id: str | None,
    qc_spec: ToolQCSpec,
    image_paths: Sequence[str],
    payload_summary: Mapping[str, Any],
    model: str,
    attempt_index: int,
) -> QCJudgeRequest:
    return QCJudgeRequest(
        model=model,
        checklist=list(qc_spec.checklist),
        allowed_failure_modes=list(qc_spec.failure_modes),
        instruction=None,
        attempt=attempt_index,
        tool_name=tool_name,
        step_id=step_id,
        image_paths=list(image_paths),
        payload_summary=dict(payload_summary),
    )


def _run_judge(
    *,
    tool_name: str,
    qc_spec: ToolQCSpec,
    image_paths: Sequence[str],
    attempt_index: int,
    model: str,
    step_id: str | None,
    payload_summary: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    judge: Any | None,
) -> ToolQCJudgeResult:
    request = _build_qc_request(
        tool_name=tool_name,
        step_id=step_id,
        qc_spec=qc_spec,
        image_paths=image_paths,
        payload_summary=payload_summary,
        model=model,
        attempt_index=attempt_index,
    )

    judge_fn = None
    if isinstance(context, Mapping):
        judge_fn = context.get("qc_judge_fn") or context.get("judge_fn")

    if callable(judge_fn):
        return _coerce_verdict(judge_fn(request), model=model)

    judge_backend = judge or GeminiToolQCJudge()
    if hasattr(judge_backend, "judge"):
        return _coerce_verdict(
            judge_backend.judge(
                model=model,
                tool_name=tool_name,
                qc_spec=qc_spec,
                image_paths=image_paths,
                attempt_index=attempt_index,
            ),
            model=model,
        )
    if callable(judge_backend):
        return _coerce_verdict(judge_backend(request), model=model)
    raise RuntimeError("invalid_qc_judge_backend")


def _apply_retry_rules(
    *,
    qc_spec: ToolQCSpec,
    parameters: Mapping[str, Any],
    failure_modes: Sequence[str],
    attempt_index: int,
) -> ToolQCRetryDecision | None:
    try:
        from brain_researcher.services.tools.catalog_loader import (
            resolve_primary_runtime_tool_id,
        )
    except Exception:
        resolve_primary_runtime_tool_id = None  # type: ignore

    active_modes = {str(mode).strip() for mode in failure_modes if str(mode).strip()}
    if not active_modes:
        return None
    for rule in qc_spec.retry_rules:
        if rule.min_attempt > attempt_index:
            continue
        if rule.max_attempt is not None and attempt_index > rule.max_attempt:
            continue
        if rule.match_any_failure_modes and not (
            active_modes & {str(mode).strip() for mode in rule.match_any_failure_modes}
        ):
            continue
        adjusted_params = None
        if rule.param_updates:
            adjusted_params = dict(parameters)
            adjusted_params.update(rule.param_updates)
        fallback_tool = str(rule.fallback_tool or "").strip() or None
        if fallback_tool and resolve_primary_runtime_tool_id is not None:
            fallback_tool = (
                resolve_primary_runtime_tool_id(fallback_tool) or fallback_tool
            )
        return ToolQCRetryDecision(
            adjusted_params=adjusted_params,
            fallback_tool=fallback_tool,
            reason=rule.notes or ",".join(sorted(active_modes)),
        )
    return None


def evaluate_semantic_qc(
    *,
    tool_name: str,
    parameters: Mapping[str, Any],
    payload: Mapping[str, Any],
    qc_spec: ToolQCSpec | None,
    attempt_index: int,
    context: Mapping[str, Any] | None = None,
    judge: Any | None = None,
) -> ToolQCEvaluation:
    """Evaluate semantic QC for a successful step output."""

    if qc_spec is None or not qc_spec.enabled:
        return ToolQCEvaluation(status="skip", skip_reason="no_qc_spec")

    context_dict = dict(context or {})
    qc_enabled = context_dict.get("semantic_qc_enabled")
    if qc_enabled is None:
        qc_enabled = _env_flag("BR_TOOL_QC_ENABLED", False)
    if not qc_enabled:
        return ToolQCEvaluation(status="skip", skip_reason="disabled")

    precheck_result = _run_deterministic_prechecks(payload=payload, qc_spec=qc_spec)
    if precheck_result is not None:
        decision = _apply_retry_rules(
            qc_spec=qc_spec,
            parameters=parameters,
            failure_modes=precheck_result.failure_modes,
            attempt_index=attempt_index,
        )
        return ToolQCEvaluation(
            status="fail",
            judge_result=precheck_result,
            selected_model=precheck_result.judge_model,
            retry_decision=decision,
        )

    image_assets = collect_qc_image_paths(payload, qc_spec=qc_spec, require_exists=True)
    artifact_paths = [asset.path for asset in image_assets]
    if not artifact_paths:
        return ToolQCEvaluation(status="skip", skip_reason="no_qc_artifacts")

    cheap_model, uncertain_model, threshold = _model_routing(qc_spec, context_dict)
    step_id = None
    if isinstance(context_dict.get("step_metadata"), Mapping):
        step_id = context_dict["step_metadata"].get("step_id")
    elif isinstance(context_dict.get("metadata"), Mapping):
        step_id = context_dict["metadata"].get("step_id")
    if not step_id:
        step_id = context_dict.get("step_id")

    payload_summary = {
        "status": payload.get("status"),
        "output_keys": sorted(payload.get("outputs", {}).keys())
        if isinstance(payload.get("outputs"), Mapping)
        else [],
    }

    try:
        result = _run_judge(
            tool_name=tool_name,
            qc_spec=qc_spec,
            image_paths=artifact_paths,
            attempt_index=attempt_index,
            model=cheap_model,
            step_id=step_id,
            payload_summary=payload_summary,
            context=context_dict,
            judge=judge,
        )
        selected_model = cheap_model
        if (
            uncertain_model
            and uncertain_model != cheap_model
            and (result.uncertain or result.confidence < threshold)
        ):
            result = _run_judge(
                tool_name=tool_name,
                qc_spec=qc_spec,
                image_paths=artifact_paths,
                attempt_index=attempt_index,
                model=uncertain_model,
                step_id=step_id,
                payload_summary=payload_summary,
                context=context_dict,
                judge=judge,
            )
            selected_model = uncertain_model
    except Exception as exc:
        logger.warning("Semantic QC skipped for %s: %s", tool_name, exc)
        return ToolQCEvaluation(
            status="skip",
            artifact_paths=artifact_paths,
            skip_reason=str(exc),
        )

    if result.passed:
        return ToolQCEvaluation(
            status="pass",
            artifact_paths=artifact_paths,
            judge_result=result,
            selected_model=selected_model,
        )

    decision = _apply_retry_rules(
        qc_spec=qc_spec,
        parameters=parameters,
        failure_modes=result.failure_modes,
        attempt_index=attempt_index,
    )
    return ToolQCEvaluation(
        status="fail",
        artifact_paths=artifact_paths,
        judge_result=result,
        selected_model=selected_model,
        retry_decision=decision,
    )


def evaluate_qc_for_execution(
    tool_name: str,
    current_params: Mapping[str, Any] | None,
    tool_spec: Any,
    step_metadata: Any,
    exec_result: Any,
    context: Mapping[str, Any] | None,
    attempt_index: int,
) -> ToolQCDecision:
    qc_spec = resolve_qc_spec(tool_spec, step_metadata)
    if qc_spec is None or not qc_spec.enabled:
        raise ValueError("QC is disabled or no QC spec is available")

    payload = (
        exec_result.get("result", exec_result)
        if isinstance(exec_result, Mapping)
        else exec_result
    )
    image_assets = collect_qc_image_paths(payload, qc_spec=qc_spec, require_exists=True)
    evaluation = evaluate_semantic_qc(
        tool_name=tool_name,
        parameters=dict(current_params or {}),
        payload=payload if isinstance(payload, Mapping) else {},
        qc_spec=qc_spec,
        attempt_index=attempt_index,
        context={**dict(context or {}), "semantic_qc_enabled": True},
    )

    failure_codes = (
        list(evaluation.judge_result.failure_modes) if evaluation.judge_result else []
    )
    next_model = None
    if evaluation.selected_model:
        _, uncertain_model, threshold = _model_routing(qc_spec, context)
        judge_result = evaluation.judge_result
        if (
            judge_result is not None
            and evaluation.selected_model != uncertain_model
            and uncertain_model
            and (judge_result.uncertain or judge_result.confidence < threshold)
        ):
            next_model = uncertain_model

    if evaluation.status == "pass":
        return ToolQCDecision(
            action=ToolQCAction.ACCEPT,
            reason="qc_pass",
            failure_codes=failure_codes,
            next_judge_model=next_model,
            attempt=attempt_index,
            verdict=evaluation.judge_result,
            image_paths=image_assets,
        )

    if (
        evaluation.status == "fail"
        and evaluation.retry_decision is not None
        and evaluation.retry_decision.adjusted_params is not None
    ):
        return ToolQCDecision(
            action=ToolQCAction.RETRY,
            reason=evaluation.retry_decision.reason or "qc_retry",
            failure_codes=failure_codes,
            parameter_patch=evaluation.retry_decision.adjusted_params,
            next_judge_model=next_model,
            attempt=attempt_index,
            verdict=evaluation.judge_result,
            image_paths=image_assets,
        )

    if (
        evaluation.status == "fail"
        and evaluation.retry_decision is not None
        and evaluation.retry_decision.fallback_tool
    ):
        return ToolQCDecision(
            action=ToolQCAction.FALLBACK,
            reason=evaluation.retry_decision.reason or "qc_fallback",
            failure_codes=failure_codes,
            fallback_tool=evaluation.retry_decision.fallback_tool,
            next_judge_model=next_model,
            attempt=attempt_index,
            verdict=evaluation.judge_result,
            image_paths=image_assets,
        )

    return ToolQCDecision(
        action=ToolQCAction.FAIL,
        reason=f"qc_failure:{','.join(failure_codes) or 'unknown'}",
        failure_codes=failure_codes,
        next_judge_model=next_model,
        attempt=attempt_index,
        exhausted=True,
        verdict=evaluation.judge_result,
        image_paths=image_assets,
    )


__all__ = [
    "DEFAULT_QC_ESCALATION_MODEL",
    "DEFAULT_QC_PRIMARY_MODEL",
    "QCFailureCode",
    "QCImageAsset",
    "QCJudgeRequest",
    "QCSpec",
    "GeminiToolQCJudge",
    "ToolQCAction",
    "ToolQCDecision",
    "ToolQCEvaluation",
    "ToolQCJudgeResult",
    "ToolQCRetryDecision",
    "ToolQCVerdict",
    "collect_qc_image_paths",
    "evaluate_qc_for_execution",
    "evaluate_semantic_qc",
    "merge_qc_spec",
    "resolve_qc_spec",
]
