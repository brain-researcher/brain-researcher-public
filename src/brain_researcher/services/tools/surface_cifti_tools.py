"""Surface and CIFTI neuroimaging tool wrappers.

Extracted from grandmaster_tools.py (Layer 2 / between-layer block).
Covers volume-to-surface projection, CIFTI processing, CIFTI parcellation,
and surface-map comparison tools.

All grandmaster_tools helpers (_call_wrapper, _ensure_dir) are lazy-imported
inside _run() bodies to avoid circular imports and preserve monkeypatch
contracts that patch grandmaster_tools._call_wrapper.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class MapVolumeToSurfaceArgs(BaseModel):
    volume_img: str = Field(description="3D/4D volume image")
    surf_mesh: str | None = Field(
        default="fsaverage5", description="Surface mesh name or path"
    )
    hemi: str = Field(default="both", description="left|right|both")
    output_file: str | None = Field(
        default=None, description="Optional output surface data file"
    )


class MapVolumeToSurfaceTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "map_volume_to_surface"

    def get_tool_description(self) -> str:
        return "Project NIfTI volume data to cortical surface (wrapper over surface_projection)."

    def get_args_schema(self):
        return MapVolumeToSurfaceArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        """Project volume to surface and save GIFTI outputs."""
        try:
            import nibabel as nib
            import numpy as np
            from nilearn import datasets, surface
        except ImportError as exc:
            return ToolResult(
                status="error", error=f"nibabel/nilearn not available: {exc}", data={}
            )

        params = dict(kwargs)
        # Accept legacy aliases
        if "volume" in params and "volume_img" not in params:
            params["volume_img"] = params.pop("volume")
        if "surface" in params and "surf_mesh" not in params:
            params["surf_mesh"] = params.pop("surface")

        volume_img = params.get("volume_img")
        surf_mesh = params.get("surf_mesh", "fsaverage5")
        hemi = params.get("hemi", "both")
        output_file = params.get("output_file")

        if not volume_img:
            return ToolResult(status="error", error="volume_img is required", data={})

        if not output_file:
            output_file = str(Path.cwd() / "surface_projection.func.gii")

        if surf_mesh in ["fsaverage", "fsaverage5"]:
            fsaverage = datasets.fetch_surf_fsaverage(mesh=surf_mesh)
            surf_mesh_left = fsaverage.pial_left
            surf_mesh_right = fsaverage.pial_right
        else:
            surf_mesh_left = surf_mesh
            surf_mesh_right = surf_mesh

        out_paths: dict[str, str] = {}
        base_path = Path(output_file).expanduser().resolve()
        base_path.parent.mkdir(parents=True, exist_ok=True)

        def _save_gifti(data: Any, out_path: Path) -> None:
            darray = nib.gifti.GiftiDataArray(data=np.asarray(data, dtype=np.float32))
            img = nib.gifti.GiftiImage(darrays=[darray])
            nib.save(img, str(out_path))

        if hemi in ("left", "both") and surf_mesh_left:
            tex_left = surface.vol_to_surf(str(volume_img), surf_mesh_left, kind="line")
            out_left = base_path
            if hemi == "both":
                out_left = base_path.with_name(f"{base_path.stem}_L{base_path.suffix}")
            _save_gifti(tex_left, out_left)
            out_paths["left"] = str(out_left)

        if hemi in ("right", "both") and surf_mesh_right:
            tex_right = surface.vol_to_surf(
                str(volume_img), surf_mesh_right, kind="line"
            )
            out_right = base_path
            if hemi == "both":
                out_right = base_path.with_name(f"{base_path.stem}_R{base_path.suffix}")
            _save_gifti(tex_right, out_right)
            out_paths["right"] = str(out_right)

        return ToolResult(
            status="success",
            data={
                "outputs": {"surfaces": out_paths},
                "summary": {
                    "volume": str(volume_img),
                    "surface": surf_mesh,
                    "hemi": hemi,
                },
            },
        )


class ProcessCiftiArgs(BaseModel):
    cifti_in: str = Field(description="Input CIFTI file")
    smoothing_fwhm: float = Field(default=2.0, description="Smoothing kernel (mm)")
    output_dir: str | None = Field(default=None, description="Output directory")


class ProcessCiftiTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "process_cifti"

    def get_tool_description(self) -> str:
        return "Process CIFTI (currently: smoothing via HCP Workbench if available)."

    def get_args_schema(self):
        return ProcessCiftiArgs

    def _run(
        self,
        cifti_in: str,
        smoothing_fwhm: float = 2.0,
        output_dir: str | None = None,
        **_: Any,
    ) -> ToolResult:
        from brain_researcher.services.tools.grandmaster_tools import (
            _call_wrapper,
            _ensure_dir,
        )

        out_root = _ensure_dir(output_dir or (Path.cwd() / "process_cifti"))
        cifti_out = out_root / "processed.dscalar.nii"
        try:
            from brain_researcher.services.tools.hcp_workbench_tool import (
                CiftiSmoothingTool,
            )

            tool = CiftiSmoothingTool()
            return _call_wrapper(
                tool,
                {
                    "cifti_in": cifti_in,
                    "surface_kernel_size": float(smoothing_fwhm),
                    "volume_kernel_size": float(smoothing_fwhm),
                    "cifti_out": str(cifti_out),
                },
            )
        except Exception:
            # Fallback: copy input as-is and report no smoothing applied.
            try:
                shutil.copy(cifti_in, cifti_out)
            except Exception as exc:
                return ToolResult(
                    status="error",
                    error=str(exc),
                    data={
                        "suggestions": [
                            "cifti_smoothing",
                            "hcp_workbench",
                            "niwrap_search",
                        ]
                    },
                )
            return ToolResult(
                status="success",
                data={
                    "outputs": {"cifti_out": str(cifti_out)},
                    "summary": {"input": cifti_in, "applied_smoothing": False},
                },
            )


class ParcellateCiftiArgs(BaseModel):
    cifti_in: str | None = Field(
        default=None, description="Input CIFTI/GIFTI/volume file"
    )
    cifti_file: str | None = Field(default=None, description="Alias for cifti_in")
    atlas: str = Field(description="Atlas/parcellation definition")
    output_dir: str | None = Field(default=None, description="Output directory")
    output_file: str | None = Field(default=None, description="Optional output file")


class ParcellateCiftiTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "parcellate_cifti"

    def get_tool_description(self) -> str:
        return "Parcellate CIFTI into ROI signals (TODO: wire to workbench/cifti-parcellate)."

    def get_args_schema(self):
        return ParcellateCiftiArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        from brain_researcher.services.tools.grandmaster_tools import _ensure_dir

        try:
            import nibabel as nib
            import numpy as np
        except ImportError as exc:
            return ToolResult(
                status="error", error=f"nibabel not available: {exc}", data={}
            )

        args = ParcellateCiftiArgs(**kwargs)
        cifti_path = args.cifti_in or args.cifti_file
        if not cifti_path:
            return ToolResult(
                status="error", error="cifti_in/cifti_file is required", data={}
            )
        cifti_path = str(Path(cifti_path).expanduser().resolve())

        atlas_path = str(Path(args.atlas).expanduser().resolve())
        out_dir = _ensure_dir(args.output_dir or (Path.cwd() / "parcellate_cifti"))
        out_path = (
            Path(args.output_file).expanduser().resolve()
            if args.output_file
            else out_dir / "parcellation.func.gii"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)

        def _load_surface_data(path: str) -> np.ndarray:
            obj = nib.load(path)
            if isinstance(obj, nib.gifti.GiftiImage):
                data = obj.agg_data()
            elif hasattr(nib, "Cifti2Image") and isinstance(obj, nib.Cifti2Image):
                data = np.asarray(obj.get_fdata())
            else:
                raise ValueError("Unsupported surface map format")
            data = np.asarray(data)
            if data.ndim == 2:
                data = data.mean(axis=0)
            return data.ravel()

        def _load_surface_labels(path: str) -> np.ndarray:
            obj = nib.load(path)
            if isinstance(obj, nib.gifti.GiftiImage):
                labels = np.asarray(obj.agg_data()).ravel()
            elif hasattr(nib, "Cifti2Image") and isinstance(obj, nib.Cifti2Image):
                labels = np.asarray(obj.get_fdata()).ravel()
            else:
                raise ValueError("Unsupported surface atlas format")
            return labels

        # Determine if surface or volume
        if (
            Path(cifti_path).suffix in {".nii", ".gz", ".gii"}
            or "cifti" in cifti_path.lower()
        ):
            pass

        try:
            data = _load_surface_data(cifti_path)
            labels = _load_surface_labels(atlas_path)
            if data.shape[0] != labels.shape[0]:
                return ToolResult(
                    status="error",
                    error="Surface data and atlas have different lengths",
                    data={},
                )

            unique_labels = np.unique(labels[labels > 0])
            parcel_means = {}
            vertex_values = np.zeros_like(data, dtype=float)
            for lbl in unique_labels:
                mask = labels == lbl
                if mask.sum() == 0:
                    continue
                mean_val = float(np.mean(data[mask]))
                parcel_means[int(lbl)] = mean_val
                vertex_values[mask] = mean_val

            if out_path.suffix.endswith(".gii"):
                darray = nib.gifti.GiftiDataArray(data=vertex_values.astype(np.float32))
                img = nib.gifti.GiftiImage(darrays=[darray])
                nib.save(img, str(out_path))
                outputs = {"parcellated_gifti": str(out_path)}
            else:
                import pandas as pd

                df = pd.DataFrame(
                    [
                        {"label": int(k), "mean": float(v)}
                        for k, v in parcel_means.items()
                    ]
                )
                df.to_csv(out_path, sep="\t", index=False)
                outputs = {"table": str(out_path)}

            return ToolResult(
                status="success",
                data={
                    "outputs": outputs,
                    "summary": {
                        "n_labels": int(len(parcel_means)),
                        "atlas": atlas_path,
                        "input": cifti_path,
                    },
                },
            )
        except Exception:
            # Volume fallback: atlas & volume must be NIfTI
            try:
                import pandas as pd
                from nilearn import image as nl_image

                vol = nib.load(cifti_path)
                atlas = nib.load(atlas_path)
                if vol.shape[:3] != atlas.shape[:3]:
                    atlas = nl_image.resample_to_img(
                        atlas, vol, interpolation="nearest"
                    )
                data = vol.get_fdata()
                labels = atlas.get_fdata()
                uniq = sorted(int(x) for x in np.unique(labels) if x > 0)
                rows = []
                for lbl in uniq:
                    mask = labels == lbl
                    if mask.sum() == 0:
                        continue
                    rows.append({"label": lbl, "mean": float(data[mask].mean())})
                df = pd.DataFrame(rows)
                df.to_csv(out_path, sep="\t", index=False)
                return ToolResult(
                    status="success",
                    data={
                        "outputs": {"table": str(out_path)},
                        "summary": {
                            "n_labels": len(rows),
                            "atlas": atlas_path,
                            "input": cifti_path,
                        },
                    },
                )
            except Exception as exc:
                return ToolResult(
                    status="error",
                    error=str(exc),
                    data={
                        "suggestions": ["process_cifti", "get_atlas", "niwrap_search"]
                    },
                )


class CompareSurfaceMapsArgs(BaseModel):
    map_a: str = Field(description="Surface map A")
    map_b: str = Field(description="Surface map B")
    method: str = Field(default="spin", description="Comparison method")


class CompareSurfaceMapsTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "compare_surface_maps"

    def get_tool_description(self) -> str:
        return "Compare surface maps with spatial autocorrelation correction (spin tests via neuromaps)."

    def get_args_schema(self):
        return CompareSurfaceMapsArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        try:
            from brain_researcher.services.tools.grandmaster.runtime_tools import (
                compare_surface_maps_tool,
            )

            result = compare_surface_maps_tool(
                map1=kwargs.get("map_a") or kwargs.get("map1") or kwargs.get("map"),
                map2=kwargs.get("map_b")
                or kwargs.get("map2")
                or kwargs.get("reference"),
                method=kwargs.get("method", "pearson"),
                null_permutations=kwargs.get("null_permutations", 0),
                output_file=kwargs.get("output_file"),
            )
            if isinstance(result, ToolResult):
                return result
            return ToolResult(status=result.get("status", "success"), data=result)
        except Exception as exc:  # pragma: no cover
            return ToolResult(
                status="error",
                error=str(exc),
                data={"suggestions": ["surface_projection", "process_cifti"]},
            )


__all__ = [
    "CompareSurfaceMapsArgs",
    "CompareSurfaceMapsTool",
    "MapVolumeToSurfaceArgs",
    "MapVolumeToSurfaceTool",
    "ParcellateCiftiArgs",
    "ParcellateCiftiTool",
    "ProcessCiftiArgs",
    "ProcessCiftiTool",
]
