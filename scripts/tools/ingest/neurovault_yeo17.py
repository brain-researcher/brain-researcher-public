#!/usr/bin/env python3
"""Attach sparse Yeo-17 edges to NeuroVault maps."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import nibabel as nib
import requests

from brain_researcher.services.br_kg.etl.yeo17_features import (
    compute_features,
    resolve_label_and_template,
)
from brain_researcher.services.br_kg.etl.yeo17_writer import (
    WriterConfig,
    write_sparse_edges,
)

logger = logging.getLogger(__name__)


def _load_manifest(path: Path) -> List[Dict[str, str]]:
    if path.suffix in {".json", ".jsonl"}:
        if path.suffix == ".jsonl":
            return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        return json.loads(path.read_text())

    rows: List[Dict[str, str]] = []
    with path.open("r", newline="") as fp:
        reader = csv.DictReader(fp)
        rows.extend(reader)
    return rows


def _resolve_map_uri(record: Dict[str, str]) -> str:
    for key in ("map_path", "map_uri", "url", "download_url"):
        value = record.get(key)
        if value:
            return value
    raise ValueError("Manifest row missing map URI/path")


def _load_image(uri: str, cache_dir: Path) -> nib.Nifti1Image:
    path = Path(uri)
    if path.exists():
        return nib.load(str(path))

    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(uri).suffix or ".nii.gz"
    tmp_path = cache_dir / f"download_{abs(hash(uri))}{suffix}"
    if not tmp_path.exists():
        logger.info("Downloading %s", uri)
        with requests.get(uri, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with tmp_path.open("wb") as fp:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    fp.write(chunk)
    return nib.load(str(tmp_path))


def ingest_manifest(
    *,
    manifest: Path,
    neuromaps_root: Path,
    writer_config: WriterConfig,
    top_k: int,
    z_thr: float,
    edge_source: str = "neurovault",
    dry_run: bool = False,
) -> None:
    rows = _load_manifest(manifest)
    logger.info("Loaded %d manifest rows", len(rows))

    assets = resolve_label_and_template(neuromaps_root)
    label_img = assets.load_label()

    temp_dir = Path(tempfile.gettempdir()) / "nv_maps"

    total_edges = 0
    for row in rows:
        uri = _resolve_map_uri(row)
        map_id = row.get("statsmap_id") or f"neurovault:{row.get(collection_id)}:{row.get(image_id)}"
        map_source = "neurovault"
        template_space = row.get("template_space") or "tpl:MNI152NLin2009cAsym_2mm"

        try:
            img = _load_image(uri, temp_dir)
            features = compute_features(
                map_img=img,
                label_img=label_img,
                z_threshold=z_thr,
            )
        except Exception as exc:  # pragma: no cover - nibabel edge cases
            logger.exception("Failed to process %s: %s", map_id, exc)
            continue

        if dry_run:
            logger.info("%s ⇒ %d features", map_id, len(features))
            continue

        written = write_sparse_edges(
            config=writer_config,
            map_id=map_id,
            map_source=map_source,
            template_space=template_space,
            edge_source=edge_source,
            features=features,
            top_k=top_k,
        )
        total_edges += written
        logger.info("%s ⇒ wrote %d edges (running total %d)", map_id, written, total_edges)

    logger.info("Finished. Total edges written: %d", total_edges)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="CSV or JSON manifest")
    parser.add_argument(
        "--neuromaps-root",
        type=Path,
        default=Path("data/br-kg/raw/nilearn_atlases"),
        help="Directory holding Yeo/Nilearn assets (falls back to nilearn download)",
    )
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="password")
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--z-thr", type=float, default=2.3)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)

    config = WriterConfig(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password,
        database=args.neo4j_database,
    )

    ingest_manifest(
        manifest=args.manifest,
        neuromaps_root=args.neuromaps_root,
        writer_config=config,
        top_k=args.top_k,
        z_thr=args.z_thr,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
