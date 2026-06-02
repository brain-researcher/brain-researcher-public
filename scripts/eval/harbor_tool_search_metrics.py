#!/usr/bin/env python3
"""Compute Harbor tool-search top-k metrics for baseline vs cards mode."""

from __future__ import annotations

import argparse
import ast
import csv
import json
import os
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HARBOR_JSON = (
    _REPO_ROOT
    / "apps"
    / "web-ui"
    / "public"
    / "benchmarks"
    / "neuroimage-code-bench.harbor.json"
)
DEFAULT_BENCH_CSV = Path(
    "/app/data/brain_researcher_benchmark/BrainRearcherBenchmark_MicroTooling.clean.csv"
)

_PREPROCESSING_BASE_TOOLS = (
    "fmriprep_preprocessing",
    "workflow_fmriprep_preprocessing",
    "motion_quantification",
)
_DENOISING_TOOLS = (
    "fsl_fix",
    "fsl_melodic",
    "nilearn_preprocessing",
    "workflow_fmriprep_preprocessing",
)
_QC_TIMESERIES_TOOLS = (
    "workflow_preprocessing_qc",
    "workflow_mriqc",
    "mriqc_group_report",
    "motion_quantification",
)
_RANDOMISE_TOOLS = (
    "fsl_palm",
    "multiple_comparison_correction",
)
_LESION_TOOLS = ("lesion_detection",)
_TEDANA_TOOLS = (
    "afni.24.2.06.tedana_wrapper.py.run",
    "workflow_fmriprep_preprocessing",
)


def _parse_expected_capabilities(row: dict[str, str]) -> list[str]:
    raw = (row.get("expected_capability_list") or "").strip()
    if raw:
        try:
            values = ast.literal_eval(raw)
            if isinstance(values, list):
                return [str(v).strip() for v in values if str(v).strip()]
        except Exception:
            pass
    fallback = row.get("expected_capability") or ""
    return [part.strip() for part in fallback.split(";") if part.strip()]


def _task_query(task: dict, query_source: str) -> str:
    title = str(task.get("title") or "").strip()
    instruction = str(task.get("instruction") or "").strip()
    instruction_query = title
    for line in instruction.splitlines():
        stripped = line.strip()
        if stripped.startswith("Task:"):
            instruction_query = stripped.removeprefix("Task:").strip()
            break
    if query_source == "instruction":
        return instruction_query or title
    if query_source == "both" and instruction_query and instruction_query != title:
        return f"{title}\n{instruction_query}".strip()
    return title or instruction_query


def _task_id(task: dict) -> str:
    return str(task.get("task_id") or task.get("id") or "").strip()


def _add(target: set[str], *values: str) -> None:
    for value in values:
        if value:
            target.add(value)


def _gold_tools_for_task(task: dict, benchmark_row: dict[str, str] | None) -> list[str]:
    title = str(task.get("title") or "")
    instruction = str(task.get("instruction") or "")
    text = f"{title}\n{instruction}".lower()
    category = str(
        task.get("category") or benchmark_row.get("task_category")
        if benchmark_row
        else ""
    ).lower()
    capabilities = {
        cap.lower()
        for cap in (
            _parse_expected_capabilities(benchmark_row) if benchmark_row else []
        )
    }

    tools: set[str] = set()

    if "searchlight" in text:
        _add(tools, "searchlight_analysis", "mvpa")
    if "brain age" in text:
        _add(tools, "compute_brain_age")
    if "vbm" in text:
        _add(tools, "spm12_vbm")
    if any(
        token in text
        for token in ("fdr", "fwe", "tfce", "multiple comparison", "bonferroni")
    ):
        _add(tools, "multiple_comparison_correction")
    if "registration" in text or "mni152" in text or "syn" in text:
        _add(tools, "ants_registration", "fsl_fnirt", "fsl_flirt")
    if (
        "motion correction" in text
        or "realignment" in text
        or "volume registration" in text
    ):
        _add(tools, *_PREPROCESSING_BASE_TOOLS)
    if any(
        token in text
        for token in (
            "ica-aroma",
            "ica aroma",
            "compcor",
            "physiological noise",
            "temporal filtering",
            "temporal filter",
            "bandpass",
            "nuisance regression",
            "denoising",
        )
    ):
        _add(tools, *_DENOISING_TOOLS)
    if any(
        token in text
        for token in ("scrubbing", "high-motion", "high motion", "temporal snr")
    ):
        _add(tools, *_QC_TIMESERIES_TOOLS, "nilearn_preprocessing")
    if any(token in text for token in ("tedana", "multi-echo", "multi echo")):
        _add(tools, *_TEDANA_TOOLS)
    if any(token in text for token in ("lesion", "stroke patient")):
        _add(tools, *_LESION_TOOLS)
    if any(
        token in text
        for token in ("randomise", "cluster-extent", "cluster extent", "permutation")
    ):
        _add(tools, *_RANDOMISE_TOOLS)
    if "connectivity" in text:
        _add(tools, "connectivity_matrix", "seed_based_fc")
    if "quality assurance" in text or "qc" in text:
        _add(tools, "mriqc_group_report", "freesurfer_qc")
    if "visualiz" in text or "plot" in text or "render" in text:
        _add(tools, "viz_stat_maps")
    if "meta-analysis" in text or "coordinate-based" in text:
        _add(tools, "coordinate_meta_analysis")

    for cap in capabilities:
        if any(
            token in cap
            for token in (
                "ants_tool",
                "syn_registration",
                "registration_tool",
                "registration",
                "flirt_tool",
                "affine_registration",
                "multimodal_registration",
            )
        ):
            _add(tools, "ants_registration", "fsl_fnirt", "fsl_flirt")
        if any(
            token in cap
            for token in (
                "motion_correction",
                "fmriprep_tool",
                "ica_aroma_tool",
                "temporal_filter_tool",
                "compcor_tool",
                "cpac_tool",
                "specialized_processing_tool",
                "realignment_tool",
            )
        ):
            _add(tools, *_PREPROCESSING_BASE_TOOLS)
        if any(
            token in cap
            for token in (
                "ica_aroma_tool",
                "compcor_tool",
                "temporal_filter_tool",
                "bandpass",
                "nuisance_regression",
            )
        ):
            _add(tools, *_DENOISING_TOOLS)
        if any(
            token in cap
            for token in (
                "multiecho_tool",
                "tedana",
            )
        ):
            _add(tools, *_TEDANA_TOOLS)
        if any(
            token in cap
            for token in (
                "connectivity_tool",
                "conn_tool",
                "graph_theory_tool",
                "connectome_tool",
                "dynamic_connectivity_tool",
                "nilearn_signal_extraction",
                "gnn_connectivity_tool",
            )
        ):
            _add(tools, "connectivity_matrix", "seed_based_fc")
        if any(
            token in cap
            for token in (
                "mvpa_tool",
                "svm_classifier",
                "feature_selection_tool",
                "anova_feature_selection",
                "nested_cv_tool",
                "hyperparameter_tuning",
            )
        ):
            if "searchlight" in text:
                _add(tools, "searchlight_analysis", "mvpa")
            else:
                _add(tools, "decoding_classifier", "mvpa", "temporal_decoding")
        if any(
            token in cap
            for token in (
                "fdr_correction_tool",
                "multiple_comparisons",
                "multiple_comparison_tool",
                "statistical_inference_tool",
                "permutation_testing_tool",
                "permutation_test",
                "fsl_palm_tool",
                "bonferroni_tool",
                "fwe_control",
            )
        ):
            _add(tools, "multiple_comparison_correction")
        if any(
            token in cap
            for token in ("nilearn_glm_tool", "first_level", "second_level")
        ):
            _add(tools, "glm_first_level")
        if any(
            token in cap
            for token in (
                "qa_report_tool",
                "data_profiler",
                "qc_tools",
                "mriqc_tool",
                "motion_qc",
                "qc_metrics",
                "artifact_detection_tool",
                "coverage_checker",
                "timeseries_qc",
            )
        ):
            _add(tools, "mriqc_group_report", "freesurfer_qc", "motion_quantification")
            _add(tools, *_QC_TIMESERIES_TOOLS)
        if any(
            token in cap
            for token in (
                "data_management_tool",
                "bids_tools",
                "data_catalog_tool",
                "metadata_indexer",
                "data_linker",
                "archive_tool",
                "sync_tool",
                "data_dictionary_tool",
            )
        ):
            _add(
                tools,
                "datasets.describe_resources",
                "openneuro.search",
                "br_kg.search_datasets",
            )
        if any(
            token in cap
            for token in (
                "coordinate_meta_analysis_tool",
                "image_based_meta_analysis_tool",
            )
        ):
            _add(tools, "coordinate_meta_analysis", "meta_analysis")
        if any(
            token in cap for token in ("knowledge_graph_tool", "neurosynth_integration")
        ):
            _add(tools, "br_kg.search_nodes", "kg_multihop_qa")
        if any(token in cap for token in ("data_harmonization_tool", "harmonization")):
            _add(tools, "data_harmonization")
        if any(
            token in cap
            for token in ("advanced_visualization_tool", "visualization_tool")
        ):
            _add(tools, "viz_stat_maps")
        if any(token in cap for token in ("realtime_fmri_tool", "real-time")):
            _add(tools, "realtime_fmri")
        if any(
            token in cap
            for token in (
                "spm_segment_tool",
                "tissue_classification",
                "fsl_fast_tool",
                "bias_correction",
                "freesurfer_tool",
                "freesurfer_morphometry",
                "surface_metrics",
                "surface_projection_tool",
                "volume_to_surface",
                "myelin_mapping_tool",
                "surface_projection",
                "lesion_detection_tool",
                "segmentation_tool",
                "automated_segmentation",
            )
        ):
            _add(tools, "spm12_vbm", "freesurfer_qc")
        if any(
            token in cap
            for token in ("lesion_detection_tool", "automated_segmentation")
        ):
            _add(tools, *_LESION_TOOLS)
        if any(token in cap for token in ("fsl_randomise_tool", "permutation_test")):
            _add(tools, *_RANDOMISE_TOOLS)
        if any(token in cap for token in ("clinical_decision_support",)):
            if "brain age" in text:
                _add(tools, "compute_brain_age")
            else:
                _add(tools, "decoding_classifier")

    if category in {"registration"}:
        _add(tools, "ants_registration", "fsl_fnirt", "fsl_flirt")
    if category in {"preprocessing"}:
        _add(tools, *_PREPROCESSING_BASE_TOOLS)
    if category in {"connectivity", "connectivity analysis"}:
        _add(tools, "connectivity_matrix", "seed_based_fc")
    if category in {"machine learning"}:
        if "searchlight" in text:
            _add(tools, "searchlight_analysis", "mvpa")
        else:
            _add(tools, "decoding_classifier", "mvpa", "temporal_decoding")
    if category in {"statistics", "statistical inference", "statistical analysis"}:
        _add(tools, "multiple_comparison_correction")
        if "randomise" in text or "cluster-extent" in text or "cluster extent" in text:
            _add(tools, *_RANDOMISE_TOOLS)
    if category in {"quality control"}:
        _add(tools, "mriqc_group_report", "freesurfer_qc")
    if category in {"visualization"}:
        _add(tools, "viz_stat_maps")
    if category in {"meta-analysis"}:
        _add(tools, "coordinate_meta_analysis", "meta_analysis")
    if category in {"harmonization"}:
        _add(tools, "data_harmonization")
    if category in {"knowledge graph"}:
        _add(tools, "br_kg.search_nodes", "kg_multihop_qa")
    if category in {"real-time / streaming"}:
        _add(tools, "realtime_fmri")

    return sorted(tools)


@contextmanager
def _tool_search_mode(mode: str) -> Iterator[None]:
    original = {
        "BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE": os.environ.get(
            "BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE"
        ),
        "BR_TOOL_FAMILY_ROUTING_MODE": os.environ.get("BR_TOOL_FAMILY_ROUTING_MODE"),
    }
    try:
        os.environ["BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE"] = mode
        os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] = mode
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run_tool_search(query: str, *, limit: int, exposed_only: bool) -> list[str]:
    from brain_researcher.services.mcp import server as srv

    payload = srv.tool_search(
        query=query,
        limit=limit,
        exposed_only=exposed_only,
        include_workflows=True,
        include_total=True,
    )
    return [str(item.get("name") or "") for item in (payload.get("tools") or [])]


def _hit(names: list[str], gold: Iterable[str], k: int) -> bool:
    gold_set = set(gold)
    return any(name in gold_set for name in names[:k])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harbor-json", type=Path, default=DEFAULT_HARBOR_JSON)
    parser.add_argument("--benchmark-csv", type=Path, default=DEFAULT_BENCH_CSV)
    parser.add_argument(
        "--query-source",
        choices=("title", "instruction", "both"),
        default="title",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--exposed-only",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    harbor = json.loads(args.harbor_json.read_text(encoding="utf-8"))
    tasks = harbor.get("tasks") or []

    bench_by_id: dict[str, dict[str, str]] = {}
    with args.benchmark_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            task_id = str(row.get("task_id") or "").strip()
            if task_id:
                bench_by_id[task_id] = row

    results: list[dict] = []
    for task in tasks:
        task_id = _task_id(task)
        benchmark_row = bench_by_id.get(task_id)
        gold = _gold_tools_for_task(task, benchmark_row)
        covered = benchmark_row is not None and bool(gold)
        query = _task_query(task, args.query_source)

        with _tool_search_mode("legacy"):
            baseline_top = _run_tool_search(
                query,
                limit=max(1, args.limit),
                exposed_only=bool(args.exposed_only),
            )
        with _tool_search_mode("cards"):
            cards_top = _run_tool_search(
                query,
                limit=max(1, args.limit),
                exposed_only=bool(args.exposed_only),
            )

        results.append(
            {
                "task_id": task_id,
                "title": task.get("title"),
                "category": task.get("category"),
                "query": query,
                "covered": covered,
                "gold_tools": gold,
                "baseline_top": baseline_top,
                "cards_top": cards_top,
                "baseline_top1_hit": _hit(baseline_top, gold, 1) if covered else False,
                "baseline_top3_hit": _hit(baseline_top, gold, 3) if covered else False,
                "cards_top1_hit": _hit(cards_top, gold, 1) if covered else False,
                "cards_top3_hit": _hit(cards_top, gold, 3) if covered else False,
            }
        )

    payload = {
        "harbor_json": str(args.harbor_json),
        "benchmark_csv": str(args.benchmark_csv),
        "query_source": args.query_source,
        "limit": max(1, args.limit),
        "exposed_only": bool(args.exposed_only),
        "results": results,
    }
    text = json.dumps(payload, indent=2)
    if args.output is not None:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
