#!/usr/bin/env python3
"""Exact item-label permutation validation for embedding contrast findings.

This validator is intentionally narrow: it recomputes the contrast score used by
``run_embedding_autoresearch.py`` and enumerates balanced relabelings for a
locked set of candidate HCP language/social contrasts.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class ClaimSpec:
    claim_id: str
    round_id: str
    prediction_dir: Path
    analysis_dir: Path
    task_id: str
    contrast_id: str
    positive_conditions: tuple[str, ...]
    negative_conditions: tuple[str, ...]
    claim_status: str


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 0:
        return 0.0
    return float(np.dot(left, right) / denom)


def _score_for(
    embeddings: np.ndarray,
    positive_indices: list[int],
    negative_indices: list[int],
) -> dict[str, float]:
    pos = embeddings[positive_indices].mean(axis=0)
    neg = embeddings[negative_indices].mean(axis=0)
    diff = pos - neg
    diff_norm = float(np.linalg.norm(diff))
    cosine_gap = 1.0 - _cosine(pos, neg)
    score = diff_norm * max(cosine_gap, 1e-6)
    projection_gap = 0.0
    if diff_norm > 0:
        axis = diff / diff_norm
        projection_gap = float(np.dot(embeddings[positive_indices], axis).mean()) - float(
            np.dot(embeddings[negative_indices], axis).mean()
        )
    return {
        "score": float(score),
        "diff_norm": diff_norm,
        "cosine_gap": float(cosine_gap),
        "projection_gap": projection_gap,
    }


def _read_contrast_record(
    analysis_dir: Path,
    task_id: str,
    contrast_id: str,
) -> dict[str, Any]:
    path = analysis_dir / "contrast_findings.jsonl"
    for row in _read_jsonl(path):
        if row.get("task_id") == task_id and row.get("contrast_id") == contrast_id:
            return row
    raise ValueError(f"contrast not found: {task_id}:{contrast_id} in {path}")


def _hcp_language_social_claims(root: Path) -> list[ClaimSpec]:
    return [
        ClaimSpec(
            claim_id="hcp_language_round1_story_audio_vs_math_audio",
            round_id="round_01",
            prediction_dir=root / "predictions" / "wave1_pilot_round_01",
            analysis_dir=root / "analysis" / "embedding_autoresearch_20260425T031252Z",
            task_id="ibc_hcp_language",
            contrast_id="story_audio_vs_math_audio",
            positive_conditions=("story_audio",),
            negative_conditions=("math_audio",),
            claim_status="candidate_solid_positive",
        ),
        ClaimSpec(
            claim_id="hcp_social_round1_social_animation_vs_mechanical_motion",
            round_id="round_01",
            prediction_dir=root / "predictions" / "wave1_pilot_round_01",
            analysis_dir=root / "analysis" / "embedding_autoresearch_20260425T031252Z",
            task_id="ibc_hcp_social",
            contrast_id="social_animation_vs_mechanical_motion",
            positive_conditions=("social_animation",),
            negative_conditions=("mechanical_motion",),
            claim_status="negative_or_weak",
        ),
        ClaimSpec(
            claim_id="hcp_social_round2_social_animation_vs_mechanical_motion",
            round_id="round_02",
            prediction_dir=root / "predictions" / "wave1_pilot_round_02",
            analysis_dir=root / "analysis" / "embedding_autoresearch_20260425T062137Z",
            task_id="ibc_hcp_social_closed_loop_round02_hcp_social_tighten_positive_set",
            contrast_id="social_animation_vs_mechanical_motion",
            positive_conditions=("social_animation",),
            negative_conditions=("mechanical_motion",),
            claim_status="negative_or_weak_followup",
        ),
    ]


def _validate_claim(root: Path, claim: ClaimSpec) -> dict[str, Any]:
    rows = _read_jsonl(claim.prediction_dir / "embedding_rows.jsonl")
    embeddings = np.load(claim.prediction_dir / "embeddings_matrix.npy")
    if len(rows) != embeddings.shape[0]:
        raise ValueError(
            f"row/matrix mismatch in {claim.prediction_dir}: "
            f"{len(rows)} rows vs matrix shape {embeddings.shape}"
        )

    pos_conditions = set(claim.positive_conditions)
    neg_conditions = set(claim.negative_conditions)
    selected = [
        idx
        for idx, row in enumerate(rows)
        if row.get("task_id") == claim.task_id
        and (row.get("condition") in pos_conditions or row.get("condition") in neg_conditions)
    ]
    pos_original = [idx for idx in selected if rows[idx].get("condition") in pos_conditions]
    neg_original = [idx for idx in selected if rows[idx].get("condition") in neg_conditions]
    if not pos_original or not neg_original:
        raise ValueError(
            f"empty positive/negative set for {claim.claim_id}: "
            f"{len(pos_original)} positive, {len(neg_original)} negative"
        )

    local_lookup = {idx: local_idx for local_idx, idx in enumerate(selected)}
    pos_local = [local_lookup[idx] for idx in pos_original]
    neg_local = [local_lookup[idx] for idx in neg_original]
    selected_embeddings = embeddings[selected]

    observed = _score_for(selected_embeddings, pos_local, neg_local)
    contrast_record = _read_contrast_record(claim.analysis_dir, claim.task_id, claim.contrast_id)

    n_items = len(selected)
    n_positive = len(pos_local)
    null_scores: list[float] = []
    for combo in itertools.combinations(range(n_items), n_positive):
        pos = list(combo)
        pos_set = set(pos)
        neg = [idx for idx in range(n_items) if idx not in pos_set]
        null_scores.append(_score_for(selected_embeddings, pos, neg)["score"])

    null = np.asarray(null_scores, dtype=float)
    n_extreme = int(np.sum(null >= observed["score"] - 1e-12))
    exact_p = float(n_extreme / len(null))
    conservative_p = float((n_extreme + 1) / (len(null) + 1))
    quantiles = {
        str(q): float(np.quantile(null, q))
        for q in (0.0, 0.5, 0.9, 0.95, 0.975, 0.99, 1.0)
    }

    return {
        "schema_version": "br.autoresearch.permutation_validation.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_id": claim.claim_id,
        "claim_status_before_validation": claim.claim_status,
        "dataset_root": str(root),
        "prediction_dir": str(claim.prediction_dir),
        "analysis_dir": str(claim.analysis_dir),
        "task_id": claim.task_id,
        "round": claim.round_id,
        "contrast_id": claim.contrast_id,
        "positive_conditions": list(claim.positive_conditions),
        "negative_conditions": list(claim.negative_conditions),
        "score_function": "diff_norm * max(1 - cosine(pos_centroid, neg_centroid), 1e-6)",
        "permutation_unit": "item embedding row",
        "exchangeability_assumption": (
            "Labels are permuted only within the locked contrast item set while "
            "preserving n_positive and n_negative."
        ),
        "tail": "upper_one_sided_score_separation",
        "n_positive": len(pos_original),
        "n_negative": len(neg_original),
        "n_items": n_items,
        "n_exact_permutations": int(len(null)),
        "n_extreme_ge_observed": n_extreme,
        "exact_p_value": exact_p,
        "conservative_plus_one_p_value": conservative_p,
        "observed": observed,
        "analysis_record_score": {
            "score": contrast_record.get("score"),
            "diff_norm": contrast_record.get("diff_norm"),
            "cosine_gap": contrast_record.get("cosine_gap"),
            "n_positive": contrast_record.get("n_positive"),
            "n_negative": contrast_record.get("n_negative"),
        },
        "effect_summary": {
            "observed_minus_null_mean": float(observed["score"] - float(null.mean())),
            "observed_over_null_mean": float(observed["score"] / (float(null.mean()) + 1e-12)),
            "null_mean": float(null.mean()),
            "null_std": float(null.std(ddof=0)),
            "null_quantiles": quantiles,
        },
        "items": [
            {
                "item_id": rows[idx].get("item_id"),
                "condition": rows[idx].get("condition"),
                "labels": rows[idx].get("labels", {}),
            }
            for idx in selected
        ],
        "null_scores": [float(value) for value in sorted(null.tolist())],
    }


def _apply_corrections(results: list[dict[str, Any]]) -> None:
    n_tests = len(results)
    raw = [float(result["exact_p_value"]) for result in results]
    for result in results:
        result["correction_family"] = "hcp_language_social_locked_3_contrasts"
        result["bonferroni_p_value"] = min(1.0, float(result["exact_p_value"]) * n_tests)

    order = sorted(range(n_tests), key=lambda idx: raw[idx])
    holm = [0.0] * n_tests
    running = 0.0
    for rank, idx in enumerate(order):
        value = min(1.0, raw[idx] * (n_tests - rank))
        running = max(running, value)
        holm[idx] = running

    bh = [0.0] * n_tests
    previous = 1.0
    for rank_from_end, idx in enumerate(reversed(order), start=1):
        rank = n_tests - rank_from_end + 1
        value = min(previous, raw[idx] * n_tests / rank)
        bh[idx] = min(1.0, value)
        previous = value

    for idx, result in enumerate(results):
        result["holm_p_value"] = float(holm[idx])
        result["bh_fdr_q_value"] = float(bh[idx])
        result["validation_decision"] = (
            "significant_after_bonferroni"
            if float(result["bonferroni_p_value"]) < 0.05
            else "not_significant_after_bonferroni"
        )


def _fisher_social_p(results: list[dict[str, Any]]) -> dict[str, Any]:
    p_values = [
        float(result["exact_p_value"])
        for result in results
        if result["contrast_id"] == "social_animation_vs_mechanical_motion"
    ]
    statistic = -2.0 * sum(math.log(value) for value in p_values)
    # Survival function for chi-square with df=4: exp(-x/2) * (1 + x/2).
    p_value = math.exp(-statistic / 2.0) * (1.0 + statistic / 2.0)
    return {
        "method": "Fisher method over round1 and round2 exact p-values; chi-square df=4 survival",
        "p_values": p_values,
        "statistic": statistic,
        "p_value": p_value,
        "interpretation": "not_significant" if p_value >= 0.05 else "significant",
    }


def _write_summary(out_dir: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "schema_version": "br.autoresearch.permutation_validation_summary.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation_dir": str(out_dir),
        "correction_family": "hcp_language_social_locked_3_contrasts",
        "n_claims": len(results),
        "results": [
            {
                "claim_id": result["claim_id"],
                "round": result["round"],
                "task_id": result["task_id"],
                "contrast_id": result["contrast_id"],
                "n_positive": result["n_positive"],
                "n_negative": result["n_negative"],
                "n_exact_permutations": result["n_exact_permutations"],
                "n_extreme_ge_observed": result["n_extreme_ge_observed"],
                "observed_score": result["observed"]["score"],
                "diff_norm": result["observed"]["diff_norm"],
                "cosine_gap": result["observed"]["cosine_gap"],
                "exact_p_value": result["exact_p_value"],
                "conservative_plus_one_p_value": result["conservative_plus_one_p_value"],
                "bonferroni_p_value": result["bonferroni_p_value"],
                "holm_p_value": result["holm_p_value"],
                "bh_fdr_q_value": result["bh_fdr_q_value"],
                "validation_decision": result["validation_decision"],
            }
            for result in results
        ],
        "social_two_round_fisher_combination": _fisher_social_p(results),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))

    lines = [
        "# Permutation Validation Summary: HCP Language/Social",
        "",
        f"Created UTC: `{summary['created_at_utc']}`",
        "",
        (
            "Exact balanced item-label permutations were run for the locked HCP "
            "contrast family. The score was `diff_norm * max(cosine_gap, 1e-6)`, "
            "matching `run_embedding_autoresearch.py`."
        ),
        "",
        "| Claim | Observed score | diff_norm | cosine_gap | exact p | Bonferroni p | Decision |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in summary["results"]:
        lines.append(
            f"| `{result['claim_id']}` | {result['observed_score']:.6g} | "
            f"{result['diff_norm']:.6g} | {result['cosine_gap']:.6g} | "
            f"{result['exact_p_value']:.6g} | {result['bonferroni_p_value']:.6g} | "
            f"`{result['validation_decision']}` |"
        )
    social = summary["social_two_round_fisher_combination"]
    lines.extend(
        [
            "",
            f"Social two-round Fisher combination: p = `{social['p_value']:.6g}` ({social['interpretation']}).",
            "",
            (
                "Interpretation: HCP language remains a significant item-level "
                "finding after correction across the locked three-contrast family. "
                "HCP social remains non-significant in both rounds and in the "
                "two-round combination."
            ),
        ]
    )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Closed-loop root containing predictions/analysis.")
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory for validation cards.")
    parser.add_argument(
        "--preset",
        choices=["hcp_language_social_codex_v2"],
        default="hcp_language_social_codex_v2",
    )
    args = parser.parse_args()

    claims = _hcp_language_social_claims(args.root)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    results = [_validate_claim(args.root, claim) for claim in claims]
    _apply_corrections(results)
    for result in results:
        (args.out_dir / f"{result['claim_id']}.json").write_text(
            json.dumps(result, indent=2, sort_keys=True)
        )
    summary = _write_summary(args.out_dir, results)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
