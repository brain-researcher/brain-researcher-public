#!/usr/bin/env python3
"""Launch reproducibility-audit rerun manifests one condition at a time."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_DIR = (
    REPO_ROOT
    / "benchmarks"
    / "reproducibility_audit_examples"
    / "runs"
    / "rerun_manifests_20260513"
)
DEFAULT_OUT_ROOT = REPO_ROOT / "benchmarks" / "reproducibility_audit_examples" / "runs"


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def condition_from_manifest(path: Path) -> str:
    suffix = "__rerun_candidates_20260513.csv"
    name = path.name
    if not name.endswith(suffix):
        raise ValueError(f"Unexpected rerun manifest filename: {path}")
    return name[: -len(suffix)]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--run-prefix", default="repro_rerun_cells")
    parser.add_argument("--batch-name", default=None)
    parser.add_argument("--condition", action="append", dest="conditions", default=[])
    parser.add_argument(
        "--agent-conditions-path",
        type=Path,
        default=None,
        help="Optional alternate coding-agent condition JSONL passed through to the episode runner.",
    )
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-opencode-with-br-without-mcp", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.execute == args.dry_run:
        print("Choose exactly one of --execute or --dry-run", file=sys.stderr)
        return 2

    manifest_dir = args.manifest_dir.resolve()
    out_root = args.out_root.resolve()
    manifests = sorted(manifest_dir.glob("*__rerun_candidates_20260513.csv"))
    requested = set(args.conditions)
    if requested:
        manifests = [path for path in manifests if condition_from_manifest(path) in requested]
    if not manifests:
        print(f"No rerun manifests selected from {manifest_dir}", file=sys.stderr)
        return 2

    batch_name = args.batch_name or f"{args.run_prefix}_{timestamp()}"
    batch_dir = out_root / batch_name
    logs_dir = batch_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    plan_rows = []
    for manifest in manifests:
        condition = condition_from_manifest(manifest)
        run_name = f"{batch_name}__{condition}"
        run_dir = out_root / run_name
        cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "reproducibility_audit" / "run_reproducibility_audit_examples.py"),
            "--episode-manifest",
            str(manifest),
            "--condition",
            condition,
            "--out-root",
            str(out_root),
            "--run-name",
            run_name,
            "--timeout-s",
            str(args.timeout_s),
            "--max-workers",
            str(args.max_workers),
            "--reasoning-effort",
            args.reasoning_effort,
        ]
        if args.agent_conditions_path is not None:
            cmd.extend(["--agent-conditions-path", str(args.agent_conditions_path.resolve())])
        cmd.append("--execute" if args.execute else "--dry-run")
        if args.allow_opencode_with_br_without_mcp:
            cmd.append("--allow-opencode-with-br-without-mcp")
        plan_rows.append(
            {
                "condition": condition,
                "manifest": str(manifest),
                "run_name": run_name,
                "run_dir": str(run_dir),
                "log": str(logs_dir / f"{condition}.log"),
                "command": cmd,
            }
        )

    (batch_dir / "batch_plan.json").write_text(
        json.dumps(
            {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "execute": args.execute,
                "timeout_s": args.timeout_s,
                "max_workers": args.max_workers,
                "agent_conditions_path": (
                    str(args.agent_conditions_path.resolve())
                    if args.agent_conditions_path is not None
                    else None
                ),
                "conditions": [row["condition"] for row in plan_rows],
                "runs": plan_rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if args.plan_only:
        print(json.dumps({"batch_dir": str(batch_dir), "runs": plan_rows}, indent=2))
        return 0

    status_path = batch_dir / "batch_status.jsonl"
    for row in plan_rows:
        run_dir = Path(row["run_dir"])
        summary_path = run_dir / "summary.json"
        if args.skip_existing and summary_path.exists():
            status = {"condition": row["condition"], "status": "skipped_existing", "run_dir": str(run_dir)}
            with status_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(status, sort_keys=True) + "\n")
            print(json.dumps(status, sort_keys=True), flush=True)
            continue

        started_at = datetime.now().isoformat(timespec="seconds")
        log_path = Path(row["log"])
        with log_path.open("w", encoding="utf-8") as log_fh:
            log_fh.write(f"$ {' '.join(row['command'])}\n")
            log_fh.flush()
            proc = subprocess.run(
                row["command"],
                cwd=REPO_ROOT,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        status = {
            "condition": row["condition"],
            "status": "completed" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "run_dir": str(run_dir),
            "log": str(log_path),
        }
        with status_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(status, sort_keys=True) + "\n")
        print(json.dumps(status, sort_keys=True), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
