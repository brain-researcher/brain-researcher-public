#!/usr/bin/env python3
"""Run NeuroMetaBench Layer C diagnostic/audit checks.

Layer C is a non-headline diagnostic layer. It does not score model quality.
It records boundary conditions that explain whether Layer A screening and
Layer B reproduction results are interpretable: retrieval ceiling, public-map
substrate coverage, and NiMADS coordinate asset readiness.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.audit_nimads_assets import (
    DEFAULT_AUDIT_JSON,
    DEFAULT_AUDIT_MD,
)
from scripts.neurometabench_v1.audit_nimads_assets import (
    run_audit as run_nimads_asset_audit,
)
from scripts.neurometabench_v1.build_nimads_reproduction_manifest import (
    DEFAULT_OUTPUT as DEFAULT_NIMADS_MANIFEST,
)
from scripts.neurometabench_v1.neurovault_substrate_diagnostic import (
    DEFAULT_METADATA_CSV,
    DEFAULT_NEUROVAULT_COLLECTIONS_CSV,
    DEFAULT_NEUROVAULT_IMAGES_CSV,
)
from scripts.neurometabench_v1.neurovault_substrate_diagnostic import (
    run_diagnostic as run_neurovault_substrate_diagnostic,
)
from scripts.neurometabench_v1.retrieval_only import run_retrieval_diagnostics
from scripts.neurometabench_v1.shared import (
    DEFAULT_CASES_PATH,
    DEFAULT_DATA_DIR,
    LAYER_C_DIAGNOSTIC_AUDIT,
    load_case_records,
    read_jsonl,
    write_jsonl,
)

DEFAULT_OUTPUT_ROOT = Path("benchmarks/neurometabench/experiments/layer_c_diagnostics")
RETRIEVERS = ("closed_world", "mixed_pool", "pubmed")


def _parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _rate(num: int, denom: int) -> float | None:
    return round(num / denom, 6) if denom else None


def build_layer_c_manifest(cases: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        task_layers = list(case.get("task_layers") or [])
        if LAYER_C_DIAGNOSTIC_AUDIT not in task_layers:
            task_layers.append(LAYER_C_DIAGNOSTIC_AUDIT)
        contract = case.get("layer_c_diagnostic_contract") or {}
        rows.append(
            {
                "case_id": case.get("case_id"),
                "meta_pmid": case.get("meta_pmid"),
                "topic": case.get("topic"),
                "route": case.get("route"),
                "primary_task_layer": case.get("primary_task_layer") or LAYER_C_DIAGNOSTIC_AUDIT,
                "task_layers": task_layers,
                "layer": LAYER_C_DIAGNOSTIC_AUDIT,
                "task_type": "diagnostic_audit",
                "headline_score": False,
                "n_gt": int(case.get("n_gt") or len(case.get("gt_pmids") or [])),
                "has_gt": bool(case.get("has_gt") or case.get("gt_pmids")),
                "diagnostic_contract": contract
                or {
                    "layer": LAYER_C_DIAGNOSTIC_AUDIT,
                    "role": "diagnostic_audit_not_headline_score",
                    "headline_score": False,
                    "audits": [],
                },
            }
        )
    return rows


def summarize_manifest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    primary_counts = Counter(str(row.get("primary_task_layer") or "unknown") for row in rows)
    route_counts = Counter(str(row.get("route") or "unknown") for row in rows)
    n_gt_cases = sum(1 for row in rows if row.get("has_gt"))
    return {
        "layer": LAYER_C_DIAGNOSTIC_AUDIT,
        "role": "diagnostic_audit_not_headline_score",
        "headline_score": False,
        "n_cases": len(rows),
        "n_cases_with_gt": n_gt_cases,
        "n_cases_without_gt": len(rows) - n_gt_cases,
        "primary_task_layer_counts": dict(sorted(primary_counts.items())),
        "route_counts": dict(sorted(route_counts.items())),
    }


def _retrieval_health(summary: dict[str, Any]) -> dict[str, Any]:
    by_mode = summary.get("macro_candidate_recall_by_mode") or {}
    union_recall = by_mode.get("union_query")
    return {
        "retriever": summary.get("retriever"),
        "n_cases": summary.get("n_cases"),
        "n_rows": summary.get("n_rows"),
        "n_failures": summary.get("n_failures"),
        "macro_candidate_recall": summary.get("macro_candidate_recall"),
        "union_macro_candidate_recall": union_recall,
        "screening_gate": summary.get("screening_gate"),
    }


def _neurovault_health(result: dict[str, Any]) -> dict[str, Any]:
    overall = (result.get("summary") or {}).get("overall") or {}
    return {
        "n_cases": result.get("n_cases"),
        "n_metadata_pmids_with_pmcid": result.get("n_metadata_pmids_with_pmcid"),
        "n_pmcids_with_neurovault_links": result.get("n_pmcids_with_neurovault_links"),
        "micro_gt_neurovault_collection_coverage": overall.get("micro_gt_neurovault_collection_coverage"),
        "micro_gt_neurovault_image_coverage": overall.get("micro_gt_neurovault_image_coverage"),
        "micro_gt_pmcid_coverage": overall.get("micro_gt_pmcid_coverage"),
    }


def _nimads_health(result: dict[str, Any]) -> dict[str, Any]:
    summary = result.get("summary") or {}
    return {
        "n_cases": summary.get("n_cases"),
        "n_cases_with_coordinate_gt": summary.get("n_cases_with_coordinate_gt"),
        "n_cases_with_annotation_labels": summary.get("n_cases_with_annotation_labels"),
        "path_b_status_counts": summary.get("path_b_status_counts"),
        "total_nimads_points": summary.get("total_nimads_points"),
    }


def write_markdown(summary: dict[str, Any], output: Path) -> None:
    lines = [
        "# NeuroMetaBench Layer C Diagnostics",
        "",
        "Layer C is a diagnostic/audit layer, not a headline model score.",
        "",
        "## Summary",
        "",
    ]
    manifest = summary["manifest_summary"]
    lines.extend(
        [
            f"- `layer`: `{manifest['layer']}`",
            f"- `n_cases`: `{manifest['n_cases']}`",
            f"- `n_cases_with_gt`: `{manifest['n_cases_with_gt']}`",
            f"- `headline_score`: `{manifest['headline_score']}`",
            f"- `primary_task_layer_counts`: `{manifest['primary_task_layer_counts']}`",
        ]
    )
    if summary.get("retrieval"):
        lines.extend(["", "## Retrieval Ceiling", ""])
        for retriever, result in summary["retrieval"].items():
            health = result["health"]
            lines.append(
                "- `{}`: union macro candidate recall `{}`, failures `{}`".format(
                    retriever,
                    health.get("union_macro_candidate_recall"),
                    health.get("n_failures"),
                )
            )
    if summary.get("neurovault"):
        lines.extend(["", "## NeuroVault Substrate", ""])
        for key, value in summary["neurovault"]["health"].items():
            lines.append(f"- `{key}`: `{value}`")
    if summary.get("nimads"):
        lines.extend(["", "## NiMADS Assets", ""])
        for key, value in summary["nimads"]["health"].items():
            lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Use Layer C to explain retrieval/substrate ceilings and missing assets.",
            "- Do not aggregate Layer C as a model capability score.",
            "- Layer A and Layer B remain the scored benchmark layers.",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_layer_c_diagnostics(
    *,
    cases_path: Path = DEFAULT_CASES_PATH,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    retrievers: Iterable[str] = ("closed_world", "mixed_pool"),
    max_candidates: int = 500,
    max_cases: int | None = None,
    pubmed_api_key: str | None = None,
    email: str | None = None,
    sleep_s: float = 0.34,
    run_retrieval: bool = True,
    run_neurovault: bool = True,
    run_nimads: bool = True,
    metadata_csv: Path = DEFAULT_METADATA_CSV,
    neurovault_collections_csv: Path = DEFAULT_NEUROVAULT_COLLECTIONS_CSV,
    neurovault_images_csv: Path = DEFAULT_NEUROVAULT_IMAGES_CSV,
    nimads_manifest: Path = DEFAULT_NIMADS_MANIFEST,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    cases = load_case_records(cases_path)
    if max_cases is not None:
        cases = cases[: max(0, int(max_cases))]

    manifest_rows = build_layer_c_manifest(cases)
    manifest_path = output_root / "layer_c_manifest.jsonl"
    write_jsonl(manifest_rows, manifest_path)

    artifacts: dict[str, Any] = {
        "manifest_jsonl": str(manifest_path),
    }
    diagnostic_cases_path = cases_path
    if max_cases is not None:
        diagnostic_cases_path = output_root / "layer_c_cases.filtered.jsonl"
        write_jsonl(cases, diagnostic_cases_path)
        artifacts["filtered_cases_jsonl"] = str(diagnostic_cases_path)
    retrieval_results: dict[str, Any] = {}
    requested_retrievers = tuple(retrievers)
    unknown_retrievers = sorted(set(requested_retrievers) - set(RETRIEVERS))
    if unknown_retrievers:
        raise ValueError(f"Unsupported Layer C retrieval diagnostics: {unknown_retrievers}")

    if run_retrieval:
        for retriever in requested_retrievers:
            output = output_root / f"retrieval_{retriever}.jsonl"
            result = run_retrieval_diagnostics(
                diagnostic_cases_path,
                output,
                retriever=retriever,
                data_dir=data_dir,
                max_candidates=max_candidates,
                max_cases=None,
                only_with_gt=True,
                api_key=pubmed_api_key,
                email=email,
                sleep_s=sleep_s,
            )
            summary_path = output_root / f"retrieval_{retriever}_summary.json"
            _write_json(summary_path, result)
            retrieval_results[retriever] = {
                "summary_json": str(summary_path),
                "rows_jsonl": str(output),
                "health": _retrieval_health(result),
                "result": result,
            }
    neurovault_result: dict[str, Any] | None = None
    if run_neurovault:
        neurovault_result = run_neurovault_substrate_diagnostic(
            cases_path=diagnostic_cases_path,
            metadata_csv=metadata_csv,
            neurovault_collections_csv=neurovault_collections_csv,
            neurovault_images_csv=neurovault_images_csv,
            output_jsonl=output_root / "neurovault_substrate_coverage.jsonl",
            output_summary=output_root / "neurovault_substrate_coverage_summary.json",
        )
    nimads_result: dict[str, Any] | None = None
    nimads_skipped: dict[str, Any] | None = None
    if run_nimads:
        if nimads_manifest.exists():
            audit_manifest = nimads_manifest
            if max_cases is not None:
                wanted_meta_pmids = {str(case.get("meta_pmid") or "") for case in cases}
                manifest_rows_for_cases = [
                    row for row in read_jsonl(nimads_manifest) if str(row.get("meta_pmid") or "") in wanted_meta_pmids
                ]
                audit_manifest = output_root / "nimads_reproduction_manifest.filtered.jsonl"
                write_jsonl(manifest_rows_for_cases, audit_manifest)
                artifacts["filtered_nimads_manifest_jsonl"] = str(audit_manifest)
            nimads_result = run_nimads_asset_audit(
                cases_path=diagnostic_cases_path,
                manifest_path=audit_manifest,
                output_json=output_root / DEFAULT_AUDIT_JSON.name,
                output_md=output_root / DEFAULT_AUDIT_MD.name,
            )
        else:
            nimads_skipped = {
                "status": "skipped",
                "reason": "nimads_manifest_missing",
                "manifest": str(nimads_manifest),
            }

    summary: dict[str, Any] = {
        "layer": LAYER_C_DIAGNOSTIC_AUDIT,
        "role": "diagnostic_audit_not_headline_score",
        "headline_score": False,
        "inputs": {
            "cases": str(cases_path),
            "data_dir": str(data_dir),
            "max_candidates": max_candidates,
            "max_cases": max_cases,
        },
        "artifacts": artifacts,
        "manifest_summary": summarize_manifest(manifest_rows),
        "retrieval": retrieval_results,
        "neurovault": None
        if neurovault_result is None
        else {
            "rows_jsonl": neurovault_result["output_jsonl"],
            "summary_json": neurovault_result["output_summary"],
            "health": _neurovault_health(neurovault_result),
            "result": neurovault_result,
        },
        "nimads": None
        if nimads_result is None and nimads_skipped is None
        else (
            nimads_skipped
            if nimads_skipped is not None
            else {
                "audit_json": str(output_root / DEFAULT_AUDIT_JSON.name),
                "audit_md": str(output_root / DEFAULT_AUDIT_MD.name),
                "health": _nimads_health(nimads_result or {}),
                "result": nimads_result,
            }
        ),
    }
    summary_path = output_root / "layer_c_diagnostic_summary.json"
    markdown_path = output_root / "layer_c_diagnostic_summary.md"
    _write_json(summary_path, summary)
    write_markdown(summary, markdown_path)
    summary["artifacts"]["summary_json"] = str(summary_path)
    summary["artifacts"]["summary_md"] = str(markdown_path)
    _write_json(summary_path, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--retrievers",
        default="closed_world,mixed_pool",
        help="Comma-separated retrieval diagnostics to run: closed_world,mixed_pool,pubmed.",
    )
    parser.add_argument("--max-candidates", type=int, default=500)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--pubmed-api-key")
    parser.add_argument("--email")
    parser.add_argument("--sleep-s", type=float, default=0.34)
    parser.add_argument("--skip-retrieval", action="store_true")
    parser.add_argument("--skip-neurovault", action="store_true")
    parser.add_argument("--skip-nimads", action="store_true")
    parser.add_argument("--metadata-csv", type=Path, default=DEFAULT_METADATA_CSV)
    parser.add_argument("--neurovault-collections-csv", type=Path, default=DEFAULT_NEUROVAULT_COLLECTIONS_CSV)
    parser.add_argument("--neurovault-images-csv", type=Path, default=DEFAULT_NEUROVAULT_IMAGES_CSV)
    parser.add_argument("--nimads-manifest", type=Path, default=DEFAULT_NIMADS_MANIFEST)
    args = parser.parse_args()
    print(
        json.dumps(
            run_layer_c_diagnostics(
                cases_path=args.cases,
                data_dir=args.data_dir,
                output_root=args.output_root,
                retrievers=_parse_csv_list(args.retrievers),
                max_candidates=args.max_candidates,
                max_cases=args.max_cases,
                pubmed_api_key=args.pubmed_api_key,
                email=args.email,
                sleep_s=args.sleep_s,
                run_retrieval=not args.skip_retrieval,
                run_neurovault=not args.skip_neurovault,
                run_nimads=not args.skip_nimads,
                metadata_csv=args.metadata_csv,
                neurovault_collections_csv=args.neurovault_collections_csv,
                neurovault_images_csv=args.neurovault_images_csv,
                nimads_manifest=args.nimads_manifest,
            ),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
