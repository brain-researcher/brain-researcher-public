#!/usr/bin/env python3
"""Build the locked HCP-language layer-family confirmatory manifest.

The exploratory layer-feature run used ``hcp_language_heldout21_audio_v1``.
This helper builds a fresh story-audio vs math-audio split that excludes that
manifest by both item id and source block, then pairs story/math audio items by
simple audio/text covariates. The resulting pair id is the exchangeability
block for the confirmatory permutation test: labels may be swapped within a
matched pair, not within condition-pure source families.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import re
import wave
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "br.autoresearch.hcp_language_layer_family_confirmatory_manifest.v1"
BALANCE_SCHEMA_VERSION = "br.autoresearch.hcp_language_layer_family_balance.v1"

WORD_RE = re.compile(r"\b[\w']+\b")
MATH_RE = re.compile(
    r"^math-level(?P<level>\d+)-(?P<problem>\d+)-(?P<segment>[^.]+)\.wav$",
    re.IGNORECASE,
)

COVARIATES = [
    "duration_seconds",
    "rms",
    "dbfs",
    "word_count",
    "speech_rate_words_per_second",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _filename_for(item: dict[str, Any]) -> str | None:
    labels = _as_dict(item.get("labels"))
    filename = labels.get("filename") or item.get("filename")
    if filename:
        return Path(str(filename)).name
    path = _audio_path_for(item)
    if path:
        return Path(path).name
    item_id = item.get("item_id")
    if item_id and str(item_id).lower().endswith(".wav"):
        return Path(str(item_id)).name
    return None


def _audio_path_for(item: dict[str, Any]) -> str | None:
    tribe_args = _as_dict(item.get("tribe_args"))
    source = _as_dict(item.get("source"))
    path = tribe_args.get("audio_path") or item.get("audio_path") or source.get("path")
    return str(path) if path else None


def _condition_for(item: dict[str, Any]) -> str | None:
    condition = item.get("condition") or _as_dict(item.get("labels")).get("condition")
    if condition:
        lower = str(condition).lower()
        if lower in {"story", "story_audio"}:
            return "story_audio"
        if lower in {"math", "math_audio"}:
            return "math_audio"
        return str(condition)
    filename = _filename_for(item)
    if filename and MATH_RE.match(filename):
        return "math_audio"
    return None


def _source_block_id(item: dict[str, Any]) -> str:
    condition = _condition_for(item)
    filename = _filename_for(item) or str(item.get("item_id") or "unknown")
    math_match = MATH_RE.match(filename)
    if condition == "math_audio" and math_match:
        return (
            f"math_level{int(math_match.group('level'))}"
            f"_problem{int(math_match.group('problem'))}"
        )
    return f"story_{Path(filename).stem.lower()}"


def _wordlist_path(item: dict[str, Any], *, wordlist_root: Path) -> Path | None:
    filename = _filename_for(item)
    condition = _condition_for(item)
    if not filename or condition not in {"story_audio", "math_audio"}:
        return None
    subdir = "Story" if condition == "story_audio" else "Math"
    return wordlist_root / subdir / f"{Path(filename).stem}.txt"


def _word_count(item: dict[str, Any], *, wordlist_root: Path) -> tuple[int | None, str | None]:
    labels = _as_dict(item.get("labels"))
    for value in (
        item.get("words"),
        item.get("transcript"),
        labels.get("words"),
        labels.get("transcript"),
    ):
        if isinstance(value, list):
            text = " ".join(str(part) for part in value)
            return len(WORD_RE.findall(text)), "manifest"
        if isinstance(value, str) and value.strip():
            return len(WORD_RE.findall(value)), "manifest"
    path = _wordlist_path(item, wordlist_root=wordlist_root)
    if path and path.exists():
        return len(WORD_RE.findall(path.read_text(encoding="utf-8", errors="ignore"))), str(path)
    return None, None


def _wav_covariates(path: Path) -> dict[str, float]:
    with wave.open(str(path), "rb") as handle:
        sample_rate = handle.getframerate()
        n_frames = handle.getnframes()
        sample_width = handle.getsampwidth()
        raw = handle.readframes(n_frames)
    if sample_rate <= 0:
        raise ValueError(f"invalid sample rate in {path}")
    # Avoid audioop: it is deprecated and unavailable in some future Pythons.
    if sample_width == 1:
        import array

        samples = array.array("b", raw)
    elif sample_width == 2:
        import array

        samples = array.array("h", raw)
    elif sample_width == 4:
        import array

        samples = array.array("i", raw)
    else:
        raise ValueError(f"unsupported sample width {sample_width} bytes in {path}")
    if not samples:
        rms = 0.0
    else:
        rms = math.sqrt(sum(float(sample) ** 2 for sample in samples) / len(samples))
    full_scale = float(2 ** (8 * sample_width - 1))
    dbfs = 20.0 * math.log10(rms / full_scale) if rms > 0 else -120.0
    return {
        "duration_seconds": float(n_frames) / float(sample_rate),
        "rms": float(rms),
        "dbfs": float(dbfs),
        "sample_rate": float(sample_rate),
        "n_samples": float(n_frames),
    }


def _candidate_rows(
    base_items: list[dict[str, Any]],
    *,
    exclude_item_ids: set[str],
    exclude_source_blocks: set[str],
    wordlist_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in base_items:
        if not isinstance(item, dict):
            continue
        condition = _condition_for(item)
        if condition not in {"story_audio", "math_audio"}:
            continue
        item_id = str(item.get("item_id") or "")
        source_block_id = _source_block_id(item)
        if item_id in exclude_item_ids or source_block_id in exclude_source_blocks:
            skipped.append(
                {
                    "item_id": item_id,
                    "condition": condition,
                    "source_block_id": source_block_id,
                    "reason": "excluded_prior_heldout_overlap",
                }
            )
            continue
        raw_audio_path = _audio_path_for(item)
        if not raw_audio_path:
            skipped.append({"item_id": item_id, "condition": condition, "reason": "missing_audio_path"})
            continue
        audio_path = Path(raw_audio_path)
        if not audio_path.exists():
            skipped.append(
                {
                    "item_id": item_id,
                    "condition": condition,
                    "audio_path": str(audio_path),
                    "reason": "audio_path_not_found",
                }
            )
            continue
        words, word_source = _word_count(item, wordlist_root=wordlist_root)
        if words is None:
            skipped.append(
                {
                    "item_id": item_id,
                    "condition": condition,
                    "source_block_id": source_block_id,
                    "reason": "missing_wordlist",
                }
            )
            continue
        wav = _wav_covariates(audio_path)
        row = {
            "item": item,
            "item_id": item_id,
            "condition": condition,
            "filename": _filename_for(item),
            "audio_path": str(audio_path),
            "source_block_id": source_block_id,
            "word_count": float(words),
            "wordlist_source": word_source,
            **wav,
        }
        row["speech_rate_words_per_second"] = (
            row["word_count"] / row["duration_seconds"] if row["duration_seconds"] > 0 else None
        )
        rows.append(row)
    return rows, skipped


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((value - mu) ** 2 for value in values) / (len(values) - 1))


def _standardize(rows: list[dict[str, Any]]) -> None:
    for covariate in COVARIATES:
        values = [float(row[covariate]) for row in rows if row.get(covariate) is not None]
        mu = _mean(values)
        sd = _std(values) or 1.0
        for row in rows:
            row[f"{covariate}_z"] = (float(row[covariate]) - mu) / sd


def _pair_distance(story: dict[str, Any], math_item: dict[str, Any]) -> float:
    return math.sqrt(
        sum(
            (float(story[f"{covariate}_z"]) - float(math_item[f"{covariate}_z"])) ** 2
            for covariate in COVARIATES
        )
    )


def _greedy_pairs(
    rows: list[dict[str, Any]],
    *,
    target_pairs: int,
) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
    story_rows = [row for row in rows if row["condition"] == "story_audio"]
    math_rows = [row for row in rows if row["condition"] == "math_audio"]
    pair_candidates: list[tuple[float, int, int]] = []
    for story_idx, story in enumerate(story_rows):
        for math_idx, math_item in enumerate(math_rows):
            pair_candidates.append((_pair_distance(story, math_item), story_idx, math_idx))

    pairs: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    used_story: set[int] = set()
    used_math: set[int] = set()
    used_story_blocks: set[str] = set()
    used_math_blocks: set[str] = set()
    for distance, story_idx, math_idx in sorted(pair_candidates):
        story = story_rows[story_idx]
        math_item = math_rows[math_idx]
        if story_idx in used_story or math_idx in used_math:
            continue
        if story["source_block_id"] in used_story_blocks or math_item["source_block_id"] in used_math_blocks:
            continue
        pairs.append((story, math_item, distance))
        used_story.add(story_idx)
        used_math.add(math_idx)
        used_story_blocks.add(str(story["source_block_id"]))
        used_math_blocks.add(str(math_item["source_block_id"]))
        if len(pairs) >= target_pairs:
            break
    return pairs


def _unique_by_source_block(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Keep the first deterministic row per source block. For math, this avoids
    # picking multiple segments from one arithmetic problem in one confirmatory
    # set; for story it is effectively one row per audio item.
    unique: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda value: (str(value["source_block_id"]), str(value["item_id"]))):
        unique.setdefault(str(row["source_block_id"]), row)
    return list(unique.values())


def _pairs_from_selected_sets(
    story_rows: list[dict[str, Any]],
    math_rows: list[dict[str, Any]],
    *,
    target_pairs: int,
) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
    pair_candidates: list[tuple[float, int, int]] = []
    for story_idx, story in enumerate(story_rows):
        for math_idx, math_item in enumerate(math_rows):
            pair_candidates.append((_pair_distance(story, math_item), story_idx, math_idx))
    pairs: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    used_story: set[int] = set()
    used_math: set[int] = set()
    for distance, story_idx, math_idx in sorted(pair_candidates):
        if story_idx in used_story or math_idx in used_math:
            continue
        pairs.append((story_rows[story_idx], math_rows[math_idx], distance))
        used_story.add(story_idx)
        used_math.add(math_idx)
        if len(pairs) >= target_pairs:
            break
    return pairs


def _search_balanced_pairs(
    rows: list[dict[str, Any]],
    *,
    target_pairs: int,
    max_balance_smd: float,
    iterations: int,
    seed: int,
) -> tuple[list[tuple[dict[str, Any], dict[str, Any], float]], dict[str, Any]]:
    greedy = _greedy_pairs(rows, target_pairs=target_pairs)
    best_pairs = greedy
    best_balance = _balance_report(greedy, max_balance_smd=max_balance_smd) if greedy else None
    best_objective = (
        float(best_balance["max_abs_standardized_difference"]) if best_balance else float("inf")
    )
    if iterations <= 0:
        return best_pairs, {
            "search_strategy": "greedy_pair_distance_only",
            "iterations": 0,
            "best_objective": best_objective,
        }

    rng = random.Random(seed)
    story_pool = _unique_by_source_block([row for row in rows if row["condition"] == "story_audio"])
    math_pool = _unique_by_source_block([row for row in rows if row["condition"] == "math_audio"])
    if len(story_pool) < target_pairs or len(math_pool) < target_pairs:
        return best_pairs, {
            "search_strategy": "insufficient_unique_source_blocks",
            "iterations": 0,
            "best_objective": best_objective,
        }

    math_durations = sorted(float(row["duration_seconds"]) for row in math_pool)
    duration_floor = math_durations[max(0, int(len(math_durations) * 0.10) - 1)]
    long_story_pool = [
        row for row in story_pool if float(row["duration_seconds"]) >= duration_floor * 0.75
    ]
    if len(long_story_pool) < target_pairs:
        long_story_pool = story_pool

    for iteration in range(iterations):
        # Alternate between uniform sampling and a duration-biased story pool.
        # The raw HCP story pool contains many very short single-word clips,
        # while math clips are longer; without this bias the strict balance gate
        # is rarely reachable even though a balanced subset exists.
        selected_story_pool = long_story_pool if iteration % 2 else story_pool
        selected_story = rng.sample(selected_story_pool, target_pairs)
        selected_math = rng.sample(math_pool, target_pairs)
        pairs = _pairs_from_selected_sets(
            selected_story,
            selected_math,
            target_pairs=target_pairs,
        )
        if len(pairs) < target_pairs:
            continue
        balance = _balance_report(pairs, max_balance_smd=max_balance_smd)
        max_abs_smd = float(balance["max_abs_standardized_difference"])
        mean_pair_distance = float(balance["pair_distance_summary"]["mean"] or 0.0)
        objective = max_abs_smd + 0.01 * mean_pair_distance
        if objective < best_objective:
            best_pairs = pairs
            best_balance = balance
            best_objective = objective
        if max_abs_smd <= max_balance_smd:
            return best_pairs, {
                "search_strategy": "random_balanced_subset_with_greedy_pairing",
                "iterations": iteration + 1,
                "seed": seed,
                "best_objective": best_objective,
                "stopped_reason": "balance_gate_reached",
            }

    return best_pairs, {
        "search_strategy": "random_balanced_subset_with_greedy_pairing",
        "iterations": iterations,
        "seed": seed,
        "best_objective": best_objective,
        "stopped_reason": "iteration_budget_exhausted",
    }


def _balance_report(
    pairs: list[tuple[dict[str, Any], dict[str, Any], float]],
    *,
    max_balance_smd: float,
) -> dict[str, Any]:
    story_rows = [pair[0] for pair in pairs]
    math_rows = [pair[1] for pair in pairs]
    numeric: dict[str, Any] = {}
    for covariate in COVARIATES:
        story_values = [float(row[covariate]) for row in story_rows]
        math_values = [float(row[covariate]) for row in math_rows]
        story_mean = _mean(story_values)
        math_mean = _mean(math_values)
        story_std = _std(story_values)
        math_std = _std(math_values)
        pooled = math.sqrt((story_std * story_std + math_std * math_std) / 2.0)
        smd = (story_mean - math_mean) / pooled if pooled > 0 else 0.0
        numeric[covariate] = {
            "story_audio": {"n": len(story_values), "mean": story_mean, "std": story_std},
            "math_audio": {"n": len(math_values), "mean": math_mean, "std": math_std},
            "mean_difference_story_minus_math": story_mean - math_mean,
            "standardized_difference": smd,
            "passes_gate": abs(smd) <= max_balance_smd,
        }
    max_abs_smd = max(abs(row["standardized_difference"]) for row in numeric.values()) if numeric else None
    return {
        "schema_version": BALANCE_SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "covariates": COVARIATES,
        "max_balance_smd": max_balance_smd,
        "max_abs_standardized_difference": max_abs_smd,
        "passes_gate": bool(max_abs_smd is not None and max_abs_smd <= max_balance_smd),
        "numeric_covariates": numeric,
        "pair_distance_summary": {
            "mean": _mean([pair[2] for pair in pairs]) if pairs else None,
            "max": max((pair[2] for pair in pairs), default=None),
        },
    }


def _excluded_sets(exclude_manifest: dict[str, Any]) -> tuple[set[str], set[str]]:
    item_ids: set[str] = set()
    source_blocks: set[str] = set()
    for item in exclude_manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("item_id") is not None:
            item_ids.add(str(item.get("item_id")))
        source_blocks.add(_source_block_id(item))
    return item_ids, source_blocks


def _materialize_item(
    row: dict[str, Any],
    *,
    pair_id: str,
    pair_role: str,
    pair_distance: float,
) -> dict[str, Any]:
    item = copy.deepcopy(row["item"])
    labels = _as_dict(item.get("labels")).copy()
    labels.update(
        {
            "confirmatory_pair_id": pair_id,
            "confirmatory_pair_role": pair_role,
            "source_block_id": row["source_block_id"],
            "filename": row["filename"],
            "word_count": row["word_count"],
            "speech_rate_words_per_second": row["speech_rate_words_per_second"],
            "duration_seconds": row["duration_seconds"],
            "rms": row["rms"],
            "dbfs": row["dbfs"],
            "pair_distance": pair_distance,
        }
    )
    item["labels"] = labels
    item["condition"] = row["condition"]
    item["item_id"] = row["item_id"]
    return item


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    base_manifest = _read_json(Path(args.base_manifest))
    exclude_manifest = _read_json(Path(args.exclude_manifest))
    base_items = base_manifest.get("items")
    if not isinstance(base_items, list):
        raise ValueError("--base-manifest must contain list field 'items'")

    exclude_item_ids, exclude_source_blocks = _excluded_sets(exclude_manifest)
    candidates, skipped = _candidate_rows(
        base_items,
        exclude_item_ids=exclude_item_ids,
        exclude_source_blocks=exclude_source_blocks,
        wordlist_root=Path(args.wordlist_root),
    )
    if not candidates:
        raise ValueError("no candidates remain after exclusion and covariate extraction")
    _standardize(candidates)
    pairs, search_summary = _search_balanced_pairs(
        candidates,
        target_pairs=int(args.target_pairs),
        max_balance_smd=float(args.max_balance_smd),
        iterations=int(args.balance_search_iterations),
        seed=int(args.seed),
    )
    if len(pairs) < int(args.target_pairs):
        raise ValueError(f"only built {len(pairs)} pairs; target was {args.target_pairs}")

    balance = _balance_report(pairs, max_balance_smd=float(args.max_balance_smd))
    if args.require_balance and not balance["passes_gate"]:
        raise ValueError(
            "covariate balance gate failed: "
            f"max_abs_smd={balance['max_abs_standardized_difference']:.4f} "
            f"> {args.max_balance_smd}"
        )

    items: list[dict[str, Any]] = []
    pairs_out: list[dict[str, Any]] = []
    for pair_index, (story, math_item, distance) in enumerate(pairs, start=1):
        pair_id = f"hcp_language_layer_family_pair_{pair_index:03d}"
        items.append(
            _materialize_item(
                story,
                pair_id=pair_id,
                pair_role="story_audio",
                pair_distance=distance,
            )
        )
        items.append(
            _materialize_item(
                math_item,
                pair_id=pair_id,
                pair_role="math_audio",
                pair_distance=distance,
            )
        )
        pairs_out.append(
            {
                "pair_id": pair_id,
                "distance": distance,
                "story_item_id": story["item_id"],
                "math_item_id": math_item["item_id"],
                "story_source_block_id": story["source_block_id"],
                "math_source_block_id": math_item["source_block_id"],
                "covariates": {
                    covariate: {
                        "story_audio": story[covariate],
                        "math_audio": math_item[covariate],
                    }
                    for covariate in COVARIATES
                },
            }
        )

    manifest = copy.deepcopy(base_manifest)
    manifest.update(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": _utc_now(),
            "task_id": "ibc_hcp_language",
            "source_manifest_path": str(Path(args.base_manifest).resolve()),
            "excluded_manifest_path": str(Path(args.exclude_manifest).resolve()),
            "item_count": len(items),
            "items": items,
            "condition_counts": dict(sorted(Counter(item["condition"] for item in items).items())),
            "contrasts": [
                {
                    "contrast_id": "story_audio_vs_math_audio_layer_family_confirmatory",
                    "positive": ["story_audio"],
                    "negative": ["math_audio"],
                }
            ],
            "layer_family_confirmatory": {
                "exchangeability_unit": "confirmatory_pair_id",
                "permutation": "within_pair_label_swap",
                "target_pairs": args.target_pairs,
                "pair_count": len(pairs),
                "covariates": COVARIATES,
                "max_balance_smd": args.max_balance_smd,
                "balance_search": search_summary,
                "exclude_item_ids_count": len(exclude_item_ids),
                "exclude_source_blocks_count": len(exclude_source_blocks),
                "pairs": pairs_out,
                "skipped_candidate_count": len(skipped),
                "caveats": [
                    "HCP story and math source blocks are condition-pure; the confirmatory exchangeability block is therefore the matched story/math pair.",
                    "Word-count and speech-rate covariates are inferred from HCP wordlist text files.",
                    "The manifest excludes prior heldout items by item_id and source_block_id.",
                ],
            },
        }
    )
    _write_json(Path(args.out), manifest)
    if args.balance_out:
        _write_json(Path(args.balance_out), balance)
    print(
        json.dumps(
            {
                "out": str(Path(args.out)),
                "balance_out": str(Path(args.balance_out)) if args.balance_out else None,
                "item_count": len(items),
                "pair_count": len(pairs),
                "condition_counts": manifest["condition_counts"],
                "balance_passes": balance["passes_gate"],
                "max_abs_smd": balance["max_abs_standardized_difference"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--exclude-manifest", type=Path, required=True)
    parser.add_argument("--wordlist-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--balance-out", type=Path)
    parser.add_argument("--target-pairs", type=int, default=21)
    parser.add_argument("--max-balance-smd", type=float, default=0.25)
    parser.add_argument("--balance-search-iterations", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=20260426)
    parser.add_argument(
        "--require-balance",
        action="store_true",
        help="Fail if any locked covariate exceeds --max-balance-smd.",
    )
    return parser.parse_args()


def main() -> int:
    build_manifest(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
