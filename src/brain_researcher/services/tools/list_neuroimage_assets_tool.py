"""List registry-backed neuroimage assets for MCP and agent workflows."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.services.tools.asset_provenance import build_provenance_record
from brain_researcher.services.tools.neuroimage_asset_registry import (
    load_neuroimage_asset_registry,
    load_template_assets,
    load_transform_assets,
)
from brain_researcher.services.tools.reference_asset_registry import (
    load_reference_assets,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


def _normalize_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _is_stat_map_asset(asset: dict[str, Any]) -> bool:
    if str(asset.get("kind") or "").strip().lower() != "reference_map":
        return False
    family = str(asset.get("family") or "").strip().lower()
    metadata = asset.get("metadata") or {}
    return (
        family == "openneuro_glmfitlins_stat_map"
        or str(metadata.get("source_dataset") or "").strip() == "openneuro_glmfitlins"
    )


def _public_kind(asset: dict[str, Any]) -> str:
    return "stat_map" if _is_stat_map_asset(asset) else str(asset.get("kind") or "")


def _subfamily_id_for_asset(asset: dict[str, Any]) -> str:
    return "stat_maps" if _is_stat_map_asset(asset) else ""


def _family_id_for_asset(asset: dict[str, Any]) -> str:
    explicit = str(asset.get("family_id") or "").strip()
    if explicit:
        return explicit

    kind = str(asset.get("kind") or "").strip().lower()
    if kind in {"template", "warp"}:
        return "templates_spaces_transforms"
    if kind == "atlas":
        return "atlases_parcellations"
    if kind == "reference_map":
        return "reference_maps_annotations"
    return "unknown"


def _scale_value(asset: dict[str, Any]) -> str:
    metadata = asset.get("metadata") or {}
    return str(
        asset.get("resolution")
        or asset.get("density")
        or metadata.get("resolution")
        or metadata.get("density")
        or metadata.get("space_or_density")
        or ""
    ).strip()


def _matches_query(asset: dict[str, Any], query: str | None) -> bool:
    if not query:
        return True
    needle = _normalize_token(query)
    if not needle:
        return True

    metadata = asset.get("metadata") or {}
    fields = [
        asset.get("id") or "",
        _public_kind(asset),
        asset.get("kind") or "",
        asset.get("family") or "",
        asset.get("canonical_runtime_name") or "",
        asset.get("title") or "",
        asset.get("summary") or "",
        metadata.get("next_action") or "",
        metadata.get("scope") or "",
        metadata.get("format") or "",
        metadata.get("space_or_density") or "",
        metadata.get("contrast") or "",
        metadata.get("statistic") or "",
        metadata.get("dataset_id") or "",
        metadata.get("task") or "",
        metadata.get("node") or "",
        metadata.get("subject_id") or "",
        _subfamily_id_for_asset(asset),
    ]
    fields.extend(asset.get("aliases") or [])
    fields.extend(asset.get("spaces") or [])
    return any(needle in _normalize_token(value) for value in fields if value)


def _matches_space(asset: dict[str, Any], space: str | None) -> bool:
    if not space:
        return True
    needle = _normalize_token(space)
    metadata = asset.get("metadata") or {}
    candidates = [
        *(asset.get("spaces") or []),
        metadata.get("space") or "",
        metadata.get("source_space") or "",
        metadata.get("target_space") or "",
        metadata.get("space_or_density") or "",
    ]
    return any(_normalize_token(value) == needle for value in candidates if value)


def _matches_scale(asset: dict[str, Any], resolution: str | None) -> bool:
    if not resolution:
        return True
    needle = _normalize_token(resolution)
    candidate = _normalize_token(_scale_value(asset))
    return bool(candidate) and needle in candidate


def _matches_current_state(asset: dict[str, Any], current_state: str | None) -> bool:
    if not current_state:
        return True
    return (
        str(asset.get("current_state") or "").strip()
        == str(current_state or "").strip()
    )


def _matches_family(asset: dict[str, Any], family: str | None) -> bool:
    if not family:
        return True
    requested = _normalize_token(family)
    if not requested:
        return True

    family_id = _family_id_for_asset(asset)
    subfamily_id = _subfamily_id_for_asset(asset)
    candidates = {
        _normalize_token(family_id),
        _normalize_token(asset.get("family") or ""),
        _normalize_token(subfamily_id),
    }
    candidates.discard("")
    if requested in candidates:
        return True

    if requested == "referencemapsannotations":
        return family_id == "reference_maps_annotations"
    if requested in {"statmap", "statmaps", "glmstatmap", "glmstatmaps"}:
        return bool(subfamily_id)
    return False


def _matches_kind(asset: dict[str, Any], kind: str | None) -> bool:
    if not kind:
        return True
    requested = _normalize_token(kind)
    if not requested:
        return True

    public_kind = _normalize_token(_public_kind(asset))
    raw_kind = _normalize_token(asset.get("kind") or "")
    if requested == public_kind or requested == raw_kind:
        return True
    if requested == "referencemap":
        return raw_kind == "referencemap"
    if requested in {"statmap", "glmstatmap"}:
        return public_kind == "statmap"
    return False


def _public_asset_view(
    asset: dict[str, Any],
    *,
    include_metadata: bool,
) -> dict[str, Any]:
    metadata = asset.get("metadata") or {}
    local_paths = asset.get("local_paths") or []
    source_path = str(local_paths[0]) if local_paths else ""
    provenance = build_provenance_record(
        kind=_public_kind(asset),
        preferred_id=str(asset.get("id") or "").strip() or None,
        source=(
            str(metadata.get("source_dataset") or "").strip()
            or str(asset.get("source_project") or "").strip()
            or str(asset.get("source_repo") or "").strip()
            or str(asset.get("family") or "").strip()
        ),
        source_path=source_path,
        roots=[metadata.get("root") or ""],
        dataset_id=metadata.get("dataset_id") or "",
        subject_id=metadata.get("subject_id") or "",
        session_id=metadata.get("session_id") or "",
        task=metadata.get("task") or "",
        run=metadata.get("run") or "",
        space=metadata.get("space") or "",
        contrast=metadata.get("contrast") or metadata.get("description_key") or "",
        statistic=metadata.get("statistic") or "",
        level=metadata.get("level") or "",
        estimator=metadata.get("estimator") or "",
        metadata=metadata,
    )
    view = {
        "id": asset.get("id") or "",
        "canonical_id": provenance["canonical_id"],
        "kind": _public_kind(asset),
        "family_id": _family_id_for_asset(asset),
        "subfamily_id": _subfamily_id_for_asset(asset),
        "family": asset.get("family") or "",
        "canonical_runtime_name": asset.get("canonical_runtime_name") or "",
        "title": asset.get("title") or "",
        "summary": asset.get("summary") or "",
        "spaces": asset.get("spaces") or [],
        "resolution": str(asset.get("resolution") or metadata.get("resolution") or ""),
        "density": str(asset.get("density") or metadata.get("density") or ""),
        "current_state": str(asset.get("current_state") or ""),
        "local_paths": asset.get("local_paths") or [],
        "source": provenance["source"],
        "source_path": provenance["source_path"],
        "relative_path": provenance["relative_path"]
        or str(metadata.get("relative_path") or ""),
        "checksum": provenance["checksum"],
        "level": provenance["level"],
        "estimator": provenance["estimator"],
        "manifest_fields": provenance["manifest_fields"],
        "aliases": asset.get("aliases") or [],
    }
    if include_metadata:
        view["metadata"] = metadata
    return view


_KIND_PRIORITY = {
    "template": 0,
    "warp": 1,
    "atlas": 2,
    "stat_map": 3,
    "reference_map": 4,
    "inventory_entry": 5,
}


def _asset_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    metadata = item.get("metadata") or {}
    dynamic_priority = 0 if metadata else 1
    return (
        _KIND_PRIORITY.get(str(item.get("kind") or "").strip().lower(), 99),
        dynamic_priority,
        item["family_id"],
        item.get("family") or "",
        item["canonical_runtime_name"] or item["id"],
    )


def _limit_assets(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(items) <= limit:
        return items

    kind_buckets: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for item in items:
        kind = str(item.get("kind") or "").strip().lower()
        family = str(item.get("family") or item.get("family_id") or "").strip()
        family_buckets = kind_buckets.setdefault(kind, {})
        family_buckets.setdefault(family, []).append(item)

    ordered_kinds = sorted(
        kind_buckets,
        key=lambda kind: (_KIND_PRIORITY.get(kind, 99), kind),
    )
    ordered_families = {
        kind: list(family_buckets.keys())
        for kind, family_buckets in kind_buckets.items()
    }
    limited: list[dict[str, Any]] = []

    while len(limited) < limit and ordered_kinds:
        next_round: list[str] = []
        for kind in ordered_kinds:
            family_buckets = kind_buckets.get(kind) or {}
            family_order = ordered_families.get(kind) or []
            if not family_order:
                continue

            selected_item: dict[str, Any] | None = None
            next_family_order: list[str] = []
            used_family = ""
            for family in family_order:
                bucket = family_buckets.get(family) or []
                if not bucket:
                    continue
                if selected_item is None:
                    selected_item = bucket.pop(0)
                    used_family = family
                if bucket:
                    next_family_order.append(family)

            if selected_item is None:
                continue

            limited.append(selected_item)
            if used_family and family_buckets.get(used_family):
                next_family_order.append(used_family)
            ordered_families[kind] = next_family_order
            if next_family_order:
                next_round.append(kind)
            if len(limited) >= limit:
                break
        ordered_kinds = next_round

    return limited


def _inventory_assets() -> list[dict[str, Any]]:
    payload = load_neuroimage_asset_registry()
    inventory_assets: list[dict[str, Any]] = []
    for family in payload.get("families") or []:
        if not isinstance(family, dict):
            continue
        family_id = str(family.get("family_id") or "").strip()
        family_title = str(family.get("title") or family_id).strip()
        for entry in family.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            asset_name = str(entry.get("asset_name") or "").strip()
            metadata = {
                "scope": str(entry.get("scope") or "").strip(),
                "format": str(entry.get("format") or "").strip(),
                "space_or_density": str(entry.get("space_or_density") or "").strip(),
                "local_status": str(entry.get("local_status") or "").strip(),
                "resolver_status": str(entry.get("resolver_status") or "").strip(),
                "provenance_status": str(entry.get("provenance_status") or "").strip(),
                "license_status": str(entry.get("license_status") or "").strip(),
                "priority": str(entry.get("priority") or "").strip(),
                "source": str(entry.get("source") or "").strip(),
                "next_action": str(entry.get("next_action") or "").strip(),
            }
            inventory_assets.append(
                {
                    "id": f"inventory.{family_id}.{asset_name}",
                    "kind": "inventory_entry",
                    "family_id": family_id,
                    "family": family_title,
                    "canonical_runtime_name": asset_name,
                    "title": asset_name,
                    "summary": str(entry.get("why_it_matters") or "").strip(),
                    "spaces": [metadata["space_or_density"]]
                    if metadata["space_or_density"]
                    else [],
                    "resolution": "",
                    "density": "",
                    "current_state": str(entry.get("current_state") or "").strip(),
                    "local_paths": [
                        str(path) for path in (entry.get("evidence_paths") or [])
                    ],
                    "aliases": [],
                    "metadata": metadata,
                }
            )
    return inventory_assets


def _write_inventory_json(output_dir: str, assets: list[dict[str, Any]]) -> str:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "neuroimage_asset_inventory.json"
    output_path.write_text(json.dumps(assets, indent=2), encoding="utf-8")
    return str(output_path)


class ListNeuroimageAssetsArgs(BaseModel):
    """Arguments for enumerating local neuroimage assets."""

    view: str = Field(
        default="concrete",
        description="Which records to return: concrete, inventory, or all.",
    )
    family: str | None = Field(
        default=None,
        description=(
            "Optional broad family filter: templates_spaces_transforms, "
            "atlases_parcellations, reference_maps_annotations, or stat_maps."
        ),
    )
    kind: str | None = Field(
        default=None,
        description=(
            "Optional kind filter: template, warp, atlas, reference_map, "
            "stat_map, or inventory_entry."
        ),
    )
    query: str | None = Field(
        default=None,
        description="Optional fuzzy query over IDs, aliases, titles, and summaries.",
    )
    space: str | None = Field(
        default=None,
        description="Optional space filter such as MNI152NLin2009cAsym, fsaverage, or fsLR.",
    )
    resolution: str | None = Field(
        default=None,
        description="Optional scale filter such as 2mm, 10k, 32k, or 164k.",
    )
    current_state: str | None = Field(
        default=None,
        description="Optional state filter such as already_usable or present_not_standardized.",
    )
    local_only: bool = Field(
        default=True,
        description="When true, only return concrete assets with at least one existing local path.",
    )
    include_metadata: bool = Field(
        default=False,
        description="Include raw metadata records in each returned asset when true.",
    )
    limit: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum number of assets to return.",
    )


class ListNeuroimageAssetsTool(NeuroToolWrapper):
    """List registry-backed neuroimage assets from local inventories."""

    execution_backend = "python"

    def get_tool_name(self) -> str:
        return "list_neuroimage_assets"

    def get_tool_description(self) -> str:
        return (
            "List registry-backed neuroimage templates, transforms, atlases, "
            "reference maps, and backlog inventory entries."
        )

    def get_args_schema(self):
        return ListNeuroimageAssetsArgs

    def _run(self, **kwargs) -> ToolResult:
        output_dir = kwargs.get("output_dir")
        args = ListNeuroimageAssetsArgs(**kwargs)

        view = str(args.view or "").strip().lower()
        if view not in {"concrete", "inventory", "all"}:
            return ToolResult(
                status="error",
                error="view must be one of concrete, inventory, or all",
                data={},
            )

        assets: list[dict[str, Any]] = []
        if view in {"concrete", "all"}:
            assets.extend(load_template_assets())
            assets.extend(load_transform_assets())
            assets.extend(load_reference_assets())
        if view in {"inventory", "all"}:
            assets.extend(_inventory_assets())

        filtered_assets: list[dict[str, Any]] = []
        requested_family = str(args.family or "").strip()
        requested_kind = str(args.kind or "").strip().lower()

        for asset in assets:
            family_id = _family_id_for_asset(asset)
            kind = _public_kind(asset).strip().lower()
            local_paths = asset.get("local_paths") or []

            if not _matches_family(asset, requested_family):
                continue
            if not _matches_kind(asset, requested_kind):
                continue
            if args.local_only and kind != "inventory_entry" and not local_paths:
                continue
            if not _matches_query(asset, args.query):
                continue
            if not _matches_space(asset, args.space):
                continue
            if not _matches_scale(asset, args.resolution):
                continue
            if not _matches_current_state(asset, args.current_state):
                continue

            filtered_assets.append(asset)

        filtered_assets.sort(
            key=lambda asset: _asset_sort_key(
                _public_asset_view(asset, include_metadata=True)
            )
        )
        total_matches = len(filtered_assets)
        limited_assets = _limit_assets(filtered_assets, args.limit)
        limited = [
            _public_asset_view(asset, include_metadata=args.include_metadata)
            for asset in limited_assets
        ]

        family_counts: dict[str, int] = {}
        subfamily_counts: dict[str, int] = {}
        kind_counts: dict[str, int] = {}
        for asset in filtered_assets:
            family_id = _family_id_for_asset(asset)
            subfamily_id = _subfamily_id_for_asset(asset)
            kind = _public_kind(asset).strip().lower()
            family_counts[family_id] = family_counts.get(family_id, 0) + 1
            if subfamily_id:
                subfamily_counts[subfamily_id] = (
                    subfamily_counts.get(subfamily_id, 0) + 1
                )
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

        outputs: dict[str, Any] = {
            "assets": limited,
            "asset_ids": [item["id"] for item in limited],
        }
        if output_dir:
            outputs["inventory_json"] = _write_inventory_json(output_dir, limited)

        return ToolResult(
            status="success",
            data={
                "outputs": outputs,
                "summary": {
                    "count": len(limited),
                    "total_matches": total_matches,
                    "view": view,
                    "family": args.family or "all",
                    "kind": args.kind or "all",
                    "query": args.query or "",
                    "space": args.space or "",
                    "resolution": args.resolution or "",
                    "current_state": args.current_state or "",
                    "local_only": args.local_only,
                    "include_metadata": args.include_metadata,
                    "family_counts": family_counts,
                    "subfamily_counts": subfamily_counts,
                    "kind_counts": kind_counts,
                },
            },
        )


class ListNeuroimageAssetsTools:
    @staticmethod
    def get_all_tools():
        return [ListNeuroimageAssetsTool()]


__all__ = ["ListNeuroimageAssetsTool", "ListNeuroimageAssetsTools"]
