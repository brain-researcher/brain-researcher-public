#!/usr/bin/env python3
"""
NeuroMetaBench Layer B Producer - case 29484767 (Emotion)
Condition: opencode_qwen36_plus_without_br
Runner: opencode, model: opencode/qwen3.6-plus, br_mode: without_br
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# ── Configuration ──────────────────────────────────────────────────────────
CASE_ID = "neurometabench:29484767"
META_PMID = "29484767"
CONDITION_ID = "opencode_qwen36_plus_without_br"
RUNNER = "opencode"
MODEL_TARGET = "opencode/qwen3.6-plus"
BR_MODE = "without_br"
TOPIC = "Emotion"
PROJECT_KEY = "emotion"

STUDYSET_PATH = "/app/brain_researcher/external/neurometabench/data/nimads/emotion/merged/nimads_studyset.json"
ANNOTATION_PATH = "/app/brain_researcher/external/neurometabench/data/nimads/emotion/merged/nimads_annotation.json"
RAW_JSONS = [
    "/app/brain_researcher/external/neurometabench/data/nimads/emotion/Emotion_Cluster_07132016_1_of_5.json",
    "/app/brain_researcher/external/neurometabench/data/nimads/emotion/Emotion_Cluster_07132016_2_of_5.json",
    "/app/brain_researcher/external/neurometabench/data/nimads/emotion/Emotion_Cluster_07132016_3_of_5.json",
    "/app/brain_researcher/external/neurometabench/data/nimads/emotion/Emotion_Cluster_07132016_4_of_5.json",
    "/app/brain_researcher/external/neurometabench/data/nimads/emotion/Emotion_Cluster_07132016_5_of_5.json",
]

OUTPUT_DIR = Path(
    "benchmarks/neurometabench/experiments/agent_condition_matrix/"
    "layer_b_claude_deepseek_kimi_qwen_6case_promptscanfix_20260513/"
    "producer_outputs/opencode_qwen36_plus_without_br/"
    "_episode_layer_b_29484767/layer_b_29484767"
)

REPO_ROOT = "/app/brain_researcher"


def get_repo_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT
        ).decode().strip()
    except Exception:
        return "unknown"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def extract_coordinate_rows(studyset: dict) -> list[dict]:
    """Extract coordinate rows from NiMADS studyset following run_path_b_reproduction.py pattern."""
    rows = []
    for study in studyset.get("studies") or []:
        study_id = str(study.get("id") or "")
        study_name = str(study.get("name") or "")
        for analysis in study.get("analyses") or []:
            analysis_id = str(analysis.get("id") or "")
            analysis_name = str(analysis.get("name") or "")
            metadata = analysis.get("metadata") or {}
            sample_sizes = metadata.get("sample_sizes") or []
            sample_size = sample_sizes[0] if sample_sizes else metadata.get("sample_size")
            for index, point in enumerate(analysis.get("points") or []):
                coords = point.get("coordinates") or []
                if len(coords) != 3:
                    continue
                rows.append({
                    "study_id": study_id,
                    "study_name": study_name,
                    "analysis_id": analysis_id,
                    "analysis_name": analysis_name,
                    "point_index": index,
                    "x": coords[0],
                    "y": coords[1],
                    "z": coords[2],
                    "space": point.get("space") or "UNKNOWN",
                    "sample_size": sample_size if sample_size is not None else "",
                })
    return rows


def write_coordinate_table(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "study_id", "study_name", "analysis_id", "analysis_name",
        "point_index", "x", "y", "z", "space", "sample_size",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_included_studies(studyset: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["study_id", "study_name", "authors", "publication", "n_analyses", "n_points"],
        )
        writer.writeheader()
        for study in studyset.get("studies") or []:
            analyses = study.get("analyses") or []
            writer.writerow({
                "study_id": study.get("id") or "",
                "study_name": study.get("name") or "",
                "authors": study.get("authors") or "",
                "publication": study.get("publication") or "",
                "n_analyses": len(analyses),
                "n_points": sum(len(a.get("points") or []) for a in analyses),
            })


def run_ale(studyset_path: str, output_dir: Path, prefix: str) -> dict:
    """Convert NiMADS to NiMARE Dataset, run ALE, and save all maps."""
    from nimare.io import convert_nimads_to_dataset
    from nimare.meta.cbma.ale import ALE

    dset = convert_nimads_to_dataset(studyset_path)
    result = ALE(n_cores=1).fit(dset)
    output_dir.mkdir(parents=True, exist_ok=True)
    result.save_maps(str(output_dir), prefix=prefix)
    map_paths = {
        name: str(output_dir / f"{prefix}_{name}.nii.gz")
        for name in sorted(result.maps)
        if (output_dir / f"{prefix}_{name}.nii.gz").exists()
    }
    return {
        "n_dataset_experiments": len(dset.ids),
        "n_dataset_coordinates": int(len(dset.coordinates)),
        "dataset_coordinate_spaces": dset.coordinates["space"].value_counts().to_dict()
        if "space" in dset.coordinates else {},
        "map_paths": map_paths,
    }


def map_qc(map_path: Path) -> dict:
    import nibabel as nib
    img = nib.load(str(map_path))
    data = np.asarray(img.get_fdata(), dtype=float)
    finite = np.isfinite(data)
    positive = finite & (data > 0)
    finite_values = data[finite]
    positive_values = data[positive]
    return {
        "path": str(map_path),
        "shape": list(data.shape),
        "finite_voxels": int(finite.sum()),
        "positive_voxels": int(positive.sum()),
        "min": float(np.nanmin(finite_values)) if finite_values.size else None,
        "max": float(np.nanmax(finite_values)) if finite_values.size else None,
        "mean_positive": float(np.mean(positive_values)) if positive_values.size else None,
        "p95_positive": float(np.percentile(positive_values, 95)) if positive_values.size else None,
    }


def write_spatial_report(metrics: dict, path: Path) -> None:
    lines = [
        f"# Spatial Report: {TOPIC} Meta-Analysis (PMID: {META_PMID})",
        "",
        "## Overview",
        "",
        f"- **Topic**: {TOPIC}",
        f"- **Meta-analysis PMID**: {META_PMID}",
        f"- **Method**: Activation Likelihood Estimation (ALE) via NiMARE",
        f"- **NiMADS studies**: {metrics['n_nimads_studies']}",
        f"- **Coordinate rows**: {metrics['n_coordinate_rows']}",
        f"- **Source coordinate spaces**: {metrics['source_coordinate_spaces']}",
        "",
        "## ALE Outputs",
        "",
    ]
    for name, map_path in sorted(metrics["ale"]["map_paths"].items()):
        lines.append(f"- `{name}`: `{map_path}`")
    z_qc = metrics.get("z_map_qc", {})
    lines.extend([
        "",
        "## Map QC",
        "",
        f"- Z-map positive voxels: `{z_qc.get('positive_voxels', 'N/A')}`",
        f"- Z-map max: `{z_qc.get('max', 'N/A')}`",
        f"- Z-map p95 positive: `{z_qc.get('p95_positive', 'N/A')}`",
        "",
        "## Method Notes",
        "",
        "- NiMADS studyset converted to NiMARE Dataset via `nimare.io.convert_nimads_to_dataset`.",
        "- ALE performed via `nimare.meta.cbma.ale.ALE` with default parameters.",
        "- All analyses from the emotion NiMADS project were included.",
        "- Coordinates are in MNI space.",
        "",
        "## Generated Artifacts",
        "",
        f"- `ale_maps/{META_PMID}_stat.nii.gz` — ALE statistic map",
        f"- `ale_maps/{META_PMID}_z.nii.gz` — Z-score map",
        f"- `ale_maps/{META_PMID}_p.nii.gz` — P-value map",
        f"- `included_studies.csv` — Study-level inclusion table",
        f"- `coordinate_table.csv` — Full coordinate extraction table",
        f"- `metrics.json` — Quantitative metrics",
        f"- `provenance_manifest.json` — Execution provenance",
        "",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    start_time = time.time()
    print(f"[START] Layer B producer for case {CASE_ID}")
    print(f"[START] Output directory: {OUTPUT_DIR}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load NiMADS assets
    studyset = load_json(STUDYSET_PATH)
    annotation = load_json(ANNOTATION_PATH)
    print(f"[INFO] Studyset: {len(studyset.get('studies', []))} studies")
    print(f"[INFO] Annotation: {len(annotation.get('notes', []))} notes")

    # Extract coordinate rows (all analyses included for full emotion project)
    coords = extract_coordinate_rows(studyset)
    print(f"[INFO] Extracted {len(coords)} coordinate rows")

    # Write CSVs
    write_coordinate_table(coords, OUTPUT_DIR / "coordinate_table.csv")
    write_included_studies(studyset, OUTPUT_DIR / "included_studies.csv")
    print(f"[INFO] Wrote coordinate_table.csv and included_studies.csv")

    # Run ALE
    maps_dir = OUTPUT_DIR / "ale_maps"
    print(f"[INFO] Running ALE meta-analysis...")
    ale = run_ale(STUDYSET_PATH, maps_dir, META_PMID)
    print(f"[INFO] ALE: {ale['n_dataset_experiments']} experiments, {ale['n_dataset_coordinates']} coordinates")
    print(f"[INFO] Map paths: {list(ale['map_paths'].keys())}")

    # Map QC
    z_map = Path(ale["map_paths"]["z"])
    stat_map = Path(ale["map_paths"]["stat"])
    z_qc = map_qc(z_map)
    stat_qc = map_qc(stat_map)
    print(f"[INFO] Z-map QC: positive_voxels={z_qc['positive_voxels']}, max={z_qc['max']}")

    # Build metrics
    source_spaces = {}
    for c in coords:
        source_spaces[str(c["space"])] = source_spaces.get(str(c["space"]), 0) + 1

    metrics = {
        "meta_pmid": META_PMID,
        "case_id": CASE_ID,
        "topic": TOPIC,
        "project_key": PROJECT_KEY,
        "n_nimads_studies": len(studyset.get("studies") or []),
        "n_coordinate_rows": len(coords),
        "source_coordinate_spaces": dict(sorted(source_spaces.items())),
        "ale": ale,
        "z_map_qc": z_qc,
        "stat_map_qc": stat_qc,
        "map_generated": True,
        "map_generation_status": "success",
        "degraded_fallback_map": False,
        "outputs": {
            "output_dir": str(OUTPUT_DIR),
            "coordinate_table": str(OUTPUT_DIR / "coordinate_table.csv"),
            "included_studies": str(OUTPUT_DIR / "included_studies.csv"),
            "ale_maps_dir": str(maps_dir),
            "metrics": str(OUTPUT_DIR / "metrics.json"),
            "spatial_report": str(OUTPUT_DIR / "spatial_report.md"),
            "provenance_manifest": str(OUTPUT_DIR / "provenance_manifest.json"),
        },
    }

    # Write metrics.json
    (OUTPUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"[INFO] Wrote metrics.json")

    # Write spatial_report.md
    write_spatial_report(metrics, OUTPUT_DIR / "spatial_report.md")
    print(f"[INFO] Wrote spatial_report.md")

    end_time = time.time()
    commit = get_repo_commit()

    # Write provenance_manifest.json
    provenance = {
        "condition_id": CONDITION_ID,
        "runner": RUNNER,
        "model_target": MODEL_TARGET,
        "resolved_model": MODEL_TARGET,
        "br_mode": BR_MODE,
        "case_id": CASE_ID,
        "meta_pmid": META_PMID,
        "topic": TOPIC,
        "source_assets": {
            "nimads_studyset": STUDYSET_PATH,
            "nimads_annotation": ANNOTATION_PATH,
            "nimads_studyset_sha256": sha256_file(STUDYSET_PATH),
            "nimads_annotation_sha256": sha256_file(ANNOTATION_PATH),
            "raw_jsons": RAW_JSONS,
        },
        "commands_executed": [
            "python3 scripts/neurometabench_v1/layer_b_producer_29484767.py",
        ],
        "start_timestamp": datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
        "end_timestamp": datetime.fromtimestamp(end_time, tz=timezone.utc).isoformat(),
        "duration_seconds": round(end_time - start_time, 2),
        "repository_commit": commit,
        "method": {
            "coordinate_source": "merged NiMADS studyset",
            "ale_engine": "nimare.meta.cbma.ale.ALE",
            "map_names": sorted(ale["map_paths"]),
        },
        "bundle_artifacts": {
            "included_studies_csv": "included_studies.csv",
            "coordinate_table_csv": "coordinate_table.csv",
            "metrics_json": "metrics.json",
            "spatial_report_md": "spatial_report.md",
            "provenance_manifest_json": "provenance_manifest.json",
            "ale_stat_map": ale["map_paths"].get("stat", ""),
            "ale_z_map": ale["map_paths"].get("z", ""),
            "ale_p_map": ale["map_paths"].get("p", ""),
        },
        "study_counts": {
            "n_included_studies": len(studyset.get("studies") or []),
            "n_total_coordinates": len(coords),
            "n_ale_experiments": ale["n_dataset_experiments"],
        },
    }

    (OUTPUT_DIR / "provenance_manifest.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"[INFO] Wrote provenance_manifest.json")

    # Verify all required files
    required = [
        "included_studies.csv",
        "coordinate_table.csv",
        "metrics.json",
        "provenance_manifest.json",
        "spatial_report.md",
        f"ale_maps/{META_PMID}_stat.nii.gz",
        f"ale_maps/{META_PMID}_z.nii.gz",
        f"ale_maps/{META_PMID}_p.nii.gz",
    ]
    missing = [f for f in required if not (OUTPUT_DIR / f).exists()]
    if missing:
        print(f"[WARN] Missing artifacts: {missing}")
    else:
        print(f"[OK] All required artifacts present")

    print(f"[DONE] Layer B producer completed in {end_time - start_time:.2f}s")
    print(f"[DONE] Bundle: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
