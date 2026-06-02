#!/usr/bin/env python3
"""Run NeuroMetaBench Layer B NiMADS -> ALE map reproduction."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.build_nimads_reproduction_manifest import DEFAULT_OUTPUT
from scripts.neurometabench_v1.shared import DEFAULT_CASES_PATH, read_jsonl

DEFAULT_OUTPUT_ROOT = Path("benchmarks/neurometabench/experiments/path_b_reproduction")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest_rows(manifest_path: Path = DEFAULT_OUTPUT) -> list[dict[str, Any]]:
    return read_jsonl(manifest_path)


def load_case_by_pmid(cases_path: Path = DEFAULT_CASES_PATH) -> dict[str, dict[str, Any]]:
    return {str(row.get("meta_pmid") or ""): row for row in read_jsonl(cases_path)}


def coordinate_rows(studyset: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
                rows.append(
                    {
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
                    }
                )
    return rows


def analysis_ids_with_points(studyset: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for study in studyset.get("studies") or []:
        for analysis in study.get("analyses") or []:
            if analysis.get("points"):
                ids.append(str(analysis.get("id") or ""))
    return sorted({analysis_id for analysis_id in ids if analysis_id})


def filter_studyset_by_analysis_ids(studyset: dict[str, Any], keep_ids: set[str]) -> dict[str, Any]:
    filtered = copy.deepcopy(studyset)
    kept_studies: list[dict[str, Any]] = []
    for study in filtered.get("studies") or []:
        analyses = [
            analysis
            for analysis in study.get("analyses") or []
            if str(analysis.get("id") or "") in keep_ids
        ]
        if analyses:
            study["analyses"] = analyses
            kept_studies.append(study)
    filtered["studies"] = kept_studies
    return filtered


def write_coordinate_table(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "study_id",
        "study_name",
        "analysis_id",
        "analysis_name",
        "point_index",
        "x",
        "y",
        "z",
        "space",
        "sample_size",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_included_studies(studyset: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "study_id",
                "study_name",
                "authors",
                "publication",
                "n_analyses",
                "n_points",
            ],
        )
        writer.writeheader()
        for study in studyset.get("studies") or []:
            analyses = study.get("analyses") or []
            writer.writerow(
                {
                    "study_id": study.get("id") or "",
                    "study_name": study.get("name") or "",
                    "authors": study.get("authors") or "",
                    "publication": study.get("publication") or "",
                    "n_analyses": len(analyses),
                    "n_points": sum(len(analysis.get("points") or []) for analysis in analyses),
                }
            )


def run_ale(studyset: dict[str, Any] | Path, output_dir: Path, prefix: str, n_cores: int = 1) -> dict[str, Any]:
    """Convert NiMADS to NiMARE Dataset, run ALE, and save all maps."""

    from nimare.io import convert_nimads_to_dataset
    from nimare.meta.cbma.ale import ALE

    source: dict[str, Any] | str
    source = str(studyset) if isinstance(studyset, Path) else studyset
    dset = convert_nimads_to_dataset(source)
    result = ALE(n_cores=n_cores).fit(dset)
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
        if "space" in dset.coordinates
        else {},
        "map_paths": map_paths,
    }


def _top_fraction_mask(values: np.ndarray, fraction: float = 0.05) -> np.ndarray:
    finite = np.isfinite(values)
    positive = finite & (values > 0)
    if not positive.any():
        return np.zeros(values.shape, dtype=bool)
    candidates = values[positive]
    n_top = max(1, int(math.ceil(candidates.size * fraction)))
    threshold = np.partition(candidates, -n_top)[-n_top]
    return positive & (values >= threshold)


def map_qc(map_path: Path) -> dict[str, Any]:
    img = nib.load(str(map_path))
    data = np.asarray(img.get_fdata(), dtype=float)
    finite = np.isfinite(data)
    positive = finite & (data > 0)
    finite_values = data[finite]
    positive_values = data[positive]
    top5 = _top_fraction_mask(data)
    return {
        "path": str(map_path),
        "shape": list(data.shape),
        "finite_voxels": int(finite.sum()),
        "positive_voxels": int(positive.sum()),
        "top5_positive_voxels": int(top5.sum()),
        "min": float(np.nanmin(finite_values)) if finite_values.size else None,
        "max": float(np.nanmax(finite_values)) if finite_values.size else None,
        "mean_positive": float(np.mean(positive_values)) if positive_values.size else None,
        "p95_positive": float(np.percentile(positive_values, 95)) if positive_values.size else None,
    }


def spatial_metrics(map_a: Path, map_b: Path) -> dict[str, Any]:
    img_a = nib.load(str(map_a))
    img_b = nib.load(str(map_b))
    if img_a.shape != img_b.shape:
        from nilearn.image import resample_to_img

        img_b = resample_to_img(img_b, img_a, interpolation="continuous", force_resample=True)
    a = np.asarray(img_a.get_fdata(), dtype=float)
    b = np.asarray(img_b.get_fdata(), dtype=float)
    finite = np.isfinite(a) & np.isfinite(b)
    union_positive = finite & ((a > 0) | (b > 0))

    def _corr(mask: np.ndarray) -> float | None:
        if int(mask.sum()) < 3:
            return None
        av = a[mask]
        bv = b[mask]
        if float(np.std(av)) == 0.0 or float(np.std(bv)) == 0.0:
            return None
        return float(np.corrcoef(av, bv)[0, 1])

    top_a = _top_fraction_mask(a)
    top_b = _top_fraction_mask(b)
    denom = int(top_a.sum() + top_b.sum())
    dice = float(2 * int((top_a & top_b).sum()) / denom) if denom else None
    return {
        "pearson_all_finite": _corr(finite),
        "pearson_union_positive": _corr(union_positive),
        "dice_top5_positive": dice,
        "n_union_positive_voxels": int(union_positive.sum()),
        "n_top5_a": int(top_a.sum()),
        "n_top5_b": int(top_b.sum()),
    }


def split_half_metrics(
    studyset: dict[str, Any],
    output_dir: Path,
    prefix: str,
    *,
    n_cores: int = 1,
    min_half_analyses: int = 10,
) -> dict[str, Any]:
    analysis_ids = analysis_ids_with_points(studyset)
    even = set(analysis_ids[::2])
    odd = set(analysis_ids[1::2])
    if min(len(even), len(odd)) < min_half_analyses:
        return {
            "status": "skipped",
            "reason": "too_few_analyses",
            "n_even_analyses": len(even),
            "n_odd_analyses": len(odd),
            "min_half_analyses": min_half_analyses,
        }

    split_dir = output_dir / "split_half_maps"
    even_result = run_ale(
        filter_studyset_by_analysis_ids(studyset, even),
        split_dir,
        f"{prefix}_even",
        n_cores=n_cores,
    )
    odd_result = run_ale(
        filter_studyset_by_analysis_ids(studyset, odd),
        split_dir,
        f"{prefix}_odd",
        n_cores=n_cores,
    )
    even_z = Path(even_result["map_paths"]["z"])
    odd_z = Path(odd_result["map_paths"]["z"])
    return {
        "status": "computed",
        "n_even_analyses": len(even),
        "n_odd_analyses": len(odd),
        "even": even_result,
        "odd": odd_result,
        "z_map_metrics": spatial_metrics(even_z, odd_z),
    }


def run_case(
    row: dict[str, Any],
    case: dict[str, Any],
    output_root: Path,
    *,
    n_cores: int = 1,
    reference_map: Path | None = None,
    min_half_analyses: int = 10,
) -> dict[str, Any]:
    meta_pmid = str(row["meta_pmid"])
    out_dir = output_root / f"layer_b_{meta_pmid}_{row.get('project_key') or 'nimads'}"
    maps_dir = out_dir / "ale_maps"
    studyset_path = Path(row["merged_studyset"])
    studyset = _read_json(studyset_path)
    coords = coordinate_rows(studyset)

    write_coordinate_table(coords, out_dir / "coordinate_table.csv")
    write_included_studies(studyset, out_dir / "included_studies.csv")

    ale = run_ale(studyset_path, maps_dir, meta_pmid, n_cores=n_cores)
    z_map = Path(ale["map_paths"]["z"])
    stat_map = Path(ale["map_paths"]["stat"])
    metrics: dict[str, Any] = {
        "meta_pmid": meta_pmid,
        "case_id": row.get("case_id"),
        "topic": row.get("topic"),
        "project_key": row.get("project_key"),
        "case_gt_pmids_n": len(case.get("gt_pmids") or []),
        "n_nimads_studies": len(studyset.get("studies") or []),
        "n_coordinate_rows": len(coords),
        "source_coordinate_spaces": dict(sorted({r["space"]: 0 for r in coords}.items())),
        "ale": ale,
        "z_map_qc": map_qc(z_map),
        "stat_map_qc": map_qc(stat_map),
        "split_half": split_half_metrics(
            studyset,
            out_dir,
            meta_pmid,
            n_cores=n_cores,
            min_half_analyses=min_half_analyses,
        ),
        "reference_comparison": None,
        "outputs": {
            "output_dir": str(out_dir),
            "coordinate_table": str(out_dir / "coordinate_table.csv"),
            "included_studies": str(out_dir / "included_studies.csv"),
            "ale_maps_dir": str(maps_dir),
            "metrics": str(out_dir / "metrics.json"),
            "spatial_report": str(out_dir / "spatial_report.md"),
            "provenance_manifest": str(out_dir / "provenance_manifest.json"),
        },
    }
    source_spaces: dict[str, int] = {}
    for coord in coords:
        source_spaces[str(coord["space"])] = source_spaces.get(str(coord["space"]), 0) + 1
    metrics["source_coordinate_spaces"] = dict(sorted(source_spaces.items()))

    if reference_map:
        metrics["reference_comparison"] = {
            "reference_map": str(reference_map),
            "z_map_metrics": spatial_metrics(z_map, reference_map),
        }

    provenance = {
        "meta_pmid": meta_pmid,
        "inputs": {
            "manifest_row": row,
            "case_gt_pmids": case.get("gt_pmids") or [],
            "studyset": str(studyset_path),
            "annotation": row.get("merged_annotation"),
            "reference_map": str(reference_map) if reference_map else None,
        },
        "method": {
            "coordinate_source": "merged NiMADS studyset",
            "ale_engine": "nimare.meta.cbma.ale.ALE",
            "map_names": sorted(ale["map_paths"]),
            "split_half_rule": "sorted analysis ids, even vs odd",
        },
        "outputs": metrics["outputs"],
    }

    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "provenance_manifest.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_spatial_report(metrics, out_dir / "spatial_report.md")
    return metrics


def write_spatial_report(metrics: dict[str, Any], path: Path) -> None:
    split = metrics.get("split_half") or {}
    split_line = "not computed"
    if split.get("status") == "computed":
        split_metrics = split["z_map_metrics"]
        split_line = (
            f"pearson_union_positive={split_metrics['pearson_union_positive']}, "
            f"dice_top5_positive={split_metrics['dice_top5_positive']}"
        )
    elif split:
        split_line = f"skipped ({split.get('reason')})"

    lines = [
        f"# Path B Reproduction: {metrics['meta_pmid']} {metrics['topic']}",
        "",
        "## Inputs",
        "",
        f"- Project: `{metrics['project_key']}`",
        f"- Case-level GT PMIDs: `{metrics['case_gt_pmids_n']}`",
        f"- NiMADS studies: `{metrics['n_nimads_studies']}`",
        f"- Coordinate rows: `{metrics['n_coordinate_rows']}`",
        f"- Source coordinate spaces: `{metrics['source_coordinate_spaces']}`",
        "",
        "## ALE Outputs",
        "",
    ]
    for name, map_path in sorted(metrics["ale"]["map_paths"].items()):
        lines.append(f"- `{name}`: `{map_path}`")
    lines.extend(
        [
            "",
            "## Map QC",
            "",
            f"- Z-map positive voxels: `{metrics['z_map_qc']['positive_voxels']}`",
            f"- Z-map max: `{metrics['z_map_qc']['max']}`",
            f"- Z-map p95 positive: `{metrics['z_map_qc']['p95_positive']}`",
            f"- Split-half spatial check: `{split_line}`",
        ]
    )
    if metrics.get("reference_comparison"):
        lines.extend(
            [
                "",
                "## Reference Comparison",
                "",
                f"- Reference map: `{metrics['reference_comparison']['reference_map']}`",
                f"- Metrics: `{metrics['reference_comparison']['z_map_metrics']}`",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Reference Comparison",
                "",
                "- No external published/reference NIfTI was supplied for this run.",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def select_rows(
    rows: list[dict[str, Any]],
    *,
    meta_pmid: str | None = None,
    all_cases: bool = False,
) -> list[dict[str, Any]]:
    if all_cases:
        return rows
    if meta_pmid:
        selected = [row for row in rows if str(row.get("meta_pmid")) == str(meta_pmid)]
        if not selected:
            raise SystemExit(f"No Path B manifest row found for meta PMID {meta_pmid}")
        return selected
    raise SystemExit("Provide --meta-pmid or --all")


def run_reproductions(
    *,
    manifest_path: Path = DEFAULT_OUTPUT,
    cases_path: Path = DEFAULT_CASES_PATH,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    meta_pmid: str | None = None,
    all_cases: bool = False,
    n_cores: int = 1,
    reference_map: Path | None = None,
    min_half_analyses: int = 10,
) -> dict[str, Any]:
    rows = select_rows(load_manifest_rows(manifest_path), meta_pmid=meta_pmid, all_cases=all_cases)
    case_by_pmid = load_case_by_pmid(cases_path)
    output_root.mkdir(parents=True, exist_ok=True)
    case_metrics = [
        run_case(
            row,
            case_by_pmid.get(str(row.get("meta_pmid") or ""), {}),
            output_root,
            n_cores=n_cores,
            reference_map=reference_map if len(rows) == 1 else None,
            min_half_analyses=min_half_analyses,
        )
        for row in rows
    ]
    summary = {
        "n_cases": len(case_metrics),
        "n_cases_with_maps": sum(1 for row in case_metrics if row.get("ale", {}).get("map_paths")),
        "n_cases_split_half_computed": sum(
            1 for row in case_metrics if (row.get("split_half") or {}).get("status") == "computed"
        ),
        "total_coordinate_rows": sum(row.get("n_coordinate_rows", 0) for row in case_metrics),
        "cases": [
            {
                "meta_pmid": row["meta_pmid"],
                "topic": row["topic"],
                "n_coordinate_rows": row["n_coordinate_rows"],
                "split_half_status": (row.get("split_half") or {}).get("status"),
                "output_dir": row["outputs"]["output_dir"],
            }
            for row in case_metrics
        ],
    }
    (output_root / "path_b_reproduction_summary.json").write_text(
        json.dumps({"summary": summary, "cases": case_metrics}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"summary": summary, "cases": case_metrics, "summary_json": str(output_root / "path_b_reproduction_summary.json")}


def summarize_existing(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    case_metrics: list[dict[str, Any]] = []
    for metrics_path in sorted(output_root.glob("layer_b_*/metrics.json")):
        case_metrics.append(json.loads(metrics_path.read_text(encoding="utf-8")))
    summary = {
        "n_cases": len(case_metrics),
        "n_cases_with_maps": sum(
            1
            for row in case_metrics
            if all(Path(path).exists() for path in (row.get("ale", {}).get("map_paths") or {}).values())
        ),
        "n_cases_split_half_computed": sum(
            1 for row in case_metrics if (row.get("split_half") or {}).get("status") == "computed"
        ),
        "total_coordinate_rows": sum(row.get("n_coordinate_rows", 0) for row in case_metrics),
        "cases": [
            {
                "meta_pmid": row["meta_pmid"],
                "topic": row["topic"],
                "n_coordinate_rows": row["n_coordinate_rows"],
                "split_half_status": (row.get("split_half") or {}).get("status"),
                "output_dir": row["outputs"]["output_dir"],
            }
            for row in case_metrics
        ],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    summary_path = output_root / "path_b_reproduction_summary.json"
    summary_path.write_text(
        json.dumps({"summary": summary, "cases": case_metrics}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"summary": summary, "cases": case_metrics, "summary_json": str(summary_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--meta-pmid")
    parser.add_argument("--all", action="store_true", help="Run every Path B manifest case.")
    parser.add_argument("--n-cores", type=int, default=1)
    parser.add_argument("--reference-map", type=Path)
    parser.add_argument("--min-half-analyses", type=int, default=10)
    parser.add_argument(
        "--summarize-existing",
        action="store_true",
        help="Rebuild the aggregate summary from existing layer_b_*/metrics.json files without rerunning ALE.",
    )
    args = parser.parse_args()
    if args.summarize_existing:
        result = summarize_existing(args.output_root)
    else:
        result = run_reproductions(
            manifest_path=args.manifest,
            cases_path=args.cases,
            output_root=args.output_root,
            meta_pmid=args.meta_pmid,
            all_cases=args.all,
            n_cores=args.n_cores,
            reference_map=args.reference_map,
            min_half_analyses=args.min_half_analyses,
        )
    print(json.dumps({"summary": result["summary"], "summary_json": result["summary_json"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
