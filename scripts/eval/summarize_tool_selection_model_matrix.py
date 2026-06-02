#!/usr/bin/env python3
"""Build comprehensive metrics for tool-selection real-trace model matrices."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any


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


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def rate(numer: int, denom: int) -> float | None:
    return numer / denom if denom else None


def avg(values: Iterable[Any]) -> float | None:
    nums = [float(value) for value in values if isinstance(value, int | float)]
    return mean(nums) if nums else None


def system_key(condition: str) -> str:
    for suffix in ("_without_br", "_with_br"):
        if condition.endswith(suffix):
            return condition.removesuffix(suffix)
    return condition


def br_condition(condition: str) -> str:
    if condition.endswith("_with_br"):
        return "with_br"
    if condition.endswith("_without_br"):
        return "without_br"
    return "unknown"


def display_system(system: str) -> str:
    return {
        "codex_cli_gpt55": "Codex CLI GPT-5.5",
        "claude_code_opus47": "Claude Code Opus 4.7",
        "opencode_gemini_pro": "OpenCode Gemini Pro",
        "opencode_glm51": "OpenCode GLM 5.1",
        "opencode_kimi_k25": "OpenCode Kimi K2.5",
        "opencode_qwen36_plus": "OpenCode Qwen 3.6 Plus",
        "opencode_deepseek_v4_pro": "OpenCode DeepSeek v4 Pro",
    }.get(system, system)


def flatten_status_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get("status") or "missing") for row in rows).items()))


def first_non_neutral_action(row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    neutral_groups = {
        item.get("budget_group")
        for item in row.get("neutral_actions", [])
        if isinstance(item, Mapping)
    }
    for action in row.get("selected_actions", []):
        if not isinstance(action, Mapping):
            continue
        if action.get("budget_group") in neutral_groups:
            continue
        target = str(action.get("target") or "").strip()
        if target:
            return action
    return None


def load_episode_action_counts(episode_dir: Path) -> dict[str, Any]:
    actions = read_jsonl(episode_dir / "parsed_actions.jsonl")
    counts = Counter(str(action.get("action_type") or "") for action in actions)
    first = next((action for action in actions if str(action.get("target") or "").strip()), {})
    return {
        "parsed_action_count_from_file": len(actions),
        "mcp_tool_action_count": counts.get("mcp_tool", 0),
        "agent_tool_action_count": counts.get("agent_tool", 0),
        "bash_cmd_action_count": counts.get("bash_cmd", 0),
        "python_action_count": sum(
            counts.get(kind, 0)
            for kind in ("py_import", "py_call", "python_call", "python_import")
        ),
        "recipe_tool_action_count": counts.get("recipe_tool", 0),
        "first_parsed_action_type": first.get("action_type"),
        "first_parsed_action_target": first.get("target"),
        "first_parsed_action_source": first.get("source"),
    }


def build_task_condition_rows(
    *,
    run_dir: Path,
    records: Sequence[Mapping[str, Any]],
    score_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    score_by_key = {
        (str(row.get("condition")), str(row.get("task_id"))): row for row in score_rows
    }
    out: list[dict[str, Any]] = []
    for record in records:
        condition = str(record.get("condition_id") or "")
        task_id = str(record.get("task_id") or "")
        score = score_by_key.get((condition, task_id), {})
        first = first_non_neutral_action(score) if score else None
        episode_dir = run_dir / "episodes" / condition / task_id
        action_counts = (
            load_episode_action_counts(episode_dir)
            if episode_dir.exists() and (episode_dir / "parsed_actions.jsonl").exists()
            else {}
        )
        row = {
            "condition": condition,
            "system_key": system_key(condition),
            "system": display_system(system_key(condition)),
            "br_condition": br_condition(condition),
            "task_id": task_id,
            "runner": record.get("runner"),
            "model": record.get("model"),
            "status": record.get("status"),
            "returncode": record.get("returncode"),
            "json_error_event": bool(record.get("json_error_event")),
            "wall_time_s": record.get("wall_time_s"),
            "stopped_after_actions": bool(record.get("stopped_after_actions")),
            "record_parsed_action_count": record.get("parsed_action_count"),
            "record_relevant_action_count": record.get("relevant_action_count"),
            "record_non_neutral_action_count": record.get("non_neutral_action_count"),
            "scored": bool(score),
            "correct": score.get("correct"),
            "capability_score": score.get("capability_score"),
            "ungated_capability_score": score.get("ungated_capability_score"),
            "n_required_capabilities": score.get("n_required_capabilities"),
            "n_capabilities_covered": score.get("n_capabilities_covered"),
            "missing_capabilities": ";".join(score.get("missing_capabilities") or []),
            "capabilities_covered": ";".join(score.get("capabilities_covered") or []),
            "br_contract_mode": score.get("br_contract_mode"),
            "br_usage_ok": score.get("br_usage_ok"),
            "br_usage_failures": json.dumps(score.get("br_usage_failures") or [], sort_keys=True),
            "br_direct_plan_preflight_count": score.get("br_direct_plan_preflight_count"),
            "br_direct_concrete_route_count": score.get("br_direct_concrete_route_count"),
            "execution_handoff_contract": score.get("execution_handoff_contract"),
            "execution_handoff_ok": score.get("execution_handoff_ok"),
            "execution_handoff_score": score.get("execution_handoff_score"),
            "execution_handoff_failures": json.dumps(
                score.get("execution_handoff_failures") or [], sort_keys=True
            ),
            "trace_oracle_contract": score.get("trace_oracle_contract"),
            "trace_required_call_coverage": score.get("trace_required_call_coverage"),
            "trace_required_calls_missing": ";".join(
                score.get("trace_required_calls_missing") or []
            ),
            "failure_mode_labels": ";".join(score.get("failure_mode_labels") or []),
            "failure_mode_count": score.get("failure_mode_count"),
            "duplicate_route_call_count": score.get("duplicate_route_call_count"),
            "canonical_tool_hit": score.get("canonical_tool_hit"),
            "canonical_routing_path_applicable": score.get(
                "canonical_routing_path_applicable"
            ),
            "used_canonical_routing_path": score.get("used_canonical_routing_path"),
            "trap_fall": score.get("trap_fall"),
            "trap_hits": json.dumps(score.get("trap_hits") or [], sort_keys=True),
            "no_action": score.get("no_action"),
            "needs_human_adjudication": score.get("needs_human_adjudication"),
            "parse_confidence": score.get("parse_confidence"),
            "first_task_relevant_action_index": score.get(
                "first_task_relevant_action_index"
            ),
            "first_task_relevant_global_action_index": score.get(
                "first_task_relevant_global_action_index"
            ),
            "selected_action_count": len(score.get("selected_actions") or []),
            "neutral_action_count": len(score.get("neutral_actions") or []),
            "first_non_neutral_action_type": first.get("action_type") if first else None,
            "first_non_neutral_action_target": first.get("target") if first else None,
            "first_non_neutral_action_source": first.get("source") if first else None,
        }
        row.update(action_counts)
        out.append(row)
    return out


def summarize_condition(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for condition in sorted({str(row["condition"]) for row in rows}):
        subset = [row for row in rows if row["condition"] == condition]
        scored = [row for row in subset if row.get("scored")]
        status_counts = flatten_status_counts(subset)
        no_action_count = sum(1 for row in scored if row.get("no_action"))
        human_adjudication_count = sum(
            1 for row in scored if row.get("needs_human_adjudication")
        )
        failed_or_timeout_count = sum(
            1 for row in subset if row.get("status") in {"failed", "timed_out"}
        )
        provider_failure_like = (
            bool(subset)
            and bool(scored)
            and failed_or_timeout_count == len(subset)
            and no_action_count == len(scored)
            and human_adjudication_count == len(scored)
        )
        routing_applicable = [
            row for row in scored if row.get("canonical_routing_path_applicable")
        ]
        br_usage_scored = [
            row for row in scored if isinstance(row.get("br_usage_ok"), bool)
        ]
        handoff_scored = [
            row for row in scored if isinstance(row.get("execution_handoff_ok"), bool)
        ]
        failure_labels = Counter(
            label
            for row in scored
            for label in str(row.get("failure_mode_labels") or "").split(";")
            if label
        )
        out.append(
            {
                "condition": condition,
                "system_key": system_key(condition),
                "system": display_system(system_key(condition)),
                "br_condition": br_condition(condition),
                "record_count": len(subset),
                "scored_count": len(scored),
                "score_coverage": rate(len(scored), len(subset)),
                "valid_condition": (
                    len(subset) > 0
                    and len(scored) == len(subset)
                    and not provider_failure_like
                ),
                "provider_failure_like": provider_failure_like,
                "status_counts": json.dumps(status_counts, sort_keys=True),
                "succeeded_or_captured_count": sum(
                    1
                    for row in subset
                    if row.get("status") in {"succeeded", "captured_stop"}
                ),
                "failed_count": sum(1 for row in subset if row.get("status") == "failed"),
                "timed_out_count": sum(
                    1 for row in subset if row.get("status") == "timed_out"
                ),
                "json_error_count": sum(1 for row in subset if row.get("json_error_event")),
                "tool_selection_accuracy": rate(
                    sum(1 for row in scored if row.get("correct")), len(scored)
                ),
                "mean_capability_score": avg(
                    row.get("capability_score") for row in scored
                ),
                "mean_ungated_capability_score": avg(
                    row.get("ungated_capability_score") for row in scored
                ),
                "execution_handoff_ok_rate": rate(
                    sum(1 for row in handoff_scored if row.get("execution_handoff_ok")),
                    len(handoff_scored),
                ),
                "mean_execution_handoff_score": avg(
                    row.get("execution_handoff_score") for row in scored
                ),
                "mean_trace_required_call_coverage": avg(
                    row.get("trace_required_call_coverage") for row in scored
                ),
                "failure_mode_counts": json.dumps(dict(failure_labels), sort_keys=True),
                "duplicate_route_call_count": sum(
                    int(row.get("duplicate_route_call_count") or 0) for row in scored
                ),
                "br_usage_ok_rate": rate(
                    sum(1 for row in br_usage_scored if row.get("br_usage_ok")),
                    len(br_usage_scored),
                ),
                "mean_br_direct_plan_preflight_count": avg(
                    row.get("br_direct_plan_preflight_count") for row in scored
                ),
                "mean_br_direct_concrete_route_count": avg(
                    row.get("br_direct_concrete_route_count") for row in scored
                ),
                "mean_capabilities_covered": avg(
                    row.get("n_capabilities_covered") for row in scored
                ),
                "canonical_tool_hit_rate": rate(
                    sum(1 for row in scored if row.get("canonical_tool_hit")),
                    len(scored),
                ),
                "canonical_routing_path_rate": rate(
                    sum(
                        1
                        for row in routing_applicable
                        if row.get("used_canonical_routing_path")
                    ),
                    len(routing_applicable),
                ),
                "trap_fall_rate": rate(
                    sum(1 for row in scored if row.get("trap_fall")), len(scored)
                ),
                "no_action_rate": rate(no_action_count, len(scored)),
                "human_adjudication_rate": rate(human_adjudication_count, len(scored)),
                "mean_parse_confidence": avg(
                    row.get("parse_confidence") for row in scored
                ),
                "mean_first_task_relevant_action_index": avg(
                    row.get("first_task_relevant_action_index") for row in scored
                ),
                "mean_wall_time_s": avg(row.get("wall_time_s") for row in subset),
                "total_wall_time_s": sum(
                    float(row.get("wall_time_s") or 0.0) for row in subset
                ),
                "mean_mcp_tool_actions": avg(
                    row.get("mcp_tool_action_count") for row in subset
                ),
                "mean_bash_actions": avg(
                    row.get("bash_cmd_action_count") for row in subset
                ),
                "mean_python_actions": avg(
                    row.get("python_action_count") for row in subset
                ),
                "wrong_or_incomplete_tasks": ";".join(
                    str(row.get("task_id")) for row in scored if not row.get("correct")
                ),
                "unscored_tasks": ";".join(
                    str(row.get("task_id")) for row in subset if not row.get("scored")
                ),
            }
        )
    return out


def summarize_pairs(condition_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_system: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in condition_rows:
        by_system[str(row["system_key"])][str(row["br_condition"])] = row
    out: list[dict[str, Any]] = []
    for system in sorted(by_system):
        no_br = by_system[system].get("without_br", {})
        with_br = by_system[system].get("with_br", {})
        valid_pair = bool(no_br.get("valid_condition")) and bool(with_br.get("valid_condition"))
        cap_no = no_br.get("mean_capability_score")
        cap_br = with_br.get("mean_capability_score")
        ungated_cap_no = no_br.get("mean_ungated_capability_score")
        ungated_cap_br = with_br.get("mean_ungated_capability_score")
        acc_no = no_br.get("tool_selection_accuracy")
        acc_br = with_br.get("tool_selection_accuracy")
        out.append(
            {
                "system_key": system,
                "system": display_system(system),
                "valid_pair": valid_pair,
                "scored_without_br": no_br.get("scored_count"),
                "scored_with_br": with_br.get("scored_count"),
                "capability_without_br": cap_no,
                "capability_with_br": cap_br,
                "ungated_capability_without_br": ungated_cap_no,
                "ungated_capability_with_br": ungated_cap_br,
                "execution_handoff_without_br": no_br.get("mean_execution_handoff_score"),
                "execution_handoff_with_br": with_br.get("mean_execution_handoff_score"),
                "execution_handoff_ok_without_br": no_br.get("execution_handoff_ok_rate"),
                "execution_handoff_ok_with_br": with_br.get("execution_handoff_ok_rate"),
                "trace_required_call_coverage_without_br": no_br.get(
                    "mean_trace_required_call_coverage"
                ),
                "trace_required_call_coverage_with_br": with_br.get(
                    "mean_trace_required_call_coverage"
                ),
                "capability_delta_with_minus_without": (
                    float(cap_br) - float(cap_no)
                    if isinstance(cap_no, int | float) and isinstance(cap_br, int | float)
                    else None
                ),
                "ungated_capability_delta_with_minus_without": (
                    float(ungated_cap_br) - float(ungated_cap_no)
                    if isinstance(ungated_cap_no, int | float)
                    and isinstance(ungated_cap_br, int | float)
                    else None
                ),
                "accuracy_without_br": acc_no,
                "accuracy_with_br": acc_br,
                "accuracy_delta_with_minus_without": (
                    float(acc_br) - float(acc_no)
                    if isinstance(acc_no, int | float) and isinstance(acc_br, int | float)
                    else None
                ),
                "canonical_tool_hit_without_br": no_br.get("canonical_tool_hit_rate"),
                "canonical_tool_hit_with_br": with_br.get("canonical_tool_hit_rate"),
                "canonical_routing_without_br": no_br.get(
                    "canonical_routing_path_rate"
                ),
                "canonical_routing_with_br": with_br.get(
                    "canonical_routing_path_rate"
                ),
                "br_usage_ok_without_br": no_br.get("br_usage_ok_rate"),
                "br_usage_ok_with_br": with_br.get("br_usage_ok_rate"),
                "mean_br_direct_plan_preflight_with_br": with_br.get(
                    "mean_br_direct_plan_preflight_count"
                ),
                "mean_br_direct_concrete_route_with_br": with_br.get(
                    "mean_br_direct_concrete_route_count"
                ),
                "human_adjudication_without_br": no_br.get("human_adjudication_rate"),
                "human_adjudication_with_br": with_br.get("human_adjudication_rate"),
                "no_action_without_br": no_br.get("no_action_rate"),
                "no_action_with_br": with_br.get("no_action_rate"),
                "mean_wall_time_without_br": no_br.get("mean_wall_time_s"),
                "mean_wall_time_with_br": with_br.get("mean_wall_time_s"),
                "status_without_br": no_br.get("status_counts"),
                "status_with_br": with_br.get("status_counts"),
                "invalid_reason": (
                    ""
                    if valid_pair
                    else (
                        f"without_br valid={bool(no_br.get('valid_condition'))} "
                        f"scored={no_br.get('scored_count')}/{no_br.get('record_count')}; "
                        f"with_br valid={bool(with_br.get('valid_condition'))} "
                        f"scored={with_br.get('scored_count')}/{with_br.get('record_count')}"
                    )
                ),
            }
        )
    return out


def summarize_tasks(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for task_id in sorted({str(row["task_id"]) for row in rows}):
        subset = [row for row in rows if row["task_id"] == task_id]
        scored = [row for row in subset if row.get("scored")]
        handoff_scored = [
            row for row in scored if isinstance(row.get("execution_handoff_ok"), bool)
        ]
        failure_labels = Counter(
            label
            for row in scored
            for label in str(row.get("failure_mode_labels") or "").split(";")
            if label
        )
        no_br = [
            row
            for row in scored
            if (row.get("br_condition") or br_condition(str(row.get("condition") or "")))
            == "without_br"
        ]
        with_br = [
            row
            for row in scored
            if (row.get("br_condition") or br_condition(str(row.get("condition") or "")))
            == "with_br"
        ]
        out.append(
            {
                "task_id": task_id,
                "record_count": len(subset),
                "scored_count": len(scored),
                "score_coverage": rate(len(scored), len(subset)),
                "status_counts": json.dumps(flatten_status_counts(subset), sort_keys=True),
                "accuracy_all": rate(sum(1 for row in scored if row.get("correct")), len(scored)),
                "mean_capability_all": avg(row.get("capability_score") for row in scored),
                "mean_ungated_capability_all": avg(
                    row.get("ungated_capability_score") for row in scored
                ),
                "execution_handoff_ok_all": rate(
                    sum(1 for row in handoff_scored if row.get("execution_handoff_ok")),
                    len(handoff_scored),
                ),
                "mean_execution_handoff_all": avg(
                    row.get("execution_handoff_score") for row in scored
                ),
                "mean_trace_required_call_coverage_all": avg(
                    row.get("trace_required_call_coverage") for row in scored
                ),
                "accuracy_without_br": rate(
                    sum(1 for row in no_br if row.get("correct")), len(no_br)
                ),
                "accuracy_with_br": rate(
                    sum(1 for row in with_br if row.get("correct")), len(with_br)
                ),
                "mean_capability_without_br": avg(
                    row.get("capability_score") for row in no_br
                ),
                "mean_capability_with_br": avg(
                    row.get("capability_score") for row in with_br
                ),
                "mean_ungated_capability_with_br": avg(
                    row.get("ungated_capability_score") for row in with_br
                ),
                "br_usage_ok_with_br": rate(
                    sum(1 for row in with_br if row.get("br_usage_ok")),
                    sum(1 for row in with_br if isinstance(row.get("br_usage_ok"), bool)),
                ),
                "execution_handoff_failed_count": sum(
                    1 for row in handoff_scored if row.get("execution_handoff_ok") is False
                ),
                "failure_mode_counts": json.dumps(dict(failure_labels), sort_keys=True),
                "trap_fall_count": sum(1 for row in scored if row.get("trap_fall")),
                "no_action_count": sum(1 for row in scored if row.get("no_action")),
                "human_adjudication_count": sum(
                    1 for row in scored if row.get("needs_human_adjudication")
                ),
                "canonical_tool_hit_count": sum(
                    1 for row in scored if row.get("canonical_tool_hit")
                ),
                "with_br_mcp_tool_mean": avg(
                    row.get("mcp_tool_action_count")
                    for row in subset
                    if row.get("br_condition") == "with_br"
                ),
                "without_br_mcp_tool_mean": avg(
                    row.get("mcp_tool_action_count")
                    for row in subset
                    if row.get("br_condition") == "without_br"
                ),
                "top_missing_capabilities": json.dumps(
                    dict(
                        Counter(
                            cap
                            for row in scored
                            for cap in str(row.get("missing_capabilities") or "").split(";")
                            if cap
                        ).most_common()
                    ),
                    sort_keys=True,
                ),
            }
        )
    return out


def build_completion_audit(run_summary: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    expected_conditions = list(run_summary.get("conditions") or [])
    expected_tasks = list(run_summary.get("tasks") or [])
    expected_records = len(expected_conditions) * len(expected_tasks)
    observed_pairs = {(row.get("condition"), row.get("task_id")) for row in rows}
    expected_pairs = {(condition, task) for condition in expected_conditions for task in expected_tasks}
    record_count = len(rows)
    parsed_action_records = sum(
        1 for row in rows if isinstance(row.get("parsed_action_count_from_file"), int)
    )
    scored_records = sum(1 for row in rows if row.get("scored"))
    missing_pairs = sorted(f"{condition}/{task}" for condition, task in expected_pairs - observed_pairs)
    duplicate_count = record_count - len(observed_pairs)
    return {
        "expected_conditions": expected_conditions,
        "expected_tasks": expected_tasks,
        "expected_record_count": expected_records,
        "observed_record_count": record_count,
        "observed_unique_condition_task_pairs": len(observed_pairs),
        "duplicate_condition_task_records": duplicate_count,
        "missing_condition_task_pairs": missing_pairs,
        "all_expected_records_present": record_count == expected_records and not missing_pairs,
        "parsed_action_record_count": parsed_action_records,
        "all_records_have_parsed_actions": parsed_action_records == record_count,
        "scored_record_count": scored_records,
        "unscored_record_count": record_count - scored_records,
        "complete_execution_matrix": record_count == expected_records and not missing_pairs,
    }


def markdown_report(
    *,
    run_dir: Path,
    audit: Mapping[str, Any],
    condition_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    task_rows: Sequence[Mapping[str, Any]],
) -> str:
    lines: list[str] = [
        "# Comprehensive Tool-Selection Model Matrix Metrics",
        "",
        f"Run dir: `{run_dir}`",
        "",
        "## Completion Audit",
        "",
        f"- Expected records: {audit['expected_record_count']}",
        f"- Observed records: {audit['observed_record_count']}",
        f"- Parsed-action records: {audit['parsed_action_record_count']}",
        f"- Scored records: {audit['scored_record_count']}",
        f"- Complete execution matrix: `{audit['complete_execution_matrix']}`",
        f"- All records have parsed actions: `{audit['all_records_have_parsed_actions']}`",
        "",
        "## BR Pair Summary",
        "",
        "| System | Valid pair | Scored no BR | Scored +BR | Cap no BR | Cap +BR | Trace no BR | Trace +BR | Handoff no BR | Handoff +BR | Handoff ok +BR | Ungated +BR | BR ok +BR | Delta | Acc no BR | Acc +BR | Canon +BR | Status no BR | Status +BR |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in pair_rows:
        def fmt(value: Any) -> str:
            return "NA" if value is None or value == "" else (
                f"{value:.3f}" if isinstance(value, float) else str(value)
            )
        lines.append(
            "| {system} | {valid_pair} | {scored_without_br} | {scored_with_br} | "
            "{capability_without_br} | {capability_with_br} | "
            "{trace_required_call_coverage_without_br} | "
            "{trace_required_call_coverage_with_br} | "
            "{execution_handoff_without_br} | {execution_handoff_with_br} | "
            "{execution_handoff_ok_with_br} | "
            "{ungated_capability_with_br} | {br_usage_ok_with_br} | "
            "{capability_delta_with_minus_without} | {accuracy_without_br} | "
            "{accuracy_with_br} | {canonical_tool_hit_with_br} | `{status_without_br}` | "
            "`{status_with_br}` |".format(
                system=row["system"],
                valid_pair="yes" if row["valid_pair"] else "no",
                scored_without_br=fmt(row.get("scored_without_br")),
                scored_with_br=fmt(row.get("scored_with_br")),
                capability_without_br=fmt(row.get("capability_without_br")),
                capability_with_br=fmt(row.get("capability_with_br")),
                trace_required_call_coverage_without_br=fmt(
                    row.get("trace_required_call_coverage_without_br")
                ),
                trace_required_call_coverage_with_br=fmt(
                    row.get("trace_required_call_coverage_with_br")
                ),
                execution_handoff_without_br=fmt(row.get("execution_handoff_without_br")),
                execution_handoff_with_br=fmt(row.get("execution_handoff_with_br")),
                execution_handoff_ok_with_br=fmt(row.get("execution_handoff_ok_with_br")),
                ungated_capability_with_br=fmt(row.get("ungated_capability_with_br")),
                br_usage_ok_with_br=fmt(row.get("br_usage_ok_with_br")),
                capability_delta_with_minus_without=fmt(
                    row.get("capability_delta_with_minus_without")
                ),
                accuracy_without_br=fmt(row.get("accuracy_without_br")),
                accuracy_with_br=fmt(row.get("accuracy_with_br")),
                canonical_tool_hit_with_br=fmt(row.get("canonical_tool_hit_with_br")),
                status_without_br=row.get("status_without_br") or "",
                status_with_br=row.get("status_with_br") or "",
            )
        )
    invalid = [row for row in pair_rows if not row.get("valid_pair")]
    if invalid:
        lines.extend(["", "Invalid/degraded pair notes:"])
        for row in invalid:
            lines.append(f"- {row['system']}: {row.get('invalid_reason')}")

    lines.extend(
        [
            "",
            "## Task Difficulty Summary",
            "",
            "| Task | Scored | Cap all | Trace calls | Handoff all | Handoff ok | Cap no BR | Cap +BR | Ungated +BR | BR ok +BR | Acc all | No-action | Human adj | Failure modes | Top missing capabilities |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in task_rows:
        def fmt(value: Any) -> str:
            return "NA" if value is None or value == "" else (
                f"{value:.3f}" if isinstance(value, float) else str(value)
            )
        lines.append(
            f"| {row['task_id']} | {row['scored_count']}/{row['record_count']} | "
            f"{fmt(row.get('mean_capability_all'))} | "
            f"{fmt(row.get('mean_trace_required_call_coverage_all'))} | "
            f"{fmt(row.get('mean_execution_handoff_all'))} | "
            f"{fmt(row.get('execution_handoff_ok_all'))} | "
            f"{fmt(row.get('mean_capability_without_br'))} | "
            f"{fmt(row.get('mean_capability_with_br'))} | "
            f"{fmt(row.get('mean_ungated_capability_with_br'))} | "
            f"{fmt(row.get('br_usage_ok_with_br'))} | "
            f"{fmt(row.get('accuracy_all'))} | "
            f"{row.get('no_action_count')} | {row.get('human_adjudication_count')} | "
            f"`{row.get('failure_mode_counts')}` | "
            f"`{row.get('top_missing_capabilities')}` |"
        )

    lines.extend(
        [
            "",
            "## Condition Diagnostics",
            "",
            "| Condition | Scored | Status | Mean cap | Trace calls | Handoff | Handoff ok | Ungated cap | BR ok | Acc | Human adj | No-action | Mean MCP actions | Mean wall s |",
            "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in condition_rows:
        def fmt(value: Any) -> str:
            return "NA" if value is None or value == "" else (
                f"{value:.3f}" if isinstance(value, float) else str(value)
            )
        lines.append(
            f"| `{row['condition']}` | {row['scored_count']}/{row['record_count']} | "
            f"`{row['status_counts']}` | {fmt(row.get('mean_capability_score'))} | "
            f"{fmt(row.get('mean_trace_required_call_coverage'))} | "
            f"{fmt(row.get('mean_execution_handoff_score'))} | "
            f"{fmt(row.get('execution_handoff_ok_rate'))} | "
            f"{fmt(row.get('mean_ungated_capability_score'))} | "
            f"{fmt(row.get('br_usage_ok_rate'))} | "
            f"{fmt(row.get('tool_selection_accuracy'))} | "
            f"{fmt(row.get('human_adjudication_rate'))} | "
            f"{fmt(row.get('no_action_rate'))} | "
            f"{fmt(row.get('mean_mcp_tool_actions'))} | "
            f"{fmt(row.get('mean_wall_time_s'))} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_summary(run_dir: Path, score_rows_path: Path | None = None) -> dict[str, Any]:
    run_summary = read_json(run_dir / "run_summary.json")
    score_rows = read_jsonl(score_rows_path or run_dir / "score_rows.jsonl")
    task_condition_rows = build_task_condition_rows(
        run_dir=run_dir,
        records=run_summary.get("records") or [],
        score_rows=score_rows,
    )
    condition_rows = summarize_condition(task_condition_rows)
    pair_rows = summarize_pairs(condition_rows)
    task_rows = summarize_tasks(task_condition_rows)
    audit = build_completion_audit(run_summary, task_condition_rows)
    return {
        "schema_version": "br.tool_selection_comprehensive_model_matrix.v1",
        "run_dir": str(run_dir),
        "audit": audit,
        "condition_summary": condition_rows,
        "pair_summary": pair_rows,
        "task_summary": task_rows,
        "task_condition_rows": task_condition_rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--score-rows",
        type=Path,
        help="Optional rescored score_rows JSONL path. Defaults to run_dir/score_rows.jsonl.",
    )
    parser.add_argument(
        "--prefix",
        default="comprehensive_model_matrix",
        help="Output file prefix inside run_dir.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    summary = build_summary(run_dir, args.score_rows.resolve() if args.score_rows else None)
    prefix = args.prefix
    write_json(run_dir / f"{prefix}_summary.json", summary)
    write_json(run_dir / f"{prefix}_audit.json", summary["audit"])
    write_csv(
        run_dir / f"{prefix}_condition_summary.csv",
        summary["condition_summary"],
        fieldnames=list(summary["condition_summary"][0].keys())
        if summary["condition_summary"]
        else [],
    )
    write_csv(
        run_dir / f"{prefix}_pair_summary.csv",
        summary["pair_summary"],
        fieldnames=list(summary["pair_summary"][0].keys())
        if summary["pair_summary"]
        else [],
    )
    write_csv(
        run_dir / f"{prefix}_task_summary.csv",
        summary["task_summary"],
        fieldnames=list(summary["task_summary"][0].keys())
        if summary["task_summary"]
        else [],
    )
    write_csv(
        run_dir / f"{prefix}_task_condition_rows.csv",
        summary["task_condition_rows"],
        fieldnames=list(summary["task_condition_rows"][0].keys())
        if summary["task_condition_rows"]
        else [],
    )
    (run_dir / f"{prefix}_summary.md").write_text(
        markdown_report(
            run_dir=run_dir,
            audit=summary["audit"],
            condition_rows=summary["condition_summary"],
            pair_rows=summary["pair_summary"],
            task_rows=summary["task_summary"],
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary["audit"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
