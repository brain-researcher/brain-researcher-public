#!/usr/bin/env python3

"""
Filter a cached NeuroVault inventory down to a curated subset and write:
  - filtered metadata JSON
  - newline-delimited image ID list

Defaults are tuned for Brain Researcher:
  * Collections: drop obvious temp/test/sandbox names; require number_of_images > 0
  * Images:
      - map_type in {T/Z/F variants}
      - modality == "fMRI-BOLD"
      - is_thresholded is not True
      - in_mni_space is not False (allows True or missing)
      - analysis_level in {None, "", "group", "study"}

Usage (from repo root):
    python scripts/tools/etl/neurovault_filter.py

Override paths if your cache filenames differ:
    python scripts/tools/etl/neurovault_filter.py \\
      --images data/neurovault/cache/neurovault_images_*.json \\
      --collections data/neurovault/cache/search_*.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

DEFAULT_IMAGES = Path("data/neurovault/cache/neurovault_images_20251115_122632.json")
DEFAULT_COLLECTIONS = Path(
    "data/neurovault/cache/search_27c2e0f787a6e138fa382d983e396a25.json"
)
DEFAULT_OUT_JSON = Path("data/neurovault/cache/neurovault_images_filtered.json")
DEFAULT_OUT_IDS = Path("data/neurovault/cache/neurovault_image_ids_filtered.txt")

ALLOWED_MAP_TYPES = {"T map", "Z map", "F map", "T", "Z", "F"}
ALLOWED_MODALITY = "fMRI-BOLD"
ALLOWED_ANALYSIS = {None, "", "group", "study"}
EXCLUDE_NAME_TOKENS = {"temporary collection", "test collection", "sandbox", "tmp", "test"}


def load_json(path: Path) -> Any:
    with path.open("r") as f:
        return json.load(f)


def _normalize_images(obj: Any) -> list[dict]:
    if isinstance(obj, dict):
        if "statistical_maps" in obj:
            return obj["statistical_maps"]
        if "images" in obj:
            return obj["images"]
    if isinstance(obj, Sequence):
        return list(obj)
    raise ValueError("Unrecognized images JSON structure")


def _normalize_collections(obj: Any) -> list[dict]:
    if isinstance(obj, dict) and "collections" in obj:
        return obj["collections"]
    if isinstance(obj, Sequence):
        return list(obj)
    raise ValueError("Unrecognized collections JSON structure")


def want_collection(coll: dict) -> bool:
    name = (coll.get("name") or "").lower()
    if any(tok in name for tok in EXCLUDE_NAME_TOKENS):
        return False
    if coll.get("number_of_images", 0) <= 0:
        return False
    return True


def want_image(img: dict, good_collection_ids: set[int]) -> bool:
    if img.get("collection_id") not in good_collection_ids:
        return False

    mt = (img.get("map_type") or "").strip()
    if mt not in ALLOWED_MAP_TYPES:
        return False

    modality = (img.get("modality") or "").strip()
    if modality != ALLOWED_MODALITY:
        return False

    if img.get("is_thresholded") is True:
        return False

    # Keep MNI if unknown; drop only explicit False / not_mni flag
    if img.get("in_mni_space") is False:
        return False
    if img.get("not_mni") is True:
        return False

    level = (img.get("analysis_level") or "").strip().lower() or None
    if level not in ALLOWED_ANALYSIS:
        return False

    return True


def filter_inventories(
    images: Iterable[dict], collections: Iterable[dict]
) -> tuple[list[dict], list[int]]:
    good_cols = {c["id"] for c in collections if want_collection(c)}
    filtered_images: list[dict] = []
    filtered_ids: list[int] = []

    for img in images:
        if want_image(img, good_cols):
            filtered_images.append(img)
            filtered_ids.append(int(img["id"]))

    return filtered_images, filtered_ids


def write_outputs(images: list[dict], ids: list[int], out_json: Path, out_ids: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"statistical_maps": images}, indent=2))
    with out_ids.open("w") as f:
        for _id in ids:
            f.write(f"{_id}\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Filter NeuroVault cached inventories")
    p.add_argument("--images", type=Path, default=DEFAULT_IMAGES, help="Path to images inventory JSON")
    p.add_argument("--collections", type=Path, default=DEFAULT_COLLECTIONS, help="Path to collections JSON")
    p.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON, help="Output filtered images JSON")
    p.add_argument("--out-ids", type=Path, default=DEFAULT_OUT_IDS, help="Output image IDs list")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    img_data = load_json(args.images)
    col_data = load_json(args.collections)

    images = _normalize_images(img_data)
    collections = _normalize_collections(col_data)

    filtered_images, filtered_ids = filter_inventories(images, collections)

    print(f"Collections: {len(collections)} total -> {len({c['id'] for c in collections if want_collection(c)})} kept")
    print(f"Images: {len(images)} total -> {len(filtered_images)} kept")

    write_outputs(filtered_images, filtered_ids, args.out_json, args.out_ids)
    print(f"Wrote {len(filtered_images)} images to {args.out_json}")
    print(f"Wrote {len(filtered_ids)} IDs to {args.out_ids}")


if __name__ == "__main__":
    main()
