"""Seed repo-wide atlas assets into a flat shared atlas home."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from nilearn import datasets

from brain_researcher.services.tools.atlas_utils import (
    atlas_family_output_root,
    default_atlas_output_root,
    derive_local_atlas_labels,
    find_local_aal_atlas,
    find_local_harvard_oxford_atlas,
    find_local_schaefer_atlas,
    find_local_yeo_atlas,
    normalize_harvard_oxford_variant,
    write_labels_sidecars,
)


@dataclass(frozen=True)
class NilearnSeedSpec:
    key: str
    fetcher: Callable[[Path], object]


def _fetch_schaefer(
    data_dir: Path,
    *,
    n_rois: int,
    yeo_networks: int,
) -> object:
    return datasets.fetch_atlas_schaefer_2018(
        n_rois=n_rois,
        yeo_networks=yeo_networks,
        resolution_mm=2,
        data_dir=str(data_dir),
        verbose=0,
    )


def _fetch_aal(data_dir: Path) -> object:
    return datasets.fetch_atlas_aal(data_dir=str(data_dir), verbose=0)


def _fetch_harvard(data_dir: Path, *, variant: str) -> object:
    return datasets.fetch_atlas_harvard_oxford(
        atlas_name=variant,
        data_dir=str(data_dir),
    )


def _fetch_yeo(data_dir: Path, *, n_networks: int) -> object:
    return datasets.fetch_atlas_yeo_2011(
        n_networks=n_networks,
        thickness="thick",
        data_dir=str(data_dir),
    )


def _fetch_destrieux(data_dir: Path) -> object:
    return datasets.fetch_atlas_destrieux_2009(data_dir=str(data_dir), verbose=0)


def _fetch_basc(data_dir: Path) -> object:
    return datasets.fetch_atlas_basc_multiscale_2015(
        version="sym",
        resolution=122,
        data_dir=str(data_dir),
    )


def _fetch_msdl(data_dir: Path) -> object:
    return datasets.fetch_atlas_msdl(data_dir=str(data_dir), verbose=0)


NILEARN_SEED_SPECS: List[NilearnSeedSpec] = [
    NilearnSeedSpec("aal", _fetch_aal),
    NilearnSeedSpec(
        "schaefer100_7n",
        lambda data_dir: _fetch_schaefer(data_dir, n_rois=100, yeo_networks=7),
    ),
    NilearnSeedSpec(
        "schaefer200_7n",
        lambda data_dir: _fetch_schaefer(data_dir, n_rois=200, yeo_networks=7),
    ),
    NilearnSeedSpec(
        "schaefer200_17n",
        lambda data_dir: _fetch_schaefer(data_dir, n_rois=200, yeo_networks=17),
    ),
    NilearnSeedSpec(
        "schaefer400_7n",
        lambda data_dir: _fetch_schaefer(data_dir, n_rois=400, yeo_networks=7),
    ),
    NilearnSeedSpec(
        "schaefer1000_7n",
        lambda data_dir: _fetch_schaefer(data_dir, n_rois=1000, yeo_networks=7),
    ),
    NilearnSeedSpec(
        "harvard_oxford_cort25",
        lambda data_dir: _fetch_harvard(data_dir, variant="cort-maxprob-thr25-2mm"),
    ),
    NilearnSeedSpec(
        "harvard_oxford_sub25",
        lambda data_dir: _fetch_harvard(data_dir, variant="sub-maxprob-thr25-2mm"),
    ),
    NilearnSeedSpec("yeo7", lambda data_dir: _fetch_yeo(data_dir, n_networks=7)),
    NilearnSeedSpec("yeo17", lambda data_dir: _fetch_yeo(data_dir, n_networks=17)),
    NilearnSeedSpec("destrieux_2009", _fetch_destrieux),
    NilearnSeedSpec("basc_multiscale_2015_scale122", _fetch_basc),
    NilearnSeedSpec("msdl", _fetch_msdl),
]


def _resolve_root(candidate: Optional[Path]) -> Optional[Path]:
    if candidate is None:
        return None
    expanded = candidate.expanduser().resolve()
    return expanded if expanded.exists() else None


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if path.is_file() or (path.is_symlink() and not path.is_dir()):
            yield path


def _snapshot_files(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {path.resolve() if path.is_symlink() else path for path in _iter_files(root)}


def _sync_tree(
    src: Path,
    dst: Path,
    provenance: Dict[Path, str],
) -> Dict[str, int]:
    copied = 0
    reused = 0
    if not src.exists():
        return {"copied": copied, "reused": reused}

    for source_path in _iter_files(src):
        relpath = source_path.relative_to(src)
        dest_path = dst / relpath
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            same_size = dest_path.stat().st_size == source_path.stat().st_size
            if same_size:
                provenance.setdefault(dest_path, "reused_local")
                reused += 1
                continue
        shutil.copy2(source_path, dest_path)
        provenance[dest_path] = "synced"
        copied += 1
    return {"copied": copied, "reused": reused}


def _record_download_delta(
    before: set[Path],
    after: set[Path],
    provenance: Dict[Path, str],
) -> int:
    created = 0
    for path in after - before:
        provenance[path] = "downloaded"
        created += 1
    return created


def _link_or_copy_file(src: Path, dest: Path, provenance: Dict[Path, str]) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        if dest.is_symlink() and dest.resolve() == src.resolve():
            provenance.setdefault(dest, "symlinked")
            return "symlinked"
        dest.unlink()

    try:
        os.symlink(src, dest)
        provenance[dest] = "symlinked"
        return "symlinked"
    except OSError:
        shutil.copy2(src, dest)
        provenance[dest] = "copied"
        return "copied"


def _best_effort_write_labels(
    atlas_path: Path,
    labels: List[str],
    provenance: Dict[Path, str],
) -> None:
    tsv_path, json_path = write_labels_sidecars(atlas_path, labels)
    provenance[tsv_path] = "generated"
    provenance[json_path] = "generated"


def _seed_family_atlas(
    source_path: Path,
    family_dir: Path,
    labels: List[str],
    provenance: Dict[Path, str],
) -> None:
    dest_path = family_dir / source_path.name
    _link_or_copy_file(source_path, dest_path, provenance)
    _best_effort_write_labels(dest_path, labels, provenance)


def _ensure_nilearn_inventory(
    dest_root: Path,
    provenance: Dict[Path, str],
    *,
    source_root: Optional[Path] = None,
    download_missing: bool = True,
) -> Dict[str, int]:
    dest_root.mkdir(parents=True, exist_ok=True)
    summary = {"synced": 0, "reused": 0, "downloaded": 0}
    if source_root and source_root != dest_root:
        sync_summary = _sync_tree(source_root, dest_root, provenance)
        summary["synced"] += sync_summary["copied"]
        summary["reused"] += sync_summary["reused"]

    if not download_missing:
        return summary

    for spec in NILEARN_SEED_SPECS:
        before = _snapshot_files(dest_root)
        spec.fetcher(dest_root)
        after = _snapshot_files(dest_root)
        summary["downloaded"] += _record_download_delta(before, after, provenance)
    return summary


def _ensure_neuromaps_inventory(
    dest_root: Path,
    provenance: Dict[Path, str],
    *,
    source_root: Optional[Path] = None,
    download_missing: bool = True,
) -> Dict[str, int]:
    dest_root.mkdir(parents=True, exist_ok=True)
    summary = {"synced": 0, "reused": 0, "downloaded": 0}
    if source_root and source_root != dest_root:
        sync_summary = _sync_tree(source_root, dest_root, provenance)
        summary["synced"] += sync_summary["copied"]
        summary["reused"] += sync_summary["reused"]

    if not download_missing:
        return summary

    from brain_researcher.services.br_kg.spatial.fetch_all_neuromaps import (
        _fetch_annotations,
        _fetch_atlases,
    )

    before = _snapshot_files(dest_root)
    _fetch_atlases(dest_root, verbose=0)
    _fetch_annotations(dest_root, verbose=0, token=None)
    after = _snapshot_files(dest_root)
    summary["downloaded"] += _record_download_delta(before, after, provenance)
    return summary


def _ensure_niclip_inventory(
    source_root: Path,
    dest_root: Path,
    provenance: Dict[Path, str],
) -> Dict[str, int]:
    if not source_root.exists():
        raise FileNotFoundError(
            f"NiCLIP source root not found: {source_root}. "
            "Mount /app/data/niclip or provide --niclip-source-root."
        )
    if source_root == dest_root:
        return {"synced": 0, "reused": sum(1 for _ in _iter_files(dest_root))}
    dest_root.mkdir(parents=True, exist_ok=True)
    sync_summary = _sync_tree(source_root, dest_root, provenance)
    return {"synced": sync_summary["copied"], "reused": sync_summary["reused"]}


def _seed_tool_facing_families(
    output_root: Path,
    nilearn_root: Path,
    provenance: Dict[Path, str],
) -> Dict[str, int]:
    summary = {"seeded": 0}

    schaefer_dir = atlas_family_output_root(output_root, "schaefer_2018")
    schaefer_dir.mkdir(parents=True, exist_ok=True)
    for n_rois, n_networks in ((100, 7), (200, 7), (200, 17), (400, 7), (1000, 7)):
        atlas_path = find_local_schaefer_atlas(
            n_rois=n_rois,
            roots=[nilearn_root],
            yeo_networks=n_networks,
        )
        if atlas_path is None:
            continue
        labels = derive_local_atlas_labels(
            atlas_path,
            atlas_name=f"Schaefer2018_{n_rois}_{n_networks}n",
            family="schaefer_2018",
        )
        _seed_family_atlas(atlas_path, schaefer_dir, labels, provenance)
        summary["seeded"] += 1

    aal_path = find_local_aal_atlas([nilearn_root])
    if aal_path is not None:
        labels = derive_local_atlas_labels(aal_path, atlas_name="aal", family="aal")
        _seed_family_atlas(aal_path, output_root / "aal", labels, provenance)
        summary["seeded"] += 1

    for atlas_name in ("harvard_oxford", "harvard_oxford_sub25"):
        variant = normalize_harvard_oxford_variant(atlas_name)
        atlas_path = find_local_harvard_oxford_atlas(variant, [nilearn_root])
        if atlas_path is None:
            continue
        labels = derive_local_atlas_labels(
            atlas_path,
            atlas_name=atlas_name,
            family="harvard_oxford",
        )
        _seed_family_atlas(
            atlas_path, output_root / "harvard_oxford", labels, provenance
        )
        summary["seeded"] += 1

    for atlas_name in ("yeo7", "yeo17"):
        n_networks = 17 if atlas_name == "yeo17" else 7
        atlas_path = find_local_yeo_atlas(n_networks=n_networks, roots=[nilearn_root])
        if atlas_path is None:
            continue
        labels = derive_local_atlas_labels(
            atlas_path,
            atlas_name=atlas_name,
            family="yeo_2011",
        )
        _seed_family_atlas(atlas_path, output_root / "yeo_2011", labels, provenance)
        summary["seeded"] += 1

    return summary


def _read_mountinfo_line_for_path(path: Path) -> str:
    try:
        text = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError:
        return ""

    best_line = ""
    best_len = -1
    target = str(path.resolve())
    for line in text.splitlines():
        parts = line.split(" - ", maxsplit=1)
        if len(parts) != 2:
            continue
        mount_fields = parts[0].split()
        if len(mount_fields) < 5:
            continue
        mount_point = mount_fields[4]
        if target.startswith(mount_point) and len(mount_point) > best_len:
            best_line = line
            best_len = len(mount_point)
    return best_line


def detect_storage_scope(
    output_root: Path,
    *,
    mountinfo_line: Optional[str] = None,
) -> str:
    line = (
        mountinfo_line
        if mountinfo_line is not None
        else _read_mountinfo_line_for_path(output_root)
    )
    lowered = line.lower()
    if "kubernetes.io~host-path" in lowered or "/srv/datasets/atlases" in lowered:
        return "node_local"
    if (
        "kubernetes.io~csi" in lowered
        or "pvc-" in lowered
        or "persistentvolume" in lowered
    ):
        return "shared"
    return "shared"


def _relative_asset_group(output_root: Path, path: Path) -> str:
    try:
        rel = path.relative_to(output_root)
    except ValueError:
        return "external"
    return rel.parts[0] if rel.parts else "root"


def _build_inventory(
    output_root: Path,
    provenance: Dict[Path, str],
    storage_scope: str,
) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    for path in _iter_files(output_root):
        rel = path.relative_to(output_root)
        if rel.parts and rel.parts[0] == "manifests":
            continue
        record = {
            "asset_group": _relative_asset_group(output_root, path),
            "atlas_family": rel.parts[0] if rel.parts else "root",
            "variant": rel.name,
            "path": str(path),
            "provenance": provenance.get(path, "existing"),
            "size_bytes": path.stat().st_size,
            "storage_scope": storage_scope,
        }
        records.append(record)
    return records


def _write_manifests(
    output_root: Path,
    inventory: List[Dict[str, object]],
    summary: Dict[str, object],
) -> Dict[str, str]:
    manifest_dir = output_root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    inventory_json = manifest_dir / "atlas_inventory.json"
    inventory_tsv = manifest_dir / "atlas_inventory.tsv"
    summary_json = manifest_dir / "seed_report.json"

    inventory_json.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    header = [
        "asset_group",
        "atlas_family",
        "variant",
        "path",
        "provenance",
        "size_bytes",
        "storage_scope",
    ]
    tsv_lines = ["\t".join(header)]
    for row in inventory:
        tsv_lines.append("\t".join(str(row[key]) for key in header))
    inventory_tsv.write_text("\n".join(tsv_lines) + "\n", encoding="utf-8")
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "atlas_inventory_json": str(inventory_json),
        "atlas_inventory_tsv": str(inventory_tsv),
        "seed_report_json": str(summary_json),
    }


def seed_repo_atlas_assets(
    *,
    output_root: Optional[Path] = None,
    nilearn_source_root: Optional[Path] = None,
    neuromaps_source_root: Optional[Path] = None,
    niclip_source_root: Optional[Path] = None,
    download_missing: bool = True,
    storage_scope: str = "auto",
) -> Dict[str, object]:
    resolved_output_root = (
        (output_root or default_atlas_output_root()).expanduser().resolve()
    )
    resolved_output_root.mkdir(parents=True, exist_ok=True)

    nilearn_root = resolved_output_root / "nilearn"
    neuromaps_root = resolved_output_root / "neuromaps"
    niclip_root = resolved_output_root / "niclip"

    nilearn_source = _resolve_root(nilearn_source_root)
    neuromaps_source = _resolve_root(neuromaps_source_root)
    niclip_source = _resolve_root(niclip_source_root)
    if niclip_source is None:
        niclip_source = _resolve_root(Path("data/niclip"))

    provenance: Dict[Path, str] = {}
    nilearn_summary = _ensure_nilearn_inventory(
        nilearn_root,
        provenance,
        source_root=nilearn_source,
        download_missing=download_missing,
    )
    neuromaps_summary = _ensure_neuromaps_inventory(
        neuromaps_root,
        provenance,
        source_root=neuromaps_source,
        download_missing=download_missing,
    )
    if niclip_source is None:
        raise FileNotFoundError(
            "NiCLIP source root not found. "
            "Mount /app/data/niclip or pass --niclip-source-root."
        )
    niclip_summary = _ensure_niclip_inventory(niclip_source, niclip_root, provenance)
    family_summary = _seed_tool_facing_families(
        resolved_output_root, nilearn_root, provenance
    )

    resolved_storage_scope = (
        detect_storage_scope(resolved_output_root)
        if storage_scope == "auto"
        else storage_scope
    )
    inventory = _build_inventory(
        resolved_output_root,
        provenance,
        resolved_storage_scope,
    )

    summary = {
        "output_root": str(resolved_output_root),
        "storage_scope": resolved_storage_scope,
        "counts": {
            "inventory_records": len(inventory),
            "nilearn_synced": nilearn_summary["synced"],
            "nilearn_reused": nilearn_summary["reused"],
            "nilearn_downloaded": nilearn_summary["downloaded"],
            "neuromaps_synced": neuromaps_summary["synced"],
            "neuromaps_reused": neuromaps_summary["reused"],
            "neuromaps_downloaded": neuromaps_summary["downloaded"],
            "niclip_synced": niclip_summary["synced"],
            "niclip_reused": niclip_summary["reused"],
            "tool_facing_seeded": family_summary["seeded"],
        },
        "source_roots": {
            "nilearn": str(nilearn_source) if nilearn_source else None,
            "neuromaps": str(neuromaps_source) if neuromaps_source else None,
            "niclip": str(niclip_source),
        },
    }
    manifests = _write_manifests(resolved_output_root, inventory, summary)
    summary["manifests"] = manifests
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=default_atlas_output_root(),
        help="Flat atlas home (default: BR_ATLAS_OUTPUT_ROOT or /app/data/atlases).",
    )
    parser.add_argument(
        "--nilearn-source-root",
        type=Path,
        default=Path("data/br-kg/raw/nilearn_atlases"),
        help="Existing Nilearn atlas tree to reuse when present.",
    )
    parser.add_argument(
        "--neuromaps-source-root",
        type=Path,
        default=Path("data/br-kg/raw/neuromaps"),
        help="Existing Neuromaps tree to reuse when present.",
    )
    parser.add_argument(
        "--niclip-source-root",
        type=Path,
        default=Path("/app/data/niclip"),
        help="Existing NiCLIP tree to sync into the atlas home.",
    )
    parser.add_argument(
        "--no-download-missing",
        action="store_true",
        help="Reuse local trees only; do not fetch missing Nilearn/Neuromaps assets.",
    )
    parser.add_argument(
        "--storage-scope",
        choices=["auto", "shared", "node_local"],
        default="auto",
        help="Override storage scope recorded in manifests.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = seed_repo_atlas_assets(
        output_root=args.output_root,
        nilearn_source_root=args.nilearn_source_root,
        neuromaps_source_root=args.neuromaps_source_root,
        niclip_source_root=args.niclip_source_root,
        download_missing=not args.no_download_missing,
        storage_scope=args.storage_scope,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
