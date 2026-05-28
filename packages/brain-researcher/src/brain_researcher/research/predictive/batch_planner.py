"""Canonical predictive batch-planner wrapper around the live FC planner."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from brain_researcher.research._legacy_project_loader import (
    legacy_project_script_path,
    load_legacy_project_module,
    run_legacy_main,
)

LEGACY_SCRIPT = Path("scripts/analysis/fc_benchmarking/next_campaign_generator.py")


def batch_planner_script_path(
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> Path:
    return legacy_project_script_path(
        "predictive",
        LEGACY_SCRIPT,
        project_root=project_root,
        implementation_path=implementation_path,
    )


def legacy_script_path(*, project_root: Path | str | None = None) -> Path:
    return batch_planner_script_path(project_root=project_root)


def load_implementation(
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
):
    return load_legacy_project_module(
        "predictive",
        "brain_researcher_predictive_batch_planner_legacy",
        LEGACY_SCRIPT,
        project_root=project_root,
        implementation_path=implementation_path,
    )


def load_legacy_module(*, project_root: Path | str | None = None):
    return load_implementation(project_root=project_root)


def render_plan_markdown(
    plan: dict[str, Any],
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> str:
    module = load_implementation(
        project_root=project_root,
        implementation_path=implementation_path,
    )
    return module.render_plan_markdown(plan)


def main(
    argv: Sequence[str] | None = None,
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> int:
    module = load_implementation(
        project_root=project_root,
        implementation_path=implementation_path,
    )
    result = run_legacy_main(
        module,
        script_path=batch_planner_script_path(
            project_root=project_root,
            implementation_path=implementation_path,
        ),
        argv=argv,
    )
    return 0 if result is None else int(result)


__all__ = [
    "batch_planner_script_path",
    "legacy_script_path",
    "load_implementation",
    "load_legacy_module",
    "main",
    "render_plan_markdown",
]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
