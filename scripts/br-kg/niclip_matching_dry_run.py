from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from brain_researcher.services.br_kg.graph.graph_factory import create_graph_client
from brain_researcher.services.br_kg.utils.matching_profile import (
    MatchingProfile,
    export_matching_profiles,
    load_matching_profiles,
)
from brain_researcher.services.br_kg.utils.node_label_linker import NodeLabelLinker


logger = logging.getLogger(__name__)


def _filter_by_source(
    nodes: list[tuple[str, dict[str, Any]]], needle: str
) -> list[tuple[str, dict[str, Any]]]:
    needle_lower = needle.lower()
    return [
        (nid, data)
        for nid, data in nodes
        if needle_lower in str(data.get("source", "")).lower()
    ]


def _build_match_report(
    *,
    linker: NodeLabelLinker,
    profile: MatchingProfile,
    source_label: str,
    target_label: str,
    source_nodes: list[tuple[str, dict[str, Any]]],
    target_nodes: list[tuple[str, dict[str, Any]]],
    use_embeddings: bool,
    sample_size: int,
) -> dict[str, Any]:
    def alias_applied(label: str) -> bool:
        if not label:
            return False
        canonical = profile.alias_to_canonical.get(label.strip().lower())
        return bool(canonical and canonical.strip().lower() != label.strip().lower())

    source_labels_raw = [linker._get_label(data) for _, data in source_nodes]
    target_labels_raw = [linker._get_label(data) for _, data in target_nodes]

    source_normalized = [profile.normalize_label(label) for label in source_labels_raw]
    target_normalized = [profile.normalize_label(label) for label in target_labels_raw]

    source_dropped = [
        label for label, normalized in zip(source_labels_raw, source_normalized, strict=False) if not normalized
    ]
    target_dropped = [
        label for label, normalized in zip(target_labels_raw, target_normalized, strict=False) if not normalized
    ]

    source_alias_applied = [label for label in source_labels_raw if alias_applied(label)]
    target_alias_applied = [label for label in target_labels_raw if alias_applied(label)]

    matches = linker.match_nodes(
        source_nodes,
        target_nodes,
        embed_threshold=profile.embed_threshold,
        fuzzy_threshold=profile.fuzzy_threshold,
        use_embeddings=use_embeddings,
        profile=profile.name,
    )

    source_labels = {nid: linker._get_label(data) for nid, data in source_nodes}
    target_labels = {nid: linker._get_label(data) for nid, data in target_nodes}

    method_counts = {"embedding": 0, "fuzzy": 0}
    exact_normalized = 0
    suffix_mismatch = 0
    detailed_matches: list[dict[str, Any]] = []

    for start_id, end_id, score, method in matches:
        method_counts[method] = method_counts.get(method, 0) + 1
        source_label_value = source_labels.get(start_id, "")
        target_label_value = target_labels.get(end_id, "")
        normalized_source = profile.normalize_label(source_label_value)
        normalized_target = profile.normalize_label(target_label_value)
        if normalized_source and normalized_source == normalized_target:
            exact_normalized += 1
        if profile.has_disallowed_suffix(source_label_value) or profile.has_disallowed_suffix(
            target_label_value
        ):
            suffix_mismatch += 1
        detailed_matches.append(
            {
                "source_id": start_id,
                "target_id": end_id,
                "source_label": source_label_value,
                "target_label": target_label_value,
                "normalized_source": normalized_source,
                "normalized_target": normalized_target,
                "confidence": score,
                "method": method,
            }
        )

    detailed_matches.sort(key=lambda item: item["confidence"])
    low_confidence_samples = detailed_matches[:sample_size]
    non_exact_samples = [
        item for item in detailed_matches if item["normalized_source"] != item["normalized_target"]
    ][:sample_size]

    return {
        "source_label": source_label,
        "target_label": target_label,
        "source_count": len(source_nodes),
        "target_count": len(target_nodes),
        "match_count": len(matches),
        "method_counts": method_counts,
        "exact_normalized": exact_normalized,
        "non_exact": len(matches) - exact_normalized,
        "suffix_mismatch": suffix_mismatch,
        "dropped_by_profile": {
            "source_dropped": len(source_dropped),
            "target_dropped": len(target_dropped),
            "source_samples": source_dropped[:sample_size],
            "target_samples": target_dropped[:sample_size],
        },
        "alias_applied": {
            "source_count": len(source_alias_applied),
            "target_count": len(target_alias_applied),
            "source_samples": source_alias_applied[:sample_size],
            "target_samples": target_alias_applied[:sample_size],
        },
        "samples": {
            "low_confidence": low_confidence_samples,
            "non_exact": non_exact_samples,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run NiCLIP cross-source matching with compiled profiles."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON report path (default: artifacts/matching/niclip_link_report_*.json).",
    )
    parser.add_argument(
        "--export-profiles",
        action="store_true",
        help="Export compiled matching profiles to artifacts/matching/alias_compiled.niclip_v1.json.",
    )
    parser.add_argument(
        "--use-embeddings",
        action="store_true",
        help="Enable embedding matching (default: fuzzy-only).",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=20,
        help="Number of samples to include for low-confidence/non-exact matches.",
    )
    args = parser.parse_args()

    report_path = args.output
    if report_path is None:
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        report_path = Path("artifacts/matching") / f"niclip_link_report_{stamp}.json"

    profiles = load_matching_profiles()

    if args.export_profiles:
        export_matching_profiles(
            Path("artifacts/matching/alias_compiled.niclip_v1.json"),
            profiles,
            conflicts_path=Path("artifacts/matching/alias_conflicts.niclip_v1.json"),
        )

    db = create_graph_client()
    linker = NodeLabelLinker(db)

    task_profile = profiles["task"]
    concept_profile = profiles["concept"]

    all_tasks = db.find_nodes(labels="Task")
    all_concepts = db.find_nodes(labels="Concept")
    niclip_tasks = _filter_by_source(all_tasks, "niclip")
    cogatlas_tasks = _filter_by_source(all_tasks, "cognitive_atlas")
    niclip_concepts = _filter_by_source(all_concepts, "niclip")
    cogatlas_concepts = _filter_by_source(all_concepts, "cognitive_atlas")

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "use_embeddings": args.use_embeddings,
        "profiles": {
            "task": task_profile.to_dict(include_aliases=False),
            "concept": concept_profile.to_dict(include_aliases=False),
        },
        "matches": {
            "tasks": _build_match_report(
                linker=linker,
                profile=task_profile,
                source_label="Task",
                target_label="Task",
                source_nodes=niclip_tasks,
                target_nodes=cogatlas_tasks,
                use_embeddings=args.use_embeddings,
                sample_size=args.sample_size,
            ),
            "concepts": _build_match_report(
                linker=linker,
                profile=concept_profile,
                source_label="Concept",
                target_label="Concept",
                source_nodes=niclip_concepts,
                target_nodes=cogatlas_concepts,
                use_embeddings=args.use_embeddings,
                sample_size=args.sample_size,
            ),
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Wrote NiCLIP matching dry-run report to %s", report_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
