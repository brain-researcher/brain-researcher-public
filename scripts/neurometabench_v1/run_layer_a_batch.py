#!/usr/bin/env python3
"""Batch runner for NeuroMetaBench Layer A screening experiments.

The batch runner deliberately delegates single-case work to
``run_layer_a_experiment`` and aggregate scoring to ``evaluate_prediction_files``.
It adds bounded concurrency, retry/backoff, resumable per-case outputs, JSONL task
status logging, and aggregate prediction/evaluation files.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.evaluate_study_set import evaluate_prediction_files
from scripts.neurometabench_v1.layer_a_baselines import (
    ASREVIEW_MODES,
    LAYER_A_CANDIDATE_SOURCES,
    LAYER_A_SYSTEMS,
    build_layer_a_baseline_predictions,
)
from scripts.neurometabench_v1.run_layer_a_experiment import run_layer_a_experiment
from scripts.neurometabench_v1.shared import (
    DEFAULT_CASES_PATH,
    DEFAULT_DATA_DIR,
    load_case_records,
    read_jsonl,
    write_jsonl,
)


@dataclass(frozen=True)
class LayerATask:
    meta_pmid: str
    case_id: str
    topic: str | None
    output_dir: Path
    prediction_jsonl: Path
    summary_json: Path


@dataclass(frozen=True)
class TaskResult:
    meta_pmid: str
    case_id: str
    status: str
    prediction_jsonl: str | None = None
    summary_json: str | None = None
    attempts: int = 0
    error: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _append_status(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": _utc_now(), **row}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")


def _load_meta_pmids_file(path: Path) -> list[str]:
    pmids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if clean and not clean.startswith("#"):
            pmids.append(clean)
    return pmids


def _parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _select_layer_a_cases(
    *,
    cases_path: Path,
    output_root: Path,
    candidate_source: str,
    meta_pmids: Iterable[str],
    limit: int | None,
) -> list[LayerATask]:
    wanted = {str(pmid).strip() for pmid in meta_pmids if str(pmid).strip()}
    tasks: list[LayerATask] = []
    for case in load_case_records(cases_path):
        meta_pmid = str(case.get("meta_pmid") or "").strip()
        if not meta_pmid:
            continue
        if wanted and meta_pmid not in wanted and f"neurometabench:{meta_pmid}" not in wanted:
            continue
        layers = case.get("task_layers") or []
        if case.get("primary_task_layer") != "layer_a_screening_with_justification" and (
            "layer_a_screening_with_justification" not in layers
        ):
            continue
        exp_dir = output_root / f"layer_a_{meta_pmid}_{candidate_source}"
        tasks.append(
            LayerATask(
                meta_pmid=meta_pmid,
                case_id=str(case.get("case_id") or f"neurometabench:{meta_pmid}"),
                topic=case.get("topic"),
                output_dir=exp_dir,
                prediction_jsonl=exp_dir / "predictions.jsonl",
                summary_json=exp_dir / "experiment_summary.json",
            )
        )
        if limit is not None and len(tasks) >= limit:
            break
    return tasks


def _is_complete(task: LayerATask) -> bool:
    if not task.prediction_jsonl.exists() or not task.summary_json.exists():
        return False
    try:
        return bool(read_jsonl(task.prediction_jsonl)) and bool(json.loads(task.summary_json.read_text(encoding="utf-8")))
    except Exception:
        return False


def _copy_aggregate_predictions(prediction_paths: list[Path], output: Path) -> int:
    rows: list[dict[str, Any]] = []
    for prediction_path in prediction_paths:
        for row in read_jsonl(prediction_path):
            copied = dict(row)
            copied.setdefault("source_prediction_jsonl", str(prediction_path))
            rows.append(copied)
    write_jsonl(rows, output)
    return len(rows)


def _run_one_sync(
    *,
    task: LayerATask,
    cases_path: Path,
    data_dir: Path,
    output_root: Path,
    candidate_source: str,
    mixed_pool_noise_ratio: int,
    mixed_pool_seed: int,
    max_candidates: int,
    min_candidate_recall_to_screen: float,
    llm_model: str,
    run_screening: bool,
    judge_mode: str,
    judge_model: str,
    judge_repeat: int,
) -> TaskResult:
    result = run_layer_a_experiment(
        meta_pmid=task.meta_pmid,
        cases_path=cases_path,
        data_dir=data_dir,
        output_root=output_root,
        screening_output_dir=None,
        candidate_source=candidate_source,
        mixed_pool_noise_ratio=mixed_pool_noise_ratio,
        mixed_pool_seed=mixed_pool_seed,
        max_candidates=max_candidates,
        min_candidate_recall_to_screen=min_candidate_recall_to_screen,
        llm_model=llm_model,
        run_screening=run_screening,
        judge_mode=judge_mode,
        judge_json=None,
        judge_model=judge_model,
        judge_repeat=judge_repeat,
    )
    return TaskResult(
        meta_pmid=task.meta_pmid,
        case_id=task.case_id,
        status="completed",
        prediction_jsonl=result.get("experiment_dir") and str(task.prediction_jsonl),
        summary_json=result.get("summary_json"),
    )


async def _run_one_with_retry(
    *,
    task: LayerATask,
    semaphore: asyncio.Semaphore,
    status_log: Path,
    retries: int,
    retry_backoff_seconds: float,
    skip_completed: bool,
    dry_run: bool,
    run_kwargs: dict[str, Any],
) -> TaskResult:
    if dry_run:
        _append_status(
            status_log,
            {"event": "dry_run", "meta_pmid": task.meta_pmid, "case_id": task.case_id, "output_dir": task.output_dir},
        )
        return TaskResult(meta_pmid=task.meta_pmid, case_id=task.case_id, status="dry_run")

    if skip_completed and _is_complete(task):
        _append_status(
            status_log,
            {
                "event": "skipped_completed",
                "meta_pmid": task.meta_pmid,
                "case_id": task.case_id,
                "prediction_jsonl": task.prediction_jsonl,
                "summary_json": task.summary_json,
            },
        )
        return TaskResult(
            meta_pmid=task.meta_pmid,
            case_id=task.case_id,
            status="skipped_completed",
            prediction_jsonl=str(task.prediction_jsonl),
            summary_json=str(task.summary_json),
        )

    max_attempts = max(1, retries + 1)
    async with semaphore:
        for attempt in range(1, max_attempts + 1):
            _append_status(
                status_log,
                {"event": "started", "meta_pmid": task.meta_pmid, "case_id": task.case_id, "attempt": attempt},
            )
            try:
                result = await asyncio.to_thread(_run_one_sync, task=task, **run_kwargs)
                result = TaskResult(
                    meta_pmid=result.meta_pmid,
                    case_id=result.case_id,
                    status=result.status,
                    prediction_jsonl=result.prediction_jsonl,
                    summary_json=result.summary_json,
                    attempts=attempt,
                )
                _append_status(status_log, {"event": "completed", **asdict(result)})
                return result
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                _append_status(
                    status_log,
                    {
                        "event": "failed_attempt",
                        "meta_pmid": task.meta_pmid,
                        "case_id": task.case_id,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "error": error,
                    },
                )
                if attempt >= max_attempts:
                    result = TaskResult(
                        meta_pmid=task.meta_pmid,
                        case_id=task.case_id,
                        status="failed",
                        attempts=attempt,
                        error=error,
                    )
                    _append_status(status_log, {"event": "failed", **asdict(result)})
                    return result
                await asyncio.sleep(max(0.0, retry_backoff_seconds) * (2 ** (attempt - 1)))

    raise RuntimeError("unreachable")


async def run_layer_a_batch(
    *,
    cases_path: Path = DEFAULT_CASES_PATH,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_root: Path = Path("benchmarks/neurometabench/experiments/layer_a_batch"),
    meta_pmids: Iterable[str] = (),
    baseline_prediction_paths: Iterable[Path] = (),
    generate_baselines: bool = False,
    baseline_systems: Iterable[str] = LAYER_A_SYSTEMS,
    baseline_candidate_source: str = "mixed_pool",
    baseline_output: Path | None = None,
    baseline_screening_budget: int | None = None,
    baseline_asreview_mode: str = "style",
    baseline_only: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
    concurrency: int = 2,
    retries: int = 2,
    retry_backoff_seconds: float = 5.0,
    skip_completed: bool = True,
    run_screening: bool = False,
    candidate_source: str = "mixed_pool",
    mixed_pool_noise_ratio: int = 5,
    mixed_pool_seed: int = 0,
    max_candidates: int = 150,
    min_candidate_recall_to_screen: float = 0.6,
    llm_model: str = "gemini-2.5-flash",
    judge_mode: str = "heuristic",
    judge_model: str = "gemini-2.5-flash",
    judge_repeat: int = 2,
    status_log: Path | None = None,
    aggregate_predictions: Path | None = None,
    evaluation_dir: Path | None = None,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    status_log = status_log or output_root / "batch_status.jsonl"
    aggregate_predictions = aggregate_predictions or output_root / "predictions.aggregate.jsonl"
    evaluation_dir = evaluation_dir or output_root / "evaluation"

    baseline_paths = [Path(path) for path in baseline_prediction_paths]
    if generate_baselines and not dry_run:
        baseline_output = baseline_output or output_root / "layer_a_baseline_predictions.jsonl"
        baseline_summary = build_layer_a_baseline_predictions(
            cases_path,
            baseline_output,
            data_dir=data_dir,
            systems=baseline_systems,
            meta_pmids=meta_pmids,
            candidate_source=baseline_candidate_source,
            only_with_gt=True,
            max_cases=limit,
            mixed_noise_ratio=mixed_pool_noise_ratio,
            mixed_seed=mixed_pool_seed,
            mixed_max_total=max_candidates,
            screening_budget=baseline_screening_budget,
            asreview_mode=baseline_asreview_mode,
        )
        baseline_paths.append(baseline_output)
        _append_status(status_log, {"event": "generated_baselines", **baseline_summary})
    elif generate_baselines:
        _append_status(
            status_log,
            {
                "event": "planned_baseline_generation",
                "baseline_systems": list(baseline_systems),
                "baseline_candidate_source": baseline_candidate_source,
                "baseline_output": baseline_output or output_root / "layer_a_baseline_predictions.jsonl",
                "baseline_asreview_mode": baseline_asreview_mode,
            },
        )
    missing_baselines = [str(path) for path in baseline_paths if not path.exists()]
    if missing_baselines:
        raise FileNotFoundError(f"Baseline prediction files not found: {', '.join(missing_baselines)}")

    tasks = [] if baseline_only else _select_layer_a_cases(
        cases_path=cases_path,
        output_root=output_root,
        candidate_source=candidate_source,
        meta_pmids=meta_pmids,
        limit=limit,
    )
    if not tasks and not baseline_paths and not (dry_run and generate_baselines):
        raise ValueError("No Layer A tasks selected and no --baseline-predictions files supplied.")

    _append_status(
        status_log,
        {
            "event": "batch_started",
            "n_tasks": len(tasks),
            "n_baseline_prediction_files": len(baseline_paths),
            "generate_baselines": generate_baselines,
            "baseline_only": baseline_only,
            "dry_run": dry_run,
            "concurrency": concurrency,
        },
    )

    run_kwargs = {
        "cases_path": cases_path,
        "data_dir": data_dir,
        "output_root": output_root,
        "candidate_source": candidate_source,
        "mixed_pool_noise_ratio": mixed_pool_noise_ratio,
        "mixed_pool_seed": mixed_pool_seed,
        "max_candidates": max_candidates,
        "min_candidate_recall_to_screen": min_candidate_recall_to_screen,
        "llm_model": llm_model,
        "run_screening": run_screening,
        "judge_mode": judge_mode,
        "judge_model": judge_model,
        "judge_repeat": judge_repeat,
    }
    semaphore = asyncio.Semaphore(max(1, concurrency))
    task_results = await asyncio.gather(
        *[
            _run_one_with_retry(
                task=task,
                semaphore=semaphore,
                status_log=status_log,
                retries=retries,
                retry_backoff_seconds=retry_backoff_seconds,
                skip_completed=skip_completed,
                dry_run=dry_run,
                run_kwargs=run_kwargs,
            )
            for task in tasks
        ]
    )

    completed_prediction_paths = [
        Path(result.prediction_jsonl)
        for result in task_results
        if result.prediction_jsonl and result.status in {"completed", "skipped_completed"}
    ]
    aggregate_input_paths = completed_prediction_paths + baseline_paths
    aggregate: dict[str, Any] | None = None
    if not dry_run and aggregate_input_paths:
        n_prediction_rows = _copy_aggregate_predictions(aggregate_input_paths, aggregate_predictions)
        evaluation = evaluate_prediction_files(
            cases_path=cases_path,
            prediction_paths=[aggregate_predictions],
            output_dir=evaluation_dir,
            add_closed_world_baselines=False,
            data_dir=data_dir,
        )
        aggregate = {
            "prediction_jsonl": str(aggregate_predictions),
            "n_prediction_rows": n_prediction_rows,
            "evaluation": evaluation,
        }
        _append_status(status_log, {"event": "aggregate_completed", **aggregate})

    summary = {
        "status": "dry_run" if dry_run else ("failed" if any(r.status == "failed" for r in task_results) else "completed"),
        "output_root": str(output_root),
        "status_log": str(status_log),
        "n_tasks": len(tasks),
        "n_completed": sum(1 for r in task_results if r.status == "completed"),
        "n_skipped_completed": sum(1 for r in task_results if r.status == "skipped_completed"),
        "n_failed": sum(1 for r in task_results if r.status == "failed"),
        "n_dry_run": sum(1 for r in task_results if r.status == "dry_run"),
        "generated_baselines": generate_baselines,
        "baseline_prediction_files": [str(path) for path in baseline_paths],
        "tasks": [asdict(result) for result in task_results],
        "aggregate": aggregate,
    }
    (output_root / "batch_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    _append_status(status_log, {"event": "batch_finished", "status": summary["status"], "summary_json": output_root / "batch_summary.json"})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-root", type=Path, default=Path("benchmarks/neurometabench/experiments/layer_a_batch"))
    parser.add_argument("--meta-pmid", action="append", default=[], help="Layer A meta-analysis PMID to run. Repeatable.")
    parser.add_argument("--meta-pmids-file", type=Path, help="Text file with one meta-analysis PMID per line.")
    parser.add_argument("--limit", type=int, help="Limit selected Layer A tasks after filtering.")
    parser.add_argument("--baseline-predictions", type=Path, action="append", default=[], help="Existing prediction JSONL to include in aggregate evaluation. Repeatable.")
    parser.add_argument("--generate-baselines", action="store_true", help="Generate deterministic rule and/or ASReview-style Layer A baseline predictions before aggregation.")
    parser.add_argument("--baseline-systems", default="rule,asreview_style", help="Comma-separated baseline systems to generate: rule,asreview_style.")
    parser.add_argument("--baseline-candidate-source", choices=LAYER_A_CANDIDATE_SOURCES, default="mixed_pool")
    parser.add_argument("--baseline-output", type=Path)
    parser.add_argument("--baseline-screening-budget", type=int, help="ASReview-style screened-candidate budget; defaults to selected_n per case.")
    parser.add_argument(
        "--baseline-asreview-mode",
        choices=ASREVIEW_MODES,
        default="style",
        help="ASReview backend for generated baselines: style, external, or auto.",
    )
    parser.add_argument("--baseline-only", action="store_true", help="Evaluate generated/supplied baselines without running Layer A cases.")
    parser.add_argument("--dry-run", action="store_true", help="Write task plan/status only; do not run screening or evaluation.")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=float, default=5.0)
    parser.add_argument("--skip-completed", dest="skip_completed", action="store_true", default=True)
    parser.add_argument("--no-skip-completed", dest="skip_completed", action="store_false")
    parser.add_argument("--run-screening", action="store_true")
    parser.add_argument("--candidate-source", choices=["mixed_pool", "closed_world", "pubmed", "union", "auto"], default="mixed_pool")
    parser.add_argument("--mixed-pool-noise-ratio", type=int, default=5)
    parser.add_argument("--mixed-pool-seed", type=int, default=0)
    parser.add_argument("--max-candidates", type=int, default=150)
    parser.add_argument("--min-candidate-recall-to-screen", type=float, default=0.6)
    parser.add_argument("--llm-model", default="gemini-2.5-flash")
    parser.add_argument("--judge-mode", choices=["none", "heuristic", "gemini"], default="heuristic")
    parser.add_argument("--judge-model", default="gemini-2.5-flash")
    parser.add_argument("--judge-repeat", type=int, default=2)
    parser.add_argument("--status-log", type=Path)
    parser.add_argument("--aggregate-predictions", type=Path)
    parser.add_argument("--evaluation-dir", type=Path)
    args = parser.parse_args()

    meta_pmids = list(args.meta_pmid)
    if args.meta_pmids_file is not None:
        meta_pmids.extend(_load_meta_pmids_file(args.meta_pmids_file))

    start = time.monotonic()
    summary = asyncio.run(
        run_layer_a_batch(
            cases_path=args.cases,
            data_dir=args.data_dir,
            output_root=args.output_root,
            meta_pmids=meta_pmids,
            baseline_prediction_paths=args.baseline_predictions,
            generate_baselines=args.generate_baselines,
            baseline_systems=_parse_csv_list(args.baseline_systems),
            baseline_candidate_source=args.baseline_candidate_source,
            baseline_output=args.baseline_output,
            baseline_screening_budget=args.baseline_screening_budget,
            baseline_asreview_mode=args.baseline_asreview_mode,
            baseline_only=args.baseline_only,
            dry_run=args.dry_run,
            limit=args.limit,
            concurrency=args.concurrency,
            retries=args.retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
            skip_completed=args.skip_completed,
            run_screening=args.run_screening,
            candidate_source=args.candidate_source,
            mixed_pool_noise_ratio=args.mixed_pool_noise_ratio,
            mixed_pool_seed=args.mixed_pool_seed,
            max_candidates=args.max_candidates,
            min_candidate_recall_to_screen=args.min_candidate_recall_to_screen,
            llm_model=args.llm_model,
            judge_mode=args.judge_mode,
            judge_model=args.judge_model,
            judge_repeat=args.judge_repeat,
            status_log=args.status_log,
            aggregate_predictions=args.aggregate_predictions,
            evaluation_dir=args.evaluation_dir,
        )
    )
    summary["elapsed_seconds"] = round(time.monotonic() - start, 3)
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
