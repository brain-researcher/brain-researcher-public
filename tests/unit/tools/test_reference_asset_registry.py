from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import yaml

import brain_researcher.services.tools.neuroimage_asset_registry as registry_module
from brain_researcher.services.tools.neuroimage_asset_registry import (
    clear_neuroimage_asset_registry_cache,
)
from brain_researcher.services.tools.reference_asset_registry import (
    clear_reference_asset_registry_cache,
    find_reference_asset,
    get_reference_asset,
    load_reference_asset_index,
    resolve_reference_map_asset,
)


def _write_registry(
    tmp_path: Path,
    *,
    atlas_root: Path | None = None,
    reference_root: Path | None = None,
    neurosynth_root: Path | None = None,
    openneuro_root: Path | None = None,
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
    if (
        reference_root is not None
        or neurosynth_root is not None
        or openneuro_root is not None
    ):
        entries = []
        if reference_root is not None:
            entries.append(
                {
                    "asset_name": "local_neuromaps_annotation_cache",
                    "current_state": "already_usable",
                    "evidence_paths": [str(reference_root)],
                }
            )
        if neurosynth_root is not None:
            entries.append(
                {
                    "asset_name": "local_neurosynth_and_nimare_assets",
                    "current_state": "already_usable",
                    "evidence_paths": [str(neurosynth_root)],
                }
            )
        if openneuro_root is not None:
            entries.append(
                {
                    "asset_name": "local_openneuro_glmfitlins_stat_map_corpus",
                    "current_state": "already_usable",
                    "evidence_paths": [str(openneuro_root)],
                }
            )
        families.append(
            {
                "family_id": "reference_maps_annotations",
                "entries": entries,
            }
        )
    registry_path = tmp_path / "neuroimage_assets_backlog.yaml"
    registry_path.write_text(
        yaml.safe_dump({"version": "test", "families": families}),
        encoding="utf-8",
    )
    return registry_path


def _write_nifti(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = nib.Nifti1Image(np.zeros((2, 2, 2), dtype="float32"), affine=np.eye(4))
    nib.save(img, path)


def _write_bytes(path: Path, payload: bytes = b"stub\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_reference_asset_registry_loads_static_workflow_atlas_assets():
    clear_reference_asset_registry_cache()
    index = load_reference_asset_index()
    assert "atlas.schaefer2018.400.17networks.bundle" in index
    assert "atlas.yeo2011.17networks.bundle" in index
    assert "nilearn.atlas.schaefer2018.400.17networks" in index
    assert "nilearn.atlas.yeo2011.17networks.volume" in index


def test_reference_asset_registry_alias_lookup_preserves_legacy_cbig_ids():
    clear_reference_asset_registry_cache()
    asset = find_reference_asset("cbig.atlas.yeo2011.17networks", kind="atlas")
    assert asset is not None
    assert asset["id"] == "atlas.yeo2011.17networks.bundle"
    assert asset["canonical_runtime_name"] == "yeo17"


def test_reference_asset_registry_get_by_id():
    clear_reference_asset_registry_cache()
    asset = get_reference_asset("warp.mni_fsaverage.registration_fusion.ants")
    assert asset is not None
    assert asset["kind"] == "warp"
    assert asset["id"] == "warp.mni_fsaverage.registration_fusion.ants"


def test_reference_asset_registry_discovers_materialized_bundle_paths(
    monkeypatch, tmp_path: Path
):
    reference_root = tmp_path / "reference_assets"

    deepresbat_source = (
        reference_root / "repos" / "cbig" / "Standalone_An2024_DeepResBat"
    )
    deepresbat_source.mkdir(parents=True, exist_ok=True)
    deepresbat_bundle = (
        reference_root
        / "materialized"
        / "method_bundles"
        / "method.deepresbat.reference"
    )
    deepresbat_bundle.mkdir(parents=True, exist_ok=True)
    (deepresbat_bundle / "source").symlink_to(
        deepresbat_source, target_is_directory=True
    )

    tang_source = (
        reference_root
        / "repos"
        / "cbig"
        / "CBIG"
        / "stable_projects"
        / "disorder_subtypes"
        / "Tang2020_ASDFactors"
    )
    tang_source.mkdir(parents=True, exist_ok=True)
    tang_bundle = (
        reference_root
        / "materialized"
        / "method_bundles"
        / "method.asd_factor_subtyping.reference"
    )
    tang_bundle.mkdir(parents=True, exist_ok=True)
    (tang_bundle / "source").symlink_to(tang_source, target_is_directory=True)

    monkeypatch.setenv("BR_REFERENCE_ASSET_ROOTS", str(reference_root))
    clear_reference_asset_registry_cache()

    deepresbat = get_reference_asset("method.deepresbat.reference")
    assert deepresbat is not None
    assert str(deepresbat_bundle) in deepresbat["local_paths"]
    assert str(deepresbat_source) in deepresbat["local_paths"]

    tang = get_reference_asset("method.asd_factor_subtyping.reference")
    assert tang is not None
    assert str(tang_bundle) in tang["local_paths"]
    assert str(tang_source) in tang["local_paths"]


def test_reference_asset_registry_discovers_dynamic_atlas_and_reference_map_assets(
    monkeypatch, tmp_path: Path
):
    atlas_root = tmp_path / "atlases"
    msdl_dir = atlas_root / "msdl_atlas" / "MSDL_rois"
    msdl_dir.mkdir(parents=True, exist_ok=True)
    _write_nifti(msdl_dir / "msdl_rois.nii")
    (msdl_dir / "msdl_rois_labels.csv").write_text(
        "x,y,z,name,net name\n-1,0,0,L Aud,Aud\n1,0,0,R Aud,Aud\n",
        encoding="utf-8",
    )

    reference_root = tmp_path / "annotations"
    _write_nifti(
        reference_root
        / "neurosynth"
        / "cogpc1"
        / "MNI152"
        / "source-neurosynth_desc-cogpc1_space-MNI152_res-2mm_feature.nii.gz"
    )
    registry_path = _write_registry(
        tmp_path,
        atlas_root=atlas_root,
        reference_root=reference_root,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_reference_asset_registry_cache()

    atlas_asset = find_reference_asset("msdl", kind="atlas")
    assert atlas_asset is not None
    assert atlas_asset["id"] == "nilearn.atlas.msdl"
    assert atlas_asset["family"] == "msdl_atlas"
    assert atlas_asset["metadata"]["n_regions"] == 2
    assert atlas_asset["local_paths"][0].endswith("msdl_rois.nii")

    reference_map = resolve_reference_map_asset(
        "cogpc1",
        space="MNI152",
        resolution="2mm",
    )
    assert reference_map["id"] == "neuromaps.annotation.neurosynth.cogpc1.mni152.2mm"
    assert reference_map["metadata"]["space_kind"] == "volume"
    assert reference_map["local_paths"][0].endswith("_res-2mm_feature.nii.gz")


def test_reference_asset_registry_discovers_templateflow_atlas_assets(
    monkeypatch, tmp_path: Path
):
    templateflow_root = tmp_path / "templateflow"
    tf_dir = templateflow_root / "tpl-MNI152NLin2009cAsym"
    tf_dir.mkdir(parents=True, exist_ok=True)
    _write_nifti(
        tf_dir
        / "tpl-MNI152NLin2009cAsym_res-02_atlas-Schaefer2018_desc-100Parcels7Networks_dseg.nii.gz"
    )
    _write_nifti(
        tf_dir / "tpl-MNI152NLin2009cAsym_res-02_atlas-DiFuMo_desc-512dimensions_probseg.nii.gz"
    )

    registry_path = _write_registry(tmp_path, atlas_root=templateflow_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    monkeypatch.setattr(
        registry_module,
        "_templateflow_mount_root",
        lambda: templateflow_root,
    )
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    schaefer = find_reference_asset("Schaefer2018_100", kind="atlas")
    assert schaefer is not None
    assert schaefer["id"] == "nilearn.atlas.schaefer2018.100.7networks"
    assert schaefer["local_paths"][0].endswith(
        "tpl-MNI152NLin2009cAsym_res-02_atlas-Schaefer2018_desc-100Parcels7Networks_dseg.nii.gz"
    )
    assert schaefer["metadata"]["space"] == "MNI152NLin2009cAsym"
    assert schaefer["metadata"]["resolution"] == "2mm"
    assert schaefer["metadata"]["templateflow_resolution"] == "02"
    assert schaefer["spaces"] == ["MNI152NLin2009cAsym", "MNI152"]

    difumo = find_reference_asset("difumo512", kind="atlas")
    assert difumo is not None
    assert difumo["id"] == "nilearn.atlas.difumo.512"
    assert difumo["local_paths"][0].endswith(
        "tpl-MNI152NLin2009cAsym_res-02_atlas-DiFuMo_desc-512dimensions_probseg.nii.gz"
    )
    assert difumo["metadata"]["space"] == "MNI152NLin2009cAsym"
    assert difumo["metadata"]["resolution"] == "2mm"
    assert difumo["metadata"]["templateflow_resolution"] == "02"
    assert difumo["spaces"] == ["MNI152NLin2009cAsym", "MNI152"]

    schaefer_specific = find_reference_asset(
        "Schaefer2018_100",
        kind="atlas",
        space="MNI152NLin2009cAsym",
        resolution="2mm",
    )
    assert schaefer_specific is not None
    assert schaefer_specific["id"] == "nilearn.atlas.schaefer2018.100.7networks"

    schaefer_generic = find_reference_asset(
        "Schaefer2018_100",
        kind="atlas",
        space="MNI152",
        resolution="2mm",
    )
    assert schaefer_generic is not None
    assert schaefer_generic["id"] == "nilearn.atlas.schaefer2018.100.7networks"


def test_reference_asset_registry_discovers_prod_neuromaps_annotation_root(
    monkeypatch, tmp_path: Path
):
    shared_root = tmp_path / "atlases"
    reference_path = (
        shared_root
        / "neuromaps"
        / "annotations"
        / "neurosynth"
        / "cogpc1"
        / "MNI152"
        / "source-neurosynth_desc-cogpc1_space-MNI152_res-2mm_feature.nii.gz"
    )
    _write_nifti(reference_path)

    registry_path = _write_registry(
        tmp_path,
        reference_root=tmp_path / "missing_annotations",
    )
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    monkeypatch.setattr(
        registry_module,
        "default_atlas_output_root",
        lambda: shared_root,
    )
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    reference_map = resolve_reference_map_asset(
        "cogpc1",
        space="MNI152",
        resolution="2mm",
    )
    assert reference_map["id"] == "neuromaps.annotation.neurosynth.cogpc1.mni152.2mm"
    assert reference_map["local_paths"] == [str(reference_path.resolve())]


def test_reference_asset_registry_discovers_neurosynth_bundle_assets(
    monkeypatch, tmp_path: Path
):
    neurosynth_root = tmp_path / "neurosynth_nimare"
    _write_bytes(neurosynth_root / "neurosynth_dataset_v7.pkl.gz")
    _write_bytes(neurosynth_root / "neurosynth_dataset_v7.json.gz")
    _write_bytes(
        neurosynth_root / "neurosynth" / "data-neurosynth_version-7_coordinates.tsv.gz"
    )
    _write_bytes(
        neurosynth_root / "neurosynth" / "data-neurosynth_version-7_metadata.tsv.gz"
    )
    _write_bytes(
        neurosynth_root
        / "neurosynth"
        / "data-neurosynth_version-7_vocab-LDA50_source-abstract_type-weight_features.npz"
    )
    _write_bytes(
        neurosynth_root
        / "neurosynth"
        / "data-neurosynth_version-7_vocab-LDA50_metadata.json"
    )
    _write_bytes(
        neurosynth_root
        / "neurosynth"
        / "data-neurosynth_version-7_vocab-LDA50_keys.tsv"
    )
    _write_bytes(
        neurosynth_root
        / "neurosynth"
        / "data-neurosynth_version-7_vocab-LDA50_vocabulary.txt"
    )
    registry_path = _write_registry(tmp_path, neurosynth_root=neurosynth_root)

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_reference_asset_registry_cache()

    dataset_asset = resolve_reference_map_asset("nimare_dataset")
    assert dataset_asset["id"] == "neurosynth.nimare.dataset.v7"
    assert dataset_asset["metadata"]["space_kind"] == "literature_model"
    assert any(
        path.endswith("neurosynth_dataset_v7.pkl.gz")
        for path in dataset_asset["local_paths"]
    )

    lda_asset = resolve_reference_map_asset("lda50")
    assert lda_asset["id"] == "neurosynth.nimare.lda50.v7"
    assert lda_asset["metadata"]["description_key"] == "lda50"
    assert any(
        path.endswith(
            "data-neurosynth_version-7_vocab-LDA50_source-abstract_type-weight_features.npz"
        )
        for path in lda_asset["local_paths"]
    )


def test_reference_asset_registry_discovers_neurosynth_stat_maps(
    monkeypatch, tmp_path: Path
):
    neurosynth_root = tmp_path / "neurosynth_assets"
    flat_map = (
        neurosynth_root
        / "neurosynth"
        / "statmaps"
        / "neurosynth_term_terms_abstract_tfidf__memory.nii.gz"
    )
    bundle_map = (
        neurosynth_root
        / "neurosynth_maps"
        / "terms_abstract_tfidf__attention"
        / "neurosynth_terms_abstract_tfidf__attention_z.nii.gz"
    )
    bundle_roi = bundle_map.parent / "roi_summary.tsv"
    _write_nifti(flat_map)
    _write_nifti(bundle_map)
    bundle_roi.write_text("term\tscore\nattention\t1.0\n", encoding="utf-8")
    registry_path = _write_registry(tmp_path, neurosynth_root=neurosynth_root)

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_reference_asset_registry_cache()

    flat_asset = resolve_reference_map_asset("memory", space="MNI152")
    assert flat_asset["id"] == "neurosynth.term.terms.abstract.tfidf.memory"
    assert flat_asset["metadata"]["map_variant"] == "term_flat"
    assert flat_asset["local_paths"] == [str(flat_map.resolve())]

    bundle_asset = resolve_reference_map_asset("attention", space="MNI152")
    assert bundle_asset["id"] == "neurosynth.map.terms.abstract.tfidf.attention.z"
    assert bundle_asset["metadata"]["map_variant"] == "bundle_map"
    assert any(path.endswith("roi_summary.tsv") for path in bundle_asset["local_paths"])


def test_reference_asset_registry_discovers_openneuro_glmfitlins_stat_maps(
    monkeypatch, tmp_path: Path
):
    openneuro_root = tmp_path / "openneuro_glmfitlins" / "stat_maps"
    stat_path = (
        openneuro_root
        / "ds000114"
        / "task-linebisection"
        / "node-subjectLevel"
        / "sub-01"
        / "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz"
    )
    _write_nifti(stat_path)
    (
        openneuro_root / "ds000114" / "task-linebisection" / "dataset_description.json"
    ).write_text(
        json.dumps(
            {
                "BIDSVersion": "1.1.0",
                "License": "CC0",
                "PipelineDescription": {
                    "Version": "0.11.0",
                    "Parameters": {"space": "MNI152NLin2009cAsym"},
                },
                "SourceDatasetsURLs": [
                    "https://doi.org/10.18112/openneuro.ds000114.v1.0.2"
                ],
            }
        ),
        encoding="utf-8",
    )
    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_reference_asset_registry_cache()

    stat_asset = resolve_reference_map_asset("taskvbaseline", space="MNI152")
    assert stat_asset["id"].endswith(".contrast.taskvbaseline.stat.z")
    assert stat_asset["metadata"]["dataset_id"] == "ds000114"
    assert stat_asset["metadata"]["task"] == "linebisection"
    assert stat_asset["metadata"]["node"] == "subjectLevel"
    assert stat_asset["metadata"]["subject_id"] == "sub-01"
    assert stat_asset["metadata"]["statistic"] == "z"
    assert stat_asset["local_paths"] == [str(stat_path.resolve())]


def test_reference_asset_registry_discovers_openneuro_stat_maps_from_prod_data_root(
    monkeypatch, tmp_path: Path
):
    data_root = tmp_path / "data"
    shared_root = data_root / "atlases"
    shared_root.mkdir(parents=True, exist_ok=True)
    stat_path = (
        data_root
        / "openneuro_glmfitlins"
        / "stat_maps"
        / "ds000114"
        / "task-linebisection"
        / "node-subjectLevel"
        / "sub-01"
        / "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz"
    )
    _write_nifti(stat_path)
    (
        data_root
        / "openneuro_glmfitlins"
        / "stat_maps"
        / "ds000114"
        / "task-linebisection"
        / "dataset_description.json"
    ).write_text(
        json.dumps(
            {
                "BIDSVersion": "1.1.0",
                "License": "CC0",
                "PipelineDescription": {
                    "Version": "0.11.0",
                    "Parameters": {"space": "MNI152NLin2009cAsym"},
                },
                "SourceDatasetsURLs": [
                    "https://doi.org/10.18112/openneuro.ds000114.v1.0.2"
                ],
            }
        ),
        encoding="utf-8",
    )

    registry_path = _write_registry(
        tmp_path,
        reference_root=tmp_path / "missing_annotations",
        openneuro_root=tmp_path / "missing_openneuro",
    )
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    monkeypatch.setattr(
        registry_module,
        "default_atlas_output_root",
        lambda: shared_root,
    )
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    stat_asset = resolve_reference_map_asset("taskvbaseline", space="MNI152")
    assert stat_asset["id"].endswith(".contrast.taskvbaseline.stat.z")
    assert stat_asset["metadata"]["dataset_id"] == "ds000114"
    assert stat_asset["local_paths"] == [str(stat_path.resolve())]


def test_reference_asset_registry_defaults_bare_schaefer_queries_to_7networks(
    monkeypatch, tmp_path: Path
):
    atlas_root = tmp_path / "atlases" / "schaefer_2018"
    _write_nifti(
        atlas_root / "Schaefer2018_200Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    _write_nifti(
        atlas_root / "Schaefer2018_200Parcels_17Networks_order_FSLMNI152_2mm.nii.gz"
    )
    registry_path = _write_registry(tmp_path, atlas_root=tmp_path / "atlases")

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_reference_asset_registry_cache()

    bare_asset = find_reference_asset("Schaefer2018_200", kind="atlas")
    assert bare_asset is not None
    assert bare_asset["id"] == "nilearn.atlas.schaefer2018.200.7networks"
    assert bare_asset["canonical_runtime_name"] == "Schaefer2018_200_7Networks"

    parcel_asset = find_reference_asset("Schaefer2018_200Parcels", kind="atlas")
    assert parcel_asset is not None
    assert parcel_asset["id"] == "nilearn.atlas.schaefer2018.200.7networks"

    explicit_asset = find_reference_asset("Schaefer2018_200_17Networks", kind="atlas")
    assert explicit_asset is not None
    assert explicit_asset["id"] == "nilearn.atlas.schaefer2018.200.17networks"
