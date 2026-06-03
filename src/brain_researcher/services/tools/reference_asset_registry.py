from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.config.paths import get_repo_root, resolve_from_config
from brain_researcher.services.tools.atlas_utils import (
    derive_local_atlas_labels,
    filename_entities,
    find_local_aal_atlas,
    find_local_destrieux_atlas,
    find_local_msdl_atlas,
    find_local_yeo_atlas,
)
from brain_researcher.services.tools.neuroimage_asset_registry import (
    atlas_cache_roots,
    clear_neuroimage_asset_registry_cache,
    reference_map_cache_roots,
)

_STATIC_REFERENCE_ASSET_FILES = (
    "cbig_assets.yaml",
    "reference_asset_registry.yaml",
)
_LEGACY_REFERENCE_ASSET_IDS = {
    "cbig.atlas.schaefer2018.400.17networks": "atlas.schaefer2018.400.17networks.bundle",
    "cbig.atlas.yeo2011.7networks": "atlas.yeo2011.7networks.bundle",
    "cbig.atlas.yeo2011.17networks": "atlas.yeo2011.17networks.bundle",
    "cbig.warp.wu2017.mni_fsaverage.rf_ants": "warp.mni_fsaverage.registration_fusion.ants",
    "cbig.method.deepresbat": "method.deepresbat.reference",
    "cbig.method.gcvae": "method.gcvae.reference",
    "cbig.atlas.schaefer2018_localglobal": "atlas.schaefer2018.localglobal_bundle",
    "cbig.atlas.yeo2011_networks": "atlas.yeo2011.network_bundle",
    "cbig.warp.wu2017_registration_fusion": "warp.mni_fsaverage.registration_fusion",
    "cbig.model.nguyen2020_rnnad": "model.longitudinal_progression.reference",
    "cbig.method.tang2020_asd_factors": "method.asd_factor_subtyping.reference",
    "cbig.method.sun2019_adjointfactors": "method.ad_joint_factor_subtyping.reference",
}
_REFERENCE_ASSET_ROOTS_ENV = "BR_REFERENCE_ASSET_ROOTS"
_DEFAULT_REFERENCE_ASSET_ROOTS = (
    "/app/data/reference_assets",
    "/srv/reference_assets",
)
_SCHAEFER_FILENAME_RE = re.compile(
    r"^Schaefer2018_(\d+)Parcels_(7|17)Networks_order_FSLMNI152_2mm\.nii(?:\.gz)?$"
)
_DIFUMO_FILENAME_RE = re.compile(
    r"(?:atlas-DiFuMo_dimension-|DiFuMo_|atlas-DiFuMo(?:_[^_]+-[^_]+)*_desc-)"
    r"(?P<dimension>\d+)(?:dimensions)?"
)
_HARVARD_FILENAME_RE = re.compile(r"^HarvardOxford-(.+)\.nii(?:\.gz)?$")
_REFERENCE_MAP_FILENAME_RE = re.compile(
    r"^source-(?P<source>[^_]+)_desc-(?P<desc>[^_]+)_space-(?P<space>[^_]+)_"
    r"(?P<scale_kind>res|den)-(?P<scale_value>[^_]+)"
    r"(?:_hemi-(?P<hemi>[LR]))?_feature\.(?P<suffix>.+)$"
)
_OPENNEURO_STATMAP_FILENAME_RE = re.compile(
    r"^(?:(?P<subject>sub-[^_]+)_)?contrast-(?P<contrast>[^_]+)_"
    r"stat-(?P<stat>[^_]+)_statmap\.nii(?:\.gz)?$"
)
_NEUROSYNTH_FLAT_STATMAP_RE = re.compile(
    r"^neurosynth_term_(?P<vocabulary>.+?)__(?P<term>.+)\.nii(?:\.gz)?$"
)
_NEUROSYNTH_BUNDLE_STATMAP_RE = re.compile(
    r"^neurosynth_(?P<vocabulary>.+?)__(?P<term>.+?)_(?P<stat>z|pAgF|pFgA)\.nii(?:\.gz)?$"
)
_OPENNEURO_DATASET_RE = re.compile(r"(ds\d+)")
_OPENNEURO_STAT_PREFERENCE = {
    "z": 0,
    "t": 1,
    "effect": 2,
    "variance": 3,
    "p": 4,
}


def _normalize_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _coerce_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        item = values.strip()
        return [item] if item else []
    if not isinstance(values, list):
        return []

    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        items.append(text)
        seen.add(text)
    return items


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", ".", str(value or "").strip().lower())
    return text.strip(".")


def _merge_unique(items: Iterable[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        merged.append(text)
        seen.add(text)
    return merged


def _atlas_metadata_specificity(metadata: dict[str, Any]) -> tuple[int, int, int]:
    space = str(metadata.get("space") or "").strip()
    resolution = str(metadata.get("resolution") or "").strip()
    templateflow_resolution = str(metadata.get("templateflow_resolution") or "").strip()
    normalized_space = _normalize_token(space)
    return (
        int(bool(templateflow_resolution)),
        int(bool(space) and normalized_space not in {"", "mni152"}),
        len(_normalize_token(resolution)),
    )


def _parse_templateflow_schaefer_filename(path: Path) -> tuple[int, int] | None:
    entities = filename_entities(path)
    if str(entities.get("atlas") or "").strip() != "Schaefer2018":
        return None
    desc = str(entities.get("desc") or "").strip()
    if not desc:
        return None
    match = re.fullmatch(r"(?P<rois>\d+)Parcels(?P<networks>\d+)Networks", desc)
    if match is None:
        return None
    return int(match.group("rois")), int(match.group("networks"))


def _normalize_asset(asset: dict[str, Any]) -> dict[str, Any] | None:
    asset_id = str(asset.get("id") or "").strip()
    if not asset_id:
        return None

    title = str(asset.get("title") or "").strip()
    canonical_runtime_name = str(asset.get("canonical_runtime_name") or "").strip()
    description = str(asset.get("description") or "").strip()
    summary = str(asset.get("summary") or "").strip() or description

    metadata = asset.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    normalized = {
        "id": asset_id,
        "kind": str(asset.get("kind") or "").strip(),
        "family": str(asset.get("family") or "").strip(),
        "bundle_id": str(asset.get("bundle_id") or "").strip(),
        "canonical_runtime_name": canonical_runtime_name,
        "title": title,
        "aliases": _coerce_list(asset.get("aliases")),
        "spaces": _coerce_list(asset.get("spaces")),
        "modalities": _coerce_list(asset.get("modalities")),
        "tags": _coerce_list(asset.get("tags")),
        "summary": summary,
        "description": description,
        "source_repo": str(asset.get("source_repo") or "").strip(),
        "source_release": str(asset.get("source_release") or "").strip(),
        "source_project": str(asset.get("source_project") or "").strip(),
        "source_paper": str(asset.get("source_paper") or "").strip(),
        "version": str(asset.get("version") or "").strip(),
        "license": str(asset.get("license") or "").strip(),
        "local_search_hints": _coerce_list(asset.get("local_search_hints")),
        "local_paths": _coerce_list(
            asset.get("local_paths") or asset.get("paths") or asset.get("files")
        ),
        "urls": _coerce_list(asset.get("urls")),
        "formats": _coerce_list(asset.get("formats")),
        "hemispheres": _coerce_list(asset.get("hemispheres")),
        "resolution": str(asset.get("resolution") or "").strip(),
        "density": str(asset.get("density") or "").strip(),
        "metadata": dict(metadata),
    }
    return normalized


def _merge_asset_records(
    base: dict[str, Any],
    extra: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(base)
    base_metadata = dict(base.get("metadata") or {})
    extra_metadata = dict(extra.get("metadata") or {})
    extra_metadata_preferred = _atlas_metadata_specificity(extra_metadata) >= (
        _atlas_metadata_specificity(base_metadata)
    )

    for key in (
        "kind",
        "family",
        "bundle_id",
        "canonical_runtime_name",
        "title",
        "summary",
        "description",
        "source_repo",
        "source_release",
        "source_project",
        "source_paper",
        "version",
        "license",
        "resolution",
        "density",
    ):
        if (
            key in {"resolution", "density"}
            and extra_metadata_preferred
            and extra.get(key)
        ):
            merged[key] = extra[key]
        elif not merged.get(key) and extra.get(key):
            merged[key] = extra[key]

    for key in (
        "aliases",
        "spaces",
        "modalities",
        "tags",
        "local_search_hints",
        "local_paths",
        "urls",
        "formats",
        "hemispheres",
    ):
        merged[key] = _merge_unique((merged.get(key) or []) + (extra.get(key) or []))

    if extra_metadata_preferred:
        merged_metadata = dict(base_metadata)
        merged_metadata.update(extra_metadata)
    else:
        merged_metadata = dict(extra_metadata)
        merged_metadata.update(base_metadata)
    merged["metadata"] = merged_metadata
    return merged


def clear_reference_asset_registry_cache() -> None:
    clear_neuroimage_asset_registry_cache()
    load_reference_assets.cache_clear()
    load_reference_asset_index.cache_clear()
    load_reference_asset_alias_index.cache_clear()
    _load_static_yaml_assets.cache_clear()
    _discover_local_atlas_assets.cache_clear()
    _discover_reference_map_assets.cache_clear()
    _load_openneuro_dataset_description.cache_clear()
    _load_neuromaps_annotation_metadata.cache_clear()
    reference_asset_search_roots.cache_clear()


@lru_cache(maxsize=1)
def reference_asset_search_roots() -> list[Path]:
    raw_env = os.getenv(_REFERENCE_ASSET_ROOTS_ENV, "").strip()
    env_roots = [item.strip() for item in raw_env.split(",") if item.strip()]
    roots = [
        Path(item).expanduser()
        for item in (env_roots or _DEFAULT_REFERENCE_ASSET_ROOTS)
    ]

    repo_reference_assets = get_repo_root() / "data" / "reference_assets"
    roots.append(repo_reference_assets)

    unique_roots: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except Exception:
            resolved = root
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists():
            unique_roots.append(resolved)
    return unique_roots


def _resolve_existing_paths(paths: Iterable[Path]) -> list[str]:
    resolved_paths: list[str] = []
    seen: set[str] = set()
    for path in paths:
        try:
            exists = path.exists()
        except OSError:
            exists = False
        if not exists:
            continue
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        for candidate in (path, resolved):
            text = str(candidate)
            if text in seen:
                continue
            seen.add(text)
            resolved_paths.append(text)
    return resolved_paths


def _static_local_hint_paths(asset: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for hint in asset.get("local_search_hints") or []:
        candidate = Path(str(hint or "").strip()).expanduser()
        if not candidate.is_absolute():
            candidate = get_repo_root() / candidate
        paths.append(candidate)
    return paths


def _bundle_candidate_paths(asset: dict[str, Any]) -> list[Path]:
    kind = str(asset.get("kind") or "").strip().lower()
    if kind not in {"method_bundle", "model_bundle"}:
        return []

    asset_id = str(asset.get("id") or "").strip()
    source_project = str(asset.get("source_project") or "").strip()
    source_repo = str(asset.get("source_repo") or "").strip().lower()
    materialized_family = (
        "method_bundles" if kind == "method_bundle" else "model_bundles"
    )

    candidates: list[Path] = []
    for root in reference_asset_search_roots():
        materialized_dir = root / "materialized" / materialized_family / asset_id
        candidates.append(materialized_dir)
        candidates.append(materialized_dir / "source")

        if source_project:
            candidates.append(root / "repos" / "cbig" / source_project)
            if "thomasyeolab/cbig" in source_repo or source_project.startswith(
                "stable_projects/"
            ):
                candidates.append(root / "repos" / "cbig" / "CBIG" / source_project)

    return candidates


def _augment_static_asset_local_paths(asset: dict[str, Any]) -> dict[str, Any]:
    augmented = dict(asset)
    hint_paths = _static_local_hint_paths(augmented)
    bundle_paths = _bundle_candidate_paths(augmented)
    augmented["local_paths"] = _merge_unique(
        (augmented.get("local_paths") or [])
        + _resolve_existing_paths([*hint_paths, *bundle_paths])
    )
    return augmented


def _path_format(path: Path) -> str:
    suffixes = path.suffixes
    if not suffixes:
        return path.name
    if len(suffixes) >= 2:
        return "".join(suffixes[-2:])
    return suffixes[-1]


def _path_basename_without_suffix(path: Path) -> str:
    name = path.name
    for suffix in (
        ".nii.gz",
        ".pkl.gz",
        ".json.gz",
        ".tsv.gz",
        ".func.gii",
        ".shape.gii",
        ".surf.gii",
        ".label.gii",
        ".annot",
        ".npz",
        ".json",
        ".tsv",
        ".txt",
        ".nii",
        ".gz",
    ):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def _find_named_files(roots: list[Path], filenames: Iterable[str]) -> list[str]:
    matches: list[str] = []
    for filename in filenames:
        text = str(filename or "").strip()
        if not text:
            continue
        for root in roots:
            for path in sorted(root.rglob(text)):
                if path.is_file():
                    matches.append(str(path.resolve()))
    return _merge_unique(matches)


@lru_cache(maxsize=512)
def _load_openneuro_dataset_description(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _openneuro_space_aliases(space: str) -> list[str]:
    canonical = str(space or "").strip()
    if not canonical:
        return []
    aliases = [canonical]
    if _normalize_token(canonical).startswith("mni152") and "MNI152" not in aliases:
        aliases.append("MNI152")
    return aliases


def _canonicalize_neurosynth_stat(value: str) -> str:
    stat = str(value or "").strip()
    if not stat:
        return ""
    lowered = stat.lower()
    return {
        "pagf": "pAgF",
        "pfga": "pFgA",
    }.get(lowered, stat)


@lru_cache(maxsize=1)
def _load_static_yaml_assets() -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for filename in _STATIC_REFERENCE_ASSET_FILES:
        path = resolve_from_config("reference_assets", filename)
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw_assets = data.get("assets")
        if not isinstance(raw_assets, list):
            continue
        for raw_asset in raw_assets:
            if not isinstance(raw_asset, dict):
                continue
            normalized = _normalize_asset(raw_asset)
            if normalized is not None:
                assets.append(_augment_static_asset_local_paths(normalized))
    return assets


def _atlas_record(
    *,
    asset_id: str,
    family: str,
    canonical_runtime_name: str,
    aliases: list[str],
    spaces: list[str],
    local_paths: list[str],
    summary: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": asset_id,
        "kind": "atlas",
        "family": family,
        "bundle_id": "",
        "canonical_runtime_name": canonical_runtime_name,
        "title": "",
        "aliases": _merge_unique(aliases),
        "spaces": _merge_unique(spaces),
        "modalities": ["fmri", "smri"],
        "tags": ["atlas", "parcellation", family],
        "summary": summary,
        "description": "",
        "source_repo": "",
        "source_release": "",
        "source_project": "",
        "source_paper": "",
        "version": "",
        "license": "",
        "local_paths": _merge_unique(local_paths),
        "urls": [],
        "formats": [],
        "hemispheres": [],
        "resolution": str(metadata.get("resolution") or "").strip(),
        "density": str(metadata.get("density") or "").strip(),
        "metadata": metadata,
    }


def _count_non_background_labels(labels: list[str]) -> int:
    if not labels:
        return 0
    first = labels[0].strip().lower()
    if first in {"background", "unknown", "???", "none"}:
        return max(len(labels) - 1, 0)
    return len(labels)


def _templateflow_resolution_label(raw_value: str | None) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    if text.lower().endswith("mm"):
        return text
    if text.isdigit():
        return f"{int(text)}mm"
    return text


def _atlas_space_metadata(path: Path) -> tuple[str, list[str], str, str]:
    entities = filename_entities(path)
    specific_space = str(entities.get("tpl") or entities.get("space") or "").strip()
    raw_res = str(entities.get("res") or "").strip()
    resolution = _templateflow_resolution_label(raw_res) or "2mm"
    metadata_space = specific_space or "MNI152"
    spaces = _merge_unique([metadata_space, "MNI152"])
    return metadata_space, spaces, resolution, raw_res


def _default_schaefer_aliases(n_rois: int, n_networks: int) -> list[str]:
    if int(n_networks) != 7:
        return []
    return [
        f"Schaefer2018_{n_rois}",
        f"Schaefer2018_{n_rois}Parcels",
        f"schaefer{n_rois}",
    ]


def _discover_schaefer_assets(roots: list[Path]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        for path in sorted(root.rglob("*.nii*")):
            match = _SCHAEFER_FILENAME_RE.match(path.name)
            templateflow_match = _parse_templateflow_schaefer_filename(path)
            if match is None and templateflow_match is None:
                continue
            try:
                if not path.is_file() or path.stat().st_size <= 0:
                    continue
            except OSError:
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            if match is not None:
                n_rois = int(match.group(1))
                n_networks = int(match.group(2))
                metadata_space = "MNI152"
                spaces = ["MNI152"]
                resolution = "2mm"
                raw_res = ""
                variant_key = f"{n_rois}_{n_networks}n_2mm"
            else:
                n_rois, n_networks = templateflow_match
                metadata_space, spaces, resolution, raw_res = _atlas_space_metadata(
                    path
                )
                variant_key = (
                    f"{n_rois}_{n_networks}n_{_slugify(metadata_space)}"
                    f"_{_slugify(raw_res or resolution)}"
                )
            asset_id = f"nilearn.atlas.schaefer2018.{n_rois}.{n_networks}networks"
            canonical = f"Schaefer2018_{n_rois}_{n_networks}Networks"
            assets.append(
                _atlas_record(
                    asset_id=asset_id,
                    family="schaefer_2018",
                    canonical_runtime_name=canonical,
                    aliases=[
                        canonical,
                        f"Schaefer2018_{n_rois}Parcels_{n_networks}Networks",
                        f"schaefer{n_rois}_{n_networks}n",
                        f"schaefer_{n_rois}_{n_networks}networks",
                        *_default_schaefer_aliases(n_rois, n_networks),
                    ],
                    spaces=spaces,
                    local_paths=[str(path)],
                    summary=(
                        f"Local Schaefer2018 atlas with {n_rois} parcels and "
                        f"{n_networks} Yeo networks in {metadata_space} {resolution} space."
                    ),
                    metadata={
                        "atlas_family_id": "schaefer2018",
                        "variant_key": variant_key,
                        "space_kind": "volume",
                        "space": metadata_space,
                        "resolution": resolution,
                        "runtime_family_dir": "schaefer_2018",
                        "n_regions": n_rois,
                        "yeo_networks": n_networks,
                        "templateflow_resolution": raw_res,
                    },
                )
            )
    return assets


def _discover_aal_assets(roots: list[Path]) -> list[dict[str, Any]]:
    path = find_local_aal_atlas(roots)
    if path is None:
        return []
    labels = derive_local_atlas_labels(path, atlas_name="aal", family="aal")
    return [
        _atlas_record(
            asset_id="nilearn.atlas.aal_spm12_116",
            family="aal",
            canonical_runtime_name="aal",
            aliases=["aal", "AAL", "aal_spm12", "ROI_MNI_V4"],
            spaces=["MNI152"],
            local_paths=[str(path)],
            summary="Local AAL SPM12 atlas in MNI152 space.",
            metadata={
                "atlas_family_id": "aal_spm12",
                "variant_key": "aal_spm12_116",
                "space_kind": "volume",
                "space": "MNI152",
                "resolution": "2mm",
                "runtime_family_dir": "aal",
                "n_regions": _count_non_background_labels(labels),
            },
        )
    ]


def _discover_harvard_assets(roots: list[Path]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    alias_map = {
        "cort-maxprob-thr25-2mm": "harvard_oxford_cort25",
        "sub-maxprob-thr25-2mm": "harvard_oxford_sub25",
        "cortl-maxprob-thr25-2mm": "harvard_oxford_cortl25",
    }
    for root in roots:
        for path in sorted(root.rglob("HarvardOxford-*.nii*")):
            match = _HARVARD_FILENAME_RE.match(path.name)
            if match is None:
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            variant = match.group(1)
            labels = derive_local_atlas_labels(
                path,
                atlas_name=f"harvard_oxford_{variant}",
                family="harvard_oxford",
            )
            resolution_match = re.search(r"(\d+mm)$", variant)
            canonical = alias_map.get(variant, f"HarvardOxford-{variant}")
            assets.append(
                _atlas_record(
                    asset_id=f"nilearn.atlas.harvard_oxford.{_slugify(variant)}",
                    family="harvard_oxford",
                    canonical_runtime_name=canonical,
                    aliases=[
                        canonical,
                        f"HarvardOxford-{variant}",
                        variant,
                    ],
                    spaces=["MNI152"],
                    local_paths=[str(path)],
                    summary=f"Local Harvard-Oxford atlas variant '{variant}'.",
                    metadata={
                        "atlas_family_id": "harvard_oxford",
                        "variant_key": variant,
                        "space_kind": "volume",
                        "space": "MNI152",
                        "resolution": (
                            resolution_match.group(1) if resolution_match else ""
                        ),
                        "runtime_family_dir": "harvard_oxford",
                        "n_regions": _count_non_background_labels(labels),
                    },
                )
            )
    return assets


def _discover_yeo_assets(roots: list[Path]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for n_networks in (7, 17):
        volume_path = find_local_yeo_atlas(n_networks, roots)
        if volume_path is not None:
            labels = derive_local_atlas_labels(
                volume_path,
                atlas_name=f"yeo{n_networks}",
                family="yeo_2011",
            )
            assets.append(
                _atlas_record(
                    asset_id=f"nilearn.atlas.yeo2011.{n_networks}networks.volume",
                    family="yeo_2011",
                    canonical_runtime_name=f"yeo{n_networks}_volume",
                    aliases=[
                        f"yeo{n_networks}_volume",
                        f"Yeo2011_{n_networks}Networks_MNI152",
                    ],
                    spaces=["MNI152"],
                    local_paths=[str(volume_path)],
                    summary=(
                        f"Local Yeo2011 {n_networks}-network volume atlas in "
                        "MNI152 FreeSurfer-conformed 1mm space."
                    ),
                    metadata={
                        "atlas_family_id": "yeo2011",
                        "variant_key": f"{n_networks}networks_volume",
                        "space_kind": "volume",
                        "space": "MNI152",
                        "resolution": "1mm",
                        "runtime_family_dir": "yeo_2011",
                        "n_regions": _count_non_background_labels(labels),
                        "yeo_networks": n_networks,
                    },
                )
            )
    return assets


def _discover_destrieux_assets(roots: list[Path]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for lateralized in (False, True):
        path = find_local_destrieux_atlas(roots, lateralized=lateralized)
        if path is None:
            continue
        atlas_name = "destrieux_2009_lateralized" if lateralized else "destrieux_2009"
        labels = derive_local_atlas_labels(
            path,
            atlas_name=atlas_name,
            family="destrieux_2009",
        )
        assets.append(
            _atlas_record(
                asset_id=f"nilearn.atlas.{atlas_name}",
                family="destrieux_2009",
                canonical_runtime_name=atlas_name,
                aliases=[atlas_name, "destrieux"],
                spaces=["MNI152"],
                local_paths=[str(path)],
                summary="Local Destrieux 2009 atlas staged from the Nilearn cache.",
                metadata={
                    "atlas_family_id": "destrieux_2009",
                    "variant_key": ("lateralized" if lateralized else "default_volume"),
                    "space_kind": "volume",
                    "space": "MNI152",
                    "resolution": "",
                    "runtime_family_dir": "destrieux_2009",
                    "n_regions": _count_non_background_labels(labels),
                    "lateralized": lateralized,
                },
            )
        )
    return assets


def _discover_basc_assets(roots: list[Path]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    seen: set[int] = set()
    for root in roots:
        for path in sorted(
            root.rglob("template_cambridge_basc_multiscale_sym_scale*.nii.gz")
        ):
            match = re.search(r"scale(\d+)\.nii\.gz$", path.name)
            if match is None:
                continue
            scale = int(match.group(1))
            if scale in seen:
                continue
            seen.add(scale)
            assets.append(
                _atlas_record(
                    asset_id=f"nilearn.atlas.basc_multiscale_2015_scale{scale}",
                    family="basc_multiscale_2015",
                    canonical_runtime_name=f"basc_scale{scale}",
                    aliases=[
                        f"basc_scale{scale}",
                        f"basc{scale}",
                        f"basc_multiscale_2015_scale{scale}",
                    ],
                    spaces=["MNI152"],
                    local_paths=[str(path)],
                    summary=(
                        f"Local BASC multiscale 2015 atlas at scale {scale} "
                        "in symmetric MNI152 space."
                    ),
                    metadata={
                        "atlas_family_id": "basc_multiscale_2015",
                        "variant_key": f"scale{scale}",
                        "space_kind": "volume",
                        "space": "MNI152",
                        "resolution": "",
                        "runtime_family_dir": "basc_multiscale_2015",
                        "n_regions": scale,
                    },
                )
            )
    return assets


def _discover_msdl_assets(roots: list[Path]) -> list[dict[str, Any]]:
    path = find_local_msdl_atlas(roots)
    if path is None:
        return []
    labels = derive_local_atlas_labels(path, atlas_name="msdl", family="msdl_atlas")
    return [
        _atlas_record(
            asset_id="nilearn.atlas.msdl",
            family="msdl_atlas",
            canonical_runtime_name="msdl",
            aliases=["msdl", "msdl_atlas"],
            spaces=["MNI152"],
            local_paths=[str(path)],
            summary="Local MSDL dictionary-learning atlas in MNI152 space.",
            metadata={
                "atlas_family_id": "msdl",
                "variant_key": "default",
                "space_kind": "volume",
                "space": "MNI152",
                "resolution": "2mm",
                "runtime_family_dir": "msdl_atlas",
                "n_regions": _count_non_background_labels(labels),
            },
        )
    ]


def _discover_difumo_assets(roots: list[Path]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        for path in sorted(root.rglob("*.nii*")):
            match = _DIFUMO_FILENAME_RE.search(path.name)
            if match is None:
                continue
            try:
                if not path.is_file() or path.stat().st_size <= 0:
                    continue
            except OSError:
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            dimension = int(match.group("dimension"))
            metadata_space, spaces, resolution, raw_res = _atlas_space_metadata(path)
            labels = derive_local_atlas_labels(
                path,
                atlas_name=f"difumo{dimension}",
                family="difumo",
            )
            assets.append(
                _atlas_record(
                    asset_id=f"nilearn.atlas.difumo.{dimension}",
                    family="difumo",
                    canonical_runtime_name=f"difumo{dimension}",
                    aliases=[f"difumo{dimension}", f"DiFuMo_{dimension}"],
                    spaces=spaces,
                    local_paths=[str(path)],
                    summary=(
                        f"Local DiFuMo {dimension}-component atlas in {metadata_space} "
                        f"{resolution} "
                        "volume space."
                    ),
                    metadata={
                        "atlas_family_id": "difumo",
                        "variant_key": (
                            f"dimension-{dimension}_{_slugify(metadata_space)}_"
                            f"{_slugify(raw_res or resolution)}"
                        ),
                        "space_kind": "volume",
                        "space": metadata_space,
                        "resolution": resolution,
                        "runtime_family_dir": "difumo",
                        "n_regions": _count_non_background_labels(labels),
                        "dimension": dimension,
                        "templateflow_resolution": raw_res,
                    },
                )
            )
    return assets


@lru_cache(maxsize=1)
def _discover_local_atlas_assets() -> list[dict[str, Any]]:
    roots = [root for root in atlas_cache_roots() if root.exists()]
    if not roots:
        return []

    assets: list[dict[str, Any]] = []
    assets.extend(_discover_schaefer_assets(roots))
    assets.extend(_discover_aal_assets(roots))
    assets.extend(_discover_harvard_assets(roots))
    assets.extend(_discover_yeo_assets(roots))
    assets.extend(_discover_destrieux_assets(roots))
    assets.extend(_discover_basc_assets(roots))
    assets.extend(_discover_msdl_assets(roots))
    assets.extend(_discover_difumo_assets(roots))
    return assets


@lru_cache(maxsize=1)
def _load_neuromaps_annotation_metadata() -> (
    dict[tuple[str, str, str, str], dict[str, Any]]
):
    try:
        from neuromaps.datasets import annotations
    except Exception:
        return {}

    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "tags": set(),
            "urls": set(),
            "formats": set(),
            "hemispheres": set(),
            "title": "",
        }
    )
    try:
        entries = annotations.get_dataset_info("annotations", False)
    except Exception:
        return {}

    for entry in entries:
        source = str(entry.get("source") or "").strip()
        desc = str(entry.get("desc") or "").strip()
        space = str(entry.get("space") or "").strip()
        scale_value = str(entry.get("den") or entry.get("res") or "").strip()
        if not (source and desc and space and scale_value):
            continue
        key = (source, desc, space, scale_value)
        grouped[key]["tags"].update(_coerce_list(entry.get("tags")))
        if entry.get("url"):
            grouped[key]["urls"].add(str(entry["url"]).strip())
        if entry.get("format"):
            grouped[key]["formats"].add(str(entry["format"]).strip())
        if entry.get("hemi"):
            grouped[key]["hemispheres"].add(str(entry["hemi"]).strip())
        if entry.get("title") and not grouped[key]["title"]:
            grouped[key]["title"] = str(entry["title"]).strip()

    normalized: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for key, payload in grouped.items():
        normalized[key] = {
            "tags": sorted(payload["tags"]),
            "urls": sorted(payload["urls"]),
            "formats": sorted(payload["formats"]),
            "hemispheres": sorted(payload["hemispheres"]),
            "title": payload["title"],
        }
    return normalized


def _discover_neuromaps_annotation_assets(roots: list[Path]) -> list[dict[str, Any]]:
    if not roots:
        return []

    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "paths": [],
            "hemispheres": set(),
            "formats": set(),
        }
    )

    for root in roots:
        for path in sorted(root.rglob("source-*")):
            if not path.is_file():
                continue
            match = _REFERENCE_MAP_FILENAME_RE.match(path.name)
            if match is None:
                continue
            source = match.group("source")
            desc = match.group("desc")
            space = match.group("space")
            scale_kind = match.group("scale_kind")
            scale_value = match.group("scale_value")
            hemi = match.group("hemi")
            grouped[(source, desc, space, scale_kind, scale_value)]["paths"].append(
                str(path)
            )
            if hemi:
                grouped[(source, desc, space, scale_kind, scale_value)][
                    "hemispheres"
                ].add(hemi)
            grouped[(source, desc, space, scale_kind, scale_value)]["formats"].add(
                path.suffix or path.name.split(".", 1)[-1]
            )

    metadata_index = _load_neuromaps_annotation_metadata()
    assets: list[dict[str, Any]] = []
    for (source, desc, space, scale_kind, scale_value), payload in sorted(
        grouped.items()
    ):
        extra = metadata_index.get((source, desc, space, scale_value), {})
        space_kind = "surface" if space in {"fsaverage", "fsLR", "civet"} else "volume"
        metric_key = "density" if scale_kind == "den" else "resolution"
        summary = (
            f"Local neuromaps annotation {source}/{desc} in {space} "
            f"({scale_kind}={scale_value})."
        )
        assets.append(
            {
                "id": (
                    f"neuromaps.annotation.{_slugify(source)}."
                    f"{_slugify(desc)}.{_slugify(space)}.{_slugify(scale_value)}"
                ),
                "kind": "reference_map",
                "family": "neuromaps_annotation",
                "bundle_id": "",
                "canonical_runtime_name": f"{source}_{desc}",
                "title": str(extra.get("title") or "").strip(),
                "aliases": _merge_unique(
                    [
                        desc,
                        f"{source}_{desc}",
                        f"{source}:{desc}",
                        f"{source}-{desc}",
                    ]
                ),
                "spaces": [space],
                "modalities": ["fmri", "smri"],
                "tags": _merge_unique(
                    ["reference_map", "neuromaps", source, desc]
                    + list(extra.get("tags") or [])
                ),
                "summary": summary,
                "description": "",
                "source_repo": "",
                "source_release": "",
                "source_project": "neuromaps",
                "source_paper": "",
                "version": "",
                "license": "",
                "local_paths": sorted(payload["paths"]),
                "urls": _coerce_list(extra.get("urls")),
                "formats": _merge_unique(
                    list(extra.get("formats") or []) + sorted(payload["formats"])
                ),
                "hemispheres": _merge_unique(
                    list(extra.get("hemispheres") or [])
                    + sorted(payload["hemispheres"])
                ),
                "resolution": scale_value if scale_kind == "res" else "",
                "density": scale_value if scale_kind == "den" else "",
                "metadata": {
                    "atlas_family_id": "reference_maps_annotations",
                    "variant_key": f"{source}_{desc}_{space}_{scale_value}",
                    "space_kind": space_kind,
                    "space": space,
                    metric_key: scale_value,
                    "source_dataset": source,
                    "description_key": desc,
                },
            }
        )
    return assets


def _discover_neurosynth_statmap_assets(roots: list[Path]) -> list[dict[str, Any]]:
    if not roots:
        return []

    assets: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    shared_spaces = ["MNI152", "MNI152NLin2009cAsym"]

    for root in roots:
        for path in sorted(root.rglob("neurosynth_term_*.nii*")):
            if not path.is_file():
                continue
            match = _NEUROSYNTH_FLAT_STATMAP_RE.match(path.name)
            if match is None:
                continue
            resolved_key = str(path.resolve())
            if resolved_key in seen_paths:
                continue
            seen_paths.add(resolved_key)

            vocabulary = str(match.group("vocabulary") or "").strip()
            term = str(match.group("term") or "").strip()
            if not (vocabulary and term):
                continue

            basename = _path_basename_without_suffix(path)
            assets.append(
                {
                    "id": (f"neurosynth.term.{_slugify(vocabulary)}.{_slugify(term)}"),
                    "kind": "reference_map",
                    "family": "neurosynth_term_map",
                    "bundle_id": "",
                    "canonical_runtime_name": f"neurosynth_{term}",
                    "title": "",
                    "aliases": _merge_unique(
                        [
                            term,
                            f"neurosynth:{term}",
                            basename,
                        ]
                    ),
                    "spaces": shared_spaces,
                    "modalities": ["fmri"],
                    "tags": [
                        "reference_map",
                        "neurosynth",
                        "statmap",
                        "term_map",
                        vocabulary,
                    ],
                    "summary": (
                        f"Local Neurosynth term stat map for '{term}' using "
                        f"{vocabulary} vocabulary weights."
                    ),
                    "description": "",
                    "source_repo": "",
                    "source_release": "",
                    "source_project": "neurosynth",
                    "source_paper": "",
                    "version": "",
                    "license": "",
                    "local_paths": [resolved_key],
                    "urls": [],
                    "formats": [_path_format(path)],
                    "hemispheres": [],
                    "resolution": "",
                    "density": "",
                    "metadata": {
                        "atlas_family_id": "reference_maps_annotations",
                        "variant_key": f"{vocabulary}_{term}",
                        "space_kind": "volume",
                        "space": "MNI152",
                        "source_dataset": "neurosynth",
                        "description_key": term,
                        "vocabulary": vocabulary,
                        "map_variant": "term_flat",
                    },
                }
            )

        for path in sorted(root.rglob("neurosynth_*_*.nii*")):
            if not path.is_file():
                continue
            match = _NEUROSYNTH_BUNDLE_STATMAP_RE.match(path.name)
            if match is None:
                continue
            resolved_key = str(path.resolve())
            if resolved_key in seen_paths:
                continue
            seen_paths.add(resolved_key)

            vocabulary = str(match.group("vocabulary") or "").strip()
            term = str(match.group("term") or "").strip()
            statistic = _canonicalize_neurosynth_stat(match.group("stat"))
            if not (vocabulary and term and statistic):
                continue

            basename = _path_basename_without_suffix(path)
            companion_paths = [resolved_key]
            roi_summary = path.parent / "roi_summary.tsv"
            if roi_summary.exists():
                companion_paths.append(str(roi_summary.resolve()))

            aliases = [
                f"{term}_{statistic}",
                f"neurosynth:{term}:{statistic}",
                basename,
            ]
            if statistic == "z":
                aliases.append(term)

            assets.append(
                {
                    "id": (
                        f"neurosynth.map.{_slugify(vocabulary)}."
                        f"{_slugify(term)}.{_slugify(statistic)}"
                    ),
                    "kind": "reference_map",
                    "family": "neurosynth_term_map",
                    "bundle_id": "",
                    "canonical_runtime_name": f"neurosynth_{term}_{statistic}",
                    "title": "",
                    "aliases": _merge_unique(aliases),
                    "spaces": shared_spaces,
                    "modalities": ["fmri"],
                    "tags": [
                        "reference_map",
                        "neurosynth",
                        "statmap",
                        "bundle_map",
                        vocabulary,
                        statistic,
                    ],
                    "summary": (
                        f"Local Neurosynth {statistic} map for '{term}' from "
                        f"{vocabulary} bundle exports."
                    ),
                    "description": "",
                    "source_repo": "",
                    "source_release": "",
                    "source_project": "neurosynth",
                    "source_paper": "",
                    "version": "",
                    "license": "",
                    "local_paths": companion_paths,
                    "urls": [],
                    "formats": _merge_unique(
                        [_path_format(Path(candidate)) for candidate in companion_paths]
                    ),
                    "hemispheres": [],
                    "resolution": "",
                    "density": "",
                    "metadata": {
                        "atlas_family_id": "reference_maps_annotations",
                        "variant_key": f"{vocabulary}_{term}_{statistic}",
                        "space_kind": "volume",
                        "space": "MNI152",
                        "source_dataset": "neurosynth",
                        "description_key": term,
                        "vocabulary": vocabulary,
                        "statistic": statistic,
                        "map_variant": "bundle_map",
                    },
                }
            )

    return assets


def _discover_neurosynth_bundle_assets(roots: list[Path]) -> list[dict[str, Any]]:
    if not roots:
        return []

    coordinates_and_metadata = [
        "data-neurosynth_version-7_coordinates.tsv.gz",
        "data-neurosynth_version-7_metadata.tsv.gz",
    ]
    bundle_specs = [
        {
            "id": "neurosynth.nimare.dataset.v7",
            "canonical_runtime_name": "neurosynth_dataset_v7",
            "aliases": [
                "neurosynth_dataset_v7",
                "neurosynth_dataset",
                "nimare_dataset_v7",
                "nimare_dataset",
                "neurosynth_v7",
                "nimare_v7",
            ],
            "filenames": [
                "neurosynth_dataset_v7.pkl.gz",
                "neurosynth_dataset_v7.json.gz",
                *coordinates_and_metadata,
            ],
            "description_key": "dataset_v7",
            "summary": "Local Neurosynth/NiMARE dataset bundle for Neurosynth version 7.",
            "tags": ["reference_map", "neurosynth", "nimare", "dataset_bundle"],
        },
        {
            "id": "neurosynth.nimare.terms_tfidf.v7",
            "canonical_runtime_name": "neurosynth_terms_tfidf_v7",
            "aliases": [
                "terms_tfidf",
                "neurosynth_terms_tfidf",
                "neurosynth_terms_tfidf_v7",
                "nimare_terms_tfidf",
            ],
            "filenames": [
                "data-neurosynth_version-7_vocab-terms_source-abstract_type-tfidf_features.npz",
                "data-neurosynth_version-7_vocab-terms_vocabulary.txt",
                *coordinates_and_metadata,
            ],
            "description_key": "terms_tfidf",
            "summary": "Local Neurosynth term TF-IDF features bundle for version 7.",
            "tags": ["reference_map", "neurosynth", "nimare", "tfidf", "terms"],
        },
        *[
            {
                "id": f"neurosynth.nimare.lda{n_topics}.v7",
                "canonical_runtime_name": f"neurosynth_lda{n_topics}_v7",
                "aliases": [
                    f"lda{n_topics}",
                    f"neurosynth_lda{n_topics}",
                    f"neurosynth_lda{n_topics}_v7",
                    f"nimare_lda{n_topics}",
                ],
                "filenames": [
                    f"data-neurosynth_version-7_vocab-LDA{n_topics}_source-abstract_type-weight_features.npz",
                    f"data-neurosynth_version-7_vocab-LDA{n_topics}_metadata.json",
                    f"data-neurosynth_version-7_vocab-LDA{n_topics}_keys.tsv",
                    f"data-neurosynth_version-7_vocab-LDA{n_topics}_vocabulary.txt",
                    *coordinates_and_metadata,
                ],
                "description_key": f"lda{n_topics}",
                "summary": (
                    f"Local Neurosynth LDA{n_topics} topic-model bundle for version 7."
                ),
                "tags": [
                    "reference_map",
                    "neurosynth",
                    "nimare",
                    "topic_model",
                    f"lda{n_topics}",
                ],
            }
            for n_topics in (50, 100, 200, 400)
        ],
    ]

    assets: list[dict[str, Any]] = []
    for spec in bundle_specs:
        local_paths = _find_named_files(roots, spec["filenames"])
        if not local_paths:
            continue
        assets.append(
            {
                "id": spec["id"],
                "kind": "reference_map",
                "family": "neurosynth_nimare",
                "bundle_id": "",
                "canonical_runtime_name": spec["canonical_runtime_name"],
                "title": "",
                "aliases": _merge_unique(spec["aliases"]),
                "spaces": [],
                "modalities": ["fmri"],
                "tags": spec["tags"],
                "summary": spec["summary"],
                "description": "",
                "source_repo": "",
                "source_release": "v7",
                "source_project": "neurosynth_nimare",
                "source_paper": "",
                "version": "7",
                "license": "",
                "local_paths": local_paths,
                "urls": [],
                "formats": _merge_unique(
                    [_path_format(Path(path)) for path in local_paths]
                ),
                "hemispheres": [],
                "resolution": "",
                "density": "",
                "metadata": {
                    "atlas_family_id": "reference_maps_annotations",
                    "variant_key": spec["description_key"],
                    "space_kind": "literature_model",
                    "source_dataset": "neurosynth_nimare",
                    "description_key": spec["description_key"],
                    "version": "7",
                    "bundle_kind": spec["description_key"],
                },
            }
        )
    return assets


def _discover_openneuro_glmfitlins_assets(roots: list[Path]) -> list[dict[str, Any]]:
    if not roots:
        return []

    assets: list[dict[str, Any]] = []
    for root in roots:
        for path in sorted(root.rglob("*_statmap.nii*")):
            if not path.is_file():
                continue

            match = _OPENNEURO_STATMAP_FILENAME_RE.match(path.name)
            if match is None:
                continue

            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            parts = list(relative.parts)
            relative_root = root
            if parts and parts[0] == "stat_maps":
                parts = parts[1:]
                relative_root = root / "stat_maps"
            if len(parts) < 4:
                continue

            dataset_dir = parts[0]
            task_dir = parts[1]
            node_dir = parts[2]
            parent_subject = ""
            if len(parts) > 4 and parts[3].startswith("sub-"):
                parent_subject = parts[3]

            dataset_match = _OPENNEURO_DATASET_RE.search(dataset_dir)
            dataset_id = dataset_match.group(1) if dataset_match else dataset_dir
            task = task_dir.removeprefix("task-")
            node = node_dir.removeprefix("node-")
            subject_id = str(match.group("subject") or parent_subject or "").strip()
            contrast = str(match.group("contrast") or "").strip()
            statistic = str(match.group("stat") or "").strip()
            if not (dataset_id and task and node and contrast and statistic):
                continue

            task_root = relative_root / dataset_dir / task_dir
            dataset_description = _load_openneuro_dataset_description(
                str(task_root / "dataset_description.json")
            )
            pipeline_description = dataset_description.get("PipelineDescription") or {}
            parameters = pipeline_description.get("Parameters") or {}
            raw_space = str(parameters.get("space") or "").strip()
            space = raw_space or "MNI152NLin2009cAsym"

            asset_parts = [
                "openneuro",
                "glmfitlins",
                _slugify(dataset_id),
                "task",
                _slugify(task),
                "node",
                _slugify(node),
            ]
            if subject_id:
                asset_parts.extend(["subject", _slugify(subject_id)])
            asset_parts.extend(
                ["contrast", _slugify(contrast), "stat", _slugify(statistic)]
            )
            basename = _path_basename_without_suffix(path)

            aliases = [
                basename,
                f"{dataset_id}_{task}_{contrast}_{statistic}",
                f"{dataset_id}_{contrast}_{statistic}",
                f"{task}_{contrast}_{statistic}",
                f"{contrast}_{statistic}",
            ]
            if subject_id:
                aliases.append(f"{subject_id}_{contrast}_{statistic}")
            if statistic.lower() == "z":
                aliases.extend(
                    [
                        contrast,
                        f"{dataset_id}_{contrast}",
                        f"{task}_{contrast}",
                    ]
                )
                if subject_id:
                    aliases.append(f"{subject_id}_{contrast}")

            assets.append(
                {
                    "id": ".".join(part for part in asset_parts if part),
                    "kind": "reference_map",
                    "family": "openneuro_glmfitlins_stat_map",
                    "bundle_id": "",
                    "canonical_runtime_name": (
                        f"{dataset_id}_{task}_{contrast}_{statistic}"
                    ),
                    "title": "",
                    "aliases": _merge_unique(aliases),
                    "spaces": _openneuro_space_aliases(space),
                    "modalities": ["fmri"],
                    "tags": _merge_unique(
                        [
                            "reference_map",
                            "openneuro",
                            "glmfitlins",
                            "statmap",
                            dataset_id,
                            task,
                            node,
                            statistic,
                        ]
                    ),
                    "summary": (
                        f"Local OpenNeuro GLMFitLins stat map for {dataset_id} "
                        f"task '{task}' contrast '{contrast}' ({statistic})."
                    ),
                    "description": "",
                    "source_repo": "",
                    "source_release": str(
                        pipeline_description.get("Version") or ""
                    ).strip(),
                    "source_project": "openneuro_glmfitlins",
                    "source_paper": "",
                    "version": str(
                        dataset_description.get("BIDSVersion") or ""
                    ).strip(),
                    "license": str(dataset_description.get("License") or "").strip(),
                    "local_paths": [str(path.resolve())],
                    "urls": _coerce_list(
                        dataset_description.get("SourceDatasetsURLs") or []
                    ),
                    "formats": [_path_format(path)],
                    "hemispheres": [],
                    "resolution": "",
                    "density": "",
                    "metadata": {
                        "atlas_family_id": "reference_maps_annotations",
                        "variant_key": f"{dataset_id}_{task}_{contrast}_{statistic}",
                        "space_kind": "volume",
                        "space": space,
                        "space_inferred": not bool(raw_space),
                        "source_dataset": "openneuro_glmfitlins",
                        "contrast": contrast,
                        "description_key": contrast,
                        "dataset_id": dataset_id,
                        "task": task,
                        "node": node,
                        "level": (
                            "subject"
                            if _normalize_token(node) == "subjectlevel"
                            else ""
                        ),
                        "subject_id": subject_id,
                        "statistic": statistic,
                    },
                }
            )

    assets.sort(
        key=lambda asset: (
            str((asset.get("metadata") or {}).get("dataset_id") or ""),
            str((asset.get("metadata") or {}).get("task") or ""),
            str((asset.get("metadata") or {}).get("node") or ""),
            str((asset.get("metadata") or {}).get("subject_id") or ""),
            str((asset.get("metadata") or {}).get("description_key") or ""),
            _OPENNEURO_STAT_PREFERENCE.get(
                str((asset.get("metadata") or {}).get("statistic") or "").lower(),
                99,
            ),
            str(asset.get("id") or ""),
        )
    )
    return assets


@lru_cache(maxsize=1)
def _discover_reference_map_assets() -> list[dict[str, Any]]:
    roots = [root for root in reference_map_cache_roots() if root.exists()]
    if not roots:
        return []

    assets: list[dict[str, Any]] = []
    assets.extend(_discover_neuromaps_annotation_assets(roots))
    assets.extend(_discover_neurosynth_statmap_assets(roots))
    assets.extend(_discover_neurosynth_bundle_assets(roots))
    assets.extend(_discover_openneuro_glmfitlins_assets(roots))
    return assets


def _merge_dynamic_assets(
    static_assets: list[dict[str, Any]],
    dynamic_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged_assets = list(static_assets)
    used_dynamic_ids: set[str] = set()

    def _dynamic_match(asset: dict[str, Any]) -> dict[str, Any] | None:
        if asset.get("kind") != "atlas":
            return None
        names = [asset.get("canonical_runtime_name") or ""]
        names.extend(asset.get("aliases") or [])
        targets = {_normalize_token(name) for name in names if str(name).strip()}
        if not targets:
            return None
        for candidate in dynamic_assets:
            if candidate.get("kind") != "atlas":
                continue
            candidate_names = [candidate.get("canonical_runtime_name") or ""]
            candidate_names.extend(candidate.get("aliases") or [])
            for name in candidate_names:
                if _normalize_token(name) in targets:
                    return candidate
        return None

    for idx, asset in enumerate(merged_assets):
        candidate = _dynamic_match(asset)
        if candidate is None:
            continue
        merged_assets[idx] = _merge_asset_records(asset, candidate)
        used_dynamic_ids.add(str(candidate.get("id") or ""))

    for candidate in dynamic_assets:
        candidate_id = str(candidate.get("id") or "")
        if candidate_id and candidate_id in used_dynamic_ids:
            continue
        merged_assets.append(candidate)

    return merged_assets


@lru_cache(maxsize=1)
def load_reference_assets() -> list[dict[str, Any]]:
    static_assets = _load_static_yaml_assets()
    atlas_assets = _discover_local_atlas_assets()
    reference_map_assets = _discover_reference_map_assets()
    merged = _merge_dynamic_assets(static_assets, atlas_assets)
    merged.extend(reference_map_assets)

    deduped: dict[str, dict[str, Any]] = {}
    for asset in merged:
        asset_id = str(asset.get("id") or "").strip()
        if not asset_id:
            continue
        if asset_id in deduped:
            deduped[asset_id] = _merge_asset_records(deduped[asset_id], asset)
        else:
            deduped[asset_id] = dict(asset)
    return list(deduped.values())


@lru_cache(maxsize=1)
def load_reference_asset_index() -> dict[str, dict[str, Any]]:
    return {asset["id"]: asset for asset in load_reference_assets()}


@lru_cache(maxsize=1)
def load_reference_asset_alias_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for asset in load_reference_assets():
        names = [asset.get("id") or ""]
        names.extend(asset.get("aliases") or [])
        for raw_name in names:
            name = str(raw_name or "").strip()
            if not name:
                continue
            index.setdefault(_normalize_token(name), asset)
    return index


def _canonical_asset_id(asset_id: str) -> str:
    key = str(asset_id or "").strip()
    if not key:
        return ""
    normalized = _normalize_token(key)
    for legacy_id, canonical_id in _LEGACY_REFERENCE_ASSET_IDS.items():
        if _normalize_token(legacy_id) == normalized:
            return canonical_id
    return key


def get_reference_asset(asset_id: str) -> dict[str, Any] | None:
    key = _canonical_asset_id(asset_id)
    if not key:
        return None
    asset = load_reference_asset_index().get(key)
    if asset is not None:
        return asset
    return load_reference_asset_alias_index().get(_normalize_token(key))


def _asset_matches_space(asset: dict[str, Any], space: str | None) -> bool:
    if not space:
        return True
    requested = _normalize_token(space)
    if not requested:
        return True
    spaces = asset.get("spaces") or []
    if any(_normalize_token(candidate) == requested for candidate in spaces):
        return True
    metadata = asset.get("metadata") or {}
    return _normalize_token(metadata.get("space")) == requested


def _asset_matches_resolution(asset: dict[str, Any], resolution: str | None) -> bool:
    if not resolution:
        return True
    requested = _normalize_token(resolution)
    if not requested:
        return True
    candidates = [
        asset.get("resolution") or "",
        asset.get("density") or "",
        (asset.get("metadata") or {}).get("resolution") or "",
        (asset.get("metadata") or {}).get("density") or "",
    ]
    return any(_normalize_token(candidate) == requested for candidate in candidates)


def find_reference_asset(
    query: str,
    *,
    kind: str | None = None,
    space: str | None = None,
    resolution: str | None = None,
) -> dict[str, Any] | None:
    needle = str(query or "").strip()
    if not needle:
        return None
    if "." in needle:
        direct = get_reference_asset(needle)
        if direct is not None:
            asset_kind = str(direct.get("kind") or "").strip().lower()
            if (
                (not kind or asset_kind == str(kind or "").strip().lower())
                and _asset_matches_space(direct, space)
                and _asset_matches_resolution(direct, resolution)
            ):
                return direct
    needle_norm = _normalize_token(needle)
    target_kind = str(kind or "").strip().lower()

    best_score = -1
    best_asset: dict[str, Any] | None = None

    for asset in load_reference_assets():
        asset_kind = str(asset.get("kind") or "").strip().lower()
        if target_kind and asset_kind != target_kind:
            continue
        if not _asset_matches_space(asset, space):
            continue
        if not _asset_matches_resolution(asset, resolution):
            continue

        names = [
            asset.get("id") or "",
            asset.get("canonical_runtime_name") or "",
            asset.get("title") or "",
            asset.get("summary") or "",
            asset.get("description") or "",
        ]
        names.extend(asset.get("aliases") or [])
        names.extend(asset.get("tags") or [])

        score = -1
        for name in names:
            candidate = str(name or "").strip()
            if not candidate:
                continue
            candidate_norm = _normalize_token(candidate)
            if not candidate_norm:
                continue
            if candidate_norm == needle_norm:
                score = max(score, 100)
            elif needle_norm in candidate_norm:
                score = max(score, 60)
            elif candidate_norm in needle_norm:
                score = max(score, 45)

        if score < 0:
            continue
        if asset.get("local_paths"):
            score += 1
        if score > best_score:
            best_score = score
            best_asset = asset

    return best_asset


def resolve_reference_map_asset(
    query: str,
    *,
    space: str | None = None,
    resolution: str | None = None,
) -> dict[str, Any]:
    asset = find_reference_asset(
        query,
        kind="reference_map",
        space=space,
        resolution=resolution,
    )
    if asset is None:
        raise FileNotFoundError(
            f"Reference map '{query}' was not found in the local reference asset registry."
        )

    local_paths = [
        Path(path) for path in asset.get("local_paths") or [] if Path(path).exists()
    ]
    if not local_paths:
        raise FileNotFoundError(
            f"Reference map '{query}' matched asset '{asset['id']}' but no local files exist."
        )

    resolved = dict(asset)
    resolved["local_paths"] = [str(path) for path in local_paths]
    return resolved


__all__ = [
    "clear_reference_asset_registry_cache",
    "find_reference_asset",
    "get_reference_asset",
    "load_reference_asset_index",
    "load_reference_assets",
    "resolve_reference_map_asset",
]
