#!/usr/bin/env python3
"""Refresh Layer B episode records with the current harness finalizer.

This is a posthoc maintenance command for long-running agent matrices. It is
useful when the finalizer or BR-anchor tracer changes after a matrix has already
written terminal `record.json` files.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.layer_b_harness_finalizer import (
    BR_REQUIRED_MODES,
    finalize_layer_b_episode,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BR_MODES_WITH_TOOLS = {"with_br_mcp", "with_br_required", *BR_REQUIRED_MODES}
TERMINAL_STATUSES = {
    "succeeded",
    "failed",
    "timed_out",
    "failed_output_validation",
    "failed_br_required_gate",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _br_required_for_record(record: dict[str, Any], *, force_required: bool) -> bool:
    br_mode = str(record.get("br_mode") or "")
    return br_mode in BR_MODES_WITH_TOOLS and (
        force_required or br_mode in BR_REQUIRED_MODES
    )


def _command_for_record(record: dict[str, Any]) -> list[str]:
    episode_dir_raw = str(record.get("episode_dir") or "")
    if not episode_dir_raw:
        return []
    episode_dir = Path(episode_dir_raw)
    command_payload = _read_json(episode_dir / "command.json")
    command = command_payload.get("command")
    if isinstance(command, list):
        return [str(part) for part in command]
    return []


def refresh_record(
    record: dict[str, Any],
    *,
    run_dir: Path,
    require_br_effective_use: bool,
    repo_root: Path,
) -> tuple[dict[str, Any], bool]:
    """Return an updated record and whether it changed."""

    status = str(record.get("status") or "")
    if status not in TERMINAL_STATUSES:
        return record, False
    producer_output_raw = str(record.get("producer_output_dir") or "")
    meta_pmids = [str(value) for value in (record.get("meta_pmids") or []) if str(value)]
    if not producer_output_raw or not meta_pmids:
        return record, False
    producer_output_dir = Path(producer_output_raw)

    old_record = dict(record)
    br_required = _br_required_for_record(
        record,
        force_required=require_br_effective_use,
    )
    finalizer = finalize_layer_b_episode(
        producer_output_dir=producer_output_dir,
        input_root=run_dir / "case_inputs" / "layer_b",
        meta_pmids=meta_pmids,
        condition_metadata={
            "condition_id": record.get("condition_id"),
            "runner": record.get("runner"),
            "model_target": record.get("model_target"),
            "br_mode": record.get("br_mode"),
        },
        command=_command_for_record(record),
        started_at=record.get("started_at"),
        ended_at=record.get("ended_at"),
        repo_root=repo_root,
        episode_dir=Path(str(record.get("episode_dir") or ""))
        if record.get("episode_dir")
        else None,
        require_br_effective_use=br_required,
    )

    updated = dict(record)
    updated["layer_b_harness_finalizer"] = finalizer
    if br_required:
        if status == "succeeded" and not finalizer["all_br_required_pass"]:
            updated["status"] = "failed_br_required_gate"
            updated["error"] = "BR-required condition did not produce an effective BR anchor"
        elif status == "failed_br_required_gate" and finalizer["all_br_required_pass"]:
            updated["status"] = "succeeded"
            updated.pop("error", None)
            updated["posthoc_status_repair"] = "failed_br_required_gate_to_succeeded"

    return updated, updated != old_record


def refresh_run(
    *,
    run_dir: Path,
    records_path: Path | None = None,
    require_br_effective_use: bool = False,
    repo_root: Path = REPO_ROOT,
    backup_suffix: str = ".pre_layer_b_refresh",
    dry_run: bool = False,
) -> dict[str, Any]:
    records_path = records_path or run_dir / "episode_records.jsonl"
    rows = _read_jsonl(records_path)
    if dry_run:
        refreshable = sum(
            1
            for row in rows
            if str(row.get("status") or "") in TERMINAL_STATUSES
            and row.get("producer_output_dir")
            and row.get("meta_pmids")
        )
        return {
            "run_dir": str(run_dir),
            "records_path": str(records_path),
            "n_records": len(rows),
            "n_refreshable": refreshable,
            "n_changed": 0,
            "n_repaired_failed_br_required_gate": 0,
            "n_failed_br_required_gate_after_refresh": None,
            "dry_run": True,
        }

    updated_rows: list[dict[str, Any]] = []
    changed = 0
    repaired = 0
    failed_gate = 0

    for row in rows:
        updated, did_change = refresh_record(
            row,
            run_dir=run_dir,
            require_br_effective_use=require_br_effective_use,
            repo_root=repo_root,
        )
        if did_change:
            changed += 1
        if updated.get("posthoc_status_repair") == "failed_br_required_gate_to_succeeded":
            repaired += 1
        if updated.get("status") == "failed_br_required_gate":
            failed_gate += 1
        updated_rows.append(updated)

    if not dry_run:
        backup_path = records_path.with_name(records_path.name + backup_suffix)
        if records_path.exists() and not backup_path.exists():
            shutil.copy2(records_path, backup_path)
        _write_jsonl(records_path, updated_rows)
        for row in updated_rows:
            episode_dir_raw = str(row.get("episode_dir") or "")
            if episode_dir_raw:
                _write_json(Path(episode_dir_raw) / "record.json", row)

    return {
        "run_dir": str(run_dir),
        "records_path": str(records_path),
        "n_records": len(rows),
        "n_changed": changed,
        "n_repaired_failed_br_required_gate": repaired,
        "n_failed_br_required_gate_after_refresh": failed_gate,
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--records-path", type=Path)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--require-br-effective-use", action="store_true")
    parser.add_argument("--backup-suffix", default=".pre_layer_b_refresh")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    summary = refresh_run(
        run_dir=args.run_dir,
        records_path=args.records_path,
        require_br_effective_use=args.require_br_effective_use,
        repo_root=args.repo_root,
        backup_suffix=args.backup_suffix,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
