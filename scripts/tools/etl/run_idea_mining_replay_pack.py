from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from brain_researcher.services.agent.hypothesis_candidate_cards import (
    build_candidate_cards_from_workflow_result,
)
from brain_researcher.services.tools.runner import execute_tool

try:
    from scripts.tools.etl.evaluate_idea_mining_failure_probes import (
        evaluate_probe_cards,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from evaluate_idea_mining_failure_probes import evaluate_probe_cards

POSITIVE_OR_GROUNDED_VERDICTS = {
    "supported",
    "refuted",
    "contradicted",
    "conflicting_evidence",
    "mixed_evidence",
    "challenged",
}
FAIL_CLOSED_TAGS = {
    "fallback_only_without_grounded_verification",
    "benchmark_candidate_ambiguity_unresolved",
    "missing_seed_or_workflow_provenance",
}
FAILURE_PATTERN_MAP = {
    "generic_candidate_hypothesis": "generic_concept_inflation_repeats",
    "benchmark_candidate_ambiguity_unresolved": "candidate_lane_ambiguity_repeats",
    "broad_strict_candidate_dependency": "candidate_lane_ambiguity_repeats",
    "fallback_only_without_grounded_verification": "fallback_overconfidence_repeats",
    "verification_error_present": "fallback_overconfidence_repeats",
}
FAILURE_LAYER_METADATA = {
    "SC-1": {
        "name": "semantic_collapse",
        "codification_target": "runtime_query_alignment_gate",
        "rule_text": (
            "Fail closed when required query roles disappear before card return."
        ),
    },
    "TA-1": {
        "name": "topology_attractor",
        "codification_target": "candidate_family_gate",
        "rule_text": (
            "Penalize or reject graph-convenient generic candidates that dominate "
            "mechanism-specific queries."
        ),
    },
    "TD-1": {
        "name": "template_degeneration",
        "codification_target": "template_rejection_gate",
        "rule_text": (
            "Reject transfer-template cards for queries that do not imply transfer "
            "or cross-task generalization."
        ),
    },
    "LV-1": {
        "name": "late_verifier",
        "codification_target": "verifier_shaping_gate",
        "rule_text": (
            "Do not treat late literature-backed verdict improvement as aligned idea "
            "generation when core query roles remain absent."
        ),
    },
}
DIMENSION_WEIGHTS = {
    "evidence_grounding": 3,
    "candidate_lane_separation": 2,
    "novelty_specificity": 2,
    "discriminating_testability": 2,
    "routing_clarity": 2,
    "provenance_integrity": 1,
}
REVIEW_LOG_FILES = {
    "review_rows": "candidate_card_review_rows.jsonl",
    "refinement_log": "candidate_card_refinement_log.jsonl",
    "routing_decisions": "candidate_card_routing_decisions.jsonl",
    "codified_failures": "candidate_card_codified_failures.jsonl",
    "failure_probe_run_evaluations": "idea_mining_failure_probe_run_evaluations.jsonl",
}


def _log_file_names(replay_pack_id: str) -> dict[str, str]:
    version_tag = "v1"
    parts = [part for part in replay_pack_id.split("_") if part]
    for part in parts:
        if part.startswith("v") and part[1:].isdigit():
            version_tag = part
            break
    return {
        **REVIEW_LOG_FILES,
        "outcome_ledger": f"idea_mining_outcome_ledger_{version_tag}.jsonl",
        "run_results": f"{replay_pack_id}_results.jsonl",
        "run_summary": f"{replay_pack_id}_run_summary.json",
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(dict(row), sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _safe_get(mapping: Mapping[str, Any] | None, key: str, default: Any = None) -> Any:
    if not isinstance(mapping, Mapping):
        return default
    return mapping.get(key, default)


def _resolve_manifest_path(path_value: str, *, base_dir: Path | None = None) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path.resolve()
    if base_dir is None:
        return path.resolve()
    return (base_dir / path).resolve()


def _load_failure_probe_lookup(
    manifest: Mapping[str, Any],
    *,
    manifest_dir: Path | None = None,
) -> dict[str, dict[str, Any]]:
    probes_jsonl = str(manifest.get("failure_probes_jsonl") or "").strip()
    probes_base_dir = manifest_dir
    if not probes_jsonl:
        nested_manifest_json = str(
            manifest.get("failure_regression_manifest_json")
            or manifest.get("failure_probe_manifest_json")
            or ""
        ).strip()
        if nested_manifest_json:
            nested_manifest_path = _resolve_manifest_path(
                nested_manifest_json,
                base_dir=manifest_dir,
            )
            nested_manifest = _load_json(nested_manifest_path)
            probes_jsonl = str(nested_manifest.get("probes_jsonl") or "").strip()
            probes_base_dir = nested_manifest_path.parent
    if not probes_jsonl:
        return {}

    probe_rows = _load_jsonl(
        _resolve_manifest_path(probes_jsonl, base_dir=probes_base_dir)
    )
    lookup: dict[str, dict[str, Any]] = {}
    for row in probe_rows:
        probe_id = str(row.get("probe_id") or "").strip()
        if probe_id:
            lookup[probe_id] = row
    return lookup


def _attach_failure_probe_evaluations(
    run_results: Sequence[Mapping[str, Any]],
    *,
    probe_lookup: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for raw_run in run_results:
        run = dict(raw_run)
        probe_id = str(run.get("failure_probe_id") or "").strip()
        evaluation = (
            dict(run.get("failure_probe_evaluation") or {})
            if isinstance(run.get("failure_probe_evaluation"), Mapping)
            else {}
        )
        if not evaluation and probe_id and probe_id in probe_lookup:
            evaluation = evaluate_probe_cards(
                probe_lookup[probe_id],
                run.get("cards") or [],
            )
        if evaluation:
            run["failure_probe_evaluation"] = evaluation
            run["failure_probe_status"] = str(evaluation.get("status") or "").strip() or None
            run["failure_layers_triggered"] = list(
                evaluation.get("failure_layers_triggered") or []
            )
        annotated.append(run)
    return annotated


def _build_failure_probe_run_rows(
    run_results: Sequence[Mapping[str, Any]],
    *,
    replay_pack_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in run_results:
        probe_id = str(run.get("failure_probe_id") or "").strip()
        evaluation = (
            dict(run.get("failure_probe_evaluation") or {})
            if isinstance(run.get("failure_probe_evaluation"), Mapping)
            else {}
        )
        if not probe_id and not evaluation:
            continue
        rows.append(
            {
                "schema_version": "idea-mining-failure-probe-run-eval-v1",
                "replay_pack_id": replay_pack_id,
                "run_spec_id": str(run.get("run_spec_id") or ""),
                "seed_id": str(run.get("seed_id") or ""),
                "query": str(run.get("query") or ""),
                "candidate_lane_mode": str(run.get("candidate_lane_mode") or ""),
                "raw_result_path": str(run.get("raw_path") or ""),
                "tool_status": str(run.get("tool_status") or ""),
                "tool_error": run.get("tool_error"),
                "failure_probe_id": probe_id or None,
                "failure_probe_label": str(evaluation.get("label") or "").strip() or None,
                "failure_probe_status": str(evaluation.get("status") or "").strip() or None,
                "cards_total": int(evaluation.get("cards_total") or len(run.get("cards") or [])),
                "allow_zero_card": bool(evaluation.get("allow_zero_card")),
                "zero_card_pass_closed": bool(evaluation.get("zero_card_pass_closed")),
                "failure_layers_triggered": list(
                    evaluation.get("failure_layers_triggered") or []
                ),
                "checks": dict(evaluation.get("checks") or {}),
                "role_coverage": dict(evaluation.get("role_coverage") or {}),
                "missing_required_roles": list(
                    evaluation.get("missing_required_roles") or []
                ),
                "anchor_family_coverage": dict(
                    evaluation.get("anchor_family_coverage") or {}
                ),
                "missing_anchor_families": list(
                    evaluation.get("missing_anchor_families") or []
                ),
                "template_hits": list(evaluation.get("template_hits") or []),
                "candidate_family_hits": list(
                    evaluation.get("candidate_family_hits") or []
                ),
            }
        )
    return rows


def _is_generic_text(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True
    generic_patterns = (
        "candidate node",
        "interesting connection",
        "out-of-distribution coupling",
        "ood hypothesis",
    )
    return any(pattern in lowered for pattern in generic_patterns)


def _has_substantive_test(card: Mapping[str, Any]) -> bool:
    minimal = str(card.get("minimal_discriminating_test") or "").strip()
    falsifier = str(card.get("falsifier_hint") or "").strip()
    if not minimal or not falsifier:
        return False
    return "candidate node" not in minimal.lower() and "candidate node" not in falsifier.lower()


def _extract_card_context(card: Mapping[str, Any]) -> dict[str, Any]:
    provenance = dict(card.get("provenance") or {}) if isinstance(card.get("provenance"), Mapping) else {}
    sampled = (
        dict(provenance.get("sampled_hypothesis_verification") or {})
        if isinstance(provenance.get("sampled_hypothesis_verification"), Mapping)
        else {}
    )
    controller = (
        dict(provenance.get("principle_controller") or {})
        if isinstance(provenance.get("principle_controller"), Mapping)
        else {}
    )
    kg_verification = (
        dict(card.get("kg_verification") or {})
        if isinstance(card.get("kg_verification"), Mapping)
        else dict(sampled.get("kg_verification") or {})
        if isinstance(sampled.get("kg_verification"), Mapping)
        else {}
    )
    return {
        "provenance": provenance,
        "sampled": sampled,
        "controller": controller,
        "kg_verification": kg_verification,
        "seed_id": str(provenance.get("seed_kg_id") or "").strip(),
        "candidate_kg_id": str(provenance.get("candidate_kg_id") or "").strip(),
        "relation_hint": str(provenance.get("relation_hint") or "").strip(),
        "source_workflow": str(provenance.get("source_workflow") or "").strip(),
        "candidate_lane_mode": str(sampled.get("candidate_lane_mode") or "").strip(),
        "candidate_lane_filtered": sampled.get("candidate_lane_filtered"),
        "verification_error": str(sampled.get("verification_error") or "").strip(),
        "verdict": str(kg_verification.get("verdict") or "").strip(),
    }


def _base_failure_tags(card: Mapping[str, Any], spec_mode: str) -> list[str]:
    ctx = _extract_card_context(card)
    tags: list[str] = []
    if not ctx["seed_id"] or not ctx["source_workflow"]:
        tags.append("missing_seed_or_workflow_provenance")
    if not ctx["candidate_lane_mode"] or ctx["candidate_lane_mode"] != spec_mode:
        tags.append("benchmark_candidate_ambiguity_unresolved")
    if ctx["verification_error"]:
        tags.append("verification_error_present")
    if not ctx["verdict"]:
        tags.append("fallback_only_without_grounded_verification")
    elif ctx["verdict"] == "insufficient_evidence":
        tags.append("insufficient_evidence_verdict")
    if not ctx["candidate_kg_id"] or _is_generic_text(str(card.get("hypothesis") or "")):
        tags.append("generic_candidate_hypothesis")
    if not _has_substantive_test(card):
        tags.append("weak_discriminating_test")
    return sorted(set(tags))


def _score_card(
    card: Mapping[str, Any],
    *,
    spec_mode: str,
    pair_delta: dict[str, Any] | None = None,
) -> dict[str, int]:
    ctx = _extract_card_context(card)
    verdict = ctx["verdict"]
    failure_tags = set(_base_failure_tags(card, spec_mode))
    novelty_signal = max(
        float(_safe_get(ctx["provenance"], "novelty_score", 0.0) or 0.0),
        float(_safe_get(ctx["provenance"], "ood_score", 0.0) or 0.0),
        float(_safe_get(ctx["provenance"], "principle_score", 0.0) or 0.0),
        float(_safe_get(ctx["provenance"], "leverage_score", 0.0) or 0.0),
    )

    if not verdict or "fallback_only_without_grounded_verification" in failure_tags:
        evidence_grounding = 0
    elif verdict in POSITIVE_OR_GROUNDED_VERDICTS:
        evidence_grounding = 3 if spec_mode == "strict" else 2
    else:
        evidence_grounding = 1

    if pair_delta and pair_delta.get("broad_grounded") and pair_delta.get("strict_insufficient"):
        if spec_mode == "broad":
            evidence_grounding = min(evidence_grounding, 2)
        else:
            evidence_grounding = min(evidence_grounding, 1)

    if ctx["candidate_lane_mode"] and ctx["candidate_lane_mode"] == spec_mode:
        if pair_delta and pair_delta.get("has_pair"):
            candidate_lane_separation = 3
        else:
            candidate_lane_separation = 2
    elif ctx["candidate_lane_mode"]:
        candidate_lane_separation = 1
    else:
        candidate_lane_separation = 0

    if (
        ctx["candidate_kg_id"]
        and ctx["relation_hint"]
        and not _is_generic_text(str(card.get("hypothesis") or ""))
    ):
        novelty_specificity = 3 if novelty_signal >= 0.65 else 2
    elif str(card.get("hypothesis") or "").strip():
        novelty_specificity = 1
    else:
        novelty_specificity = 0

    minimal = str(card.get("minimal_discriminating_test") or "").strip()
    falsifier = str(card.get("falsifier_hint") or "").strip()
    if minimal and falsifier:
        discriminating_testability = 3 if _has_substantive_test(card) else 2
    elif minimal or falsifier:
        discriminating_testability = 1
    else:
        discriminating_testability = 0

    has_full_provenance = all(
        [
            ctx["seed_id"],
            ctx["source_workflow"],
            ctx["candidate_kg_id"],
            ctx["candidate_lane_mode"],
        ]
    )
    if has_full_provenance:
        provenance_integrity = 3
    elif ctx["seed_id"] and ctx["source_workflow"]:
        provenance_integrity = 2
    elif ctx["seed_id"] or ctx["source_workflow"]:
        provenance_integrity = 1
    else:
        provenance_integrity = 0

    if failure_tags & FAIL_CLOSED_TAGS:
        routing_clarity = 0
    elif evidence_grounding >= 2 and novelty_specificity >= 2:
        routing_clarity = 3
    elif novelty_specificity >= 2 or discriminating_testability >= 2:
        routing_clarity = 2
    else:
        routing_clarity = 1

    return {
        "evidence_grounding": evidence_grounding,
        "candidate_lane_separation": candidate_lane_separation,
        "novelty_specificity": novelty_specificity,
        "discriminating_testability": discriminating_testability,
        "routing_clarity": routing_clarity,
        "provenance_integrity": provenance_integrity,
    }


def _raw_total(scores: Mapping[str, int]) -> int:
    return sum(int(v) for v in scores.values())


def _weighted_total(scores: Mapping[str, int]) -> int:
    return sum(int(scores[k]) * int(weight) for k, weight in DIMENSION_WEIGHTS.items())


def _route_row(
    row: Mapping[str, Any],
    *,
    repeated_patterns: Counter[str],
) -> tuple[str, str]:
    failure_tags = set(row.get("failure_tags") or [])
    failure_layers = {
        str(layer).strip()
        for layer in (row.get("failure_layers_triggered") or [])
        if str(layer).strip()
    }
    mapped_patterns = [
        FAILURE_PATTERN_MAP[tag]
        for tag in failure_tags
        if tag in FAILURE_PATTERN_MAP and repeated_patterns[FAILURE_PATTERN_MAP[tag]] >= 2
    ]
    raw_total = int(row.get("raw_total", 0))
    scores = row.get("scores") or {}
    evidence_grounding = int(scores.get("evidence_grounding", 0))
    routing_clarity = int(scores.get("routing_clarity", 0))

    if "LV-1" in failure_layers and failure_layers.intersection({"SC-1", "TA-1", "TD-1"}):
        return "codify_failure_pattern", "Late verifier rescue observed after upstream semantic degeneration"
    if {"TA-1", "TD-1"}.issubset(failure_layers):
        return "codify_failure_pattern", "Repeated topology-attractor plus template-degeneration failure"
    if {"SC-1", "TA-1"}.issubset(failure_layers):
        return "retire_from_candidate_pack", "Query semantics collapsed and candidate set drifted to topology attractors"
    if failure_layers == {"SC-1"}:
        return "hold_for_refinement", "Query-role loss detected without downstream cascade"
    if failure_layers == {"LV-1"}:
        return "hold_for_refinement", "Verifier improved late but upstream alignment remained fragile"

    if failure_tags & FAIL_CLOSED_TAGS:
        if mapped_patterns:
            return "codify_failure_pattern", f"Repeated fail-closed pattern: {mapped_patterns[0]}"
        return "retire_from_candidate_pack", "Fail-closed provenance or grounding failure"

    if (
        evidence_grounding <= 1
        and int(scores.get("novelty_specificity", 0)) >= 2
        and int(scores.get("discriminating_testability", 0)) >= 2
        and int(scores.get("provenance_integrity", 0)) >= 2
        and "generic_candidate_hypothesis" not in failure_tags
        and "weak_discriminating_test" not in failure_tags
    ):
        if mapped_patterns:
            return "codify_failure_pattern", f"Repeated bounded failure pattern: {mapped_patterns[0]}"
        return "hold_for_refinement", "Plausible candidate with weak grounding but clear refinement path"

    if (
        row.get("paired_broad_strict_delta")
        and row.get("candidate_lane_mode") == "broad"
        and row.get("verdict") in POSITIVE_OR_GROUNDED_VERDICTS
    ):
        return "hold_for_refinement", "Broad-only grounded signal drops under strict replay"

    if raw_total >= 14 and evidence_grounding >= 2 and routing_clarity >= 2:
        return "promote_for_candidate_review", "Meets v1 rubric promote threshold"
    if 9 <= raw_total <= 13:
        if mapped_patterns:
            return "codify_failure_pattern", f"Repeated bounded failure pattern: {mapped_patterns[0]}"
        return "hold_for_refinement", "Plausible card with incomplete grounding or routing"
    if mapped_patterns:
        return "codify_failure_pattern", f"Repeated low-score failure pattern: {mapped_patterns[0]}"
    return "retire_from_candidate_pack", "Low-score or overly generic candidate card"


def _refinement_actions(row: Mapping[str, Any]) -> list[str]:
    route = str(row.get("route") or "")
    scores = row.get("scores") or {}
    if route == "promote_for_candidate_review":
        return []
    actions: list[str] = []
    if int(scores.get("evidence_grounding", 0)) <= 1:
        actions.append("strengthen_claim_first_grounding")
    if int(scores.get("candidate_lane_separation", 0)) <= 1:
        actions.append("clarify_candidate_lane_boundary")
    if int(scores.get("novelty_specificity", 0)) <= 1:
        actions.append("sharpen_hypothesis_scope")
    if int(scores.get("discriminating_testability", 0)) <= 2:
        actions.append("tighten_discriminating_test")
    if int(scores.get("routing_clarity", 0)) <= 1:
        actions.append("state_explicit_route")
    if int(scores.get("provenance_integrity", 0)) <= 1:
        actions.append("repair_provenance_surface")
    if route == "codify_failure_pattern":
        actions.append("codify_failure_pattern")
    return sorted(set(actions))


def _changed_fields(actions: Sequence[str]) -> list[str]:
    mapping = {
        "strengthen_claim_first_grounding": "kg_verification",
        "clarify_candidate_lane_boundary": "provenance.sampled_hypothesis_verification",
        "sharpen_hypothesis_scope": "hypothesis",
        "tighten_discriminating_test": "minimal_discriminating_test",
        "state_explicit_route": "routing_recommendation",
        "repair_provenance_surface": "provenance",
        "codify_failure_pattern": "failure_pattern",
    }
    fields = [mapping[action] for action in actions if action in mapping]
    return sorted(set(fields))


def _pair_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("seed_id") or "").strip(),
        str(row.get("candidate_kg_id") or "").strip(),
        str(row.get("hypothesis") or "").strip(),
    )


def _annotate_pair_deltas(review_rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in review_rows:
        grouped[_pair_key(row)][str(row.get("candidate_lane_mode") or "")] = row

    pair_delta_lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key, lane_rows in grouped.items():
        broad = lane_rows.get("broad")
        strict = lane_rows.get("strict")
        broad_verdict = str(_safe_get(broad, "verdict", "") or "")
        strict_verdict = str(_safe_get(strict, "verdict", "") or "")
        broad_grounded = broad_verdict in POSITIVE_OR_GROUNDED_VERDICTS
        strict_grounded = strict_verdict in POSITIVE_OR_GROUNDED_VERDICTS
        strict_insufficient = strict_verdict == "insufficient_evidence"
        paired = broad is not None and strict is not None
        delta = bool(
            paired
            and (
                broad_verdict != strict_verdict
                or int(_safe_get(broad, "candidate_lane_filtered", 0) or 0)
                != int(_safe_get(strict, "candidate_lane_filtered", 0) or 0)
            )
        )
        pair_delta_lookup[key] = {
            "has_pair": paired,
            "has_delta": delta,
            "broad_grounded": broad_grounded,
            "strict_grounded": strict_grounded,
            "strict_insufficient": strict_insufficient,
            "broad_verdict": broad_verdict or None,
            "strict_verdict": strict_verdict or None,
        }
    return pair_delta_lookup


def _run_example(example: Mapping[str, Any], raw_dir: Path) -> dict[str, Any]:
    params = {
        "query": str(example.get("query") or "").strip(),
        "seed_kg_ids": [str(example.get("seed_id") or "").strip()],
        "top_k": int(example.get("top_k") or 5),
        "n_samples": int(example.get("n_samples") or 2),
        "controller_mode": str(example.get("controller_mode") or "legacy").strip() or "legacy",
        "candidate_lane_mode": str(example.get("candidate_lane_mode") or "broad").strip() or "broad",
    }
    result = execute_tool(
        str(example.get("workflow_id") or "workflow_hypothesis_candidate_cards"),
        params,
        emit_execution_pack=False,
    )
    workflow_result = result.data if isinstance(result.data, Mapping) else {}
    cards: list[dict[str, Any]] = []
    if result.status == "success" and workflow_result:
        cards = build_candidate_cards_from_workflow_result(
            workflow_result,
            query=params["query"],
            top_n=int(example.get("n_samples") or 2),
        )

    raw_payload = {
        "run_spec": dict(example),
        "tool_status": result.status,
        "tool_error": result.error,
        "workflow_result": workflow_result,
        "candidate_cards": cards,
    }
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{example['run_spec_id']}.json"
    _write_json(raw_path, raw_payload)
    return {
        "run_spec_id": str(example.get("run_spec_id") or ""),
        "seed_id": str(example.get("seed_id") or ""),
        "query": str(example.get("query") or ""),
        "candidate_lane_mode": str(example.get("candidate_lane_mode") or ""),
        "failure_probe_id": str(example.get("failure_probe_id") or "").strip() or None,
        "tool_status": result.status,
        "tool_error": result.error,
        "cards": cards,
        "raw_path": str(raw_path),
        "workflow": workflow_result.get("workflow") if isinstance(workflow_result, Mapping) else None,
        "steps_present": sorted((workflow_result.get("steps") or {}).keys()) if isinstance(workflow_result, Mapping) else [],
    }


def _build_review_rows(
    run_results: Sequence[Mapping[str, Any]],
    *,
    replay_pack_id: str,
) -> list[dict[str, Any]]:
    review_rows: list[dict[str, Any]] = []
    for run in run_results:
        for card in run.get("cards") or []:
            ctx = _extract_card_context(card)
            row = {
                "schema_version": "v1",
                "template_only": False,
                "replay_pack_id": replay_pack_id,
                "run_spec_id": run["run_spec_id"],
                "seed_id": run["seed_id"],
                "query": run["query"],
                "failure_probe_id": run.get("failure_probe_id"),
                "failure_probe_status": run.get("failure_probe_status"),
                "candidate_card_id": str(card.get("card_id") or ""),
                "candidate_lane_mode": run["candidate_lane_mode"],
                "title": str(card.get("title") or ""),
                "hypothesis": str(card.get("hypothesis") or ""),
                "candidate_kg_id": ctx["candidate_kg_id"],
                "relation_hint": ctx["relation_hint"],
                "verdict": ctx["verdict"] or None,
                "candidate_lane_filtered": ctx["candidate_lane_filtered"],
                "source_workflow": ctx["source_workflow"],
                "raw_result_path": run["raw_path"],
                "scores": {},
                "raw_total": 0,
                "weighted_total": 0,
                "failure_tags": _base_failure_tags(card, str(run["candidate_lane_mode"])),
                "failure_layers_triggered": list(run.get("failure_layers_triggered") or []),
                "failure_probe_checks": dict(
                    _safe_get(run.get("failure_probe_evaluation"), "checks", {})
                    if isinstance(run.get("failure_probe_evaluation"), Mapping)
                    else {}
                ),
                "missing_required_roles": list(
                    _safe_get(run.get("failure_probe_evaluation"), "missing_required_roles", [])
                    if isinstance(run.get("failure_probe_evaluation"), Mapping)
                    else []
                ),
                "missing_anchor_families": list(
                    _safe_get(run.get("failure_probe_evaluation"), "missing_anchor_families", [])
                    if isinstance(run.get("failure_probe_evaluation"), Mapping)
                    else []
                ),
                "template_hits": list(
                    _safe_get(run.get("failure_probe_evaluation"), "template_hits", [])
                    if isinstance(run.get("failure_probe_evaluation"), Mapping)
                    else []
                ),
                "candidate_family_hits": list(
                    _safe_get(run.get("failure_probe_evaluation"), "candidate_family_hits", [])
                    if isinstance(run.get("failure_probe_evaluation"), Mapping)
                    else []
                ),
                "reviewer_notes": "",
                "_card_payload": dict(card),
            }
            review_rows.append(row)

    pair_lookup = _annotate_pair_deltas(review_rows)
    for row in review_rows:
        pair_delta = pair_lookup.get(_pair_key(row), {})
        if pair_delta.get("has_delta") and pair_delta.get("broad_grounded") and pair_delta.get("strict_insufficient"):
            row["failure_tags"] = sorted(set(row["failure_tags"]) | {"broad_strict_candidate_dependency"})
        row["paired_broad_strict_delta"] = bool(pair_delta.get("has_delta"))
        row["pair_summary"] = pair_delta
        scores = _score_card(
            row["_card_payload"],
            spec_mode=str(row["candidate_lane_mode"] or ""),
            pair_delta=pair_delta,
        )
        row["scores"] = scores
        row["raw_total"] = _raw_total(scores)
        row["weighted_total"] = _weighted_total(scores)
        row["reviewer_notes"] = (
            f"First-pass replay review for {row['candidate_lane_mode']} mode; "
            f"verdict={row.get('verdict') or 'missing'}, raw_total={row['raw_total']}."
        )
        row.pop("_card_payload", None)
    return review_rows


def _build_logs(review_rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    pattern_counter: Counter[str] = Counter()
    for row in review_rows:
        for tag in row.get("failure_tags") or []:
            mapped = FAILURE_PATTERN_MAP.get(tag)
            if mapped:
                pattern_counter[mapped] += 1

    routing_rows: list[dict[str, Any]] = []
    refinement_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    codified_failures: dict[str, dict[str, Any]] = {}

    for row in review_rows:
        route, reason = _route_row(row, repeated_patterns=pattern_counter)
        actions = _refinement_actions({**row, "route": route})
        routing_row = {
            "schema_version": "v1",
            "template_only": False,
            "candidate_card_id": row["candidate_card_id"],
            "run_spec_id": row["run_spec_id"],
            "seed_id": row["seed_id"],
            "failure_probe_id": row.get("failure_probe_id"),
            "failure_probe_status": row.get("failure_probe_status"),
            "failure_layers_triggered": list(row.get("failure_layers_triggered") or []),
            "route": route,
            "decision_reason": reason,
            "reviewer": "idea_mining_replay_pack_v1_first_pass",
            "candidate_lane_mode": row["candidate_lane_mode"],
            "promotion_blocked_from_benchmark": True,
            "raw_total": row["raw_total"],
            "weighted_total": row["weighted_total"],
            "failure_tags": row["failure_tags"],
        }
        routing_rows.append(routing_row)

        refinement_rows.append(
            {
                "schema_version": "v1",
                "template_only": False,
                "candidate_card_id": row["candidate_card_id"],
                "run_spec_id": row["run_spec_id"],
                "pre_refinement_summary": row["hypothesis"],
                "refinement_actions": actions,
                "post_refinement_summary": (
                    row["hypothesis"]
                    if not actions
                    else f"{row['hypothesis']} | next_actions={','.join(actions)}"
                ),
                "changed_fields": _changed_fields(actions),
                "preserved_candidate_lane_mode": row["candidate_lane_mode"],
                "preserved_candidate_provenance": bool(row["source_workflow"] and row["seed_id"]),
            }
        )

        ledger_rows.append(
            {
                "schema_version": "v1",
                "template_only": False,
                "seed_id": row["seed_id"],
                "candidate_card_id": row["candidate_card_id"],
                "candidate_lane_mode": row["candidate_lane_mode"],
                "review_status": "scored_first_pass",
                "route": route,
                "benchmark_admission_allowed": False,
                "notes": reason,
            }
        )

        if route == "codify_failure_pattern":
            for layer_id in row.get("failure_layers_triggered") or []:
                normalized_layer_id = str(layer_id or "").strip()
                layer_meta = FAILURE_LAYER_METADATA.get(normalized_layer_id)
                if not normalized_layer_id or layer_meta is None:
                    continue
                existing_layer = codified_failures.get(normalized_layer_id)
                if existing_layer is None:
                    codified_failures[normalized_layer_id] = {
                        "schema_version": "v1",
                        "template_only": False,
                        "failure_pattern_id": normalized_layer_id,
                        "failure_pattern_name": layer_meta["name"],
                        "failure_layer_id": normalized_layer_id,
                        "classification": "failure_layer",
                        "source_candidate_card_ids": [row["candidate_card_id"]],
                        "source_probe_ids": [
                            str(row.get("failure_probe_id") or "").strip()
                        ]
                        if str(row.get("failure_probe_id") or "").strip()
                        else [],
                        "proposed_codification_target": layer_meta["codification_target"],
                        "proposed_rule_text": layer_meta["rule_text"],
                        "status": "draft",
                    }
                else:
                    existing_layer["source_candidate_card_ids"].append(row["candidate_card_id"])
                    if str(row.get("failure_probe_id") or "").strip():
                        existing_layer.setdefault("source_probe_ids", []).append(
                            str(row.get("failure_probe_id") or "").strip()
                        )
            for tag in row["failure_tags"]:
                mapped = FAILURE_PATTERN_MAP.get(tag)
                if not mapped or pattern_counter[mapped] < 2:
                    continue
                existing = codified_failures.get(mapped)
                if existing is None:
                    codified_failures[mapped] = {
                        "schema_version": "v1",
                        "template_only": False,
                        "failure_pattern_id": mapped,
                        "failure_pattern_name": mapped,
                        "classification": "legacy_pattern",
                        "source_candidate_card_ids": [row["candidate_card_id"]],
                        "proposed_codification_target": "workflow_gate",
                        "proposed_rule_text": f"Flag repeated pattern `{mapped}` during first-pass replay review.",
                        "status": "draft",
                    }
                else:
                    existing["source_candidate_card_ids"].append(row["candidate_card_id"])

    codified_rows = list(codified_failures.values())
    for row in codified_rows:
        row["source_candidate_card_ids"] = sorted(set(row["source_candidate_card_ids"]))
        if isinstance(row.get("source_probe_ids"), list):
            row["source_probe_ids"] = sorted(
                {
                    str(item).strip()
                    for item in row.get("source_probe_ids") or []
                    if str(item).strip()
                }
            )
    return routing_rows, refinement_rows, ledger_rows, codified_rows


def _summary(
    manifest: Mapping[str, Any],
    run_results: Sequence[Mapping[str, Any]],
    failure_probe_run_rows: Sequence[Mapping[str, Any]],
    review_rows: Sequence[Mapping[str, Any]],
    routing_rows: Sequence[Mapping[str, Any]],
    codified_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    route_counter = Counter(str(row.get("route") or "") for row in routing_rows)
    tag_counter = Counter(tag for row in review_rows for tag in row.get("failure_tags") or [])
    layer_counter = Counter(
        layer
        for row in review_rows
        for layer in row.get("failure_layers_triggered") or []
    )
    probe_run_layer_counter = Counter(
        layer
        for row in failure_probe_run_rows
        for layer in row.get("failure_layers_triggered") or []
    )
    probe_status_counter = Counter(
        str(row.get("failure_probe_status") or "")
        for row in failure_probe_run_rows
        if str(row.get("failure_probe_status") or "").strip()
    )
    zero_card_pass_closed_runs = sum(
        1 for row in failure_probe_run_rows if bool(row.get("zero_card_pass_closed"))
    )
    pair_counter = Counter()
    seeds_with_delta: set[str] = set()
    seen_pairs: set[tuple[str, str, str]] = set()
    for row in review_rows:
        pair_key = _pair_key(row)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        if row.get("pair_summary", {}).get("has_pair"):
            pair_counter["pairs_total"] += 1
            if row.get("pair_summary", {}).get("has_delta"):
                pair_counter["pairs_with_delta"] += 1
                if row.get("seed_id"):
                    seeds_with_delta.add(str(row["seed_id"]))

    return {
        "schema_version": "idea-mining-replay-run-summary-v1",
        "replay_pack_id": manifest.get("replay_pack_id"),
        "workflow_id": manifest.get("workflow_id"),
        "runs_total": len(run_results),
        "runs_succeeded": sum(1 for row in run_results if row.get("tool_status") == "success"),
        "runs_failed": sum(1 for row in run_results if row.get("tool_status") != "success"),
        "candidate_cards_total": sum(len(row.get("cards") or []) for row in run_results),
        "failure_probe_runs_total": len(failure_probe_run_rows),
        "review_rows_total": len(review_rows),
        "route_counts": dict(route_counter),
        "failure_tag_counts": dict(tag_counter),
        "failure_layer_counts": dict(layer_counter),
        "failure_probe_run_layer_counts": dict(probe_run_layer_counter),
        "failure_probe_status_counts": dict(probe_status_counter),
        "zero_card_pass_closed_runs": zero_card_pass_closed_runs,
        "pair_counts": dict(pair_counter),
        "seeds_with_meaningful_delta": sorted(seeds_with_delta),
        "codified_failure_patterns_total": len(codified_rows),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the first-pass idea-mining replay pack.")
    parser.add_argument(
        "--manifest-json",
        required=True,
        help="Path to idea_mining_replay_pack_v1_manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where logs and summary will be written. Defaults to manifest parent.",
    )
    parser.add_argument(
        "--reuse-run-results-jsonl",
        default=None,
        help="Optional precomputed run-results JSONL to reuse instead of rerunning workflows.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    manifest_path = Path(args.manifest_json).expanduser().resolve()
    manifest = _load_json(manifest_path)
    replay_pack_id = str(manifest.get("replay_pack_id") or "idea_mining_replay_pack_v1")
    log_files = _log_file_names(replay_pack_id)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else manifest_path.parent
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    reuse_run_results_jsonl = (
        Path(args.reuse_run_results_jsonl).expanduser().resolve()
        if args.reuse_run_results_jsonl
        else None
    )
    if reuse_run_results_jsonl is not None:
        run_results = _load_jsonl(reuse_run_results_jsonl)
    else:
        examples_path = _resolve_manifest_path(
            str(manifest.get("examples_jsonl") or ""),
            base_dir=manifest_path.parent,
        )
        examples = _load_jsonl(examples_path)
        raw_dir = output_dir / "raw_workflow_results"
        run_results = [_run_example(example, raw_dir) for example in examples]
    probe_lookup = _load_failure_probe_lookup(
        manifest,
        manifest_dir=manifest_path.parent,
    )
    if probe_lookup:
        run_results = _attach_failure_probe_evaluations(
            run_results,
            probe_lookup=probe_lookup,
        )
    failure_probe_run_rows = _build_failure_probe_run_rows(
        run_results,
        replay_pack_id=replay_pack_id,
    )
    review_rows = _build_review_rows(
        run_results,
        replay_pack_id=replay_pack_id,
    )
    routing_rows, refinement_rows, ledger_rows, codified_rows = _build_logs(review_rows)
    run_summary = _summary(
        manifest,
        run_results,
        failure_probe_run_rows,
        review_rows,
        routing_rows,
        codified_rows,
    )

    _write_jsonl(output_dir / log_files["review_rows"], review_rows)
    _write_jsonl(output_dir / log_files["refinement_log"], refinement_rows)
    _write_jsonl(output_dir / log_files["routing_decisions"], routing_rows)
    _write_jsonl(output_dir / log_files["codified_failures"], codified_rows)
    _write_jsonl(
        output_dir / log_files["failure_probe_run_evaluations"],
        failure_probe_run_rows,
    )
    _write_jsonl(output_dir / log_files["outcome_ledger"], ledger_rows)
    _write_jsonl(output_dir / log_files["run_results"], run_results)
    _write_json(output_dir / log_files["run_summary"], run_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
