#!/usr/bin/env python3
"""Unified retention policy runner for runtime artifact roots.

This script centralizes retention handling for:
- logs
- outputs
- tmp
- data/runs

It also normalizes legacy path aliases into canonical locations while preserving
public paths via symlinks.

Default mode is dry-run.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.config.run_artifacts import (
    RUN_PATH_ALIASES,
    get_mcp_run_roots_for_read,
    is_active_run,
    iter_mcp_run_dirs,
    iter_recorded_run_dirs,
    iter_run_date_dirs,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_ROOT = REPO_ROOT / "tmp" / "retention_policy_state"


@dataclass(frozen=True)
class RootPolicy:
    key: str
    root: Path
    mode: str  # "files" | "runs" | "mcp_runs"
    max_age_days: float
    max_total_gb: float


DEFAULT_POLICIES: dict[str, RootPolicy] = {
    "logs": RootPolicy(
        key="logs",
        root=REPO_ROOT / "logs",
        mode="files",
        max_age_days=21,
        max_total_gb=30.0,
    ),
    "outputs": RootPolicy(
        key="outputs",
        root=REPO_ROOT / "outputs",
        mode="files",
        max_age_days=45,
        max_total_gb=200.0,
    ),
    "tmp": RootPolicy(
        key="tmp",
        root=REPO_ROOT / "tmp",
        mode="files",
        max_age_days=14,
        max_total_gb=50.0,
    ),
    "data_runs": RootPolicy(
        key="data_runs",
        root=REPO_ROOT / "data" / "runs",
        mode="runs",
        max_age_days=30,
        max_total_gb=120.0,
    ),
    "mcp_runs": RootPolicy(
        key="mcp_runs",
        root=REPO_ROOT / "data" / "runs" / "mcp_runs",
        mode="mcp_runs",
        max_age_days=30,
        max_total_gb=120.0,
    ),
}


# alias -> canonical
PATH_ALIASES: list[tuple[Path, Path]] = [
    (
        REPO_ROOT / "outputs" / "out" / "tmp_tests" / "pytest-of-zijiaochen",
        REPO_ROOT / ".pytest_tmp" / "pytest-of-zijiaochen",
    ),
    (
        REPO_ROOT / "artifacts" / "tests" / "results",
        REPO_ROOT / "test-results" / "artifacts-tests",
    ),
    (
        REPO_ROOT / "outputs" / "test_logs",
        REPO_ROOT / "artifacts" / "tests" / "logs",
    ),
    (
        REPO_ROOT / "outputs" / "test_outputs",
        REPO_ROOT / "artifacts" / "tests" / "outputs",
    ),
    (
        REPO_ROOT / "outputs" / "logs",
        REPO_ROOT / "logs" / "outputs",
    ),
    (
        REPO_ROOT / "artifacts" / "logs",
        REPO_ROOT / "logs" / "artifacts",
    ),
    (
        REPO_ROOT / "data" / "logs",
        REPO_ROOT / "logs" / "data",
    ),
    (
        REPO_ROOT / "out",
        REPO_ROOT / "outputs" / "out",
    ),
    *RUN_PATH_ALIASES,
]


def _bytes_to_gb(value: int) -> float:
    return value / (1024**3)


def _max_total_bytes(limit_gb: float) -> int | None:
    if math.isinf(limit_gb):
        return None
    return int(limit_gb * (1024**3))


def _safe_relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except Exception:
        return str(path)


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        if p.is_file() and not p.is_symlink():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def _remove_empty_dirs(path: Path) -> None:
    if not path.exists() or not path.is_dir():
        return
    for d in sorted((p for p in path.rglob("*") if p.is_dir()), key=lambda x: len(x.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        pass


def _move_tree_with_conflicts(
    src: Path,
    dst: Path,
    conflict_root: Path,
) -> dict[str, int]:
    moved = 0
    conflicts = 0

    if not src.exists():
        return {"moved": moved, "conflicts": conflicts}

    dst.mkdir(parents=True, exist_ok=True)
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        target = dst / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            conflict_path = conflict_root / rel
            conflict_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(conflict_path))
            conflicts += 1
        else:
            shutil.move(str(p), str(target))
            moved += 1

    _remove_empty_dirs(src)
    return {"moved": moved, "conflicts": conflicts}


def _normalize_alias(
    alias: Path,
    target: Path,
    *,
    apply: bool,
    conflict_root: Path,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "alias": str(alias),
        "target": str(target),
        "status": "noop",
        "moved_files": 0,
        "conflicts": 0,
    }

    target.mkdir(parents=True, exist_ok=True)

    if alias.is_symlink():
        try:
            resolved = alias.resolve()
        except OSError:
            resolved = None
        if resolved == target.resolve():
            result["status"] = "already_normalized"
            return result
        if apply:
            alias.unlink(missing_ok=True)
            alias.parent.mkdir(parents=True, exist_ok=True)
            alias.symlink_to(target)
            result["status"] = "relinked"
        else:
            result["status"] = "would_relink"
        return result

    if not alias.exists():
        if apply:
            alias.parent.mkdir(parents=True, exist_ok=True)
            alias.symlink_to(target)
            result["status"] = "linked_missing_alias"
        else:
            result["status"] = "would_link_missing_alias"
        return result

    if alias == target:
        result["status"] = "same_path"
        return result

    if apply:
        if alias.is_dir():
            moved = _move_tree_with_conflicts(alias, target, conflict_root)
            result["moved_files"] = moved["moved"]
            result["conflicts"] = moved["conflicts"]
            if alias.exists() and not alias.is_symlink():
                if alias.is_dir():
                    _remove_empty_dirs(alias)
                if alias.exists():
                    residual = conflict_root.parent / "residual" / alias.name
                    residual.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(alias), str(residual))
            alias.parent.mkdir(parents=True, exist_ok=True)
            alias.symlink_to(target)
            result["status"] = "merged_and_linked"
        else:
            conflict_path = conflict_root / alias.name
            conflict_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(alias), str(conflict_path))
            alias.symlink_to(target)
            result["status"] = "replaced_file_with_link"
            result["conflicts"] = 1
    else:
        result["status"] = "would_merge_and_link"

    return result


def _collect_root_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            files.append(p)
    return files


def _delete_path(path: Path, apply: bool) -> bool:
    if not path.exists():
        return False
    if not apply:
        return True
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    return True


def _prune_files_root(
    policy: RootPolicy,
    *,
    now_ts: float,
    apply: bool,
) -> dict[str, Any]:
    root = policy.root
    files = _collect_root_files(root)
    entries = []
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        entries.append((p, st.st_mtime, st.st_size))

    total_before = sum(s for _, _, s in entries)
    cutoff_ts = now_ts - (policy.max_age_days * 86400)

    deleted_by_age = 0
    bytes_deleted_age = 0
    deleted_by_size = 0
    bytes_deleted_size = 0
    actions: list[dict[str, Any]] = []

    for p, mtime, size in sorted(entries, key=lambda x: x[1]):
        if mtime < cutoff_ts:
            if _delete_path(p, apply):
                deleted_by_age += 1
                bytes_deleted_age += size
                actions.append(
                    {
                        "kind": "age",
                        "path": str(p),
                        "size_bytes": size,
                        "mtime": mtime,
                    }
                )

    entries_after_age = []
    for p, _, _ in entries:
        if p.exists():
            try:
                st = p.stat()
            except OSError:
                continue
            entries_after_age.append((p, st.st_mtime, st.st_size))

    total_after_age = sum(s for _, _, s in entries_after_age)
    max_bytes = _max_total_bytes(policy.max_total_gb)
    current_total = total_after_age

    if max_bytes is not None and current_total > max_bytes:
        for p, mtime, size in sorted(entries_after_age, key=lambda x: x[1]):
            if current_total <= max_bytes:
                break
            if _delete_path(p, apply):
                deleted_by_size += 1
                bytes_deleted_size += size
                current_total -= size
                actions.append(
                    {
                        "kind": "size",
                        "path": str(p),
                        "size_bytes": size,
                        "mtime": mtime,
                    }
                )

    total_after = _dir_size_bytes(root)
    _remove_empty_dirs(root)
    root.mkdir(parents=True, exist_ok=True)

    return {
        "root": str(root),
        "mode": "files",
        "max_age_days": policy.max_age_days,
        "max_total_gb": policy.max_total_gb,
        "total_before_bytes": total_before,
        "total_after_bytes": total_after,
        "deleted_by_age_count": deleted_by_age,
        "deleted_by_age_bytes": bytes_deleted_age,
        "deleted_by_size_count": deleted_by_size,
        "deleted_by_size_bytes": bytes_deleted_size,
        "actions_preview": actions[:200],
    }


def _read_run_state(run_dir: Path) -> str:
    status_file = run_dir / "status.json"
    if not status_file.exists():
        return "unknown"
    try:
        payload = json.loads(status_file.read_text(encoding="utf-8"))
        state = str(payload.get("state", "unknown")).strip().lower()
        return state or "unknown"
    except Exception:
        return "unknown"


def _parse_iso_timestamp(raw: Any) -> float | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, int | float):
        return float(raw)
    try:
        normalized = str(raw).strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return None


def _collect_run_dirs(runs_root: Path) -> list[tuple[Path, float, int, str]]:
    out: list[tuple[Path, float, int, str]] = []
    if not runs_root.exists():
        return out
    for run_dir in iter_recorded_run_dirs(runs_root):
        try:
            mtime = run_dir.stat().st_mtime
        except OSError:
            continue
        size = _dir_size_bytes(run_dir)
        state = _read_run_state(run_dir)
        out.append((run_dir, mtime, size, state))
    return out


def _is_active_run(mtime: float, state: str, now_ts: float) -> bool:
    return is_active_run(state, mtime, now_ts=now_ts)


def _read_mcp_run_metadata(
    run_dir: Path,
    *,
    fallback_ts: float | None = None,
) -> tuple[str, float]:
    run_json = run_dir / "run.json"
    if fallback_ts is None:
        fallback_ts = run_dir.stat().st_mtime
    if not run_json.exists():
        return "unknown", fallback_ts
    try:
        payload = json.loads(run_json.read_text(encoding="utf-8"))
    except Exception:
        return "unknown", fallback_ts

    status = str(payload.get("status", "unknown")).strip().lower() or "unknown"
    age_ts = (
        _parse_iso_timestamp(payload.get("finished_at"))
        or _parse_iso_timestamp(payload.get("started_at"))
        or _parse_iso_timestamp(payload.get("created_at"))
        or fallback_ts
    )
    return status, age_ts


def _collect_mcp_run_dirs(runs_root: Path) -> list[tuple[Path, float, int, str, float]]:
    out: list[tuple[Path, float, int, str, float]] = []
    if not runs_root.exists():
        return out
    for run_dir in iter_mcp_run_dirs(runs_root):
        try:
            mtime = run_dir.stat().st_mtime
        except OSError:
            continue
        size = _dir_size_bytes(run_dir)
        state, age_ts = _read_mcp_run_metadata(run_dir, fallback_ts=mtime)
        out.append((run_dir, age_ts, size, state, mtime))
    return out


def _prune_runs_root(
    policy: RootPolicy,
    *,
    now_ts: float,
    apply: bool,
) -> dict[str, Any]:
    runs = _collect_run_dirs(policy.root)
    total_before = sum(size for _, _, size, _ in runs)
    cutoff_ts = now_ts - (policy.max_age_days * 86400)
    max_bytes = _max_total_bytes(policy.max_total_gb)

    deleted_by_age = 0
    bytes_deleted_age = 0
    deleted_by_size = 0
    bytes_deleted_size = 0
    actions: list[dict[str, Any]] = []

    active = []
    inactive = []
    for run_dir, mtime, size, state in runs:
        if _is_active_run(mtime, state, now_ts):
            active.append((run_dir, mtime, size, state))
        else:
            inactive.append((run_dir, mtime, size, state))

    # Age pruning first.
    survivors: list[tuple[Path, float, int, str]] = []
    for run_dir, mtime, size, state in sorted(inactive, key=lambda x: x[1]):
        if mtime < cutoff_ts:
            if _delete_path(run_dir, apply):
                deleted_by_age += 1
                bytes_deleted_age += size
                actions.append(
                    {
                        "kind": "age",
                        "path": str(run_dir),
                        "size_bytes": size,
                        "mtime": mtime,
                        "state": state,
                    }
                )
        else:
            survivors.append((run_dir, mtime, size, state))

    current_total = sum(size for _, _, size, _ in survivors) + sum(
        size for _, _, size, _ in active
    )

    # Size pruning only on inactive survivors.
    if max_bytes is not None and current_total > max_bytes:
        for run_dir, mtime, size, state in sorted(survivors, key=lambda x: x[1]):
            if current_total <= max_bytes:
                break
            if _delete_path(run_dir, apply):
                deleted_by_size += 1
                bytes_deleted_size += size
                current_total -= size
                actions.append(
                    {
                        "kind": "size",
                        "path": str(run_dir),
                        "size_bytes": size,
                        "mtime": mtime,
                        "state": state,
                    }
                )

    # Clean empty date directories.
    empty_date_dirs_removed = 0
    if policy.root.exists():
        for date_dir in iter_run_date_dirs(policy.root):
            has_entries = any(date_dir.iterdir())
            if not has_entries:
                if apply:
                    date_dir.rmdir()
                empty_date_dirs_removed += 1

    total_after = _dir_size_bytes(policy.root)
    policy.root.mkdir(parents=True, exist_ok=True)

    return {
        "root": str(policy.root),
        "mode": "runs",
        "max_age_days": policy.max_age_days,
        "max_total_gb": policy.max_total_gb,
        "total_before_bytes": total_before,
        "total_after_bytes": total_after,
        "active_runs_count": len(active),
        "deleted_by_age_count": deleted_by_age,
        "deleted_by_age_bytes": bytes_deleted_age,
        "deleted_by_size_count": deleted_by_size,
        "deleted_by_size_bytes": bytes_deleted_size,
        "empty_date_dirs_removed": empty_date_dirs_removed,
        "actions_preview": actions[:200],
    }


def _prune_mcp_runs_root(
    policy: RootPolicy,
    *,
    now_ts: float,
    apply: bool,
) -> dict[str, Any]:
    runs = _collect_mcp_run_dirs(policy.root)
    total_before = sum(size for _, _, size, _, _ in runs)
    cutoff_ts = now_ts - (policy.max_age_days * 86400)
    max_bytes = _max_total_bytes(policy.max_total_gb)

    deleted_by_age = 0
    bytes_deleted_age = 0
    deleted_by_size = 0
    bytes_deleted_size = 0
    actions: list[dict[str, Any]] = []

    active: list[tuple[Path, float, int, str, float]] = []
    inactive: list[tuple[Path, float, int, str, float]] = []
    for run_dir, age_ts, size, state, mtime in runs:
        if _is_active_run(mtime, state, now_ts):
            active.append((run_dir, age_ts, size, state, mtime))
        else:
            inactive.append((run_dir, age_ts, size, state, mtime))

    survivors: list[tuple[Path, float, int, str, float]] = []
    for run_dir, age_ts, size, state, mtime in sorted(inactive, key=lambda x: x[1]):
        if age_ts < cutoff_ts:
            if _delete_path(run_dir, apply):
                deleted_by_age += 1
                bytes_deleted_age += size
                actions.append(
                    {
                        "kind": "age",
                        "path": str(run_dir),
                        "size_bytes": size,
                        "age_ts": age_ts,
                        "mtime": mtime,
                        "state": state,
                    }
                )
        else:
            survivors.append((run_dir, age_ts, size, state, mtime))

    current_total = sum(size for _, _, size, _, _ in survivors) + sum(
        size for _, _, size, _, _ in active
    )

    if max_bytes is not None and current_total > max_bytes:
        for run_dir, age_ts, size, state, mtime in sorted(
            survivors, key=lambda x: x[1]
        ):
            if current_total <= max_bytes:
                break
            if _delete_path(run_dir, apply):
                deleted_by_size += 1
                bytes_deleted_size += size
                current_total -= size
                actions.append(
                    {
                        "kind": "size",
                        "path": str(run_dir),
                        "size_bytes": size,
                        "age_ts": age_ts,
                        "mtime": mtime,
                        "state": state,
                    }
                )

    runs_dir = policy.root / "runs"
    empty_run_dirs_removed = 0
    if runs_dir.exists():
        for run_dir in iter_mcp_run_dirs(policy.root):
            try:
                has_entries = any(run_dir.iterdir())
            except OSError:
                continue
            if has_entries:
                continue
            if apply:
                run_dir.rmdir()
            empty_run_dirs_removed += 1

    total_after = _dir_size_bytes(policy.root)
    policy.root.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    return {
        "root": str(policy.root),
        "runs_dir": str(runs_dir),
        "mode": "mcp_runs",
        "max_age_days": policy.max_age_days,
        "max_total_gb": policy.max_total_gb,
        "total_before_bytes": total_before,
        "total_after_bytes": total_after,
        "active_runs_count": len(active),
        "deleted_by_age_count": deleted_by_age,
        "deleted_by_age_bytes": bytes_deleted_age,
        "deleted_by_size_count": deleted_by_size,
        "deleted_by_size_bytes": bytes_deleted_size,
        "empty_run_dirs_removed": empty_run_dirs_removed,
        "actions_preview": actions[:200],
    }


def classify_run_root_mode(runs_root: Path | str) -> str:
    """Classify a run root as ordinary date-bucketed runs or MCP metadata runs."""

    root = Path(runs_root).expanduser().resolve()
    if root in get_mcp_run_roots_for_read():
        return "mcp_runs"
    if root.name == "mcp_runs":
        return "mcp_runs"

    runs_dir = root / "runs"
    if runs_dir.exists():
        for run_dir in iter_mcp_run_dirs(root):
            if (run_dir / "run.json").exists():
                return "mcp_runs"
    return "runs"


def prune_root_policy(
    policy: RootPolicy,
    *,
    now_ts: float,
    apply: bool,
) -> dict[str, Any]:
    """Dispatch pruning to the appropriate mode-specific implementation."""

    if policy.mode == "runs":
        return _prune_runs_root(policy, now_ts=now_ts, apply=apply)
    if policy.mode == "mcp_runs":
        return _prune_mcp_runs_root(policy, now_ts=now_ts, apply=apply)
    if policy.mode == "files":
        return _prune_files_root(policy, now_ts=now_ts, apply=apply)
    raise ValueError(f"Unsupported policy mode: {policy.mode}")


def _policy_from_args(base: RootPolicy, args: argparse.Namespace) -> RootPolicy:
    key = base.key
    days = getattr(args, f"{key}_days", None)
    max_gb = getattr(args, f"{key}_max_gb", None)
    return RootPolicy(
        key=base.key,
        root=base.root,
        mode=base.mode,
        max_age_days=days if days is not None else base.max_age_days,
        max_total_gb=max_gb if max_gb is not None else base.max_total_gb,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Unified retention + path normalization for runtime artifact roots."
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default is dry-run).",
    )
    p.add_argument(
        "--normalize-paths",
        dest="normalize_paths",
        action="store_true",
        default=True,
        help="Normalize alias paths into canonical targets (default: on).",
    )
    p.add_argument(
        "--no-normalize-paths",
        dest="normalize_paths",
        action="store_false",
        help="Disable path normalization step.",
    )
    p.add_argument(
        "--prune",
        dest="prune",
        action="store_true",
        default=True,
        help="Run retention pruning step (default: on).",
    )
    p.add_argument(
        "--no-prune",
        dest="prune",
        action="store_false",
        help="Disable retention pruning step.",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional report path (JSON). Default: artifacts/retention/*.json",
    )

    for base in DEFAULT_POLICIES.values():
        p.add_argument(
            f"--{base.key}-days",
            type=int,
            default=None,
            help=f"Override max-age days for {base.key}.",
        )
        p.add_argument(
            f"--{base.key}-max-gb",
            type=float,
            default=None,
            help=f"Override max total GB for {base.key}.",
        )
    return p


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    now_ts = time.time()
    stamp = now.strftime("%Y%m%d_%H%M%S")

    state_dir = STATE_ROOT / stamp
    conflict_dir = state_dir / "conflicts"
    state_dir.mkdir(parents=True, exist_ok=True)
    conflict_dir.mkdir(parents=True, exist_ok=True)

    report_path = (
        args.report
        if args.report is not None
        else REPO_ROOT / "artifacts" / "retention" / f"retention_report_{stamp}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "timestamp_utc": now.isoformat(),
        "repo_root": str(REPO_ROOT),
        "mode": "apply" if args.apply else "dry-run",
        "normalize_paths": args.normalize_paths,
        "prune": args.prune,
        "state_dir": str(state_dir),
        "conflict_dir": str(conflict_dir),
        "aliases": [],
        "roots": {},
    }

    print("== retention policy ==")
    print(f"repo_root: {REPO_ROOT}")
    print(f"mode: {'apply' if args.apply else 'dry-run'}")
    print(f"normalize_paths: {args.normalize_paths}")
    print(f"prune: {args.prune}")
    print(f"state_dir: {state_dir}")
    print()

    # Normalize canonical roots (without changing public paths).
    for base in DEFAULT_POLICIES.values():
        base.root.mkdir(parents=True, exist_ok=True)

    if args.normalize_paths:
        print("-- path normalization --")
        for alias, target in PATH_ALIASES:
            alias_conflicts = conflict_dir / _safe_relative(alias, REPO_ROOT).replace("/", "__")
            result = _normalize_alias(
                alias,
                target,
                apply=args.apply,
                conflict_root=alias_conflicts,
            )
            report["aliases"].append(result)
            print(
                f"{result['status']}: "
                f"{_safe_relative(alias, REPO_ROOT)} -> {_safe_relative(target, REPO_ROOT)}"
            )
        print()

    if args.prune:
        print("-- retention prune --")
        for key, base in DEFAULT_POLICIES.items():
            policy = _policy_from_args(base, args)
            root_report = prune_root_policy(policy, now_ts=now_ts, apply=args.apply)
            report["roots"][key] = root_report
            print(
                f"{key}: {_bytes_to_gb(root_report['total_before_bytes']):.2f}GB -> "
                f"{_bytes_to_gb(root_report['total_after_bytes']):.2f}GB | "
                f"age_del={root_report.get('deleted_by_age_count', 0)} "
                f"size_del={root_report.get('deleted_by_size_count', 0)}"
            )
        print()

    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
