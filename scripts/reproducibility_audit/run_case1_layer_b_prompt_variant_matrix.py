#!/usr/bin/env python3
"""Run reproducibility-audit Case 1 prompt variants through NeuroMetaBench Layer B.

This is a bridge for the ALE reproducibility-audit case. It reuses the
NeuroMetaBench Layer B coding-agent harness for writable-workspace execution and
comparison, while expanding the reproducibility-audit prompt variants as the
input perturbation axis.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1 import run_agent_condition_matrix as matrix

DEFAULT_REPRO_CASE = (
    matrix.REPO_ROOT
    / "benchmarks"
    / "reproducibility_audit_examples"
    / "case_001_neurometabench_ale_30793072.json"
)
DEFAULT_META_PMID = "30793072"
DEFAULT_CODEX_PAIR = (
    "codex_cli_gpt55_without_br",
    "codex_cli_gpt55_with_br",
)
MEMORY_LEAK_PATTERNS = (
    "/app/.codex",
    "/app/.agents",
    "MEMORY.md",
    "memory_summary.md",
    "rollout_summaries",
    "log_research_event",
    "write_session_snapshot",
)
BENCHMARK_GUIDANCE_PATTERNS = (
    "benchmarks/experiment_setup.md",
)
PRIOR_EXPERIMENT_PATTERNS = (
    "benchmarks/neurometabench/experiments/agent_condition_matrix/",
    "benchmarks/neurometabench/experiments/path_b_reproduction",
    "benchmarks/neurometabench/experiments/layer_b_comparison",
)
MAX_ISOLATION_EXCERPTS = 25
ISOLATED_NEUROMETABENCH_SCRIPT_FILES = (
    "scripts/__init__.py",
    "scripts/neurometabench_v1/__init__.py",
    "scripts/neurometabench_v1/shared.py",
    "scripts/neurometabench_v1/build_nimads_reproduction_manifest.py",
    "scripts/neurometabench_v1/run_path_b_reproduction.py",
)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def rewrite_repo_paths(value: Any, *, isolated_root: Path) -> Any:
    old_prefix = str(matrix.REPO_ROOT)
    new_prefix = str(isolated_root)
    if isinstance(value, dict):
        return {
            key: rewrite_repo_paths(item, isolated_root=isolated_root)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [rewrite_repo_paths(item, isolated_root=isolated_root) for item in value]
    if isinstance(value, str):
        return value.replace(old_prefix, new_prefix)
    return value


def copy_isolated_script_subset(isolated_root: Path) -> None:
    for relative in ISOLATED_NEUROMETABENCH_SCRIPT_FILES:
        source = matrix.REPO_ROOT / relative
        if not source.exists():
            continue
        target = isolated_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    # Avoid exposing the pure-control output path in the isolated script copy.
    reproduction_script = (
        isolated_root / "scripts" / "neurometabench_v1" / "run_path_b_reproduction.py"
    )
    if reproduction_script.exists():
        text = reproduction_script.read_text(encoding="utf-8")
        text = text.replace(
            'DEFAULT_OUTPUT_ROOT = Path("benchmarks/neurometabench/experiments/path_b_reproduction")',
            'DEFAULT_OUTPUT_ROOT = Path("outputs/path_b_reproduction")',
        )
        reproduction_script.write_text(text, encoding="utf-8")


def copy_required_nimads_assets(
    *,
    case: dict[str, Any],
    isolated_root: Path,
) -> None:
    assets = case.get("nimads_assets") or {}
    project_dir = Path(str(assets.get("project_dir") or ""))
    if not project_dir.exists():
        raise FileNotFoundError(f"Missing NiMADS project_dir: {project_dir}")
    relative_project_dir = project_dir.relative_to(matrix.REPO_ROOT)
    target_project_dir = isolated_root / relative_project_dir
    if target_project_dir.exists():
        shutil.rmtree(target_project_dir)
    shutil.copytree(
        project_dir,
        target_project_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def write_isolated_case_files(
    *,
    case: dict[str, Any],
    original_input_dir: Path,
    isolated_root: Path,
) -> Path:
    meta_pmid = str(case.get("meta_pmid") or "")
    case_input_dir = isolated_root / "case_inputs" / "layer_b" / f"layer_b_{meta_pmid}"
    case_input_dir.mkdir(parents=True, exist_ok=True)

    original_case = read_json(original_input_dir / "case.json")
    original_manifest = read_json(original_input_dir / "input_manifest.json")
    isolated_case = rewrite_repo_paths(original_case, isolated_root=isolated_root)
    isolated_manifest = rewrite_repo_paths(original_manifest, isolated_root=isolated_root)
    # Keep the isolated input focused on the structured NiMADS substrate.
    isolated_case.pop("pmc_assets", None)
    matrix.write_json(case_input_dir / "case.json", isolated_case)
    matrix.write_json(case_input_dir / "input_manifest.json", isolated_manifest)
    return case_input_dir


def write_isolated_neurometabench_metadata(
    *,
    case: dict[str, Any],
    isolated_root: Path,
) -> None:
    meta_pmid = str(case.get("meta_pmid") or "")
    benchmark_dir = isolated_root / "benchmarks" / "neurometabench"
    benchmark_dir.mkdir(parents=True, exist_ok=True)

    isolated_case = rewrite_repo_paths(case, isolated_root=isolated_root)
    isolated_case.pop("pmc_assets", None)
    write_jsonl(benchmark_dir / "cases.v1.jsonl", [isolated_case])

    manifest_rows = [
        row
        for row in matrix.read_jsonl_rows(
            matrix.REPO_ROOT
            / "benchmarks"
            / "neurometabench"
            / "nimads_reproduction_manifest.jsonl"
        )
        if str(row.get("meta_pmid") or "") == meta_pmid
    ]
    if not manifest_rows:
        raise ValueError(f"No NiMADS reproduction manifest row for PMID {meta_pmid}")
    write_jsonl(
        benchmark_dir / "nimads_reproduction_manifest.jsonl",
        [rewrite_repo_paths(manifest_rows[0], isolated_root=isolated_root)],
    )

    (benchmark_dir / "README.md").write_text(
        "Isolated NeuroMetaBench Case 1 workspace. This workspace intentionally "
        "contains only sanitized case metadata, the NiMADS source asset needed "
        "for this episode, and the minimal reproduction script subset.\n",
        encoding="utf-8",
    )


def prepare_isolated_workspace(
    *,
    run_dir: Path,
    condition_id: str,
    case: dict[str, Any],
    original_input_dir: Path,
    reset: bool,
) -> tuple[Path, Path, Path]:
    isolated_root = run_dir / "isolated_workspaces" / condition_id
    if reset and isolated_root.exists():
        shutil.rmtree(isolated_root)
    isolated_root.mkdir(parents=True, exist_ok=True)
    copy_isolated_script_subset(isolated_root)
    copy_required_nimads_assets(case=case, isolated_root=isolated_root)
    case_input_dir = write_isolated_case_files(
        case=case,
        original_input_dir=original_input_dir,
        isolated_root=isolated_root,
    )
    write_isolated_neurometabench_metadata(case=case, isolated_root=isolated_root)
    isolated_producer_output_dir = isolated_root / "producer_outputs" / condition_id
    return isolated_root, case_input_dir, isolated_producer_output_dir


def selected_prompt_variants(
    repro_case: dict[str, Any],
    variant_ids: set[str],
) -> list[dict[str, Any]]:
    variants = list(repro_case.get("prompt_variants") or [])
    if variant_ids:
        variants = [
            variant
            for variant in variants
            if str(variant.get("variant_id") or "") in variant_ids
        ]
    if not variants:
        raise ValueError("No matching prompt variants selected.")
    return variants


def select_conditions(args: argparse.Namespace) -> list[matrix.Condition]:
    conditions = matrix.filter_conditions(
        matrix.load_conditions(args.conditions_file),
        layer="layer_b",
        condition_ids=set(args.condition),
        runners=set(args.runner),
        max_conditions=args.max_conditions,
    )
    if not args.all_coding_agents and not args.condition and not args.runner:
        requested = set(DEFAULT_CODEX_PAIR)
        conditions = [
            condition for condition in conditions if condition.condition_id in requested
        ]
    if not conditions:
        raise ValueError("No matching Layer B coding-agent conditions.")
    return conditions


def synthetic_condition(
    condition: matrix.Condition,
    variant: dict[str, Any],
) -> matrix.Condition:
    variant_id = str(variant.get("variant_id") or "")
    raw = dict(condition.raw)
    raw["base_condition_id"] = condition.condition_id
    raw["prompt_variant_id"] = variant_id
    raw["prompt_variant_type"] = variant.get("variant_type")
    return matrix.Condition(
        condition_id=f"{condition.condition_id}__{variant_id}",
        runner=condition.runner,
        model_target=condition.model_target,
        br_mode=condition.br_mode,
        layers=condition.layers,
        raw=raw,
    )


def variant_base_prompt(
    base_prompt: str,
    repro_case: dict[str, Any],
    variant: dict[str, Any],
) -> str:
    axes = [
        {
            "axis": axis.get("axis"),
            "canonical_expectation": axis.get("canonical_expectation"),
        }
        for axis in repro_case.get("scoring_axes") or []
    ]
    output_contract = repro_case.get("output_contract") or {}
    canonical_task = repro_case.get("canonical_task") or {}
    canonical_validation = repro_case.get("canonical_validation") or {}
    return f"""{base_prompt.rstrip()}

---

# Reproducibility-Audit Prompt Variant Overlay

This episode is also part of reproducibility-audit Case 1.

Reproducibility case:
- case_id: `{repro_case.get("case_id")}`
- title: `{repro_case.get("title")}`
- task_shape: `{repro_case.get("task_shape")}`
- variant_id: `{variant.get("variant_id")}`
- variant_type: `{variant.get("variant_type")}`

User prompt variant:

{variant.get("prompt")}

Canonical intent:
{canonical_task.get("description") or ""}

Required pipeline expectations:
{json.dumps(canonical_task.get("required_pipeline_steps") or [], ensure_ascii=False, indent=2)}

Do-not constraints:
{json.dumps(canonical_task.get("do_not") or [], ensure_ascii=False, indent=2)}

Reproducibility scoring axes:
{json.dumps(axes, ensure_ascii=False, indent=2)}

Output contract from reproducibility audit:
{json.dumps(output_contract.get("required_files") or output_contract, ensure_ascii=False, indent=2)}

Canonical validation status:
{json.dumps(canonical_validation, ensure_ascii=False, indent=2)}

Use the NeuroMetaBench Layer B producer output directory from the matrix
override as the concrete bundle location. The reproducibility-audit output
contract is an evaluation expectation, not permission to inspect prior control
outputs or benchmark answer keys.

Benchmark isolation:
- Do not inspect client memory, user memory, or agent memory files such as
  `~/.codex`, `~/.agents`, `.codex`, `.agents`, or rollout summaries.
- Do not inspect prior run outputs except the sanitized per-case input
  directory supplied by the matrix launcher.
- Do not call research logging, session snapshot, durable-memory, or run
  management tools inside the benchmark episode.
"""


def build_variant_episodes(
    *,
    run_dir: Path,
    base_prompt: str,
    repro_case: dict[str, Any],
    variants: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    input_dirs: dict[str, Path],
    conditions: list[matrix.Condition],
    args: argparse.Namespace,
) -> tuple[list[matrix.Episode], list[matrix.Condition], dict[str, dict[str, Any]]]:
    episodes: list[matrix.Episode] = []
    synthetic_conditions: list[matrix.Condition] = []
    episode_meta: dict[str, dict[str, Any]] = {}
    for variant in variants:
        for base_condition in conditions:
            condition = synthetic_condition(base_condition, variant)
            synthetic_conditions.append(condition)
            meta_pmid = str(cases[0].get("meta_pmid") or "")
            canonical_producer_output_dir = (
                run_dir / "producer_outputs" / condition.condition_id
            )
            prompt_input_dirs = input_dirs
            producer_output_dir = canonical_producer_output_dir
            command_repo_root = matrix.REPO_ROOT
            isolated_workspace = None
            isolated_producer_output_dir = None
            if args.isolated_workspace:
                (
                    isolated_workspace,
                    isolated_case_input_dir,
                    isolated_producer_output_dir,
                ) = prepare_isolated_workspace(
                    run_dir=run_dir,
                    condition_id=condition.condition_id,
                    case=cases[0],
                    original_input_dir=input_dirs[meta_pmid],
                    reset=not args.resume,
                )
                prompt_input_dirs = {meta_pmid: isolated_case_input_dir}
                producer_output_dir = isolated_producer_output_dir
                command_repo_root = isolated_workspace
            prompt = matrix.build_prompt(
                base_prompt=variant_base_prompt(base_prompt, repro_case, variant),
                layer="layer_b",
                condition=condition,
                cases=cases,
                input_dirs=prompt_input_dirs,
                producer_output_dir=producer_output_dir,
                max_candidates=args.max_candidates,
                mixed_pool_noise_ratio=args.mixed_pool_noise_ratio,
                mixed_pool_seed=args.mixed_pool_seed,
            )
            command, skip_reason = matrix.build_command(
                condition=condition,
                prompt=prompt,
                run_dir=run_dir,
                repo_root=command_repo_root,
                codex_bin=args.codex_bin,
                claude_bin=args.claude_bin,
                opencode_bin=args.opencode_bin,
                claude_br_mcp_config=args.claude_br_mcp_config,
                allow_opencode_with_br=args.allow_opencode_with_br_without_mcp,
            )
            episode_id = f"{condition.condition_id}/layer_b_{meta_pmid}"
            episode = matrix.Episode(
                condition=condition,
                episode_dir=run_dir / "episodes" / episode_id,
                producer_output_dir=producer_output_dir,
                command=command,
                prompt=prompt,
                meta_pmids=(meta_pmid,),
                status="skipped" if skip_reason else "materialized",
                skip_reason=skip_reason,
            )
            episodes.append(episode)
            episode_meta[condition.condition_id] = {
                "base_condition_id": base_condition.condition_id,
                "prompt_variant_id": variant.get("variant_id"),
                "prompt_variant_type": variant.get("variant_type"),
                "repro_case_id": repro_case.get("case_id"),
                "canonical_producer_output_dir": str(canonical_producer_output_dir),
                "isolated_workspace": str(isolated_workspace)
                if isolated_workspace
                else None,
                "isolated_producer_output_dir": str(isolated_producer_output_dir)
                if isolated_producer_output_dir
                else None,
            }
    return episodes, synthetic_conditions, episode_meta


def augment_records(
    records: list[dict[str, Any]],
    episode_meta: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    augmented: list[dict[str, Any]] = []
    for record in records:
        copied = dict(record)
        copied.update(episode_meta.get(str(record.get("condition_id")), {}))
        record_path = Path(str(copied.get("episode_dir") or "")) / "record.json"
        if record_path.exists():
            matrix.write_json(record_path, copied)
        augmented.append(copied)
    return augmented


def sync_isolated_outputs(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    synced: list[dict[str, Any]] = []
    for record in records:
        copied = dict(record)
        isolated_output = copied.get("isolated_producer_output_dir")
        canonical_output = copied.get("canonical_producer_output_dir")
        if (
            copied.get("status") == "succeeded"
            and isolated_output
            and canonical_output
        ):
            isolated_path = Path(str(isolated_output))
            canonical_path = Path(str(canonical_output))
            if isolated_path.exists():
                if canonical_path.exists():
                    shutil.rmtree(canonical_path)
                shutil.copytree(
                    isolated_path,
                    canonical_path,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
                copied["producer_output_dir"] = str(canonical_path)
                copied["synced_from_isolated_producer_output_dir"] = str(isolated_path)
            else:
                copied["isolation_sync_warning"] = (
                    f"isolated producer output not found: {isolated_path}"
                )
        record_path = Path(str(copied.get("episode_dir") or "")) / "record.json"
        if record_path.exists():
            matrix.write_json(record_path, copied)
        synced.append(copied)
    return synced


def _record_isolation_hit(
    hits: list[dict[str, Any]],
    *,
    condition_id: str,
    file_path: Path,
    line_number: int,
    pattern: str,
    line: str,
) -> None:
    if len(hits) >= MAX_ISOLATION_EXCERPTS:
        return
    hits.append(
        {
            "condition_id": condition_id,
            "file": str(file_path),
            "line": line_number,
            "pattern": pattern,
            "excerpt": line[:500],
        }
    )


def _is_prior_experiment_exclusion_reference(line: str) -> bool:
    """Ignore child search-command globs that explicitly exclude prior outputs."""
    return any(
        marker in line
        for marker in (
            "!benchmarks/neurometabench/experiments/",
            "-g '\\\"'!benchmarks/neurometabench/experiments/",
            "-g '!'benchmarks/neurometabench/experiments/",
        )
    )


def scan_episode_isolation(
    *,
    run_dir: Path,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Scan child-agent logs for evidence of benchmark-isolation leakage."""
    memory_hits: list[dict[str, Any]] = []
    guidance_hits: list[dict[str, Any]] = []
    prior_experiment_hits: list[dict[str, Any]] = []
    current_run_name = run_dir.name

    for record in records:
        condition_id = str(record.get("condition_id") or "")
        episode_dir = Path(str(record.get("episode_dir") or ""))
        if not episode_dir.exists():
            continue
        for file_path in (episode_dir / "stdout.txt", episode_dir / "stderr.txt"):
            if not file_path.exists():
                continue
            for line_number, line in enumerate(
                file_path.read_text(encoding="utf-8", errors="replace").splitlines(),
                start=1,
            ):
                for pattern in MEMORY_LEAK_PATTERNS:
                    if pattern in line:
                        _record_isolation_hit(
                            memory_hits,
                            condition_id=condition_id,
                            file_path=file_path,
                            line_number=line_number,
                            pattern=pattern,
                            line=line,
                        )
                for pattern in BENCHMARK_GUIDANCE_PATTERNS:
                    if pattern in line:
                        _record_isolation_hit(
                            guidance_hits,
                            condition_id=condition_id,
                            file_path=file_path,
                            line_number=line_number,
                            pattern=pattern,
                            line=line,
                        )
                for pattern in PRIOR_EXPERIMENT_PATTERNS:
                    if (
                        pattern in line
                        and current_run_name not in line
                        and not _is_prior_experiment_exclusion_reference(line)
                    ):
                        _record_isolation_hit(
                            prior_experiment_hits,
                            condition_id=condition_id,
                            file_path=file_path,
                            line_number=line_number,
                            pattern=pattern,
                            line=line,
                        )

    status = (
        "clean"
        if not memory_hits and not guidance_hits and not prior_experiment_hits
        else "warning"
    )
    return {
        "status": status,
        "scanned_files": [
            str(Path(str(record.get("episode_dir") or "")) / name)
            for record in records
            for name in ("stdout.txt", "stderr.txt")
        ],
        "memory_leak_hit_count": len(memory_hits),
        "benchmark_guidance_hit_count": len(guidance_hits),
        "prior_experiment_hit_count": len(prior_experiment_hits),
        "memory_leak_hits": memory_hits,
        "benchmark_guidance_hits": guidance_hits,
        "prior_experiment_hits": prior_experiment_hits,
        "interpretation": (
            "clean means no scanned child-agent stdout/stderr references to "
            "client memory, benchmark guidance docs, or prior NeuroMetaBench "
            "experiment outputs were detected. warning means the run should be "
            "treated as smoke/debug evidence until manually reviewed."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repro-case", type=Path, default=DEFAULT_REPRO_CASE)
    parser.add_argument("--meta-pmid", default=DEFAULT_META_PMID)
    parser.add_argument("--conditions-file", type=Path, default=matrix.DEFAULT_CONDITIONS_PATH)
    parser.add_argument("--cases", type=Path, default=matrix.DEFAULT_CASES_PATH)
    parser.add_argument("--output-root", type=Path, default=matrix.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-name")
    parser.add_argument("--condition", action="append", default=[])
    parser.add_argument("--runner", action="append", default=[])
    parser.add_argument("--variant", action="append", default=[])
    parser.add_argument("--all-coding-agents", action="store_true")
    parser.add_argument("--max-conditions", type=int)
    parser.add_argument("--max-candidates", type=int, default=150)
    parser.add_argument("--mixed-pool-noise-ratio", type=int, default=5)
    parser.add_argument("--mixed-pool-seed", type=int, default=0)
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--isolated-workspace",
        action="store_true",
        help=(
            "Run each coding-agent episode from a minimal per-condition workspace "
            "containing only sanitized Case 1 inputs, required NiMADS assets, and "
            "the minimal Layer B reproduction script subset."
        ),
    )
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--opencode-bin", default="opencode")
    parser.add_argument("--env-file", type=Path, default=matrix.REPO_ROOT / ".env")
    parser.add_argument("--claude-br-mcp-config", type=Path, default=matrix.REPO_ROOT / ".mcp.json")
    parser.add_argument("--allow-opencode-with-br-without-mcp", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.execute and args.dry_run:
        print("Use either --execute or --dry-run, not both.", file=sys.stderr)
        return 2
    if args.env_file:
        matrix.load_env_file(args.env_file)

    dry_run = not args.execute
    run_name = args.run_name or (
        f"repro_case001_layer_b_prompt_variants_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    run_dir = args.output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    repro_case = read_json(args.repro_case)
    variants = selected_prompt_variants(repro_case, set(args.variant))
    conditions = select_conditions(args)
    cases = matrix.select_cases(
        cases_path=args.cases,
        layer="layer_b",
        meta_pmids={str(args.meta_pmid)},
        limit_cases=1,
    )
    if len(cases) != 1:
        raise SystemExit(f"Expected one NeuroMetaBench Layer B case for PMID {args.meta_pmid}")

    input_dirs = matrix.materialize_layer_b_inputs(run_dir=run_dir, cases=cases)
    base_prompt = matrix.DEFAULT_LAYER_B_PROMPT.read_text(encoding="utf-8")
    episodes, synthetic_conditions, episode_meta = build_variant_episodes(
        run_dir=run_dir,
        base_prompt=base_prompt,
        repro_case=repro_case,
        variants=variants,
        cases=cases,
        input_dirs=input_dirs,
        conditions=conditions,
        args=args,
    )
    matrix.write_json(
        run_dir / "prompt_variant_manifest.json",
        {
            "repro_case": str(args.repro_case),
            "repro_case_id": repro_case.get("case_id"),
            "meta_pmid": str(args.meta_pmid),
            "variants": [
                {
                    "variant_id": variant.get("variant_id"),
                    "variant_type": variant.get("variant_type"),
                    "prompt": variant.get("prompt"),
                }
                for variant in variants
            ],
            "base_conditions": [condition.condition_id for condition in conditions],
            "synthetic_conditions": [condition.condition_id for condition in synthetic_conditions],
        },
    )

    records = matrix.run_episodes(
        episodes=episodes,
        timeout_s=args.timeout_s,
        dry_run=dry_run,
        max_workers=args.max_workers,
        resume=args.resume,
        records_path=run_dir / "episode_records.jsonl",
    )
    records = augment_records(records, episode_meta)
    if args.isolated_workspace and not dry_run:
        records = sync_isolated_outputs(records)
    write_jsonl(run_dir / "episode_records.augmented.jsonl", records)

    evaluation_dir = None
    if not dry_run:
        evaluation_dir = matrix.compare_layer_b_outputs(
            run_dir=run_dir,
            conditions=synthetic_conditions,
            records=records,
        )

    summary = matrix.write_run_summary(
        run_dir=run_dir,
        layer="layer_b",
        cases=cases,
        conditions=synthetic_conditions,
        records=records,
        evaluation_dir=evaluation_dir,
        episode_scope="case_prompt_variant",
        output_validation={},
    )
    summary["repro_case_id"] = repro_case.get("case_id")
    summary["prompt_variant_ids"] = [variant.get("variant_id") for variant in variants]
    summary["base_condition_ids"] = [condition.condition_id for condition in conditions]
    summary["isolated_workspace_enabled"] = bool(args.isolated_workspace)
    isolation_scan = scan_episode_isolation(run_dir=run_dir, records=records)
    summary["isolation_scan"] = isolation_scan
    matrix.write_json(run_dir / "isolation_scan.json", isolation_scan)
    matrix.write_json(run_dir / "RUN_SUMMARY.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
