#!/usr/bin/env python3
"""Build ready-now HCP language/social manifests for TRIBE closed-loop runs.

This is intentionally stdlib-only so it can run directly on the discovery VM.
It does not transcode media; it indexes already-packaged HCP audio/video assets.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": manifest["task_id"],
        "item_count": manifest["item_count"],
        "condition_counts": manifest["condition_counts"],
        "contrasts": [row["contrast_id"] for row in manifest["contrasts"]],
    }


def build_hcp_language(project_root: Path, source_root: Path) -> dict[str, Any]:
    stim_root = source_root / "hcp" / "protocols" / "language" / "LANGUAGE Stimuli"
    story_paths = sorted((stim_root / "Story").glob("*.wav"))
    math_paths = sorted((stim_root / "Math").glob("*.wav"))
    if not story_paths or not math_paths:
        raise FileNotFoundError(f"Missing HCP language Story/Math wav files under {stim_root}")

    items: list[dict[str, Any]] = []
    for condition, paths in (("story_audio", story_paths), ("math_audio", math_paths)):
        for path in paths:
            item_id = f"hcp_language_{condition}_{_safe_id(path.stem)}"
            items.append(
                {
                    "item_id": item_id,
                    "condition": condition,
                    "tribe_args": {"audio_path": str(path)},
                    "source": {"path": str(path)},
                    "labels": {
                        "hcp_task": "language",
                        "source_condition": path.parent.name,
                        "filename": path.name,
                    },
                }
            )

    return {
        "schema_version": "tribe-hcp-ready-manifest-v1",
        "prepared_at_utc": _utc_now(),
        "generated_at_utc": _utc_now(),
        "task_id": "ibc_hcp_language",
        "library_id": "tribe_ibc_paradigm_sweep_v1",
        "priority": "wave2",
        "task_family": "language",
        "task_readiness": "ready_now",
        "family": "language",
        "source_subdir": "hcp/protocols/language",
        "preferred_tribe_input": "audio_path",
        "materialized_root": str(project_root / "inputs" / "materialized" / "ibc_hcp_language"),
        "source_root": str(stim_root.parent),
        "expected_rois": [
            "left_inferior_frontal_gyrus",
            "left_superior_temporal_gyrus",
            "left_middle_temporal_gyrus",
        ],
        "br_kg_tags": ["hcp_language", "language_localizer", "story_comprehension"],
        "contrasts": [
            {
                "contrast_id": "story_audio_vs_math_audio",
                "positive_conditions": ["story_audio"],
                "negative_conditions": ["math_audio"],
            }
        ],
        "item_count": len(items),
        "condition_counts": dict(Counter(str(item["condition"]) for item in items)),
        "items": items,
    }


def _social_condition(path: Path) -> str | None:
    stem = path.stem.lower()
    if stem == "random social":
        return "social_animation"
    if stem.startswith(("billiard", "coaxing", "mocking", "seducing", "surprising")):
        return "social_animation"
    if stem == "random mechanical":
        return "mechanical_motion"
    if stem.startswith(("drifting", "star", "tennis")):
        return "mechanical_motion"
    return None


def build_hcp_social(project_root: Path, source_root: Path) -> dict[str, Any]:
    stim_root = source_root / "hcp" / "protocols" / "social" / "SOCIAL Stimuli"
    video_paths = sorted(stim_root.glob("*.AVI"))
    if not video_paths:
        raise FileNotFoundError(f"Missing HCP social AVI files under {stim_root}")

    items: list[dict[str, Any]] = []
    skipped: list[str] = []
    for path in video_paths:
        condition = _social_condition(path)
        if condition is None:
            skipped.append(path.name)
            continue
        item_id = f"hcp_social_{condition}_{_safe_id(path.stem)}"
        items.append(
            {
                "item_id": item_id,
                "condition": condition,
                "tribe_args": {"video_path": str(path)},
                "source": {"path": str(path)},
                "labels": {
                    "hcp_task": "social",
                    "filename": path.name,
                    "excluded_noncontrast_videos": skipped,
                },
            }
        )

    counts = Counter(str(item["condition"]) for item in items)
    if not counts.get("social_animation") or not counts.get("mechanical_motion"):
        raise ValueError(f"HCP social condition split is invalid: {dict(counts)}")

    return {
        "schema_version": "tribe-hcp-ready-manifest-v1",
        "prepared_at_utc": _utc_now(),
        "generated_at_utc": _utc_now(),
        "task_id": "ibc_hcp_social",
        "library_id": "tribe_ibc_paradigm_sweep_v1",
        "priority": "wave2",
        "task_family": "social_cognition",
        "task_readiness": "ready_now",
        "family": "social_cognition",
        "source_subdir": "hcp/protocols/social",
        "preferred_tribe_input": "video_path",
        "materialized_root": str(project_root / "inputs" / "materialized" / "ibc_hcp_social"),
        "source_root": str(stim_root.parent),
        "expected_rois": [
            "posterior_superior_temporal_sulcus",
            "temporoparietal_junction",
            "medial_prefrontal_cortex",
        ],
        "br_kg_tags": ["hcp_social", "theory_of_mind", "social_animation"],
        "contrasts": [
            {
                "contrast_id": "social_animation_vs_mechanical_motion",
                "positive_conditions": ["social_animation"],
                "negative_conditions": ["mechanical_motion"],
            }
        ],
        "item_count": len(items),
        "condition_counts": dict(counts),
        "items": items,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("/data/brain_researcher/research/discovery/project"),
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("/data/brain_researcher/research/discovery/inputs/public_protocols"),
    )
    parser.add_argument("--wave", default="hcp_stronger_codex_20260425")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifests_root = args.project_root / "manifests"
    language = build_hcp_language(args.project_root, args.source_root)
    social = build_hcp_social(args.project_root, args.source_root)

    language_path = manifests_root / "ibc_hcp_language_manifest.json"
    social_path = manifests_root / "ibc_hcp_social_manifest.json"
    _write_json(language_path, language)
    _write_json(social_path, social)

    index = {
        "library_id": "tribe_ibc_paradigm_sweep_v1",
        "prepared_at_utc": _utc_now(),
        "wave": args.wave,
        "task_count": 2,
        "tasks": [
            {
                "task_id": language["task_id"],
                "manifest_path": str(language_path),
                "item_count": language["item_count"],
                "preferred_tribe_input": language["preferred_tribe_input"],
            },
            {
                "task_id": social["task_id"],
                "manifest_path": str(social_path),
                "item_count": social["item_count"],
                "preferred_tribe_input": social["preferred_tribe_input"],
            },
        ],
    }
    index_path = manifests_root / "hcp_language_social_codex_manifest_index.json"
    _write_json(index_path, index)
    print(json.dumps({"index_path": str(index_path), "manifests": [_manifest_summary(language), _manifest_summary(social)]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
