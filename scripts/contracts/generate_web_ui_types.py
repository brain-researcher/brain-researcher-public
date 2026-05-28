#!/usr/bin/env python3
"""Generate TypeScript types for the web UI from Python contract models.

This keeps the web UI from hand-authoring canonical RunCard/Observation/Bundle
shapes while the platform evolves.
"""

from __future__ import annotations

import argparse
import os
import sys
import types
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin, get_type_hints

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = (
    REPO_ROOT
    / "apps"
    / "web-ui"
    / "src"
    / "types"
    / "contracts.generated.ts"
)


def _repo_imports() -> dict[str, Any]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "src"))

    os.environ.setdefault("BR_DISABLE_TOOL_RUNNER_IMPORT", "1")

    from brain_researcher.core.contracts.analysis_bundle import (
        AnalysisBundleFiles,
        AnalysisBundleV1,
        BundleFileEntry,
    )
    from brain_researcher.core.contracts.analysis_stream import (
        AnalysisCompletedEventV1,
        AnalysisCompletedPayloadV1,
        AnalysisStreamBaseEventV1,
        AnalysisStreamEventV1,
        ArtifactWrittenEventV1,
        ArtifactWrittenPayloadV1,
        ErrorEventV1,
        ErrorPayloadV1,
        JobStartedEventV1,
        JobStartedPayloadV1,
        LogLineEventV1,
        LogLinePayloadV1,
        MetricEventV1,
        MetricPayloadV1,
        ObservationAppendedEventV1,
        ObservationAppendedPayloadV1,
        StageEventV1,
        StagePayloadV1,
        ToolCallFinishedEventV1,
        ToolCallFinishedPayloadV1,
        ToolCallStartedEventV1,
        ToolCallStartedPayloadV1,
        UnknownEventPayloadV1,
        UnknownEventV1,
        WarningEventV1,
        WarningPayloadV1,
    )
    from brain_researcher.core.contracts.artifact import ArtifactV1
    from brain_researcher.core.contracts.evaluation import EvaluationV1
    from brain_researcher.core.contracts.execution_manifest import (
        ExecutionEntrypointsV1,
        ExecutionIORefV1,
        ExecutionManifestV1,
        ExecutionModeV1,
        ExecutionReproV1,
        ExecutionRuntimeV1,
        NeurodeskExecutionV1,
    )
    from brain_researcher.core.contracts.ids import IdsV1
    from brain_researcher.core.contracts.job import JobRecordV1, JobSpecV1
    from brain_researcher.core.contracts.observation import (
        ObservationFiles,
        ObservationSpecV1,
    )
    from brain_researcher.core.contracts.policy_ref import PolicyRefV1
    from brain_researcher.core.contracts.provenance import (
        ProvenanceRuntimeV1,
        ProvenanceTimestampsV1,
        ProvenanceV1,
    )
    from brain_researcher.core.contracts.run_card import RunCardV1
    from brain_researcher.core.contracts.scorecard import ScorecardV1
    from brain_researcher.core.contracts.stream_event import StreamEventV1
    from brain_researcher.core.contracts.task_spec import TaskSpecV1
    from brain_researcher.core.contracts.trace_event import TraceEventV1
    from brain_researcher.core.contracts.version_ref import VersionRefV1

    return {
        "IdsV1": IdsV1,
        "PolicyRefV1": PolicyRefV1,
        "VersionRefV1": VersionRefV1,
        "RunCardV1": RunCardV1,
        "TraceEventV1": TraceEventV1,
        "StreamEventV1": StreamEventV1,
        "ObservationSpecV1": ObservationSpecV1,
        "ObservationFiles": ObservationFiles,
        "AnalysisBundleV1": AnalysisBundleV1,
        "AnalysisBundleFiles": AnalysisBundleFiles,
        "BundleFileEntry": BundleFileEntry,
        "TaskSpecV1": TaskSpecV1,
        "ScorecardV1": ScorecardV1,
        "EvaluationV1": EvaluationV1,
        "ExecutionEntrypointsV1": ExecutionEntrypointsV1,
        "ExecutionIORefV1": ExecutionIORefV1,
        "ExecutionManifestV1": ExecutionManifestV1,
        "ExecutionModeV1": ExecutionModeV1,
        "ExecutionReproV1": ExecutionReproV1,
        "ExecutionRuntimeV1": ExecutionRuntimeV1,
        "NeurodeskExecutionV1": NeurodeskExecutionV1,
        "ArtifactV1": ArtifactV1,
        "JobSpecV1": JobSpecV1,
        "JobRecordV1": JobRecordV1,
        "ProvenanceTimestampsV1": ProvenanceTimestampsV1,
        "ProvenanceRuntimeV1": ProvenanceRuntimeV1,
        "ProvenanceV1": ProvenanceV1,
        "AnalysisStreamBaseEventV1": AnalysisStreamBaseEventV1,
        "JobStartedPayloadV1": JobStartedPayloadV1,
        "JobStartedEventV1": JobStartedEventV1,
        "ToolCallStartedPayloadV1": ToolCallStartedPayloadV1,
        "ToolCallStartedEventV1": ToolCallStartedEventV1,
        "ToolCallFinishedPayloadV1": ToolCallFinishedPayloadV1,
        "ToolCallFinishedEventV1": ToolCallFinishedEventV1,
        "ArtifactWrittenPayloadV1": ArtifactWrittenPayloadV1,
        "ArtifactWrittenEventV1": ArtifactWrittenEventV1,
        "LogLinePayloadV1": LogLinePayloadV1,
        "LogLineEventV1": LogLineEventV1,
        "ObservationAppendedPayloadV1": ObservationAppendedPayloadV1,
        "ObservationAppendedEventV1": ObservationAppendedEventV1,
        "StagePayloadV1": StagePayloadV1,
        "StageEventV1": StageEventV1,
        "WarningPayloadV1": WarningPayloadV1,
        "WarningEventV1": WarningEventV1,
        "MetricPayloadV1": MetricPayloadV1,
        "MetricEventV1": MetricEventV1,
        "AnalysisCompletedPayloadV1": AnalysisCompletedPayloadV1,
        "AnalysisCompletedEventV1": AnalysisCompletedEventV1,
        "ErrorPayloadV1": ErrorPayloadV1,
        "ErrorEventV1": ErrorEventV1,
        "UnknownEventPayloadV1": UnknownEventPayloadV1,
        "UnknownEventV1": UnknownEventV1,
        "AnalysisStreamEventV1": AnalysisStreamEventV1,
    }


def _strip_annotated(tp: Any) -> Any:
    if get_origin(tp) is Annotated:
        return get_args(tp)[0]
    return tp


def _ts_literal(val: Any) -> str:
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    if val is True:
        return "true"
    if val is False:
        return "false"
    if val is None:
        return "null"
    return "any"


def _ts_type(tp: Any) -> str:
    tp = _strip_annotated(tp)
    origin = get_origin(tp)
    args = get_args(tp)

    if tp is Any:
        return "any"
    if tp is str:
        return "string"
    if tp in {int, float}:
        return "number"
    if tp is bool:
        return "boolean"

    if isinstance(tp, type) and issubclass(tp, Enum):
        values = [member.value for member in tp]
        if not values:
            return "string"
        return " | ".join(_ts_literal(v) for v in values)

    # datetime serializes as ISO8601 string
    if getattr(tp, "__name__", None) == "datetime":
        return "string"

    if origin is list and args:
        return f"Array<{_ts_type(args[0])}>"
    if origin is dict and args:
        key = _ts_type(args[0])
        value = _ts_type(args[1])
        if key != "string":
            key = "string"
        return f"Record<{key}, {value}>"

    if origin is tuple and args:
        return f"[{', '.join(_ts_type(a) for a in args)}]"

    if origin is type(None):
        return "null"

    # Literal[...] => union of literal values
    if origin is Literal:
        if not args:
            return "string"
        return " | ".join(_ts_literal(a) for a in args)

    # Union / X | Y
    if origin in {Union, types.UnionType}:
        return " | ".join(_ts_type(a) for a in args)

    # Pydantic models: refer by class name
    if hasattr(tp, "__mro__") and any(b.__name__ == "BaseModel" for b in tp.__mro__):
        return tp.__name__

    return "any"


def _render_interface(name: str, model: type) -> str:
    # Use resolved annotations to avoid forward refs.
    hints = get_type_hints(model, include_extras=True)
    fields = getattr(model, "model_fields", {})

    lines: list[str] = [f"export interface {name} {{"]
    for field_name, field in fields.items():
        tp = hints.get(field_name, Any)
        # Optional if it allows None OR pydantic says not required.
        args = get_args(_strip_annotated(tp))
        allows_none = type(None) in args
        optional = allows_none or not field.is_required()
        ts_tp = _ts_type(tp)
        if allows_none:
            # Represent Optional[T] as an optional property with T type (model_dump typically omits None).
            non_none = [a for a in args if a is not type(None)]
            ts_tp = " | ".join(_ts_type(a) for a in non_none) if non_none else "any"
        suffix = "?" if optional else ""
        lines.append(f"  {field_name}{suffix}: {ts_tp}")
    lines.append("}")
    return "\n".join(lines)


def _is_pydantic_model(obj: Any) -> bool:
    return (
        isinstance(obj, type)
        and hasattr(obj, "__mro__")
        and any(b.__name__ == "BaseModel" for b in obj.__mro__)
    )


def _generate() -> str:
    models = _repo_imports()

    parts: list[str] = [
        "/* AUTO-GENERATED. DO NOT EDIT. */",
        "/* Source: brain_researcher.core.contracts (Pydantic models) */",
        "",
    ]

    for name, model in models.items():
        if _is_pydantic_model(model):
            parts.append(_render_interface(name, model))
        else:
            parts.append(f"export type {name} = {_ts_type(model)}")
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the generated web UI types are out of date.",
    )
    args = parser.parse_args(argv)

    content = _generate()
    existing = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else None
    if existing != content:
        if args.check:
            rel = OUT_PATH.relative_to(REPO_ROOT)
            print(f"Out of date: {rel}", file=sys.stderr)
            print(
                "Run: python scripts/contracts/generate_web_ui_types.py",
                file=sys.stderr,
            )
            return 1
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(content, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
