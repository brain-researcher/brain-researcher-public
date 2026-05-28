from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.agent.harness_scaffolding import (
    scaffold_harness_task,
)
from brain_researcher.services.agent.repo_repair_context import (
    generate_repo_repair_context,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_scaffold_harness_task_creates_draft_task_and_registrations(tmp_path):
    benchmark_root = tmp_path / "benchmark"
    (benchmark_root / "harbor_json").mkdir(parents=True, exist_ok=True)
    (benchmark_root / "configs" / "autoresearch").mkdir(parents=True, exist_ok=True)
    (benchmark_root / "tests").mkdir(parents=True, exist_ok=True)
    _write_json(benchmark_root / "harbor_json" / "neuroimage-code-bench.harbor.json", {"tasks": []})
    _write_json(benchmark_root / "BrainRearcherBenchmark_MicroTooling.json", [])
    (benchmark_root / "configs" / "autoresearch" / "motif_slices.yaml").write_text(
        "\n".join(
            [
                "motifs:",
                "  wrong_tool_or_workflow_routing:",
                "    task_ids:",
                "      - HARNESS-008",
                "    canary_task_ids:",
                "      - HARNESS-008",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (benchmark_root / "configs" / "autoresearch" / "canary_slice.yaml").write_text(
        "task_ids:\n  - HARNESS-008\n",
        encoding="utf-8",
    )
    (benchmark_root / "tests" / "test_benchmark_task_cards.py").write_text(
        "import json\nfrom benchmark_task_cards import build_task_card\n",
        encoding="utf-8",
    )

    result = scaffold_harness_task(
        "wrong_tool_or_workflow_routing",
        task_id="HARNESS-099",
        benchmark_root=benchmark_root,
        activate=False,
    )

    assert result.task_id == "HARNESS-099"
    assert result.activation_mode == "draft"
    assert any("task.toml" in path for path in result.created_paths)
    assert any("Promote scaffold_task_ids" in warning for warning in result.warnings)

    task_root = benchmark_root / "harbor" / "HARNESS-099"
    assert (task_root / "task.toml").exists()
    assert (task_root / "instruction.md").exists()
    assert (task_root / "solution" / "solve.sh").exists()
    assert (task_root / "tests" / "test_outputs.py").exists()
    assert (task_root / "tests" / "semantic_contract.json").exists()
    assert (task_root / "scaffold_manifest.json").exists()

    motif_yaml = (benchmark_root / "configs" / "autoresearch" / "motif_slices.yaml").read_text(
        encoding="utf-8"
    )
    assert "scaffold_task_ids:" in motif_yaml
    assert "scaffold_canary_task_ids:" in motif_yaml
    assert "HARNESS-099" in motif_yaml

    canary_yaml = (benchmark_root / "configs" / "autoresearch" / "canary_slice.yaml").read_text(
        encoding="utf-8"
    )
    assert "scaffold_task_ids:" in canary_yaml
    assert "HARNESS-099" in canary_yaml

    harbor_payload = json.loads(
        (benchmark_root / "harbor_json" / "neuroimage-code-bench.harbor.json").read_text(
            encoding="utf-8"
        )
    )
    harbor_entry = next(task for task in harbor_payload["tasks"] if task["id"] == "HARNESS-099")
    assert harbor_entry["metadata"]["scaffold_status"] == "draft"
    assert (
        harbor_entry["metadata"]["semantic_contract_profile"]
        == "harness_wrong_tool_or_workflow_routing_scaffold_v0"
    )

    legacy_payload = json.loads(
        (benchmark_root / "BrainRearcherBenchmark_MicroTooling.json").read_text(
            encoding="utf-8"
        )
    )
    legacy_entry = next(task for task in legacy_payload if task["task_id"] == "HARNESS-099")
    assert legacy_entry["task_id"] == "HARNESS-099"
    assert legacy_entry["expected_capability_list"] == ["routing_rejection_contracts"]

    regression_text = (
        benchmark_root / "tests" / "test_benchmark_task_cards.py"
    ).read_text(encoding="utf-8")
    assert (
        "test_build_task_card_prefers_real_harbor_entry_for_"
        "wrong_tool_or_workflow_routing_harness_task"
    ) in regression_text


def test_generate_repo_repair_context_tracks_draft_scaffolds_without_counting_native(
    tmp_path,
):
    autoresearch_root = tmp_path / "autoresearch"
    benchmark_root = tmp_path / "benchmark"
    golden_path = tmp_path / "configs" / "codegen" / "autoresearch_golden_principles.yaml"

    (benchmark_root / "configs" / "autoresearch").mkdir(parents=True, exist_ok=True)
    (benchmark_root / "configs" / "autoresearch" / "motif_slices.yaml").write_text(
        "\n".join(
            [
                "motifs:",
                "  runtime_stall_or_incomplete_bundle:",
                "    task_ids:",
                "      - HARNESS-002",
                "    canary_task_ids:",
                "      - HARNESS-002",
                "  wrong_tool_or_workflow_routing:",
                "    scaffold_task_ids:",
                "      - HARNESS-099",
                "    scaffold_canary_task_ids:",
                "      - HARNESS-099",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (benchmark_root / "configs" / "autoresearch" / "canary_slice.yaml").write_text(
        "\n".join(
            [
                "task_ids:",
                "  - HARNESS-002",
                "scaffold_task_ids:",
                "  - HARNESS-099",
                "",
            ]
        ),
        encoding="utf-8",
    )
    golden_path.parent.mkdir(parents=True, exist_ok=True)
    golden_path.write_text(
        "\n".join(
            [
                "principles:",
                "  - id: terminal_run_invariant",
                "    title: Terminal Run Invariant",
                "    rule: Every run must become terminal.",
                "    why_it_exists: Stalled runs hide failures.",
                "    failure_modes: [runtime_stall_or_incomplete_bundle]",
                "    applies_to: [runtime, harness]",
                "",
            ]
        ),
        encoding="utf-8",
    )

    payload = generate_repo_repair_context(
        top_n=4,
        persist=False,
        autoresearch_root=autoresearch_root,
        benchmark_root=benchmark_root,
        golden_principles_path=golden_path,
    )

    coverage = payload["repo_repair_context"]["harness_coverage"]
    assert coverage["all_harness_tasks"] == ["HARNESS-002"]
    assert coverage["all_scaffold_harness_tasks"] == ["HARNESS-099"]
    assert "runtime_stall_or_incomplete_bundle" in coverage["motifs_with_native_harness"]
    assert "wrong_tool_or_workflow_routing" in coverage["motifs_with_draft_scaffold"]
    assert "wrong_tool_or_workflow_routing" in coverage["motifs_without_native_harness"]
    assert "Draft scaffold HARNESS tasks" in payload["markdown"]
