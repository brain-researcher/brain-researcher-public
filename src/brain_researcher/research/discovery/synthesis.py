"""Canonical discovery synthesis wrappers and artifact readers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from brain_researcher.autoresearch.artifact_schema import resolve_line_paths
from brain_researcher.research._legacy_project_loader import (
    legacy_project_script_path,
    load_legacy_project_module,
    run_legacy_main,
)
from brain_researcher.research.discovery.hypothesis_schema import HypothesisEntryV1

STATE_BUILDER_SCRIPT = Path("scripts/controller/build_research_state.py")
PROPOSAL_SCRIPT = Path("scripts/controller/generate_next_round_proposal.py")


def resolve_paths(*, root: Path | str | None = None):
    return resolve_line_paths("discovery", root=root)


def state_builder_script_path(
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> Path:
    return legacy_project_script_path(
        "discovery",
        STATE_BUILDER_SCRIPT,
        project_root=project_root,
        implementation_path=implementation_path,
    )


def proposal_script_path(
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> Path:
    return legacy_project_script_path(
        "discovery",
        PROPOSAL_SCRIPT,
        project_root=project_root,
        implementation_path=implementation_path,
    )


def load_state_implementation(
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
):
    return load_legacy_project_module(
        "discovery",
        "brain_researcher_discovery_state_builder_legacy",
        STATE_BUILDER_SCRIPT,
        project_root=project_root,
        implementation_path=implementation_path,
    )


def load_proposal_implementation(
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
):
    return load_legacy_project_module(
        "discovery",
        "brain_researcher_discovery_proposal_legacy",
        PROPOSAL_SCRIPT,
        project_root=project_root,
        implementation_path=implementation_path,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def hypothesis_ledger_path(*, root: Path | str | None = None) -> Path:
    return resolve_paths(root=root).ledger_path


def kg_call_log_path(*, root: Path | str | None = None) -> Path:
    return resolve_paths(root=root).checkpoint_root / "tribe_kg_call_log.jsonl"


def surprises_path(*, root: Path | str | None = None) -> Path:
    return resolve_paths(root=root).checkpoint_root / "tribe_surprises.jsonl"


def load_hypothesis_ledger(
    *,
    root: Path | str | None = None,
) -> list[HypothesisEntryV1]:
    return [HypothesisEntryV1.model_validate(row) for row in _read_jsonl(hypothesis_ledger_path(root=root))]


def load_kg_call_log(*, root: Path | str | None = None) -> list[dict[str, Any]]:
    return _read_jsonl(kg_call_log_path(root=root))


def load_surprises(*, root: Path | str | None = None) -> list[dict[str, Any]]:
    return _read_jsonl(surprises_path(root=root))


def latest_loop_root(*, root: Path | str | None = None) -> Path | None:
    checkpoint_root = resolve_paths(root=root).checkpoint_root
    if checkpoint_root is None or not checkpoint_root.exists():
        return None
    candidates = sorted(
        (
            candidate
            for candidate in checkpoint_root.glob("closed_loop_*")
            if candidate.is_dir()
        ),
        key=lambda candidate: candidate.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def latest_checkpoint_path(*, root: Path | str | None = None) -> Path | None:
    loop_root = latest_loop_root(root=root)
    if loop_root is None:
        return None
    checkpoint_path = loop_root / "closed_loop_checkpoint.json"
    return checkpoint_path if checkpoint_path.exists() else None


def build_research_state(
    *,
    run_root: Path | str,
    analysis_dir: Path | str,
    out: Path | str,
    line_summaries: list[Path | str],
    project_id: str = "discovery",
    parent_round_id: str | None = None,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> dict[str, Any]:
    module = load_state_implementation(
        project_root=project_root,
        implementation_path=implementation_path,
    )
    return module.build_research_state(
        run_root=Path(run_root).expanduser().resolve(),
        analysis_dir=Path(analysis_dir).expanduser().resolve(),
        out=Path(out).expanduser().resolve(),
        line_summaries=[Path(path).expanduser().resolve() for path in line_summaries],
        project_id=project_id,
        parent_round_id=parent_round_id,
    )


def build_proposal(
    state: dict[str, Any],
    *,
    proposal_id: str | None = None,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> dict[str, Any]:
    module = load_proposal_implementation(
        project_root=project_root,
        implementation_path=implementation_path,
    )
    return module.build_proposal(state, proposal_id=proposal_id)


def state_main(
    argv: list[str] | None = None,
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> int:
    module = load_state_implementation(
        project_root=project_root,
        implementation_path=implementation_path,
    )
    result = run_legacy_main(
        module,
        script_path=state_builder_script_path(
            project_root=project_root,
            implementation_path=implementation_path,
        ),
        argv=argv,
    )
    return 0 if result is None else int(result)


def proposal_main(
    argv: list[str] | None = None,
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> int:
    module = load_proposal_implementation(
        project_root=project_root,
        implementation_path=implementation_path,
    )
    result = run_legacy_main(
        module,
        script_path=proposal_script_path(
            project_root=project_root,
            implementation_path=implementation_path,
        ),
        argv=argv,
    )
    return 0 if result is None else int(result)


__all__ = [
    "build_proposal",
    "build_research_state",
    "hypothesis_ledger_path",
    "kg_call_log_path",
    "load_proposal_implementation",
    "load_state_implementation",
    "latest_checkpoint_path",
    "latest_loop_root",
    "load_hypothesis_ledger",
    "load_kg_call_log",
    "load_surprises",
    "proposal_main",
    "proposal_script_path",
    "resolve_paths",
    "state_builder_script_path",
    "state_main",
    "surprises_path",
]
