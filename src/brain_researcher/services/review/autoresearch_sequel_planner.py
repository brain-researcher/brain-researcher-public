"""Post-closeout sequel planning helpers for autoresearch workspaces."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _normalize_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        items.append(text)
        seen.add(text)
    return items


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _component_status(mean_r: float | None) -> str:
    if mean_r is None:
        return "unknown"
    if mean_r >= 0.15:
        return "strong"
    if mean_r >= 0.08:
        return "mixed"
    if mean_r >= 0.0:
        return "weak"
    return "negative"


def _parse_primary_analysis_components(report_text: str) -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    header_seen = False
    for raw_line in report_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        if "Component" in line and "fold_mean_r" in line:
            header_seen = True
            continue
        if not header_seen or not line.startswith("| ICA_"):
            continue
        cols = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cols) < 5:
            continue
        name = cols[0]
        mean_r = _safe_float(cols[1])
        ref_mean = _safe_float(cols[2])
        ref_best = _safe_float(cols[3])
        components[name] = {
            "fold_mean_r": mean_r,
            "ref_mean_r": ref_mean,
            "ref_best_r": ref_best,
            "status": _component_status(mean_r),
        }
    return components


def _extract_validation_missing(verdict: dict[str, Any], report_text: str) -> list[str]:
    validation_status = verdict.get("validation_status") or {}
    missing = [
        str(key)
        for key, value in validation_status.items()
        if str(value) in {"missing", "mentioned_only"}
    ]
    match = re.search(r"\*\*validation_missing:\*\*\s*(.+)", report_text)
    if match:
        for item in match.group(1).split(","):
            text = item.strip()
            if text:
                missing.append(text)
    return _normalize_list(missing)


def _extract_data_engineering_blockers(report_text: str) -> list[str]:
    blockers: list[str] = []
    for match in re.finditer(
        r"`([^`]+)`:\s+\*\*out of dataset scope(?: for this line)?\*\*", report_text
    ):
        blockers.append(f"{match.group(1)}_blocked_by_data_scope")
    lowered = report_text.lower()
    if "raw bold" in lowered and "not" in lowered:
        blockers.append("raw_bold_not_available")
    return _normalize_list(blockers)


def _infer_existing_line_types(workspace_root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    if not workspace_root.exists():
        return found
    tokens = [
        "blind_replication",
        "data_scaling",
        "representation_scaling",
        "model_scaling",
        "generalization",
        "foundation_transfer",
        "validation",
    ]
    for path in workspace_root.iterdir():
        if not path.is_dir():
            continue
        name = path.name.lower()
        if not name.startswith("autoresearch_"):
            continue
        for token in tokens:
            if token in name:
                found.setdefault(token, []).append(str(path.resolve()))
    return found


def build_closeout_card(
    workspace: str | Path,
    *,
    line_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(workspace).resolve()
    outputs_dir = root / "outputs"
    final_report_path = outputs_dir / "final_report.md"
    verdict_path = outputs_dir / "autoresearch_scientific_review_verdict.json"

    report_text = _load_text(final_report_path)
    verdict = _load_json(verdict_path)
    if line_state is None:
        line_state = _load_json(root / "line_state.json")

    components = _parse_primary_analysis_components(report_text)
    confirmed_wins = [
        name
        for name, payload in components.items()
        if payload.get("status") == "strong"
    ]
    tentative_components = [
        name for name, payload in components.items() if payload.get("status") == "mixed"
    ]
    weak_or_null_components = [
        name
        for name, payload in components.items()
        if payload.get("status") in {"weak", "negative"}
    ]
    negative_results = [
        {
            "type": "component_signal_not_robust",
            "component": name,
            "fold_mean_r": components[name].get("fold_mean_r"),
            "status": components[name].get("status"),
        }
        for name in weak_or_null_components
    ]
    validation_missing = _extract_validation_missing(verdict, report_text)
    data_engineering_blockers = _extract_data_engineering_blockers(report_text)
    open_blockers = list(data_engineering_blockers)
    judgment = verdict.get("judgment") or {}
    if str(judgment.get("judgment_status") or "") == "parse_failed":
        open_blockers.append("judgment_critic_transport_failure")

    return {
        "schema_version": "autoresearch-closeout-card-v1",
        "generated_at_utc": _utc_now(),
        "source_workspace": str(root),
        "line_type": str(line_state.get("line_type") or ""),
        "status": str(line_state.get("status") or ""),
        "review": {
            "overall_decision": verdict.get("overall_decision"),
            "report_action": verdict.get("report_action"),
            "claim_strength": verdict.get("claim_strength"),
            "rationale": verdict.get("rationale"),
        },
        "latest_summary": line_state.get("last_latest_summary") or {},
        "components": components,
        "confirmed_wins": confirmed_wins,
        "tentative_components": tentative_components,
        "weak_or_null_components": weak_or_null_components,
        "negative_results": negative_results,
        "validation_missing": validation_missing,
        "data_engineering_blockers": data_engineering_blockers,
        "open_blockers": _normalize_list(open_blockers),
        "demo_gaps": _normalize_list(
            [
                "no_blind_replication_baseline",
                "no_kg_grounded_sequel",
                (
                    "pe_feature_vs_data_limit_unresolved"
                    if "ICA_PersonalityEmotion" in tentative_components
                    else ""
                ),
                (
                    "generalization_axes_blocked"
                    if any(
                        "alternate_parcellation" in item
                        or "external_cohort" in item
                        or "replication_evidence" in item
                        for item in validation_missing
                    )
                    else ""
                ),
            ]
        ),
    }


def _candidate(
    *,
    candidate_id: str,
    line_type: str,
    analysis_focus: str | None,
    scientific_question: str,
    why_now: str,
    expected_demo_value: str,
    priority: int,
    triggered_by: list[str],
    existing_workspaces: list[str],
    blockers: list[str],
    module_presets: dict[str, dict[str, Any]],
    budget_envelope: dict[str, Any],
) -> dict[str, Any]:
    preset = module_presets.get(line_type, {})
    status = "ready"
    if existing_workspaces:
        status = "already_exists"
    elif blockers:
        status = "blocked"
    return {
        "candidate_id": candidate_id,
        "line_type": line_type,
        "analysis_focus": analysis_focus,
        "scientific_question": scientific_question,
        "why_now": why_now,
        "expected_demo_value": expected_demo_value,
        "priority": priority,
        "triggered_by": _normalize_list(triggered_by),
        "status": status,
        "existing_workspaces": existing_workspaces,
        "blockers": _normalize_list(blockers),
        "loaded_modules": _normalize_list(preset.get("loaded_modules")),
        "forbidden_modules": _normalize_list(preset.get("forbidden_modules")),
        "training_backend": str(preset.get("training_backend") or ""),
        "success_criterion": str(preset.get("success_criterion") or ""),
        "budget_envelope": dict(budget_envelope),
    }


def build_candidate_lines(
    closeout_card: dict[str, Any],
    *,
    module_presets: dict[str, dict[str, Any]] | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(
        workspace_root or Path(closeout_card["source_workspace"]).parent
    ).resolve()
    module_presets = module_presets or {}
    existing = _infer_existing_line_types(root)
    demo_gaps = set(_normalize_list(closeout_card.get("demo_gaps")))
    validation_missing = set(_normalize_list(closeout_card.get("validation_missing")))
    weak_or_null = set(_normalize_list(closeout_card.get("weak_or_null_components")))
    tentative = set(_normalize_list(closeout_card.get("tentative_components")))
    data_blockers = set(_normalize_list(closeout_card.get("data_engineering_blockers")))

    candidates: list[dict[str, Any]] = []

    candidates.append(
        _candidate(
            candidate_id="blind_replication_baseline",
            line_type="blind_replication",
            analysis_focus="human_baseline_proxy",
            scientific_question=(
                "Can a blind solo agent reproduce Liu 2023 reference performance "
                "without reading prior autoresearch artifacts?"
            ),
            why_now=(
                "The closeout is accepted, but the demo still lacks a clean "
                "agent-solo baseline for comparison."
            ),
            expected_demo_value="high",
            priority=100,
            triggered_by=["no_blind_replication_baseline"],
            existing_workspaces=existing.get("blind_replication", []),
            blockers=[],
            module_presets=module_presets,
            budget_envelope={
                "max_runner_turns": 8,
                "max_wallclock_hours": 4,
                "exploration_floor_iters": 6,
                "max_confirmation_fraction": 0.5,
            },
        )
    )

    candidates.append(
        _candidate(
            candidate_id="kg_grounded_prior",
            line_type="representation_scaling",
            analysis_focus="kg_grounded_metric_prior",
            scientific_question=(
                "Can KG-grounded FC metric priors recover the best routing faster "
                "than free search in the same feature space?"
            ),
            why_now=(
                "The accepted closeout is scientifically coherent, but the demo "
                "story still lacks a BR-specific KG-grounded decision."
            ),
            expected_demo_value="high",
            priority=95,
            triggered_by=["no_kg_grounded_sequel"],
            existing_workspaces=[],
            blockers=[],
            module_presets=module_presets,
            budget_envelope={
                "max_runner_turns": 8,
                "max_wallclock_hours": 6,
                "exploration_floor_iters": 6,
                "max_confirmation_fraction": 0.4,
            },
        )
    )

    if tentative or weak_or_null:
        candidates.append(
            _candidate(
                candidate_id="pe_feature_limit_disambiguation",
                line_type="representation_scaling",
                analysis_focus="pe_feature_vs_data_limit",
                scientific_question=(
                    "Does feature-space expansion saturate before sample-size needs "
                    "for the mixed-strength components, especially PersonalityEmotion?"
                ),
                why_now=(
                    "The closeout still contains mixed-strength components whose "
                    "remaining headroom could reflect feature limits rather than only "
                    "sample limits."
                ),
                expected_demo_value="medium",
                priority=80,
                triggered_by=[
                    (
                        "pe_feature_vs_data_limit_unresolved"
                        if "pe_feature_vs_data_limit_unresolved" in demo_gaps
                        else "mixed_strength_components_present"
                    )
                ],
                existing_workspaces=existing.get("representation_scaling", []),
                blockers=[],
                module_presets=module_presets,
                budget_envelope={
                    "max_runner_turns": 10,
                    "max_wallclock_hours": 10,
                    "exploration_floor_iters": 8,
                    "max_confirmation_fraction": 0.4,
                },
            )
        )

        candidates.append(
            _candidate(
                candidate_id="data_scaling_refinement",
                line_type="data_scaling",
                analysis_focus="sample_size_go_no_go",
                scientific_question=(
                    "How do predictive ceilings and go/no-go thresholds shift under "
                    "sample-size scaling for the weak or mixed targets?"
                ),
                why_now=(
                    "Weak and mixed components remain after accepted closeout, so a "
                    "scaling-law line can turn them into quantified go/no-go decisions."
                ),
                expected_demo_value="medium",
                priority=78,
                triggered_by=["weak_or_null_components_present"],
                existing_workspaces=existing.get("data_scaling", []),
                blockers=[],
                module_presets=module_presets,
                budget_envelope={
                    "max_runner_turns": 12,
                    "max_wallclock_hours": 12,
                    "exploration_floor_iters": 10,
                    "max_confirmation_fraction": 0.3,
                },
            )
        )

    if validation_missing:
        candidates.append(
            _candidate(
                candidate_id="generalization_axes_followup",
                line_type="generalization",
                analysis_focus="alt_parcellation_gsr_external",
                scientific_question=(
                    "Do the accepted claims survive alternate parcellation, GSR, "
                    "and broader replication axes?"
                ),
                why_now=(
                    "The accepted closeout still records missing replication/generalization "
                    "axes that matter for a stronger demo claim."
                ),
                expected_demo_value="medium",
                priority=76,
                triggered_by=sorted(validation_missing),
                existing_workspaces=existing.get("generalization", []),
                blockers=sorted(data_blockers),
                module_presets=module_presets,
                budget_envelope={
                    "max_runner_turns": 10,
                    "max_wallclock_hours": 12,
                    "exploration_floor_iters": 8,
                    "max_confirmation_fraction": 0.4,
                },
            )
        )

    if tentative:
        candidates.append(
            _candidate(
                candidate_id="model_capacity_followup",
                line_type="model_scaling",
                analysis_focus="capacity_crossover_probe",
                scientific_question=(
                    "Is any remaining headroom for the mixed-strength components a "
                    "true model-capacity issue?"
                ),
                why_now=(
                    "A model-scaling sequel can distinguish residual headroom from "
                    "search incompleteness or seed selection effects."
                ),
                expected_demo_value="medium",
                priority=70,
                triggered_by=["mixed_strength_components_present"],
                existing_workspaces=existing.get("model_scaling", []),
                blockers=[],
                module_presets=module_presets,
                budget_envelope={
                    "max_runner_turns": 10,
                    "max_wallclock_hours": 16,
                    "exploration_floor_iters": 8,
                    "max_confirmation_fraction": 0.4,
                },
            )
        )

    foundation_blockers = (
        ["raw_bold_not_available"] if "raw_bold_not_available" in data_blockers else []
    )
    candidates.append(
        _candidate(
            candidate_id="foundation_transfer_feasibility",
            line_type="foundation_transfer",
            analysis_focus="pretrained_embedding_probe",
            scientific_question=(
                "Can pretrained or transfer-learning representations beat the sparse "
                "linear ceiling once the required raw inputs are available?"
            ),
            why_now=(
                "Transfer remains a natural sequel axis, but its feasibility depends "
                "on raw-input availability."
            ),
            expected_demo_value="low",
            priority=40,
            triggered_by=["transfer_followup_candidate"],
            existing_workspaces=existing.get("foundation_transfer", []),
            blockers=foundation_blockers,
            module_presets=module_presets,
            budget_envelope={
                "max_runner_turns": 8,
                "max_wallclock_hours": 12,
                "exploration_floor_iters": 6,
                "max_confirmation_fraction": 0.4,
            },
        )
    )

    candidates = sorted(
        candidates, key=lambda item: (-int(item["priority"]), item["candidate_id"])
    )
    selected = next((item for item in candidates if item["status"] == "ready"), None)

    return {
        "schema_version": "autoresearch-candidate-lines-v1",
        "generated_at_utc": _utc_now(),
        "source_workspace": closeout_card["source_workspace"],
        "selection_policy": {
            "prefer_ready_over_blocked": True,
            "prefer_not_already_existing": True,
            "sort_by_priority_desc": True,
        },
        "selected_candidate_id": None if selected is None else selected["candidate_id"],
        "candidates": candidates,
    }


def build_line_spec(
    candidate_lines: dict[str, Any],
    *,
    closeout_card: dict[str, Any],
) -> dict[str, Any]:
    selected_id = candidate_lines.get("selected_candidate_id")
    selected = next(
        (
            item
            for item in candidate_lines.get("candidates", [])
            if item.get("candidate_id") == selected_id
        ),
        None,
    )
    return {
        "schema_version": "autoresearch-line-spec-v1",
        "generated_at_utc": _utc_now(),
        "source_workspace": closeout_card["source_workspace"],
        "source_closeout_claim_strength": (closeout_card.get("review") or {}).get(
            "claim_strength"
        ),
        "selected_candidate_id": selected_id,
        "line_spec": selected,
    }


def generate_sequel_planning_artifacts(
    workspace: str | Path,
    *,
    line_state: dict[str, Any] | None = None,
    module_presets: dict[str, dict[str, Any]] | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(workspace).resolve()
    outputs_dir = root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    closeout_card = build_closeout_card(root, line_state=line_state)
    candidate_lines = build_candidate_lines(
        closeout_card,
        module_presets=module_presets,
        workspace_root=workspace_root or root.parent,
    )
    line_spec = build_line_spec(candidate_lines, closeout_card=closeout_card)

    closeout_card_path = outputs_dir / "closeout_card.json"
    candidate_lines_path = outputs_dir / "candidate_lines.json"
    line_spec_path = outputs_dir / "line_spec.json"
    closeout_card_path.write_text(
        json.dumps(closeout_card, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    candidate_lines_path.write_text(
        json.dumps(candidate_lines, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    line_spec_path.write_text(
        json.dumps(line_spec, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    return {
        "closeout_card_path": str(closeout_card_path),
        "candidate_lines_path": str(candidate_lines_path),
        "line_spec_path": str(line_spec_path),
        "selected_candidate_id": candidate_lines.get("selected_candidate_id"),
    }


__all__ = [
    "build_candidate_lines",
    "build_closeout_card",
    "build_line_spec",
    "generate_sequel_planning_artifacts",
]
