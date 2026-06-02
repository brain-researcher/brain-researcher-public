#!/usr/bin/env python3
"""Build manual adjudication packets for real-trace tool-selection runs.

The scorer reports parser-detected capability coverage. This packet adds a
separate, conservative "claimed capability" view from concrete tool/recipe
contracts so reviewers can distinguish parser/template gaps from real model
misses.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASKS = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "capability_pilot"
    / "microtooling_capability_pilot.v1.jsonl"
)
DEFAULT_RUN_DIR = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "capability_pilot"
    / "real_trace_runs"
    / "full_reachable_models_prod_br_20260504"
)

SYSTEM_LABELS = {
    "codex_cli_gpt55": "Codex CLI GPT-5.5",
    "claude_code_opus47": "Claude Opus 4.7",
    "opencode_gemini_pro": "Gemini Pro",
    "opencode_glm51": "GLM 5.1",
    "opencode_deepseek_v4_pro": "DeepSeek v4 Pro",
    "opencode_kimi_k25": "Kimi K2.5",
    "opencode_qwen36_plus": "Qwen 3.6 Plus",
}

FIELDNAMES = [
    "priority_rank",
    "review_priority",
    "adjudication_cluster_hint",
    "condition",
    "system",
    "br_mode",
    "task_id",
    "category",
    "query",
    "template_id",
    "required_capabilities",
    "parser_detected_capabilities",
    "capabilities_covered",
    "missing_capabilities",
    "claimed_capabilities_selected",
    "claimed_capabilities_all",
    "missing_but_claimed_selected",
    "missing_but_claimed_all",
    "claimed_not_parser_detected_selected",
    "claimed_not_parser_detected_all",
    "parser_detected_not_claimed_selected",
    "claim_source_tools_selected",
    "claim_source_tools_all",
    "claim_evidence_selected",
    "claim_evidence_all",
    "capability_score",
    "correct",
    "needs_human_adjudication",
    "no_action",
    "trap_fall",
    "canonical_tool_hit",
    "used_canonical_routing_path",
    "pair_capability_delta_with_minus_without",
    "status",
    "wall_time_s",
    "json_error_event",
    "parsed_action_count",
    "non_neutral_action_count",
    "action_summary",
    "all_action_summary",
    "response_preview",
    "prompt_path",
    "stdout_path",
    "parsed_actions_path",
    "record_path",
    "manual_decision",
    "manual_covered_capabilities",
    "manual_false_positive_capabilities",
    "manual_false_negative_capabilities",
    "manual_notes",
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _system_key(condition: str) -> str:
    for suffix in ("_without_br", "_with_br"):
        if condition.endswith(suffix):
            return condition.removesuffix(suffix)
    return condition


def _br_mode(condition: str) -> str:
    if condition.endswith("_with_br"):
        return "with_br"
    if condition.endswith("_without_br"):
        return "without_br"
    return "unknown"


def _display_system(condition: str) -> str:
    return SYSTEM_LABELS.get(_system_key(condition), _system_key(condition))


def _split_caps(value: Any) -> set[str]:
    if isinstance(value, str):
        return {item for item in value.split(";") if item}
    return {_string(item) for item in _as_list(value) if _string(item)}


def _join_caps(values: Iterable[str]) -> str:
    return ";".join(sorted({value for value in values if value}))


def _json_compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def load_tasks(path: Path) -> dict[str, dict[str, Any]]:
    return {row["task_id"]: row for row in read_jsonl(path)}


def selected_full_actions(
    score_row: Mapping[str, Any],
    parsed_actions: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    by_index = {
        int(action.get("index") or 0): action
        for action in parsed_actions
        if str(action.get("index") or "").strip()
    }
    out: list[Mapping[str, Any]] = []
    for action in _as_list(score_row.get("selected_actions")):
        if not isinstance(action, Mapping):
            continue
        index = int(action.get("index") or 0)
        out.append(by_index.get(index, action))
    return out


def _nested_mapping(value: Any, *path: str) -> Mapping[str, Any]:
    cursor = value
    for key in path:
        if not isinstance(cursor, Mapping):
            return {}
        cursor = cursor.get(key)
    return cursor if isinstance(cursor, Mapping) else {}


def action_input(action: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = action.get("raw")
    candidates = [
        raw.get("input") if isinstance(raw, Mapping) else None,
        _nested_mapping(raw, "state").get("input") if isinstance(raw, Mapping) else None,
        _nested_mapping(raw, "part", "state").get("input") if isinstance(raw, Mapping) else None,
        _nested_mapping(raw, "item", "input") if isinstance(raw, Mapping) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            return candidate
    return {}


def recipe_tool_id(action: Mapping[str, Any]) -> str:
    target = _string(action.get("target"))
    if action.get("action_type") == "recipe_tool" and target:
        return target
    payload = action_input(action)
    tool_id = _string(payload.get("tool_id"))
    if target == "get_execution_recipe" and tool_id:
        return tool_id
    return target


def recipe_params(action: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = action_input(action)
    params = payload.get("params")
    return params if isinstance(params, Mapping) else {}


def _target_contains(action: Mapping[str, Any], *patterns: str) -> bool:
    target = _string(action.get("target")).lower()
    return any(re.search(pattern, target, flags=re.IGNORECASE) for pattern in patterns)


def _is_python_shell_command(action: Mapping[str, Any]) -> bool:
    if action.get("action_type") != "bash_cmd":
        return False
    target = _string(action.get("target"))
    return (
        re.search(r"\bpython(?:\d+(?:\.\d+)?)?\s+(-c|-|<<)", target) is not None
        or re.search(r"<<\s*['\"]?PY", target) is not None
    )


def claimed_capability_evidence(
    action: Mapping[str, Any],
    required: set[str],
) -> list[dict[str, Any]]:
    action_type = _string(action.get("action_type"))
    target = _string(action.get("target"))
    tool_id = recipe_tool_id(action)
    params = recipe_params(action)
    claims: dict[str, str] = {}

    def claim(capability: str, reason: str) -> None:
        if capability in required:
            claims[capability] = reason

    contract_action = action_type in {"mcp_tool", "plan_tool", "recipe_tool"}
    if contract_action:
        if target == "dataset_get_resources" or tool_id in {
            "openneuro.get_dataset",
            "openneuro.search",
        }:
            claim("dataset_access", "dataset resource/discovery tool")

        if tool_id in {"validate_bids_structure", "query_bids_layout", "bids.list_subjects"}:
            claim("bids_validation", "BIDS validation/layout tool")

        if tool_id == "list_dataset_assets":
            claim("dataset_access", "dataset asset listing recipe")
            if params.get("validate_bids") is True or params.get("use_pybids_layout") is True:
                claim("bids_validation", "list_dataset_assets recipe requested BIDS validation")

        if tool_id in {"workflow_task_glm_group", "glm_first_level", "nilearn_first_level"}:
            claim("first_level_glm", "task GLM workflow contract")
            claim("hrf_modeling", "task GLM workflow contract")
            claim("contrast_estimation", "task GLM workflow contract")

        if tool_id in {"workflow_preprocessing_qc", "workflow_mriqc", "mriqc"}:
            claim("image_quality_metrics", "MRIQC/preprocessing QC workflow contract")
            claim("qc_reporting", "MRIQC/preprocessing QC workflow contract")

        if tool_id in {"workflow_fmriprep_preprocessing", "container_fmriprep", "fmriprep"}:
            claim("fmri_preprocessing", "fMRIPrep workflow contract")
            claim("surface_reconstruction", "fMRIPrep/FreeSurfer workflow contract")

        if tool_id in {"workflow_ml_decoding_pipeline", "decoding_classifier", "nilearn_decoding"}:
            claim("roi_feature_extraction", "ML decoding workflow contract")
            claim("supervised_decoding", "ML decoding workflow contract")
            claim("cross_validation", "ML decoding workflow contract")

        if tool_id in {"workflow_neurosynth_roi_analysis", "neurosynth_meta_analysis"}:
            claim("study_search", "Neurosynth/NiMARE meta-analysis workflow contract")
            claim("coordinate_meta_analysis", "Neurosynth/NiMARE meta-analysis workflow contract")

        if tool_id in {"kg_behavior_to_fmri_retrieval", "neurosynth_search_terms"}:
            claim("study_search", "KG/literature retrieval tool")

        if tool_id == "workflow_data_harmonization":
            claim("site_harmonization", "data harmonization workflow contract")
            claim("site_effect_diagnostics", "data harmonization workflow contract")

        if tool_id == "workflow_rest_connectome_e2e":
            claim("atlas_timeseries_extraction", "rest-connectome workflow contract")
            claim("connectivity_extraction", "rest-connectome workflow contract")

        if tool_id in {"clean_confounds", "standardize_confounds", "nilearn_preprocessing"}:
            claim("confound_cleaning", "confound cleaning tool")

    if action_type == "bash_cmd" and not _is_python_shell_command(action):
        if _target_contains(action, r"\bmriqc\b"):
            claim("image_quality_metrics", "MRIQC command invocation")
            if _target_contains(action, r"\bgroup\b", r"report", r"html", r"json"):
                claim("qc_reporting", "MRIQC reporting/group command")
        if _target_contains(action, r"\bfmriprep\b"):
            claim("fmri_preprocessing", "fMRIPrep command invocation")
            if _target_contains(action, r"fsaverage", r"freesurfer", r"recon-all", r"fs-license"):
                claim("surface_reconstruction", "fMRIPrep command requested FreeSurfer/surface outputs")
        if _target_contains(action, r"\brandomise\b", r"\bpalm\b", r"non_parametric_inference"):
            claim("permutation_inference", "permutation inference command/API")
            if _target_contains(action, r"\s-T\b", r"tfce", r"fwe", r"family[- ]wise"):
                claim("multiple_comparison_control", "permutation command requested TFCE/FWE-style correction")
        if _target_contains(action, r"permuted_ols"):
            claim("permutation_inference", "permuted_ols API invocation")
        if _target_contains(action, r"neuroharmonize", r"neurocombat"):
            claim("site_harmonization", "ComBat/neuroHarmonize invocation")
            if _target_contains(action, r"diagnostic", r"site.*predict", r"residual", r"combat.*covar"):
                claim("site_effect_diagnostics", "harmonization command included diagnostics language")
        if _target_contains(action, r"nilearn\.connectome", r"ConnectivityMeasure"):
            claim("connectivity_extraction", "nilearn connectome invocation")
        if _target_contains(action, r"NiftiMapsMasker", r"NiftiLabelsMasker", r"nilearn\.maskers"):
            claim("atlas_timeseries_extraction", "nilearn atlas masker invocation")
        if _target_contains(action, r"nilearn\.signal", r"confound"):
            claim("confound_cleaning", "confound cleaning signal in command")
        if _target_contains(action, r"tedana"):
            claim("multi_echo_denoising", "TEDANA command/API invocation")
        if _target_contains(action, r"nilearn\.glm\.first_level", r"FirstLevelModel"):
            claim("first_level_glm", "nilearn first-level GLM invocation")
            claim("hrf_modeling", "nilearn first-level GLM invocation")
        if _target_contains(action, r"compute_contrast", r"contrast"):
            claim("contrast_estimation", "contrast estimation invocation")
        if _target_contains(action, r"nimare", r"\bALE\b", r"meta\.cbma"):
            claim("coordinate_meta_analysis", "NiMARE/ALE invocation")
        if _target_contains(action, r"neurosynth", r"pubmed", r"openalex"):
            claim("study_search", "study search/retrieval invocation")

    if action_type in {"py_import", "py_call"}:
        if _target_contains(action, r"mriqc"):
            claim("image_quality_metrics", "MRIQC Python import/call")
        if _target_contains(action, r"nilearn\.connectome", r"ConnectivityMeasure"):
            claim("connectivity_extraction", "nilearn connectome Python import/call")
        if _target_contains(action, r"NiftiMapsMasker", r"NiftiLabelsMasker", r"nilearn\.maskers"):
            claim("atlas_timeseries_extraction", "nilearn masker Python import/call")
        if _target_contains(action, r"nilearn\.signal", r"clean"):
            claim("confound_cleaning", "nilearn signal Python import/call")
        if _target_contains(action, r"neuroharmonize", r"neurocombat"):
            claim("site_harmonization", "ComBat/neuroHarmonize Python import/call")
        if _target_contains(action, r"permuted_ols", r"non_parametric_inference"):
            claim("permutation_inference", "permutation Python import/call")
        if _target_contains(action, r"nilearn\.glm\.first_level", r"FirstLevelModel"):
            claim("first_level_glm", "nilearn first-level GLM Python import/call")
            claim("hrf_modeling", "nilearn first-level GLM Python import/call")
        if _target_contains(action, r"compute_contrast", r"contrast"):
            claim("contrast_estimation", "contrast Python import/call")
        if _target_contains(action, r"tedana"):
            claim("multi_echo_denoising", "TEDANA Python import/call")
        if _target_contains(action, r"nimare", r"\bALE\b", r"meta\.cbma"):
            claim("coordinate_meta_analysis", "NiMARE/ALE Python import/call")

    evidence = []
    for capability, reason in sorted(claims.items()):
        evidence.append(
            {
                "capability": capability,
                "action_index": action.get("index"),
                "action_type": action_type,
                "target": target,
                "tool_id": tool_id,
                "reason": reason,
            }
        )
    return evidence


def claim_summary(
    actions: Sequence[Mapping[str, Any]],
    required: set[str],
) -> tuple[set[str], list[str], list[dict[str, Any]]]:
    capabilities: set[str] = set()
    tools: set[str] = set()
    evidence: list[dict[str, Any]] = []
    for action in actions:
        action_evidence = claimed_capability_evidence(action, required)
        if not action_evidence:
            continue
        tools.add(recipe_tool_id(action))
        evidence.extend(action_evidence)
        capabilities.update(item["capability"] for item in action_evidence)
    return capabilities, sorted(tools), evidence


def _truncate(value: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def action_summary(actions: Sequence[Mapping[str, Any]], limit: int = 8) -> str:
    parts = []
    for action in actions[:limit]:
        parts.append(
            f"{action.get('index')}:{action.get('action_type')}:{_truncate(_string(action.get('target')), 120)}"
        )
    if len(actions) > limit:
        parts.append(f"...(+{len(actions) - limit})")
    return " | ".join(parts)


def response_preview(stdout_path: Path, limit: int = 600) -> str:
    snippets: list[str] = []
    for row in read_jsonl(stdout_path):
        row_type = _string(row.get("type"))
        if row_type == "result" and _string(row.get("result")):
            snippets.append(_string(row.get("result")))
        elif row_type == "assistant":
            message = row.get("message")
            if isinstance(message, Mapping):
                for block in _as_list(message.get("content")):
                    if not isinstance(block, Mapping):
                        continue
                    if block.get("type") == "text":
                        snippets.append(_string(block.get("text")))
                    elif block.get("type") == "tool_use":
                        snippets.append(f"tool_use:{block.get('name')}")
        elif row_type == "tool_use":
            tool = row.get("tool") or _nested_mapping(row, "part").get("tool")
            if tool:
                snippets.append(f"tool_use:{tool}")
    return _truncate(" ".join(snippets), limit)


def priority_for_row(
    *,
    score_row: Mapping[str, Any],
    record: Mapping[str, Any],
    delta: float | None,
    missing_but_claimed: set[str],
    claimed_not_parser: set[str],
) -> int:
    priority = 0
    if score_row.get("no_action"):
        priority += 200
    if not score_row.get("correct"):
        priority += 35
    if score_row.get("needs_human_adjudication"):
        priority += 25
    if _br_mode(_string(score_row.get("condition"))) == "with_br" and delta is not None and delta < 0:
        priority += 30
    if _br_mode(_string(score_row.get("condition"))) == "without_br" and delta is not None and delta > 0:
        priority += 20
    if abs(float(delta or 0.0)) >= 0.5:
        priority += 15
    if missing_but_claimed:
        priority += 35
    if claimed_not_parser:
        priority += 20
    if record.get("status") not in {"captured_stop", "succeeded"}:
        priority += 20
    return priority


def cluster_hint(
    *,
    br_mode: str,
    no_action: bool,
    delta: float | None,
    missing_but_claimed: set[str],
    claimed_not_parser: set[str],
    missing: set[str],
) -> str:
    if no_action:
        return "likely_model_failure_no_actions"
    if br_mode == "with_br" and missing_but_claimed:
        return "with_br_recipe_or_tool_claim_gap"
    if br_mode == "without_br" and (missing_but_claimed or claimed_not_parser):
        return "without_br_local_tool_mapping_gap"
    if br_mode == "with_br" and delta is not None and delta < 0:
        return "negative_delta_with_br_diagnostic"
    if br_mode == "with_br" and missing:
        return "with_br_missing_without_claim"
    if br_mode == "without_br" and delta is not None and delta > 0:
        return "without_br_underperformance_or_mapping_gap"
    return ""


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def build_packet_rows(run_dir: Path, tasks_path: Path) -> list[dict[str, Any]]:
    tasks = load_tasks(tasks_path)
    run_summary = read_json(run_dir / "run_summary.json")
    records = run_summary.get("records") or []
    record_by_key = {
        (_string(row.get("condition_id")), _string(row.get("task_id"))): row
        for row in records
        if isinstance(row, Mapping)
    }
    score_rows = read_jsonl(run_dir / "score_rows.jsonl")
    score_by_key = {
        (_string(row.get("condition")), _string(row.get("task_id"))): row
        for row in score_rows
    }
    deltas: dict[tuple[str, str], float] = {}
    for row in score_rows:
        condition = _string(row.get("condition"))
        task_id = _string(row.get("task_id"))
        system = _system_key(condition)
        without = score_by_key.get((f"{system}_without_br", task_id))
        with_br = score_by_key.get((f"{system}_with_br", task_id))
        if without and with_br:
            deltas[(condition, task_id)] = float(with_br.get("capability_score") or 0.0) - float(
                without.get("capability_score") or 0.0
            )

    rows: list[dict[str, Any]] = []
    for score_row in score_rows:
        condition = _string(score_row.get("condition"))
        task_id = _string(score_row.get("task_id"))
        task = tasks.get(task_id, {})
        required = _split_caps(score_row.get("required_capabilities") or task.get("required_capabilities"))
        parser_detected = _split_caps(score_row.get("capabilities_covered"))
        missing = _split_caps(score_row.get("missing_capabilities"))
        episode_dir = run_dir / "episodes" / condition / task_id
        parsed_actions_path = episode_dir / "parsed_actions.jsonl"
        parsed_actions = read_jsonl(parsed_actions_path)
        selected_actions = selected_full_actions(score_row, parsed_actions)
        selected_claims, selected_tools, selected_evidence = claim_summary(selected_actions, required)
        all_claims, all_tools, all_evidence = claim_summary(parsed_actions, required)
        missing_but_claimed_selected = missing & selected_claims
        missing_but_claimed_all = missing & all_claims
        claimed_not_parser_selected = selected_claims - parser_detected
        claimed_not_parser_all = all_claims - parser_detected
        parser_not_claimed_selected = parser_detected - selected_claims
        delta = deltas.get((condition, task_id))
        record = record_by_key.get((condition, task_id), {})
        br_mode = _br_mode(condition)
        priority = priority_for_row(
            score_row=score_row,
            record=record,
            delta=delta,
            missing_but_claimed=missing_but_claimed_selected,
            claimed_not_parser=claimed_not_parser_selected,
        )
        prompt_path = episode_dir / "prompt.txt"
        stdout_path = episode_dir / "stdout.jsonl"
        record_path = episode_dir / "record.json"
        rows.append(
            {
                "review_priority": priority,
                "adjudication_cluster_hint": cluster_hint(
                    br_mode=br_mode,
                    no_action=bool(score_row.get("no_action")),
                    delta=delta,
                    missing_but_claimed=missing_but_claimed_selected,
                    claimed_not_parser=claimed_not_parser_selected,
                    missing=missing,
                ),
                "condition": condition,
                "system": _display_system(condition),
                "br_mode": br_mode,
                "task_id": task_id,
                "category": score_row.get("category") or task.get("category"),
                "query": score_row.get("query") or task.get("query"),
                "template_id": score_row.get("template_id") or task.get("template_id"),
                "required_capabilities": _join_caps(required),
                "parser_detected_capabilities": _join_caps(parser_detected),
                "capabilities_covered": _join_caps(parser_detected),
                "missing_capabilities": _join_caps(missing),
                "claimed_capabilities_selected": _join_caps(selected_claims),
                "claimed_capabilities_all": _join_caps(all_claims),
                "missing_but_claimed_selected": _join_caps(missing_but_claimed_selected),
                "missing_but_claimed_all": _join_caps(missing_but_claimed_all),
                "claimed_not_parser_detected_selected": _join_caps(claimed_not_parser_selected),
                "claimed_not_parser_detected_all": _join_caps(claimed_not_parser_all),
                "parser_detected_not_claimed_selected": _join_caps(parser_not_claimed_selected),
                "claim_source_tools_selected": ";".join(selected_tools),
                "claim_source_tools_all": ";".join(all_tools),
                "claim_evidence_selected": _json_compact(selected_evidence),
                "claim_evidence_all": _json_compact(all_evidence),
                "capability_score": score_row.get("capability_score"),
                "correct": score_row.get("correct"),
                "needs_human_adjudication": score_row.get("needs_human_adjudication"),
                "no_action": score_row.get("no_action"),
                "trap_fall": score_row.get("trap_fall"),
                "canonical_tool_hit": score_row.get("canonical_tool_hit"),
                "used_canonical_routing_path": score_row.get("used_canonical_routing_path"),
                "pair_capability_delta_with_minus_without": delta,
                "status": record.get("status"),
                "wall_time_s": record.get("wall_time_s"),
                "json_error_event": bool(record.get("json_error_event")),
                "parsed_action_count": record.get("parsed_action_count"),
                "non_neutral_action_count": record.get("non_neutral_action_count"),
                "action_summary": action_summary(selected_actions),
                "all_action_summary": action_summary(parsed_actions),
                "response_preview": response_preview(stdout_path) if stdout_path.exists() else "",
                "prompt_path": _relative(prompt_path, ROOT),
                "stdout_path": _relative(stdout_path, ROOT),
                "parsed_actions_path": _relative(parsed_actions_path, ROOT),
                "record_path": _relative(record_path, ROOT),
                "manual_decision": "",
                "manual_covered_capabilities": "",
                "manual_false_positive_capabilities": "",
                "manual_false_negative_capabilities": "",
                "manual_notes": "",
            }
        )

    rows.sort(
        key=lambda row: (
            -int(row.get("review_priority") or 0),
            row.get("system") or "",
            row.get("br_mode") or "",
            row.get("task_id") or "",
        )
    )
    for rank, row in enumerate(rows, 1):
        row["priority_rank"] = rank
    return rows


def write_priority_markdown(path: Path, rows: Sequence[Mapping[str, Any]], run_dir: Path) -> None:
    lines = [
        "# Manual Adjudication Priority Sample",
        "",
        f"Run: `{_relative(run_dir, ROOT)}`",
        "",
        "This priority sample is sorted by adjudication ROI. The claim columns separate parser-detected coverage from conservative tool/recipe contract coverage.",
        "",
        "| Priority | Cluster | System | Mode | Task | Score | Missing | Claimed Missing | Delta | Actions | Paths |",
        "|---:|---|---|---|---|---:|---|---|---:|---|---|",
    ]
    for row in rows:
        score = row.get("capability_score")
        score_text = f"{float(score):.3f}" if isinstance(score, int | float) else _string(score)
        delta = row.get("pair_capability_delta_with_minus_without")
        delta_text = f"{float(delta):+.3f}" if isinstance(delta, int | float) else ""
        escaped_action_summary = _string(row.get("action_summary")).replace("|", "\\|")
        paths = (
            f"[prompt]({_string(row.get('prompt_path'))}) "
            f"[actions]({_string(row.get('parsed_actions_path'))}) "
            f"[stdout]({_string(row.get('stdout_path'))})"
        )
        lines.append(
            "| "
            f"{row.get('review_priority')} | "
            f"{_string(row.get('adjudication_cluster_hint'))} | "
            f"{_string(row.get('system'))} | "
            f"{_string(row.get('br_mode'))} | "
            f"{_string(row.get('task_id'))} | "
            f"{score_text} | "
            f"{_string(row.get('missing_capabilities'))} | "
            f"{_string(row.get('missing_but_claimed_selected'))} | "
            f"{delta_text} | "
            f"{escaped_action_summary} | "
            f"{paths} |"
        )
    lines.extend(
        [
            "",
            "Suggested manual labels:",
            "",
            "- `manual_decision`: `accept_score`, `false_positive`, `false_negative`, `parser_error`, `template_gap`, `ambiguous`.",
            "- `manual_covered_capabilities`: semicolon-separated capabilities judged covered by a human reviewer.",
            "- `manual_false_positive_capabilities`: capabilities counted by the parser but not truly invoked.",
            "- `manual_false_negative_capabilities`: capabilities missed by the parser/template but actually present.",
            "- `missing_but_claimed_selected`: capabilities missing from parser scoring but claimed by a selected concrete tool/recipe contract.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build manual adjudication packet for tool-selection real traces."
    )
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--tasks-jsonl", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--csv-out", type=Path)
    parser.add_argument("--jsonl-out", type=Path)
    parser.add_argument("--priority-md-out", type=Path)
    parser.add_argument("--priority-sample-size", type=int, default=30)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    csv_out = args.csv_out or run_dir / "manual_adjudication_packet.csv"
    jsonl_out = args.jsonl_out or run_dir / "manual_adjudication_packet.jsonl"
    md_out = args.priority_md_out or run_dir / "manual_adjudication_priority_sample.md"
    rows = build_packet_rows(run_dir, args.tasks_jsonl.resolve())
    write_csv(csv_out, rows)
    write_jsonl(jsonl_out, rows)
    write_priority_markdown(md_out, rows[: args.priority_sample_size], run_dir)
    print(
        json.dumps(
            {
                "rows": len(rows),
                "csv_out": str(csv_out),
                "jsonl_out": str(jsonl_out),
                "priority_md_out": str(md_out),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
