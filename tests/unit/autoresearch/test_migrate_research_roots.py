from __future__ import annotations

from pathlib import Path

from scripts.autoresearch.migrate_research_roots import (
    apply_actions,
    plan_line_migration,
)


def test_apply_migration_moves_predictive_root_and_creates_alias(tmp_path: Path) -> None:
    data_root = tmp_path / "brain_researcher"
    legacy_root = data_root / "fc_benchmarking"
    (legacy_root / "project").mkdir(parents=True)
    (legacy_root / "project" / "sentinel.txt").write_text("ok", encoding="utf-8")

    actions = plan_line_migration("predictive", data_root=data_root)
    apply_actions(actions)

    canonical_root = data_root / "research" / "predictive"
    assert (canonical_root / "project" / "sentinel.txt").read_text(encoding="utf-8") == "ok"
    assert legacy_root.is_symlink()
    assert legacy_root.resolve() == canonical_root


def test_plan_reports_conflict_when_both_roots_exist(tmp_path: Path) -> None:
    data_root = tmp_path / "brain_researcher"
    (data_root / "fc_benchmarking").mkdir(parents=True)
    (data_root / "research" / "predictive").mkdir(parents=True)

    actions = plan_line_migration("predictive", data_root=data_root)

    assert any(action.kind == "conflict" for action in actions)
