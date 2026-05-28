#!/usr/bin/env python3
"""
Fetch a fresh NeuroVault metadata inventory (no NIfTI downloads).

This hits the public NeuroVault API with pagination and writes:
  data/neurovault/cache/neurovault_images_raw.json

Only metadata is downloaded; files are not fetched. You can then run
scripts/tools/etl/neurovault_filter.py on the raw snapshot to produce the filtered set.

Usage (from repo root):
  python scripts/tools/etl/neurovault_fetch_inventory.py --max-images 200000

Flags:
  --max-images   cap number of images (default: 50000, set to 0 for no cap)
  --page-size    API page size (<= 200)
  --dest         output path (default: data/neurovault/cache/neurovault_images_raw.json)
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List

import requests
from requests.exceptions import ReadTimeout, ConnectionError as ReqConnectionError

log = logging.getLogger("neurovault_fetch_inventory")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BASE = "https://neurovault.org/api/images/"


def fetch_page(url: str, params: dict[str, Any], *, retries: int = 5, backoff: float = 2.0) -> dict[str, Any]:
    attempt = 0
    while True:
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (ReadTimeout, ReqConnectionError, requests.HTTPError) as e:
            attempt += 1
            if attempt > retries:
                log.error("Giving up after %s retries on %s: %s", retries, url, e)
                raise
            sleep = backoff * attempt
            log.warning("Request failed (attempt %s/%s): %s; retrying in %.1fs", attempt, retries, e, sleep)
            import time

            time.sleep(sleep)


def _fetch_parallel(max_images: int, page_size: int, start_offset: int, max_workers: int) -> List[dict]:
    offsets = list(range(start_offset, start_offset + max_images, page_size))
    params_template = {
        "format": "json",
        "file_type": "nii.gz",
        "limit": page_size,
    }
    batches: Dict[int, list[dict]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fetch_page, BASE, {**params_template, "offset": offset}): offset
            for offset in offsets
        }
        for future in as_completed(futures):
            offset = futures[future]
            data = future.result()
            batch = data.get("results", [])
            batches[offset] = batch
            log.info("Fetched offset %s (+%s images)", offset, len(batch))

    images: list[dict] = []
    for offset in offsets:
        images.extend(batches.get(offset, []))
        if len(images) >= max_images:
            images = images[:max_images]
            break
    return images


def fetch_all(
    max_images: int,
    page_size: int,
    start_offset: int = 0,
    *,
    max_workers: int = 1,
) -> List[dict]:
    if max_workers > 1 and max_images > 0:
        return _fetch_parallel(max_images, page_size, start_offset, max_workers)

    images: list[dict] = []
    url = BASE
    params = {
        "format": "json",
        "file_type": "nii.gz",
        "limit": page_size,
        "offset": start_offset,
    }

    while url:
        data = fetch_page(url, params if url == BASE else {})
        results = data.get("results", [])
        images.extend(results)

        if max_images and len(images) >= max_images:
            images = images[:max_images]
            break

        url = data.get("next")
        if url:
            log.info("Fetched %d images; next page: %s", len(images), url)

    return images


def dedupe_by_id(images: List[dict]) -> List[dict]:
    seen = set()
    deduped = []
    for img in images:
        iid = img.get("id")
        if iid in seen:
            continue
        seen.add(iid)
        deduped.append(img)
    return deduped


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch NeuroVault image metadata inventory")
    ap.add_argument("--max-images", type=int, default=50000, help="Max images to fetch (0 = all)")
    ap.add_argument(
        "--page-size",
        type=int,
        default=200,
        help="Page size per API call (<=1000; NeuroVault caps requests at ~1000)",
    )
    ap.add_argument(
        "--dest",
        type=Path,
        default=Path("data/neurovault/cache/neurovault_images_raw.json"),
        help="Output JSON path",
    )
    ap.add_argument(
        "--start-offset",
        type=int,
        default=0,
        help="Initial API offset (use to resume chunked fetches)",
    )
    ap.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Parallel requests to issue (1 = sequential). Only used when --max-images > 0.",
    )
    args = ap.parse_args()

    max_images = args.max_images if args.max_images > 0 else 0
    page_size = max(1, min(args.page_size, 1000))
    max_workers = max(1, min(args.max_workers, 16))

    log.info(
        (
            "Fetching NeuroVault metadata: max_images=%s page_size=%s "
            "start_offset=%s workers=%s"
        ),
        max_images or "all",
        page_size,
        args.start_offset,
        max_workers,
    )
    images = fetch_all(
        max_images,
        page_size,
        start_offset=args.start_offset,
        max_workers=max_workers,
    )
    log.info("Fetched %d rows", len(images))

    deduped = dedupe_by_id(images)
    if len(deduped) != len(images):
        log.info("Deduped by id: %d unique out of %d", len(deduped), len(images))

    args.dest.parent.mkdir(parents=True, exist_ok=True)
    args.dest.write_text(json.dumps({"statistical_maps": deduped}, indent=2))
    log.info("Wrote %d unique images to %s", len(deduped), args.dest)

    if deduped:
        ids = [d["id"] for d in deduped if "id" in d]
        log.info("ID range: min=%s max=%s", min(ids), max(ids))


if __name__ == "__main__":
    main()
