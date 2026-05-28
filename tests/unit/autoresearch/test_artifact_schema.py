from __future__ import annotations

from pathlib import Path

from brain_researcher.autoresearch.artifact_schema import (
    canonical_line_root,
    canonicalize_line_path,
    legacy_line_root,
    resolve_line_paths,
)


def test_resolve_predictive_paths_uses_research_root(tmp_path: Path) -> None:
    data_root = tmp_path / "brain_researcher"
    paths = resolve_line_paths("predictive", data_root=data_root)

    assert paths.line_root == data_root / "research" / "predictive"
    assert paths.project_root == data_root / "research" / "predictive" / "project"
    assert paths.ledger_path == paths.project_root / "experiments.jsonl"
    assert paths.diagnostics_root == paths.project_root / "artifacts" / "diagnostics"


def test_canonicalize_legacy_predictive_path_maps_to_new_root(tmp_path: Path) -> None:
    data_root = tmp_path / "brain_researcher"
    legacy_project = legacy_line_root("predictive", data_root=data_root) / "project"
    canonical_project = canonical_line_root("predictive", data_root=data_root) / "project"

    remapped = canonicalize_line_path(
        legacy_project / "artifacts" / "diagnostics" / "status.json",
        "predictive",
        data_root=data_root,
    )

    assert remapped == canonical_project / "artifacts" / "diagnostics" / "status.json"


def test_resolve_discovery_paths_tracks_closed_loop_ledgers(tmp_path: Path) -> None:
    data_root = tmp_path / "brain_researcher"
    paths = resolve_line_paths("discovery", data_root=data_root)

    assert paths.checkpoint_root == paths.project_root / "artifacts" / "closed_loop"
    assert paths.ledger_path == paths.checkpoint_root / "tribe_hypothesis_ledger.jsonl"
    assert len(paths.scored_ledgers) == 3
    assert paths.scored_ledgers[1].name == "tribe_kg_call_log.jsonl"
    assert paths.scored_ledgers[2].name == "tribe_surprises.jsonl"
