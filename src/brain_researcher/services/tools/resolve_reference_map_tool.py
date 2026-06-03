"""Resolve reusable reference maps and annotations from the local registry."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.services.br_kg import query_service
from brain_researcher.services.tools.asset_provenance import build_provenance_record
from brain_researcher.services.tools.glm_stat_map_selector import (
    GLMStatMapQuery,
    select_glm_stat_map_matches,
)
from brain_researcher.services.tools.reference_asset_registry import (
    resolve_reference_map_asset,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

_FAST_DATASET_RESOURCE_KWARGS = {
    "run_bids_validation": False,
    "enforce_semantic_gate": False,
    "check_source_access": False,
}


class ResolveReferenceMapArgs(BaseModel):
    """Arguments for resolving a reusable reference map."""

    map_name: str | None = Field(
        default=None,
        description=(
            "Reference map identifier or alias (for example cogpc1, "
            "margulies2016_fcgradient01, myelinmap)."
        ),
    )
    space: str | None = Field(
        default=None,
        description="Optional target space hint (MNI152, fsaverage, fsLR, civet).",
    )
    resolution: str | None = Field(
        default=None,
        description="Optional volume resolution or surface density hint (2mm, 32k).",
    )
    dataset_ref: str | None = Field(
        default=None,
        description="Optional dataset id/alias for dataset-scoped GLM stat-map lookup.",
    )
    task: str | None = Field(
        default=None,
        description="Optional GLM task selector for structured stat-map lookup.",
    )
    node: str | None = Field(
        default=None,
        description="Optional GLM node selector such as subjectLevel or runLevel.",
    )
    subject_id: str | None = Field(
        default=None,
        description="Optional subject id for structured stat-map lookup.",
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session id for structured stat-map lookup.",
    )
    run: str | None = Field(
        default=None,
        description="Optional run label for structured stat-map lookup.",
    )
    contrast: str | None = Field(
        default=None,
        description="Optional GLM contrast selector for structured stat-map lookup.",
    )
    statistic: str | None = Field(
        default=None,
        description="Optional GLM statistic selector such as z or t.",
    )


def _copy_local_asset(src: Path, output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    dest = output_root / src.name
    if dest.resolve() != src.resolve():
        dest.write_bytes(src.read_bytes())
    return dest


def _is_left_hemi(path: Path) -> bool:
    name = path.name
    return "_hemi-L_" in name or name.startswith("lh.")


def _is_right_hemi(path: Path) -> bool:
    name = path.name
    return "_hemi-R_" in name or name.startswith("rh.")


def _materialize_match_paths(
    matches: list[dict],
    *,
    output_root: Path | None,
) -> list[dict]:
    materialized_matches: list[dict] = []
    for match in matches:
        src = Path(str(match["path"]))
        dest = _copy_local_asset(src, output_root) if output_root else src
        item = dict(match)
        item["source_path"] = item.get("source_path") or str(src)
        item["path"] = str(dest)
        materialized_matches.append(item)
    return materialized_matches


def _has_structured_glm_query(args: ResolveReferenceMapArgs) -> bool:
    return any(
        [
            str(args.dataset_ref or "").strip(),
            str(args.task or "").strip(),
            str(args.node or "").strip(),
            str(args.subject_id or "").strip(),
            str(args.session_id or "").strip(),
            str(args.run or "").strip(),
            str(args.contrast or "").strip(),
            str(args.statistic or "").strip(),
        ]
    )


def _load_derivative_roots(dataset_ref: str | None) -> dict[str, str]:
    if not dataset_ref:
        return {}
    try:
        resources = query_service.dataset_resources(
            dataset_ref,
            analysis_goal="fmri-glm",
            **_FAST_DATASET_RESOURCE_KWARGS,
        )
    except Exception:
        return {}
    if resources is None:
        return {}
    return dict(getattr(resources, "derivatives", {}) or {})


def _structured_glm_query(args: ResolveReferenceMapArgs) -> GLMStatMapQuery:
    return GLMStatMapQuery(
        dataset_ref=args.dataset_ref,
        query_text=args.map_name,
        task=args.task,
        node=args.node,
        subject_id=args.subject_id,
        session_id=args.session_id,
        run=args.run,
        contrast=args.contrast,
        statistic=args.statistic,
        space=args.space,
    )


class ResolveReferenceMapTool(NeuroToolWrapper):
    """Resolve a reference map/annotation from the local registry-backed inventory."""

    execution_backend = "python"

    def get_tool_name(self) -> str:
        return "resolve_reference_map"

    def get_tool_description(self) -> str:
        return "Resolve reusable reference maps and annotations from local registry-backed caches."

    def get_args_schema(self):
        return ResolveReferenceMapArgs

    def _run(self, **kwargs) -> ToolResult:
        output_dir = kwargs.get("output_dir")
        args = ResolveReferenceMapArgs(**kwargs)
        has_structured_query = _has_structured_glm_query(args)
        if not (str(args.map_name or "").strip() or str(args.contrast or "").strip()):
            return ToolResult(
                status="error",
                error="resolve_reference_map requires map_name or contrast.",
                data={},
            )

        output_root = Path(output_dir) if output_dir else None

        if has_structured_query:
            try:
                matches = select_glm_stat_map_matches(
                    query=_structured_glm_query(args),
                    derivative_roots=_load_derivative_roots(args.dataset_ref),
                    include_registry=True,
                )
            except Exception as exc:
                return ToolResult(
                    status="error",
                    error=str(exc),
                    data={
                        "requested_map": args.map_name,
                        "requested_space": args.space,
                        "requested_resolution": args.resolution,
                    },
                )
            if not matches:
                return ToolResult(
                    status="error",
                    error="No matching structured GLM stat maps were found.",
                    data={
                        "requested_map": args.map_name,
                        "requested_space": args.space,
                        "requested_resolution": args.resolution,
                    },
                )

            materialized_matches = _materialize_match_paths(
                matches,
                output_root=output_root,
            )
            primary = materialized_matches[0]
            normalized_matches = []
            for match in materialized_matches:
                normalized_matches.append(
                    {
                        **match,
                        **build_provenance_record(
                            kind="stat_map",
                            preferred_id=match.get("asset_id") or None,
                            source=match.get("source") or "",
                            source_path=match.get("path") or "",
                            roots=[match.get("root") or ""],
                            dataset_id=match.get("dataset_id") or "",
                            derivative_kind=match.get("derivative_kind") or "",
                            subject_id=match.get("subject_id") or "",
                            session_id=match.get("session_id") or "",
                            task=match.get("task") or "",
                            run=match.get("run") or "",
                            space=match.get("space") or "",
                            contrast=match.get("contrast") or "",
                            statistic=match.get("statistic") or "",
                            level=match.get("level") or "",
                            metadata={
                                "canonical_runtime_name": match.get(
                                    "canonical_runtime_name"
                                )
                                or "",
                                "space_inferred": bool(match.get("space_inferred")),
                                "format": match.get("format") or "",
                            },
                        ),
                    }
                )
            outputs = {
                "reference_map": primary["path"],
                "reference_map_files": [
                    match["path"] for match in materialized_matches
                ],
                "matches": normalized_matches,
            }
            summary = {
                "map_name": args.map_name or args.contrast or "",
                "asset_id": primary.get("asset_id") or "",
                "canonical_runtime_name": primary.get("canonical_runtime_name") or "",
                "space": args.space or primary.get("space") or "",
                "canonical_space": primary.get("space") or "",
                "space_kind": "volume",
                "source_dataset": "openneuro_glmfitlins"
                if primary.get("source") == "openneuro_registry"
                else primary.get("derivative_kind") or "",
                "description_key": primary.get("contrast") or "",
                "contrast": primary.get("contrast") or "",
                "dataset_id": primary.get("dataset_id") or "",
                "task": primary.get("task") or "",
                "node": primary.get("node") or "",
                "subject_id": primary.get("subject_id") or "",
                "session_id": primary.get("session_id") or "",
                "run": primary.get("run") or "",
                "statistic": primary.get("statistic") or "",
                "source": primary.get("source") or "",
                "n_matches": len(materialized_matches),
                "returned_all_matches": True,
            }
            compact_outputs = {
                key: value
                for key, value in outputs.items()
                if value is not None and value != ""
            }
            compact_outputs["resolved_asset"] = build_provenance_record(
                kind="stat_map",
                preferred_id=primary.get("asset_id") or None,
                source=primary.get("source") or "",
                source_path=primary.get("path") or "",
                roots=[primary.get("root") or ""],
                dataset_id=primary.get("dataset_id") or "",
                derivative_kind=primary.get("derivative_kind") or "",
                subject_id=primary.get("subject_id") or "",
                session_id=primary.get("session_id") or "",
                task=primary.get("task") or "",
                run=primary.get("run") or "",
                space=primary.get("space") or "",
                contrast=primary.get("contrast") or "",
                statistic=primary.get("statistic") or "",
                level=primary.get("level") or "",
                metadata={
                    "canonical_runtime_name": primary.get("canonical_runtime_name")
                    or "",
                    "space_inferred": bool(primary.get("space_inferred")),
                    "format": primary.get("format") or "",
                },
            )
            compact_summary = {
                key: value
                for key, value in summary.items()
                if value is not None and value != ""
            }
            return ToolResult(
                status="success",
                data={"outputs": compact_outputs, "summary": compact_summary},
            )

        try:
            asset = resolve_reference_map_asset(
                args.map_name or "",
                space=args.space,
                resolution=args.resolution,
            )
        except Exception as exc:
            return ToolResult(
                status="error",
                error=str(exc),
                data={
                    "requested_map": args.map_name,
                    "requested_space": args.space,
                    "requested_resolution": args.resolution,
                },
            )

        local_paths = [Path(path) for path in asset.get("local_paths") or []]
        materialized_paths = [
            _copy_local_asset(path, output_root) if output_root else path
            for path in local_paths
        ]

        left_path = next(
            (path for path in materialized_paths if _is_left_hemi(path)), None
        )
        right_path = next(
            (path for path in materialized_paths if _is_right_hemi(path)),
            None,
        )
        primary_path = left_path or materialized_paths[0]

        metadata = asset.get("metadata") or {}
        outputs = {
            "reference_map": str(primary_path),
            "reference_map_left": str(left_path) if left_path else None,
            "reference_map_right": str(right_path) if right_path else None,
            "reference_map_files": [str(path) for path in materialized_paths],
            "matches": [
                {
                    "path": str(primary_path),
                    "source_path": str(local_paths[0]),
                    "source": "registry_local_cache",
                    "dataset_id": metadata.get("dataset_id") or "",
                    "task": metadata.get("task") or "",
                    "node": metadata.get("node") or "",
                    "subject_id": metadata.get("subject_id") or "",
                    "statistic": metadata.get("statistic") or "",
                    "contrast": metadata.get("contrast")
                    or metadata.get("description_key")
                    or "",
                    "space": metadata.get("space") or "",
                    **build_provenance_record(
                        kind="reference_map",
                        preferred_id=asset.get("id") or None,
                        source=metadata.get("source_dataset") or "registry_local_cache",
                        source_path=str(local_paths[0]),
                        roots=[metadata.get("root") or ""],
                        dataset_id=metadata.get("dataset_id") or "",
                        subject_id=metadata.get("subject_id") or "",
                        task=metadata.get("task") or "",
                        space=metadata.get("space") or "",
                        contrast=metadata.get("contrast")
                        or metadata.get("description_key")
                        or "",
                        statistic=metadata.get("statistic") or "",
                        level=metadata.get("level") or "",
                        estimator=metadata.get("estimator") or "",
                        metadata=metadata,
                    ),
                }
            ],
        }
        outputs["resolved_asset"] = build_provenance_record(
            kind="reference_map",
            preferred_id=asset.get("id") or None,
            source=metadata.get("source_dataset") or "registry_local_cache",
            source_path=str(primary_path),
            roots=[metadata.get("root") or ""],
            dataset_id=metadata.get("dataset_id") or "",
            subject_id=metadata.get("subject_id") or "",
            task=metadata.get("task") or "",
            space=metadata.get("space") or "",
            contrast=metadata.get("contrast") or metadata.get("description_key") or "",
            statistic=metadata.get("statistic") or "",
            level=metadata.get("level") or "",
            estimator=metadata.get("estimator") or "",
            metadata=metadata,
        )
        summary = {
            "map_name": args.map_name,
            "asset_id": asset["id"],
            "canonical_runtime_name": asset.get("canonical_runtime_name") or "",
            "space": args.space or metadata.get("space") or "",
            "canonical_space": metadata.get("space") or "",
            "space_kind": metadata.get("space_kind") or "",
            "resolution": metadata.get("resolution") or asset.get("resolution") or "",
            "density": metadata.get("density") or asset.get("density") or "",
            "source_dataset": metadata.get("source_dataset") or "",
            "description_key": metadata.get("description_key") or "",
            "contrast": metadata.get("contrast")
            or metadata.get("description_key")
            or "",
            "dataset_id": metadata.get("dataset_id") or "",
            "task": metadata.get("task") or "",
            "node": metadata.get("node") or "",
            "subject_id": metadata.get("subject_id") or "",
            "statistic": metadata.get("statistic") or "",
            "bundle_kind": metadata.get("bundle_kind") or "",
            "source": "registry_local_cache",
            "n_matches": len(materialized_paths),
            "returned_all_matches": True,
            "reference_asset": asset,
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


class ResolveReferenceMapTools:
    @staticmethod
    def get_all_tools():
        return [ResolveReferenceMapTool()]


__all__ = ["ResolveReferenceMapTool", "ResolveReferenceMapTools"]
