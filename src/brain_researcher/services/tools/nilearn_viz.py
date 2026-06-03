"""
Nilearn Visualization Tools

Provides tools for visualizing statistical maps and projecting data onto surfaces.
"""

from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field
import numpy as np
import logging
import os

from brain_researcher.services.tools.tool_base import NeuroToolWrapper
from brain_researcher.services.tools.result import ToolResult
from brain_researcher.services.tools.spec import ToolExample

logger = logging.getLogger(__name__)


# =============================================================================
# 1. Statistical Map Visualization Tool
# =============================================================================

class VizStatMapArgs(BaseModel):
    """Arguments for statistical map visualization."""

    stat_map: str = Field(description="Path to statistical map")
    bg_img: Optional[str] = Field(None, description="Background anatomical image or 'MNI152'")
    threshold: Optional[Union[float, str]] = Field(None, description="Threshold for display or 'auto'")
    cmap: str = Field(default="cold_hot", description="Colormap name")
    display_mode: str = Field(default="ortho", description="Display: 'ortho', 'x', 'y', 'z', 'mosaic', 'tiled'")
    cut_coords: Optional[Union[int, List[float]]] = Field(None, description="Slice coordinates or number of slices")
    title: Optional[str] = Field(None, description="Plot title")
    output_file: Optional[str] = Field(None, description="Save figure to file")
    annotate: bool = Field(default=True, description="Add annotations")
    draw_cross: bool = Field(default=True, description="Draw crosshairs")
    black_bg: bool = Field(default=False, description="Use black background")
    symmetric_cbar: bool = Field(default=True, description="Symmetric colorbar")
    preview: bool = Field(default=False, description="If true, don't render figure; return header info only")


class VizStatMapTool(NeuroToolWrapper):
    """Visualize statistical brain maps."""

    name = "viz_stat_maps"
    description = "Create publication-quality visualizations of statistical brain maps with automatic thresholding"
    category = "visualization"

    ARG_SYNONYMS = {
        "stat_map": ["map", "image", "statistical_map"],
        "bg_img": ["background", "anat", "underlay"],
        "threshold": ["thresh", "cutoff"],
        "cmap": ["colormap", "colors"],
        "display_mode": ["view", "mode", "projection"]
    }

    EXAMPLES = [
        ToolExample(
            user_query="Visualize t-statistic map",
            params={
                "stat_map": "group_tstat.nii.gz",
                "threshold": 2.3,
                "cmap": "hot",
                "display_mode": "mosaic",
                "title": "Group activation"
            },
            notes="Mosaic view with thresholding"
        ),
        ToolExample(
            user_query="Create orthogonal slices of contrast",
            params={
                "stat_map": "contrast_zmap.nii.gz",
                "bg_img": "MNI152",
                "threshold": "auto",
                "cut_coords": [0, -52, 18],
                "output_file": "figure.png"
            },
            notes="Orthogonal view at specific coordinates"
        )
    ]

    args_model = VizStatMapArgs

    def get_tool_name(self) -> str:
        return self.name

    def get_tool_description(self) -> str:
        return self.description

    def get_args_schema(self) -> type:
        return self.args_model

    def _run(self, **kwargs) -> ToolResult:
        result = self._invoke(**kwargs)
        if isinstance(result, ToolResult):
            return result
        if isinstance(result, dict):
            return ToolResult(**result)
        return ToolResult(status="error", error="Unexpected result type")

    def _invoke(self, **kwargs) -> ToolResult:
        """Create statistical map visualization."""
        # Force headless backend even if caller forgot to set MPLBACKEND
        from matplotlib import use as mpl_use
        mpl_use("Agg", force=True)

        from nilearn import plotting, datasets
        import matplotlib.pyplot as plt
        import nibabel as nib

        args = VizStatMapArgs(**kwargs)

        # Optional global preview override to avoid rendering during tests / headless runs
        if not args.output_file and os.getenv("VIZ_PREVIEW_ONLY", "0") in {"1", "true", "True"}:
            args.preview = True

        # Short-circuit in preview/smoke mode to avoid heavy rendering
        if args.preview or os.getenv("SMOKE_TEST_MODE", "0") in {"1", "true", "True"}:
            try:
                img = nib.load(args.stat_map)
                header = img.header
                shape = header.get_data_shape()
                affine = img.affine.tolist()
                return ToolResult(
                    status="success",
                    data={
                        "message": "Preview only (no rendering)",
                        "shape": shape,
                        "affine": affine,
                        "preview_only": True,
                    },
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Preview failed in viz_stat_maps: %s", exc)
                return ToolResult(
                    status="error",
                    error=str(exc),
                    data={"preview_only": True},
                )

        # Get background image
        if args.bg_img == "MNI152" or args.bg_img is None:
            bg_img = datasets.load_mni152_template()
        else:
            bg_img = args.bg_img

        # Auto threshold if requested
        threshold = args.threshold
        if threshold == "auto":
            from nilearn.image import get_data
            data = get_data(nib.load(args.stat_map))
            threshold = np.percentile(np.abs(data[data != 0]), 95)

        # Create display
        display = None
        try:
            if args.display_mode == "mosaic":
                display = plotting.plot_stat_map(
                    args.stat_map,
                    bg_img=bg_img,
                    threshold=threshold,
                    cmap=args.cmap,
                    title=args.title,
                    cut_coords=args.cut_coords,
                    annotate=args.annotate,
                    draw_cross=args.draw_cross,
                    black_bg=args.black_bg,
                    symmetric_cbar=args.symmetric_cbar,
                    display_mode='mosaic'
                )
            elif args.display_mode in ["x", "y", "z"]:
                display = plotting.plot_stat_map(
                    args.stat_map,
                    bg_img=bg_img,
                    threshold=threshold,
                    cmap=args.cmap,
                    title=args.title,
                    cut_coords=args.cut_coords or 7,
                    annotate=args.annotate,
                    draw_cross=args.draw_cross,
                    black_bg=args.black_bg,
                    symmetric_cbar=args.symmetric_cbar,
                    display_mode=args.display_mode
                )
            else:  # ortho or other
                display = plotting.plot_stat_map(
                    args.stat_map,
                    bg_img=bg_img,
                    threshold=threshold,
                    cmap=args.cmap,
                    title=args.title,
                    cut_coords=args.cut_coords,
                    annotate=args.annotate,
                    draw_cross=args.draw_cross,
                    black_bg=args.black_bg,
                    symmetric_cbar=args.symmetric_cbar
                )

            # Save if requested
            if args.output_file:
                display.savefig(args.output_file, dpi=300)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("viz_stat_maps failed: %s", exc)
            return ToolResult(
                status="error",
                error=str(exc),
                data={"preview_only": False},
            )
        finally:
            if display is not None:
                try:
                    display.close()  # type: ignore[attr-defined]
                except Exception:
                    pass
            try:
                plt.close("all")
            except Exception:
                pass

        return ToolResult(
            status="success",
            data={
                "display_mode": args.display_mode,
                "threshold_used": float(threshold) if threshold else None,
                # keep top-level for backward compatibility, but also mirror under outputs
                "output_file": args.output_file,
                "outputs": {"output_file": args.output_file} if args.output_file else {},
            },
        )


# =============================================================================
# 2. Surface Projection Tool
# =============================================================================

class SurfaceProjectionArgs(BaseModel):
    """Arguments for volume to surface projection."""

    volume_img: str = Field(description="Path to 3D/4D volume image")
    surf_mesh: Optional[str] = Field(None, description="Surface mesh: 'fsaverage', 'fsaverage5', or custom path")
    hemi: str = Field(default="both", description="Hemisphere: 'left', 'right', 'both'")
    kind: str = Field(default="line", description="Interpolation: 'line', 'nearest'")
    radius: Optional[float] = Field(None, description="Searchlight radius for sampling")
    mask_img: Optional[str] = Field(None, description="Mask to constrain projection")
    output_file: Optional[str] = Field(None, description="Save surface data")
    view: str = Field(default="lateral", description="View for visualization: 'lateral', 'medial', 'dorsal', 'ventral'")
    colorbar: bool = Field(default=True, description="Show colorbar")


class SurfaceProjectionTool(NeuroToolWrapper):
    """Project volumetric data to surface mesh."""

    name = "surface_projection"
    description = "Project volume data onto cortical surface meshes (fsaverage) for visualization"
    category = "visualization"

    ARG_SYNONYMS = {
        "volume_img": ["vol", "image", "stat_map"],
        "surf_mesh": ["surface", "mesh", "template"],
        "hemi": ["hemisphere", "side"]
    }

    EXAMPLES = [
        ToolExample(
            user_query="Project activation to surface",
            params={
                "volume_img": "activation_map.nii.gz",
                "surf_mesh": "fsaverage",
                "hemi": "both",
                "view": "lateral"
            },
            notes="Project to fsaverage surface"
        ),
        ToolExample(
            user_query="Surface rendering of statistical map",
            params={
                "volume_img": "tstat_map.nii.gz",
                "surf_mesh": "fsaverage5",
                "hemi": "left",
                "view": "medial",
                "radius": 3.0
            },
            notes="Left hemisphere medial view"
        )
    ]

    args_model = SurfaceProjectionArgs

    def get_tool_name(self) -> str:
        return self.name

    def get_tool_description(self) -> str:
        return self.description

    def get_args_schema(self) -> type:
        return self.args_model

    def _run(self, **kwargs) -> Dict[str, Any]:
        return self._invoke(**kwargs)

    def _invoke(self, **kwargs) -> Dict[str, Any]:
        """Project volume to surface."""
        from nilearn import surface, datasets
        from nilearn.plotting import plot_surf_stat_map
        import matplotlib.pyplot as plt

        args = SurfaceProjectionArgs(**kwargs)

        # Get surface mesh
        if args.surf_mesh in ["fsaverage", "fsaverage5"]:
            fsaverage = datasets.fetch_surf_fsaverage(mesh=args.surf_mesh)
            surf_mesh_left = fsaverage.pial_left
            surf_mesh_right = fsaverage.pial_right
        else:
            # Custom mesh path
            surf_mesh_left = args.surf_mesh
            surf_mesh_right = args.surf_mesh

        # Project volume to surface
        texture_data = {}

        if args.hemi in ["left", "both"] and surf_mesh_left:
            texture_left = surface.vol_to_surf(
                args.volume_img,
                surf_mesh=surf_mesh_left,
                kind=args.kind,
                radius=args.radius,
                mask_img=args.mask_img
            )
            texture_data["left"] = texture_left

        if args.hemi in ["right", "both"] and surf_mesh_right:
            texture_right = surface.vol_to_surf(
                args.volume_img,
                surf_mesh=surf_mesh_right,
                kind=args.kind,
                radius=args.radius,
                mask_img=args.mask_img
            )
            texture_data["right"] = texture_right

        # Visualize if not saving
        figures = []
        if not args.output_file:
            for hemi, texture in texture_data.items():
                if hemi == "left":
                    surf_mesh = surf_mesh_left
                elif hemi == "right":
                    surf_mesh = surf_mesh_right
                else:
                    continue

                fig = plot_surf_stat_map(
                    surf_mesh,
                    texture,
                    hemi=hemi,
                    view=args.view,
                    colorbar=args.colorbar,
                    title=f"{hemi.capitalize()} hemisphere"
                )
                figures.append(fig)

        # Save surface data
        if args.output_file:
            np.savez(args.output_file, **texture_data)

        return {
            "status": "success",
            "hemispheres": list(texture_data.keys()),
            "n_vertices": {k: len(v) for k, v in texture_data.items()},
            "output_file": args.output_file
        }


# =============================================================================
# Tool Registration
# =============================================================================

def register_nilearn_viz_tools(registry):
    """Register the Nilearn visualization tools."""
    tools = [
        VizStatMapTool(),
        SurfaceProjectionTool(),
    ]

    for tool in tools:
        registry.register_tool(tool)
        logger.info(f"Registered viz tool: {tool.name}")

    return len(tools)
