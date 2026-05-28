from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


TAXONOMY_ROWS: list[dict[str, Any]] = [
    {
        "taxonomy_id": "SC-1",
        "label": "semantic_collapse",
        "layer_index": 1,
        "definition": (
            "A structured scientific question is reduced too early to a lexical "
            "anchor bundle or flat seed list, so role structure is lost."
        ),
        "runtime_symptoms": [
            "query roles such as population/comparator/region disappear before candidate generation",
            "anchors look locally plausible while missing the scientific core of the query",
        ],
        "code_refs": [
            "src/brain_researcher/services/tools/kg_novelty_tools.py#L138",
            "src/brain_researcher/services/tools/kg_novelty_tools.py#L226",
            "src/brain_researcher/services/neurokg/query_service.py#L8597",
        ],
        "required_regression_assertion": (
            "If a query contains explicit comparator, population, or region language, "
            "at least one returned card must retain those roles, or the runtime must "
            "return zero cards."
        ),
    },
    {
        "taxonomy_id": "TA-1",
        "label": "topology_attractor",
        "layer_index": 2,
        "definition": (
            "After semantic collapse, ranking is pulled toward high-connectivity, "
            "graph-convenient generic nodes rather than question-aligned candidates."
        ),
        "runtime_symptoms": [
            "task, task-family, dataset, or publication-heavy nodes dominate top candidates",
            "principle reranking reshuffles generic leverage features without restoring query fidelity",
        ],
        "code_refs": [
            "src/brain_researcher/services/neurokg/query_service.py#L8085",
            "src/brain_researcher/services/neurokg/query_service.py#L8320",
            "src/brain_researcher/services/agent/principle_controller.py#L413",
        ],
        "required_regression_assertion": (
            "For mechanism-specific queries, Task, TaskFamily, or Dataset nodes "
            "should not dominate the top candidate set unless the query explicitly "
            "asks about transfer or cross-task generalization."
        ),
    },
    {
        "taxonomy_id": "TD-1",
        "label": "template_degeneration",
        "layer_index": 3,
        "definition": (
            "Once a generic task-like candidate survives ranking, hypothesis "
            "generation collapses into a narrow transfer-template family instead of "
            "question-conditioned statements."
        ),
        "runtime_symptoms": [
            "unrelated query domains produce nearly identical transfer statements",
            "shared latent mechanism and cross-condition generalization templates repeat",
        ],
        "code_refs": [
            "src/brain_researcher/services/neurokg/query_service.py#L7185",
            "src/brain_researcher/services/neurokg/query_service.py#L7201",
            "src/brain_researcher/services/neurokg/query_service.py#L7323",
        ],
        "required_regression_assertion": (
            "If the original query does not imply transfer or generalization, "
            "transfer-style statements should be fail-closed before card return."
        ),
    },
    {
        "taxonomy_id": "LV-1",
        "label": "late_verifier",
        "layer_index": 4,
        "definition": (
            "Verification happens after a misaligned hypothesis has already been "
            "drafted, and the verifier mostly audits or vetoes rather than shaping "
            "the hypothesis upstream."
        ),
        "runtime_symptoms": [
            "support counts can grow around a generic candidate without restoring query semantics",
            "external literature can improve verdicts late without fixing the mis-specified statement",
        ],
        "code_refs": [
            "src/brain_researcher/services/neurokg/query_service.py#L4785",
            "src/brain_researcher/services/neurokg/query_service.py#L5605",
            "src/brain_researcher/services/neurokg/query_service.py#L9980",
            "docs/specs/kg_verify_hypothesis_spec.md#L61",
        ],
        "required_regression_assertion": (
            "If literature changes the verdict but the card still omits the core "
            "query roles, the result remains a failure of aligned idea generation."
        ),
    },
]

PROBE_ROWS: list[dict[str, Any]] = [
    {
        "probe_id": "IMR-01",
        "label": "dmn_aging_probe",
        "query": (
            "Does default mode network suppression during working memory tasks "
            "differ between younger and older adults?"
        ),
        "query_role_terms_required": [
            {
                "role": "network_or_phenomenon",
                "any_of": ["default mode network", "dmn", "task-evoked deactivation"],
            },
            {
                "role": "population_comparator",
                "any_of": ["younger", "older", "aging", "older adults", "younger adults"],
            },
        ],
        "query_role_terms_optional": [
            {"role": "task_context", "any_of": ["working memory", "n-back"]},
        ],
        "expected_failure_layers": ["SC-1", "TA-1", "TD-1", "LV-1"],
        "expected_anchor_families": [
            "default_mode_network",
            "working_memory",
            "aging",
        ],
        "forbidden_candidate_families": [
            "generic_psychometric_battery",
            "task_family_without_dmn_or_aging",
        ],
        "forbidden_template_families": [
            "generic_transfer_shared_latent_mechanism",
            "cross_task_transfer_without_population_or_network_roles",
        ],
        "allow_zero_card": True,
        "preferred_runtime_behavior": (
            "Return zero cards with a transparent insufficiency message rather "
            "than return task-transfer cards that omit DMN or age comparison."
        ),
        "harness_fail_conditions": [
            "returned cards omit both DMN-equivalent language and age-comparison framing",
            "generic task-transfer templates are returned without DMN or age roles",
        ],
    },
    {
        "probe_id": "IMR-02",
        "label": "visual_decoding_region_probe",
        "query": (
            "Can fMRI-based neural decoding accurately reconstruct visual image "
            "representations across different visual cortex regions?"
        ),
        "query_role_terms_required": [
            {
                "role": "representation_target",
                "any_of": ["visual image", "visual representation", "image reconstruction"],
            },
            {
                "role": "region_scope",
                "any_of": ["visual cortex", "v1", "v2", "v4", "ffa", "loc", "roi", "regions"],
            },
        ],
        "query_role_terms_optional": [
            {"role": "method_context", "any_of": ["fmri", "decoding", "reconstruct"]},
        ],
        "expected_failure_layers": ["SC-1", "TA-1", "TD-1", "LV-1"],
        "expected_anchor_families": [
            "visual_image_reconstruction",
            "fmri_decoding",
            "visual_cortex_regions",
        ],
        "forbidden_candidate_families": [
            "abstract_task_family_without_visual_or_region_scope",
            "publication_heavy_anchor_without_roi_scope",
        ],
        "forbidden_template_families": [
            "generic_transfer_shared_latent_mechanism",
            "cross_task_transfer_without_visual_region_scope",
        ],
        "allow_zero_card": True,
        "preferred_runtime_behavior": (
            "Return zero cards if only generic task-transfer statements are "
            "available and no card retains visual representation plus region scope."
        ),
        "harness_fail_conditions": [
            "returned cards omit visual image or visual representation language",
            "returned cards omit visual cortex, roi, or cross-region framing",
            "generic task-transfer templates are returned without visual-region scope",
        ],
    },
]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(dict(row), sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def build_taxonomy_rows() -> list[dict[str, Any]]:
    return [
        {
            "schema_version": "idea-mining-failure-taxonomy-row-v1",
            **row,
        }
        for row in TAXONOMY_ROWS
    ]


def build_probe_rows() -> list[dict[str, Any]]:
    return [
        {
            "schema_version": "idea-mining-failure-probe-v1",
            **row,
        }
        for row in PROBE_ROWS
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the idea-mining failure-taxonomy regression pack "
            "artifacts."
        )
    )
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    taxonomy_rows = build_taxonomy_rows()
    probe_rows = build_probe_rows()

    taxonomy_bundle = {
        "schema_version": "idea-mining-failure-taxonomy-v1",
        "generated_at": "2026-03-16T00:00:00Z",
        "taxonomy_id": "idea_mining_failure_taxonomy_v1_20260316",
        "layers": taxonomy_rows,
        "cascade_rule": [
            "SC-1",
            "TA-1",
            "TD-1",
            "LV-1",
        ],
    }
    manifest = {
        "schema_version": "idea-mining-failure-regression-pack-v1",
        "generated_at": "2026-03-16T00:00:00Z",
        "pack_id": "idea_mining_failure_regression_pack_v1_20260316",
        "taxonomy_json": "idea_mining_failure_taxonomy_v1.json",
        "probes_jsonl": "idea_mining_failure_regression_probes_v1.jsonl",
        "intended_surface": "workflow_hypothesis_candidate_cards",
        "checks": [
            "query_role_coverage",
            "anchor_family_alignment",
            "candidate_family_restriction",
            "template_family_rejection",
            "allow_zero_card_fail_closed",
        ],
        "routing_policy": {
            "semantic_collapse_only": "hold_for_refinement",
            "semantic_collapse_plus_topology_attractor": "retire_from_candidate_pack",
            "topology_attractor_plus_template_degeneration": "codify_failure_pattern",
            "late_verifier_only": "hold_for_refinement",
            "late_verifier_after_upstream_collapse": "codify_failure_pattern",
        },
    }
    summary = {
        "schema_version": "idea-mining-failure-regression-pack-summary-v1",
        "taxonomy_layers_total": len(taxonomy_rows),
        "probe_rows_total": len(probe_rows),
        "probe_ids": [row["probe_id"] for row in probe_rows],
        "allow_zero_card_probe_ids": [
            row["probe_id"] for row in probe_rows if row.get("allow_zero_card")
        ],
    }

    _write_json(output_dir / "idea_mining_failure_taxonomy_v1.json", taxonomy_bundle)
    _write_jsonl(
        output_dir / "idea_mining_failure_regression_probes_v1.jsonl", probe_rows
    )
    _write_json(
        output_dir / "idea_mining_failure_regression_manifest_v1.json", manifest
    )
    _write_json(
        output_dir / "idea_mining_failure_regression_summary_v1.json", summary
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
