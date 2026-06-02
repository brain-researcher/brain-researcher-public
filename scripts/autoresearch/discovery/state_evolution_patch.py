#!/usr/bin/env python3
"""Idempotent patch: add a no-op baseline-pivot gate to build_research_state.

Target: ``scripts/controller/build_research_state.py`` on the VM.

This patch does two things:
1. Carries a compact manifest condition signature in branch evidence so parent
   and child rounds can tell whether a baseline intervention actually changed
   the selected condition set.
2. Converts repeated no-op ``pivot_baseline`` follow-ups into ``tighten`` when
   the best contrast stays stable and the condition signature does not change.
   That forces a different intervention instead of spinning forever on the
   same baseline.
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    "/data/brain_researcher/research/discovery/project/scripts/controller/build_research_state.py"
)


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "baseline_pivot_noop" in src:
        print("already patched", file=sys.stderr)
        return 0

    helper_anchor = (
        "def _write_json(path: Path, payload: dict[str, Any]) -> None:\n"
        "    path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    path.write_text(\n"
        "        json.dumps(payload, indent=2, ensure_ascii=False) + \"\\n\",\n"
        "        encoding=\"utf-8\",\n"
        "    )\n"
    )
    helper_inject = helper_anchor + (
        "\n"
        "def _condition_signature(condition_counts: dict[str, Any] | None) -> str:\n"
        "    counts = condition_counts if isinstance(condition_counts, dict) else {}\n"
        "    return \"|\".join(\n"
        "        f\"{name}:{counts[name]}\" for name in sorted(str(key) for key in counts)\n"
        "    )\n"
    )
    if helper_anchor not in src:
        print("helper anchor not found", file=sys.stderr)
        return 2
    src = src.replace(helper_anchor, helper_inject, 1)

    infer_anchor = (
        "    completed_counts = source_run_summary.get(\n"
        "        \"per_task_completed_condition_counts\",\n"
        "        {},\n"
        "    ).get(task_id, {})\n"
        "\n"
        "    branch_payload: dict[str, Any] = {\n"
    )
    infer_inject = (
        "    completed_counts = source_run_summary.get(\n"
        "        \"per_task_completed_condition_counts\",\n"
        "        {},\n"
        "    ).get(task_id, {})\n"
        "    manifest_condition_counts = manifest.get(\"condition_counts\", {})\n"
        "\n"
        "    branch_payload: dict[str, Any] = {\n"
    )
    if infer_anchor not in src:
        print("infer anchor not found", file=sys.stderr)
        return 2
    src = src.replace(infer_anchor, infer_inject, 1)

    evidence_anchor = (
        "            \"completed_condition_counts\": completed_counts,\n"
        "            \"expected_rois\": manifest.get(\"expected_rois\", []),\n"
        "        },\n"
    )
    evidence_inject = (
        "            \"completed_condition_counts\": completed_counts,\n"
        "            \"condition_signature\": _condition_signature(manifest_condition_counts),\n"
        "            \"expected_rois\": manifest.get(\"expected_rois\", []),\n"
        "        },\n"
    )
    if evidence_anchor not in src:
        print("evidence anchor not found", file=sys.stderr)
        return 2
    src = src.replace(evidence_anchor, evidence_inject, 1)

    enrich_anchor = (
        "    evidence.setdefault(\"manifest_path\", str(Path(manifest[\"_manifest_path\"]).resolve()))\n"
        "    evidence.setdefault(\"current_task_id\", manifest.get(\"task_id\"))\n"
        "    evidence.setdefault(\"priority\", manifest.get(\"priority\"))\n"
        "    evidence.setdefault(\"best_run\", str(run_root.resolve()))\n"
    )
    enrich_inject = (
        "    evidence.setdefault(\"manifest_path\", str(Path(manifest[\"_manifest_path\"]).resolve()))\n"
        "    evidence.setdefault(\"current_task_id\", manifest.get(\"task_id\"))\n"
        "    evidence.setdefault(\"priority\", manifest.get(\"priority\"))\n"
        "    evidence.setdefault(\"best_run\", str(run_root.resolve()))\n"
        "    evidence.setdefault(\n"
        "        \"condition_signature\",\n"
        "        _condition_signature(manifest.get(\"condition_counts\", {})),\n"
        "    )\n"
    )
    if enrich_anchor not in src:
        print("enrich anchor not found", file=sys.stderr)
        return 2
    src = src.replace(enrich_anchor, enrich_inject, 1)

    parent_anchor = (
        "    evidence[\"parent_round_id\"] = parent_round_id\n"
        "    evidence[\"parent_best_contrast\"] = parent_best_contrast\n"
        "    evidence[\"parent_best_score\"] = _best_score(parent_branch)\n"
        "    evidence[\"score_delta_vs_parent\"] = _best_score(branch) - _best_score(parent_branch)\n"
        "    evidence[\"best_contrast_stable_vs_parent\"] = bool(\n"
        "        current_best_contrast and current_best_contrast == parent_best_contrast\n"
        "    )\n"
        "    evidence[\"failure_modes_persisted_vs_parent\"] = sorted(\n"
        "        current_failures & parent_failures\n"
        "    )\n"
    )
    parent_inject = (
        "    current_condition_signature = str(evidence.get(\"condition_signature\") or \"\")\n"
        "    parent_condition_signature = str(parent_evidence.get(\"condition_signature\") or \"\")\n"
        "    evidence[\"parent_round_id\"] = parent_round_id\n"
        "    evidence[\"parent_best_contrast\"] = parent_best_contrast\n"
        "    evidence[\"parent_best_score\"] = _best_score(parent_branch)\n"
        "    evidence[\"score_delta_vs_parent\"] = _best_score(branch) - _best_score(parent_branch)\n"
        "    evidence[\"best_contrast_stable_vs_parent\"] = bool(\n"
        "        current_best_contrast and current_best_contrast == parent_best_contrast\n"
        "    )\n"
        "    evidence[\"parent_condition_signature\"] = parent_condition_signature\n"
        "    evidence[\"condition_signature_stable_vs_parent\"] = bool(\n"
        "        current_condition_signature\n"
        "        and current_condition_signature == parent_condition_signature\n"
        "    )\n"
        "    evidence[\"failure_modes_persisted_vs_parent\"] = sorted(\n"
        "        current_failures & parent_failures\n"
        "    )\n"
    )
    if parent_anchor not in src:
        print("parent anchor not found", file=sys.stderr)
        return 2
    src = src.replace(parent_anchor, parent_inject, 1)

    evolve_anchor = (
        "    persistent_failures = set(evidence.get(\"failure_modes_persisted_vs_parent\", []))\n"
        "    stable_best = bool(evidence.get(\"best_contrast_stable_vs_parent\"))\n"
        "    parent_decision = str(evidence.get(\"parent_decision\") or parent_branch.get(\"decision\") or \"\")\n"
        "    score_delta = float(evidence.get(\"score_delta_vs_parent\") or 0.0)\n"
    )
    evolve_inject = (
        "    persistent_failures = set(evidence.get(\"failure_modes_persisted_vs_parent\", []))\n"
        "    stable_best = bool(evidence.get(\"best_contrast_stable_vs_parent\"))\n"
        "    condition_signature_stable = bool(\n"
        "        evidence.get(\"condition_signature_stable_vs_parent\")\n"
        "    )\n"
        "    parent_decision = str(evidence.get(\"parent_decision\") or parent_branch.get(\"decision\") or \"\")\n"
        "    score_delta = float(evidence.get(\"score_delta_vs_parent\") or 0.0)\n"
    )
    if evolve_anchor not in src:
        print("evolve anchor not found", file=sys.stderr)
        return 2
    src = src.replace(evolve_anchor, evolve_inject, 1)

    rule_anchor = "    # Rule B (general): confound_persistence"
    rule_inject = (
        "    # Rule B0 (general): baseline_pivot_noop — a baseline pivot that\n"
        "    # preserved the exact same condition set under the same best\n"
        "    # contrast did not actually change the intervention surface.\n"
        "    # Force a different tightening action instead of spinning on\n"
        "    # another change_baseline round.\n"
        "    if (\n"
        "        not mutated\n"
        "        and parent_decision == \"pivot_baseline\"\n"
        "        and stable_best\n"
        "        and condition_signature_stable\n"
        "    ):\n"
        "        branch[\"failure_modes\"] = list(\n"
        "            dict.fromkeys(\n"
        "                list(branch.get(\"failure_modes\", [])) + [\"baseline_pivot_noop\"]\n"
        "            )\n"
        "        )\n"
        "        branch[\"decision\"] = \"tighten\"\n"
        "        branch[\"decision_rationale\"] = (\n"
        "            \"Baseline pivot preserved the same condition set while the \"\n"
        "            \"best contrast stayed stable, so the next round should force \"\n"
        "            \"a different tightening intervention instead of another \"\n"
        "            \"change_baseline round.\"\n"
        "        )\n"
        "        mutated = True\n"
        "\n"
        "    # Rule B (general): confound_persistence"
    )
    if rule_anchor not in src:
        print("rule anchor not found", file=sys.stderr)
        return 2
    src = src.replace(rule_anchor, rule_inject, 1)

    TARGET.write_text(src, encoding="utf-8")
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
