#!/usr/bin/env python3
"""Score plan-level tool selection against capability templates.

This pilot is intentionally non-executing. It parses early agent actions from
JSON event traces, scores whether the first N actions cover task capabilities,
and reports parser-validation metrics on trace-shaped fixtures.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shlex
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


ROOT = _repo_root()
DEFAULT_PILOT_DIR = ROOT / "benchmarks" / "tool_routing_validation" / "capability_pilot"
DEFAULT_TASKS = DEFAULT_PILOT_DIR / "microtooling_capability_pilot.v1.jsonl"
DEFAULT_PARSER_FIXTURES = DEFAULT_PILOT_DIR / "parser_validation_traces.v1.jsonl"
DEFAULT_OUT_JSON = DEFAULT_PILOT_DIR / "capability_pilot_results.v1.json"
DEFAULT_OUT_ROWS = DEFAULT_PILOT_DIR / "capability_pilot_rows.v1.jsonl"
DEFAULT_CONDITION_TRACES = (
    (
        "codex_only_catalog",
        ROOT
        / "benchmarks"
        / "tool_routing_validation"
        / "codex_microtooling_pilot_20260503"
        / "codex_only_catalog.events.jsonl",
    ),
    (
        "codex_plus_br_shortlist",
        ROOT
        / "benchmarks"
        / "tool_routing_validation"
        / "codex_microtooling_pilot_20260503"
        / "codex_plus_br_shortlist.events.jsonl",
    ),
)
STRICT_DIRECT_BR_CONDITIONS = {"codex_cli_gpt55_with_br"}
GENERIC_BR_ROUTE_TOOLS = {"tool_search", "plan_preflight", "get_execution_recipe"}
EXECUTION_HANDOFF_CONTRACT = "execution_handoff_v1"
TRACE_ORACLE_CONTRACT = "trace_oracle_v1"
ROUTING_ONLY_PARAM_KEYS = {"mode", "no_download", "no_heavy_execution", "routing_only"}
META_PARAM_KEYS = {
    "mode",
    "task",
    "task_id",
    "query",
    "prompt",
    "description",
    "metadata",
    "notes",
    "no_download",
    "no_heavy_execution",
    "routing_only",
}

EXECUTION_HANDOFF_DATASET_HINTS: dict[str, dict[str, tuple[str, ...]]] = {
    "DATA-001": {
        "expected": ("haxby", "ds000105", "fetch_haxby"),
        "forbidden": ("haxby_raiders", "ds000114"),
    },
    "PREP-001": {
        "expected": ("haxby", "ds000105", "fetch_haxby"),
        "forbidden": ("haxby_raiders", "ds000114"),
    },
    "QC-001": {
        "expected": ("haxby", "ds000105", "fetch_haxby"),
        "forbidden": ("haxby_raiders", "ds000114"),
    },
    "STAT-001": {
        "expected": ("haxby", "ds000105", "fetch_haxby"),
        "forbidden": ("haxby_raiders", "ds000114"),
    },
    "ML-001": {
        "expected": ("haxby", "ds000105", "fetch_haxby"),
        "forbidden": ("haxby_raiders", "ds000114"),
    },
    "CONN-001": {
        "expected": ("adhd", "adhd200", "adhd-200"),
        "forbidden": (),
    },
    "HARM-001": {
        "expected": ("abide",),
        "forbidden": (),
    },
}

EXECUTION_HANDOFF_REQUIRED_TEXT_GATES: dict[str, dict[str, tuple[str, ...]]] = {
    "CONN-001": {
        "atlas_bound": ("msdl", "fetch_atlas", "fetch_atlas_msdl"),
        "confounds_bound": ("clean_confounds", "load_confounds", "confound"),
    },
    "DATA-001": {
        "bids_validation_bound": (
            "validate_bids",
            "validate_bids_structure",
            "bidslayout",
            "bids-validator",
            "use_pybids_layout",
        ),
    },
    "META-001": {
        "study_search_bound": (
            "neurosynth_search_terms",
            "pipeline.search",
            "neurosynth",
            "study_search",
        ),
    },
    "STATINF-001": {
        "multiple_comparison_bound": (
            "multiple_comparison_correction",
            "tfce",
            "fwe",
            "fdr",
            "max-stat",
            "max_stat",
            "permuted_ols",
            "randomise",
        ),
    },
    "HARM-001": {
        "site_diagnostics_bound": (
            "detect_outliers",
            "site_effect",
            "site diagnostics",
            "mixed_effects",
        ),
    },
    "SPEC-001": {
        "multi_echo_bound": ("tedana", "multi-echo", "multi_echo"),
    },
}

EXECUTION_HANDOFF_FORBIDDEN_TEXT: dict[str, tuple[str, ...]] = {
    "PREP-001": ("--fs-no-reconall",),
}

TRACE_ORACLE_SPECS: dict[str, dict[str, Any]] = {
    "DATA-001": {
        "required_calls": [
            {
                "id": "dataset_resolution",
                "patterns": [
                    {"action_type": "mcp_tool", "pattern": "dataset_get_resources", "match": "exact"},
                    {"action_type": "recipe_tool", "pattern": "openneuro.search", "match": "exact"},
                    {"action_type": "bash_cmd", "pattern": r"fetch_haxby|openneuro", "match": "regex"},
                ],
            },
            {
                "id": "bids_validation",
                "text_any": ("validate_bids", "validate_bids_structure", "bidslayout", "bids-validator", "use_pybids_layout"),
            },
        ],
    },
    "PREP-001": {
        "required_calls": [
            {"id": "dataset_resolution", "text_any": ("dataset_get_resources", "fetch_haxby", "ds000105", "bids_dir")},
            {"id": "fmriprep_route", "text_any": ("fmriprep", "workflow_fmriprep_preprocessing")},
            {"id": "surface_reconstruction", "text_any": ("fsaverage", "fsnative", "freesurfer", "recon-all", "--fs-license-file")},
        ],
    },
    "QC-001": {
        "required_calls": [
            {"id": "dataset_resolution", "text_any": ("dataset_get_resources", "fetch_haxby", "ds000105", "bids_dir")},
            {"id": "mriqc_backend", "text_any": ("mriqc", "workflow_mriqc", "workflow_preprocessing_qc")},
            {"id": "qc_report_or_table", "text_any": ("get_qc_table", "detect_outliers", "dashboard", "report", "group")},
        ],
    },
    "STAT-001": {
        "required_calls": [
            {"id": "dataset_resolution", "text_any": ("dataset_get_resources", "fetch_haxby", "ds000105", "bids_dir")},
            {"id": "glm_workflow", "text_any": ("workflow_task_glm_group", "glm_first_level", "firstlevelmodel", "nilearn.glm.first_level")},
            {"id": "condition_contrast", "text_any": ("contrast", "compute_contrast", "events", "hrf")},
        ],
    },
    "CONN-001": {
        "required_calls": [
            {"id": "dataset_resolution", "text_any": ("dataset_get_resources", "adhd", "adhd200", "adhd-200")},
            {"id": "atlas_resolution", "text_any": ("fetch_atlas", "fetch_atlas_msdl", "msdl")},
            {"id": "connectome_workflow_or_connectivity", "text_any": ("workflow_rest_connectome_e2e", "nilearn_connectivity_matrix", "connectivitymeasure")},
            {"id": "confound_cleaning", "text_any": ("clean_confounds", "load_confounds", "confound", "nilearn.signal")},
        ],
        "terminal_tools": ("coordinate_meta_analysis", "nilearn_connectivity_matrix", "connectivity_measures"),
    },
    "ML-001": {
        "required_calls": [
            {"id": "dataset_resolution", "text_any": ("dataset_get_resources", "fetch_haxby", "ds000105", "fetch_haxby")},
            {"id": "roi_feature_extraction", "text_any": ("nilearn.maskers", "nilearn_roi", "nifti", "masker")},
            {"id": "svm_cv_decoding", "text_any": ("sklearn.svm", "svc", "cross_val", "cross-validation", "cross_validation", "decoder")},
        ],
    },
    "META-001": {
        "required_calls": [
            {"id": "study_search", "text_any": ("neurosynth_search_terms", "pipeline.search", "study_search", "neurosynth")},
            {"id": "coordinate_meta_analysis", "text_any": ("coordinate_meta_analysis", "ale", "nimare", "meta_analysis")},
        ],
        "terminal_tools": ("coordinate_meta_analysis",),
    },
    "STATINF-001": {
        "required_calls": [
            {"id": "permutation_inference", "text_any": ("permutation_testing", "permuted_ols", "randomise", "permutation")},
            {"id": "multiple_comparison_correction", "text_any": ("multiple_comparison_correction", "tfce", "fwe", "fdr", "max-stat", "max_stat")},
        ],
    },
    "HARM-001": {
        "required_calls": [
            {"id": "dataset_resolution", "text_any": ("dataset_get_resources", "abide")},
            {"id": "site_harmonization", "text_any": ("workflow_data_harmonization", "harmonize_data", "combat", "neurocombat")},
            {"id": "site_effect_diagnostics", "text_any": ("detect_outliers", "site_effect", "mixed_effects", "diagnostic")},
        ],
    },
    "SPEC-001": {
        "required_calls": [
            {"id": "multi_echo_denoising", "text_any": ("tedana", "multi-echo", "multi_echo")},
            {"id": "confound_cleaning", "text_any": ("clean_confounds", "load_confounds", "confound", "nilearn.signal")},
        ],
    },
}

SCORE_TEMPLATE_REPAIR_PATTERNS: dict[str, list[dict[str, Any]]] = {
    "DATA-001": [
        {
            "capability": "bids_validation",
            "action_type": "recipe_tool",
            "pattern": "list_dataset_assets",
            "match": "exact",
            "requires_any_input": [
                {"path": "params.validate_bids", "equals": True},
                {"path": "params.use_pybids_layout", "equals": True},
            ],
        }
    ],
    "STAT-001": [
        {
            "capability": capability,
            "action_type": "recipe_tool",
            "pattern": "workflow_task_glm_group",
            "match": "exact",
        }
        for capability in (
            "first_level_glm",
            "hrf_modeling",
            "contrast_estimation",
        )
    ],
    "STATINF-001": [
        {
            "capability": "permutation_inference",
            "action_type": "bash_cmd",
            "pattern": r"\b(randomise|palm)\b",
            "match": "regex",
        },
        {
            "capability": "multiple_comparison_control",
            "action_type": "bash_cmd",
            "pattern": r"\b(randomise|palm)\b.*(\s-T\b|tfce|fwe|family[- ]wise)",
            "match": "regex",
        },
        {
            "capability": "permutation_inference",
            "action_type": "py_import_or_call",
            "pattern": "non_parametric_inference",
            "match": "contains",
        },
        {
            "capability": "multiple_comparison_control",
            "action_type": "py_import_or_call",
            "pattern": "non_parametric_inference",
            "match": "contains",
        },
        {
            "capability": "multiple_comparison_control",
            "action_type": "py_import_or_call",
            "pattern": "permuted_ols",
            "match": "contains",
        },
    ],
    "QC-001": [
        {
            "capability": "qc_reporting",
            "action_type": "bash_cmd",
            "pattern": r"\bmriqc\b.*(\bgroup\b|--verbose-reports|\breport\b|\.html\b|\.json\b)",
            "match": "regex",
        }
    ],
    "PREP-001": [
        {
            "capability": "surface_reconstruction",
            "action_type": "bash_cmd",
            "pattern": r"\bfmriprep\b.*(--fs-license-file|--fs-subjects-dir|fsaverage|fsnative|freesurfer|recon-all)",
            "match": "regex",
        }
    ],
    "HARM-001": [
        {
            "capability": "site_harmonization",
            "action_type": "py_call",
            "pattern": r"(harmonizationLearn|harmonizationApply|neuroCombat)$",
            "match": "regex",
        }
    ],
    "CONN-001": [
        {
            "capability": "atlas_timeseries_extraction",
            "action_type": "py_import_or_call",
            "pattern": "NiftiMapsMasker",
            "match": "contains",
        },
        {
            "capability": "atlas_timeseries_extraction",
            "action_type": "py_import_or_call",
            "pattern": "NiftiLabelsMasker",
            "match": "contains",
        },
        {
            "capability": "connectivity_extraction",
            "action_type": "py_import_or_call",
            "pattern": "ConnectivityMeasure",
            "match": "contains",
        },
        {
            "capability": "confound_cleaning",
            "action_type": "bash_cmd",
            "pattern": r"(load_confounds|nilearn\.signal|confounds?\s*=)",
            "match": "regex",
        },
    ],
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no} is not a JSON object")
        rows.append(payload)
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def load_tasks(path: Path) -> list[dict[str, Any]]:
    tasks = _read_jsonl(path)
    seen: set[str] = set()
    for row in tasks:
        task_id = _string(row.get("task_id"))
        required = [_string(item) for item in _as_list(row.get("required_capabilities"))]
        if not task_id:
            raise ValueError(f"Task without task_id in {path}")
        if task_id in seen:
            raise ValueError(f"Duplicate task_id in {path}: {task_id}")
        if not required:
            raise ValueError(f"Task without required_capabilities: {task_id}")
        seen.add(task_id)
    return tasks


def _action(
    *,
    action_type: str,
    target: str,
    source: str,
    index: int,
    task_id: str | None = None,
    confidence: float = 1.0,
    raw: Any = None,
    budget_group: int | None = None,
) -> dict[str, Any]:
    return {
        "index": index,
        "action_type": action_type,
        "target": target,
        "task_id": task_id,
        "source": source,
        "confidence": confidence,
        "raw": raw,
        "budget_group": budget_group if budget_group is not None else index,
    }


def _tool_name_from_payload(payload: Mapping[str, Any]) -> str:
    for key in ("name", "tool", "tool_name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    function = payload.get("function")
    if isinstance(function, Mapping):
        value = function.get("name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    item = payload.get("item")
    if isinstance(item, Mapping):
        return _tool_name_from_payload(item)
    part = payload.get("part")
    if isinstance(part, Mapping):
        return _tool_name_from_payload(part)
    return ""


def _arguments_from_payload(payload: Mapping[str, Any]) -> Any:
    for key in ("arguments", "args", "input", "parameters"):
        if key in payload:
            return payload[key]
    state = payload.get("state")
    if isinstance(state, Mapping):
        for key in ("input", "arguments", "args", "parameters"):
            if key in state:
                return state[key]
    item = payload.get("item")
    if isinstance(item, Mapping):
        return _arguments_from_payload(item)
    part = payload.get("part")
    if isinstance(part, Mapping):
        return _arguments_from_payload(part)
    return None


def _command_from_payload(payload: Mapping[str, Any]) -> str:
    for key in ("command", "cmd", "shell_command", "code"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    state = payload.get("state")
    if isinstance(state, Mapping):
        command = _command_from_payload(state)
        if command:
            return command
    item = payload.get("item")
    if isinstance(item, Mapping):
        return _command_from_payload(item)
    part = payload.get("part")
    if isinstance(part, Mapping):
        return _command_from_payload(part)
    return ""


def _task_id_from_payload(payload: Mapping[str, Any]) -> str | None:
    for key in ("task_id", "task"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    item = payload.get("item")
    if isinstance(item, Mapping):
        return _task_id_from_payload(item)
    return None


def _command_from_arguments(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments.strip()
    if isinstance(arguments, Mapping):
        for key in ("cmd", "command", "shell_command", "code"):
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _claude_tool_uses(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    message = payload.get("message")
    if not isinstance(message, Mapping):
        return []
    content = message.get("content")
    out: list[Mapping[str, Any]] = []
    for block in _as_list(content):
        if isinstance(block, Mapping) and block.get("type") == "tool_use":
            out.append(block)
    return out


def _normalize_mcp_tool_name(name: str) -> str:
    """Normalize common client-specific MCP tool names without hiding provenance."""

    if name.startswith("mcp__"):
        parts = name.split("__")
        if len(parts) >= 3:
            return parts[-1]
    for prefix in (
        "brain-researcher-local_",
        "brain-researcher-prod_",
        "brain_researcher_local_",
        "brain_researcher_prod_",
    ):
        if name.startswith(prefix):
            return name.removeprefix(prefix)
    return name


def _loads_jsonish(text: str) -> Any:
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _prediction_rows_from_text(text: str) -> list[Mapping[str, Any]]:
    payload = _loads_jsonish(text)
    if isinstance(payload, Mapping):
        rows = payload.get("predictions")
        return [row for row in _as_list(rows) if isinstance(row, Mapping)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    return []


def _markdown_code_fence_actions(
    text: str,
    *,
    start_index: int,
    raw: Any = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    """Extract concrete route actions from markdown code fences.

    This intentionally treats fenced shell/python snippets as proposed
    invocations, while leaving plain-text tool mentions unscored.
    """

    actions: list[dict[str, Any]] = []
    next_index = start_index
    for match in re.finditer(
        r"```(?P<lang>[A-Za-z0-9_+.-]*)[^\n]*\n(?P<code>.*?)(?:\n```|$)",
        text,
        flags=re.DOTALL,
    ):
        lang = match.group("lang").strip().lower()
        code = match.group("code").strip()
        if not code:
            continue
        if lang in {"python", "py"}:
            budget_group = next_index
            for py_action in _python_actions(
                code,
                start_index=next_index,
                budget_group=budget_group,
                task_id=task_id,
                raw=raw,
            ):
                py_action["source"] = "agent_message.code_fence.python"
                py_action["confidence"] = min(float(py_action.get("confidence") or 0.0), 0.8)
                actions.append(py_action)
                next_index = py_action["index"] + 1
            continue
        if lang in {"", "bash", "sh", "shell", "zsh", "console", "terminal"}:
            budget_group = next_index
            actions.append(
                _action(
                    action_type="bash_cmd",
                    target=code,
                    source="agent_message.code_fence.shell",
                    index=next_index,
                    task_id=task_id,
                    confidence=0.8,
                    raw=raw,
                    budget_group=budget_group,
                )
            )
            next_index += 1
            for py_action in _python_actions(
                _python_source_from_command(code),
                start_index=next_index,
                budget_group=budget_group,
                task_id=task_id,
                raw=raw,
            ):
                actions.append(py_action)
                next_index = py_action["index"] + 1
    return actions


def _python_source_from_command(command: str) -> str:
    if not command:
        return ""
    for candidate in _python_command_candidates(command):
        heredoc = re.search(
            r"python(?:\d(?:\.\d+)?)?\s+-\s+<<['\"]?PY['\"]?\n(?P<code>.*?)(?:\nPY\b|$)",
            candidate,
            flags=re.DOTALL,
        )
        if heredoc:
            return heredoc.group("code")
        inline = re.search(
            r"python(?:\d(?:\.\d+)?)?\s+-c\s+(['\"])(?P<code>.*)\1",
            candidate,
        )
        if inline:
            return inline.group("code")
        if "\n" in candidate and ("import " in candidate or "from " in candidate):
            return candidate
    return ""


def _python_command_candidates(command: str) -> list[str]:
    candidates: list[str] = []
    try:
        parts = shlex.split(command)
    except ValueError:
        return [command]
    if len(parts) >= 3 and Path(parts[0]).name in {"bash", "sh"} and parts[1] in {
        "-c",
        "-lc",
    }:
        candidates.append(parts[2])
    candidates.append(command)
    return list(dict.fromkeys(candidates))


def _python_actions(
    source: str,
    *,
    start_index: int,
    budget_group: int,
    raw: Any = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    if not source.strip():
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    records: list[tuple[int, int, int, str, str, str, float]] = []
    ordinal = 0

    def add_record(
        node: ast.AST,
        *,
        action_type: str,
        target: str,
        source_name: str,
        confidence: float,
    ) -> None:
        nonlocal ordinal
        ordinal += 1
        records.append(
            (
                int(getattr(node, "lineno", 0) or 0),
                int(getattr(node, "col_offset", 0) or 0),
                ordinal,
                action_type,
                target,
                source_name,
                confidence,
            )
        )

    # First pass: build alias map so that `import X as Y; Y.method` and
    # `from X import Y; Y(...)` resolve back to the canonical dotted path.
    alias_map: dict[str, str] = {}
    implicit_from_import_bindings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    alias_map[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                bound = alias.asname or alias.name
                resolved = f"{module}.{alias.name}" if module else alias.name
                alias_map[bound] = resolved
                if module and alias.asname is None:
                    implicit_from_import_bindings.add(bound)

    def _resolve_alias(name: str) -> str:
        if not name:
            return name
        head, sep, rest = name.partition(".")
        if head in alias_map:
            return alias_map[head] + sep + rest
        return name

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add_record(
                    node,
                    action_type="py_import",
                    target=alias.name,
                    source_name="python_ast.import",
                    confidence=0.9,
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module:
                add_record(
                    node,
                    action_type="py_import",
                    target=module,
                    source_name="python_ast.import_from",
                    confidence=0.9,
                )
            for alias in node.names:
                if module:
                    target = f"{module}.{alias.name}"
                else:
                    target = alias.name
                add_record(
                    node,
                    action_type="py_import",
                    target=target,
                    source_name="python_ast.import_from",
                    confidence=0.9,
                )
        elif isinstance(node, ast.Call):
            target = _call_name(node.func)
            if target:
                add_record(
                    node,
                    action_type="py_call",
                    target=target,
                    source_name="python_ast.call",
                    confidence=0.8,
                )
                resolved = _resolve_alias(target)
                if (
                    resolved
                    and resolved != target
                    and target not in implicit_from_import_bindings
                ):
                    add_record(
                        node,
                        action_type="py_call",
                        target=resolved,
                        source_name="python_ast.call.alias_resolved",
                        confidence=0.85,
                    )
                recipe_tool_id = _call_keyword_string(node, "tool_id")
                if target.split(".")[-1] == "get_execution_recipe" and recipe_tool_id:
                    add_record(
                        node,
                        action_type="recipe_tool",
                        target=recipe_tool_id,
                        source_name="python_ast.call.keyword.tool_id",
                        confidence=0.95,
                    )
        elif isinstance(node, ast.Attribute):
            # Emit attribute accesses (e.g., `smf.mixedlm` inside `print(smf.mixedlm)`)
            # so canonical capability matchers can see the resolved symbol.
            target = _call_name(node)
            if target and "." in target:
                resolved = _resolve_alias(target)
                if resolved and resolved != target:
                    add_record(
                        node,
                        action_type="py_call",
                        target=resolved,
                        source_name="python_ast.attribute.alias_resolved",
                        confidence=0.7,
                    )
    actions: list[dict[str, Any]] = []
    for offset, (_, _, _, action_type, target, source_name, confidence) in enumerate(
        sorted(records)
    ):
        actions.append(
            _action(
                action_type=action_type,
                target=target,
                source=source_name,
                index=start_index + offset,
                task_id=task_id,
                confidence=confidence,
                raw=raw,
                budget_group=budget_group,
            )
        )
    return actions


def _br_cli_recipe_actions(
    command: str,
    *,
    start_index: int,
    budget_group: int,
    raw: Any = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    """Extract recipe selection from an actual BR CLI invocation.

    Route text such as ``printf 'get_execution_recipe(tool_id=...)'`` is only a
    mention and must not receive canonical tool credit. This helper therefore
    requires the shell command itself to invoke ``br get_execution_recipe`` or
    ``br mcp get_execution_recipe``.
    """

    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = re.compile(
        r"^\s*(?:(?:[A-Za-z_][A-Za-z0-9_]*=[^;&|()\s]+)\s+)*"
        r"br\s+(?:mcp\s+)?get[-_]?execution[-_]?recipe\b"
        r".*?(?:--tool[-_]id|tool_id=)\s*['\"]?(?P<tool_id>workflow_[\w.-]+)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for candidate in _python_command_candidates(command):
        match = pattern.search(candidate.strip())
        if match is None:
            continue
        tool_id = match.group("tool_id")
        if tool_id in seen:
            continue
        seen.add(tool_id)
        actions.append(
            _action(
                action_type="recipe_tool",
                target=tool_id,
                source="shell_command.br_get_execution_recipe.tool_id",
                index=start_index + len(actions),
                task_id=task_id,
                confidence=0.9,
                raw=raw,
                budget_group=budget_group,
            )
        )
    return actions


def _call_keyword_string(node: ast.Call, keyword_name: str) -> str:
    for keyword in node.keywords:
        if keyword.arg != keyword_name:
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return ""


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _recipe_tool_action(
    *,
    normalized_name: str,
    arguments: Any,
    source: str,
    index: int,
    task_id: str | None,
    raw: Any,
) -> dict[str, Any] | None:
    if normalized_name != "get_execution_recipe" or not isinstance(arguments, Mapping):
        return None
    tool_id = _string(arguments.get("tool_id"))
    if not tool_id:
        return None
    return _action(
        action_type="recipe_tool",
        target=tool_id,
        source=f"{source}.arguments.tool_id",
        index=index,
        task_id=task_id,
        confidence=0.95,
        raw=raw,
    )


def parse_events(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen_invocation_ids: set[str] = set()
    next_index = 1
    for event in events:
        item = event.get("item") if isinstance(event.get("item"), Mapping) else {}
        part = event.get("part") if isinstance(event.get("part"), Mapping) else {}
        payloads = [event]
        if isinstance(item, Mapping):
            payloads.append(item)
        if isinstance(part, Mapping):
            payloads.append(part)

        text = ""
        if isinstance(item, Mapping) and isinstance(item.get("text"), str):
            text = item["text"]
        elif isinstance(part, Mapping) and isinstance(part.get("text"), str):
            text = part["text"]
        elif isinstance(event.get("text"), str):
            text = event["text"]
        if text:
            for prediction in _prediction_rows_from_text(text):
                task_id = _string(prediction.get("task_id")) or None
                tools = prediction.get("top_tool_ids") or prediction.get("predicted_tool_ids")
                for tool_id in _as_list(tools):
                    target = _string(tool_id)
                    if not target:
                        continue
                    actions.append(
                        _action(
                            action_type="plan_tool",
                            target=target,
                            source="agent_message.predictions",
                            index=next_index,
                            task_id=task_id,
                            confidence=1.0,
                            raw=prediction,
                        )
                    )
                    next_index += 1
            for text_action in _markdown_code_fence_actions(
                text,
                start_index=next_index,
                raw=event,
                task_id=_task_id_from_payload(event),
            ):
                actions.append(text_action)
                next_index = int(text_action.get("index") or next_index) + 1

        for payload in payloads:
            event_type = _string(payload.get("type")).lower()
            name = _tool_name_from_payload(payload)
            arguments = _arguments_from_payload(payload)
            command = _command_from_payload(payload) or _command_from_arguments(arguments)
            task_id = _task_id_from_payload(payload) or _task_id_from_payload(event)
            is_tool_event = (
                "tool_call" in event_type
                or "tool_use" in event_type
                or "function_call" in event_type
                or event_type == "command_execution"
                or event_type == "tool"
            )
            if is_tool_event:
                invocation_id = _string(payload.get("id"))
                if invocation_id:
                    invocation_key = f"{event_type}:{invocation_id}"
                    if invocation_key in seen_invocation_ids:
                        continue
                    seen_invocation_ids.add(invocation_key)
                if name in {"shell", "bash", "exec", "exec_command", "python"} and command:
                    budget_group = next_index
                    actions.append(
                        _action(
                            action_type="bash_cmd",
                            target=command,
                            source=f"{event_type}.command",
                            index=next_index,
                            task_id=task_id,
                            confidence=0.85,
                            raw=payload,
                            budget_group=budget_group,
                        )
                    )
                    next_index += 1
                    for py_action in _python_actions(
                        _python_source_from_command(command),
                        start_index=next_index,
                        budget_group=budget_group,
                        task_id=task_id,
                        raw=payload,
                    ):
                        actions.append(py_action)
                        next_index = py_action["index"] + 1
                    for recipe_action in _br_cli_recipe_actions(
                        command,
                        start_index=next_index,
                        budget_group=budget_group,
                        task_id=task_id,
                        raw=payload,
                    ):
                        actions.append(recipe_action)
                        next_index = recipe_action["index"] + 1
                elif name:
                    normalized_name = _normalize_mcp_tool_name(name)
                    actions.append(
                        _action(
                            action_type="mcp_tool",
                            target=normalized_name,
                            source=event_type,
                            index=next_index,
                            task_id=task_id,
                            confidence=0.95,
                            raw=payload,
                        )
                    )
                    next_index += 1
                    recipe_action = _recipe_tool_action(
                        normalized_name=normalized_name,
                        arguments=arguments,
                        source=event_type,
                        index=next_index,
                        task_id=task_id,
                        raw=payload,
                    )
                    if recipe_action is not None:
                        actions.append(recipe_action)
                        next_index += 1
                elif command:
                    budget_group = next_index
                    actions.append(
                        _action(
                            action_type="bash_cmd",
                            target=command,
                            source=f"{event_type}.command",
                            index=next_index,
                            task_id=task_id,
                            confidence=0.85,
                            raw=payload,
                            budget_group=budget_group,
                        )
                    )
                    next_index += 1
                    for py_action in _python_actions(
                        _python_source_from_command(command),
                        start_index=next_index,
                        budget_group=budget_group,
                        task_id=task_id,
                        raw=payload,
                    ):
                        actions.append(py_action)
                        next_index = py_action["index"] + 1
                    for recipe_action in _br_cli_recipe_actions(
                        command,
                        start_index=next_index,
                        budget_group=budget_group,
                        task_id=task_id,
                        raw=payload,
                    ):
                        actions.append(recipe_action)
                        next_index = recipe_action["index"] + 1

        for tool_use in _claude_tool_uses(event):
            name = _string(tool_use.get("name"))
            arguments = _arguments_from_payload(tool_use)
            if arguments is None:
                arguments = tool_use.get("input")
            command = _command_from_arguments(arguments)
            task_id = _task_id_from_payload(tool_use) or _task_id_from_payload(event)
            if name == "Bash" and command:
                budget_group = next_index
                actions.append(
                    _action(
                        action_type="bash_cmd",
                        target=command,
                        source="claude.tool_use.Bash",
                        index=next_index,
                        task_id=task_id,
                        confidence=0.85,
                        raw=tool_use,
                        budget_group=budget_group,
                    )
                )
                next_index += 1
                for py_action in _python_actions(
                    _python_source_from_command(command),
                    start_index=next_index,
                    budget_group=budget_group,
                    task_id=task_id,
                    raw=tool_use,
                ):
                    actions.append(py_action)
                    next_index = py_action["index"] + 1
                for recipe_action in _br_cli_recipe_actions(
                    command,
                    start_index=next_index,
                    budget_group=budget_group,
                    task_id=task_id,
                    raw=tool_use,
                ):
                    actions.append(recipe_action)
                    next_index = recipe_action["index"] + 1
            elif name:
                action_type = "mcp_tool" if name.startswith("mcp__") else "agent_tool"
                normalized_name = _normalize_mcp_tool_name(name)
                actions.append(
                    _action(
                        action_type=action_type,
                        target=normalized_name,
                        source=f"claude.tool_use.{name}",
                        index=next_index,
                        task_id=task_id,
                        confidence=0.85,
                        raw=tool_use,
                    )
                )
                next_index += 1
                # Skill invocations carry the routing intent inside `args` and
                # `skill` fields. Emit a synthetic bash_cmd-equivalent action
                # so canonical regex patterns (which assume bash_cmd targets)
                # can match against the user-provided rationale text.
                if name == "Skill" and isinstance(arguments, Mapping):
                    skill_args = _string(arguments.get("args"))
                    skill_name = _string(arguments.get("skill"))
                    skill_text = " ".join(part for part in (skill_name, skill_args) if part).strip()
                    if skill_text:
                        actions.append(
                            _action(
                                action_type="bash_cmd",
                                target=skill_text,
                                source="claude.tool_use.Skill.args",
                                index=next_index,
                                task_id=task_id,
                                confidence=0.6,
                                raw=tool_use,
                                budget_group=next_index - 1,
                            )
                        )
                        next_index += 1
                recipe_action = _recipe_tool_action(
                    normalized_name=normalized_name,
                    arguments=arguments,
                    source=f"claude.tool_use.{name}",
                    index=next_index,
                    task_id=task_id,
                    raw=tool_use,
                )
                if recipe_action is not None:
                    actions.append(recipe_action)
                    next_index += 1
    return actions


def _matches_action_type(action_type: str, pattern_type: str) -> bool:
    if pattern_type in {"any", "*"}:
        return True
    if pattern_type == "py_import_or_call":
        return action_type in {"py_import", "py_call"}
    if pattern_type == "tool":
        return action_type in {"plan_tool", "mcp_tool", "recipe_tool"}
    return action_type == pattern_type


def _input_from_action(action: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = action.get("raw")
    candidates: list[Any] = []
    if isinstance(raw, Mapping):
        candidates.append(_arguments_from_payload(raw))
        candidates.append(raw.get("input"))
        state = raw.get("state")
        if isinstance(state, Mapping):
            candidates.append(state.get("input"))
        item = raw.get("item")
        if isinstance(item, Mapping):
            candidates.append(item.get("input"))
            item_state = item.get("state")
            if isinstance(item_state, Mapping):
                candidates.append(item_state.get("input"))
        part = raw.get("part")
        if isinstance(part, Mapping):
            candidates.append(part.get("input"))
            part_state = part.get("state")
            if isinstance(part_state, Mapping):
                candidates.append(part_state.get("input"))
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            return candidate
    return {}


def _is_direct_mcp_source(action: Mapping[str, Any]) -> bool:
    source = _string(action.get("source"))
    if source.startswith(("python_ast.", "shell_command.", "agent_message.")):
        return False
    if source.startswith("claude.tool_use."):
        return "mcp__" in source or "brain-researcher" in source or "brain_researcher" in source
    return source.split(".", 1)[0] in {"function_call", "mcp_tool_call", "tool_call", "tool_use"}


def _is_direct_mcp_tool(action: Mapping[str, Any], target: str | None = None) -> bool:
    if action.get("action_type") != "mcp_tool" or not _is_direct_mcp_source(action):
        return False
    return target is None or _string(action.get("target")) == target


def _is_direct_mcp_recipe(action: Mapping[str, Any]) -> bool:
    return action.get("action_type") == "recipe_tool" and _is_direct_mcp_source(action)


def _is_direct_concrete_br_route(action: Mapping[str, Any]) -> bool:
    if _is_direct_mcp_recipe(action):
        return True
    if not _is_direct_mcp_tool(action):
        return False
    return _string(action.get("target")) not in GENERIC_BR_ROUTE_TOOLS


def _plan_preflight_selection_mode(action: Mapping[str, Any]) -> bool:
    value = _input_from_action(action).get("selection_mode")
    if value is True:
        return True
    return _string(value).lower() == "true"


def _strict_br_contract(
    *,
    condition: str,
    selected_actions: Sequence[Mapping[str, Any]],
    neutral_patterns: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if condition not in STRICT_DIRECT_BR_CONDITIONS:
        return {
            "br_contract_mode": "not_required",
            "br_usage_ok": None,
            "br_usage_failures": [],
        }

    direct_plan_actions = [
        action for action in selected_actions if _is_direct_mcp_tool(action, "plan_preflight")
    ]
    failures: list[str] = []
    if not direct_plan_actions:
        failures.append("missing_direct_plan_preflight")
    elif not any(_plan_preflight_selection_mode(action) for action in direct_plan_actions):
        failures.append("plan_preflight_missing_selection_mode_true")

    first_plan_index = min(
        (int(action.get("index") or 0) for action in direct_plan_actions),
        default=None,
    )
    direct_route_actions = [
        action
        for action in selected_actions
        if _is_direct_concrete_br_route(action)
        and (first_plan_index is None or int(action.get("index") or 0) > first_plan_index)
    ]
    if not direct_route_actions:
        failures.append("missing_direct_concrete_br_route_after_plan_preflight")

    first_route_index = min(
        (int(action.get("index") or 0) for action in direct_route_actions),
        default=None,
    )
    if first_route_index is not None:
        for action in selected_actions:
            action_index = int(action.get("index") or 0)
            if action_index >= first_route_index:
                continue
            if _neutral_pattern_label(action, neutral_patterns) is not None:
                continue
            if not _is_direct_mcp_source(action):
                failures.append("local_or_wrapper_action_before_direct_br_route")
                break

    return {
        "br_contract_mode": "strict_direct_br_v1",
        "br_usage_ok": not failures,
        "br_usage_failures": failures,
        "br_direct_plan_preflight_count": len(direct_plan_actions),
        "br_direct_concrete_route_count": len(direct_route_actions),
    }


def _value_at_dotted_path(payload: Mapping[str, Any], path: str) -> Any:
    cursor: Any = payload
    for key in path.split("."):
        if not isinstance(cursor, Mapping):
            return None
        cursor = cursor.get(key)
    return cursor


def _input_constraint_matches(action: Mapping[str, Any], constraint: Mapping[str, Any]) -> bool:
    path = _string(constraint.get("path"))
    if not path:
        return False
    value = _value_at_dotted_path(_input_from_action(action), path)
    if "equals" in constraint:
        return value == constraint.get("equals")
    if "contains" in constraint:
        return _string(constraint.get("contains")).lower() in _string(value).lower()
    return value is not None


def _pattern_constraints_match(action: Mapping[str, Any], pattern: Mapping[str, Any]) -> bool:
    required = [
        item for item in _as_list(pattern.get("requires_input")) if isinstance(item, Mapping)
    ]
    if required and not all(_input_constraint_matches(action, item) for item in required):
        return False
    required_any = [
        item
        for item in _as_list(pattern.get("requires_any_input"))
        if isinstance(item, Mapping)
    ]
    if required_any and not any(
        _input_constraint_matches(action, item) for item in required_any
    ):
        return False
    return True


def _pattern_matches(action: Mapping[str, Any], pattern: Mapping[str, Any]) -> bool:
    action_type = _string(action.get("action_type"))
    if not _matches_action_type(action_type, _string(pattern.get("action_type"))):
        return False
    target = _string(action.get("target"))
    needle = _string(pattern.get("pattern"))
    match = _string(pattern.get("match")) or "contains"
    if not target or not needle:
        return False
    if match == "exact":
        return target == needle and _pattern_constraints_match(action, pattern)
    if match == "regex":
        return re.search(needle, target) is not None and _pattern_constraints_match(
            action, pattern
        )
    return needle.lower() in target.lower() and _pattern_constraints_match(
        action, pattern
    )


def _acceptable_patterns(task: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    patterns = [
        p for p in _as_list(task.get("acceptable_patterns")) if isinstance(p, Mapping)
    ]
    task_id = _string(task.get("task_id"))
    patterns.extend(SCORE_TEMPLATE_REPAIR_PATTERNS.get(task_id, []))
    return patterns


def _raw_command_from_action(action: Mapping[str, Any]) -> str:
    raw = action.get("raw")
    if not isinstance(raw, Mapping):
        return ""
    return _command_from_payload(raw) or _command_from_arguments(_arguments_from_payload(raw))


def _looks_like_environment_probe(command: str) -> bool:
    if not command:
        return False
    if re.search(
        r"\b(importlib\.util\.find_spec|shutil\.which|pip\s+show|which\s+|command\s+-v)\b",
        command,
    ):
        return True
    if re.search(r"\b[\w.-]+\s+(?:--version|--help|-V|-h)\b", command):
        return True
    return (
        re.search(
            r"python(?:\d(?:\.\d+)?)?\s+-c\s+(['\"])\s*(?:from\s+[\w.]+\s+import\s+[\w.,\s*]+|import\s+[\w.,\s]+)\s*\1",
            command,
        )
        is not None
    )


def _is_default_neutral_action(action: Mapping[str, Any]) -> bool:
    action_type = _string(action.get("action_type"))
    target = _string(action.get("target"))
    target_lower = target.lower()
    raw_command = _raw_command_from_action(action)
    # Env-probe propagation: only neutralize bash_cmd actions whose underlying
    # command looks like a probe. The derived py_import / py_call entries
    # parsed from the same `python -c "..."` command still carry the agent's
    # route commitment (the target library / symbol they imported), so they
    # must remain capability-bearing. Filtering them too penalizes Claude's
    # concise `python -c "from X import Y"` style without rewarding any real
    # commitment difference vs. heredoc styles like Codex's.
    if (
        raw_command
        and _looks_like_environment_probe(raw_command)
        and action_type not in {"py_import", "py_call", "recipe_tool"}
    ):
        return True
    if action_type == "mcp_tool" and target in {
        "tool_search",
        "plan_preflight",
        "get_execution_recipe",
    }:
        return True
    if action_type == "agent_tool" and target in {"ToolSearch", "tool_search"}:
        return True
    if action_type == "bash_cmd":
        if _looks_like_environment_probe(target):
            return True
        return (
            re.match(
                r"\s*(?:/bin/bash\s+-lc\s+)?[\"']?\s*(?:ls|find|rg|grep|ag|fd)\b",
                target_lower,
            )
            is not None
        )
    if action_type == "py_call" and target in {
        "importlib.util.find_spec",
        "shutil.which",
        "print",
        "help",
    }:
        return True
    if action_type == "py_import" and target in {"importlib", "importlib.util", "shutil"}:
        return True
    return False


def _neutral_pattern_label(
    action: Mapping[str, Any],
    neutral_patterns: Sequence[Mapping[str, Any]],
) -> str | None:
    pattern = next(
        (item for item in neutral_patterns if _pattern_matches(action, item)),
        None,
    )
    if pattern is not None:
        return _string(pattern.get("pattern")) or "__neutral_pattern__"
    if _is_default_neutral_action(action):
        return "__default_neutral__"
    return None


def _task_actions(
    actions: Sequence[Mapping[str, Any]],
    task_id: str,
    max_actions: int,
    neutral_patterns: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    ordered = [
        action
        for action in actions
        if action.get("task_id") in {None, task_id}
        and _string(action.get("target"))
    ]
    ordered.sort(key=lambda action: int(action.get("index") or 0))

    selected: list[Mapping[str, Any]] = []
    budget_groups_seen: set[int] = set()
    for action in ordered:
        if _neutral_pattern_label(action, neutral_patterns) is not None:
            selected.append(action)
            continue
        budget_group = int(action.get("budget_group") or action.get("index") or 0)
        new_budget_group = budget_group not in budget_groups_seen
        if new_budget_group and len(budget_groups_seen) >= max_actions:
            break
        selected.append(action)
        if new_budget_group:
            budget_groups_seen.add(budget_group)
    return selected


def count_non_neutral_task_actions(
    task: Mapping[str, Any],
    actions: Sequence[Mapping[str, Any]],
) -> int:
    task_id = _string(task.get("task_id"))
    neutral_patterns = [p for p in _as_list(task.get("neutral_patterns")) if isinstance(p, Mapping)]
    ordered = [
        action
        for action in actions
        if action.get("task_id") in {None, task_id}
        and _string(action.get("target"))
    ]
    budget_groups: set[int] = set()
    for action in ordered:
        if _neutral_pattern_label(action, neutral_patterns) is not None:
            continue
        budget_groups.add(int(action.get("budget_group") or action.get("index") or 0))
    return len(budget_groups)


def _path_matches_actions(
    actions: Sequence[Mapping[str, Any]],
    patterns: Sequence[Mapping[str, Any]],
) -> tuple[bool, list[dict[str, Any]]]:
    if not patterns:
        return False, []
    evidence: list[dict[str, Any]] = []
    cursor = 0
    for pattern in patterns:
        match: Mapping[str, Any] | None = None
        for index in range(cursor, len(actions)):
            action = actions[index]
            if _pattern_matches(action, pattern):
                match = action
                cursor = index + 1
                break
        if match is None:
            return False, []
        evidence.append(
            {
                "action_index": match.get("index"),
                "action_type": match.get("action_type"),
                "target": match.get("target"),
                "pattern": pattern.get("pattern"),
            }
        )
    return True, evidence


def _canonical_routing_paths(task: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return explicit routing paths plus inferred workflow recipe paths."""

    paths = [
        p
        for p in _as_list(task.get("canonical_routing_paths"))
        if isinstance(p, Mapping)
    ]
    existing_path_ids = {_string(path.get("path_id")) for path in paths}
    for tool_id in {_string(item) for item in _as_list(task.get("canonical_br_tools"))}:
        if not tool_id.startswith("workflow_"):
            continue
        path_id = f"br_recipe_{tool_id}"
        if path_id in existing_path_ids:
            continue
        paths.append(
            {
                "path_id": path_id,
                "description": f"Select the BR workflow recipe route for {tool_id}.",
                "patterns": [
                    {
                        "action_type": "recipe_tool",
                        "pattern": tool_id,
                        "match": "exact",
                    }
                ],
            }
        )
    return paths


def _jsonish_text(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _action_text_blob(action: Mapping[str, Any]) -> str:
    return " ".join(
        part
        for part in (
            _string(action.get("action_type")),
            _string(action.get("target")),
            _string(action.get("source")),
            _jsonish_text(action.get("raw")),
            _jsonish_text(_input_from_action(action)),
        )
        if part
    ).lower()


def _actions_text_blob(actions: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(_action_text_blob(action) for action in actions)


def _drop_meta_text(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _drop_meta_text(item)
            for key, item in value.items()
            if _string(key) not in META_PARAM_KEYS
        }
    if isinstance(value, list):
        return [_drop_meta_text(item) for item in value]
    return value


def _action_trace_blob(action: Mapping[str, Any]) -> str:
    return " ".join(
        part
        for part in (
            _string(action.get("action_type")),
            _string(action.get("target")),
            _string(action.get("source")),
            _jsonish_text(_drop_meta_text(action.get("raw"))),
            _jsonish_text(_drop_meta_text(_input_from_action(action))),
        )
        if part
    ).lower()


def _has_any_text(blob: str, needles: Sequence[str]) -> bool:
    return any(needle.lower() in blob for needle in needles if needle)


def _task_requires_dataset(task: Mapping[str, Any], required: Sequence[str]) -> bool:
    task_id = _string(task.get("task_id"))
    query = _string(task.get("query")).lower()
    if task_id in EXECUTION_HANDOFF_DATASET_HINTS:
        return True
    if "dataset_access" in set(required):
        return True
    return any(token in query for token in ("dataset", "haxby", "adhd", "abide", "openneuro"))


def _dataset_bound(actions: Sequence[Mapping[str, Any]], task: Mapping[str, Any]) -> bool:
    blob = "\n".join(_action_trace_blob(action) for action in actions)
    if re.search(r"\b(dataset_get_resources|openneuro|fetch_[a-z0-9_]+|bids_dir|bids-dir)\b", blob):
        return True
    return False


def _routing_only_value(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() == "routing_only"
    return False


def _contains_routing_only_marker(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_s = _string(key)
            if key_s in ROUTING_ONLY_PARAM_KEYS and _routing_only_value(item):
                return True
            if _contains_routing_only_marker(item):
                return True
    elif isinstance(value, list):
        return any(_contains_routing_only_marker(item) for item in value)
    return False


def _extract_params_from_input(input_payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    params = input_payload.get("params")
    if isinstance(params, Mapping):
        return params
    params_json = input_payload.get("params_json")
    if isinstance(params_json, Mapping):
        return params_json
    if any(key in input_payload for key in ("img", "bids_dir", "output_dir", "events", "atlas")):
        return input_payload
    return None


def _has_scientific_params(params: Mapping[str, Any] | None) -> bool:
    if not params:
        return False
    for key, value in params.items():
        key_s = _string(key)
        if key_s in META_PARAM_KEYS:
            continue
        if value in (None, "", [], {}):
            continue
        return True
    return False


def _recipe_actions(actions: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [action for action in actions if action.get("action_type") == "recipe_tool"]


def _recipe_params_status(
    actions: Sequence[Mapping[str, Any]],
) -> tuple[bool, bool, list[dict[str, Any]]]:
    recipe_actions = _recipe_actions(actions)
    if not recipe_actions:
        return False, True, []
    evidence: list[dict[str, Any]] = []
    for action in recipe_actions:
        input_payload = _input_from_action(action)
        params = _extract_params_from_input(input_payload)
        has_params = _has_scientific_params(params)
        routing_only = _contains_routing_only_marker(input_payload) or _contains_routing_only_marker(params)
        evidence.append(
            {
                "action_index": action.get("index"),
                "target": action.get("target"),
                "has_scientific_params": has_params,
                "routing_only": routing_only,
            }
        )
        if has_params and not routing_only:
            return True, True, evidence
    return True, False, evidence


def _single_action_covers_all_capabilities(
    covered: Mapping[str, Sequence[Mapping[str, Any]]],
    required: Sequence[str],
) -> bool:
    if not required:
        return False
    action_keys: set[tuple[Any, Any]] | None = None
    for capability in required:
        keys = {
            (hit.get("action_index"), hit.get("target"))
            for hit in covered.get(capability, [])
            if hit.get("action_index") is not None
        }
        if action_keys is None:
            action_keys = keys
        else:
            action_keys &= keys
    return bool(action_keys)


def _non_neutral_action_count(
    actions: Sequence[Mapping[str, Any]],
    neutral_patterns: Sequence[Mapping[str, Any]],
) -> int:
    groups = {
        int(action.get("budget_group") or action.get("index") or 0)
        for action in actions
        if _neutral_pattern_label(action, neutral_patterns) is None
    }
    return len(groups)


def _gate(
    gates: list[dict[str, Any]],
    *,
    name: str,
    applicable: bool,
    passed: bool,
    reason: str = "",
    evidence: Any = None,
) -> None:
    item: dict[str, Any] = {
        "gate": name,
        "applicable": applicable,
        "passed": (passed if applicable else None),
    }
    if reason:
        item["reason"] = reason
    if evidence is not None:
        item["evidence"] = evidence
    gates.append(item)


def _execution_handoff_v1(
    *,
    task: Mapping[str, Any],
    selected_actions: Sequence[Mapping[str, Any]],
    required: Sequence[str],
    missing: Sequence[str],
    covered: Mapping[str, Sequence[Mapping[str, Any]]],
    neutral_patterns: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    task_id = _string(task.get("task_id"))
    gates: list[dict[str, Any]] = []
    blob = _actions_text_blob(selected_actions)

    _gate(
        gates,
        name="capability_coverage",
        applicable=True,
        passed=not missing,
        reason="all required capabilities must be covered",
        evidence={"missing_capabilities": list(missing)},
    )

    recipe_present, recipe_params_ok, recipe_evidence = _recipe_params_status(selected_actions)
    _gate(
        gates,
        name="recipe_params_populated",
        applicable=recipe_present,
        passed=recipe_params_ok,
        reason="recipe selections must include non-empty scientific params and must not be routing_only/no_download/no_heavy_execution",
        evidence=recipe_evidence,
    )

    dataset_required = _task_requires_dataset(task, required)
    _gate(
        gates,
        name="dataset_binding",
        applicable=dataset_required,
        passed=_dataset_bound(selected_actions, task),
        reason="dataset tasks must bind or explicitly resolve a dataset before handoff",
    )

    hints = EXECUTION_HANDOFF_DATASET_HINTS.get(task_id, {})
    forbidden_dataset_hits = [
        item for item in hints.get("forbidden", ()) if item.lower() in blob
    ]
    _gate(
        gates,
        name="dataset_not_mismatched",
        applicable=bool(hints.get("forbidden")),
        passed=not forbidden_dataset_hits,
        reason="dataset aliases/defaults must not contradict the requested dataset",
        evidence={"forbidden_hits": forbidden_dataset_hits},
    )

    for gate_name, needles in EXECUTION_HANDOFF_REQUIRED_TEXT_GATES.get(task_id, {}).items():
        _gate(
            gates,
            name=gate_name,
            applicable=True,
            passed=_has_any_text(blob, needles),
            reason=f"task handoff requires one of: {', '.join(needles)}",
        )

    forbidden_text_hits = [
        item
        for item in EXECUTION_HANDOFF_FORBIDDEN_TEXT.get(task_id, ())
        if item.lower() in blob
    ]
    _gate(
        gates,
        name="no_query_contradiction",
        applicable=bool(EXECUTION_HANDOFF_FORBIDDEN_TEXT.get(task_id)),
        passed=not forbidden_text_hits,
        reason="handoff must not include command flags that contradict the task",
        evidence={"forbidden_hits": forbidden_text_hits},
    )

    plan_indices = [
        int(action.get("index") or 0)
        for action in selected_actions
        if action.get("action_type") == "mcp_tool" and action.get("target") == "plan_preflight"
    ]
    concrete_after_plan = True
    if plan_indices:
        first_plan = min(plan_indices)
        concrete_after_plan = any(
            int(action.get("index") or 0) > first_plan
            and (
                action.get("action_type") == "recipe_tool"
                or (
                    action.get("action_type") == "mcp_tool"
                    and _string(action.get("target")) not in GENERIC_BR_ROUTE_TOOLS
                )
            )
            for action in selected_actions
        )
    _gate(
        gates,
        name="plan_followed_by_concrete_route",
        applicable=bool(plan_indices),
        passed=concrete_after_plan,
        reason="plan_preflight must be followed by a concrete recommended route",
    )

    unknown_tool_seen = "unknown_tool" in blob
    _gate(
        gates,
        name="no_unknown_tool_terminal_error",
        applicable=True,
        passed=not unknown_tool_seen,
        reason="unknown_tool must be recovered from or reported as a blocking failure",
    )

    non_neutral_count = _non_neutral_action_count(selected_actions, neutral_patterns)
    workflow_recipe = any(
        _string(action.get("target")).startswith("workflow_")
        for action in _recipe_actions(selected_actions)
    )
    single_action_complete = _single_action_covers_all_capabilities(covered, required)
    needs_depth = len(required) > 1 and not workflow_recipe and not single_action_complete
    _gate(
        gates,
        name="multi_step_followthrough",
        applicable=needs_depth,
        passed=non_neutral_count >= 2,
        reason="multi-capability tasks need more than a single primitive unless a workflow recipe covers the stack",
        evidence={"non_neutral_action_count": non_neutral_count},
    )

    applicable = [gate for gate in gates if gate["applicable"]]
    passed = [gate for gate in applicable if gate["passed"]]
    failures = [gate["gate"] for gate in applicable if not gate["passed"]]
    return {
        "execution_handoff_contract": EXECUTION_HANDOFF_CONTRACT,
        "execution_handoff_ok": bool(applicable) and len(passed) == len(applicable),
        "execution_handoff_score": (
            len(passed) / len(applicable) if applicable else None
        ),
        "execution_handoff_failures": failures,
        "execution_handoff_gates": gates,
    }


def _trace_call_hit(
    actions: Sequence[Mapping[str, Any]],
    call_spec: Mapping[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    text_needles = tuple(_string(item) for item in _as_list(call_spec.get("text_any")))
    for action in actions:
        blob = _action_trace_blob(action)
        if text_needles and _has_any_text(blob, text_needles):
            evidence.append(
                {
                    "action_index": action.get("index"),
                    "action_type": action.get("action_type"),
                    "target": action.get("target"),
                    "match": "text_any",
                }
            )
            return True, evidence
        for pattern in _as_list(call_spec.get("patterns")):
            if isinstance(pattern, Mapping) and _pattern_matches(action, pattern):
                evidence.append(
                    {
                        "action_index": action.get("index"),
                        "action_type": action.get("action_type"),
                        "target": action.get("target"),
                        "match": pattern.get("pattern"),
                    }
                )
                return True, evidence
    return False, evidence


def _duplicate_route_count(actions: Sequence[Mapping[str, Any]]) -> int:
    seen: set[tuple[str, str, str]] = set()
    duplicates = 0
    for action in actions:
        key = (
            _string(action.get("action_type")),
            _string(action.get("target")),
            _jsonish_text(_input_from_action(action)),
        )
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
    return duplicates


def _unknown_tool_recovered(
    actions: Sequence[Mapping[str, Any]],
    neutral_patterns: Sequence[Mapping[str, Any]],
) -> bool:
    first_unknown: int | None = None
    for action in actions:
        if "unknown_tool" in _action_text_blob(action):
            first_unknown = int(action.get("index") or 0)
            break
    if first_unknown is None:
        return True
    for action in actions:
        if int(action.get("index") or 0) <= first_unknown:
            continue
        if _neutral_pattern_label(action, neutral_patterns) is not None:
            continue
        action_type = _string(action.get("action_type"))
        target = _string(action.get("target"))
        if action_type == "recipe_tool":
            return True
        if action_type == "mcp_tool" and target not in GENERIC_BR_ROUTE_TOOLS:
            return True
        if action_type in {"bash_cmd", "py_import", "py_call", "plan_tool"}:
            return True
    return False


def _trace_oracle_v1(
    *,
    task: Mapping[str, Any],
    selected_actions: Sequence[Mapping[str, Any]],
    neutral_patterns: Sequence[Mapping[str, Any]],
    execution_handoff: Mapping[str, Any],
) -> dict[str, Any]:
    task_id = _string(task.get("task_id"))
    spec = TRACE_ORACLE_SPECS.get(task_id, {})
    required_calls = [
        call for call in _as_list(spec.get("required_calls")) if isinstance(call, Mapping)
    ]
    required_hits: list[str] = []
    required_missing: list[str] = []
    required_evidence: dict[str, list[dict[str, Any]]] = {}
    for call in required_calls:
        call_id = _string(call.get("id"))
        hit, evidence = _trace_call_hit(selected_actions, call)
        if hit:
            required_hits.append(call_id)
            required_evidence[call_id] = evidence
        else:
            required_missing.append(call_id)

    optional_calls = [
        call for call in _as_list(spec.get("optional_calls")) if isinstance(call, Mapping)
    ]
    optional_hits: list[str] = []
    for call in optional_calls:
        call_id = _string(call.get("id"))
        hit, _ = _trace_call_hit(selected_actions, call)
        if hit:
            optional_hits.append(call_id)

    blob = _actions_text_blob(selected_actions)
    recipe_present, recipe_params_ok, _ = _recipe_params_status(selected_actions)
    dataset_required = _task_requires_dataset(task, _as_list(task.get("required_capabilities")))
    dataset_bound = _dataset_bound(selected_actions, task)
    duplicate_count = _duplicate_route_count(selected_actions)
    failures: list[str] = []

    if required_missing:
        failures.append("CRITICAL_NEXT_CALL_SKIPPED")
    if dataset_required and not dataset_bound:
        failures.append("DATASET_NOT_RESOLVED")
    if "dataset_not_mismatched" in execution_handoff.get("execution_handoff_failures", []):
        failures.append("WRONG_DATASET_CANONICALIZATION")
    if recipe_present and not recipe_params_ok:
        failures.append("RECIPE_ONLY_NO_PARAMS")
    if "routing_only" in blob:
        failures.append("ROUTING_ONLY_TERMINAL")
    if not _unknown_tool_recovered(selected_actions, neutral_patterns):
        failures.append("UNKNOWN_TOOL_NO_FALLBACK")
    if "no_query_contradiction" in execution_handoff.get("execution_handoff_failures", []):
        failures.append("TEMPLATE_PARAMETER_MISMATCH")
    if duplicate_count:
        failures.append("DUPLICATE_TOOL_CALLS")

    terminal_tools = tuple(_string(item) for item in _as_list(spec.get("terminal_tools")))
    terminal_seen = any(
        _string(action.get("target")) in terminal_tools for action in selected_actions
    )
    if terminal_seen and required_missing:
        failures.append("TERMINAL_TOOL_BEFORE_UPSTREAM")

    oversold_tokens = ("pass", "complete", "runnable", "success")
    if (
        failures
        and _has_any_text(blob, oversold_tokens)
        and not _has_any_text(blob, ("blocked", "partial", "missing", "not runnable", "fail"))
    ):
        failures.append("FINAL_STATUS_OVERSOLD")

    unique_failures = list(dict.fromkeys(failures))
    return {
        "trace_oracle_contract": TRACE_ORACLE_CONTRACT,
        "trace_required_call_count": len(required_calls),
        "trace_required_calls_hit": required_hits,
        "trace_required_calls_missing": required_missing,
        "trace_required_call_coverage": (
            len(required_hits) / len(required_calls) if required_calls else None
        ),
        "trace_optional_call_count": len(optional_calls),
        "trace_optional_calls_hit": optional_hits,
        "duplicate_route_call_count": duplicate_count,
        "failure_mode_labels": unique_failures,
        "failure_mode_count": len(unique_failures),
        "trace_required_call_evidence": required_evidence,
    }


def score_task(
    task: Mapping[str, Any],
    actions: Sequence[Mapping[str, Any]],
    *,
    condition: str,
    max_actions: int,
) -> dict[str, Any]:
    task_id = _string(task.get("task_id"))
    acceptable = _acceptable_patterns(task)
    disqualifying = [
        p for p in _as_list(task.get("disqualifying_patterns")) if isinstance(p, Mapping)
    ]
    neutral_patterns = [p for p in _as_list(task.get("neutral_patterns")) if isinstance(p, Mapping)]
    selected_actions = _task_actions(actions, task_id, max_actions, neutral_patterns)
    routing_paths = _canonical_routing_paths(task)
    required = [_string(item) for item in _as_list(task.get("required_capabilities"))]
    canonical = {_string(item) for item in _as_list(task.get("canonical_br_tools"))}

    covered: dict[str, list[dict[str, Any]]] = {capability: [] for capability in required}
    potential_trap_hits: list[dict[str, Any]] = []
    neutral_actions: list[dict[str, Any]] = []
    first_relevant_index: int | None = None
    first_relevant_global_index: int | None = None
    budget_group_ordinals: dict[int, int] = {}
    for action in selected_actions:
        neutral_label = _neutral_pattern_label(action, neutral_patterns)
        if neutral_label is not None:
            neutral_actions.append(
                {
                    "action_index": action.get("index"),
                    "action_type": action.get("action_type"),
                    "target": action.get("target"),
                    "pattern": neutral_label,
                }
            )
            continue
        budget_group = int(action.get("budget_group") or action.get("index") or 0)
        if budget_group not in budget_group_ordinals:
            budget_group_ordinals[budget_group] = len(budget_group_ordinals) + 1
        non_neutral_index = budget_group_ordinals[budget_group]
        matched_any = False
        for pattern in acceptable:
            capability = _string(pattern.get("capability"))
            if capability in covered and _pattern_matches(action, pattern):
                covered[capability].append(
                    {
                        "action_index": action.get("index"),
                        "action_type": action.get("action_type"),
                        "target": action.get("target"),
                        "pattern": pattern.get("pattern"),
                    }
                )
                matched_any = True
        for pattern in disqualifying:
            if _pattern_matches(action, pattern):
                potential_trap_hits.append(
                    {
                        "action_index": action.get("index"),
                        "action_type": action.get("action_type"),
                        "target": action.get("target"),
                        "trap_id": pattern.get("trap_id"),
                        "reason": pattern.get("reason"),
                        "requires_missing_capabilities": pattern.get(
                            "requires_missing_capabilities"
                        )
                        or pattern.get("only_if_missing_capabilities")
                        or [],
                    }
                )
                matched_any = True
        if matched_any and first_relevant_index is None:
            first_relevant_index = non_neutral_index
            first_relevant_global_index = int(action.get("index") or 0)

    missing = [capability for capability, hits in covered.items() if not hits]
    missing_set = set(missing)
    trap_hits = []
    for hit in potential_trap_hits:
        gated_by = [
            _string(item)
            for item in _as_list(hit.get("requires_missing_capabilities"))
            if _string(item)
        ]
        if gated_by and not (missing_set & set(gated_by)):
            continue
        trap_hits.append(hit)
    canonical_hit = any(
        _string(action.get("target")) in canonical
        and action.get("action_type") in {"plan_tool", "mcp_tool", "recipe_tool"}
        for action in selected_actions
    )
    canonical_routing_path_hits: list[dict[str, Any]] = []
    for path in routing_paths:
        patterns = [p for p in _as_list(path.get("patterns")) if isinstance(p, Mapping)]
        matched, evidence = _path_matches_actions(selected_actions, patterns)
        if matched:
            canonical_routing_path_hits.append(
                {
                    "path_id": path.get("path_id"),
                    "description": path.get("description"),
                    "evidence": evidence,
                }
            )
    br_contract = _strict_br_contract(
        condition=condition,
        selected_actions=selected_actions,
        neutral_patterns=neutral_patterns,
    )
    strict_br_ok = br_contract.get("br_usage_ok")
    if strict_br_ok is False:
        canonical_hit = False
        canonical_routing_path_hits = []
    execution_handoff = _execution_handoff_v1(
        task=task,
        selected_actions=selected_actions,
        required=required,
        missing=missing,
        covered=covered,
        neutral_patterns=neutral_patterns,
    )
    trace_oracle = _trace_oracle_v1(
        task=task,
        selected_actions=selected_actions,
        neutral_patterns=neutral_patterns,
        execution_handoff=execution_handoff,
    )
    n_required_capabilities = len(required)
    n_capabilities_covered = len(required) - len(missing)
    capability_score = (
        n_capabilities_covered / n_required_capabilities
        if n_required_capabilities
        else None
    )
    ungated_capability_score = capability_score
    if strict_br_ok is False and capability_score is not None:
        capability_score = 0.0
    parse_confidences = [
        float(action.get("confidence") or 0.0) for action in selected_actions
    ]
    parse_confidence = min(parse_confidences) if parse_confidences else 0.0
    no_actions = not selected_actions
    needs_human_adjudication = no_actions or parse_confidence < 0.7
    correct = (
        bool(required)
        and not missing
        and not trap_hits
        and not needs_human_adjudication
        and strict_br_ok is not False
    )

    return {
        "condition": condition,
        "task_id": task_id,
        "query": task.get("query"),
        "category": task.get("category"),
        "template_id": task.get("template_id"),
        "max_actions": max_actions,
        "action_budget_unit": "non_neutral_actions",
        "selected_actions": [
            {
                key: action.get(key)
                for key in (
                    "index",
                    "budget_group",
                    "action_type",
                    "target",
                    "task_id",
                    "source",
                    "confidence",
                )
            }
            for action in selected_actions
        ],
        "n_selected_non_neutral_actions": len(budget_group_ordinals),
        "first_task_relevant_action_index": first_relevant_index,
        "first_task_relevant_global_action_index": first_relevant_global_index,
        "required_capabilities": required,
        "n_required_capabilities": n_required_capabilities,
        "n_capabilities_covered": n_capabilities_covered,
        "capability_score": capability_score,
        "ungated_capability_score": ungated_capability_score,
        "capabilities_covered": sorted(
            capability for capability, hits in covered.items() if hits
        ),
        "capability_evidence": covered,
        "missing_capabilities": missing,
        "neutral_actions": neutral_actions,
        "trap_hits": trap_hits,
        "trap_fall": bool(trap_hits),
        "canonical_tool_hit": canonical_hit,
        "canonical_routing_path_applicable": bool(routing_paths),
        "used_canonical_routing_path": bool(canonical_routing_path_hits),
        "canonical_routing_path_hits": canonical_routing_path_hits,
        **br_contract,
        **execution_handoff,
        **trace_oracle,
        "correct": correct,
        "no_action": no_actions,
        "parse_confidence": parse_confidence,
        "needs_human_adjudication": needs_human_adjudication,
    }


def summarize_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_condition[_string(row.get("condition"))].append(row)

    summary: dict[str, Any] = {}
    for condition, condition_rows in sorted(by_condition.items()):
        n = len(condition_rows)
        relevant = [
            row.get("first_task_relevant_action_index")
            for row in condition_rows
            if isinstance(row.get("first_task_relevant_action_index"), int)
        ]
        br_required_rows = [
            row for row in condition_rows if row.get("br_usage_ok") is not None
        ]
        handoff_rows = [
            row for row in condition_rows if isinstance(row.get("execution_handoff_ok"), bool)
        ]
        capability_scores = [
            float(row["capability_score"])
            for row in condition_rows
            if isinstance(row.get("capability_score"), int | float)
        ]
        ungated_capability_scores = [
            float(row["ungated_capability_score"])
            for row in condition_rows
            if isinstance(row.get("ungated_capability_score"), int | float)
        ]
        execution_handoff_scores = [
            float(row["execution_handoff_score"])
            for row in condition_rows
            if isinstance(row.get("execution_handoff_score"), int | float)
        ]
        trace_required_call_coverages = [
            float(row["trace_required_call_coverage"])
            for row in condition_rows
            if isinstance(row.get("trace_required_call_coverage"), int | float)
        ]
        capability_counts = [
            int(row["n_capabilities_covered"])
            for row in condition_rows
            if isinstance(row.get("n_capabilities_covered"), int)
        ]
        routing_applicable_rows = [
            row for row in condition_rows if row.get("canonical_routing_path_applicable")
        ]
        summary[condition] = {
            "n_tasks": n,
            "tool_selection_accuracy": _rate(
                sum(1 for row in condition_rows if row.get("correct")),
                n,
            ),
            "mean_capability_score": (
                sum(capability_scores) / len(capability_scores)
                if capability_scores
                else None
            ),
            "mean_ungated_capability_score": (
                sum(ungated_capability_scores) / len(ungated_capability_scores)
                if ungated_capability_scores
                else None
            ),
            "execution_handoff_contract": EXECUTION_HANDOFF_CONTRACT,
            "execution_handoff_ok_rate": _rate(
                sum(1 for row in handoff_rows if row.get("execution_handoff_ok")),
                len(handoff_rows),
            ),
            "mean_execution_handoff_score": (
                sum(execution_handoff_scores) / len(execution_handoff_scores)
                if execution_handoff_scores
                else None
            ),
            "trace_oracle_contract": TRACE_ORACLE_CONTRACT,
            "mean_trace_required_call_coverage": (
                sum(trace_required_call_coverages) / len(trace_required_call_coverages)
                if trace_required_call_coverages
                else None
            ),
            "mean_capabilities_covered": (
                sum(capability_counts) / len(capability_counts)
                if capability_counts
                else None
            ),
            "canonical_tool_hit_rate": _rate(
                sum(1 for row in condition_rows if row.get("canonical_tool_hit")),
                n,
            ),
            "canonical_routing_path_applicable_count": len(routing_applicable_rows),
            "canonical_routing_path_rate": _rate(
                sum(1 for row in routing_applicable_rows if row.get("used_canonical_routing_path")),
                len(routing_applicable_rows),
            ),
            "trap_fall_rate": _rate(sum(1 for row in condition_rows if row.get("trap_fall")), n),
            "no_action_rate": _rate(sum(1 for row in condition_rows if row.get("no_action")), n),
            "human_adjudication_rate": _rate(
                sum(1 for row in condition_rows if row.get("needs_human_adjudication")),
                n,
            ),
            "br_usage_ok_rate": _rate(
                sum(1 for row in br_required_rows if row.get("br_usage_ok")),
                len(br_required_rows),
            ),
            "mean_first_task_relevant_action_index": (
                sum(relevant) / len(relevant) if relevant else None
            ),
            "wrong_or_incomplete_task_ids": [
                row.get("task_id") for row in condition_rows if not row.get("correct")
            ],
            "trap_task_ids": [
                row.get("task_id") for row in condition_rows if row.get("trap_fall")
            ],
            "execution_handoff_failed_task_ids": [
                row.get("task_id")
                for row in handoff_rows
                if row.get("execution_handoff_ok") is False
            ],
            "failure_mode_counts": dict(
                sorted(
                    {
                        label: sum(
                            1
                            for row in condition_rows
                            if label in _as_list(row.get("failure_mode_labels"))
                        )
                        for label in {
                            item
                            for row in condition_rows
                            for item in _as_list(row.get("failure_mode_labels"))
                        }
                    }.items()
                )
            ),
        }
    return summary


def _rate(numer: int, denom: int) -> float | None:
    return numer / denom if denom else None


def validate_parser(fixtures_path: Path) -> dict[str, Any]:
    rows = _read_jsonl(fixtures_path)
    fixture_results: list[dict[str, Any]] = []
    total_expected = 0
    total_actual = 0
    total_tp = 0
    for row in rows:
        expected = {
            (
                item.get("action_type"),
                item.get("target"),
                item.get("task_id"),
            )
            for item in _as_list(row.get("expected_actions"))
            if isinstance(item, Mapping)
        }
        actual_actions = parse_events(
            event for event in _as_list(row.get("events")) if isinstance(event, Mapping)
        )
        actual = {
            (
                action.get("action_type"),
                action.get("target"),
                action.get("task_id"),
            )
            for action in actual_actions
        }
        tp = len(expected & actual)
        total_expected += len(expected)
        total_actual += len(actual)
        total_tp += tp
        fixture_results.append(
            {
                "trace_id": row.get("trace_id"),
                "expected_count": len(expected),
                "actual_count": len(actual),
                "true_positive_count": tp,
                "missing": sorted(expected - actual),
                "extra": sorted(actual - expected),
                "passed": expected <= actual,
            }
        )
    return {
        "fixture_count": len(rows),
        "expected_action_count": total_expected,
        "actual_action_count": total_actual,
        "true_positive_count": total_tp,
        "precision": _rate(total_tp, total_actual),
        "recall": _rate(total_tp, total_expected),
        "all_fixtures_passed": all(item["passed"] for item in fixture_results),
        "fixtures": fixture_results,
    }


def _parse_condition_trace(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Use CONDITION=TRACE_JSONL")
    condition, path = value.split("=", 1)
    if not condition.strip():
        raise argparse.ArgumentTypeError("Condition cannot be empty")
    return condition.strip(), Path(path)


def run_pilot(
    *,
    tasks_path: Path,
    condition_traces: Sequence[tuple[str, Path]],
    parser_fixtures: Path,
    max_actions_values: Sequence[int],
) -> dict[str, Any]:
    tasks = load_tasks(tasks_path)
    parser_validation = validate_parser(parser_fixtures)
    rows: list[dict[str, Any]] = []
    trace_action_counts: dict[str, int] = {}
    for condition, trace_path in condition_traces:
        events = _read_jsonl(trace_path)
        actions = parse_events(events)
        trace_action_counts[condition] = len(actions)
        for max_actions in sorted(set(max_actions_values)):
            for task in tasks:
                rows.append(
                    score_task(
                        task,
                        actions,
                        condition=condition,
                        max_actions=max_actions,
                    )
                )

    primary_max_actions = min(max_actions_values, key=lambda value: abs(value - 3))
    primary_rows = [row for row in rows if row.get("max_actions") == primary_max_actions]
    scale_readiness = assess_scale_readiness(
        parser_validation=parser_validation,
        primary_rows=primary_rows,
        primary_max_actions=primary_max_actions,
    )
    return {
        "schema_version": "br.tool_selection_capability_pilot.results.v1",
        "tasks_path": str(tasks_path),
        "parser_fixtures": str(parser_fixtures),
        "condition_traces": {
            condition: str(path) for condition, path in condition_traces
        },
        "max_actions_values": sorted(set(max_actions_values)),
        "primary_max_actions": primary_max_actions,
        "n_tasks": len(tasks),
        "trace_action_counts": trace_action_counts,
        "parser_validation": parser_validation,
        "summary_by_max_actions": {
            str(max_actions): summarize_rows(
                [row for row in rows if row.get("max_actions") == max_actions]
            )
            for max_actions in sorted(set(max_actions_values))
        },
        "scale_readiness": scale_readiness,
        "rows": rows,
    }


def assess_scale_readiness(
    *,
    parser_validation: Mapping[str, Any],
    primary_rows: Sequence[Mapping[str, Any]],
    primary_max_actions: int,
) -> dict[str, Any]:
    precision = parser_validation.get("precision")
    recall = parser_validation.get("recall")
    parser_pass = bool(parser_validation.get("all_fixtures_passed")) and (
        isinstance(precision, float)
        and isinstance(recall, float)
        and precision >= 0.9
        and recall >= 0.9
    )
    adjudication_rate = _rate(
        sum(1 for row in primary_rows if row.get("needs_human_adjudication")),
        len(primary_rows),
    )
    trap_cases = [row.get("task_id") for row in primary_rows if row.get("trap_fall")]
    reasons: list[str] = []
    if parser_pass:
        reasons.append(
            "Parser validation passes on "
            f"{parser_validation.get('fixture_count')} trace-shaped fixtures."
        )
    else:
        reasons.append("Parser validation does not yet clear the 0.90 precision/recall gate.")
    if adjudication_rate == 0:
        reasons.append("No parsed pilot rows require human adjudication.")
    else:
        reasons.append(f"Human adjudication rate is {adjudication_rate:.3f}.")
    reasons.append(
        "Current checked-in pilot traces are Codex plan-output traces, not full shell/MCP interception traces."
    )
    if trap_cases:
        reasons.append(
            "Trap hits exist in the pilot and should be manually audited before scaling: "
            + ", ".join(sorted({str(task_id) for task_id in trap_cases}))
        )
    decision = (
        "limited_scale_plan_outputs_only"
        if parser_pass and adjudication_rate == 0
        else "do_not_scale"
    )
    return {
        "primary_max_actions": primary_max_actions,
        "decision": decision,
        "parser_gate_passed": parser_pass,
        "human_adjudication_rate": adjudication_rate,
        "reasons": reasons,
        "next_gate": (
            "Run 10 tasks x 2 systems x 2 conditions with real BR-off shell/Python "
            "and BR-on MCP traces, then manually adjudicate parser false positives "
            "and false negatives before scaling to hundreds of cases."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-jsonl", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--parser-fixtures-jsonl", type=Path, default=DEFAULT_PARSER_FIXTURES)
    parser.add_argument(
        "--condition-trace",
        action="append",
        type=_parse_condition_trace,
        default=[],
        help="Condition trace in CONDITION=TRACE_JSONL format. Defaults to existing Codex pilot traces.",
    )
    parser.add_argument("--max-actions", type=int, action="append", default=[3, 5])
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-rows-jsonl", type=Path, default=DEFAULT_OUT_ROWS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    condition_traces = args.condition_trace or list(DEFAULT_CONDITION_TRACES)
    payload = run_pilot(
        tasks_path=args.tasks_jsonl,
        condition_traces=condition_traces,
        parser_fixtures=args.parser_fixtures_jsonl,
        max_actions_values=args.max_actions,
    )
    rows = payload.pop("rows")
    _write_json(args.out_json, payload)
    _write_jsonl(args.out_rows_jsonl, rows)
    print(json.dumps(payload["scale_readiness"], indent=2, sort_keys=True))
    print(json.dumps(payload["summary_by_max_actions"].get(str(payload["primary_max_actions"])), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
