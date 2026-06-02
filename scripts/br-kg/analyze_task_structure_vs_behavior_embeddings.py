#!/usr/bin/env python3
"""Analyze whether task-graph structure aligns with behavioral embeddings."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from brain_researcher.services.br_kg.analytics.behavior_structure_validation import (
    BehaviorStructureValidationConfig,
    build_behavior_structure_validation,
    write_behavior_structure_validation_artifacts,
)
from brain_researcher.services.br_kg.ml.structural_quality_runner import (
    StructuralQualitySliceExportConfig,
    export_fixed_graph_slice,
)


def _default_output_dir() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"data/br-kg/analysis/task_structure_vs_behavior/{stamp}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=_default_output_dir(),
        help="Directory to write graph slice, summary, pairwise table, and plots.",
    )
    parser.add_argument(
        "--graph-slice-json",
        help="Optional pre-exported graph_slice.json to analyze instead of querying Neo4j.",
    )
    parser.add_argument(
        "--task-source",
        default="Psych-101",
        help="Task source label to analyze, defaults to Psych-101.",
    )
    parser.add_argument(
        "--text-embedding-property",
        default="embedding_text_v1",
        help="Node property for the baseline text embedding space.",
    )
    parser.add_argument(
        "--behavior-embedding-property",
        default="embedding_centaur_behavior_v1",
        help="Node property for the behavioral embedding space.",
    )
    parser.add_argument(
        "--limit-per-edge-type",
        type=int,
        default=500,
        help="Maximum live edges per edge type when exporting a slice.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.graph_slice_json:
        raw_slice = json.loads(
            Path(args.graph_slice_json).expanduser().read_text(encoding="utf-8")
        )
    else:
        raw_slice = export_fixed_graph_slice(
            config=StructuralQualitySliceExportConfig(
                edge_types=["BELONGS_TO_FAMILY", "MAPS_TO"],
                limit_per_edge_type=int(args.limit_per_edge_type),
                include_closure=True,
                source_node_property_filters={
                    "BELONGS_TO_FAMILY": {"source": [args.task_source]},
                    "MAPS_TO": {"source": [args.task_source]},
                },
            )
        )
        (output_dir / "graph_slice.json").write_text(
            json.dumps(raw_slice, indent=2),
            encoding="utf-8",
        )

    result = build_behavior_structure_validation(
        raw_slice,
        config=BehaviorStructureValidationConfig(
            task_source=args.task_source,
            text_embedding_property=args.text_embedding_property,
            behavior_embedding_property=args.behavior_embedding_property,
        ),
    )
    artifact_paths = write_behavior_structure_validation_artifacts(
        result,
        output_dir=output_dir,
    )

    summary = result.get("summary") or {}
    correlations = summary.get("correlations") or {}
    print(f"Wrote artifacts to {output_dir}")
    print(f"Task nodes analyzed: {summary.get('task_node_count', 0)}")
    print(f"Connected pairs: {summary.get('connected_pair_count', 0)}")
    print(
        "Spearman(distance, behavior cosine): "
        f"{correlations.get('graph_distance_vs_behavior_cosine_spearman')}"
    )
    print(
        "Spearman(distance, text cosine): "
        f"{correlations.get('graph_distance_vs_text_cosine_spearman')}"
    )
    print(f"Artifacts: {artifact_paths}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
