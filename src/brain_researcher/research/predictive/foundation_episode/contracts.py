"""Contracts for the prospective HCP foundation MVE-100 v2 episode.

This package is deliberately preflight-first.  It can freeze what a future
discovery run is allowed to do, but it cannot fit an outcome model, inspect
outcome values, or authorize discovery/confirmation.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

EPISODE_ID = "foundation_mve100_ica_cognition_codex_cli_v2"
EPISODE_SCHEMA = "br.foundation_episode.contract.v1"
AUTHORIZATION_SCHEMA = "predictive.foundation_exploration_authorization.v1"
DISCOVERY_SCOPE = "discovery_only"
CATALOG_SCHEMA = "br.foundation_episode.sanitized_catalog.v1"
METRIC_CATALOG_SCHEMA = "br.foundation_episode.metric_catalog.v1"
PHASE_AWAITING_DISCOVERY_AUTHORIZATION = "AWAITING_DISCOVERY_AUTHORIZATION"
TARGET_NAME = "ICA_Cognition"
ICA_TARGET_COLUMNS = (
    "ICA_Cognition",
    "ICA_TobaccoUse",
    "ICA_PersonalityEmotion",
    "ICA_IllicitDrugUse",
    "ICA_MentalHealth",
)
PRIMARY_STATISTIC = "signed_pearson_r"
PARTITION_SEED = 20260805
CANDIDATE_RECEIPT_COUNT = 96
RECEIPT_COUNT = 100
HOST_SLOT_CHAMPION_REPARTITION = 97
HOST_SLOT_RUNNER_UP_REPARTITION = 98
HOST_SLOT_FALSIFIER = 99
HOST_SLOT_POSITIVE_CONTROL = 100
V1_EPISODE_ID = "foundation_mve24_ica_cognition_codex_cli_v1"
V1_EXCLUDED_CANDIDATE_PAIRS = frozenset(
    {
        ("brainnetcnn", 3),
        ("cpm", 29),
        ("elasticnet", 3),
        ("gcn", 3),
        ("graph_transformer", 3),
        ("kernelridgelinear", 3),
        ("lasso", 3),
        ("pls", 3),
        ("ridge", 3),
        ("ridge", 5),
        ("ridge", 16),
        ("ridge", 17),
        ("ridge", 29),
        ("spd_aware", 3),
        ("svr", 0),
        ("svr", 3),
        ("svr", 5),
        ("svr", 17),
        ("tabnet", 29),
        ("xgboost", 3),
    }
)
COVERAGE_STRATA = (
    "classical",
    "cpm",
    "tree",
    "shallow",
    "cnn",
    "gnn",
    "transformer",
    "structure-aware",
)
SEARCH_ALPHA_STAGES = (
    ("coverage", tuple(range(1, 9)), 8 / CANDIDATE_RECEIPT_COUNT),
    ("adaptive_1", tuple(range(9, 31)), 22 / CANDIDATE_RECEIPT_COUNT),
    ("adaptive_2", tuple(range(31, 53)), 22 / CANDIDATE_RECEIPT_COUNT),
    ("adaptive_3", tuple(range(53, 75)), 22 / CANDIDATE_RECEIPT_COUNT),
    ("adaptive_4", tuple(range(75, 97)), 22 / CANDIDATE_RECEIPT_COUNT),
)
PUBLIC_CLAIM_BOUNDARY_FIELDS = (
    "study_object",
    "measurement_instrument",
    "primary_episode_result",
    "explicit_nonclaims",
)
CONTROLLER_TWO_SLOT_BATCHES = tuple(
    (
        (
            f"coverage_batch_{batch_index + 1}"
            if batch_index < 4
            else f"adaptive_batch_{batch_index - 3}"
        ),
        (batch_index * 2 + 1, batch_index * 2 + 2),
        batch_index * 2,
    )
    for batch_index in range(CANDIDATE_RECEIPT_COUNT // 2)
)
CONTROLLER_BATCH_ORDER = tuple(batch for batch, _, _ in CONTROLLER_TWO_SLOT_BATCHES)
CONTROLLER_PRIMARY_BATCH_SLOTS = {
    batch: slots for batch, slots, _ in CONTROLLER_TWO_SLOT_BATCHES
}
CONTROLLER_CALL_BUDGETS = {
    "controller_primary_calls_max": len(CONTROLLER_TWO_SLOT_BATCHES),
    "controller_schema_repair_calls_max": len(CONTROLLER_TWO_SLOT_BATCHES),
    "controller_calls_hard_max": len(CONTROLLER_TWO_SLOT_BATCHES) * 2,
}


def controller_cadence_batches() -> list[dict[str, object]]:
    """Return the one frozen, two-decision controller cadence."""

    return [
        {
            "batch": batch,
            "slots": list(slots),
            "ledger_cutoff_slot": cutoff,
            "score_release_after_slot": slots[-1],
            "requires_prior_aggregate": cutoff > 0,
            "no_within_batch_peeking": True,
            "decision_count": len(slots),
        }
        for batch, slots, cutoff in CONTROLLER_TWO_SLOT_BATCHES
    ]


class FoundationEpisodeError(ValueError):
    """A fail-closed foundation episode contract violation."""


def _normalize_json(value: object, *, label: str = "$") -> object:
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise FoundationEpisodeError(f"{label} contains a non-string key")
            normalized[key] = _normalize_json(item, label=f"{label}.{key}")
        return normalized
    if isinstance(value, list | tuple):
        return [
            _normalize_json(item, label=f"{label}[{index}]")
            for index, item in enumerate(value)
        ]
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FoundationEpisodeError(f"{label} contains a non-finite number")
        return value
    raise FoundationEpisodeError(
        f"{label} contains unsupported JSON type {type(value).__name__}"
    )


def canonical_json_bytes(payload: object) -> bytes:
    """Return normalized UTF-8 JSON for the controller request payload."""

    return json.dumps(
        _normalize_json(payload),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _require_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise FoundationEpisodeError(f"{label} must be a non-empty stripped string")
    return value


def episode_receipt_slots() -> list[dict[str, object]]:
    """Return the fixed, future MVE-100-D receipt schedule.

    These are *planned* receipts.  Preflight must never relabel them as executed.
    """

    slots: list[dict[str, object]] = []
    for cadence in controller_cadence_batches():
        batch = str(cadence["batch"])
        cutoff = int(cadence["ledger_cutoff_slot"])
        for slot in cadence["slots"]:
            assert isinstance(slot, int)
            is_coverage = slot <= len(COVERAGE_STRATA)
            slots.append(
                {
                    "slot": slot,
                    "kind": "coverage_stratum" if is_coverage else "adaptive_candidate",
                    "batch": batch,
                    "proposal_batch": batch,
                    "evidence_release": (
                        "none" if cutoff == 0 else f"aggregate_through_slot_{cutoff}"
                    ),
                    "ledger_cutoff_slot": cutoff,
                    "requires_prior_aggregate": cutoff > 0,
                    "required_stratum": (
                        COVERAGE_STRATA[slot - 1] if is_coverage else None
                    ),
                }
            )
    slots.extend(
        [
            {
                "slot": HOST_SLOT_CHAMPION_REPARTITION,
                "kind": "champion_repartition_split_robustness_check",
                "batch": "repartition_split_robustness",
                "proposal_batch": "repartition_split_robustness_batch",
                "evidence_release": "aggregate_through_slot_96",
                "ledger_cutoff_slot": CANDIDATE_RECEIPT_COUNT,
                "requires_prior_aggregate": True,
                "required_stratum": None,
            },
            {
                "slot": HOST_SLOT_RUNNER_UP_REPARTITION,
                "kind": "different_stratum_runner_up_repartition_split_robustness_check",
                "batch": "repartition_split_robustness",
                "proposal_batch": "repartition_split_robustness_batch",
                "evidence_release": "aggregate_through_slot_96",
                "ledger_cutoff_slot": CANDIDATE_RECEIPT_COUNT,
                "requires_prior_aggregate": True,
                "required_stratum": None,
            },
            {
                "slot": HOST_SLOT_FALSIFIER,
                "kind": "family_block_shuffle",
                "batch": "falsifier",
                "proposal_batch": "falsifier_batch",
                "evidence_release": "aggregate_through_slot_96",
                "ledger_cutoff_slot": CANDIDATE_RECEIPT_COUNT,
                "requires_prior_aggregate": True,
                "required_stratum": None,
            },
            {
                "slot": HOST_SLOT_POSITIVE_CONTROL,
                "kind": "synthetic_positive_control",
                "batch": "positive_control",
                "proposal_batch": "positive_control_batch",
                "evidence_release": "none",
                "ledger_cutoff_slot": 0,
                "requires_prior_aggregate": False,
                "required_stratum": None,
            },
        ]
    )
    assert len(slots) == RECEIPT_COUNT
    return slots


def build_episode_contract(*, seed: int) -> dict[str, object]:
    """Freeze the discovery-only protocol, independent of paths and outcomes."""

    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise FoundationEpisodeError("seed must be a non-negative integer")
    # Import at call time because codex_cli imports this contracts module.
    # This shared accessor lets a CLI override appear in both the invocation and
    # its persisted provenance without mutating process environment variables.
    from brain_researcher.research.predictive.foundation_episode import codex_cli

    return {
        "schema_version": EPISODE_SCHEMA,
        "episode_id": EPISODE_ID,
        "episode_label": "MVE-100-D",
        "seed": seed,
        "target": TARGET_NAME,
        "target_provenance": {
            "join_key": "Subject",
            "family_source": "exchangeability_manifest",
            "target_table_columns": ["Subject", *ICA_TARGET_COLUMNS],
            "literature_reference": {
                "citation": "Liu, Z.-Q., Luppi, A.I., Hansen, J.Y., Tian, Y.E., Zalesky, A., Yeo, B.T.T., Fulcher, B.D. and Misic, B. Benchmarking methods for mapping functional connectivity in the brain. Nature Methods 22, 1593-1602 (2025).",
                "doi": "10.1038/s41592-025-02704-4",
            },
            "cohort": {
                "dataset": "HCP Young Adult S1200",
                "subject_count": 326,
            },
            "feature_and_target_scope": {
                "pyspi_statistics": 239,
                "ica_components": 5,
                "episode_metric_subset": 76,
            },
            "comparability": {
                "status": "reconstructed_not_paper_exact",
                "reference_mean_r": 0.215,
                "reference_best_r": 0.42,
                "required_rules": {
                    "must_label_outputs_as_reconstructed": True,
                    "must_not_claim_direct_paper_reproduction": True,
                    "must_not_compare_against_raw_target_pmats_or_memory_scores": True,
                    "must_report_pearson_r_as_primary_literature_metric": True,
                    "must_treat_r2_as_secondary_internal_metric": True,
                    "must_use_component_targets": True,
                },
                "forbidden_comparisons": [
                    "raw_target",
                    "ListSort",
                    "Liu_direct_reproduction",
                ],
            },
        },
        "discovery_partition": {
            "family_group_fraction": 0.75,
            "group_column": "Family_ID",
            "holdout_state": "sealed",
        },
        "prior_round_binding": {
            "v1_episode_id": V1_EPISODE_ID,
            "partition_reuse": "required_same_seed_reconstructed_group_partition",
            "partition_seed": PARTITION_SEED,
            "replication_seed": PARTITION_SEED + 1,
            "controller_visibility": "prior_candidate_pairs_only_no_v1_outcomes",
            "v1_artifact_write": "forbidden",
            "sealed_holdout_access": "forbidden",
        },
        "hypothesis_space": {
            "runnable_classifier_count": 21,
            "metric_term_count": 76,
            "candidate_axis": "one_runnable_classifier_key_x_one_metric_term_index",
            "unique_pair_within_round": True,
            "excluded_v1_candidate_pairs": [
                {"classifier_key": classifier_key, "term_index": term_index}
                for classifier_key, term_index in sorted(V1_EXCLUDED_CANDIDATE_PAIRS)
            ],
            "forbidden_expansions": [
                "new_classifier_axis",
                "new_metric_axis",
                "hyperparameter_search_axis",
                "sealed_holdout_access",
            ],
        },
        "evaluator": {
            "outer_cv": {"kind": "GroupKFold", "n_splits": 5},
            "inner_cv": {"kind": "GroupKFold", "n_splits": 3},
            "transform_scope": "fold_local_only",
            "feature_selection_scope": "fold_local_only",
            "primary_statistic": PRIMARY_STATISTIC,
            "secondary_diagnostics": {
                "calibration_slope": {
                    "kind": "held_out_outer_fold_and_pooled_oof_ols",
                    "equation": "y_true = intercept + beta * y_pred",
                    "per_fold_metric": "calibration_slope",
                    "aggregate_metrics": [
                        "mean_fold_calibration_slope",
                        "pooled_oof_calibration_slope",
                    ],
                    "negative_beta": "preserved",
                    "degenerate_or_nonfinite": "null",
                    "role": "secondary_diagnostic_only",
                    "controller_visibility": "excluded_from_aggregate_ledger",
                    "not_used_for": [
                        "candidate_selection",
                        "episode_gates",
                        "batch_lift",
                        "search_alpha_allocation",
                    ],
                }
            },
        },
        "controller": {
            "provider": "codex.cli",
            "cli_binary": codex_cli.CODEX_CLI_BINARY,
            "model": codex_cli.CODEX_CLI_MODEL,
            "reasoning_effort": codex_cli.CODEX_CLI_REASONING_EFFORT,
            "ephemeral": True,
            "ignore_user_config": True,
            "ignore_rules": True,
            "skill_search_enabled": False,
            "skills_include_instructions": False,
            "skip_git_repo_check": True,
            "sandbox": "read-only",
            "tool_event_policy": "forbidden_fail_closed",
            "strict_json_schema": True,
            "event_audit": {
                "format": "jsonl",
                "complete": True,
            },
            "visible_inputs": [
                "sanitized_catalog",
                "metric_catalog",
                "aggregate_ledger",
                "current_slot_contracts",
                "budget",
            ],
        },
        "resource_tool_gate": {
            "max_walltime_hours": 12,
            "walltime_enforcement": {
                "target_hours": 12,
                "runner_deadline_mode": "between_dispatch_deadline",
                "launch_command_timeout_mode": "external_process_timeout_hard_kill",
                "single_in_process_evaluator_interruptibility": "not_safely_interruptible",
                "execution_receipt_required_fields": [
                    "walltime_target_hours",
                    "runner_deadline_mode",
                    "external_process_timeout_mode",
                    "external_hard_kill_observed",
                    "termination_reason",
                ],
            },
            **CONTROLLER_CALL_BUDGETS,
            "receipt_slots": RECEIPT_COUNT,
            "compute": "local_single_gpu",
            "gcp": False,
            "evaluation_concurrency": 1,
            "gpu_count": 1,
            "cpu_estimator_n_jobs": 1,
            "candidate_execution_order": "slot_serial",
            "environment_replay_semantics": "recorded_and_launch_reverified_not_container_frozen",
            "exact_environment_replay_claim": False,
            "controller_transport": {
                "provider": "codex.cli",
                "cli_binary": codex_cli.CODEX_CLI_BINARY,
                "model": codex_cli.CODEX_CLI_MODEL,
                "reasoning_effort": codex_cli.CODEX_CLI_REASONING_EFFORT,
                "ephemeral": True,
                "ignore_user_config": True,
                "ignore_rules": True,
                "skill_search_enabled": False,
                "skills_include_instructions": False,
                "skip_git_repo_check": True,
                "sandbox": "read-only",
                "tool_event_policy": "forbidden_fail_closed",
                "strict_json_schema": True,
                "event_audit": {
                    "format": "jsonl",
                    "complete": True,
                },
            },
            "controller_transport_retries": 0,
            "controller_schema_repair": "validation_failure_only_one_per_batch",
            "code_mutation": False,
            "controller_model": "gpt-5.6-sol",
            "provider_weights_may_roll": True,
        },
        "selection_and_gates": {
            "eligible_discovery_receipt": {
                "slots": list(range(1, CANDIDATE_RECEIPT_COUNT + 1)),
                "control_mode": "observed",
                "required_status": "succeeded",
                "required_outer_fold_count": 5,
                "required_finite_mean_signed_r": True,
            },
            "champion": {
                "selection": "max_mean_signed_r",
                "tie_breaker": "lowest_slot",
            },
            "different_classifier_stratum_runner_up": {
                "selection": "max_mean_signed_r",
                "must_differ_from_champion": "classifier_stratum",
            },
            "slots_97_98_repartition_split_robustness": {
                "evaluation_population": "same_discovery_subjects",
                "split_plan": "prebound_alternative_seeded_groupkfold_5x3",
                "is_independent_replication": False,
                "is_fresh_subject_replication": False,
            },
            "slot_99_falsifier": {
                "source": "champion",
                "control_mode": "family_block_shuffle",
                "runs": 1,
                "interpretation": "diagnostic_not_p_value",
            },
            "slot_100_positive_control": {
                "host_fixed": True,
                "classifier_key": "ridge",
                "term_index": 0,
                "synthetic_target": "raw_edge_0",
                "statistic": "mean_fold_signed_pearson_r",
                "required_outer_fold_count": 5,
                "all_outer_folds_must_succeed": True,
                "minimum_mean_signed_r": 0.90,
            },
            "stop_rule": {
                "coverage_slots_must_propose": list(range(1, 9)),
                "controller_stop_eligible_slots": list(
                    range(9, CANDIDATE_RECEIPT_COUNT + 1)
                ),
                "decision_boundary": "frozen_two_slot_batch",
                "same_batch_after_stop": "skipped_by_controller_stop",
                "remaining_candidate_slots": "skipped_by_controller_stop",
                "host_slots_after_stop": "still_required",
                "efficacy_stop": "not_available",
            },
            "protocol_integrity": {
                "required_for_episode_valid": True,
                "integrity_failure_events": [
                    "controller_transport_exhausted",
                    "controller_schema_repair_exhausted",
                    "interrupted_evaluation",
                    "budget_exhausted",
                ],
                "allowed_terminal_results": [
                    "controller_stop",
                    "model_evaluation_failure",
                ],
                "controller_stop": {
                    "permitted_when": "valid_frozen_controller_stop_decision_on_adaptive_slot",
                    "subsequent_candidate_slots": "skipped_by_controller_stop",
                    "breaks_protocol_integrity": False,
                },
                "model_evaluation_failure": {
                    "is_terminal_receipt_result": True,
                    "breaks_protocol_integrity": False,
                },
            },
            "episode_valid": {
                "requires": [
                    "protocol_complete",
                    "protocol_integrity",
                    "positive_control_passed",
                ],
                "does_not_imply": [
                    "discovery_champion_scientific_acceptance",
                    "confirmation_authorization",
                    "sealed_holdout_opening",
                ],
            },
        },
        "search_alpha_allocation": {
            "schema_version": "br.foundation_episode.search_budget_alpha_allocation.v1",
            "semantics": "fraction_of_frozen_candidate_evaluation_budget_not_significance_level",
            "total_alpha": 1.0,
            "allocation_unit": "research_stage",
            "denominator": "prospectively_allocated_slots",
            "score_mean_denominator": "n_scored",
            "failed_or_stopped_slot_policy": "report_missing_never_impute_zero",
            "reallocation_policy": "forbidden_without_versioned_contract",
            "controller_cadence_independent": True,
            "compatibility": "forward_only_new_episode_contract",
            "allocations": [
                {
                    "window_id": window_id,
                    "slots": list(slots),
                    "slot_budget": len(slots),
                    "alpha_mass": alpha_mass,
                }
                for window_id, slots, alpha_mass in SEARCH_ALPHA_STAGES
            ],
        },
        "claim_boundary": {
            "study_object": "controller decision trajectory under the frozen MVE-100 interface",
            "measurement_instrument": "signed Pearson r is a measurement instrument, not the episode result",
            "primary_episode_result": "100 receipts plus 48 frozen two-slot controller decisions",
            "explicit_nonclaims": [
                "previous_model_comparison",
                "foundation_model_superiority",
                "80_plus_models_executed",
                "neuroscience_confirmation",
                "contamination_elimination",
                "raw_or_ListSort_or_Liu_direct_reproduction_comparison",
            ],
        },
        "public_episode_result": {
            "claim_boundary_source": "episode_contract.claim_boundary",
            "required_claim_boundary_fields": list(PUBLIC_CLAIM_BOUNDARY_FIELDS),
            "required_status_fields": [
                "protocol_complete",
                "protocol_integrity",
                "positive_control_passed",
                "episode_valid",
            ],
            "preflight_state": "not_emitted",
        },
        "proposal_batches": controller_cadence_batches(),
        "evidence_release": {
            "kind": "aggregate_only_frozen_batch_ledger_v1",
            "batches": [
                {
                    "batch": row["batch"],
                    "ledger_cutoff_slot": row["ledger_cutoff_slot"],
                    "score_release_after_slot": row["score_release_after_slot"],
                    "no_within_batch_peeking": row["no_within_batch_peeking"],
                }
                for row in controller_cadence_batches()
            ],
            "within_batch_score_visibility": "forbidden",
        },
        "receipt_schedule": episode_receipt_slots(),
        "confirmation": {
            "status": "not_authorized",
            "requires_separate_human_authorization": True,
            "discovery_authorization_does_not_authorize_confirmation": True,
        },
        "prohibited_legacy_surfaces": [
            "run_one_experiment_replay",
            "raw_fit_nested_cv",
            "full_sample_qcod_loader",
        ],
    }


def _catalog_item(item: object, *, index: int) -> dict[str, object]:
    if not isinstance(item, Mapping):
        raise FoundationEpisodeError(f"catalog concept {index} must be an object")
    raw_id = item.get("concept_id", item.get("id", item.get("name")))
    concept_id = _require_text(raw_id, label=f"catalog concept {index}.concept_id")
    raw_family = item.get("family", item.get("concept_family", "unspecified"))
    family = _require_text(raw_family, label=f"catalog concept {index}.family")
    raw_keys = item.get("operational_keys", item.get("operations", []))
    if isinstance(raw_keys, str) or not isinstance(raw_keys, Sequence):
        raise FoundationEpisodeError(
            f"catalog concept {index}.operational_keys must be a sequence"
        )
    operational_keys = sorted(
        {
            _require_text(key, label=f"catalog concept {index}.operational_key")
            for key in raw_keys
        }
    )
    raw_maturity = item.get("implementation_maturity")
    if raw_maturity is None:
        maturity = "declared" if operational_keys else "unavailable"
    else:
        maturity = _require_text(
            raw_maturity, label=f"catalog concept {index}.implementation_maturity"
        )
        if maturity not in {
            "benchmark_native",
            "minimal_viable",
            "prototype",
            "declared",
            "unavailable",
        }:
            raise FoundationEpisodeError(
                "implementation_maturity is not a recognized public maturity label"
            )
    # Whitelisting is deliberate: current_use, search_priority, notes, historical
    # score fields, paths, and arbitrary source metadata cannot cross this boundary.
    return {
        "concept_id": concept_id,
        "family": family,
        "operational_keys": operational_keys,
        "runnable": bool(operational_keys),
        "implementation_maturity": maturity,
    }


def _normalize_stratum(value: object) -> str:
    if not isinstance(value, str):
        return "unassigned"
    normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "structureaware": "structure-aware",
        "structure-aware": "structure-aware",
        "classical": "classical",
        "cpm": "cpm",
        "tree": "tree",
        "shallow": "shallow",
        "cnn": "cnn",
        "gnn": "gnn",
        "transformer": "transformer",
    }
    return aliases.get(normalized, "unassigned")


def _name_token(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _coverage_stratum_for_operational(
    *, classifier_key: str, family_id: object, paradigms: object
) -> str:
    key = classifier_key.lower()
    if key == "cpm":
        return "cpm"
    if key in {
        "xgboost",
        "lightgbm",
        "randomforest",
        "random_forest",
        "gradientboosting",
    }:
        return "tree"
    if key in {"mlp", "autoencoder", "vae"}:
        return "shallow"
    if key == "brainnetcnn":
        return "cnn"
    if key in {"gcn", "gat", "graphsage", "gin", "braingnn", "braingb"}:
        return "gnn"
    if key in {
        "fttransformer",
        "graph_transformer",
        "set_or_perceiver",
        "tabtransformer",
        "mamba",
        "mamba2",
        "bidirectional_mamba",
    }:
        return "transformer"
    if key in {"tabnet", "tabpfn"}:
        return "shallow"
    if key in {"spd_aware", "tensor_decomposition", "persistent_homology"}:
        return "structure-aware"
    family = _normalize_stratum(family_id)
    if family != "unassigned":
        return family
    if isinstance(paradigms, Sequence) and not isinstance(paradigms, str):
        for paradigm in paradigms:
            text = str(paradigm).lower()
            if "classical" in text:
                return "classical"
            if "shallow" in text:
                return "shallow"
            if "cnn" in text:
                return "cnn"
            if "graph" in text:
                return "gnn"
            if "transformer" in text:
                return "transformer"
            if "topological" in text or "geometric" in text:
                return "structure-aware"
    return "classical"


def _operational_entries(raw_registry: object) -> dict[str, dict[str, object]]:
    """Normalize raw operational rows without exporting priority/history fields."""

    if isinstance(raw_registry, Mapping):
        nested = next(
            (
                raw_registry.get(name)
                for name in ("entries", "models", "classifiers")
                if isinstance(raw_registry.get(name), Sequence)
                and not isinstance(raw_registry.get(name), str)
            ),
            None,
        )
        source_items = (
            [(None, item) for item in nested]
            if nested is not None
            else list(raw_registry.items())
        )
    elif isinstance(raw_registry, Sequence) and not isinstance(raw_registry, str):
        source_items = [(None, item) for item in raw_registry]
    else:
        return {}
    normalized: dict[str, dict[str, object]] = {}
    for _row_index, (map_key, item) in enumerate(source_items):
        if isinstance(item, Mapping):
            raw_key = item.get(
                "classifier_key", item.get("model_name", item.get("name", map_key))
            )
            # The registry deliberately keeps backlog rows that have no runtime
            # key yet.  They still belong in the conceptual catalog, under a
            # deterministic neutral display-name token that cannot be selected
            # as runnable.
            key = (
                raw_key
                if isinstance(raw_key, str) and raw_key.strip()
                else _name_token(item.get("display_name", ""))
            )
            if not isinstance(key, str) or not key.strip() or key != key.strip():
                continue
            status = item.get("implementation_status")
            implemented = status == "implemented" or item.get("implemented") is True
            maturity = item.get("implementation_maturity")
            if maturity not in {"benchmark_native", "minimal_viable", "prototype"}:
                maturity = "unavailable"
            single_term_compatible = key != "multi_metric_dual_branch"
            runnable = bool(implemented and single_term_compatible)
            stratum = _coverage_stratum_for_operational(
                classifier_key=key,
                family_id=item.get("family_id"),
                paradigms=item.get("paradigms"),
            )
            aliases = [
                item.get("display_name"),
                key,
                *(
                    item.get("backbone_aliases")
                    if isinstance(item.get("backbone_aliases"), Sequence)
                    and not isinstance(item.get("backbone_aliases"), str)
                    else []
                ),
            ]
            alias_tokens = sorted({_name_token(alias) for alias in aliases if alias})
            reason = (
                "single_term_incompatible"
                if implemented and not single_term_compatible
                else "implemented" if implemented else "not_implemented"
            )
        else:
            key = map_key if isinstance(map_key, str) else item
            stratum = "unassigned"
            runnable = False
            maturity = "unavailable"
            alias_tokens = [_name_token(key)]
            reason = "not_implemented"
        if not isinstance(key, str) or not key.strip() or key != key.strip():
            continue
        if key in normalized:
            raise FoundationEpisodeError(
                f"operational registry has duplicate public classifier key {key!r}"
            )
        normalized[key] = {
            "stratum": stratum,
            "runnable": runnable,
            "implementation_maturity": maturity,
            "alias_tokens": alias_tokens,
            "runnable_reason": reason,
        }
    return normalized


def _sanitize_registry_catalog(raw_catalog: Mapping[str, object]) -> dict[str, object]:
    catalog_source = raw_catalog.get("catalog_source")
    if not isinstance(catalog_source, Mapping):
        raise FoundationEpisodeError("model registry catalog_source must be an object")
    paradigms = catalog_source.get("catalog_paradigms")
    if not isinstance(paradigms, Mapping):
        raise FoundationEpisodeError(
            "model registry catalog_paradigms must be an object"
        )
    operational = _operational_entries(raw_catalog.get("operational_registry"))
    concepts: list[dict[str, object]] = []
    for paradigm, value in paradigms.items():
        if not isinstance(paradigm, str) or not isinstance(value, Mapping):
            raise FoundationEpisodeError("catalog paradigms must map names to objects")
        model_names = value.get("model_names")
        if isinstance(model_names, str) or not isinstance(model_names, Sequence):
            raise FoundationEpisodeError(
                "catalog paradigm model_names must be a sequence"
            )
        for model_name in model_names:
            name = _require_text(model_name, label="catalog model name")
            matching = [
                (key, entry)
                for key, entry in operational.items()
                if _name_token(name) in entry["alias_tokens"]
            ]
            runnable_matches = [
                (key, entry) for key, entry in matching if entry["runnable"] is True
            ]
            runnable_keys = [key for key, _ in runnable_matches]
            maturity = (
                sorted(
                    {
                        str(entry["implementation_maturity"])
                        for _, entry in runnable_matches
                    }
                )[0]
                if runnable_matches
                else "unavailable"
            )
            concepts.append(
                {
                    "concept_id": name,
                    "family": paradigm,
                    "operational_keys": sorted(runnable_keys),
                    "runnable": bool(runnable_keys),
                    "implementation_maturity": maturity,
                }
            )
    if len(concepts) < 80:
        raise FoundationEpisodeError(
            f"sanitized catalog must retain at least 80 concepts, found {len(concepts)}"
        )
    concepts.sort(key=lambda entry: str(entry["concept_id"]))
    if len({entry["concept_id"] for entry in concepts}) != len(concepts):
        raise FoundationEpisodeError(
            "sanitized catalog concept_id values must be unique"
        )
    classifier_catalog = [
        {
            "classifier_key": key,
            "runnable": bool(entry["runnable"]),
            "stratum": str(entry["stratum"]),
            "implementation_maturity": str(entry["implementation_maturity"]),
            "runnable_reason": str(entry["runnable_reason"]),
        }
        for key, entry in sorted(operational.items())
    ]
    reported_count = catalog_source.get("reported_total_models")
    if (
        isinstance(reported_count, bool)
        or not isinstance(reported_count, int)
        or reported_count < 1
    ):
        reported_count = None
    enumerated_count = len(concepts)
    return {
        "schema_version": CATALOG_SCHEMA,
        "concept_count": enumerated_count,
        "source_reported_count": reported_count,
        "enumerated_count": enumerated_count,
        "count_mismatch": reported_count is not None
        and reported_count != enumerated_count,
        "concepts": concepts,
        "classifier_catalog": classifier_catalog,
    }


def sanitize_operational_catalog(raw_catalog: object) -> dict[str, object]:
    """Produce a controller-safe catalog without hiding a source count mismatch."""

    if isinstance(raw_catalog, Mapping) and "catalog_source" in raw_catalog:
        return _sanitize_registry_catalog(raw_catalog)
    raw_items: object
    if isinstance(raw_catalog, Mapping):
        raw_items = raw_catalog.get("concepts")
    else:
        raw_items = raw_catalog
    if isinstance(raw_items, str) or not isinstance(raw_items, Sequence):
        raise FoundationEpisodeError(
            "catalog must be a concept sequence or {concepts: [...]}"
        )
    concepts = [
        _catalog_item(item, index=index) for index, item in enumerate(raw_items)
    ]
    if len(concepts) < 80:
        raise FoundationEpisodeError(
            f"sanitized catalog must contain at least 80 concepts, found {len(concepts)}"
        )
    concepts.sort(key=lambda entry: str(entry["concept_id"]))
    identifiers = [str(entry["concept_id"]) for entry in concepts]
    if len(set(identifiers)) != len(identifiers):
        raise FoundationEpisodeError(
            "sanitized catalog concept_id values must be unique"
        )
    classifier_catalog = [
        {
            "classifier_key": key,
            "runnable": True,
            "stratum": _normalize_stratum(
                next(
                    str(concept["family"])
                    for concept in concepts
                    if key in concept["operational_keys"]
                )
            ),
            "implementation_maturity": "declared",
            "runnable_reason": "implemented",
        }
        for key in sorted(
            {
                key
                for concept in concepts
                if concept["runnable"] is True
                for key in concept["operational_keys"]
            }
        )
    ]
    return {
        "schema_version": CATALOG_SCHEMA,
        "concept_count": len(concepts),
        "source_reported_count": None,
        "enumerated_count": len(concepts),
        "count_mismatch": False,
        "concepts": concepts,
        "classifier_catalog": classifier_catalog,
    }


def build_metric_catalog(
    term_indices: Sequence[object],
    *,
    metric_aliases: Sequence[object],
    metric_families: Sequence[object],
) -> dict[str, object]:
    """Publish exact term metadata without paths, IDs, values, or result history."""

    indices: list[int] = []
    for value in term_indices:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise FoundationEpisodeError("term indices must be non-negative integers")
        indices.append(value)
    if len(indices) != 76 or len(set(indices)) != 76:
        raise FoundationEpisodeError(
            "metric catalog must contain exactly 76 unique terms"
        )
    if len(metric_aliases) != len(metric_families):
        raise FoundationEpisodeError("term names and prefixes must have equal lengths")
    terms: list[dict[str, object]] = []
    for index in sorted(indices):
        if index >= len(metric_aliases):
            raise FoundationEpisodeError(
                "term metadata does not cover a cache term index"
            )
        alias = _require_text(metric_aliases[index], label="metric alias")
        family = _require_text(metric_families[index], label="metric family")
        terms.append(
            {
                "term_index": index,
                "metric_alias": alias,
                "metric_family": family,
            }
        )
    return {
        "schema_version": METRIC_CATALOG_SCHEMA,
        "term_count": 76,
        "terms": terms,
    }


def write_canonical_json(path: Path, payload: object) -> None:
    """Write ordinary normalized JSON for a local preflight or discovery record."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_json_bytes(payload) + b"\n")


def authorization_template() -> dict[str, object]:
    """Return the human-owned discovery-only authorization form."""

    return {
        "schema_version": AUTHORIZATION_SCHEMA,
        "episode_id": EPISODE_ID,
        "scope": DISCOVERY_SCOPE,
        "authorized": False,
        "authorization_id": "FILL_BY_HUMAN",
        "authorized_by": "FILL_BY_HUMAN",
        "rationale": "FILL_BY_HUMAN. This authorization does not authorize confirmation.",
        "confirmation_authorization": "NOT_GRANTED",
    }


__all__ = [
    "AUTHORIZATION_SCHEMA",
    "CATALOG_SCHEMA",
    "CANDIDATE_RECEIPT_COUNT",
    "CONTROLLER_BATCH_ORDER",
    "CONTROLLER_CALL_BUDGETS",
    "CONTROLLER_PRIMARY_BATCH_SLOTS",
    "CONTROLLER_TWO_SLOT_BATCHES",
    "COVERAGE_STRATA",
    "DISCOVERY_SCOPE",
    "EPISODE_ID",
    "FoundationEpisodeError",
    "ICA_TARGET_COLUMNS",
    "METRIC_CATALOG_SCHEMA",
    "PARTITION_SEED",
    "PHASE_AWAITING_DISCOVERY_AUTHORIZATION",
    "PRIMARY_STATISTIC",
    "PUBLIC_CLAIM_BOUNDARY_FIELDS",
    "RECEIPT_COUNT",
    "SEARCH_ALPHA_STAGES",
    "TARGET_NAME",
    "HOST_SLOT_CHAMPION_REPARTITION",
    "HOST_SLOT_RUNNER_UP_REPARTITION",
    "HOST_SLOT_FALSIFIER",
    "HOST_SLOT_POSITIVE_CONTROL",
    "V1_EPISODE_ID",
    "V1_EXCLUDED_CANDIDATE_PAIRS",
    "authorization_template",
    "build_episode_contract",
    "build_metric_catalog",
    "canonical_json_bytes",
    "controller_cadence_batches",
    "episode_receipt_slots",
    "sanitize_operational_catalog",
    "write_canonical_json",
]
