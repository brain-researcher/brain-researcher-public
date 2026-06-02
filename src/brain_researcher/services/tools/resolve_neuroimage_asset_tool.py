"""Unified resolver for reusable neuroimage assets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.services.tools.neuroimage_asset_registry import (
    normalize_space_request,
)
from brain_researcher.services.tools.reference_asset_registry import (
    find_reference_asset,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

_KIND_ALIASES = {
    "annotation": "reference_map",
    "atlas": "atlas",
    "auto": "auto",
    "glm": "stat_map",
    "glm_stat_map": "stat_map",
    "glmstatmap": "stat_map",
    "map": "reference_map",
    "method": "method_bundle",
    "method_bundle": "method_bundle",
    "methodbundle": "method_bundle",
    "model": "model_bundle",
    "model_bundle": "model_bundle",
    "modelbundle": "model_bundle",
    "parcellation": "atlas",
    "reference_map": "reference_map",
    "space": "template",
    "stat_map": "stat_map",
    "statmap": "stat_map",
    "template": "template",
    "transform": "transform",
    "warp": "transform",
}
_SURFACE_ATLAS_ALIASES = {
    "aparc",
    "aparca2009s",
    "desikan",
    "desikankilliany",
    "destrieux",
    "dk",
    "yeo",
    "yeo7",
    "yeo17",
}


class ResolveNeuroimageAssetArgs(BaseModel):
    """Arguments for unified neuroimage asset resolution."""

    name: str | None = Field(
        default=None,
        description=(
            "Asset identifier. For templates this can be a space alias "
            "(MNI152, fsaverage, fsLR); for atlases/reference maps this is the "
            "atlas/map query."
        ),
    )
    kind: str = Field(
        default="auto",
        description=(
            "Asset kind. Supported values: auto, template, atlas, "
            "reference_map, stat_map, transform, method_bundle, or model_bundle."
        ),
    )
    space: str | None = Field(
        default=None,
        description=(
            "Optional target space hint. For transforms, this can also serve as "
            "the source space when source_space is omitted."
        ),
    )
    source_space: str | None = Field(
        default=None,
        description="Optional explicit source space for transform resolution.",
    )
    target_space: str | None = Field(
        default=None,
        description="Optional explicit target space for transform resolution.",
    )
    resolution: str | None = Field(
        default=None,
        description=(
            "Optional volume resolution or surface density (for example 2mm, 32k)."
        ),
    )
    dataset_ref: str | None = Field(
        default=None,
        description="Optional dataset id/alias for dataset-scoped GLM stat-map queries.",
    )
    derivative_kind: str | None = Field(
        default=None,
        description="Optional derivative family such as glmfitlins.",
    )
    task: str | None = Field(
        default=None,
        description="Optional GLM task selector for stat-map queries.",
    )
    node: str | None = Field(
        default=None,
        description="Optional GLM node selector such as subjectLevel or runLevel.",
    )
    subject_id: str | None = Field(
        default=None,
        description="Optional subject id for stat-map queries.",
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session id for stat-map queries.",
    )
    run: str | None = Field(
        default=None,
        description="Optional run label for stat-map queries.",
    )
    contrast: str | None = Field(
        default=None,
        description="Optional GLM contrast selector for stat-map queries.",
    )
    statistic: str | None = Field(
        default=None,
        description="Optional GLM statistic selector such as z or t.",
    )


def _normalize_kind(kind: str) -> str:
    key = str(kind or "").strip().lower()
    normalized = _KIND_ALIASES.get(key)
    if normalized is None:
        supported = ", ".join(sorted(_KIND_ALIASES))
        raise ValueError(f"Unsupported kind '{kind}'. Supported values: {supported}")
    return normalized


def _space_request_name(args: ResolveNeuroimageAssetArgs) -> str:
    return str(args.name or args.space or "").strip()


def _transform_source_space(args: ResolveNeuroimageAssetArgs) -> str:
    return str(args.source_space or args.space or "").strip()


def _transform_target_space(args: ResolveNeuroimageAssetArgs) -> str:
    return str(args.target_space or "").strip()


def _tool_kwargs(output_dir: str | None, **kwargs: Any) -> dict[str, Any]:
    payload = {key: value for key, value in kwargs.items() if value is not None}
    if output_dir:
        payload["output_dir"] = output_dir
    return payload


def _space_like(query: str, resolution: str | None) -> bool:
    if not query:
        return False
    try:
        normalize_space_request(query, resolution)
    except Exception:
        return False
    return True


def _atlas_candidate(
    name: str,
    *,
    space: str | None,
    resolution: str | None,
) -> bool:
    query = str(name or "").strip()
    if not query:
        return False
    if find_reference_asset(
        query,
        kind="atlas",
        space=space,
        resolution=resolution,
    ):
        return True
    normalized = "".join(ch for ch in query.lower() if ch.isalnum())
    return normalized in _SURFACE_ATLAS_ALIASES or "yeo" in normalized


def _augment_result(
    result: ToolResult,
    *,
    args: ResolveNeuroimageAssetArgs,
    resolved_kind: str,
    resolver_tool: str,
    dispatch_mode: str,
) -> ToolResult:
    data = dict(result.data or {})
    if result.status != "success":
        data["dispatch"] = {
            "requested_name": args.name,
            "requested_kind": args.kind,
            "resolved_kind": resolved_kind,
            "resolver_tool": resolver_tool,
            "dispatch_mode": dispatch_mode,
            "requested_space": args.space,
            "requested_source_space": args.source_space,
            "requested_target_space": args.target_space,
            "requested_resolution": args.resolution,
            "requested_dataset_ref": args.dataset_ref,
            "requested_derivative_kind": args.derivative_kind,
            "requested_task": args.task,
            "requested_node": args.node,
            "requested_subject_id": args.subject_id,
            "requested_session_id": args.session_id,
            "requested_run": args.run,
            "requested_contrast": args.contrast,
            "requested_statistic": args.statistic,
        }
        return ToolResult(
            status="error",
            error=result.error,
            data=data,
            metadata=result.metadata,
        )

    summary = dict(data.get("summary") or {})
    summary.update(
        {
            "requested_name": args.name or "",
            "requested_kind": args.kind,
            "resolved_kind": resolved_kind,
            "resolver_tool": resolver_tool,
            "dispatch_mode": dispatch_mode,
        }
    )
    data["summary"] = summary
    return ToolResult(status="success", data=data, metadata=result.metadata)


def _dispatch_template(
    args: ResolveNeuroimageAssetArgs,
    *,
    output_dir: str | None,
    dispatch_mode: str,
) -> ToolResult:
    from brain_researcher.services.tools.resolve_space_tool import ResolveSpaceTool

    space_name = _space_request_name(args)
    if not space_name:
        return ToolResult(
            status="error",
            error="Template resolution requires 'name' or 'space'.",
            data={},
        )
    result = ResolveSpaceTool()._run(
        **_tool_kwargs(
            output_dir,
            space_name=space_name,
            resolution=args.resolution,
        )
    )
    return _augment_result(
        result,
        args=args,
        resolved_kind="template",
        resolver_tool="resolve_space",
        dispatch_mode=dispatch_mode,
    )


def _dispatch_transform(
    args: ResolveNeuroimageAssetArgs,
    *,
    output_dir: str | None,
    dispatch_mode: str,
) -> ToolResult:
    from brain_researcher.services.tools.resolve_transform_tool import (
        ResolveTransformTool,
    )

    source_space = _transform_source_space(args)
    target_space = _transform_target_space(args)
    if not source_space or not target_space:
        return ToolResult(
            status="error",
            error=(
                "Transform resolution requires both source_space and "
                "target_space. 'space' may be used as source_space."
            ),
            data={},
        )
    result = ResolveTransformTool()._run(
        **_tool_kwargs(
            output_dir,
            source_space=source_space,
            target_space=target_space,
            resolution=args.resolution,
        )
    )
    return _augment_result(
        result,
        args=args,
        resolved_kind="transform",
        resolver_tool="resolve_transform",
        dispatch_mode=dispatch_mode,
    )


def _dispatch_atlas(
    args: ResolveNeuroimageAssetArgs,
    *,
    output_dir: str | None,
    dispatch_mode: str,
) -> ToolResult:
    from brain_researcher.services.tools.parcellation_fetch_tool import (
        ParcellationFetchTool,
    )

    atlas_name = str(args.name or "").strip()
    if not atlas_name:
        return ToolResult(
            status="error",
            error="Atlas resolution requires 'name'.",
            data={},
        )
    result = ParcellationFetchTool()._run(
        **_tool_kwargs(
            output_dir,
            atlas_name=atlas_name,
            space=args.space or "MNI152NLin2009cAsym",
            resolution=args.resolution,
        )
    )
    return _augment_result(
        result,
        args=args,
        resolved_kind="atlas",
        resolver_tool="parcellation_fetch",
        dispatch_mode=dispatch_mode,
    )


def _dispatch_reference_map(
    args: ResolveNeuroimageAssetArgs,
    *,
    output_dir: str | None,
    dispatch_mode: str,
) -> ToolResult:
    from brain_researcher.services.tools.resolve_reference_map_tool import (
        ResolveReferenceMapTool,
    )

    map_name = str(args.name or "").strip()
    if not (map_name or str(args.contrast or "").strip()):
        return ToolResult(
            status="error",
            error="Reference map resolution requires 'name' or 'contrast'.",
            data={},
        )
    result = ResolveReferenceMapTool()._run(
        **_tool_kwargs(
            output_dir,
            map_name=map_name or None,
            space=args.space,
            resolution=args.resolution,
            dataset_ref=args.dataset_ref,
            task=args.task,
            node=args.node,
            subject_id=args.subject_id,
            session_id=args.session_id,
            run=args.run,
            contrast=args.contrast,
            statistic=args.statistic,
        )
    )
    return _augment_result(
        result,
        args=args,
        resolved_kind="reference_map",
        resolver_tool="resolve_reference_map",
        dispatch_mode=dispatch_mode,
    )


def _stat_map_query_name(args: ResolveNeuroimageAssetArgs) -> str:
    return str(args.contrast or args.name or "").strip()


def _has_stat_map_query(args: ResolveNeuroimageAssetArgs) -> bool:
    if any(
        [
            str(args.contrast or "").strip(),
            str(args.statistic or "").strip(),
            str(args.node or "").strip(),
            str(args.task or "").strip(),
            str(args.subject_id or "").strip(),
            str(args.session_id or "").strip(),
            str(args.run or "").strip(),
            str(args.derivative_kind or "").strip(),
        ]
    ):
        return True
    return bool(str(args.dataset_ref or "").strip() and str(args.name or "").strip())


def _dispatch_stat_map(
    args: ResolveNeuroimageAssetArgs,
    *,
    output_dir: str | None,
    dispatch_mode: str,
) -> ToolResult:
    query_name = _stat_map_query_name(args)
    if args.dataset_ref:
        from brain_researcher.services.tools.resolve_dataset_asset_tool import (
            ResolveDatasetAssetTool,
        )

        if not (query_name or str(args.task or "").strip()):
            return ToolResult(
                status="error",
                error=(
                    "Dataset-scoped stat-map resolution requires 'name'/'contrast' "
                    "or another structured GLM selector such as task/node/statistic."
                ),
                data={},
            )
        result = ResolveDatasetAssetTool()._run(
            **_tool_kwargs(
                output_dir,
                dataset_ref=args.dataset_ref,
                kind="stat_map",
                derivative_kind=args.derivative_kind,
                task=args.task,
                node=args.node,
                subject_id=args.subject_id,
                session_id=args.session_id,
                run=args.run,
                contrast=query_name or None,
                statistic=args.statistic,
                space=args.space,
            )
        )
        return _augment_result(
            result,
            args=args,
            resolved_kind="stat_map",
            resolver_tool="resolve_dataset_asset",
            dispatch_mode=dispatch_mode,
        )

    result = _dispatch_reference_map(
        ResolveNeuroimageAssetArgs(
            **{
                **args.model_dump(),
                "name": args.name,
                "contrast": query_name or args.contrast,
            }
        ),
        output_dir=output_dir,
        dispatch_mode=dispatch_mode,
    )
    if result.status != "success":
        return result
    data = dict(result.data or {})
    summary = dict(data.get("summary") or {})
    summary["resolved_kind"] = "stat_map"
    summary["resolver_tool"] = "resolve_reference_map"
    data["summary"] = summary
    return ToolResult(status="success", data=data, metadata=result.metadata)


def _bundle_root_for_asset(asset: dict[str, Any]) -> str | None:
    asset_id = str(asset.get("id") or "").strip()
    if not asset_id:
        return None

    preferred: list[str] = []
    fallback: list[str] = []
    for raw_path in asset.get("local_paths") or []:
        path = Path(str(raw_path))
        try:
            exists = path.exists()
        except OSError:
            exists = False
        if not exists or not path.is_dir():
            continue
        if path.name == asset_id or path.parent.name in {
            "method_bundles",
            "model_bundles",
        }:
            preferred.append(str(path))
        else:
            fallback.append(str(path))
    return (preferred or fallback or [None])[0]


def _bundle_source_root(asset: dict[str, Any], bundle_root: str | None) -> str | None:
    asset_id = str(asset.get("id") or "").strip()
    if bundle_root:
        source_link = Path(bundle_root) / "source"
        try:
            if source_link.exists() and source_link.is_dir():
                return str(source_link)
        except OSError:
            pass

    source_candidates: list[str] = []
    repo_candidates: list[str] = []
    for raw_path in asset.get("local_paths") or []:
        path = Path(str(raw_path))
        try:
            exists = path.exists()
        except OSError:
            exists = False
        if not exists or not path.is_dir():
            continue
        if path.name == "source" and path.parent.name == asset_id:
            source_candidates.append(str(path))
        elif "repos" in {part.lower() for part in path.parts}:
            repo_candidates.append(str(path))
    return (source_candidates or repo_candidates or [None])[0]


def _dispatch_bundle(
    args: ResolveNeuroimageAssetArgs,
    *,
    kind: str,
    output_dir: str | None,
    dispatch_mode: str,
) -> ToolResult:
    bundle_name = str(args.name or "").strip()
    if not bundle_name:
        return ToolResult(
            status="error",
            error="Bundle resolution requires 'name'.",
            data={},
        )

    asset = find_reference_asset(bundle_name, kind=kind)
    if asset is None:
        return ToolResult(
            status="error",
            error=f"No local {kind} matched '{bundle_name}'.",
            data={},
        )

    bundle_root = _bundle_root_for_asset(asset)
    if not bundle_root:
        return ToolResult(
            status="error",
            error=f"Matched {kind} '{asset['id']}' but found no existing local bundle path.",
            data={
                "summary": {
                    "requested_name": bundle_name,
                    "requested_kind": args.kind,
                    "resolved_kind": kind,
                    "asset_id": asset["id"],
                }
            },
        )

    source_root = _bundle_source_root(asset, bundle_root)
    outputs: dict[str, Any] = {
        "bundle_root": bundle_root,
        "local_paths": list(asset.get("local_paths") or []),
    }
    bundle_manifest = Path(bundle_root) / "asset.json"
    try:
        if bundle_manifest.exists():
            outputs["bundle_manifest"] = str(bundle_manifest)
    except OSError:
        pass
    if source_root:
        outputs["source_root"] = source_root

    return _augment_result(
        ToolResult(
            status="success",
            data={
                "outputs": outputs,
                "summary": {
                    "asset_id": asset["id"],
                    "title": asset.get("title") or "",
                    "version": asset.get("version") or "",
                    "source_project": asset.get("source_project") or "",
                    "source_repo": asset.get("source_repo") or "",
                    "local_path_count": len(asset.get("local_paths") or []),
                    "source": "reference_asset_registry",
                },
            },
        ),
        args=args,
        resolved_kind=kind,
        resolver_tool="reference_asset_registry",
        dispatch_mode=dispatch_mode,
    )


class ResolveNeuroimageAssetTool(NeuroToolWrapper):
    """Dispatch a neuroimage asset query to the appropriate local resolver."""

    execution_backend = "python"

    def get_tool_name(self) -> str:
        return "resolve_neuroimage_asset"

    def get_tool_description(self) -> str:
        return (
            "Resolve templates, transforms, atlases, reference maps, GLM stat maps, "
            "or materialized method/model bundles through a single registry-backed "
            "MCP entrypoint."
        )

    def get_args_schema(self):
        return ResolveNeuroimageAssetArgs

    def _run(self, **kwargs) -> ToolResult:
        output_dir = kwargs.get("output_dir")
        try:
            args = ResolveNeuroimageAssetArgs(**kwargs)
            normalized_kind = _normalize_kind(args.kind)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})

        if normalized_kind == "template":
            return _dispatch_template(
                args,
                output_dir=output_dir,
                dispatch_mode="explicit",
            )
        if normalized_kind == "transform":
            return _dispatch_transform(
                args,
                output_dir=output_dir,
                dispatch_mode="explicit",
            )
        if normalized_kind == "atlas":
            return _dispatch_atlas(
                args,
                output_dir=output_dir,
                dispatch_mode="explicit",
            )
        if normalized_kind == "reference_map":
            return _dispatch_reference_map(
                args,
                output_dir=output_dir,
                dispatch_mode="explicit",
            )
        if normalized_kind == "stat_map":
            return _dispatch_stat_map(
                args,
                output_dir=output_dir,
                dispatch_mode="explicit",
            )
        if normalized_kind == "method_bundle":
            return _dispatch_bundle(
                args,
                kind="method_bundle",
                output_dir=output_dir,
                dispatch_mode="explicit",
            )
        if normalized_kind == "model_bundle":
            return _dispatch_bundle(
                args,
                kind="model_bundle",
                output_dir=output_dir,
                dispatch_mode="explicit",
            )

        if args.source_space or args.target_space:
            return _dispatch_transform(
                args,
                output_dir=output_dir,
                dispatch_mode="auto",
            )

        if _has_stat_map_query(args):
            return _dispatch_stat_map(
                args,
                output_dir=output_dir,
                dispatch_mode="auto",
            )

        query = _space_request_name(args)
        if query and _space_like(query, args.resolution):
            return _dispatch_template(
                args,
                output_dir=output_dir,
                dispatch_mode="auto",
            )

        attempts: list[dict[str, str]] = []
        if args.name and _atlas_candidate(
            args.name,
            space=args.space,
            resolution=args.resolution,
        ):
            atlas_result = _dispatch_atlas(
                args,
                output_dir=output_dir,
                dispatch_mode="auto",
            )
            if atlas_result.status == "success":
                return atlas_result
            attempts.append(
                {
                    "resolver_tool": "parcellation_fetch",
                    "error": str(atlas_result.error or ""),
                }
            )

        if args.name:
            map_result = _dispatch_reference_map(
                args,
                output_dir=output_dir,
                dispatch_mode="auto",
            )
            if map_result.status == "success":
                return map_result
            attempts.append(
                {
                    "resolver_tool": "resolve_reference_map",
                    "error": str(map_result.error or ""),
                }
            )

        if args.name:
            for bundle_kind in ("method_bundle", "model_bundle"):
                bundle_result = _dispatch_bundle(
                    args,
                    kind=bundle_kind,
                    output_dir=output_dir,
                    dispatch_mode="auto",
                )
                if bundle_result.status == "success":
                    return bundle_result
                attempts.append(
                    {
                        "resolver_tool": "reference_asset_registry",
                        "resolved_kind": bundle_kind,
                        "error": str(bundle_result.error or ""),
                    }
                )

        return ToolResult(
            status="error",
            error=(
                "resolve_neuroimage_asset could not infer a matching asset kind "
                "from the local registry-backed resolvers."
            ),
            data={
                "requested_name": args.name,
                "requested_kind": args.kind,
                "requested_space": args.space,
                "requested_source_space": args.source_space,
                "requested_target_space": args.target_space,
                "requested_resolution": args.resolution,
                "attempts": attempts,
            },
        )


class ResolveNeuroimageAssetTools:
    @staticmethod
    def get_all_tools():
        return [ResolveNeuroimageAssetTool()]


__all__ = ["ResolveNeuroimageAssetTool", "ResolveNeuroimageAssetTools"]
