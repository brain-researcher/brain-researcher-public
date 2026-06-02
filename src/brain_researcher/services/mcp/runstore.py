"""Run-store substrate for the MCP server (Track B extraction).

This module holds the filesystem-backed run-store layer that ``server.py`` and
the per-domain router modules depend on. It is a *lower layer*: it must only
import from stdlib, ``brain_researcher.config`` and ``brain_researcher.core``
— never from ``server`` or the routers — so the dependency graph flows one way
(server/routers -> runstore), with no import cycle.

Contents:
- run/step data records (``RunRecord`` / ``StepRecord``)
- the run-root anchor ``RUN_ROOT`` + ``get_run_root()`` / ``set_run_root()``
  facade. ``RUN_ROOT`` is the single source of truth for where runs live; the
  helpers below read it at call time (module-global lookup), so it can be
  redirected in tests via ``monkeypatch.setattr(runstore, "RUN_ROOT", tmp)`` or
  in code via ``set_run_root()``.
- path / id helpers (``_run_dir`` / ``_find_run_dir`` / ``_new_run_id``)
- atomic JSON write + run-record load/save IO

``server.py`` re-exports these names so existing ``server.<name>`` references
keep working, but ``server`` no longer *owns* the run-root value.
"""

from __future__ import annotations

import contextvars
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from brain_researcher.config.run_artifacts import (
    build_mcp_run_dir,
    get_mcp_run_root,
    iter_mcp_run_dir_candidates,
)


@dataclass
class StepRecord:
    step_id: str
    tool_id: str
    params: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"  # queued|running|succeeded|failed|skipped
    started_at: str | None = None
    finished_at: str | None = None
    work_dir: str | None = None
    output_dir: str | None = None
    result_path: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    error: str | None = None
    policy_issues: list[dict[str, Any]] = field(default_factory=list)
    progress: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunRecord:
    run_id: str
    created_at: str
    status: str = "queued"  # queued|running|succeeded|failed
    dry_run: bool = False
    run_workspace: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    steps: list[StepRecord] = field(default_factory=list)
    error: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    timing_policy: dict[str, Any] = field(default_factory=dict)
    source: str = "external"  # internal | external — MCP entry path attribution


# ---------------------------------------------------------------------------
# Run-root anchor + facade
# ---------------------------------------------------------------------------
# RUN_ROOT is the single source of truth for where runs are persisted. Helpers
# read it as a module global at call time, so tests can redirect it with
# ``monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)`` (auto-undone) and code
# can use ``set_run_root()`` / ``get_run_root()``.
RUN_ROOT: Path = get_mcp_run_root()


def get_run_root() -> Path:
    """Return the active run-root directory."""
    return RUN_ROOT


def set_run_root(path: Path) -> Path:
    """Set the active run-root directory; returns the new value.

    Production facade for redirecting run storage. Tests generally prefer
    ``monkeypatch.setattr(runstore, "RUN_ROOT", tmp)`` so the change is
    auto-reverted at teardown.
    """
    global RUN_ROOT
    RUN_ROOT = path
    return RUN_ROOT


# MCP entry-path attribution (internal | external), stamped onto RunRecord on
# save when not already set. Lives here because _save_run consumes it.
_mcp_entry_source: contextvars.ContextVar[str] = contextvars.ContextVar(
    "br_mcp_entry_source", default="external"
)


# ---------------------------------------------------------------------------
# Path / id helpers
# ---------------------------------------------------------------------------
def _new_run_id() -> str:
    # Keep it readable/sortable enough for humans; uniqueness handled by UUID.
    return f"br_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}_{uuid.uuid4().hex[:10]}"


def _run_dir(run_id: str) -> Path:
    return build_mcp_run_dir(run_id, RUN_ROOT)


def _run_dir_candidates(run_id: str) -> list[Path]:
    return list(iter_mcp_run_dir_candidates(run_id, RUN_ROOT))


def _find_run_dir(run_id: str) -> Path:
    # Prefer directories with run.json; fallback to any existing run directory.
    for candidate in _run_dir_candidates(run_id):
        if (candidate / "run.json").exists():
            return candidate
    for candidate in _run_dir_candidates(run_id):
        if candidate.exists():
            return candidate
    return _run_dir(run_id)


# ---------------------------------------------------------------------------
# JSON write + run-record load/save IO
# ---------------------------------------------------------------------------
def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    tmp.replace(path)


def _run_record_from_json(path: Path) -> RunRecord:
    data = json.loads(path.read_text())
    steps = [StepRecord(**s) for s in data.get("steps", [])]
    return RunRecord(
        run_id=data["run_id"],
        created_at=data["created_at"],
        status=data.get("status", "queued"),
        dry_run=bool(data.get("dry_run", False)),
        run_workspace=data.get("run_workspace"),
        started_at=data.get("started_at"),
        finished_at=data.get("finished_at"),
        steps=steps,
        error=data.get("error"),
        progress=data.get("progress") or {},
        timing_policy=data.get("timing_policy") or {},
        source=str(data.get("source") or "external"),
    )


def _load_run_with_dir(run_id: str) -> tuple[RunRecord, Path]:
    run_dir = _find_run_dir(run_id)
    path = run_dir / "run.json"
    record = _run_record_from_json(path)
    return record, run_dir


def _load_run(run_id: str) -> RunRecord:
    record, _ = _load_run_with_dir(run_id)
    return record


def _save_run(record: RunRecord, *, run_dir: Path | None = None) -> None:
    path = (run_dir or _run_dir(record.run_id)) / "run.json"
    if not record.source:
        record.source = _mcp_entry_source.get()
    payload = asdict(record)
    _atomic_write_json(path, payload)
