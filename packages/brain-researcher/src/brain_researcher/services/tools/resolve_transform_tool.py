"""Resolve reusable transform assets from the local neuroimage registry."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.services.tools.neuroimage_asset_registry import (
    resolve_transform_asset,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class ResolveTransformArgs(BaseModel):
    """Arguments for transform asset resolution."""

    source_space: str = Field(
        description="Source space identifier (for example MNI152, MNI152NLin2009cAsym)."
    )
    target_space: str = Field(
        description="Target space identifier (for example fsaverage, fsLR)."
    )
    resolution: str | None = Field(
        default=None,
        description=(
            "Optional transform density hint (for example 10k, 32k, 164k). "
            "This matches the shared public resolution field used by other resolvers."
        ),
    )


def _copy_local_asset(src: Path, output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    dest = output_root / src.name
    if dest.resolve() != src.resolve():
        dest.write_bytes(src.read_bytes())
    return dest


def _is_left_hemi(path: Path) -> bool:
    return "_hemi-L_" in path.name or path.name.startswith("lh.")


def _is_right_hemi(path: Path) -> bool:
    return "_hemi-R_" in path.name or path.name.startswith("rh.")


class ResolveTransformTool(NeuroToolWrapper):
    """Resolve registry-backed transform assets such as local regfusion warps."""

    execution_backend = "python"

    def get_tool_name(self) -> str:
        return "resolve_transform"

    def get_tool_description(self) -> str:
        return "Resolve reusable transform assets from registry-backed local caches."

    def get_args_schema(self):
        return ResolveTransformArgs

    def _run(self, **kwargs) -> ToolResult:
        output_dir = kwargs.get("output_dir")
        args = ResolveTransformArgs(**kwargs)

        try:
            asset = resolve_transform_asset(
                args.source_space,
                args.target_space,
                density=args.resolution,
            )
        except Exception as exc:
            return ToolResult(
                status="error",
                error=str(exc),
                data={
                    "requested_source_space": args.source_space,
                    "requested_target_space": args.target_space,
                    "requested_resolution": args.resolution,
                },
            )

        local_paths = [Path(path) for path in asset.get("local_paths") or []]
        output_root = Path(output_dir) if output_dir else None
        materialized_paths = [
            _copy_local_asset(path, output_root) if output_root else path
            for path in local_paths
        ]

        left_path = next(
            (path for path in materialized_paths if _is_left_hemi(path)),
            None,
        )
        right_path = next(
            (path for path in materialized_paths if _is_right_hemi(path)),
            None,
        )
        primary_path = left_path or materialized_paths[0]

        metadata = asset.get("metadata") or {}
        outputs = {
            "transform_file": str(primary_path),
            "transform_left": str(left_path) if left_path else None,
            "transform_right": str(right_path) if right_path else None,
            "transform_files": [str(path) for path in materialized_paths],
        }
        summary = {
            "source_space": args.source_space,
            "canonical_source_space": metadata.get("source_space") or "",
            "target_space": args.target_space,
            "canonical_target_space": metadata.get("target_space") or "",
            "space_kind": metadata.get("space_kind") or "",
            "resolution": metadata.get("density") or asset.get("density") or "",
            "density": metadata.get("density") or asset.get("density") or "",
            "asset_id": asset["id"],
            "canonical_runtime_name": asset.get("canonical_runtime_name") or "",
            "registry_entry": "regfusion_transform_files",
            "source": "registry_local_cache",
            "transform_asset": asset,
        }

        compact_outputs = {
            key: value
            for key, value in outputs.items()
            if value is not None and value != ""
        }
        compact_summary = {
            key: value
            for key, value in summary.items()
            if value is not None and value != ""
        }
        return ToolResult(
            status="success",
            data={
                "outputs": compact_outputs,
                "summary": compact_summary,
            },
        )


class ResolveTransformTools:
    @staticmethod
    def get_all_tools():
        return [ResolveTransformTool()]


__all__ = ["ResolveTransformTool", "ResolveTransformTools"]
