#!/usr/bin/env python3
"""Export a fixed BR-KG graph slice and run the structural quality benchmark."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from brain_researcher.services.br_kg.ml.structural_quality_benchmark import (
    StructuralQualityBenchmarkConfig,
)
from brain_researcher.services.br_kg.ml.structural_quality_runner import (
    DEFAULT_EDGE_TYPES,
    STRUCTURAL_QUALITY_PROFILES,
    StructuralQualitySliceExportConfig,
    export_and_run_structural_quality_benchmark,
    get_structural_quality_profile,
    run_structural_quality_benchmark_from_graph_slice,
)


def _default_output_dir() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"data/br-kg/benchmarks/structural_quality/{stamp}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=_default_output_dir(),
        help="Directory to write graph_slice.json and benchmark artifacts.",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(STRUCTURAL_QUALITY_PROFILES),
        help="Named structural-quality profile to apply before manual overrides.",
    )
    parser.add_argument(
        "--graph-slice-json",
        help="Optional pre-exported graph slice to benchmark instead of querying Neo4j.",
    )
    parser.add_argument(
        "--edge-type",
        action="append",
        dest="edge_types",
        help="Edge type to include in the fixed live slice. Repeatable.",
    )
    parser.add_argument(
        "--limit-per-edge-type",
        type=int,
        default=None,
        help="Maximum live edges per edge type when exporting a slice.",
    )
    parser.add_argument(
        "--feature-dim",
        type=int,
        default=64,
        help="Dimension of hashed fallback features for the benchmark slice.",
    )
    parser.add_argument(
        "--feature-source",
        choices=["auto", "hashed", "cache_text_v1", "neo4j_text_v1", "encoder_text_v1"],
        default=None,
        help=(
            "Feature source for node representations: prefer cached kg_text_v1 vectors, use Neo4j "
            "embedding_text_v1 when present, force hashed features, or derive text_v1-compatible "
            "embeddings on the fly."
        ),
    )
    parser.add_argument(
        "--include-closure",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Whether to add closure edges among selected slice nodes.",
    )
    parser.add_argument(
        "--include-node2vec",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run Node2Vec as an additional probe model when dependencies are available.",
    )
    parser.add_argument(
        "--include-graphsage",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Run GraphSAGE(text features) as an additional probe model.",
    )
    parser.add_argument(
        "--min-positive-edges-per-type",
        type=int,
        default=10,
        help="Minimum positive support before an edge type is treated as adequately powered.",
    )
    parser.add_argument(
        "--audit-group-key",
        action="append",
        dest="audit_group_keys",
        help="Node property key to audit on source nodes during evaluation. Repeatable.",
    )
    parser.add_argument(
        "--min-group-samples",
        type=int,
        default=5,
        help="Minimum evaluation samples required before a subgroup is treated as adequately powered.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    profile = get_structural_quality_profile(args.profile) if args.profile else {}
    edge_types = args.edge_types or list(profile.get("edge_types") or DEFAULT_EDGE_TYPES)
    feature_source = args.feature_source or str(profile.get("feature_source") or "auto")
    limit_per_edge_type = args.limit_per_edge_type or int(profile.get("limit_per_edge_type") or 250)
    benchmark_config = StructuralQualityBenchmarkConfig(
        evaluation_edge_types=edge_types,
        key_edge_types=edge_types,
        include_node2vec_probe=args.include_node2vec,
        include_graphsage_probe=args.include_graphsage,
        min_positive_edges_per_type=args.min_positive_edges_per_type,
        audit_group_keys=list(args.audit_group_keys or []),
        min_group_samples=args.min_group_samples,
    )

    output_dir = Path(args.output_dir).expanduser().resolve()
    if args.graph_slice_json:
        graph_slice = json.loads(Path(args.graph_slice_json).read_text(encoding="utf-8"))
        result = run_structural_quality_benchmark_from_graph_slice(
            graph_slice,
            output_dir=str(output_dir),
            benchmark_config=benchmark_config,
            feature_dim=args.feature_dim,
            feature_source=feature_source,
        )
    else:
        slice_config = StructuralQualitySliceExportConfig(
            edge_types=edge_types,
            limit_per_edge_type=limit_per_edge_type,
            include_closure=args.include_closure,
            feature_dim=args.feature_dim,
            feature_source=feature_source,
            profile_name=args.profile,
        )
        result = export_and_run_structural_quality_benchmark(
            output_dir=str(output_dir),
            slice_config=slice_config,
            benchmark_config=benchmark_config,
        )

    diagnostics = result["benchmark_result"]["graph_diagnostic_report"]
    fairness_report = result["benchmark_result"]["fairness_audit_report"]
    print(f"Wrote structural-quality benchmark artifacts to {output_dir}")
    print(f"Primary probe model: {diagnostics.get('primary_probe_model')}")
    print(f"Structure consistency score: {diagnostics.get('structure_consistency_score')}")
    print(f"Fairness audit status: {fairness_report.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
