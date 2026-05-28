from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.research.discovery import loop_controller as discovery_loop
from brain_researcher.research.discovery import synthesis as discovery_synthesis
from brain_researcher.research.discovery.hypothesis_schema import HypothesisEntryV1
from brain_researcher.research.predictive import batch_planner, loop_controller


def _write_script(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_predictive_loop_controller_wraps_legacy_script(tmp_path: Path) -> None:
    project_root = tmp_path / "predictive" / "project"
    capture_path = project_root / "artifacts" / "capture.json"
    _write_script(
        project_root
        / "scripts"
        / "analysis"
        / "fc_benchmarking"
        / "meta_controller.py",
        """
import json
import sys
from pathlib import Path

def build_payload(registry_path, ledger_path):
    return {"registry": str(registry_path), "ledger": str(ledger_path)}

def render_markdown(payload):
    return f"ledger={payload['ledger']}\\n"

def main():
    capture_path = Path(sys.argv[sys.argv.index("--capture-out") + 1])
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    capture_path.write_text(json.dumps({"argv": sys.argv[1:]}), encoding="utf-8")
""".strip(),
    )

    payload = loop_controller.build_payload(
        project_root / "model_registry.json",
        project_root / "experiments.jsonl",
        project_root=project_root,
    )
    assert payload["ledger"].endswith("experiments.jsonl")
    assert (
        loop_controller.render_markdown(payload, project_root=project_root).strip()
        == f"ledger={project_root / 'experiments.jsonl'}"
    )
    assert (
        loop_controller.main(
            ["--capture-out", str(capture_path)],
            project_root=project_root,
        )
        == 0
    )
    captured = json.loads(capture_path.read_text(encoding="utf-8"))
    assert captured["argv"] == ["--capture-out", str(capture_path)]


def test_predictive_loop_controller_injects_needs_exploration_gate(tmp_path: Path) -> None:
    project_root = tmp_path / "predictive" / "project"
    _write_script(
        project_root
        / "scripts"
        / "analysis"
        / "fc_benchmarking"
        / "meta_controller.py",
        """
def build_payload(registry_path, ledger_path):
    return {
        "next_campaign": {
            "campaign_type": "lane_b_weak_target_term_discovery",
            "campaign_name": "lane_b_weak_target_term_discovery",
            "reasoning": ["Weak targets remain unresolved."],
            "target_plans": {
                "PicSeq_Unadj": {
                    "leader_term_index": 11,
                    "comparator_term_index": 12,
                }
            },
            "self_critique_checkpoint": {"gates": {}},
            "recommended_first_batch": [{"target": "PicSeq_Unadj", "term_index": 11}],
            "batch_size_recommended": 1,
        }
    }

def render_markdown(payload):
    return payload["next_campaign"]["campaign_type"]

def main():
    return 0
""".strip(),
    )
    ledger_path = project_root / "experiments.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(
            {
                "phase": "phase9_weak_target_term_discovery",
                "config": {
                    "target": "PicSeq_Unadj",
                    "hyperparameters": {"term_index": 11},
                },
                "scores": {"gold_r2": 0.02},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = loop_controller.build_payload(
        project_root / "model_registry.json",
        ledger_path,
        project_root=project_root,
    )

    assert payload["next_campaign"]["campaign_type"] == "needs_exploration"
    assert payload["next_campaign"]["campaign_name"] == "lane_b_weak_target_needs_exploration"


def test_predictive_batch_planner_wraps_legacy_script(tmp_path: Path) -> None:
    project_root = tmp_path / "predictive" / "project"
    capture_path = project_root / "artifacts" / "planner_capture.json"
    _write_script(
        project_root
        / "scripts"
        / "analysis"
        / "fc_benchmarking"
        / "next_campaign_generator.py",
        """
import json
import sys
from pathlib import Path

def render_plan_markdown(plan):
    return f"campaign={plan['campaign_name']}\\n"

def main():
    capture_path = Path(sys.argv[sys.argv.index("--capture-out") + 1])
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    capture_path.write_text(json.dumps({"argv": sys.argv[1:]}), encoding="utf-8")
""".strip(),
    )

    assert (
        batch_planner.render_plan_markdown(
            {"campaign_name": "lane_b_term_search"},
            project_root=project_root,
        ).strip()
        == "campaign=lane_b_term_search"
    )
    assert (
        batch_planner.main(
            ["--capture-out", str(capture_path)],
            project_root=project_root,
        )
        == 0
    )
    captured = json.loads(capture_path.read_text(encoding="utf-8"))
    assert captured["argv"] == ["--capture-out", str(capture_path)]


def test_discovery_loop_controller_wraps_legacy_script(tmp_path: Path) -> None:
    project_root = tmp_path / "discovery" / "project"
    _write_script(
        project_root / "scripts" / "controller" / "run_closed_loop.py",
        """
from dataclasses import dataclass

@dataclass(frozen=True)
class ClosedLoopConfig:
    rounds: int

def run_closed_loop(config):
    return {"rounds": config.rounds}

def main():
    return 7
""".strip(),
    )

    legacy_module = discovery_loop.load_legacy_module(project_root=project_root)
    config = legacy_module.ClosedLoopConfig(rounds=3)
    assert discovery_loop.run_closed_loop(config, project_root=project_root) == {
        "rounds": 3
    }
    assert discovery_loop.main(project_root=project_root) == 7


def test_discovery_synthesis_reads_canonical_ledgers(tmp_path: Path) -> None:
    line_root = tmp_path / "discovery"
    project_root = line_root / "project"
    closed_loop_root = project_root / "artifacts" / "closed_loop"
    closed_loop_root.mkdir(parents=True)
    (closed_loop_root / "tribe_hypothesis_ledger.jsonl").write_text(
        json.dumps({"hypothesis_id": "hyp_001"}) + "\n",
        encoding="utf-8",
    )
    (closed_loop_root / "tribe_kg_call_log.jsonl").write_text(
        json.dumps({"kg_call_id": "kg_001"}) + "\n",
        encoding="utf-8",
    )
    (closed_loop_root / "tribe_surprises.jsonl").write_text(
        json.dumps({"surprise_id": "surprise_001"}) + "\n",
        encoding="utf-8",
    )
    latest_loop_root = closed_loop_root / "closed_loop_20260408T180000Z"
    latest_loop_root.mkdir()
    checkpoint_path = latest_loop_root / "closed_loop_checkpoint.json"
    checkpoint_path.write_text(json.dumps({"status": "initialized"}), encoding="utf-8")

    ledger = discovery_synthesis.load_hypothesis_ledger(root=project_root)
    assert len(ledger) == 1
    assert isinstance(ledger[0], HypothesisEntryV1)
    assert ledger[0].hypothesis_id == "hyp_001"
    assert discovery_synthesis.load_kg_call_log(root=project_root) == [
        {"kg_call_id": "kg_001"}
    ]
    assert discovery_synthesis.load_surprises(root=project_root) == [
        {"surprise_id": "surprise_001"}
    ]
    assert discovery_synthesis.latest_loop_root(root=project_root) == latest_loop_root
    assert (
        discovery_synthesis.latest_checkpoint_path(root=project_root) == checkpoint_path
    )
