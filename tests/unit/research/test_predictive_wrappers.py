from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.research.predictive import batch_planner, loop_controller


def _write_python(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_predictive_wrapper_default_paths_match_canonical_layout() -> None:
    assert loop_controller.loop_controller_script_path() == Path(
        "/data/brain_researcher/research/predictive/project/scripts/analysis/fc_benchmarking/meta_controller.py"
    )
    assert batch_planner.batch_planner_script_path() == Path(
        "/data/brain_researcher/research/predictive/project/scripts/analysis/fc_benchmarking/next_campaign_generator.py"
    )


def test_predictive_loop_controller_proxies_helpers_and_main(
    tmp_path: Path,
) -> None:
    implementation = _write_python(
        tmp_path / "meta_controller.py",
        """
from pathlib import Path
import argparse

def build_payload(registry_path: Path, ledger_path: Path) -> dict:
    return {"registry_path": str(registry_path), "ledger_path": str(ledger_path)}

def render_markdown(payload: dict) -> str:
    return f"registry={payload['registry_path']}"

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).write_text("predictive-loop", encoding="utf-8")
    return 0
""".strip(),
    )

    payload = loop_controller.build_payload(
        tmp_path / "registry.json",
        tmp_path / "experiments.jsonl",
        implementation_path=implementation,
    )
    assert payload["registry_path"].endswith("registry.json")
    assert payload["ledger_path"].endswith("experiments.jsonl")
    assert (
        loop_controller.render_markdown(payload, implementation_path=implementation)
        == f"registry={payload['registry_path']}"
    )

    out_path = tmp_path / "loop.out"
    assert (
        loop_controller.main(
            ["--out", str(out_path)],
            implementation_path=implementation,
        )
        == 0
    )
    assert out_path.read_text(encoding="utf-8") == "predictive-loop"


def test_predictive_loop_controller_emits_native_bundle_artifacts(
    tmp_path: Path,
) -> None:
    implementation = _write_python(
        tmp_path / "meta_controller.py",
        """
from pathlib import Path

def build_payload(registry_path: Path, ledger_path: Path) -> dict:
    run_dir = registry_path.parent / "predictive-run"
    return {
        "run_id": "predictive-run-001",
        "run_dir": str(run_dir),
        "state": "succeeded",
        "diagnostics_summary": {"rows": 3},
        "steps": [{"step_id": "s1", "tool_id": "meta_controller"}],
        "provenance": {"source": "unit-test"},
        "parameters": {
            "target_column": "story_score",
            "split_unit": "tr",
            "grouped_split_keys": ["story", "session", "subject"],
            "required_group_keys": ["story", "session", "subject"],
            "best_layer": "layer-12",
            "layer_candidates": ["layer-4", "layer-8", "layer-12"],
            "nested_cv": True,
        },
        "next_campaign": {"campaign_type": "lane_b_weak_target_term_discovery"},
    }

def render_markdown(payload: dict) -> str:
    return "native-bundle"

def main() -> int:
    return 0
""".strip(),
    )

    payload = loop_controller.build_payload(
        tmp_path / "registry.json",
        tmp_path / "experiments.jsonl",
        implementation_path=implementation,
    )

    run_dir = tmp_path / "predictive-run"
    execution_manifest = json.loads(
        (run_dir / "execution_manifest.json").read_text(encoding="utf-8")
    )
    observation = json.loads((run_dir / "observation.json").read_text(encoding="utf-8"))
    analysis_bundle = json.loads(
        (run_dir / "analysis_bundle.json").read_text(encoding="utf-8")
    )

    assert payload["run_id"] == "predictive-run-001"
    assert execution_manifest["schema_version"] == "execution-manifest-v1"
    assert execution_manifest["execution_mode"] == "python_script"
    assert execution_manifest["inputs"][0]["path"].endswith("registry.json")
    assert observation["job_id"] == "predictive-run-001"
    assert observation["diagnostics_summary"]["rows"] == 3
    assert analysis_bundle["files"]["execution_manifest_json"] == "execution_manifest.json"
    assert analysis_bundle["observation"]["diagnostics_summary"]["rows"] == 3
    assert analysis_bundle["policy_snapshot"]["source"] == "predictive_loop_controller"
    assert analysis_bundle["review_context"]["split"]["required_group_keys"] == [
        "story",
        "session",
        "subject",
    ]
    assert analysis_bundle["review_context"]["selection"]["best_layer"] == "layer-12"
    assert analysis_bundle["review_context"]["selection"]["layer_candidates"] == [
        "layer-4",
        "layer-8",
        "layer-12",
    ]
    assert analysis_bundle["review_context"]["selection"]["nested_cv"] is True


def test_predictive_batch_planner_proxies_markdown_and_main(tmp_path: Path) -> None:
    implementation = _write_python(
        tmp_path / "next_campaign_generator.py",
        """
from pathlib import Path
import argparse

def render_plan_markdown(plan: dict) -> str:
    return f"campaign={plan['campaign_name']}"

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).write_text("predictive-plan", encoding="utf-8")
    return 0
""".strip(),
    )

    plan = {"campaign_name": "weak_target_term_discovery"}
    assert (
        batch_planner.render_plan_markdown(
            plan,
            implementation_path=implementation,
        )
        == "campaign=weak_target_term_discovery"
    )

    out_path = tmp_path / "plan.out"
    assert (
        batch_planner.main(
            ["--out", str(out_path)],
            implementation_path=implementation,
        )
        == 0
    )
    assert out_path.read_text(encoding="utf-8") == "predictive-plan"
