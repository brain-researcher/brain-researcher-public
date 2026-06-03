#!/usr/bin/env python3
"""Generate planner-step prediction artifacts for sequence-routing evaluation.

This is an instrumentation harness for #23B. It calls a planning surface and
extracts ordered tool IDs from returned plan steps. It does not execute an
analysis, and emitted rows are labeled as planning-only predictions.

Example:

    python scripts/eval/generate_planner_step_predictions.py \
      --labels-jsonl benchmarks/tool_routing_validation/microtooling_exact_labels.manual_curated.v2.labels.jsonl \
      --planner-surface local-agent-plan \
      --output-dir benchmarks/tool_routing_validation/planner_step_predictions/local

The output JSONL is compatible with:

    python scripts/eval/evaluate_planner_sequence_routing.py \
      --predictions-json <output>/planner_step_predictions.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DEFAULT_LABELS = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "microtooling_exact_labels.manual_curated.v2.labels.jsonl"
)
DEFAULT_HTTP_AGENT_PLAN_URL = "http://localhost:8000/agent/plan"
DEFAULT_MODE = "planner_contract"
SCHEMA_VERSION = "br.planner_step_predictions.v1"
PLANNER_SURFACES = ("local-agent-plan", "http-agent-plan")

VALID_DOMAINS = {
    "neuroimaging",
    "br_kg",
    "literature",
    "llm_service",
    "code_assistant",
    "neurogenetics",
    "clinical",
}
VALID_MODALITIES = {
    "fmri",
    "eeg",
    "meg",
    "ieeg",
    "dmri",
    "smri",
    "pet",
    "genetics",
    "multimodal",
    "optical",
    "clinical",
    "general",
    "literature",
    "data_catalog",
    "rag",
    "search",
}
MODALITY_HINTS: dict[str, tuple[str, ...]] = {
    "fmri": (
        "fmri",
        "f-mri",
        "bold",
        "resting-state",
        "resting state",
        "functional mri",
        "functional connectivity",
        "activation",
        "glm",
    ),
    "smri": (
        "smri",
        "structural mri",
        "t1w",
        "t1-weighted",
        "t1 weighted",
        "cortical thickness",
        "freesurfer",
        "morphometry",
        "vbm",
    ),
    "dmri": ("dmri", "dwi", "diffusion", "dti", "tractography"),
    "eeg": ("eeg",),
    "meg": ("meg",),
    "ieeg": ("ieeg", "intracranial eeg", "seeg", "ecog"),
    "pet": ("pet", "suvr"),
    "genetics": ("genetic", "genomics", "gwas"),
    "clinical": ("clinical", "patient", "diagnosis", "treatment"),
    "literature": ("paper", "literature", "meta-analysis", "pubmed", "arxiv"),
    "data_catalog": ("dataset", "metadata", "data dictionary", "openneuro"),
}

PlannerFn = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class PlannerCallError(RuntimeError):
    """Raised when a planning surface cannot return a plan payload."""


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append({**row, "_line_number": line_number})
    return rows


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        raw = value
    else:
        raw = re.split(r"[,;]", str(value))
    return [str(item).strip() for item in raw if str(item).strip()]


def _sequence_label(row: Mapping[str, Any]) -> list[str]:
    exact = row.get("exact_labels")
    if not isinstance(exact, Mapping):
        return []
    return _as_list(exact.get("expected_sequence_tool_ids"))


def _normalize_modality(value: str) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "bold": "fmri",
        "f-mri": "fmri",
        "structural": "smri",
        "anatomical": "smri",
        "diffusion": "dmri",
        "dwi": "dmri",
    }
    return aliases.get(text, text)


def _modalities_from_row(row: Mapping[str, Any]) -> tuple[list[str], str]:
    values: list[str] = []
    for key in (
        "modality",
        "modalities",
        "requested_modality",
        "requested_modalities",
    ):
        values.extend(_as_list(row.get(key)))
    exact = row.get("exact_labels")
    if isinstance(exact, Mapping):
        for key in (
            "modality",
            "modalities",
            "requested_modality",
            "requested_modalities",
        ):
            values.extend(_as_list(exact.get(key)))

    normalized = []
    for value in values:
        item = _normalize_modality(value)
        if item in VALID_MODALITIES and item not in normalized:
            normalized.append(item)
    if normalized:
        return normalized, "label"

    query = str(row.get("query") or "").lower()
    inferred = [
        modality
        for modality, hints in MODALITY_HINTS.items()
        if any(hint in query for hint in hints)
    ]
    inferred = [item for item in inferred if item in VALID_MODALITIES]
    if inferred:
        return sorted(set(inferred)), "query_hint"
    return ["general"], "default_general"


def _domain_from_row(row: Mapping[str, Any]) -> tuple[str, str]:
    for key in ("domain", "planner_domain"):
        value = str(row.get(key) or "").strip().lower()
        if value in VALID_DOMAINS:
            return value, key

    category = str(row.get("category") or "").strip().lower()
    query = str(row.get("query") or "").strip().lower()
    text = f"{category} {query}"
    if "knowledge graph" in text or "kg" in category.split():
        return "br_kg", "category_hint"
    if any(term in text for term in ("literature", "meta-analysis", "pubmed")):
        return "literature", "category_hint"
    if "clinical" in text:
        return "clinical", "category_hint"
    return "neuroimaging", "default_neuroimaging"


def _string_inputs(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): (
            json.dumps(item, sort_keys=True)
            if isinstance(item, dict | list)
            else str(item)
        )
        for key, item in value.items()
        if item is not None
    }


def build_plan_request(
    row: Mapping[str, Any],
    *,
    allowlist_mode: str,
    planner_request_mode: str = "catalog",
) -> dict[str, Any]:
    """Build a read-only /agent/plan request from one benchmark label row."""
    query = str(row.get("query") or row.get("task") or "").strip()
    domain, domain_source = _domain_from_row(row)
    modalities, modality_source = _modalities_from_row(row)
    payload = {
        "pipeline": str(row.get("pipeline") or query or row.get("task_id") or ""),
        "query": query,
        "domain": domain,
        "modality": modalities,
        "inputs": _string_inputs(row.get("inputs")),
        "mode": planner_request_mode,
        "allowlist_mode": allowlist_mode,
        "runtime_surface": "planner_step_prediction_eval",
        "debug_selection": False,
    }
    payload["_prediction_request_metadata"] = {
        "domain_source": domain_source,
        "modality_source": modality_source,
    }
    return payload


def _step_tool_from_step(step: Any) -> str | None:
    if isinstance(step, str):
        text = step.strip()
        return text or None
    if not isinstance(step, Mapping):
        return None
    for field in ("tool", "tool_id", "toolId", "canonical_tool_id", "tool_name"):
        text = str(step.get(field) or "").strip()
        if text:
            return text
    return None


def extract_plan_step_tool_ids(plan_payload: Mapping[str, Any]) -> list[str]:
    """Extract ordered tool IDs from plan steps, never from ranked candidates."""
    step_lists: list[Any] = []
    dag = plan_payload.get("dag")
    if isinstance(dag, Mapping):
        step_lists.append(dag.get("steps"))
    step_lists.extend([plan_payload.get("steps"), plan_payload.get("plan_steps")])

    for steps in step_lists:
        if not isinstance(steps, list):
            continue
        tool_ids = [
            tool_id
            for step in steps
            if (tool_id := _step_tool_from_step(step)) is not None
        ]
        if tool_ids:
            return tool_ids
    return []


def _compact_plan_payload(plan_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(plan_payload, Mapping):
        return {}
    compact: dict[str, Any] = {}
    for key in (
        "plan_id",
        "schema_version",
        "version",
        "mode",
        "allowlist_mode",
        "resolvable",
        "chosen_tool",
        "warnings",
        "routing_diagnostics",
    ):
        if key in plan_payload:
            compact[key] = plan_payload.get(key)

    dag = plan_payload.get("dag")
    if isinstance(dag, Mapping):
        compact["dag"] = {
            "steps": dag.get("steps") if isinstance(dag.get("steps"), list) else [],
            "artifacts": (
                dag.get("artifacts") if isinstance(dag.get("artifacts"), list) else []
            ),
        }
    else:
        steps = plan_payload.get("steps")
        if isinstance(steps, list):
            compact["dag"] = {"steps": steps, "artifacts": []}
    return compact


def _raw_plan_summary(plan_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(plan_payload, Mapping):
        return {}
    dag = plan_payload.get("dag")
    dag_steps = dag.get("steps") if isinstance(dag, Mapping) else None
    context = plan_payload.get("context")
    tool_candidates = (
        context.get("tool_candidates") if isinstance(context, Mapping) else None
    )
    return {
        "raw_candidate_count": len(plan_payload.get("candidates") or []),
        "raw_context_tool_candidate_count": len(tool_candidates or []),
        "raw_plan_step_count": len(dag_steps or []),
    }


def _call_local_agent_plan(request_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    from brain_researcher.services.agent.web_service import app

    payload = {
        key: value
        for key, value in request_payload.items()
        if key != "_prediction_request_metadata"
    }
    client = app.test_client()
    response = client.post("/agent/plan", json=payload)
    data = response.get_json(silent=True)
    if response.status_code >= 400:
        raise PlannerCallError(
            f"local /agent/plan returned HTTP {response.status_code}: {data}"
        )
    if not isinstance(data, Mapping):
        raise PlannerCallError("local /agent/plan returned a non-object payload")
    return data


def _call_http_agent_plan(
    request_payload: Mapping[str, Any], *, url: str, timeout_s: float
) -> Mapping[str, Any]:
    payload = {
        key: value
        for key, value in request_payload.items()
        if key != "_prediction_request_metadata"
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise PlannerCallError(f"HTTP /agent/plan returned {exc.code}: {text}") from exc
    except Exception as exc:
        raise PlannerCallError(f"HTTP /agent/plan call failed: {exc}") from exc
    if not isinstance(data, Mapping):
        raise PlannerCallError("HTTP /agent/plan returned a non-object payload")
    return data


def _planner_for_surface(
    planner_surface: str,
    *,
    http_agent_plan_url: str,
    http_timeout_s: float,
) -> PlannerFn:
    if planner_surface == "local-agent-plan":
        return _call_local_agent_plan
    if planner_surface == "http-agent-plan":
        return lambda payload: _call_http_agent_plan(
            payload, url=http_agent_plan_url, timeout_s=http_timeout_s
        )
    raise ValueError(f"Unsupported planner surface: {planner_surface}")


def _prediction_row(
    *,
    label_row: Mapping[str, Any],
    mode: str,
    planner_surface: str,
    allowlist_mode: str,
    request_payload: Mapping[str, Any],
    plan_payload: Mapping[str, Any] | None,
    error: str | None,
    latency_ms: float,
) -> dict[str, Any]:
    step_tool_ids = extract_plan_step_tool_ids(plan_payload or {})
    compact_plan = _compact_plan_payload(plan_payload)
    request_meta = request_payload.get("_prediction_request_metadata")
    row = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "planner_step_prediction",
        "task_id": str(label_row.get("task_id") or ""),
        "mode": mode,
        "planner_surface": planner_surface,
        "planner_allowlist_mode": allowlist_mode,
        "prediction_kind": "planning_only",
        "analysis_executed": False,
        "flat_ranked_list_prediction": False,
        "query": label_row.get("query"),
        "category": label_row.get("category"),
        "label_line_number": label_row.get("_line_number"),
        "planner_request": {
            key: value
            for key, value in request_payload.items()
            if key != "_prediction_request_metadata"
        },
        "planner_request_metadata": (
            request_meta if isinstance(request_meta, dict) else {}
        ),
        "planner_step_tool_ids": step_tool_ids,
        "plan": compact_plan,
        "planner_raw_summary": _raw_plan_summary(plan_payload),
        "planner_status": "error" if error else ("ok" if step_tool_ids else "no_steps"),
        "planner_error": error,
        "planner_latency_ms": round(latency_ms, 3),
        "runtime_limitations": [
            "prediction_planning_only_no_analysis_execution",
            "flat_ranked_tool_search_lists_not_used_for_sequence_predictions",
        ],
    }
    return row


def run_predictions(
    *,
    labels_jsonl: Path,
    max_tasks: int | None,
    mode: str,
    planner_surface: str,
    allowlist_mode: str,
    sequence_labels_only: bool = True,
    planner_fn: PlannerFn,
) -> dict[str, Any]:
    label_rows_all = _load_jsonl(labels_jsonl)
    if sequence_labels_only:
        label_rows = [row for row in label_rows_all if _sequence_label(row)]
    else:
        label_rows = list(label_rows_all)
    if max_tasks is not None:
        label_rows = label_rows[: max(0, max_tasks)]

    prediction_rows: list[dict[str, Any]] = []
    for label_row in label_rows:
        request_payload = build_plan_request(
            label_row,
            allowlist_mode=allowlist_mode,
            planner_request_mode="catalog",
        )
        started = time.perf_counter()
        plan_payload: Mapping[str, Any] | None = None
        error = None
        try:
            plan_payload = planner_fn(request_payload)
        except Exception as exc:
            error = str(exc)
        latency_ms = (time.perf_counter() - started) * 1000
        prediction_rows.append(
            _prediction_row(
                label_row=label_row,
                mode=mode,
                planner_surface=planner_surface,
                allowlist_mode=allowlist_mode,
                request_payload=request_payload,
                plan_payload=plan_payload,
                error=error,
                latency_ms=latency_ms,
            )
        )

    status_counts = Counter(row["planner_status"] for row in prediction_rows)
    category_counts = Counter(str(row.get("category") or "") for row in prediction_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "planner_step_predictions",
        "mode": mode,
        "planner_surface": planner_surface,
        "planner_allowlist_mode": allowlist_mode,
        "labels_jsonl": str(labels_jsonl),
        "labels_loaded": len(label_rows_all),
        "sequence_labels_only": sequence_labels_only,
        "selected_label_rows": len(label_rows),
        "prediction_rows": len(prediction_rows),
        "rows_with_planner_steps": status_counts.get("ok", 0),
        "rows_without_planner_steps": status_counts.get("no_steps", 0),
        "rows_with_errors": status_counts.get("error", 0),
        "planner_status_counts": dict(sorted(status_counts.items())),
        "selected_rows_by_category": dict(sorted(category_counts.items())),
        "planning_only": True,
        "analysis_executed": False,
        "flat_ranked_list_predictions_used": False,
        "notes": [
            "Rows are planner-step predictions from a read-only plan contract.",
            "No analysis was executed.",
            "Ordered sequence predictions are extracted only from plan steps.",
            "Flat ranked-list tool_search outputs are not used as sequence predictions.",
        ],
    }
    return {"summary": summary, "predictions": prediction_rows}


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        ROOT
        / "benchmarks"
        / "tool_routing_validation"
        / "planner_step_predictions"
        / stamp
    )


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'\"")


def _load_runtime_env() -> None:
    _load_env_file(ROOT / ".env")
    _load_env_file(ROOT / ".env.local")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--labels-jsonl", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--max-tasks", type=int, default=None)
    parser.add_argument("--mode", type=str, default=DEFAULT_MODE)
    parser.add_argument(
        "--planner-surface",
        choices=PLANNER_SURFACES,
        default="local-agent-plan",
    )
    parser.add_argument(
        "--allowlist-mode",
        choices=("curated", "diagnostic"),
        default="diagnostic",
    )
    parser.add_argument("--http-agent-plan-url", default=DEFAULT_HTTP_AGENT_PLAN_URL)
    parser.add_argument("--http-timeout-s", type=float, default=30.0)
    parser.add_argument("--output-jsonl", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--load-env",
        action="store_true",
        help="Load repo .env/.env.local at runtime without printing values.",
    )
    parser.add_argument(
        "--include-all-labels",
        action="store_true",
        help="Generate predictions for labels without expected sequence labels too.",
    )
    args = parser.parse_args(argv)
    if args.load_env:
        _load_runtime_env()

    output_dir = args.output_dir or (
        None if args.output_jsonl is not None else _default_output_dir()
    )
    output_jsonl = args.output_jsonl or (
        output_dir / "planner_step_predictions.jsonl" if output_dir else None
    )
    if output_jsonl is None:
        raise ValueError("Either --output-jsonl or --output-dir must be provided")

    planner_fn = _planner_for_surface(
        args.planner_surface,
        http_agent_plan_url=args.http_agent_plan_url,
        http_timeout_s=args.http_timeout_s,
    )
    payload = run_predictions(
        labels_jsonl=args.labels_jsonl,
        max_tasks=args.max_tasks,
        mode=args.mode,
        planner_surface=args.planner_surface,
        allowlist_mode=args.allowlist_mode,
        sequence_labels_only=not args.include_all_labels,
        planner_fn=planner_fn,
    )

    _write_jsonl(output_jsonl, payload["predictions"])
    payload["summary"]["output_jsonl"] = str(output_jsonl)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "summary.json").write_text(
            json.dumps(payload["summary"], indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
