#!/usr/bin/env python3
"""Build HCP-language exchangeability and held-out split metadata.

The input is a TRIBE/BR ``embedding_rows.jsonl`` file. The output is a JSON
manifest with filename-derived stimulus metadata, source-family grouping, and a
deterministic held-out split assignment. The manifest is descriptive: it does
not by itself establish that a blocked permutation test is valid.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "br.autoresearch.hcp_language_exchangeability_manifest.v1"

STORY_RE = re.compile(r"^Story(?P<story_id>\d+)\.wav$", re.IGNORECASE)
MATH_RE = re.compile(
    r"^math-level(?P<level>\d+)-(?P<problem>\d+)-(?P<segment>[^.]+)\.wav$",
    re.IGNORECASE,
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path} line {line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"expected object in {path} line {line_number}, got {type(row).__name__}")
        rows.append(row)
    return rows


def _nested_get(mapping: dict[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _filename_for(row: dict[str, Any]) -> str | None:
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    filename = labels.get("filename")
    if filename:
        return Path(str(filename)).name
    source_path = _source_path_for(row)
    if source_path:
        return Path(source_path).name
    item_id = row.get("item_id")
    if item_id and str(item_id).lower().endswith(".wav"):
        return Path(str(item_id)).name
    return None


def _source_path_for(row: dict[str, Any]) -> str | None:
    source_path = _nested_get(row, "source", "path")
    if source_path:
        return str(source_path)
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    for key in ("source_path", "path"):
        if labels.get(key):
            return str(labels[key])
    return None


def _math_segment_role(segment: str) -> str:
    normalized = segment.strip().lower().replace("-", "_")
    if normalized in {"1", "a", "operand1", "operand_1", "op1", "op_1"}:
        return "operand_1"
    if normalized in {"2", "b", "operand2", "operand_2", "op2", "op_2"}:
        return "operand_2"
    if normalized in {"q", "question", "query"}:
        return "question"
    return "raw"


def _heldout_index(source_family: str, modulus: int) -> int:
    digest = hashlib.sha256(source_family.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % modulus


def _base_metadata(row: dict[str, Any], filename: str | None) -> dict[str, Any]:
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    source_condition = labels.get("source_condition")
    return {
        "item_id": row.get("item_id"),
        "task_id": row.get("task_id"),
        "condition": row.get("condition"),
        "filename": filename,
        "source_path": _source_path_for(row),
        "labels_source_condition": source_condition,
    }


def _parse_hcp_language_row(row: dict[str, Any], heldout_modulus: int) -> dict[str, Any]:
    filename = _filename_for(row)
    metadata = _base_metadata(row, filename)

    if filename:
        story_match = STORY_RE.match(filename)
        if story_match:
            story_id = int(story_match.group("story_id"))
            source_family = f"story_{story_id}"
            split_index = _heldout_index(source_family, heldout_modulus)
            metadata.update(
                {
                    "stimulus_family": "story",
                    "story_id": story_id,
                    "source_family": source_family,
                    "exchangeability_block": "story_audio_singleton",
                    "exchangeability_block_note": (
                        "Conservative singleton block: filename metadata does not expose "
                        "multiple story-derived exchangeable rows."
                    ),
                }
            )
            _add_split(metadata, split_index, heldout_modulus)
            return metadata

        math_match = MATH_RE.match(filename)
        if math_match:
            level = int(math_match.group("level"))
            problem = int(math_match.group("problem"))
            segment = math_match.group("segment")
            role = _math_segment_role(segment)
            source_family = f"math_level{level}_problem{problem}"
            split_index = _heldout_index(source_family, heldout_modulus)
            metadata.update(
                {
                    "stimulus_family": "math",
                    "math_level": level,
                    "math_problem_id": problem,
                    "math_segment_raw": segment,
                    "math_segment_role": role,
                    "source_family": source_family,
                    "exchangeability_block": source_family,
                    "exchangeability_block_note": (
                        "Math rows from the same level/problem are grouped together; "
                        "segment rows should not be split across held-out partitions."
                    ),
                }
            )
            _add_split(metadata, split_index, heldout_modulus)
            return metadata

    source_family = _unknown_source_family(row, filename)
    split_index = _heldout_index(source_family, heldout_modulus)
    metadata.update(
        {
            "stimulus_family": "unknown",
            "source_family": source_family,
            "exchangeability_block": "unknown_filename",
            "exchangeability_block_note": (
                "Filename did not match the known HCP language story/math patterns."
            ),
        }
    )
    _add_split(metadata, split_index, heldout_modulus)
    return metadata


def _unknown_source_family(row: dict[str, Any], filename: str | None) -> str:
    if filename:
        stem = Path(filename).stem
        return f"unknown_{stem}"
    item_id = row.get("item_id")
    if item_id:
        digest = hashlib.sha256(str(item_id).encode("utf-8")).hexdigest()[:12]
        return f"unknown_item_{digest}"
    digest = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
    return f"unknown_row_{digest}"


def _add_split(metadata: dict[str, Any], split_index: int, heldout_modulus: int) -> None:
    metadata["heldout_split_index"] = split_index
    metadata["heldout_split_label"] = f"split_{split_index}"
    metadata["heldout_split"] = "heldout" if split_index == 0 else "calibration"
    metadata["heldout_modulus"] = heldout_modulus


def _sorted_counter(values: list[str | None]) -> dict[str, int]:
    counter = Counter(str(value) if value is not None else "null" for value in values)
    return dict(sorted(counter.items()))


def _build_manifest(
    rows: list[dict[str, Any]],
    *,
    embedding_rows: Path,
    task_id: str | None,
    heldout_modulus: int,
) -> dict[str, Any]:
    if heldout_modulus <= 0:
        raise ValueError("--heldout-modulus must be a positive integer")

    if task_id is not None:
        selected_rows = [row for row in rows if str(row.get("task_id")) == task_id]
    else:
        selected_rows = rows

    parsed_rows = [_parse_hcp_language_row(row, heldout_modulus) for row in selected_rows]
    unknown_count = sum(1 for row in parsed_rows if row.get("stimulus_family") == "unknown")
    story_count = sum(1 for row in parsed_rows if row.get("stimulus_family") == "story")
    math_count = sum(1 for row in parsed_rows if row.get("stimulus_family") == "math")

    caveats = [
        (
            "Metadata is inferred from embedding row labels and filenames only; it does "
            "not include subject, run, acquisition order, or full stimulus-design context."
        ),
        (
            "The held-out assignment is a deterministic source_family hash partition, "
            "not evidence that held-out/calibration groups are balanced for all nuisance "
            "variables."
        ),
        (
            "Story rows are marked as conservative singleton blocks. This does not "
            "support within-story exchangeability or a valid blocked permutation test by itself."
        ),
        (
            "Math rows are grouped by level/problem so problem segments are kept together, "
            "but filename metadata alone does not prove segment-level exchangeability."
        ),
    ]
    if unknown_count:
        caveats.append(
            f"{unknown_count} row(s) did not match known StoryN.wav or "
            "math-level<level>-<problem>-<segment>.wav filename patterns."
        )
    if heldout_modulus == 1:
        caveats.append(
            "--heldout-modulus 1 assigns every source_family to heldout; use a larger "
            "modulus for calibration/held-out separation."
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": {
            "embedding_rows": str(embedding_rows),
            "task_id_filter": task_id,
            "n_input_rows": len(rows),
            "n_rows_after_task_filter": len(selected_rows),
            "heldout_modulus": heldout_modulus,
        },
        "counts": {
            "by_condition": _sorted_counter([row.get("condition") for row in parsed_rows]),
            "by_stimulus_family": _sorted_counter(
                [row.get("stimulus_family") for row in parsed_rows]
            ),
            "by_heldout_split": _sorted_counter([row.get("heldout_split") for row in parsed_rows]),
            "story_rows": story_count,
            "math_rows": math_count,
            "unknown_rows": unknown_count,
        },
        "source_family_counts": _sorted_counter([row.get("source_family") for row in parsed_rows]),
        "recommended_exchangeability_notes": [
            (
                "Use source_family as the minimum grouping key for held-out splits so "
                "math segments from one problem are not split across partitions."
            ),
            (
                "For math-only analyses, consider problem-level units "
                "(math_level<level>_problem<problem>) before any row-level permutation."
            ),
            (
                "For story-vs-math contrasts, family structure is asymmetric: story "
                "items are singleton audio files while math items can have multiple "
                "segments per problem. Treat blocked tests as unverified until the "
                "analysis explicitly accounts for that structure."
            ),
        ],
        "caveats": caveats,
        "rows": parsed_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--embedding-rows",
        type=Path,
        required=True,
        help="Input TRIBE/BR embedding_rows.jsonl path.",
    )
    parser.add_argument("--out", type=Path, required=True, help="Output JSON manifest path.")
    parser.add_argument("--task-id", help="Optional task_id filter.")
    parser.add_argument(
        "--heldout-modulus",
        type=int,
        default=5,
        help="Hash modulus for source_family held-out assignment; split 0 is heldout.",
    )
    args = parser.parse_args()

    rows = _read_jsonl(args.embedding_rows)
    manifest = _build_manifest(
        rows,
        embedding_rows=args.embedding_rows,
        task_id=args.task_id,
        heldout_modulus=args.heldout_modulus,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: manifest[k] for k in ("schema_version", "input", "counts")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
