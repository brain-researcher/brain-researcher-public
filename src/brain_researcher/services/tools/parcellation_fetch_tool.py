"""Registry-backed tool for fetching standard brain parcellations/atlases."""

from __future__ import annotations

from pathlib import Path

import nibabel.freesurfer.io as fsio
from pydantic import BaseModel, Field

from brain_researcher.services.tools.atlas_utils import (
    atlas_family_output_root,
    default_atlas_output_root,
    parse_yeo_networks,
    resolve_local_volume_atlas,
    symbolic_atlas_family,
    write_labels_sidecars,
)
from brain_researcher.services.tools.neuroimage_asset_registry import (
    atlas_cache_roots,
    normalize_space_request,
)
from brain_researcher.services.tools.reference_asset_registry import (
    find_reference_asset,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

_SURFACE_FSAVERAGE_DIRS = {
    "10k": "fsaverage5",
    "41k": "fsaverage6",
    "164k": "fsaverage",
}
_SURFACE_ATLAS_RELATIVE_ROOTS = (
    Path("Yeo_JNeurophysiol11_FreeSurfer"),
    Path("yeo_2011") / "Yeo_JNeurophysiol11_FreeSurfer",
)


class ParcellationFetchArgs(BaseModel):
    """Arguments for fetching brain parcellations."""

    atlas_name: str = Field(
        description="Atlas identifier (Schaefer2018_200, Yeo17, aparc, aparc.a2009s)."
    )
    space: str = Field(
        default="MNI152NLin2009cAsym",
        description="Target template space or surface (for example MNI152NLin2009cAsym, fsaverage).",
    )
    resolution: str | None = Field(
        default=None,
        description="Volume resolution (1mm, 2mm) or surface density (10k, 41k, 164k).",
    )


def _copy_local_asset(src: Path, output_root: Path, name: str | None = None) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    dest = output_root / (name or src.name)
    if dest.resolve() != src.resolve():
        dest.write_bytes(src.read_bytes())
    return dest


def _normalize_label_names(labels: list[object]) -> list[str]:
    normalized: list[str] = []
    for label in labels:
        if isinstance(label, bytes):
            normalized.append(label.decode("utf-8", errors="replace"))
        else:
            normalized.append(str(label))
    return normalized


def _count_regions(labels: list[str]) -> int:
    if not labels:
        return 0
    first = labels[0].strip().lower()
    if first in {"background", "unknown", "???", "medial_wall"}:
        return max(len(labels) - 1, 0)
    return len(labels)


def _search_roots_from_registry() -> list[Path]:
    roots = [root for root in atlas_cache_roots() if root.exists()]
    if not roots:
        raise FileNotFoundError(
            "No atlas cache roots are available from the neuroimage asset registry."
        )
    return roots


def _volume_output_root(atlas_name: str, output_dir: str | None) -> Path:
    if output_dir:
        root = Path(output_dir)
    else:
        atlas_root = default_atlas_output_root()
        family = symbolic_atlas_family(atlas_name) or "atlas"
        root = atlas_family_output_root(atlas_root, family)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_local_volume_atlas(
    atlas_name: str,
    roots: list[Path],
) -> tuple[Path, list[str], str]:
    return resolve_local_volume_atlas(atlas_name, roots)


def _surface_annotation_filename(atlas_name: str) -> str:
    atlas_key = str(atlas_name or "").strip().lower()
    if atlas_key in {"aparc", "desikan", "desikan-killiany", "dk"}:
        return "aparc.annot"
    if atlas_key in {"aparc.a2009s", "aparc_a2009s", "destrieux"}:
        return "aparc.a2009s.annot"
    if "yeo" in atlas_key:
        return f"Yeo2011_{parse_yeo_networks(atlas_name)}Networks_N1000.annot"
    raise ValueError(
        "Unsupported surface atlas_name. Supported names: yeo, yeo17, aparc, aparc.a2009s."
    )


def _surface_label_dir(roots: list[Path], density: str) -> Path:
    fsaverage_dir = _SURFACE_FSAVERAGE_DIRS.get(density)
    if fsaverage_dir is None:
        raise ValueError(
            f"Unsupported fsaverage density '{density}' for surface parcellation lookup."
        )

    for root in roots:
        for rel in _SURFACE_ATLAS_RELATIVE_ROOTS:
            candidate = root / rel / fsaverage_dir / "label"
            if candidate.exists():
                return candidate
    raise FileNotFoundError(
        f"Surface atlas labels for density '{density}' were not found under registry atlas roots."
    )


def _read_annot_label_names(path: Path) -> list[str]:
    _, _, names = fsio.read_annot(path)
    return _normalize_label_names(list(names))


def _merge_label_sets(*label_sets: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for labels in label_sets:
        for label in labels:
            if label not in seen:
                seen.add(label)
                merged.append(label)
    return merged


class ParcellationFetchTool(NeuroToolWrapper):
    """Fetch standard brain parcellation/atlas assets from local registry-backed caches."""

    execution_backend = "python"

    def get_tool_name(self) -> str:
        return "parcellation_fetch"

    def get_tool_description(self) -> str:
        return "Fetch standard brain parcellation/atlas assets from local registry-backed caches."

    def get_args_schema(self):
        return ParcellationFetchArgs

    def _run(self, **kwargs) -> ToolResult:
        output_dir = kwargs.get("output_dir")
        args = ParcellationFetchArgs(**kwargs)

        try:
            space = normalize_space_request(args.space, args.resolution)
            roots = _search_roots_from_registry()
            output_root = _volume_output_root(args.atlas_name, output_dir)
            asset_record = find_reference_asset(args.atlas_name, kind="atlas")

            if space["space_kind"] == "volume":
                atlas_path, labels, family = _resolve_local_volume_atlas(
                    args.atlas_name,
                    roots,
                )
                local_copy = _copy_local_asset(atlas_path, output_root)
                labels_tsv, labels_json = write_labels_sidecars(local_copy, labels)
                native_space = (
                    "MNI152_FreeSurferConformed1mm"
                    if "yeo" in args.atlas_name.lower()
                    else "FSLMNI152_2mm"
                )
                return ToolResult(
                    status="success",
                    data={
                        "outputs": {
                            "parcellation_volume": str(local_copy),
                            "labels_tsv": str(labels_tsv),
                            "labels_json": str(labels_json),
                        },
                        "summary": {
                            "atlas": args.atlas_name,
                            "family": family,
                            "space": args.space,
                            "canonical_space": space["canonical_space"],
                            "space_kind": space["space_kind"],
                            "resolution": space["resolved_resolution"],
                            "atlas_native_space": native_space,
                            "n_regions": _count_regions(labels),
                            "source": "registry_local_cache",
                            "registry_entry": "local_nilearn_atlas_cache",
                            "reference_asset": asset_record,
                        },
                    },
                )

            if space["canonical_space"] != "fsaverage":
                raise ValueError(
                    "Surface parcellation lookup currently supports fsaverage densities only."
                )

            label_dir = _surface_label_dir(roots, space["resolved_resolution"])
            filename = _surface_annotation_filename(args.atlas_name)
            left_src = label_dir / f"lh.{filename}"
            right_src = label_dir / f"rh.{filename}"
            if not left_src.exists() or not right_src.exists():
                raise FileNotFoundError(
                    f"Surface atlas files not found for '{args.atlas_name}' in {label_dir}"
                )

            left_copy = _copy_local_asset(left_src, output_root)
            right_copy = _copy_local_asset(right_src, output_root)
            labels = _merge_label_sets(
                _read_annot_label_names(left_src),
                _read_annot_label_names(right_src),
            )
            labels_tsv, labels_json = write_labels_sidecars(left_copy, labels)

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "parcellation_volume": str(left_copy),
                        "surface_parcellation_left": str(left_copy),
                        "surface_parcellation_right": str(right_copy),
                        "labels_tsv": str(labels_tsv),
                        "labels_json": str(labels_json),
                    },
                    "summary": {
                        "atlas": args.atlas_name,
                        "family": "surface_annotation",
                        "space": args.space,
                        "canonical_space": space["canonical_space"],
                        "space_kind": space["space_kind"],
                        "resolution": space["resolved_resolution"],
                        "atlas_native_space": f"fsaverage/{space['resolved_resolution']}",
                        "n_regions": _count_regions(labels),
                        "source": "registry_local_cache",
                        "registry_entry": "local_nilearn_atlas_cache",
                        "reference_asset": asset_record,
                    },
                },
            )
        except Exception as exc:
            return ToolResult(
                status="error",
                error=str(exc),
                data={
                    "requested_atlas": args.atlas_name,
                    "requested_space": args.space,
                    "requested_resolution": args.resolution,
                },
            )


class ParcellationFetchTools:
    @staticmethod
    def get_all_tools():
        return [ParcellationFetchTool()]


__all__ = ["ParcellationFetchTool", "ParcellationFetchTools"]
