#!/usr/bin/env python3
"""Validate and redraw the HCP workflow-search derived-artifact replay pack.

This command checks that the public-safe tables retain the recorded Figure 5
accounting and redraws the SVG.  It does not recreate HCP inputs, candidates,
or subject-level predictions, and it does not claim a governed scientific rerun.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

from render_figure5 import PACK_ROOT, render

DATA_DIR = PACK_ROOT / "data"
EXPECTED_SEARCH_HEADERS = {
    "candidate_order",
    "phase",
    "status",
    "cross_validated_r",
}
EXPECTED_OUTCOME_HEADERS = {
    "outcome_key",
    "outcome_label",
    "median_selected_r",
    "median_reference_r",
    "median_delta_r",
    "median_selected_r2",
    "median_reference_r2",
    "directional_wins",
    "repeat_count",
    "conditional_one_sided_p",
    "comparison_role",
}
EXPECTED_REPEAT_HEADERS = {"outcome_key", "repeat_index", "delta_r"}


def _load_csv(path: Path, expected_headers: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        if headers != expected_headers:
            raise ValueError(f"{path.name}: unexpected headers {sorted(headers)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name}: no rows")
    for row in rows:
        encoded = json.dumps(row, sort_keys=True)
        if "/data/" in encoded or "/home/" in encoded:
            raise ValueError(f"{path.name}: absolute path leaked into public table")
    return rows


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def _close(observed: float, expected: float, tolerance: float = 1e-12) -> bool:
    return abs(observed - expected) <= tolerance


def validate() -> dict[str, object]:
    search = _load_csv(DATA_DIR / "search_candidates.csv", EXPECTED_SEARCH_HEADERS)
    outcomes = _load_csv(DATA_DIR / "matched_outcomes.csv", EXPECTED_OUTCOME_HEADERS)
    repeats = _load_csv(DATA_DIR / "paired_repeat_deltas.csv", EXPECTED_REPEAT_HEADERS)
    summary = json.loads((DATA_DIR / "study_summary.json").read_text(encoding="utf-8"))

    if summary["replay_scope"] != "derived_artifact_replay_only":
        raise ValueError(
            "study summary must retain the derived-artifact replay boundary"
        )
    if summary["redaction"] != {
        "contains_absolute_paths": False,
        "contains_participant_or_family_identifiers": False,
        "contains_prediction_vectors": False,
        "contains_private_receipts": False,
    }:
        raise ValueError("study summary redaction declaration changed")

    orders = [int(row["candidate_order"]) for row in search]
    if orders != list(range(1, 117)):
        raise ValueError("search table must contain candidate orders 1 through 116")
    if len(search) != 116 or sum(row["phase"] == "initial_20" for row in search) != 20:
        raise ValueError("search denominator no longer records 20 + 96 candidates")
    if sum(row["phase"] == "expanded_96" for row in search) != 96:
        raise ValueError("expanded search denominator is not 96")
    complete = [row for row in search if row["status"] == "succeeded"]
    incomplete = [row for row in search if row["status"] == "incomplete"]
    if len(complete) != 104 or len(incomplete) != 12:
        raise ValueError(
            "search accounting must remain 104 completed and 12 incomplete"
        )
    if any(not row["cross_validated_r"] for row in complete) or any(
        row["cross_validated_r"] for row in incomplete
    ):
        raise ValueError(
            "search table must include scores only for completed candidates"
        )
    if not summary["search"]["transport_recovery_parent_denominator_unchanged"]:
        raise ValueError("transport recovery must not change the parent denominator")
    initial_scores = [
        float(row["cross_validated_r"])
        for row in complete
        if row["phase"] == "initial_20"
    ]
    expanded_scores = [
        float(row["cross_validated_r"])
        for row in complete
        if row["phase"] == "expanded_96"
    ]
    initial_maximum = max(initial_scores)
    expanded_maximum = max(expanded_scores)
    expanded_above_initial = sum(value > initial_maximum for value in expanded_scores)
    if len(expanded_scores) != 84 or expanded_above_initial != 27:
        raise ValueError("expanded search headline accounting drifted")
    if not _close(initial_maximum, 0.37263729808107476):
        raise ValueError("initial search maximum drifted")
    if not _close(expanded_maximum, 0.48710921135174756):
        raise ValueError("expanded search maximum drifted")
    expected_milestones = [
        {
            "candidate_order": 15,
            "label": "initial 20-candidate best covariance + SVR",
            "r": 0.37263729808107476,
        },
        {
            "candidate_order": 33,
            "label": "precision + CPM",
            "r": 0.3857684993124818,
        },
        {
            "candidate_order": 41,
            "label": "precision + ridge",
            "r": 0.4543736067828828,
        },
        {
            "candidate_order": 109,
            "label": "highest discovery score coherence + ridge",
            "r": 0.48710921135174756,
        },
    ]
    if summary["search"] != {
        "completed_candidate_count": 104,
        "expanded_scored_candidate_count": 84,
        "expanded_scores_above_initial_maximum": 27,
        "expanded_search_maximum_r": 0.48710921135174756,
        "expanded_candidate_count": 96,
        "incomplete_candidate_count": 12,
        "initial_candidate_count": 20,
        "initial_search_maximum_r": 0.37263729808107476,
        "milestones": expected_milestones,
        "parent_candidate_count": 116,
        "transport_recovery_parent_denominator_unchanged": True,
    }:
        raise ValueError("search summary no longer matches the replay table")
    by_order = {int(row["candidate_order"]): row for row in complete}
    for milestone in expected_milestones:
        observed = float(by_order[milestone["candidate_order"]]["cross_validated_r"])
        if not _close(observed, milestone["r"]):
            raise ValueError("search milestone no longer matches the replay table")

    expected_cohort_ledger = {
        "eligible_hcp_cohort_n": 326,
        "search": {"row_count": 245, "family_count": 244},
        "matched_comparison": {"row_count": 244, "family_count": 243},
        "separate_internal_holdout_row_count": 81,
    }
    if summary["cohort_ledger"] != expected_cohort_ledger:
        raise ValueError("aggregate HCP cohort ledger changed")

    selection = summary["selection"]
    if selection["automatic_champion_selected"]:
        raise ValueError(
            "selected workflow must not be represented as an automatic champion"
        )
    if not selection["analysis_frozen_before_matched_comparison"]:
        raise ValueError("matched comparison must stay downstream of the freeze")

    by_key = {row["outcome_key"]: row for row in outcomes}
    expected_keys = {
        "cognition",
        "tobacco_use",
        "personality_emotion",
        "illicit_drug_use",
        "mental_health",
    }
    if set(by_key) != expected_keys:
        raise ValueError("outcome table must contain exactly five recorded outcomes")
    if len(repeats) != 50:
        raise ValueError("repeat table must contain 50 score-difference records")

    repeats_by_key: dict[str, list[float]] = {key: [] for key in expected_keys}
    for row in repeats:
        key = row["outcome_key"]
        if key not in repeats_by_key:
            raise ValueError(f"unexpected repeat outcome {key}")
        repeats_by_key[key].append(float(row["delta_r"]))
    for key, values in repeats_by_key.items():
        if len(values) != 10:
            raise ValueError(f"{key}: expected 10 repeat-level score differences")
        outcome = by_key[key]
        if not _close(_median(values), float(outcome["median_delta_r"])):
            raise ValueError(
                f"{key}: median score difference does not match outcome table"
            )
        if sum(value > 0 for value in values) != int(outcome["directional_wins"]):
            raise ValueError(f"{key}: directional wins do not match repeat table")

    cognition = by_key["cognition"]
    if int(cognition["directional_wins"]) != 10 or int(cognition["repeat_count"]) != 10:
        raise ValueError("Cognition must remain 10/10")
    if not _close(float(cognition["median_delta_r"]), 0.09827205188739016):
        raise ValueError("Cognition median delta r drifted")
    if not _close(float(cognition["conditional_one_sided_p"]), 0.006):
        raise ValueError("Cognition conditional p drifted")

    transfer_keys = expected_keys - {"cognition"}
    transfer_wins = sum(int(by_key[key]["directional_wins"]) for key in transfer_keys)
    transfer_total = sum(int(by_key[key]["repeat_count"]) for key in transfer_keys)
    all_wins = sum(int(row["directional_wins"]) for row in outcomes)
    all_total = sum(int(row["repeat_count"]) for row in outcomes)
    if (transfer_wins, transfer_total) != (37, 40):
        raise ValueError("transfer result must remain 37/40")
    if (all_wins, all_total) != (47, 50):
        raise ValueError("all-outcome result must remain 47/50")
    if summary["transfer"]["weak_fwer_status"] != "unsupported":
        raise ValueError("transfer weak-FWER status must remain unsupported")

    positive_r2 = sorted(
        row["outcome_label"] for row in outcomes if float(row["median_selected_r2"]) > 0
    )
    if positive_r2 != ["Cognition", "Tobacco Use"]:
        raise ValueError(
            "only Cognition and Tobacco Use may have positive median selected R2"
        )

    closure = summary["producer_closure"]
    if closure["complete_governed_rerun_claimed"]:
        raise ValueError(
            "derived-artifact pack must not claim a complete governed rerun"
        )
    expected_historical_producing_code = {
        "publicly_resolvable": True,
        "public_entrypoint_guide": "src/brain_researcher/research/predictive/foundation_episode/README.md",
        "shipped_in_public_pack": False,
        "stages": [
            "MVE100 expansion",
            "12-slot recovery",
            "R2 Cognition paired inference",
            "R3 transfer",
        ],
        "status": "publicly_shipped_outside_replay_pack",
    }
    if closure["historical_producing_code"] != expected_historical_producing_code:
        raise ValueError("stage-level producer provenance changed")
    if closure["public_pack_claim"] != "derived artifact replay only":
        raise ValueError("public-pack scope changed")

    return {
        "scope": summary["replay_scope"],
        "search": {"parent": 116, "completed": 104, "incomplete": 12},
        "search_headline": {
            "initial_maximum_r": initial_maximum,
            "expanded_scored": len(expanded_scores),
            "expanded_above_initial_maximum": expanded_above_initial,
            "expanded_maximum_r": expanded_maximum,
        },
        "cohort_ledger": expected_cohort_ledger,
        "selection": {
            "automatic_champion_selected": False,
            "analysis_frozen_before_matched_comparison": True,
        },
        "cognition": {
            "directional_wins": "10/10",
            "median_delta_r": 0.09827205188739016,
            "conditional_one_sided_p": 0.006,
        },
        "transfer": {"directional_wins": "37/40", "weak_fwer_status": "unsupported"},
        "all_outcomes": {"directional_wins": "47/50"},
        "positive_median_selected_r2": positive_r2,
        "producer_closure": {
            "publicly_resolvable": True,
            "shipped_in_public_pack": False,
            "complete_governed_rerun_claimed": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PACK_ROOT / "figures" / "figure5_hcp_workflow_search.svg",
        help="SVG output path (default: committed Figure 5 artifact)",
    )
    args = parser.parse_args()
    report = validate()
    rendered = render(args.output)
    report["rendered_figure"] = str(rendered)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
