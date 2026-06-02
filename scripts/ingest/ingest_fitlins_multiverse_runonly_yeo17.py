#!/usr/bin/env python3
"""Summarise FitLins multiverse run-level maps with Yeo17 and emit ingestion artifacts.

This is intended for "run-only" multiverse demos where we deliberately drop
dataset-level nodes to avoid second-level failures when running a single subject
or session.

Outputs:
- A summary CSV with per-region mean_z (and pct_active) for each z-map, plus
  mean/std beta for effect maps when available.
- An edges CSV that can be imported into Neo4j to create/merge IN_REGION edges.
- A compact robustness report (JSON + Markdown) aggregating Yeo17 profiles across
  multiverse variants.

Note: If the statistical maps are not in MNI space, the Yeo17 summaries are only
useful as a pipeline demo. For scientific use you should first warp maps into an
MNI template space before parcellation.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import nibabel as nib
import numpy as np
import SimpleITK as sitk
from neo4j import GraphDatabase

from brain_researcher.services.br_kg.etl.yeo17_features import (
    Yeo17Feature,
    compute_features,
    resolve_label_and_template,
)
from brain_researcher.services.br_kg.spatial.neuromaps_assets import (
    preferred_neuromaps_root,
)
from brain_researcher.services.br_kg.etl.yeo17_writer import (
    WriterConfig,
    write_sparse_edges,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fitlins_multiverse_runonly_yeo17")


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


MAP_RE = re.compile(
    r"^(?P<subject>sub-[^_]+)_(?P<session>ses-[^_]+)_contrast-(?P<contrast>[^_]+)_stat-(?P<stat>[^_]+)_statmap\.nii(\.gz)?$"
)


@dataclass(frozen=True)
class MapRecord:
    model_id: str
    subject: str
    session: str
    contrast: str
    stat: str
    path: Path


def _resolve_fmriprep_dir(
    dataset_id: str, *, explicit: Optional[str]
) -> Optional[Path]:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        return candidate if candidate.exists() else None

    default = (
        Path("/app/data/openneuro")
        / dataset_id
        / "derivatives"
        / "fmriprep"
        / f"{dataset_id}-fmriprep"
    )
    if default.exists():
        return default.resolve()
    return None


def _resolve_transforms(
    *,
    fmriprep_dir: Path,
    subject: str,
    session: str,
    task: str,
) -> tuple[Path, Path]:
    scanner_to_t1w = (
        fmriprep_dir
        / subject
        / session
        / "func"
        / f"{subject}_{session}_task-{task}_from-scanner_to-T1w_mode-image_xfm.txt"
    )
    if not scanner_to_t1w.exists():
        raise FileNotFoundError(scanner_to_t1w)

    t1w_to_mni_2009 = (
        fmriprep_dir
        / subject
        / "anat"
        / f"{subject}_from-T1w_to-MNI152NLin2009cAsym_mode-image_xfm.h5"
    )
    t1w_to_mni_6 = (
        fmriprep_dir
        / subject
        / "anat"
        / f"{subject}_from-T1w_to-MNI152NLin6Asym_mode-image_xfm.h5"
    )
    if t1w_to_mni_2009.exists():
        return scanner_to_t1w, t1w_to_mni_2009
    if t1w_to_mni_6.exists():
        return scanner_to_t1w, t1w_to_mni_6
    raise FileNotFoundError(t1w_to_mni_2009)


def _compute_features_in_yeo_space(
    *,
    map_path: Path,
    label_img: sitk.Image,
    mask_idx: np.ndarray,
    label_values: np.ndarray,
    label_counts: np.ndarray,
    z_thr: float,
    transforms: tuple[sitk.Transform, sitk.Transform],
) -> list[Yeo17Feature]:
    moving = sitk.ReadImage(str(map_path), sitk.sitkFloat32)

    # CompositeTransform applies in reverse order of addition. We want:
    # scanner -> T1w -> MNI, so add MNI transform first, then scanner->T1w.
    comp = sitk.CompositeTransform(3)
    t_scanner_to_t1w, t_t1w_to_mni = transforms
    comp.AddTransform(t_t1w_to_mni)
    comp.AddTransform(t_scanner_to_t1w)

    resampled = sitk.Resample(
        moving, label_img, comp, sitk.sitkLinear, 0.0, sitk.sitkFloat32
    )
    data = sitk.GetArrayFromImage(resampled).astype(np.float32, copy=False)
    if data.ndim != 3:
        data = np.squeeze(data)

    values = data.reshape(-1)[mask_idx]
    sums = np.bincount(label_values, weights=values, minlength=18)
    active = np.bincount(
        label_values,
        weights=(values >= float(z_thr)).astype(np.float32),
        minlength=18,
    )

    rows: list[Yeo17Feature] = []
    for label in range(1, 18):
        n_vox = int(label_counts[label])
        if n_vox == 0:
            continue
        mean_z = float(sums[label] / n_vox)
        pct_active = float(active[label] / n_vox)
        rows.append(
            Yeo17Feature(
                region_id=f"yeo17:{label:02d}",
                weight=mean_z,
                pct_active=pct_active,
                n_vox=n_vox,
                z_thr=float(z_thr),
            )
        )
    return rows


@dataclass(frozen=True)
class EffectFeature:
    region_id: str
    mean: float
    std: float
    n_vox: int


def _compute_effect_stats(
    values: np.ndarray,
    label_values: np.ndarray,
    label_counts: np.ndarray,
) -> list[EffectFeature]:
    sums = np.bincount(label_values, weights=values, minlength=18)
    sums_sq = np.bincount(label_values, weights=values**2, minlength=18)
    rows: list[EffectFeature] = []
    for label in range(1, 18):
        n_vox = int(label_counts[label])
        if n_vox == 0:
            continue
        mean = float(sums[label] / n_vox)
        var = float(sums_sq[label] / n_vox - mean**2)
        std = float(np.sqrt(max(var, 0.0)))
        rows.append(
            EffectFeature(
                region_id=f"yeo17:{label:02d}",
                mean=mean,
                std=std,
                n_vox=n_vox,
            )
        )
    return rows


def _compute_effect_in_yeo_space(
    *,
    map_path: Path,
    label_img: sitk.Image,
    mask_idx: np.ndarray,
    label_values: np.ndarray,
    label_counts: np.ndarray,
    transforms: tuple[sitk.Transform, sitk.Transform],
) -> list[EffectFeature]:
    moving = sitk.ReadImage(str(map_path), sitk.sitkFloat32)
    comp = sitk.CompositeTransform(3)
    t_scanner_to_t1w, t_t1w_to_mni = transforms
    comp.AddTransform(t_t1w_to_mni)
    comp.AddTransform(t_scanner_to_t1w)

    resampled = sitk.Resample(
        moving, label_img, comp, sitk.sitkLinear, 0.0, sitk.sitkFloat32
    )
    data = sitk.GetArrayFromImage(resampled).astype(np.float32, copy=False)
    if data.ndim != 3:
        data = np.squeeze(data)

    values = data.reshape(-1)[mask_idx]
    return _compute_effect_stats(values, label_values, label_counts)


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


def _parse_manifest(path: Path) -> tuple[Optional[str], Optional[str], dict[str, dict]]:
    if not path.exists():
        return None, None, {}
    data = json.loads(path.read_text())
    variants = data.get("variants", [])
    by_model: dict[str, dict] = {}
    for row in variants:
        model_id = row.get("model_id")
        if model_id:
            by_model[str(model_id)] = row
    return data.get("dataset_id"), data.get("task"), by_model


def _iter_maps(run_base: Path, *, stat: str) -> Iterable[MapRecord]:
    for mv_dir in sorted(run_base.glob("mv*")):
        if not mv_dir.is_dir():
            continue
        model_id = mv_dir.name
        node_dir = mv_dir / "node-runLevel"
        if not node_dir.exists():
            continue
        for map_path in node_dir.rglob(f"*_stat-{stat}_statmap.nii*"):
            match = MAP_RE.match(map_path.name)
            if not match:
                continue
            yield MapRecord(
                model_id=model_id,
                subject=match.group("subject"),
                session=match.group("session"),
                contrast=match.group("contrast"),
                stat=match.group("stat"),
                path=map_path,
            )


def _map_id(
    *,
    dataset_id: str,
    task: str,
    model_id: str,
    variant_id: Optional[str],
    subject: str,
    session: str,
    contrast: str,
    stat: str,
) -> str:
    vid = variant_id or "no_variant_id"
    # Keep IDs stable and human-greppable.
    return (
        "multiverse_fitlins_runonly:"
        f"{dataset_id}:{task}:{model_id}:{vid}:{subject}:{session}:contrast-{contrast}:stat-{stat}"
    )


def _write_edges_csv_row(
    writer: csv.DictWriter,
    *,
    map_id: str,
    map_source: str,
    template_space: Optional[str],
    edge_source: str,
    etl_version: str,
    feature,
) -> None:
    writer.writerow(
        {
            "map_id": map_id,
            "map_source": map_source,
            "template_space": template_space or "",
            "edge_source": edge_source,
            "region_id": feature.region_id,
            "weight": feature.weight,
            "pct_active": feature.pct_active,
            "n_vox": feature.n_vox,
            "z_thr": feature.z_thr,
            "etl_version": etl_version,
            "expires_at_epoch": "",
        }
    )


def _write_import_cypher(*, edges_csv_name: str, out_path: Path) -> None:
    out_path.write_text(
        "\n".join(
            [
                "// Import Yeo17 IN_REGION edges for multiverse FitLins run-only maps.",
                "// 1) Copy the CSV into Neo4j's import directory.",
                "// 2) Run this Cypher in Neo4j Browser or cypher-shell.",
                "",
                f"LOAD CSV WITH HEADERS FROM 'file:///{edges_csv_name}' AS row",
                "WITH row WHERE row.map_id IS NOT NULL AND row.region_id IS NOT NULL",
                "MERGE (p:Parcellation {id: 'atlas:yeo2011_17'})",
                "  ON CREATE SET p.name = 'Yeo17'",
                "MERGE (m:StatsMap {id: row.map_id})",
                "  ON CREATE SET m.source = row.map_source,",
                "                m.template_space = CASE row.template_space WHEN '' THEN NULL ELSE row.template_space END",
                "MERGE (r:BrainRegion {id: row.region_id})",
                "MERGE (r)-[:IN_PARCELLATION]->(p)",
                "MERGE (m)-[edge:IN_REGION {atlas: 'yeo17', edge_source: row.edge_source}]->(r)",
                "SET edge.measure = 'mean_z',",
                "    edge.weight = toFloat(row.weight),",
                "    edge.pct_active = toFloat(row.pct_active),",
                "    edge.n_vox = toInteger(row.n_vox),",
                "    edge.z_thr = toFloat(row.z_thr),",
                "    edge.etl_version = row.etl_version;",
                "",
            ]
        )
    )


def _aggregate_metric(
    *,
    rows: list[dict[str, str]],
    metric: str,
    region_ids: list[str],
) -> dict[str, dict]:
    by_contrast: dict[str, dict[str, dict[str, float]]] = {}
    for row in rows:
        if (row.get("metric") or "").strip().lower() != metric:
            continue
        contrast = (row.get("contrast") or "").strip()
        model_id = (row.get("model_id") or "").strip()
        region_id = (row.get("region_id") or "").strip()
        if not contrast or not model_id or not region_id:
            continue
        try:
            value = float(row.get("value") or "0")
        except ValueError:
            continue
        by_contrast.setdefault(contrast, {}).setdefault(model_id, {})[region_id] = value

    contrast_reports: dict[str, dict] = {}
    for contrast, model_map in sorted(by_contrast.items()):
        model_ids = sorted(model_map.keys())
        if not model_ids:
            continue

        mat = np.zeros((len(model_ids), len(region_ids)), dtype=np.float32)
        for i, mid in enumerate(model_ids):
            vec = model_map.get(mid, {})
            for j, rid in enumerate(region_ids):
                mat[i, j] = float(vec.get(rid, 0.0))

        corr_mean = None
        corr_min = None
        if len(model_ids) >= 2:
            corr = np.corrcoef(mat)
            iu = np.triu_indices_from(corr, k=1)
            vals = corr[iu]
            if vals.size:
                corr_mean = float(np.nanmean(vals))
                corr_min = float(np.nanmin(vals))

        region_stats: list[dict] = []
        for j, rid in enumerate(region_ids):
            vals = mat[:, j]
            mean = float(np.mean(vals))
            std = float(np.std(vals))
            pos = float(np.mean(vals > 0))
            neg = float(np.mean(vals < 0))
            sign_consistency = float(max(pos, neg))
            label_index = int(rid.split(":")[1])
            region_stats.append(
                {
                    "region_id": rid,
                    "region_name": YEO17_LABELS.get(label_index),
                    "mean": mean,
                    "std": std,
                    "pos_frac": pos,
                    "neg_frac": neg,
                    "sign_consistency": sign_consistency,
                }
            )

        top_regions = sorted(
            region_stats, key=lambda r: abs(float(r["mean"])), reverse=True
        )[:5]

        contrast_reports[contrast] = {
            "n_variants": len(model_ids),
            "model_ids": model_ids,
            "pairwise_corr_mean": corr_mean,
            "pairwise_corr_min": corr_min,
            "top_regions_by_abs_mean": top_regions,
        }

    return contrast_reports


def _build_robustness_report(
    *,
    summary_path: Path,
    edges_path: Path,
    manifest_variants: dict[str, dict],
    out_json: Path,
    out_md: Path,
    warp_to_yeo_space: bool,
) -> None:
    rows: list[dict[str, str]] = []
    with summary_path.open("r", newline="") as fp:
        reader = csv.DictReader(fp)
        rows.extend(reader)

    region_ids = [f"yeo17:{i:02d}" for i in range(1, 18)]
    contrast_reports = _aggregate_metric(
        rows=rows, metric="mean_z", region_ids=region_ids
    )
    effect_reports = _aggregate_metric(
        rows=rows, metric="mean_beta", region_ids=region_ids
    )

    variant_meta: list[dict] = []
    for mid in sorted({row.get("model_id", "") for row in rows if row.get("model_id")}):
        src = manifest_variants.get(mid, {})
        variant_meta.append(
            {
                "model_id": mid,
                "variant_id": src.get("variant_id"),
                "hrf": src.get("hrf"),
                "confounds": src.get("confounds"),
                "high_pass": src.get("high_pass"),
                "confounds_families": src.get("confounds_families"),
            }
        )

    payload = {
        "summary_path": str(summary_path),
        "edges_path": str(edges_path),
        "variants": variant_meta,
        "contrasts": contrast_reports,
        "effect_size": effect_reports,
        "notes": {
            "warp_to_yeo_space": warp_to_yeo_space,
        },
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True))

    lines: list[str] = []
    lines.append("# Multiverse robustness (Yeo17)")
    lines.append("")
    lines.append(f"- summary: `{summary_path}`")
    lines.append(f"- edges: `{edges_path}`")
    lines.append(f"- variants: {len(variant_meta)}")
    lines.append("")
    for contrast, crep in contrast_reports.items():
        lines.append(f"## Contrast: {contrast}")
        lines.append(f"- n_variants: {crep['n_variants']}")
        if crep.get("pairwise_corr_mean") is not None:
            lines.append(f"- pairwise_corr_mean: {crep['pairwise_corr_mean']:.3f}")
            lines.append(f"- pairwise_corr_min: {crep['pairwise_corr_min']:.3f}")
        lines.append("- top_regions_by_abs_mean:")
        for row in crep["top_regions_by_abs_mean"]:
            lines.append(
                f"  - {row['region_id']} {row.get('region_name')}: "
                f"mean={row['mean']:.3f} std={row['std']:.3f} sign_consistency={row['sign_consistency']:.2f}"
            )
        lines.append("")
    if effect_reports:
        lines.append("# Effect size (beta)")
        lines.append("")
        for contrast, crep in effect_reports.items():
            lines.append(f"## Contrast: {contrast}")
            lines.append(f"- n_variants: {crep['n_variants']}")
            if crep.get("pairwise_corr_mean") is not None:
                lines.append(f"- pairwise_corr_mean: {crep['pairwise_corr_mean']:.3f}")
                lines.append(f"- pairwise_corr_min: {crep['pairwise_corr_min']:.3f}")
            lines.append("- top_regions_by_abs_mean:")
            for row in crep["top_regions_by_abs_mean"]:
                lines.append(
                    f"  - {row['region_id']} {row.get('region_name')}: "
                    f"mean={row['mean']:.4f} std={row['std']:.4f} sign_consistency={row['sign_consistency']:.2f}"
                )
            lines.append("")
    lines.append("## Notes")
    if warp_to_yeo_space:
        lines.append(
            "- Maps were warped into Yeo17 (MNI) label space using fMRIPrep transforms."
        )
    else:
        lines.append(
            "- WARNING: Maps were not warped into MNI; Yeo17 summaries may be invalid (demo only)."
        )
    out_md.write_text("\n".join(lines))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-base",
        default="outputs/_a4_ds000114_linebisection/fitlins_linear_runonly2",
        help="Folder containing mvXX FitLins outputs (each with node-runLevel/* maps).",
    )
    parser.add_argument(
        "--manifest",
        default="outputs/_a4_ds000114_linebisection/multiverse_manifest.json",
        help="Multiverse manifest with variant_id + decision points.",
    )
    parser.add_argument("--dataset-id", default=None)
    parser.add_argument("--task", default=None)
    parser.add_argument(
        "--stat", default="z", help="Stat suffix to summarise (default: z)."
    )
    parser.add_argument(
        "--effect-stat",
        default="effect",
        help="Stat suffix for effect-size summaries (default: effect).",
    )
    parser.add_argument("--top-k", type=int, default=17)
    parser.add_argument("--z-thr", type=float, default=2.3)
    parser.add_argument(
        "--warp-to-yeo-space",
        action="store_true",
        help=(
            "Warp run-level maps into the Yeo17 (MNI) label space using fMRIPrep transforms "
            "before computing region summaries."
        ),
    )
    parser.add_argument(
        "--fmriprep-dir",
        default=None,
        help=(
            "Path to fMRIPrep derivatives root (e.g., .../ds000114-fmriprep). "
            "If omitted, tries /app/data/openneuro/<ds>/derivatives/fmriprep/<ds>-fmriprep."
        ),
    )
    parser.add_argument(
        "--neuromaps-root",
        default=str(preferred_neuromaps_root()),
        help="Directory holding Yeo/Nilearn assets.",
    )
    parser.add_argument(
        "--summary-path",
        default=None,
        help="Explicit summary CSV path (defaults to <run-base>/yeo17_summary.csv).",
    )
    parser.add_argument(
        "--edges-path",
        default=None,
        help="Explicit edges CSV path (defaults to <run-base>/yeo17_edges.csv).",
    )
    parser.add_argument(
        "--robustness-json",
        default=None,
        help="Explicit robustness JSON path (defaults to <run-base>/robustness_yeo17.json).",
    )
    parser.add_argument(
        "--robustness-md",
        default=None,
        help="Explicit robustness Markdown path (defaults to <run-base>/robustness_yeo17.md).",
    )
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="password")
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument(
        "--skip-neo4j",
        action="store_true",
        help="Skip writing edges to Neo4j (still writes edges CSV).",
    )
    parser.add_argument(
        "--skip-ensure-atlas",
        action="store_true",
        help="Skip ensuring Yeo17 atlas nodes exist in Neo4j.",
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> None:
    args = build_arg_parser().parse_args(argv)

    run_base = Path(args.run_base).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    dataset_id, task, manifest_variants = _parse_manifest(manifest_path)
    dataset_id = args.dataset_id or dataset_id
    task = args.task or task
    if not dataset_id or not task:
        logger.error(
            "Missing dataset_id/task (pass --dataset-id/--task or provide --manifest)"
        )
        sys.exit(2)

    summary_path = run_base / "yeo17_summary.csv"
    if args.summary_path:
        summary_path = Path(args.summary_path).expanduser().resolve()
    edges_path = run_base / "yeo17_edges.csv"
    if args.edges_path:
        edges_path = Path(args.edges_path).expanduser().resolve()

    robustness_json = run_base / "robustness_yeo17.json"
    if args.robustness_json:
        robustness_json = Path(args.robustness_json).expanduser().resolve()
    robustness_md = run_base / "robustness_yeo17.md"
    if args.robustness_md:
        robustness_md = Path(args.robustness_md).expanduser().resolve()

    assets = resolve_label_and_template(Path(args.neuromaps_root))
    label_img = assets.load_label()

    label_img_sitk = None
    mask_idx = None
    label_values = None
    label_counts = None
    transforms_cache: dict[tuple[str, str], tuple[sitk.Transform, sitk.Transform]] = {}
    fmriprep_dir = None
    if args.warp_to_yeo_space:
        label_img_sitk = sitk.ReadImage(str(assets.label_img), sitk.sitkFloat32)
        labels = sitk.GetArrayFromImage(label_img_sitk).astype(np.int32, copy=False)
        if labels.ndim != 3:
            labels = np.squeeze(labels)
        labels_flat = labels.reshape(-1)
        mask = labels_flat > 0
        mask_idx = np.flatnonzero(mask)
        label_values = labels_flat[mask_idx]
        label_counts = np.bincount(label_values, minlength=18)
        fmriprep_dir = _resolve_fmriprep_dir(dataset_id, explicit=args.fmriprep_dir)
        if fmriprep_dir is None:
            logger.error(
                "Unable to resolve fmriprep-dir for %s; disable --warp-to-yeo-space or pass --fmriprep-dir",
                dataset_id,
            )
            sys.exit(2)
    else:
        labels = np.asarray(label_img.get_fdata(), dtype=np.int32)
        if labels.ndim == 4:
            labels = labels[..., 0]
        labels_flat = labels.reshape(-1)
        mask_idx = np.flatnonzero(labels_flat > 0)
        label_values = labels_flat[mask_idx]
        label_counts = np.bincount(label_values, minlength=18)

    writer_config = WriterConfig(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password,
        database=args.neo4j_database,
    )

    map_source = "multiverse_fitlins_runonly"
    edge_source = "multiverse_fitlins_runonly"
    etl_version = "yeo17_v1"

    neo4j_enabled = not args.skip_neo4j
    if neo4j_enabled and not args.skip_ensure_atlas:
        try:
            _ensure_yeo17_nodes(writer_config)
        except Exception as exc:
            logger.warning(
                "Neo4j atlas ensure failed; continuing without Neo4j writes: %s", exc
            )
            neo4j_enabled = False

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    edges_path.parent.mkdir(parents=True, exist_ok=True)

    with (
        summary_path.open("w", newline="") as summary_fp,
        edges_path.open("w", newline="") as edges_fp,
    ):
        summary_writer = csv.writer(summary_fp)
        summary_writer.writerow(
            [
                "dataset_id",
                "task",
                "model_id",
                "variant_id",
                "subject",
                "session",
                "contrast",
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

        edges_writer = csv.DictWriter(
            edges_fp,
            fieldnames=[
                "map_id",
                "map_source",
                "template_space",
                "edge_source",
                "region_id",
                "weight",
                "pct_active",
                "n_vox",
                "z_thr",
                "etl_version",
                "expires_at_epoch",
            ],
        )
        edges_writer.writeheader()

        processed = 0
        edges_written = 0
        neo4j_edges_written = 0
        skipped = 0

        for record in _iter_maps(run_base, stat=args.stat):
            model_meta = manifest_variants.get(record.model_id, {})
            variant_id = model_meta.get("variant_id")
            map_id = _map_id(
                dataset_id=dataset_id,
                task=task,
                model_id=record.model_id,
                variant_id=variant_id,
                subject=record.subject,
                session=record.session,
                contrast=record.contrast,
                stat=record.stat,
            )

            if args.warp_to_yeo_space:
                assert label_img_sitk is not None
                assert mask_idx is not None
                assert label_values is not None
                assert label_counts is not None
                assert fmriprep_dir is not None
                cache_key = (record.subject, record.session)
                if cache_key not in transforms_cache:
                    scanner_to_t1w_path, t1w_to_mni_path = _resolve_transforms(
                        fmriprep_dir=fmriprep_dir,
                        subject=record.subject,
                        session=record.session,
                        task=task,
                    )
                    transforms_cache[cache_key] = (
                        sitk.ReadTransform(str(scanner_to_t1w_path)),
                        sitk.ReadTransform(str(t1w_to_mni_path)),
                    )
                features = _compute_features_in_yeo_space(
                    map_path=record.path,
                    label_img=label_img_sitk,
                    mask_idx=mask_idx,
                    label_values=label_values,
                    label_counts=label_counts,
                    z_thr=args.z_thr,
                    transforms=transforms_cache[cache_key],
                )
            else:
                try:
                    img = nib.load(str(record.path))
                except Exception as exc:
                    logger.warning("Failed to load %s: %s", record.path, exc)
                    skipped += 1
                    continue

                try:
                    features = compute_features(
                        map_img=img, label_img=label_img, z_threshold=args.z_thr
                    )
                except Exception as exc:
                    logger.warning("Failed to compute features for %s: %s", map_id, exc)
                    skipped += 1
                    continue

            if not features:
                skipped += 1
                continue

            template_space = "MNI152" if args.warp_to_yeo_space else "unknown"

            # Write summary (all regions)
            for feature in features:
                summary_writer.writerow(
                    [
                        dataset_id,
                        task,
                        record.model_id,
                        variant_id or "",
                        record.subject,
                        record.session,
                        record.contrast,
                        record.stat,
                        template_space,
                        "yeo17",
                        "mean_z",
                        feature.region_id,
                        feature.weight,
                        feature.pct_active,
                        feature.n_vox,
                        feature.z_thr,
                        map_id,
                        str(record.path),
                    ]
                )

            # Write edges CSV (top-k)
            for feature in sorted(features, key=lambda f: f.weight, reverse=True)[
                : args.top_k
            ]:
                _write_edges_csv_row(
                    edges_writer,
                    map_id=map_id,
                    map_source=map_source,
                    template_space=template_space,
                    edge_source=edge_source,
                    etl_version=etl_version,
                    feature=feature,
                )
                edges_written += 1

            # Best-effort Neo4j write (may be unavailable in restricted sandboxes)
            if neo4j_enabled:
                try:
                    neo4j_edges_written += write_sparse_edges(
                        config=writer_config,
                        map_id=map_id,
                        map_source=map_source,
                        template_space=template_space,
                        edge_source=edge_source,
                        features=features,
                        top_k=args.top_k,
                        etl_version=etl_version,
                    )
                except Exception as exc:
                    logger.warning(
                        "Neo4j write failed; continuing without Neo4j writes: %s", exc
                    )
                    neo4j_enabled = False

            processed += 1
            if processed % 10 == 0:
                logger.info(
                    "Processed %d maps (skipped=%d edges_csv=%d edges_neo4j=%d)",
                    processed,
                    skipped,
                    edges_written,
                    neo4j_edges_written,
                )

        if args.effect_stat:
            for record in _iter_maps(run_base, stat=args.effect_stat):
                model_meta = manifest_variants.get(record.model_id, {})
                variant_id = model_meta.get("variant_id")
                map_id = _map_id(
                    dataset_id=dataset_id,
                    task=task,
                    model_id=record.model_id,
                    variant_id=variant_id,
                    subject=record.subject,
                    session=record.session,
                    contrast=record.contrast,
                    stat=record.stat,
                )

                try:
                    if args.warp_to_yeo_space:
                        assert label_img_sitk is not None
                        assert mask_idx is not None
                        assert label_values is not None
                        assert label_counts is not None
                        assert fmriprep_dir is not None
                        cache_key = (record.subject, record.session)
                        if cache_key not in transforms_cache:
                            scanner_to_t1w_path, t1w_to_mni_path = _resolve_transforms(
                                fmriprep_dir=fmriprep_dir,
                                subject=record.subject,
                                session=record.session,
                                task=task,
                            )
                            transforms_cache[cache_key] = (
                                sitk.ReadTransform(str(scanner_to_t1w_path)),
                                sitk.ReadTransform(str(t1w_to_mni_path)),
                            )
                        effect_features = _compute_effect_in_yeo_space(
                            map_path=record.path,
                            label_img=label_img_sitk,
                            mask_idx=mask_idx,
                            label_values=label_values,
                            label_counts=label_counts,
                            transforms=transforms_cache[cache_key],
                        )
                    else:
                        img = nib.load(str(record.path))
                        data = np.asarray(img.get_fdata(), dtype=np.float32)
                        if data.ndim == 4:
                            data = data[..., 0]
                        assert mask_idx is not None
                        assert label_values is not None
                        assert label_counts is not None
                        values = data.reshape(-1)[mask_idx]
                        effect_features = _compute_effect_stats(
                            values, label_values, label_counts
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to compute effect stats for %s: %s", map_id, exc
                    )
                    skipped += 1
                    continue

                template_space = "MNI152" if args.warp_to_yeo_space else "unknown"
                for feature in effect_features:
                    summary_writer.writerow(
                        [
                            dataset_id,
                            task,
                            record.model_id,
                            variant_id or "",
                            record.subject,
                            record.session,
                            record.contrast,
                            record.stat,
                            template_space,
                            "yeo17",
                            "mean_beta",
                            feature.region_id,
                            feature.mean,
                            0.0,
                            feature.n_vox,
                            0.0,
                            map_id,
                            str(record.path),
                        ]
                    )
                    summary_writer.writerow(
                        [
                            dataset_id,
                            task,
                            record.model_id,
                            variant_id or "",
                            record.subject,
                            record.session,
                            record.contrast,
                            record.stat,
                            template_space,
                            "yeo17",
                            "std_beta",
                            feature.region_id,
                            feature.std,
                            0.0,
                            feature.n_vox,
                            0.0,
                            map_id,
                            str(record.path),
                        ]
                    )

    import_cypher_path = edges_path.with_suffix(".cypher")
    _write_import_cypher(edges_csv_name=edges_path.name, out_path=import_cypher_path)

    _build_robustness_report(
        summary_path=summary_path,
        edges_path=edges_path,
        manifest_variants=manifest_variants,
        out_json=robustness_json,
        out_md=robustness_md,
        warp_to_yeo_space=args.warp_to_yeo_space,
    )

    logger.info("Done. summary=%s edges_csv=%s", summary_path, edges_path)
    logger.info("Neo4j import Cypher: %s", import_cypher_path)
    logger.info("Robustness report: %s (and %s)", robustness_json, robustness_md)
    if not neo4j_enabled:
        logger.info(
            "Neo4j writes were skipped/failed. Import %s manually with LOAD CSV.",
            edges_path,
        )


if __name__ == "__main__":
    main()
