#!/usr/bin/env python3
"""Build a held-out HCP language manifest from unused base-manifest items.

This is an operational helper for the hypothesis-discovery validation line. It
excludes filenames already present in a completed prediction run, keeps math
problem families intact, and writes a new manifest suitable for a held-out
story-audio vs math-audio rerun.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_hcp_language_exchangeability_manifest import (
    _filename_for,
    _parse_hcp_language_row,
    _read_jsonl,
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _used_filenames(embedding_rows_path: Path) -> set[str]:
    used: set[str] = set()
    for row in _read_jsonl(embedding_rows_path):
        filename = _filename_for(row)
        if filename:
            used.add(filename)
    return used


def _condition_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(item.get("condition")) for item in items).items()))


def _select_story_items(
    candidates: list[dict[str, Any]],
    *,
    target_count: int,
) -> list[dict[str, Any]]:
    ordered = sorted(
        candidates,
        key=lambda item: (
            item["_derived"].get("heldout_split_index", 999),
            item["_derived"].get("story_id", 10**9),
            str(item.get("item_id")),
        ),
    )
    return ordered[:target_count]


def _select_math_items(
    candidates: list[dict[str, Any]],
    *,
    target_rows: int,
) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        by_family[str(item["_derived"].get("source_family"))].append(item)

    selected: list[dict[str, Any]] = []
    for family, family_items in sorted(
        by_family.items(),
        key=lambda entry: (
            min(item["_derived"].get("heldout_split_index", 999) for item in entry[1]),
            min(item["_derived"].get("math_level", 10**9) for item in entry[1]),
            min(item["_derived"].get("math_problem_id", 10**9) for item in entry[1]),
            entry[0],
        ),
    ):
        family_items = sorted(
            family_items,
            key=lambda item: (
                item["_derived"].get("math_level", 10**9),
                item["_derived"].get("math_problem_id", 10**9),
                item["_derived"].get("math_segment_role", ""),
                str(item.get("item_id")),
            ),
        )
        if len(selected) + len(family_items) > target_rows:
            continue
        selected.extend(family_items)
        if len(selected) >= target_rows:
            break
    return selected


def _strip_derived(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped = []
    for item in items:
        clone = copy.deepcopy(item)
        clone.pop("_derived", None)
        stripped.append(clone)
    return stripped


def build_heldout_manifest(
    *,
    base_manifest_path: Path,
    used_embedding_rows_path: Path,
    out_path: Path,
    target_story_count: int,
    target_math_rows: int,
    heldout_modulus: int,
) -> dict[str, Any]:
    base_manifest = _read_json(base_manifest_path)
    base_items = base_manifest.get("items")
    if not isinstance(base_items, list):
        raise ValueError(f"base manifest {base_manifest_path} does not contain list field 'items'")

    used = _used_filenames(used_embedding_rows_path)
    story_candidates: list[dict[str, Any]] = []
    math_candidates: list[dict[str, Any]] = []
    skipped_used = 0
    skipped_unknown = 0

    for item in base_items:
        if not isinstance(item, dict):
            continue
        filename = _filename_for(item)
        if filename in used:
            skipped_used += 1
            continue
        derived = _parse_hcp_language_row(item, heldout_modulus)
        family = derived.get("stimulus_family")
        condition = str(item.get("condition") or "")
        clone = copy.deepcopy(item)
        clone["_derived"] = derived
        if family == "story" or condition == "story_audio":
            if family != "story":
                clone["_derived"]["stimulus_family"] = "story"
                clone["_derived"]["exchangeability_block_note"] = (
                    "Story candidate accepted by condition label because filename did "
                    "not match StoryN.wav; source_family is filename-derived."
                )
            story_candidates.append(clone)
        elif family == "math" or condition == "math_audio":
            math_candidates.append(clone)
        else:
            skipped_unknown += 1

    selected_story = _select_story_items(story_candidates, target_count=target_story_count)
    selected_math = _select_math_items(math_candidates, target_rows=target_math_rows)
    if len(selected_story) < target_story_count:
        raise ValueError(
            f"only selected {len(selected_story)} story items, target was {target_story_count}"
        )
    if len(selected_math) < target_math_rows:
        raise ValueError(
            f"only selected {len(selected_math)} math rows, target was {target_math_rows}"
        )

    selected_items_with_derived = selected_story + selected_math
    selected_items = _strip_derived(selected_items_with_derived)
    manifest = copy.deepcopy(base_manifest)
    manifest["schema_version"] = "br.autoresearch.hcp_language_heldout_manifest.v1"
    manifest["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["source_manifest_path"] = str(base_manifest_path)
    manifest["excluded_embedding_rows_path"] = str(used_embedding_rows_path)
    manifest["selection_policy"] = {
        "name": "unused_story_singletons_and_complete_math_problem_families",
        "target_story_count": target_story_count,
        "target_math_rows": target_math_rows,
        "heldout_modulus": heldout_modulus,
        "math_problem_families_preserved": True,
    }
    manifest["items"] = selected_items
    manifest["item_count"] = len(selected_items)
    manifest["condition_counts"] = _condition_counts(selected_items)
    manifest["heldout_selection_summary"] = {
        "n_base_items": len(base_items),
        "n_used_filenames_excluded": len(used),
        "n_items_skipped_as_used": skipped_used,
        "n_unknown_items_skipped": skipped_unknown,
        "n_story_candidates_after_exclusion": len(story_candidates),
        "n_math_candidates_after_exclusion": len(math_candidates),
        "selected_source_families": sorted(
            {
                str(item["_derived"].get("source_family"))
                for item in selected_items_with_derived
            }
        ),
        "selected_filenames": sorted(
            str(item["_derived"].get("filename")) for item in selected_items_with_derived
        ),
        "caveats": [
            "This manifest is held out from the supplied prediction rows by filename.",
            "Math problem families are kept intact, so target_math_rows should usually be a multiple of complete problem-family sizes.",
            "This helper does not balance audio covariates such as duration, loudness, speaker, transcript length, or difficulty.",
        ],
    }
    _write_json(out_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--used-embedding-rows", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--target-story-count", type=int, default=21)
    parser.add_argument("--target-math-rows", type=int, default=21)
    parser.add_argument("--heldout-modulus", type=int, default=5)
    args = parser.parse_args()
    manifest = build_heldout_manifest(
        base_manifest_path=args.base_manifest,
        used_embedding_rows_path=args.used_embedding_rows,
        out_path=args.out,
        target_story_count=args.target_story_count,
        target_math_rows=args.target_math_rows,
        heldout_modulus=args.heldout_modulus,
    )
    print(
        json.dumps(
            {
                "out": str(args.out),
                "item_count": manifest["item_count"],
                "condition_counts": manifest["condition_counts"],
                "selected_families": manifest["heldout_selection_summary"]["selected_source_families"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
