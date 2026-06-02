#!/usr/bin/env python3
"""Summarise OpenNeuro GLM FitLins maps with Yeo17 and ingest ROI edges."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

import nibabel as nib
from neo4j import GraphDatabase

from brain_researcher.core.ingestion.loaders.openneuro_glm_loader import (
    OpenNeuroGLMFitlinsLoader,
    SOURCE_NAME,
)
from brain_researcher.services.br_kg.etl.yeo17_features import (
    Yeo17Feature,
    compute_features,
    resolve_label_and_template,
)
from brain_researcher.services.br_kg.etl.yeo17_writer import (
    WriterConfig,
    write_sparse_edges,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("openneuro_glmfitlins_yeo17")

YEO17_LABELS = {
    1: "VisCent",
    2: "VisPeri",
    3: "SomMotA",
    4: "SomMotB",
    5: "DorsAttnA",
    6: "DorsAttnB",
    7: "SalVentAttnA",
    8: "SalVentAttnB",
    9: "LimbicA",
    10: "LimbicB",
    11: "ContA",
    12: "ContB",
    13: "ContC",
    14: "DefaultA",
    15: "DefaultB",
    16: "DefaultC",
    17: "TempPar",
}


def _ensure_yeo17_nodes(config: WriterConfig) -> None:
    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    try:
        with driver.session(database=config.database) as session:
            session.run(
                """
                MERGE (p:Parcellation {id: $atlas_id})
                ON CREATE SET p.name = $atlas_name
                """,
                atlas_id="atlas:yeo2011_17",
                atlas_name="Yeo17",
            )
            for label, name in YEO17_LABELS.items():
                region_id = f"yeo17:{label:02d}"
                session.run(
                    """
                    MERGE (r:BrainRegion {id: $id})
                    SET r.name = $name,
                        r.atlas = $atlas,
                        r.label_index = $label,
                        r.space = $space
                    MERGE (r)-[:IN_PARCELLATION]->(p:Parcellation {id: $atlas_id})
                    """,
                    id=region_id,
                    name=name,
                    atlas="Yeo17",
                    label=label,
                    space="MNI152",
                    atlas_id="atlas:yeo2011_17",
                )
    finally:
        driver.close()


def _load_manifest(
    datasets_root: Path,
    manifest_path: Path,
) -> Iterable:
    loader = OpenNeuroGLMFitlinsLoader(
        datasets_root=datasets_root,
        manifest_path=manifest_path,
    )
    return loader.discover()


def _load_image(path: Path) -> Optional[nib.Nifti1Image]:
    if not path.exists():
        return None
    try:
        return nib.load(str(path))
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to load %s: %s", path, exc)
        return None


def _existing_map_ids(summary_path: Path) -> set[str]:
    if not summary_path.exists():
        return set()
    existing: set[str] = set()
    with summary_path.open("r", newline="") as fp:
        reader = csv.DictReader(fp)
        if "map_id" not in reader.fieldnames:
            return set()
        for row in reader:
            if row.get("map_id"):
                existing.add(row["map_id"])
    return existing


def _parse_float(value: Optional[str], default: Optional[float] = 0.0) -> Optional[float]:
    if value is None:
        return default
    value = value.strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _parse_int(value: Optional[str], default: int = 0) -> int:
    if value is None:
        return default
    value = value.strip()
    if not value:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def _iter_summary_groups(
    summary_path: Path,
) -> Iterable[tuple[str, Optional[str], list[Yeo17Feature]]]:
    if not summary_path.exists():
        raise FileNotFoundError(summary_path)

    groups: dict[str, dict[str, object]] = defaultdict(
        lambda: {"space": None, "features": {}}
    )
    skipped_rows = 0
    skipped_metric = 0
    with summary_path.open("r", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            parcellation = (row.get("parcellation") or "").strip().lower()
            if parcellation and parcellation != "yeo17":
                continue
            metric = (row.get("metric") or "").strip().lower()
            if metric and metric != "mean_z":
                skipped_metric += 1
                continue

            map_id = (row.get("map_id") or "").strip()
            region_id = (row.get("region_id") or "").strip()
            if not map_id or not region_id:
                skipped_rows += 1
                continue

            weight = _parse_float(row.get("value"), None)
            if weight is None:
                skipped_rows += 1
                continue

            pct_active = _parse_float(row.get("pct_active"), 0.0)
            n_vox = _parse_int(row.get("n_vox"), 0)
            z_thr = _parse_float(row.get("z_thr"), 0.0)
            space = (row.get("space") or "").strip() or None

            group = groups[map_id]
            if group["space"] is None and space:
                group["space"] = space
            features = group["features"]
            assert isinstance(features, dict)
            features[region_id] = (
                Yeo17Feature(
                    region_id=region_id,
                    weight=weight,
                    pct_active=pct_active,
                    n_vox=n_vox,
                    z_thr=z_thr,
                )
            )

    if skipped_rows:
        logger.info("Skipped %d summary rows with missing values", skipped_rows)
    if skipped_metric:
        logger.info("Skipped %d summary rows with non-mean_z metric", skipped_metric)

    for map_id, group in groups.items():
        space = group["space"]
        features = group["features"]
        assert isinstance(features, dict)
        yield map_id, space if isinstance(space, str) else None, list(features.values())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--datasets-root",
        default="data/openneuro_glmfitlins",
        help="Root folder containing analyses/stat_maps.",
    )
    parser.add_argument(
        "--manifest",
        default="data/openneuro_glmfitlins/manifest/openneuro_glm_statsmaps.json",
        help="GLM FitLins stat map manifest.",
    )
    parser.add_argument(
        "--summaries-dir",
        default="data/openneuro_glmfitlins/summaries",
        help="Directory to write summary CSV.",
    )
    parser.add_argument(
        "--summary-path",
        default=None,
        help="Explicit summary CSV path (defaults to summaries-dir/yeo17_summary.csv).",
    )
    parser.add_argument(
        "--from-summary",
        action="store_true",
        help="Ingest ROI edges from an existing summary CSV.",
    )
    parser.add_argument(
        "--neuromaps-root",
        default="data/br-kg/raw/nilearn_atlases",
        help="Directory holding Yeo/Nilearn assets.",
    )
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="password")
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--top-k", type=int, default=17)
    parser.add_argument("--z-thr", type=float, default=2.3)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--skip-write-edges", action="store_true")
    parser.add_argument("--skip-summary", action="store_true")
    parser.add_argument("--skip-ensure-atlas", action="store_true")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> None:
    args = build_arg_parser().parse_args(argv)

    datasets_root = Path(args.datasets_root).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    summaries_dir = Path(args.summaries_dir).expanduser().resolve()
    summaries_dir.mkdir(parents=True, exist_ok=True)

    summary_path = summaries_dir / "yeo17_summary.csv"
    if args.summary_path:
        summary_path = Path(args.summary_path).expanduser().resolve()
    resume_map_ids = set()
    if not args.no_resume:
        resume_map_ids = _existing_map_ids(summary_path)

    writer_config = WriterConfig(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password,
        database=args.neo4j_database,
    )

    if not args.skip_ensure_atlas:
        _ensure_yeo17_nodes(writer_config)

    if args.from_summary:
        if not summary_path.exists():
            logger.error("Summary file not found: %s", summary_path)
            sys.exit(1)

        processed = 0
        edges_written = 0
        skipped = 0

        for map_id, template_space, features in _iter_summary_groups(summary_path):
            if not features:
                skipped += 1
                continue
            if not args.skip_write_edges:
                edges_written += write_sparse_edges(
                    config=writer_config,
                    map_id=map_id,
                    map_source=SOURCE_NAME,
                    template_space=template_space,
                    edge_source=SOURCE_NAME,
                    features=features,
                    top_k=args.top_k,
                    etl_version="yeo17_v1",
                )
            processed += 1
            if processed % 50 == 0:
                logger.info(
                    "Processed %d maps (skipped=%d, edges=%d)",
                    processed,
                    skipped,
                    edges_written,
                )

        logger.info(
            "Done. processed=%d skipped=%d edges_written=%d summary=%s",
            processed,
            skipped,
            edges_written,
            summary_path,
        )
        return

    assets = resolve_label_and_template(Path(args.neuromaps_root))
    label_img = assets.load_label()

    records = list(_load_manifest(datasets_root, manifest_path))
    if args.limit:
        records = records[: args.limit]
    logger.info("Processing %d stat maps", len(records))

    if args.skip_summary:
        writer = None
    else:
        needs_header = not summary_path.exists() or summary_path.stat().st_size == 0
        writer = summary_path.open("a", newline="")
        csv_writer = csv.writer(writer)
        if needs_header:
            csv_writer.writerow(
                [
                    "dataset_id",
                    "task",
                    "contrast",
                    "level",
                    "stat",
                    "space",
                    "parcellation",
                    "metric",
                    "region_id",
                    "value",
                    "pct_active",
                    "n_vox",
                    "z_thr",
                    "map_id",
                    "map_path",
                ]
            )

    processed = 0
    edges_written = 0
    skipped = 0

    for row in records:
        map_id = row.statsmap_id()
        if map_id in resume_map_ids:
            skipped += 1
            continue

        img = _load_image(row.path)
        if img is None:
            skipped += 1
            continue

        try:
            features = compute_features(
                map_img=img,
                label_img=label_img,
                z_threshold=args.z_thr,
            )
        except Exception as exc:  # pragma: no cover - nibabel edge cases
            logger.warning("Failed to compute features for %s: %s", map_id, exc)
            skipped += 1
            continue

        if not args.skip_write_edges:
            edges_written += write_sparse_edges(
                config=writer_config,
                map_id=map_id,
                map_source=SOURCE_NAME,
                template_space=row.space,
                edge_source=SOURCE_NAME,
                features=features,
                top_k=args.top_k,
                etl_version="yeo17_v1",
            )

        if writer is not None:
            for feature in features:
                csv_writer.writerow(
                    [
                        row.dataset_id,
                        row.task,
                        row.contrast,
                        row.level,
                        row.stat,
                        row.space,
                        "yeo17",
                        "mean_z",
                        feature.region_id,
                        feature.weight,
                        feature.pct_active,
                        feature.n_vox,
                        feature.z_thr,
                        map_id,
                        str(row.path),
                    ]
                )
            writer.flush()

        processed += 1
        if processed % 25 == 0:
            logger.info(
                "Processed %d/%d (skipped=%d, edges=%d)",
                processed,
                len(records),
                skipped,
                edges_written,
            )

    if writer is not None:
        writer.close()

    logger.info(
        "Done. processed=%d skipped=%d edges_written=%d summary=%s",
        processed,
        skipped,
        edges_written,
        summary_path,
    )


if __name__ == "__main__":
    main()
