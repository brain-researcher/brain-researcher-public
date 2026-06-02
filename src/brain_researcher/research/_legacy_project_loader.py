"""Load canonical predictive/discovery project scripts without moving live code yet."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from brain_researcher.autoresearch.artifact_schema import LineId, resolve_line_paths


def legacy_project_script_path(
    line_id: LineId,
    relative_script_path: str | Path,
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> Path:
    if implementation_path is not None:
        return Path(implementation_path).expanduser().resolve()
    paths = resolve_line_paths(line_id, root=project_root)
    return (paths.project_root / Path(relative_script_path)).resolve()


def load_legacy_project_module(
    line_id: LineId,
    module_name: str,
    relative_script_path: str | Path,
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> ModuleType:
    script_path = legacy_project_script_path(
        line_id,
        relative_script_path,
        project_root=project_root,
        implementation_path=implementation_path,
    )
    if not script_path.exists():
        raise FileNotFoundError(f"Legacy project script not found: {script_path}")
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def run_legacy_main(
    module: ModuleType,
    *,
    script_path: Path,
    argv: Sequence[str] | None = None,
) -> int | None:
    original_argv = sys.argv
    try:
        sys.argv = [str(script_path), *(argv or ())]
        return module.main()
    finally:
        sys.argv = original_argv


__all__ = [
    "legacy_project_script_path",
    "load_legacy_project_module",
    "run_legacy_main",
]
