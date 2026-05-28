"""Fetch atlas tool for connectivity workflows."""

from __future__ import annotations

import os
import re
from pathlib import Path
from tempfile import gettempdir

import nibabel as nib
import numpy as np
from nilearn import datasets
from pydantic import BaseModel, Field

from brain_researcher.services.tools.atlas_utils import (
    allow_network_atlas_fetch,
    atlas_reference_hints,
    atlas_family_output_root,
    default_atlas_output_root,
    derive_local_atlas_labels,
    discover_local_schaefer_resolutions,
    existing_search_roots,
    fetch_templateflow_difumo_atlas,
    fetch_templateflow_schaefer_atlas,
    find_local_aal_atlas,
    find_local_harvard_oxford_atlas,
    find_local_difumo_atlas,
    find_local_schaefer_atlas,
    find_local_yeo_atlas,
    normalize_harvard_oxford_variant,
    parse_schaefer_n_rois,
    parse_schaefer_yeo_networks,
    parse_yeo_networks,
    resolve_local_volume_atlas,
    symbolic_atlas_family,
    write_labels_sidecars,
)
from brain_researcher.services.tools.reference_asset_registry import (
    find_reference_asset,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

_OUTPUT_ROOT = Path(os.getenv("BR_DEMO_ARTIFACT_DIR", Path(gettempdir()) / "br_demo"))


def _normalize_labels(labels: list[object]) -> list[str]:
    normalized: list[str] = []
    for label in labels:
        if isinstance(label, bytes):
            normalized.append(label.decode("utf-8", errors="replace"))
        else:
            normalized.append(str(label))
    return normalized


def _ensure_local_copy(src: Path, output_root: Path) -> Path:
    atlas_file = output_root / src.name
    if atlas_file.resolve() != src.resolve():
        atlas_file.write_bytes(src.read_bytes())
    return atlas_file


def _materialize_fetched_map(
    maps: object,
    output_root: Path,
    filename_hint: str,
) -> Path:
    atlas_file = output_root / filename_hint
    if isinstance(maps, str | os.PathLike):
        return _ensure_local_copy(Path(maps), output_root)
    nib.save(maps, atlas_file)
    return atlas_file


class FetchAtlasArgs(BaseModel):
    atlas_name: str = Field(default="Schaefer2018_200", description="Atlas identifier")
    output_dir: str | None = Field(
        default=None, description="Output directory for atlas files"
    )
    reference_img: str | None = Field(
        default=None,
        description=(
            "Optional reference image path. When atlas_name is synthetic/demo/test, "
            "generate the atlas in the reference image's space."
        ),
    )
    data_dir: str | None = Field(
        default=None, description="Nilearn dataset cache directory"
    )
    atlas_path: str | None = Field(
        default=None, description="Local atlas file path (skip download)"
    )
    labels: list[str] | None = Field(
        default=None, description="Labels for local atlas (optional)"
    )


class FetchAtlasTool(NeuroToolWrapper):
    """Fetch or generate a neuroimaging atlas."""

    execution_backend = "python"
    inject_execution_output_dir = False

    def get_tool_name(self) -> str:
        return "fetch_atlas"

    def get_tool_description(self) -> str:
        return "Fetch or generate an atlas for connectivity workflows."

    def get_args_schema(self):
        return FetchAtlasArgs

    def _run(
        self,
        atlas_name: str = "Schaefer2018_200",
        output_dir: str | None = None,
        reference_img: str | None = None,
        data_dir: str | None = None,
        atlas_path: str | None = None,
        labels: list[str] | None = None,
        **kwargs,
    ) -> ToolResult:
        asset_record = find_reference_asset(atlas_name, kind="atlas")
        resolved_atlas_name = (
            str(asset_record.get("canonical_runtime_name") or atlas_name)
            if asset_record
            else atlas_name
        )
        name_lower = resolved_atlas_name.lower()
        if output_dir:
            output_root = Path(output_dir)
        elif name_lower in {"synthetic", "demo", "test"}:
            output_root = _OUTPUT_ROOT
        else:
            atlas_root = default_atlas_output_root()
            output_root = atlas_family_output_root(
                atlas_root,
                symbolic_atlas_family(resolved_atlas_name) or "",
            )
        output_root.mkdir(parents=True, exist_ok=True)

        if atlas_path:
            src = Path(atlas_path)
            if not src.exists():
                return ToolResult(status="error", error="atlas_path not found", data={})
            atlas_file = _ensure_local_copy(src, output_root)
            if labels:
                labels_list = labels
            else:
                labels_list = derive_local_atlas_labels(
                    src, atlas_name=resolved_atlas_name
                )
            labels_tsv, labels_json = write_labels_sidecars(atlas_file, labels_list)
            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "atlas_path": str(atlas_file),
                        "labels_tsv": str(labels_tsv),
                        "labels_json": str(labels_json),
                    },
                    "summary": {
                        "atlas": atlas_name,
                        "resolved_atlas": resolved_atlas_name,
                        "labels": len(labels_list),
                        "source": "local",
                        "reference_asset": asset_record,
                    },
                },
            )

        if name_lower in {"synthetic", "demo", "test"}:
            atlas_file = output_root / f"{resolved_atlas_name}.nii.gz"
            affine = np.eye(4)
            shape = (4, 4, 4)
            if reference_img:
                ref = Path(reference_img)
                if ref.exists():
                    ref_img = nib.load(ref)
                    affine = ref_img.affine
                    ref_shape = ref_img.shape[:3]
                    if len(ref_shape) == 3 and ref_shape[0] >= 2:
                        shape = tuple(int(v) for v in ref_shape)  # type: ignore[assignment]
            data = np.zeros(shape, dtype="int16")
            mid = max(1, int(shape[0] // 2))
            data[:mid, :, :] = 1
            data[mid:, :, :] = 2
            img = nib.Nifti1Image(data, affine=affine)
            nib.save(img, atlas_file)
            labels_list = ["background", "roi_001", "roi_002"]
            labels_tsv, labels_json = write_labels_sidecars(atlas_file, labels_list)
            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "atlas_path": str(atlas_file),
                        "labels_tsv": str(labels_tsv),
                        "labels_json": str(labels_json),
                    },
                    "summary": {
                        "atlas": atlas_name,
                        "resolved_atlas": resolved_atlas_name,
                        "labels": len(labels_list),
                        "source": "synthetic",
                        "reference_asset": asset_record,
                    },
                },
            )

        atlas_source = "nilearn"
        atlas_family = (
            str(asset_record.get("family") or "").strip() if asset_record else ""
        )
        labels_list: list[str]
        reference_space, reference_resolution = atlas_reference_hints(reference_img)
        search_roots = existing_search_roots(data_dir, output_root)
        allow_network = allow_network_atlas_fetch()
        resolve_legacy_schaefer = not name_lower.startswith("schaefer2018")
        try:
            local_path, local_labels, local_family = resolve_local_volume_atlas(
                resolved_atlas_name,
                search_roots,
                space=reference_space,
                resolution=reference_resolution,
                include_legacy_schaefer=resolve_legacy_schaefer,
            )
        except (FileNotFoundError, ValueError):
            local_path = None
            local_labels = []
            local_family = ""

        if local_path is not None:
            atlas_file = _ensure_local_copy(local_path, output_root)
            labels_list = local_labels
            atlas_source = "local_cache"
            atlas_family = atlas_family or local_family
        if name_lower.startswith("schaefer2018"):
            n_rois = parse_schaefer_n_rois(resolved_atlas_name)
            n_networks = parse_schaefer_yeo_networks(resolved_atlas_name)
            if local_path is None:
                local_atlas = find_local_schaefer_atlas(
                    n_rois=n_rois,
                    roots=search_roots,
                    yeo_networks=n_networks,
                    space=reference_space,
                    resolution=reference_resolution,
                    include_legacy=False,
                )
            else:
                local_atlas = local_path

            if local_path is None and local_atlas is None:
                if not allow_network:
                    legacy_atlas = find_local_schaefer_atlas(
                        n_rois=n_rois,
                        roots=search_roots,
                        yeo_networks=n_networks,
                        space=reference_space,
                        resolution=reference_resolution,
                    )
                    if legacy_atlas is not None:
                        atlas_file = _ensure_local_copy(legacy_atlas, output_root)
                        labels_list = derive_local_atlas_labels(
                            legacy_atlas,
                            atlas_name=resolved_atlas_name,
                            family="schaefer_2018",
                        )
                        atlas_source = "local_cache"
                        atlas_family = atlas_family or "schaefer_2018"
                    else:
                        available = discover_local_schaefer_resolutions(search_roots)
                        return ToolResult(
                            status="error",
                            error="atlas_not_found_local",
                            data={
                                "requested_atlas": atlas_name,
                                "requested_resolution": n_rois,
                                "searched_roots": [str(root) for root in search_roots],
                                "available_schaefer_resolutions": available,
                                "message": (
                                    "Schaefer atlas not found locally. "
                                    "Set BR_ATLAS_SEARCH_ROOTS or mount atlas files to "
                                    "/app/data/atlases."
                                ),
                            },
                        )
                else:
                    fetched_templateflow_atlas = fetch_templateflow_schaefer_atlas(
                        n_rois=n_rois,
                        yeo_networks=n_networks,
                        space=reference_space,
                        resolution=reference_resolution,
                    )
                    if fetched_templateflow_atlas is not None:
                        atlas_file = _ensure_local_copy(
                            fetched_templateflow_atlas,
                            output_root,
                        )
                        labels_list = derive_local_atlas_labels(
                            fetched_templateflow_atlas,
                            atlas_name=resolved_atlas_name,
                            family="schaefer_2018",
                        )
                        atlas_source = "templateflow_api_download"
                        atlas_family = atlas_family or "schaefer_2018"
                    else:
                        legacy_atlas = find_local_schaefer_atlas(
                            n_rois=n_rois,
                            roots=search_roots,
                            yeo_networks=n_networks,
                            space=reference_space,
                            resolution=reference_resolution,
                        )
                        if legacy_atlas is not None:
                            atlas_file = _ensure_local_copy(legacy_atlas, output_root)
                            labels_list = derive_local_atlas_labels(
                                legacy_atlas,
                                atlas_name=resolved_atlas_name,
                                family="schaefer_2018",
                            )
                            atlas_source = "local_cache"
                            atlas_family = atlas_family or "schaefer_2018"
                        else:
                            atlas = datasets.fetch_atlas_schaefer_2018(
                                n_rois=n_rois,
                                resolution_mm=2,
                                yeo_networks=n_networks,
                                data_dir=data_dir or str(output_root),
                                verbose=0,
                            )
                            atlas_file = _materialize_fetched_map(
                                atlas.maps,
                                output_root,
                                (
                                    f"Schaefer2018_{n_rois}Parcels_{n_networks}Networks_"
                                    "order_FSLMNI152_2mm.nii.gz"
                                ),
                            )
                            labels_list = _normalize_labels(list(atlas.labels))
                            atlas_source = "nilearn_download"
                            atlas_family = atlas_family or "schaefer_2018"
            elif local_path is None:
                atlas_file = _ensure_local_copy(local_atlas, output_root)
                atlas_source = "local_cache"
                labels_list = derive_local_atlas_labels(
                    local_atlas,
                    atlas_name=resolved_atlas_name,
                    family="schaefer_2018",
                )
                atlas_family = atlas_family or "schaefer_2018"
        elif name_lower in {"aal", "aal_2mm", "aal3"}:
            local_atlas = (
                find_local_aal_atlas(roots=search_roots)
                if local_path is None
                else local_path
            )
            if (
                local_path is None
                and local_atlas is None
                and not allow_network_atlas_fetch()
            ):
                return ToolResult(
                    status="error",
                    error="atlas_not_found_local",
                    data={
                        "requested_atlas": atlas_name,
                        "searched_roots": [str(root) for root in search_roots],
                        "message": (
                            "AAL atlas not found locally. "
                            "Set BR_ATLAS_SEARCH_ROOTS or mount atlas files to "
                            "/app/data/atlases."
                        ),
                    },
                )
            if local_path is None and local_atlas is not None:
                atlas_file = _ensure_local_copy(local_atlas, output_root)
                labels_list = derive_local_atlas_labels(
                    local_atlas,
                    atlas_name=atlas_name,
                    family="aal",
                )
                atlas_source = "local_cache"
                atlas_family = atlas_family or "aal"
            elif local_path is None:
                output_root.mkdir(parents=True, exist_ok=True)
                atlas = datasets.fetch_atlas_aal(
                    data_dir=data_dir or str(output_root), verbose=0
                )
                atlas_file = _materialize_fetched_map(
                    atlas.maps,
                    output_root,
                    "AAL.nii.gz",
                )
                labels_list = _normalize_labels(list(atlas.labels))
                atlas_source = "nilearn_download"
                atlas_family = atlas_family or "aal"
        elif "harvard" in name_lower:
            variant = normalize_harvard_oxford_variant(resolved_atlas_name)
            local_atlas = (
                find_local_harvard_oxford_atlas(
                    variant=variant,
                    roots=search_roots,
                )
                if local_path is None
                else local_path
            )
            if (
                local_path is None
                and local_atlas is None
                and not allow_network_atlas_fetch()
            ):
                return ToolResult(
                    status="error",
                    error="atlas_not_found_local",
                    data={
                        "requested_atlas": atlas_name,
                        "requested_variant": variant,
                        "searched_roots": [str(root) for root in search_roots],
                        "message": (
                            "Harvard-Oxford atlas not found locally. "
                            "Set BR_ATLAS_SEARCH_ROOTS or mount atlas files to "
                            "/app/data/atlases."
                        ),
                    },
                )
            if local_path is None and local_atlas is not None:
                atlas_file = _ensure_local_copy(local_atlas, output_root)
                labels_list = derive_local_atlas_labels(
                    local_atlas,
                    atlas_name=resolved_atlas_name,
                    family="harvard_oxford",
                )
                atlas_source = "local_cache"
                atlas_family = atlas_family or "harvard_oxford"
            elif local_path is None:
                atlas = datasets.fetch_atlas_harvard_oxford(
                    atlas_name=variant,
                    data_dir=data_dir or str(output_root),
                )
                atlas_file = _materialize_fetched_map(
                    atlas.maps,
                    output_root,
                    f"HarvardOxford-{variant}.nii.gz",
                )
                labels_list = _normalize_labels(list(atlas.labels))
                atlas_source = "nilearn_download"
                atlas_family = atlas_family or "harvard_oxford"
        elif "yeo" in name_lower:
            n_networks = parse_yeo_networks(resolved_atlas_name)
            local_atlas = (
                find_local_yeo_atlas(n_networks=n_networks, roots=search_roots)
                if local_path is None
                else local_path
            )
            if (
                local_path is None
                and local_atlas is None
                and not allow_network_atlas_fetch()
            ):
                return ToolResult(
                    status="error",
                    error="atlas_not_found_local",
                    data={
                        "requested_atlas": atlas_name,
                        "requested_networks": n_networks,
                        "searched_roots": [str(root) for root in search_roots],
                        "message": (
                            "Yeo atlas not found locally. "
                            "Set BR_ATLAS_SEARCH_ROOTS or mount atlas files to "
                            "/app/data/atlases."
                        ),
                    },
                )
            if local_path is None and local_atlas is not None:
                atlas_file = _ensure_local_copy(local_atlas, output_root)
                labels_list = derive_local_atlas_labels(
                    local_atlas,
                    atlas_name=resolved_atlas_name,
                    family="yeo_2011",
                )
                atlas_source = "local_cache"
                atlas_family = atlas_family or "yeo_2011"
            elif local_path is None:
                atlas = datasets.fetch_atlas_yeo_2011(
                    n_networks=n_networks,
                    thickness="thick",
                    data_dir=data_dir or str(output_root),
                )
                atlas_file = _materialize_fetched_map(
                    atlas.maps,
                    output_root,
                    atlas.maps.split("/")[-1]
                    if isinstance(atlas.maps, str)
                    else f"Yeo2011_{n_networks}Networks_MNI152_FreeSurferConformed1mm_LiberalMask.nii.gz",
                )
                labels_list = _normalize_labels(list(atlas.labels))
                atlas_source = "nilearn_download"
                atlas_family = atlas_family or "yeo_2011"
        elif "difumo" in name_lower:
            match = re.search(r"(\d+)", resolved_atlas_name)
            dimension = int(match.group(1)) if match else 512
            if local_path is None:
                local_atlas = find_local_difumo_atlas(
                    search_roots,
                    dimension=dimension,
                    space=reference_space,
                    resolution=reference_resolution,
                )
            else:
                local_atlas = local_path
            if (
                local_path is None
                and local_atlas is None
                and not allow_network_atlas_fetch()
            ):
                return ToolResult(
                    status="error",
                    error="atlas_not_found_local",
                    data={
                        "requested_atlas": atlas_name,
                        "requested_dimension": dimension,
                        "searched_roots": [str(root) for root in search_roots],
                        "message": (
                            "DiFuMo atlas not found locally. "
                            "Set BR_ATLAS_SEARCH_ROOTS or mount atlas files to "
                            "/app/data/atlases."
                        ),
                    },
                )
            if local_path is None and local_atlas is not None:
                atlas_file = _ensure_local_copy(local_atlas, output_root)
                labels_list = derive_local_atlas_labels(
                    local_atlas,
                    atlas_name=resolved_atlas_name,
                    family="difumo",
                )
                atlas_source = "local_cache"
                atlas_family = atlas_family or "difumo"
            elif local_path is None:
                fetched_templateflow_atlas = fetch_templateflow_difumo_atlas(
                    dimension=dimension,
                    space=reference_space,
                    resolution=reference_resolution,
                )
                if fetched_templateflow_atlas is not None:
                    atlas_file = _ensure_local_copy(
                        fetched_templateflow_atlas,
                        output_root,
                    )
                    labels_list = derive_local_atlas_labels(
                        fetched_templateflow_atlas,
                        atlas_name=resolved_atlas_name,
                        family="difumo",
                    )
                    atlas_source = "templateflow_api_download"
                    atlas_family = atlas_family or "difumo"
                else:
                    atlas = datasets.fetch_atlas_difumo(
                        dimension=dimension,
                        resolution_mm=2,
                        data_dir=data_dir or str(output_root),
                        verbose=0,
                    )
                    atlas_file = _materialize_fetched_map(
                        atlas.maps,
                        output_root,
                        (
                            f"DiFuMo_dimension-{dimension}_data-MNI152_2mm.nii.gz"
                        ),
                    )
                    labels_list = _normalize_labels(list(atlas.labels))
                    atlas_source = "nilearn_download"
                    atlas_family = atlas_family or "difumo"
        elif local_path is None:
            return ToolResult(
                status="error",
                error=f"Unsupported atlas_name: {atlas_name}",
                data={},
            )
        else:
            atlas_family = atlas_family or local_family

        labels_list = _normalize_labels(labels_list)
        labels_tsv, labels_json = write_labels_sidecars(atlas_file, labels_list)
        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "atlas_path": str(atlas_file),
                    "labels_tsv": str(labels_tsv),
                    "labels_json": str(labels_json),
                },
                "summary": {
                    "atlas": atlas_name,
                    "resolved_atlas": resolved_atlas_name,
                    "family": atlas_family,
                    "labels": len(labels_list),
                    "source": atlas_source,
                    "reference_space": reference_space,
                    "reference_resolution": reference_resolution,
                    "reference_asset": asset_record,
                },
            },
        )


__all__ = ["FetchAtlasTool"]
