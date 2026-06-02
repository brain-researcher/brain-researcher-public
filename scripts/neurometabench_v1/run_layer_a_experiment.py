#!/usr/bin/env python3
"""Run or summarize one NeuroMetaBench Layer A screening experiment.

This is a thin orchestration wrapper around the existing primitives:

1. optional BR/Gemini screening via ``neurometabench_screening_pipeline.py``;
2. conversion to v1 prediction JSONL;
3. study-set evaluation;
4. optional criterion-alignment judging;
5. compact experiment summary with a confusion matrix.

The wrapper is intentionally small so the experiment remains auditable. It does
not invent a new scoring path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_screening_pipeline import run_pipeline
from scripts.neurometabench_v1.br_screening_adapter import convert_br_screening_outputs
from scripts.neurometabench_v1.criterion_alignment_judge import judge_prediction_files
from scripts.neurometabench_v1.evaluate_study_set import evaluate_prediction_files
from scripts.neurometabench_v1.shared import (
    DEFAULT_CASES_PATH,
    DEFAULT_DATA_DIR,
    case_lookup,
    load_case_records,
    read_jsonl,
)


def _env_present(*names: str) -> bool:
    return any(os.environ.get(name) for name in names)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _case_for_meta(cases_path: Path, meta_pmid: str) -> dict[str, Any]:
    cases = case_lookup(load_case_records(cases_path))
    case = cases.get(meta_pmid) or cases.get(f"neurometabench:{meta_pmid}")
    if case is None:
        raise ValueError(f"Meta PMID {meta_pmid!r} not found in {cases_path}")
    return case


def _load_prediction(path: Path) -> dict[str, Any]:
    rows = read_jsonl(path)
    if len(rows) != 1:
        raise ValueError(f"Expected exactly one prediction row in {path}, found {len(rows)}")
    return rows[0]


def _confusion(case: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    gt = {str(pmid) for pmid in case.get("gt_pmids", [])}
    ranked = {str(pmid) for pmid in prediction.get("ranked_pmids", [])}
    predicted = {str(pmid) for pmid in prediction.get("predicted_pmids", [])}
    tp = gt & predicted
    fp = predicted - gt
    fn = gt - predicted
    tn = ranked - predicted - gt
    return {
        "tp": len(tp),
        "fp": len(fp),
        "fn": len(fn),
        "tn_within_ranked_pool": len(tn),
        "tp_pmids": sorted(tp, key=lambda p: (int(p), p) if p.isdigit() else (10**20, p)),
        "fp_pmids": sorted(fp, key=lambda p: (int(p), p) if p.isdigit() else (10**20, p)),
        "fn_pmids": sorted(fn, key=lambda p: (int(p), p) if p.isdigit() else (10**20, p)),
    }


def _decision_counts(prediction: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in prediction.get("decision_records") or []:
        decision = str(row.get("decision") or "unknown")
        counts[decision] = counts.get(decision, 0) + 1
    return counts


def _write_markdown(summary: dict[str, Any], path: Path) -> None:
    metrics = summary["study_set_metrics"]
    judge = summary.get("criterion_alignment")
    confusion = summary["confusion_matrix"]
    lines = [
        f"# NeuroMetaBench Layer A Experiment: {summary['meta_pmid']}",
        "",
        f"- Topic: {summary['topic']}",
        f"- Candidate source: `{summary['candidate_source']}`",
        f"- Screening output: `{summary['screening_output_dir']}`",
        f"- Prediction JSONL: `{summary['prediction_jsonl']}`",
        f"- Evaluation directory: `{summary['evaluation_dir']}`",
        "",
        "## Study-Set Metrics",
        "",
        f"- Candidate recall: `{metrics.get('candidate_recall')}`",
        f"- Precision: `{metrics.get('precision')}`",
        f"- Recall: `{metrics.get('recall')}`",
        f"- F1: `{metrics.get('f1')}`",
        f"- Average precision: `{metrics.get('average_precision')}`",
        f"- Decision records: `{metrics.get('n_decision_records')}`",
        f"- Reason coverage: `{metrics.get('reason_coverage')}`",
        f"- Criterion coverage: `{metrics.get('criterion_coverage')}`",
        f"- Evidence-span coverage: `{metrics.get('evidence_span_coverage')}`",
        f"- Confidence coverage: `{metrics.get('confidence_coverage')}`",
        "",
        "## Confusion Matrix",
        "",
        f"- TP: `{confusion['tp']}`",
        f"- FP: `{confusion['fp']}`",
        f"- FN: `{confusion['fn']}`",
        f"- TN within ranked pool: `{confusion['tn_within_ranked_pool']}`",
        f"- False-negative PMIDs: `{', '.join(confusion['fn_pmids']) or 'none'}`",
        "",
        "## Criterion-Alignment Judge",
        "",
    ]
    if judge:
        lines.extend(
            [
                f"- Judge output: `{summary.get('criterion_alignment_json')}`",
                f"- Items: `{judge.get('n_items')}`",
                f"- Labels: `{json.dumps(judge.get('label_counts', {}), sort_keys=True)}`",
                f"- Mean alignment score: `{judge.get('mean_alignment_score')}`",
                f"- Mean repeat self-agreement: `{judge.get('mean_repeat_self_agreement')}`",
            ]
        )
    else:
        lines.append("- Not run or not supplied.")
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "Primary command:",
            "",
            "```bash",
            summary["reproduction_command"],
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run_layer_a_experiment(
    *,
    meta_pmid: str,
    cases_path: Path,
    data_dir: Path,
    output_root: Path,
    screening_output_dir: Path | None,
    candidate_source: str,
    mixed_pool_noise_ratio: int,
    mixed_pool_seed: int,
    max_candidates: int,
    min_candidate_recall_to_screen: float,
    llm_model: str,
    run_screening: bool,
    judge_mode: str,
    judge_json: Path | None,
    judge_model: str,
    judge_repeat: int,
) -> dict[str, Any]:
    case = _case_for_meta(cases_path, meta_pmid)
    exp_dir = output_root / f"layer_a_{meta_pmid}_{candidate_source}"
    exp_dir.mkdir(parents=True, exist_ok=True)

    if screening_output_dir is None:
        screening_output_dir = exp_dir / "screening"
    if run_screening:
        if not _env_present("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            raise RuntimeError(
                "GEMINI_API_KEY or GOOGLE_API_KEY is required for --run-screening. "
                "Run `set -a; source /.env; set +a` first if credentials are mounted there."
            )
        run_pipeline(
            meta_pmid=meta_pmid,
            data_dir=data_dir,
            max_candidates=max_candidates,
            llm_model=llm_model,
            output_dir=screening_output_dir,
            api_key_pubmed=os.environ.get("NCBI_API_KEY"),
            use_llm_reformulation=False,
            adapter_only=False,
            candidate_source_mode=candidate_source,
            min_candidate_recall_to_screen=min_candidate_recall_to_screen,
            mixed_pool_noise_ratio=mixed_pool_noise_ratio,
            mixed_pool_seed=mixed_pool_seed,
            skip_analysis_selection=True,
        )
    elif not (screening_output_dir / "screening_decisions.jsonl").exists():
        raise FileNotFoundError(
            f"{screening_output_dir}/screening_decisions.jsonl is missing. "
            "Provide --run-screening or --screening-output-dir."
        )

    prediction_jsonl = exp_dir / "predictions.jsonl"
    convert_br_screening_outputs(
        cases_path=cases_path,
        br_output_dir=screening_output_dir,
        output=prediction_jsonl,
        candidate_source=candidate_source,
    )

    evaluation_dir = exp_dir / "evaluation"
    evaluate_prediction_files(
        cases_path=cases_path,
        prediction_paths=[prediction_jsonl],
        output_dir=evaluation_dir,
        add_closed_world_baselines=False,
        data_dir=data_dir,
    )
    metrics_rows = _load_json(evaluation_dir / "study_set_metrics.json")
    if not metrics_rows:
        raise RuntimeError(f"No evaluation rows written to {evaluation_dir}")
    metrics = metrics_rows[0]

    criterion_alignment_json: Path | None = None
    criterion_alignment_summary: dict[str, Any] | None = None
    if judge_json is not None:
        criterion_alignment_json = judge_json
        criterion_alignment_summary = _load_json(judge_json).get("summary")
    elif judge_mode != "none":
        if judge_mode == "gemini" and not _env_present("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            raise RuntimeError(
                "GEMINI_API_KEY or GOOGLE_API_KEY is required for --judge-mode gemini. "
                "Use --judge-mode heuristic or pass --judge-json to reuse a prior judge output."
            )
        criterion_alignment_json = exp_dir / f"criterion_alignment_{judge_mode}.json"
        judge_result = judge_prediction_files(
            cases_path=cases_path,
            prediction_paths=[prediction_jsonl],
            output=criterion_alignment_json,
            judge_mode=judge_mode,
            model=judge_model,
            repeat=judge_repeat,
        )
        criterion_alignment_summary = judge_result.get("summary")

    prediction = _load_prediction(prediction_jsonl)
    summary = {
        "meta_pmid": meta_pmid,
        "case_id": case.get("case_id"),
        "topic": case.get("topic"),
        "route": case.get("route"),
        "primary_task_layer": case.get("primary_task_layer"),
        "candidate_source": candidate_source,
        "mixed_pool_noise_ratio": mixed_pool_noise_ratio if candidate_source == "mixed_pool" else None,
        "mixed_pool_seed": mixed_pool_seed if candidate_source == "mixed_pool" else None,
        "max_candidates": max_candidates,
        "screening_output_dir": str(screening_output_dir),
        "prediction_jsonl": str(prediction_jsonl),
        "evaluation_dir": str(evaluation_dir),
        "criterion_alignment_json": str(criterion_alignment_json) if criterion_alignment_json else None,
        "study_set_metrics": metrics,
        "decision_counts": _decision_counts(prediction),
        "confusion_matrix": _confusion(case, prediction),
        "criterion_alignment": criterion_alignment_summary,
        "reproduction_command": (
            "python -m scripts.neurometabench_v1.run_layer_a_experiment "
            f"--meta-pmid {meta_pmid} --candidate-source {candidate_source} "
            f"--mixed-pool-noise-ratio {mixed_pool_noise_ratio} --mixed-pool-seed {mixed_pool_seed} "
            f"--max-candidates {max_candidates} --screening-output-dir {screening_output_dir}"
        ),
    }
    summary_json = exp_dir / "experiment_summary.json"
    summary_md = exp_dir / "experiment_summary.md"
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    _write_markdown(summary, summary_md)
    return {
        "experiment_dir": str(exp_dir),
        "summary_json": str(summary_json),
        "summary_md": str(summary_md),
        "summary": {
            "meta_pmid": meta_pmid,
            "precision": metrics.get("precision"),
            "recall": metrics.get("recall"),
            "f1": metrics.get("f1"),
            "candidate_recall": metrics.get("candidate_recall"),
            "criterion_alignment": criterion_alignment_summary,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta-pmid", default="36100907")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-root", type=Path, default=Path("benchmarks/neurometabench/experiments"))
    parser.add_argument("--screening-output-dir", type=Path)
    parser.add_argument("--run-screening", action="store_true")
    parser.add_argument("--candidate-source", choices=["mixed_pool", "closed_world", "pubmed", "union", "auto"], default="mixed_pool")
    parser.add_argument("--mixed-pool-noise-ratio", type=int, default=5)
    parser.add_argument("--mixed-pool-seed", type=int, default=0)
    parser.add_argument("--max-candidates", type=int, default=150)
    parser.add_argument("--min-candidate-recall-to-screen", type=float, default=0.6)
    parser.add_argument("--llm-model", default="gemini-2.5-flash")
    parser.add_argument("--judge-mode", choices=["none", "heuristic", "gemini"], default="heuristic")
    parser.add_argument("--judge-json", type=Path, help="Reuse an existing criterion-alignment judge JSON.")
    parser.add_argument("--judge-model", default="gemini-2.5-flash")
    parser.add_argument("--judge-repeat", type=int, default=2)
    args = parser.parse_args()
    print(
        json.dumps(
            run_layer_a_experiment(
                meta_pmid=args.meta_pmid,
                cases_path=args.cases,
                data_dir=args.data_dir,
                output_root=args.output_root,
                screening_output_dir=args.screening_output_dir,
                candidate_source=args.candidate_source,
                mixed_pool_noise_ratio=args.mixed_pool_noise_ratio,
                mixed_pool_seed=args.mixed_pool_seed,
                max_candidates=args.max_candidates,
                min_candidate_recall_to_screen=args.min_candidate_recall_to_screen,
                llm_model=args.llm_model,
                run_screening=args.run_screening,
                judge_mode=args.judge_mode,
                judge_json=args.judge_json,
                judge_model=args.judge_model,
                judge_repeat=args.judge_repeat,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
