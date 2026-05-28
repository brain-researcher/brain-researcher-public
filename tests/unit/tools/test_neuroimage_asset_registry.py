from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
import yaml

import brain_researcher.services.tools.neuroimage_asset_registry as registry_module
from brain_researcher.core.ingestion import neuromaps_paths
from brain_researcher.services.neurokg.spatial import neuromaps_assets
from brain_researcher.services.tools.neuroimage_asset_registry import (
    atlas_cache_roots,
    clear_neuroimage_asset_registry_cache,
    load_template_assets,
    load_transform_assets,
    resolve_space_assets,
    resolve_transform_asset,
)


def _write_registry(
    tmp_path: Path,
    *,
    atlas_root: Path | None = None,
    template_root: Path | None = None,
    transform_root: Path | None = None,
) -> Path:
    families = []
    if atlas_root is not None:
        families.append(
            {
                "family_id": "atlases_parcellations",
                "entries": [
                    {
                        "asset_name": "local_nilearn_atlas_cache",
                        "current_state": "already_usable",
                        "evidence_paths": [str(atlas_root)],
                    }
                ],
            }
        )
    if template_root is not None or transform_root is not None:
        entries = []
        if template_root is not None:
            entries.extend(
                [
                    {
                        "asset_name": "local_volumetric_templates",
                        "current_state": "already_usable",
                        "evidence_paths": [str(template_root)],
                    },
                    {
                        "asset_name": "local_surface_templates",
                        "current_state": "already_usable",
                        "evidence_paths": [str(template_root)],
                    },
                ]
            )
        if transform_root is not None:
            entries.append(
                {
                    "asset_name": "regfusion_transform_files",
                    "current_state": "present_not_standardized",
                    "evidence_paths": [str(transform_root)],
                }
            )
        families.append(
            {
                "family_id": "templates_spaces_transforms",
                "entries": entries,
            }
        )

    registry_path = tmp_path / "neuroimage_assets_backlog.yaml"
    registry_path.write_text(
        yaml.safe_dump({"version": "test", "families": families}),
        encoding="utf-8",
    )
    return registry_path


def test_atlas_cache_roots_prepend_shared_atlas_home(monkeypatch, tmp_path):
    shared_root = tmp_path / "shared_atlases"
    shared_root.mkdir()
    legacy_root = tmp_path / "legacy_nilearn"
    legacy_root.mkdir()
    registry_path = _write_registry(tmp_path, atlas_root=legacy_root)

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    monkeypatch.setattr(
        registry_module,
        "default_atlas_output_root",
        lambda: shared_root,
    )
    clear_neuroimage_asset_registry_cache()

    roots = atlas_cache_roots()
    assert legacy_root in roots
    assert shared_root in roots
    clear_neuroimage_asset_registry_cache()


def test_preferred_neuromaps_root_prefers_shared_home(monkeypatch, tmp_path):
    shared_root = tmp_path / "atlas_home"
    shared_neuromaps = shared_root / "neuromaps"
    shared_neuromaps.mkdir(parents=True)
    legacy_root = tmp_path / "legacy_neuromaps"
    legacy_root.mkdir()

    monkeypatch.setattr(
        neuromaps_paths,
        "get_default_atlas_output_root",
        lambda: shared_root,
    )
    monkeypatch.setattr(
        neuromaps_paths,
        "LEGACY_NEUROMAPS_DIR",
        legacy_root,
    )

    assert neuromaps_assets.preferred_neuromaps_root() == shared_neuromaps


def test_preferred_yeo_fallback_root_uses_legacy_when_shared_missing(
    monkeypatch, tmp_path
):
    shared_root = tmp_path / "atlas_home"
    legacy_root = tmp_path / "legacy_nilearn"
    legacy_root.mkdir()

    monkeypatch.setattr(
        neuromaps_paths,
        "get_default_atlas_output_root",
        lambda: shared_root,
    )
    monkeypatch.setattr(
        neuromaps_paths,
        "LEGACY_NILEARN_DIR",
        legacy_root,
    )

    assert neuromaps_assets.preferred_yeo_fallback_root() == legacy_root.resolve()


def test_resolve_neuromaps_assets_prefers_shared_template_and_flat_yeo_label(
    monkeypatch, tmp_path
):
    shared_root = tmp_path / "atlas_home"
    shared_neuromaps = shared_root / "neuromaps"
    shared_yeo = shared_root / "yeo_2011"
    shared_neuromaps.mkdir(parents=True)
    shared_yeo.mkdir(parents=True)

    template_path = (
        shared_neuromaps
        / "atlases"
        / "MNI152"
        / "tpl-MNI152NLin2009cAsym_res-2mm_T1w.nii.gz"
    )
    template_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(
        nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.float32), np.eye(4)),
        template_path,
    )

    label_path = (
        shared_yeo
        / "Yeo2011_17Networks_MNI152_FreeSurferConformed1mm_LiberalMask.nii.gz"
    )
    nib.save(
        nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.int16), np.eye(4)),
        label_path,
    )

    legacy_neuromaps = tmp_path / "legacy_neuromaps"
    legacy_neuromaps.mkdir()
    legacy_nilearn = tmp_path / "legacy_nilearn"
    legacy_nilearn.mkdir()

    monkeypatch.setattr(
        neuromaps_paths,
        "get_default_atlas_output_root",
        lambda: shared_root,
    )
    monkeypatch.setattr(
        neuromaps_paths,
        "LEGACY_NEUROMAPS_DIR",
        legacy_neuromaps,
    )
    monkeypatch.setattr(
        neuromaps_paths,
        "LEGACY_NILEARN_DIR",
        legacy_nilearn,
    )
    monkeypatch.setattr(
        neuromaps_assets,
        "existing_search_roots",
        lambda _data_dir, atlas_root: [atlas_root.resolve()],
    )

    def _unexpected_fetch(_: Path):
        raise AssertionError("resolve_neuromaps_assets should not fetch nilearn assets")

    monkeypatch.setattr(neuromaps_assets, "_fetch_nilearn_assets", _unexpected_fetch)

    assets = neuromaps_assets.resolve_neuromaps_assets()
    assert assets.template_img == template_path.resolve()
    assert assets.label_img == label_path.resolve()


def test_load_template_and_transform_assets_from_registry(monkeypatch, tmp_path):
    template_root = tmp_path / "templates" / "MNI152"
    template_root.mkdir(parents=True, exist_ok=True)
    template_path = template_root / "tpl-MNI152NLin2009cAsym_res-2mm_T1w.nii.gz"
    mask_path = template_root / "tpl-MNI152NLin2009cAsym_res-2mm_desc-brain_mask.nii.gz"
    nib.save(
        nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.float32), np.eye(4)),
        template_path,
    )
    nib.save(
        nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.float32), np.eye(4)),
        mask_path,
    )

    transform_root = tmp_path / "regfusion"
    transform_root.mkdir(parents=True, exist_ok=True)
    left_transform = (
        transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-L_regfusion.txt"
    )
    right_transform = (
        transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-R_regfusion.txt"
    )
    left_transform.write_text("0 0 0\n", encoding="utf-8")
    right_transform.write_text("0 0 0\n", encoding="utf-8")

    registry_path = _write_registry(
        tmp_path,
        template_root=template_root.parent,
        transform_root=transform_root,
    )
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    monkeypatch.setattr(
        registry_module,
        "default_atlas_output_root",
        lambda: tmp_path / "unused_shared_atlases",
    )
    clear_neuroimage_asset_registry_cache()

    template_assets = load_template_assets()
    assert any(
        asset["id"] == "template.mni152nlin2009casym.2mm"
        and template_path.as_posix() in asset["local_paths"]
        for asset in template_assets
    )

    transform_assets = load_transform_assets()
    assert any(
        asset["id"] == "warp.regfusion.mni152nlin2009casym.fslr.32k"
        and left_transform.as_posix() in asset["local_paths"]
        and right_transform.as_posix() in asset["local_paths"]
        for asset in transform_assets
    )

    resolved_transform = resolve_transform_asset("MNI152", "fsLR", "32k")
    assert resolved_transform["id"] == "warp.regfusion.mni152nlin2009casym.fslr.32k"
    assert left_transform.as_posix() in resolved_transform["local_paths"]


def test_load_template_and_transform_assets_from_prod_neuromaps_shared_home(
    monkeypatch, tmp_path
):
    shared_root = tmp_path / "atlases"
    neuromaps_root = shared_root / "neuromaps" / "atlases"

    template_root = neuromaps_root / "MNI152"
    template_root.mkdir(parents=True, exist_ok=True)
    template_path = template_root / "tpl-MNI152NLin2009cAsym_res-2mm_T1w.nii.gz"
    mask_path = template_root / "tpl-MNI152NLin2009cAsym_res-2mm_desc-brain_mask.nii.gz"
    nib.save(
        nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.float32), np.eye(4)),
        template_path,
    )
    nib.save(
        nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.float32), np.eye(4)),
        mask_path,
    )

    regfusion_root = neuromaps_root / "regfusion"
    regfusion_root.mkdir(parents=True, exist_ok=True)
    left_transform = (
        regfusion_root / "tpl-MNI152_space-fsLR_den-32k_hemi-L_regfusion.txt"
    )
    right_transform = (
        regfusion_root / "tpl-MNI152_space-fsLR_den-32k_hemi-R_regfusion.txt"
    )
    left_transform.write_text("0 0 0\n", encoding="utf-8")
    right_transform.write_text("0 0 0\n", encoding="utf-8")

    registry_path = _write_registry(
        tmp_path,
        template_root=tmp_path / "missing_templates",
        transform_root=tmp_path / "missing_regfusion",
    )
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    monkeypatch.setattr(
        registry_module,
        "default_atlas_output_root",
        lambda: shared_root,
    )
    clear_neuroimage_asset_registry_cache()

    template_assets = load_template_assets()
    assert any(
        asset["id"] == "template.mni152nlin2009casym.2mm"
        and template_path.as_posix() in asset["local_paths"]
        for asset in template_assets
    )

    resolved_space = resolve_space_assets("MNI152NLin2009cAsym", "2mm")
    assert resolved_space["template_volume"] == str(template_path.resolve())
    assert resolved_space["brain_mask"] == str(mask_path.resolve())

    transform_assets = load_transform_assets()
    assert any(
        asset["id"] == "warp.regfusion.mni152nlin2009casym.fslr.32k"
        and left_transform.as_posix() in asset["local_paths"]
        and right_transform.as_posix() in asset["local_paths"]
        for asset in transform_assets
    )

    resolved_transform = resolve_transform_asset("MNI152", "fsLR", "32k")
    assert resolved_transform["local_paths"] == [
        left_transform.as_posix(),
        right_transform.as_posix(),
    ]
    assert right_transform.as_posix() in resolved_transform["local_paths"]
