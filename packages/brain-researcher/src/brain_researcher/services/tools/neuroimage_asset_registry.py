"""Registry-backed helpers for reusable neuroimage assets."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.services.tools.atlas_utils import default_atlas_output_root

_REGISTRY_ENV = "BR_NEUROIMAGE_ASSET_REGISTRY"
_SPACE_ALIASES: dict[str, tuple[str, str, str | None]] = {
    "mni": ("MNI152NLin2009cAsym", "volume", "2mm"),
    "mni152": ("MNI152NLin2009cAsym", "volume", "2mm"),
    "mni152nlin2009casym": ("MNI152NLin2009cAsym", "volume", "2mm"),
    "mni1522009c": ("MNI152NLin2009cAsym", "volume", "2mm"),
    "mni1521mm": ("MNI152NLin2009cAsym", "volume", "1mm"),
    "mni152nlin6asym": ("MNI152NLin6Asym", "volume", "2mm"),
    "mni1522006": ("MNI152NLin6Asym", "volume", "2mm"),
    "fsaverage": ("fsaverage", "surface", "10k"),
    "fsaverage3": ("fsaverage", "surface", "3k"),
    "fsaverage5": ("fsaverage", "surface", "10k"),
    "fsaverage6": ("fsaverage", "surface", "41k"),
    "fslr": ("fsLR", "surface", "32k"),
    "fslr4k": ("fsLR", "surface", "4k"),
    "fslr8k": ("fsLR", "surface", "8k"),
    "fslr32k": ("fsLR", "surface", "32k"),
    "fslr164k": ("fsLR", "surface", "164k"),
    "civet": ("civet", "surface", "164k"),
    "civet164k": ("civet", "surface", "164k"),
    "t1w": ("T1w", "native", None),
}
_SURFACE_FILE_PREFERENCES = (
    "midthickness.surf.gii",
    "pial.surf.gii",
    "white.surf.gii",
    "inflated.surf.gii",
)
_REGFUSION_FILENAME_RE = re.compile(
    r"^tpl-(?P<source>[^_]+)_space-(?P<target>[^_]+)_"
    r"den-(?P<density>[^_]+)_hemi-(?P<hemi>[LR])_regfusion\.txt$"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def clear_neuroimage_asset_registry_cache() -> None:
    _load_registry_cached.cache_clear()
    load_template_assets.cache_clear()
    load_transform_assets.cache_clear()


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _registry_path() -> Path:
    explicit = os.getenv(_REGISTRY_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return repo_root() / "configs" / "neurokg" / "neuroimage_assets_backlog.yaml"


@lru_cache(maxsize=4)
def _load_registry_cached(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid neuroimage asset registry root: {path}")
    return payload


def load_neuroimage_asset_registry() -> dict[str, Any]:
    return _load_registry_cached(str(_registry_path()))


def _family_entries(family_id: str) -> list[dict[str, Any]]:
    payload = load_neuroimage_asset_registry()
    for family in payload.get("families", []):
        if family.get("family_id") == family_id:
            entries = family.get("entries") or []
            return [entry for entry in entries if isinstance(entry, dict)]
    return []


def get_registry_entry(family_id: str, asset_name: str) -> dict[str, Any] | None:
    for entry in _family_entries(family_id):
        if entry.get("asset_name") == asset_name:
            return entry
    return None


def _entry_roots(entry: dict[str, Any] | None) -> list[Path]:
    if not isinstance(entry, dict):
        return []
    roots: list[Path] = []
    for rel_path in entry.get("evidence_paths") or []:
        candidate = Path(str(rel_path))
        if not candidate.is_absolute():
            candidate = repo_root() / candidate
        existing = _existing_dir(candidate)
        if existing is not None:
            roots.append(existing)
    return _unique_existing_roots(roots)


def _existing_dir(path: Path | None) -> Path | None:
    if path is None:
        return None
    expanded = path.expanduser()
    try:
        resolved = expanded.resolve()
    except Exception:
        resolved = expanded
    try:
        if resolved.exists() and resolved.is_dir():
            return resolved
    except OSError:
        return None
    return None


def _unique_existing_roots(paths: Iterable[Path]) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        existing = _existing_dir(path)
        if existing is None:
            continue
        key = str(existing)
        if key in seen:
            continue
        seen.add(key)
        roots.append(existing)
    return roots


def _shared_atlas_home() -> Path | None:
    return _existing_dir(default_atlas_output_root())


def _shared_neuromaps_atlas_roots() -> list[Path]:
    shared_root = _shared_atlas_home()
    if shared_root is None:
        return []
    return _unique_existing_roots([shared_root / "neuromaps" / "atlases"])


def _shared_reference_roots() -> list[Path]:
    shared_root = _shared_atlas_home()
    if shared_root is None:
        return []

    data_root = shared_root.parent
    return _unique_existing_roots(
        [
            shared_root / "neuromaps" / "annotations",
            data_root / "annotations",
            data_root / "annotations" / "neuromaps",
            data_root / "neurosynth_maps",
            data_root / "neurosynth_nimare",
            data_root / "openneuro_glmfitlins",
            data_root / "openneuro_glmfitlins" / "stat_maps",
        ]
    )


def _template_cache_roots(registry_entry_name: str) -> list[Path]:
    entry = get_registry_entry("templates_spaces_transforms", registry_entry_name)
    roots: list[Path] = [*_entry_roots(entry), *_shared_neuromaps_atlas_roots()]
    mount_root = _templateflow_mount_root()
    if mount_root is not None:
        roots.append(mount_root)
    return _unique_existing_roots(roots)


def atlas_cache_roots() -> list[Path]:
    entry = get_registry_entry("atlases_parcellations", "local_nilearn_atlas_cache")
    roots: list[Path] = [*_entry_roots(entry)]
    shared_root = _shared_atlas_home()
    if shared_root is not None:
        roots.append(shared_root)
    mount_root = _templateflow_mount_root()
    if mount_root is not None:
        roots.append(mount_root)
    return _unique_existing_roots(roots)


def reference_map_cache_roots() -> list[Path]:
    roots: list[Path] = []
    for asset_name in (
        "local_neuromaps_annotation_cache",
        "local_neurosynth_and_nimare_assets",
        "local_openneuro_glmfitlins_stat_map_corpus",
    ):
        entry = get_registry_entry("reference_maps_annotations", asset_name)
        for root in _entry_roots(entry):
            roots.append(root)
    roots.extend(_shared_reference_roots())
    return _unique_existing_roots(roots)


def transform_cache_roots() -> list[Path]:
    entry = get_registry_entry(
        "templates_spaces_transforms",
        "regfusion_transform_files",
    )
    return _unique_existing_roots(
        [*_entry_roots(entry), *_shared_neuromaps_atlas_roots()]
    )


def _templateflow_mount_root() -> Path | None:
    mounts_path = repo_root() / "configs" / "datasets" / "local_mounts.yaml"
    if not mounts_path.exists():
        return None
    payload = yaml.safe_load(mounts_path.read_text(encoding="utf-8")) or {}
    resources = (payload.get("oak_mount") or {}).get("resources") or {}
    raw = str(resources.get("templateflow") or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    return root if root.exists() else None


def _find_direct_or_recursive(base: Path, filename: str) -> Path | None:
    direct = base / filename
    if direct.exists():
        return direct
    for candidate in base.rglob(filename):
        if candidate.exists():
            return candidate
    return None


def _scan_volume_resolutions(roots: list[Path], canonical_space: str) -> list[str]:
    pattern = re.compile(
        rf"tpl-{re.escape(canonical_space)}_res-([^_]+)_T1w\.nii(?:\.gz)?$"
    )
    values: set[str] = set()
    for root in roots:
        for base in (root, root / "MNI152"):
            if not base.exists():
                continue
            for path in base.rglob(f"tpl-{canonical_space}_res-*_T1w.nii*"):
                match = pattern.match(path.name)
                if match:
                    values.add(match.group(1))
    return sorted(values)


def _scan_surface_densities(roots: list[Path], canonical_space: str) -> list[str]:
    pattern = re.compile(rf"tpl-{re.escape(canonical_space)}_den-([^_]+)_hemi-[LR]_.+$")
    values: set[str] = set()
    for root in roots:
        for base in (root, root / canonical_space):
            if not base.exists():
                continue
            for path in base.rglob(f"tpl-{canonical_space}_den-*_hemi-*"):
                match = pattern.match(path.name)
                if match:
                    values.add(match.group(1))
    return sorted(values)


def _canonical_space_from_token(space_name: str) -> str:
    key = _normalize_token(space_name)
    alias = _SPACE_ALIASES.get(key)
    if alias is not None:
        return alias[0]
    return str(space_name or "").strip()


def _known_canonical_spaces(kind: str) -> list[str]:
    spaces: list[str] = []
    seen: set[str] = set()
    for canonical_space, space_kind, _default in _SPACE_ALIASES.values():
        if space_kind != kind:
            continue
        if canonical_space in seen:
            continue
        spaces.append(canonical_space)
        seen.add(canonical_space)
    return spaces


def _dedupe_strings(values: list[str | None]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        items.append(text)
        seen.add(text)
    return items


def _template_asset_record(
    *,
    canonical_space: str,
    space_kind: str,
    scale_value: str,
    local_paths: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    scale_kind = "resolution" if space_kind == "volume" else "density"
    asset_id = (
        f"template.{_normalize_token(canonical_space)}.{_normalize_token(scale_value)}"
    )
    return {
        "id": asset_id,
        "kind": "template",
        "family_id": "templates_spaces_transforms",
        "family": canonical_space,
        "canonical_runtime_name": canonical_space,
        "title": f"{canonical_space} {scale_value} template",
        "aliases": [canonical_space, f"{canonical_space}_{scale_value}"],
        "spaces": [canonical_space],
        "summary": f"Registry-backed {space_kind} template for {canonical_space} at {scale_value}.",
        "local_paths": local_paths,
        "resolution": scale_value if scale_kind == "resolution" else "",
        "density": scale_value if scale_kind == "density" else "",
        "metadata": metadata,
    }


def _transform_asset_record(
    *,
    source_space: str,
    target_space: str,
    density: str,
    local_paths: list[str],
    hemispheres: list[str],
) -> dict[str, Any]:
    asset_id = ".".join(
        [
            "warp",
            "regfusion",
            _normalize_token(source_space),
            _normalize_token(target_space),
            _normalize_token(density),
        ]
    )
    return {
        "id": asset_id,
        "kind": "warp",
        "family_id": "templates_spaces_transforms",
        "family": "regfusion",
        "canonical_runtime_name": f"regfusion_{target_space}_{density}",
        "title": f"Regfusion {source_space} to {target_space} {density}",
        "aliases": [
            f"regfusion_{target_space}_{density}",
            f"{source_space}_to_{target_space}_{density}",
        ],
        "spaces": [source_space, target_space],
        "summary": (
            f"Local regfusion transform text files from {source_space} to "
            f"{target_space} at {density}."
        ),
        "local_paths": local_paths,
        "resolution": "",
        "density": density,
        "metadata": {
            "source_space": source_space,
            "target_space": target_space,
            "space_kind": "transform",
            "density": density,
            "hemispheres": hemispheres,
        },
    }


@lru_cache(maxsize=1)
def load_template_assets() -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []

    volume_roots = _template_cache_roots("local_volumetric_templates")

    for canonical_space in _known_canonical_spaces("volume"):
        for resolution in _scan_volume_resolutions(volume_roots, canonical_space):
            try:
                resolved = resolve_space_assets(canonical_space, resolution)
            except FileNotFoundError:
                continue

            extra_outputs = resolved.get("extra_outputs") or {}
            local_paths = _dedupe_strings(
                [
                    resolved.get("template_volume"),
                    resolved.get("brain_mask"),
                    *extra_outputs.values(),
                ]
            )
            assets.append(
                _template_asset_record(
                    canonical_space=canonical_space,
                    space_kind="volume",
                    scale_value=resolution,
                    local_paths=local_paths,
                    metadata={
                        "space_kind": "volume",
                        "resolution": resolution,
                        "registry_entry": resolved.get("registry_entry") or "",
                        "template_source": resolved.get("template_source") or "",
                        "brain_mask": resolved.get("brain_mask") or "",
                    },
                )
            )

    surface_roots = _template_cache_roots("local_surface_templates")

    for canonical_space in _known_canonical_spaces("surface"):
        for density in _scan_surface_densities(surface_roots, canonical_space):
            try:
                resolved = resolve_space_assets(canonical_space, density)
            except FileNotFoundError:
                continue

            extra_outputs = resolved.get("extra_outputs") or {}
            local_paths = _dedupe_strings(
                [
                    resolved.get("template_volume"),
                    resolved.get("brain_mask"),
                    *extra_outputs.values(),
                ]
            )
            assets.append(
                _template_asset_record(
                    canonical_space=canonical_space,
                    space_kind="surface",
                    scale_value=density,
                    local_paths=local_paths,
                    metadata={
                        "space_kind": "surface",
                        "density": density,
                        "registry_entry": resolved.get("registry_entry") or "",
                        "template_source": resolved.get("template_source") or "",
                        "surface_left": extra_outputs.get("surface_left") or "",
                        "surface_right": extra_outputs.get("surface_right") or "",
                    },
                )
            )

    assets.sort(
        key=lambda item: (
            item["kind"],
            item["canonical_runtime_name"],
            item["resolution"] or item["density"],
        )
    )
    return assets


@lru_cache(maxsize=1)
def load_transform_assets() -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}

    for root in transform_cache_roots():
        if not root.exists():
            continue
        for path in sorted(root.rglob("tpl-*_regfusion.txt")):
            match = _REGFUSION_FILENAME_RE.match(path.name)
            if match is None:
                continue

            source_space = _canonical_space_from_token(match.group("source"))
            target_space = _canonical_space_from_token(match.group("target"))
            density = match.group("density")
            hemi = match.group("hemi")
            key = (source_space, target_space, density)
            record = grouped.setdefault(
                key,
                {
                    "source_space": source_space,
                    "target_space": target_space,
                    "density": density,
                    "local_paths": [],
                    "hemispheres": [],
                },
            )
            record["local_paths"] = _dedupe_strings(
                [*record["local_paths"], str(path.resolve())]
            )
            record["hemispheres"] = _dedupe_strings([*record["hemispheres"], hemi])

    assets = [
        _transform_asset_record(
            source_space=record["source_space"],
            target_space=record["target_space"],
            density=record["density"],
            local_paths=record["local_paths"],
            hemispheres=record["hemispheres"],
        )
        for record in grouped.values()
    ]
    assets.sort(key=lambda item: (item["family"], item["canonical_runtime_name"]))
    return assets


def resolve_transform_asset(
    source_space: str,
    target_space: str,
    density: str | None = None,
) -> dict[str, Any]:
    source_canonical = _canonical_space_from_token(source_space)
    target_canonical = _canonical_space_from_token(target_space)
    requested_density = str(density or "").strip()

    if not requested_density:
        try:
            requested_density = normalize_space_request(target_space)[
                "resolved_resolution"
            ]
        except Exception:
            requested_density = ""

    for asset in load_transform_assets():
        metadata = asset.get("metadata") or {}
        if str(metadata.get("source_space") or "").strip() != source_canonical:
            continue
        if str(metadata.get("target_space") or "").strip() != target_canonical:
            continue
        if (
            requested_density
            and str(metadata.get("density") or "").strip() != requested_density
        ):
            continue
        local_paths = [
            str(Path(path).resolve())
            for path in (asset.get("local_paths") or [])
            if Path(path).exists()
        ]
        if not local_paths:
            raise FileNotFoundError(
                f"Transform asset '{asset['id']}' matched but no local files exist."
            )
        resolved = dict(asset)
        resolved["local_paths"] = local_paths
        return resolved

    available = sorted(
        {
            str((asset.get("metadata") or {}).get("density") or "").strip()
            for asset in load_transform_assets()
            if str((asset.get("metadata") or {}).get("source_space") or "").strip()
            == source_canonical
            and str((asset.get("metadata") or {}).get("target_space") or "").strip()
            == target_canonical
        }
    )
    raise FileNotFoundError(
        f"Transform asset not found for {source_canonical} -> {target_canonical} "
        f"at density '{requested_density or 'default'}'; "
        f"available densities: {available or ['none']}"
    )


def normalize_space_request(
    space_name: str,
    resolution: str | None = None,
) -> dict[str, Any]:
    key = _normalize_token(space_name)
    if key not in _SPACE_ALIASES:
        raise ValueError(f"Unsupported space_name: {space_name}")

    canonical_space, kind, default_value = _SPACE_ALIASES[key]
    raw_resolution = str(resolution or default_value or "").strip()

    if kind == "native":
        raise ValueError(
            "resolve_space only handles standard shared spaces; native space 'T1w' "
            "should be resolved from subject-specific derivatives instead."
        )

    if kind == "volume":
        match = re.search(r"(\d+)", raw_resolution or "")
        if not match:
            raise ValueError(f"Unsupported resolution for {space_name}: {resolution}")
        resolved = f"{int(match.group(1))}mm"
        return {
            "canonical_space": canonical_space,
            "space_kind": kind,
            "resolved_resolution": resolved,
            "requested_space": space_name,
            "requested_resolution": resolution,
        }

    density_key = _normalize_token(raw_resolution or "")
    density_map = {
        "3k": "3k",
        "4k": "4k",
        "8k": "8k",
        "10k": "10k",
        "32k": "32k",
        "41k": "41k",
        "164k": "164k",
        "fsaverage3": "3k",
        "fsaverage5": "10k",
        "fsaverage6": "41k",
        "fslr4k": "4k",
        "fslr8k": "8k",
        "fslr32k": "32k",
        "fslr164k": "164k",
        "civet164k": "164k",
    }
    if density_key not in density_map:
        raise ValueError(f"Unsupported surface density for {space_name}: {resolution}")
    resolved = density_map[density_key]
    return {
        "canonical_space": canonical_space,
        "space_kind": kind,
        "resolved_resolution": resolved,
        "requested_space": space_name,
        "requested_resolution": resolution,
    }


def resolve_space_assets(
    space_name: str,
    resolution: str | None = None,
) -> dict[str, Any]:
    resolved = normalize_space_request(space_name, resolution)
    canonical_space = resolved["canonical_space"]
    space_kind = resolved["space_kind"]
    resolved_resolution = resolved["resolved_resolution"]

    registry_entry_name = (
        "local_volumetric_templates"
        if space_kind == "volume"
        else "local_surface_templates"
    )
    entry = get_registry_entry("templates_spaces_transforms", registry_entry_name)
    if entry is None:
        raise FileNotFoundError(
            f"Registry entry missing for templates_spaces_transforms/{registry_entry_name}"
        )
    if entry.get("current_state") == "missing_and_should_acquire":
        raise FileNotFoundError(
            f"Registry marks {registry_entry_name} as missing_and_should_acquire"
        )

    roots = _template_cache_roots(registry_entry_name)
    if not roots:
        raise FileNotFoundError(f"No template roots available for {canonical_space}")

    if space_kind == "volume":
        filename_template = (
            f"tpl-{canonical_space}_res-{resolved_resolution}_T1w.nii.gz"
        )
        filename_mask = (
            f"tpl-{canonical_space}_res-{resolved_resolution}_desc-brain_mask.nii.gz"
        )
        template_path: Path | None = None
        mask_path: Path | None = None
        for root in roots:
            for base in (root, root / "MNI152"):
                if not base.exists():
                    continue
                template_path = template_path or _find_direct_or_recursive(
                    base, filename_template
                )
                mask_path = mask_path or _find_direct_or_recursive(base, filename_mask)
                if template_path and mask_path:
                    break
            if template_path and mask_path:
                break

        if template_path is None or mask_path is None:
            available = _scan_volume_resolutions(roots, canonical_space)
            raise FileNotFoundError(
                f"Template files not found for {canonical_space} at {resolved_resolution}; "
                f"available resolutions: {available or ['none']}"
            )

        base = template_path.parent
        extras = {
            "template_t1w": str(template_path),
            "template_t2w": str(
                base / f"tpl-{canonical_space}_res-{resolved_resolution}_T2w.nii.gz"
            )
            if (
                base / f"tpl-{canonical_space}_res-{resolved_resolution}_T2w.nii.gz"
            ).exists()
            else None,
            "template_pd": str(
                base / f"tpl-{canonical_space}_res-{resolved_resolution}_PD.nii.gz"
            )
            if (
                base / f"tpl-{canonical_space}_res-{resolved_resolution}_PD.nii.gz"
            ).exists()
            else None,
            "gm_probseg": str(
                base
                / f"tpl-{canonical_space}_res-{resolved_resolution}_label-gm_probseg.nii.gz"
            )
            if (
                base
                / f"tpl-{canonical_space}_res-{resolved_resolution}_label-gm_probseg.nii.gz"
            ).exists()
            else None,
            "wm_probseg": str(
                base
                / f"tpl-{canonical_space}_res-{resolved_resolution}_label-wm_probseg.nii.gz"
            )
            if (
                base
                / f"tpl-{canonical_space}_res-{resolved_resolution}_label-wm_probseg.nii.gz"
            ).exists()
            else None,
            "csf_probseg": str(
                base
                / f"tpl-{canonical_space}_res-{resolved_resolution}_label-csf_probseg.nii.gz"
            )
            if (
                base
                / f"tpl-{canonical_space}_res-{resolved_resolution}_label-csf_probseg.nii.gz"
            ).exists()
            else None,
        }
        return {
            **resolved,
            "registry_path": str(_registry_path()),
            "registry_entry": registry_entry_name,
            "template_source": "registry_local_cache",
            "template_volume": str(template_path),
            "brain_mask": str(mask_path),
            "extra_outputs": extras,
        }

    # Surface spaces
    left_surface: Path | None = None
    right_surface: Path | None = None
    left_mask: Path | None = None
    right_mask: Path | None = None
    left_sphere: Path | None = None
    right_sphere: Path | None = None

    for root in roots:
        for base in (root, root / canonical_space):
            if not base.exists():
                continue
            for suffix in _SURFACE_FILE_PREFERENCES:
                left_surface = left_surface or _find_direct_or_recursive(
                    base,
                    f"tpl-{canonical_space}_den-{resolved_resolution}_hemi-L_{suffix}",
                )
                right_surface = right_surface or _find_direct_or_recursive(
                    base,
                    f"tpl-{canonical_space}_den-{resolved_resolution}_hemi-R_{suffix}",
                )
                if left_surface and right_surface:
                    break

            left_mask = left_mask or _find_direct_or_recursive(
                base,
                f"tpl-{canonical_space}_den-{resolved_resolution}_hemi-L_desc-nomedialwall_dparc.label.gii",
            )
            right_mask = right_mask or _find_direct_or_recursive(
                base,
                f"tpl-{canonical_space}_den-{resolved_resolution}_hemi-R_desc-nomedialwall_dparc.label.gii",
            )
            left_sphere = left_sphere or _find_direct_or_recursive(
                base,
                f"tpl-{canonical_space}_den-{resolved_resolution}_hemi-L_sphere.surf.gii",
            )
            right_sphere = right_sphere or _find_direct_or_recursive(
                base,
                f"tpl-{canonical_space}_den-{resolved_resolution}_hemi-R_sphere.surf.gii",
            )

            if left_surface and right_surface:
                break
        if left_surface and right_surface:
            break

    if left_surface is None or right_surface is None:
        available = _scan_surface_densities(roots, canonical_space)
        raise FileNotFoundError(
            f"Surface template files not found for {canonical_space} at {resolved_resolution}; "
            f"available densities: {available or ['none']}"
        )

    return {
        **resolved,
        "registry_path": str(_registry_path()),
        "registry_entry": registry_entry_name,
        "template_source": "registry_local_cache",
        "template_volume": str(left_surface),
        "brain_mask": str(left_mask or left_surface),
        "extra_outputs": {
            "surface_left": str(left_surface),
            "surface_right": str(right_surface),
            "brain_mask_left": str(left_mask) if left_mask else None,
            "brain_mask_right": str(right_mask) if right_mask else None,
            "sphere_left": str(left_sphere) if left_sphere else None,
            "sphere_right": str(right_sphere) if right_sphere else None,
        },
    }


__all__ = [
    "atlas_cache_roots",
    "clear_neuroimage_asset_registry_cache",
    "get_registry_entry",
    "load_template_assets",
    "load_transform_assets",
    "load_neuroimage_asset_registry",
    "normalize_space_request",
    "reference_map_cache_roots",
    "repo_root",
    "resolve_transform_asset",
    "resolve_space_assets",
    "transform_cache_roots",
]
