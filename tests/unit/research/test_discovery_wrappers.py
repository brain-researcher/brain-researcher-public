from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.research.discovery import loop_controller, synthesis


def _write_python(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_discovery_wrapper_default_paths_match_canonical_layout() -> None:
    assert loop_controller.loop_controller_script_path() == Path(
        "/data/brain_researcher/research/discovery/project/scripts/controller/run_closed_loop.py"
    )
    assert synthesis.state_builder_script_path() == Path(
        "/data/brain_researcher/research/discovery/project/scripts/controller/build_research_state.py"
    )
    assert synthesis.proposal_script_path() == Path(
        "/data/brain_researcher/research/discovery/project/scripts/controller/generate_next_round_proposal.py"
    )


def test_discovery_loop_controller_proxies_run_and_main(tmp_path: Path) -> None:
    implementation = _write_python(
        tmp_path / "run_closed_loop.py",
        """
from pathlib import Path
import argparse

def run_closed_loop(config):
    return {"loop_root": config["loop_root"], "status": "ok"}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).write_text("discovery-loop", encoding="utf-8")
    return 0
""".strip(),
    )

    payload = loop_controller.run_closed_loop(
        {"loop_root": "tmp-loop"},
        implementation_path=implementation,
    )
    assert payload == {"loop_root": "tmp-loop", "status": "ok"}

    out_path = tmp_path / "loop.out"
    assert (
        loop_controller.main(
            ["--out", str(out_path)],
            implementation_path=implementation,
        )
        == 0
    )
    assert out_path.read_text(encoding="utf-8") == "discovery-loop"


def test_discovery_loop_controller_emits_native_bundle_artifacts(
    tmp_path: Path,
) -> None:
    implementation = _write_python(
        tmp_path / "run_closed_loop.py",
        """
def run_closed_loop(config):
    return {
        "run_id": "discovery-run-001",
        "run_dir": config["run_dir"],
        "round_id": "round-03",
        "state": "succeeded",
        "summary": "Closed-loop discovery completed.",
        "provenance": {
            "schema_version": "provenance-v1",
            "command": ["python", "run_closed_loop.py", "--loop-root", config["run_dir"]],
            "packages": {"numpy": "1.26.4"},
            "environment": {"python_version": "3.11.9"},
        },
        "artifacts": [
            {"name": "branch_scores.csv", "type": "csv", "path": "branch_scores.csv", "size": 12}
        ],
        "inputs_manifest_ref": "inputs_manifest.json",
        "qc_summary_ref": "qc_summary.json",
        "source_manifests": ["inputs_manifest.json"],
    }

def main() -> int:
    return 0
""".strip(),
    )

    run_dir = tmp_path / "closed-loop-run"
    run_dir.mkdir()
    (run_dir / "trajectory.json").write_text(
        '{"schema_version":"ATIF-v1.4"}',
        encoding="utf-8",
    )
    (run_dir / "branch_scores.csv").write_text("score\n0.91\n", encoding="utf-8")
    (run_dir / "inputs_manifest.json").write_text(
        json.dumps({"schema_version": "inputs-manifest-v1", "inputs": []}),
        encoding="utf-8",
    )
    (run_dir / "qc_summary.json").write_text(
        json.dumps({"schema_version": "qc-summary-v1", "status": "pass"}),
        encoding="utf-8",
    )

    payload = loop_controller.run_closed_loop(
        {"run_dir": str(run_dir)},
        implementation_path=implementation,
    )

    assert payload["run_id"] == "discovery-run-001"
    execution_manifest = json.loads(
        (run_dir / "execution_manifest.json").read_text(encoding="utf-8")
    )
    observation = json.loads((run_dir / "observation.json").read_text(encoding="utf-8"))
    analysis_bundle = json.loads(
        (run_dir / "analysis_bundle.json").read_text(encoding="utf-8")
    )

    assert execution_manifest["schema_version"] == "execution-manifest-v1"
    assert observation["round_id"] == "round-03"
    assert observation["inputs_manifest_ref"] == "inputs_manifest.json"
    assert analysis_bundle["files"]["execution_manifest_json"] == "execution_manifest.json"
    assert analysis_bundle["source_manifests"] == ["inputs_manifest.json"]
    assert analysis_bundle["qc_summary_ref"] == "qc_summary.json"
    assert analysis_bundle["policy_snapshot"]["source"] == "discovery_loop_controller"


def test_discovery_synthesis_proxies_helpers_and_mains(tmp_path: Path) -> None:
    state_impl = _write_python(
        tmp_path / "build_research_state.py",
        """
from pathlib import Path
import argparse

def build_research_state(*, run_root, analysis_dir, out, line_summaries, project_id, parent_round_id=None):
    payload = {
        "run_root": str(run_root),
        "analysis_dir": str(analysis_dir),
        "out": str(out),
        "line_summaries": [str(item) for item in line_summaries],
        "project_id": project_id,
        "parent_round_id": parent_round_id,
    }
    Path(out).write_text("state-built", encoding="utf-8")
    return payload

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).write_text("state-main", encoding="utf-8")
    return 0
""".strip(),
    )
    proposal_impl = _write_python(
        tmp_path / "generate_next_round_proposal.py",
        """
from pathlib import Path
import argparse

def build_proposal(state, proposal_id=None):
    return {"state": state, "proposal_id": proposal_id}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).write_text("proposal-main", encoding="utf-8")
    return 0
""".strip(),
    )

    state_out = tmp_path / "state.json"
    state_payload = synthesis.build_research_state(
        run_root=tmp_path / "run",
        analysis_dir=tmp_path / "analysis",
        out=state_out,
        line_summaries=[tmp_path / "summary.md"],
        project_id="discovery",
        parent_round_id="round_01",
        implementation_path=state_impl,
    )
    assert state_payload["project_id"] == "discovery"
    assert state_payload["parent_round_id"] == "round_01"
    assert state_out.read_text(encoding="utf-8") == "state-built"

    proposal_payload = synthesis.build_proposal(
        {"round_id": "round_02"},
        proposal_id="proposal_001",
        implementation_path=proposal_impl,
    )
    assert proposal_payload == {
        "state": {"round_id": "round_02"},
        "proposal_id": "proposal_001",
    }

    state_main_out = tmp_path / "state-main.out"
    proposal_main_out = tmp_path / "proposal-main.out"
    assert (
        synthesis.state_main(
            ["--out", str(state_main_out)],
            implementation_path=state_impl,
        )
        == 0
    )
    assert (
        synthesis.proposal_main(
            ["--out", str(proposal_main_out)],
            implementation_path=proposal_impl,
        )
        == 0
    )
    assert state_main_out.read_text(encoding="utf-8") == "state-main"
    assert proposal_main_out.read_text(encoding="utf-8") == "proposal-main"
