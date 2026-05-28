"""Run a small regression sweep over real FC predictive artifacts.

This script imports a curated set of FC metrics JSON files into the local BR MCP
run store, computes code review and deterministic scientific review verdicts,
and writes a reproducible JSON summary.

Usage:
  python scripts/review/run_fc_external_review_sweep.py

  python scripts/review/run_fc_external_review_sweep.py \
      --metrics-root /data/brain_researcher/research/predictive/project/artifacts/metrics \
      --source-path banghcp_phase8_rawtarget_pmat24_a_cr_graph_transformer_termiu_term014_nocov_verified_n325.json \
      --source-path banghcp_phase0_rawtarget_pmat24_a_cr_ridge_termiu_term014_nocov_verified_n325.json \
      --output-json data/exports/review/fc_external_review_sweep_custom.json

Inputs:
  - FC metrics JSON files under ``--metrics-root`` or explicit absolute paths via
    ``--source-path``.

Outputs:
  - JSON summary file (default under ``data/exports/review/``)
  - Imported runs under ``BR_MCP_RUN_ROOT/runs/<run_id>``

Env:
  - ``BR_MCP_RUN_ROOT`` optional; defaults to the repo's configured run store.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.config.run_artifacts import get_mcp_run_root
from brain_researcher.services.review.distill_review import (
    distill_review_records,
    distill_scientific_review_records,
)
from brain_researcher.services.review.external_run_import import (
    ExternalRunImportSpec,
    stage_external_run_in_mcp_store,
)

UTC = timezone.utc

DEFAULT_METRICS_ROOT = Path(
    "/data/brain_researcher/research/predictive/project/artifacts/metrics"
)
DEFAULT_SOURCE_PATHS = (
    "banghcp_phase8_rawtarget_pmat24_a_cr_graph_transformer_termiu_term014_nocov_verified_n325.json",
    "banghcp_phase0_rawtarget_pmat24_a_cr_ridge_termiu_term014_nocov_verified_n325.json",
    "banghcp_phase8_rawtarget_pmat24_a_cr_fttransformer_termiu_term014_nocov_verified_n325.json",
    "banghcp_phase0_rawtarget_pmat24_a_cr_ridge_termiu_term014_cov_verified_n325_labelshuffle20260402.json",
    "banghcp_laneA_derivative_replay_ridge_feat0_term132.json",
    "banghcp_phase8_rawtarget_cardsort_unadj_graph_transformer_termiu_term000_nocov_verified_n326.json",
    "banghcp_phase2_rawtarget_listsort_unadj_fttransformer_termiu_term120_nocov_verified_n326.json",
    "banghcp_phase2_rawtarget_cardsort_unadj_brainnetcnn_termiu_term000_nocov_verified_n326.json",
)


@dataclass(slots=True)
class SweepResult:
    source_path: str
    run_id: str
    adapter_name: str | None
    review_tier: str | None
    code_decision: str | None
    code_risk_level: str | None
    code_findings: list[str]
    scientific_overall: str | None
    scientific_correctness: str | None
    scientific_completeness: str | None
    scientific_missing_caveats: list[str]
    task: str | None
    statistical_method: str | None
    n_subjects: float | int | None
    r_squared: float | None
    external_n_folds: int | None
    external_mean_test_r2: float | None
    external_mean_test_pearson_r: float | None
    status: str = "ok"
    error: str | None = None


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _slug(text: str) -> str:
    cleaned = [ch.lower() if ch.isalnum() else "-" for ch in text.strip()]
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:96]


def _resolve_sources(metrics_root: Path, explicit_sources: list[str]) -> list[Path]:
    names = explicit_sources or list(DEFAULT_SOURCE_PATHS)
    resolved: list[Path] = []
    for item in names:
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = metrics_root / item
        resolved.append(path.resolve())
    return resolved


def _extract_metric(stats: dict[str, Any], key: str) -> Any:
    value = stats.get(key)
    return value if value is not None else None


def _run_single_source(
    source_path: Path,
    *,
    run_root: Path,
    run_id_prefix: str,
    link_mode: str,
    use_judgment_critic: bool,
) -> SweepResult:
    run_id = f"{run_id_prefix}-{_slug(source_path.stem)}"
    import_result = stage_external_run_in_mcp_store(
        source_path,
        spec=ExternalRunImportSpec(run_id=run_id),
        run_root=run_root,
        link_mode=link_mode,
        adapter_preference="auto",
        overwrite=True,
        dry_run=False,
    )
    run_dir = Path(import_result.run_dir)
    code = distill_review_records(run_id, run_dir=run_dir, force_recompute=True)
    scientific = distill_scientific_review_records(
        run_id,
        run_dir=run_dir,
        use_judgment_critic=use_judgment_critic,
        force_recompute=True,
    )
    code_verdict = code.verdict
    stats = code.bundle.stats_metrics if code.bundle is not None else {}
    kg_context = code.bundle.kg_context if code.bundle is not None else {}
    return SweepResult(
        source_path=str(source_path),
        run_id=run_id,
        adapter_name=import_result.adapter_name,
        review_tier=import_result.review_tier,
        code_decision=code_verdict.decision if code_verdict else None,
        code_risk_level=code_verdict.risk_level if code_verdict else None,
        code_findings=[
            finding.rule_id
            for finding in (code_verdict.findings if code_verdict else [])
        ],
        scientific_overall=scientific.overall_decision,
        scientific_correctness=scientific.correctness.decision,
        scientific_completeness=scientific.completeness.decision,
        scientific_missing_caveats=list(scientific.completeness.missing_caveats),
        task=kg_context.get("task"),
        statistical_method=kg_context.get("statistical_method"),
        n_subjects=_extract_metric(stats, "n_subjects"),
        r_squared=_extract_metric(stats, "r_squared"),
        external_n_folds=_extract_metric(stats, "external_n_folds"),
        external_mean_test_r2=_extract_metric(stats, "external_mean_test_r2"),
        external_mean_test_pearson_r=_extract_metric(
            stats, "external_mean_test_pearson_r"
        ),
    )


def _aggregate(results: list[SweepResult]) -> dict[str, Any]:
    ok_results = [result for result in results if result.status == "ok"]
    aggregate: dict[str, Any] = {
        "total": len(results),
        "ok": len(ok_results),
        "failed": len(results) - len(ok_results),
        "adapter_counts": {},
        "code_decision_counts": {},
        "scientific_overall_counts": {},
        "scientific_completeness_counts": {},
        "metrics_coverage": {
            "n_subjects": 0,
            "r_squared": 0,
            "external_n_folds": 0,
            "external_mean_test_r2": 0,
            "external_mean_test_pearson_r": 0,
        },
    }
    for result in results:
        for field_name, bucket in (
            ("adapter_name", "adapter_counts"),
            ("code_decision", "code_decision_counts"),
            ("scientific_overall", "scientific_overall_counts"),
            ("scientific_completeness", "scientific_completeness_counts"),
        ):
            value = getattr(result, field_name)
            key = str(value or "none")
            aggregate[bucket][key] = aggregate[bucket].get(key, 0) + 1
        for metric_key in aggregate["metrics_coverage"]:
            if getattr(result, metric_key) is not None:
                aggregate["metrics_coverage"][metric_key] += 1
    return aggregate


def _default_output_path() -> Path:
    return Path("data/exports/review") / f"fc_external_review_sweep_{_utc_stamp()}.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metrics-root",
        default=str(DEFAULT_METRICS_ROOT),
        help="Root directory containing FC metrics JSON files.",
    )
    parser.add_argument(
        "--source-path",
        action="append",
        default=[],
        help="Relative path under --metrics-root or an absolute JSON path. Repeatable.",
    )
    parser.add_argument(
        "--run-root",
        default=None,
        help="Optional explicit BR_MCP_RUN_ROOT override.",
    )
    parser.add_argument(
        "--run-id-prefix",
        default="fc-sweep",
        help="Prefix for imported synthetic run ids.",
    )
    parser.add_argument(
        "--link-mode",
        choices=("symlink", "copy"),
        default="symlink",
        help="How imported artifacts should be mounted into the run store.",
    )
    parser.add_argument(
        "--use-judgment-critic",
        action="store_true",
        help="Enable the LLM judgment critic during scientific review.",
    )
    parser.add_argument(
        "--output-json",
        default=str(_default_output_path()),
        help="Where to write the JSON summary.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    metrics_root = Path(args.metrics_root).expanduser().resolve()
    run_root = (
        Path(args.run_root).expanduser().resolve()
        if args.run_root
        else get_mcp_run_root()
    )
    sources = _resolve_sources(metrics_root, list(args.source_path))

    results: list[SweepResult] = []
    for source_path in sources:
        if not source_path.exists():
            results.append(
                SweepResult(
                    source_path=str(source_path),
                    run_id=f"{args.run_id_prefix}-{_slug(source_path.stem)}",
                    adapter_name=None,
                    review_tier=None,
                    code_decision=None,
                    code_risk_level=None,
                    code_findings=[],
                    scientific_overall=None,
                    scientific_correctness=None,
                    scientific_completeness=None,
                    scientific_missing_caveats=[],
                    task=None,
                    statistical_method=None,
                    n_subjects=None,
                    r_squared=None,
                    external_n_folds=None,
                    external_mean_test_r2=None,
                    external_mean_test_pearson_r=None,
                    status="error",
                    error="source_path_not_found",
                )
            )
            continue
        try:
            results.append(
                _run_single_source(
                    source_path,
                    run_root=run_root,
                    run_id_prefix=args.run_id_prefix,
                    link_mode=args.link_mode,
                    use_judgment_critic=args.use_judgment_critic,
                )
            )
        except Exception as exc:
            results.append(
                SweepResult(
                    source_path=str(source_path),
                    run_id=f"{args.run_id_prefix}-{_slug(source_path.stem)}",
                    adapter_name=None,
                    review_tier=None,
                    code_decision=None,
                    code_risk_level=None,
                    code_findings=[],
                    scientific_overall=None,
                    scientific_correctness=None,
                    scientific_completeness=None,
                    scientific_missing_caveats=[],
                    task=None,
                    statistical_method=None,
                    n_subjects=None,
                    r_squared=None,
                    external_n_folds=None,
                    external_mean_test_r2=None,
                    external_mean_test_pearson_r=None,
                    status="error",
                    error=str(exc),
                )
            )

    payload = {
        "ok": True,
        "generated_at": _utc_stamp(),
        "metrics_root": str(metrics_root),
        "run_root": str(run_root),
        "use_judgment_critic": bool(args.use_judgment_critic),
        "sources": [str(path) for path in sources],
        "aggregate": _aggregate(results),
        "results": [asdict(result) for result in results],
    }

    output_path = Path(args.output_json).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
