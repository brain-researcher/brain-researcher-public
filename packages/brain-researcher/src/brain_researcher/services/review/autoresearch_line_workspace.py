"""Helpers for generic line-based autoresearch workspaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts.autoresearch_line import (
    AutoresearchLineStateV1,
    AutoresearchWorkspaceLayoutV1,
    LineBudgetEnvelopeV1,
    LineCloseoutV1,
    LineDecisionEventV1,
    LineLatestSummaryV1,
    LinePendingDirectiveV1,
    LineTransitionRulesV1,
)

_REQUIRED_WORKSPACE_FILES = (
    "line_state.json",
    "experiments.jsonl",
    "loop_body_prompt.md",
    "outputs",
    "runner_logs",
)
_OPTIONAL_WORKSPACE_FILES = (
    "experiments.bootstrap.jsonl",
    "predict.py",
    "run.py",
)


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def infer_line_type_from_workspace(workspace: str | Path) -> str:
    """Infer a generic line_type from a workspace directory name."""

    name = Path(workspace).name.lower()
    if "blind_replication" in name:
        return "blind_replication"
    if "validation" in name:
        return "validation"
    if "sensitivity" in name:
        return "sensitivity"
    if "closeout" in name:
        return "closeout"
    if "data_scaling" in name:
        return "data_scaling"
    if "representation_scaling" in name:
        return "representation_scaling"
    if "model_scaling" in name:
        return "model_scaling"
    if "generalization" in name:
        return "generalization"
    if "foundation_transfer" in name:
        return "foundation_transfer"
    return "exploration"


def resolve_autoresearch_workspace_layout(
    workspace: str | Path,
) -> AutoresearchWorkspaceLayoutV1:
    """Resolve the stable file layout for one autoresearch workspace."""

    root = Path(workspace).resolve()
    line_state_path = root / "line_state.json"
    experiments_path = root / "experiments.jsonl"
    bootstrap_path = root / "experiments.bootstrap.jsonl"
    prompt_path = root / "loop_body_prompt.md"
    outputs_dir = root / "outputs"
    runner_logs_dir = root / "runner_logs"
    final_report_path = outputs_dir / "final_report.md"
    reference_dirs = (
        sorted(
            path.resolve().as_posix()
            for path in root.iterdir()
            if path.is_dir() and path.name.startswith("reference")
        )
        if root.exists()
        else []
    )
    entrypoint_paths = [
        str(path.resolve())
        for path in (root / "run.py", root / "predict.py")
        if path.exists()
    ]
    required_paths = [
        str((root / name).resolve()) for name in _REQUIRED_WORKSPACE_FILES
    ]
    optional_paths = [
        str((root / name).resolve()) for name in _OPTIONAL_WORKSPACE_FILES
    ]
    existing_paths = [
        str(path.resolve())
        for path in (
            line_state_path,
            experiments_path,
            bootstrap_path,
            prompt_path,
            outputs_dir,
            runner_logs_dir,
            final_report_path,
            root / "run.py",
            root / "predict.py",
        )
        if path.exists()
    ] + reference_dirs
    return AutoresearchWorkspaceLayoutV1(
        root_dir=str(root),
        line_state_path=str(line_state_path),
        experiments_path=str(experiments_path),
        bootstrap_ledger_path=str(bootstrap_path) if bootstrap_path.exists() else None,
        prompt_path=str(prompt_path),
        outputs_dir=str(outputs_dir),
        runner_logs_dir=str(runner_logs_dir),
        final_report_path=str(final_report_path),
        reference_dirs=reference_dirs,
        entrypoint_paths=entrypoint_paths,
        required_paths=required_paths,
        optional_paths=optional_paths,
        existing_paths=sorted(dict.fromkeys(existing_paths)),
    )


def coerce_autoresearch_line_state(
    payload: dict[str, Any],
    *,
    workspace: str | Path | None = None,
) -> AutoresearchLineStateV1:
    """Coerce a legacy or generic line_state payload into the BR contract."""

    known_keys = {
        "schema_version",
        "line_id",
        "line_type",
        "status",
        "created_utc",
        "updated_utc",
        "workspace",
        "parent_workspace",
        "reference_workspace",
        "budget_envelope",
        "runner_turns_completed",
        "budget_extensions_used",
        "pending_directive",
        "transition_rules",
        "spawn_history",
        "decision_trace",
        "consecutive_no_growth",
        "loaded_modules",
        "forbidden_modules",
        "training_backend",
        "success_criterion",
        "last_completed_runner_turn",
        "last_completed_utc",
        "last_latest_summary",
        "closeout",
    }
    budget = payload.get("budget_envelope")
    pending_directive = payload.get("pending_directive")
    transition_rules = payload.get("transition_rules")
    latest_summary = payload.get("last_latest_summary")
    closeout = payload.get("closeout")
    decision_trace = payload.get("decision_trace")
    state = AutoresearchLineStateV1(
        source_schema_version=str(payload.get("schema_version") or "") or None,
        line_id=str(payload.get("line_id") or "") or None,
        line_type=(str(payload.get("line_type") or "").strip() or None),
        status=str(payload.get("status") or "draft"),
        created_utc=str(payload.get("created_utc") or "") or None,
        updated_utc=str(payload.get("updated_utc") or "") or None,
        workspace=(
            str(payload.get("workspace") or "").strip()
            or (str(Path(workspace).resolve()) if workspace is not None else None)
        ),
        parent_workspace=str(payload.get("parent_workspace") or "") or None,
        reference_workspace=str(payload.get("reference_workspace") or "") or None,
        budget_envelope=(
            LineBudgetEnvelopeV1(**budget) if isinstance(budget, dict) else None
        ),
        runner_turns_completed=(
            int(payload["runner_turns_completed"])
            if isinstance(payload.get("runner_turns_completed"), int | float)
            else None
        ),
        budget_extensions_used=(
            int(payload["budget_extensions_used"])
            if isinstance(payload.get("budget_extensions_used"), int | float)
            else None
        ),
        pending_directive=(
            LinePendingDirectiveV1(**pending_directive)
            if isinstance(pending_directive, dict)
            else None
        ),
        transition_rules=(
            LineTransitionRulesV1(**transition_rules)
            if isinstance(transition_rules, dict)
            else None
        ),
        spawn_history=(
            [
                item
                for item in payload.get("spawn_history", [])
                if isinstance(item, dict)
            ]
            if isinstance(payload.get("spawn_history"), list)
            else []
        ),
        decision_trace=(
            [
                LineDecisionEventV1(**item)
                for item in decision_trace
                if isinstance(item, dict) and item.get("event")
            ]
            if isinstance(decision_trace, list)
            else []
        ),
        consecutive_no_growth=(
            int(payload["consecutive_no_growth"])
            if isinstance(payload.get("consecutive_no_growth"), int | float)
            else None
        ),
        loaded_modules=_normalize_str_list(payload.get("loaded_modules")),
        forbidden_modules=_normalize_str_list(payload.get("forbidden_modules")),
        training_backend=str(payload.get("training_backend") or "") or None,
        success_criterion=str(payload.get("success_criterion") or "") or None,
        last_completed_runner_turn=(
            int(payload["last_completed_runner_turn"])
            if isinstance(payload.get("last_completed_runner_turn"), int | float)
            else None
        ),
        last_completed_utc=str(payload.get("last_completed_utc") or "") or None,
        last_latest_summary=(
            LineLatestSummaryV1(**latest_summary)
            if isinstance(latest_summary, dict)
            else None
        ),
        closeout=(LineCloseoutV1(**closeout) if isinstance(closeout, dict) else None),
        extra={key: value for key, value in payload.items() if key not in known_keys},
    )
    if state.line_type is None and workspace is not None:
        state.line_type = infer_line_type_from_workspace(workspace)
    return state


def load_autoresearch_line_state(
    workspace_or_state_path: str | Path,
) -> AutoresearchLineStateV1 | None:
    """Load one on-disk line_state.json into the generic BR contract."""

    path = Path(workspace_or_state_path)
    workspace = path if path.is_dir() else path.parent
    line_state_path = path / "line_state.json" if path.is_dir() else path
    payload = _read_json_object(line_state_path)
    if payload is None:
        return None
    return coerce_autoresearch_line_state(payload, workspace=workspace)


def write_autoresearch_line_state(
    line_state: AutoresearchLineStateV1,
    workspace_or_state_path: str | Path,
) -> Path:
    """Persist a generic line-state snapshot to disk."""

    path = Path(workspace_or_state_path)
    line_state_path = path / "line_state.json" if path.is_dir() else path
    line_state_path.parent.mkdir(parents=True, exist_ok=True)
    line_state_path.write_text(line_state.model_dump_json(indent=2), encoding="utf-8")
    return line_state_path


__all__ = [
    "coerce_autoresearch_line_state",
    "infer_line_type_from_workspace",
    "load_autoresearch_line_state",
    "resolve_autoresearch_workspace_layout",
    "write_autoresearch_line_state",
]
