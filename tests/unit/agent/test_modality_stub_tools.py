"""Smoke tests for newly added modality-prefixed tool stubs."""

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
import yaml
from nibabel.freesurfer import io as fsio

import brain_researcher.services.tools.kg_multihop_qa_tool as kg_multihop_module
from brain_researcher.services.neurokg import query_service
from brain_researcher.services.tools.coreg_apply_xfm_tool import CoregApplyXfmTool
from brain_researcher.services.tools.coreg_register_tool import CoregRegisterTool
from brain_researcher.services.tools.dmri_fit_model_tool import DMRIFitModelTool
from brain_researcher.services.tools.dmri_parcellate_connectome_tool import (
    DMRIParcellateConnectomeTool,
)
from brain_researcher.services.tools.dmri_resolve_dwi_triplet_tool import (
    DMRIResolveDwiTripletTool,
)
from brain_researcher.services.tools.ieeg_connectivity_tool import (
    IEEGConnectivityTool,
)
from brain_researcher.services.tools.ieeg_electrode_localize_tool import (
    IEEGElectrodeLocalizeTool,
)
from brain_researcher.services.tools.ieeg_epoch_features_tool import (
    IEEGEpochFeaturesTool,
)
from brain_researcher.services.tools.ieeg_preprocess_tool import (
    IEEGPreprocessTool,
)
from brain_researcher.services.tools.kg_ingest_tool import KGIngestTool
from brain_researcher.services.tools.kg_multihop_qa_tool import KGMultihopQATool
from brain_researcher.services.tools.kg_shacl_validate_tool import (
    KGSHACLValidateTool,
)
from brain_researcher.services.tools.label_transfer_tool import LabelTransferTool
from brain_researcher.services.tools.list_neuroimage_assets_tool import (
    ListNeuroimageAssetsTool,
)
from brain_researcher.services.tools.meta_align_tool import MetaAlignTool
from brain_researcher.services.tools.meta_brainmap_tool import MetaBrainMapTool
from brain_researcher.services.tools.meta_combine_tool import MetaCombineTool
from brain_researcher.services.tools.neuroimage_asset_registry import (
    clear_neuroimage_asset_registry_cache,
)
from brain_researcher.services.tools.parcellation_fetch_tool import (
    ParcellationFetchTool,
)
from brain_researcher.services.tools.pet_coreg_tool import PETCoregTool
from brain_researcher.services.tools.pet_parcellate_tool import PETParcellateTool
from brain_researcher.services.tools.pet_suvr_tool import PETSUVRTool
from brain_researcher.services.tools.reference_asset_registry import (
    clear_reference_asset_registry_cache,
)
from brain_researcher.services.tools.resolve_bids_tool import ResolveBIDSTool
from brain_researcher.services.tools.resolve_neuroimage_asset_tool import (
    ResolveNeuroimageAssetTool,
)
from brain_researcher.services.tools.resolve_reference_map_tool import (
    ResolveReferenceMapTool,
)
from brain_researcher.services.tools.resolve_space_tool import ResolveSpaceTool
from brain_researcher.services.tools.resolve_transform_tool import (
    ResolveTransformTool,
)
from brain_researcher.services.tools.smri_parcellation_stats_tool import (
    SMRIParcellationStatsTool,
)
from brain_researcher.services.tools.smri_recon_tool import SMRIReconTool
from brain_researcher.services.tools.smri_surface_export_tool import (
    SMRISurfaceExportTool,
)
from brain_researcher.services.tools.tool_registry import ToolRegistry


def _write_registry(
    tmp_path: Path,
    *,
    template_root: Path | None = None,
    atlas_root: Path | None = None,
    reference_root: Path | None = None,
    neurosynth_root: Path | None = None,
    openneuro_root: Path | None = None,
    transform_root: Path | None = None,
) -> Path:
    families = []
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


def _write_nifti(path: Path, data: np.ndarray | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = nib.Nifti1Image(
        np.asarray(data if data is not None else np.zeros((2, 2, 2), dtype="float32")),
        affine=np.eye(4),
    )
    nib.save(img, path)


def _write_surface_annot(path: Path) -> None:
    labels = np.array([0, 1, 1, 2, 2], dtype=np.int32)
    ctab = np.array(
        [
            [25, 5, 25, 0, 0],
            [125, 25, 125, 0, 0],
            [225, 5, 5, 0, 0],
        ],
        dtype=np.int32,
    )
    names = [b"unknown", b"net1", b"net2"]
    fsio.write_annot(path, labels, ctab, names)


def _write_regfusion(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("0 0 0\n", encoding="utf-8")


def _write_bytes(path: Path, payload: bytes = b"stub\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_ieeg_electrode_localize_stub(tmp_path):
    tool = IEEGElectrodeLocalizeTool()
    result = tool._run(
        ct_image="ct.nii.gz", mri_image="mri.nii.gz", output_dir=str(tmp_path)
    )
    assert result.status == "success"
    assert "contacts_mni" in result.data["outputs"]


def test_ieeg_preprocess_stub(tmp_path):
    tool = IEEGPreprocessTool()
    result = tool._run(raw_ieeg="raw.fif", output_dir=str(tmp_path))
    assert result.status == "success"
    assert result.data["outputs"]["clean_ieeg"].endswith("clean_ieeg.fif")


def test_ieeg_epoch_features_stub(tmp_path):
    tool = IEEGEpochFeaturesTool()
    result = tool._run(
        clean_ieeg="clean.fif", events="events.tsv", output_dir=str(tmp_path)
    )
    assert result.status == "success"
    assert result.data["outputs"]["features_table"].endswith("features_table.parquet")


def test_ieeg_connectivity_stub(tmp_path):
    tool = IEEGConnectivityTool()
    result = tool._run(features_table="features.parquet", output_dir=str(tmp_path))
    assert result.status == "success"
    outputs = result.data["outputs"]
    assert outputs["connectivity_matrix"].endswith(".npy")
    assert Path(outputs["connectivity_matrix"]).exists()
    assert outputs["feature_contract"].endswith("feature_contract.json")
    assert Path(outputs["feature_contract"]).exists()


def test_dmri_resolve_dwi_triplet_stub(tmp_path):
    bids_root = tmp_path / "bids"
    bids_root.mkdir()
    tool = DMRIResolveDwiTripletTool()
    result = tool._run(subject_id="01", bids_root=str(bids_root))
    outputs = result.data["outputs"]
    assert outputs["dwi_image"].endswith("dwi.nii.gz")
    assert outputs["bvals"].endswith("dwi.bval")
    assert outputs["bvecs"].endswith("dwi.bvec")


def test_dmri_fit_model_stub(tmp_path):
    tool = DMRIFitModelTool()
    result = tool._run(
        dwi_image="dwi.nii.gz",
        bvals="dwi.bval",
        bvecs="dwi.bvec",
        output_dir=str(tmp_path),
    )
    outputs = result.data["outputs"]
    assert outputs["fa_map"].endswith("fa_map.nii.gz")
    assert outputs["model_type"] == "dti"


def test_dmri_parcellate_connectome_stub(tmp_path):
    tool = DMRIParcellateConnectomeTool()
    result = tool._run(
        tractogram="tracts.tck",
        parcellation_labels="atlas.nii.gz",
        output_dir=str(tmp_path),
    )
    outputs = result.data["outputs"]
    assert outputs["connectivity_matrix"].endswith("connectivity_matrix.csv")
    assert outputs["feature_contract"].endswith("feature_contract.json")
    assert Path(outputs["feature_contract"]).exists()


def test_coreg_register_stub(tmp_path):
    """Test coregistration registration tool stub."""
    tool = CoregRegisterTool()
    result = tool._run(
        moving_image="ct.nii.gz", fixed_image="t1.nii.gz", output_dir=str(tmp_path)
    )
    assert result.status == "success"
    assert "transform_matrix" in result.data["outputs"]
    assert "registered_image" in result.data["outputs"]


def test_coreg_apply_xfm_stub(tmp_path):
    """Test coregistration apply transform tool stub."""
    tool = CoregApplyXfmTool()
    result = tool._run(
        input_volume="atlas.nii.gz",
        transform_matrix="ct_to_mri.mat",
        reference_image="mri.nii.gz",
        output_dir=str(tmp_path),
    )
    assert result.status == "success"
    assert result.data["outputs"]["transformed_volume"].endswith(".nii.gz")


def test_parcellation_fetch_registry_backed_surface(monkeypatch, tmp_path):
    """Test parcellation fetch tool against a temporary registry-backed surface atlas."""
    atlas_root = tmp_path / "atlases"
    label_dir = atlas_root / "Yeo_JNeurophysiol11_FreeSurfer" / "fsaverage5" / "label"
    label_dir.mkdir(parents=True, exist_ok=True)
    _write_surface_annot(label_dir / "lh.Yeo2011_7Networks_N1000.annot")
    _write_surface_annot(label_dir / "rh.Yeo2011_7Networks_N1000.annot")
    registry_path = _write_registry(tmp_path, atlas_root=atlas_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    tool = ParcellationFetchTool()
    result = tool._run(
        atlas_name="yeo",
        space="fsaverage",
        output_dir=str(tmp_path / "outputs"),
    )
    assert result.status == "success"
    assert "parcellation_volume" in result.data["outputs"]
    assert "surface_parcellation_left" in result.data["outputs"]
    assert "surface_parcellation_right" in result.data["outputs"]
    assert "labels_tsv" in result.data["outputs"]
    assert result.data["summary"]["space_kind"] == "surface"
    assert result.data["summary"]["n_regions"] == 2


def test_parcellation_fetch_registry_backed_msdl_volume(monkeypatch, tmp_path):
    atlas_root = tmp_path / "atlases"
    msdl_dir = atlas_root / "msdl_atlas" / "MSDL_rois"
    msdl_dir.mkdir(parents=True, exist_ok=True)
    _write_nifti(msdl_dir / "msdl_rois.nii")
    (msdl_dir / "msdl_rois_labels.csv").write_text(
        "x,y,z,name,net name\n-1,0,0,L Aud,Aud\n1,0,0,R Aud,Aud\n",
        encoding="utf-8",
    )
    registry_path = _write_registry(tmp_path, atlas_root=atlas_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    tool = ParcellationFetchTool()
    result = tool._run(
        atlas_name="msdl",
        space="MNI152NLin2009cAsym",
        output_dir=str(tmp_path / "outputs"),
    )
    assert result.status == "success"
    assert result.data["summary"]["family"] == "msdl_atlas"
    assert result.data["summary"]["reference_asset"]["id"] == "nilearn.atlas.msdl"
    assert result.data["summary"]["n_regions"] == 2


def test_label_transfer_stub(tmp_path):
    """Test label transfer tool stub."""
    tool = LabelTransferTool()
    result = tool._run(
        source_labels="atlas.nii.gz",
        transform_matrix="xfm.mat",
        reference_image="target.nii.gz",
        output_dir=str(tmp_path),
    )
    assert result.status == "success"
    assert "transferred_labels" in result.data["outputs"]


def test_resolve_bids_stub(tmp_path):
    """Test BIDS resolution tool."""
    tool = ResolveBIDSTool()
    bids_root = tmp_path / "bids"
    bids_root.mkdir(parents=True, exist_ok=True)
    (bids_root / "dataset_description.json").write_text(
        '{"Name": "TestDataset", "BIDSVersion": "1.8.0"}'
    )
    anat_dir = bids_root / "sub-01" / "anat"
    anat_dir.mkdir(parents=True, exist_ok=True)
    img_path = anat_dir / "sub-01_T1w.nii.gz"
    img = nib.Nifti1Image(np.zeros((2, 2, 2), dtype="float32"), affine=np.eye(4))
    nib.save(img, img_path)
    result = tool._run(
        bids_root=str(bids_root), subject_id="01", datatype="anat", suffix="T1w"
    )
    assert result.status == "success"
    assert "resolved_path" in result.data["outputs"]
    assert result.data["summary"]["query_success"] is True


def test_resolve_space_registry_backed_volume(monkeypatch, tmp_path):
    """Test space resolution tool against a temporary registry-backed template cache."""
    template_root = tmp_path / "templates" / "MNI152"
    template_root.mkdir(parents=True, exist_ok=True)
    _write_nifti(template_root / "tpl-MNI152NLin2009cAsym_res-2mm_T1w.nii.gz")
    _write_nifti(
        template_root / "tpl-MNI152NLin2009cAsym_res-2mm_desc-brain_mask.nii.gz"
    )
    _write_nifti(template_root / "tpl-MNI152NLin2009cAsym_res-2mm_T2w.nii.gz")
    registry_path = _write_registry(tmp_path, template_root=template_root.parent)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    tool = ResolveSpaceTool()
    result = tool._run(space_name="MNI152NLin2009cAsym")
    assert result.status == "success"
    assert "template_volume" in result.data["outputs"]
    assert "brain_mask" in result.data["outputs"]
    assert result.data["summary"]["template_source"] == "registry_local_cache"


def test_resolve_transform_registry_backed_local_warp(monkeypatch, tmp_path):
    transform_root = tmp_path / "regfusion"
    left_path = transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-L_regfusion.txt"
    right_path = transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-R_regfusion.txt"
    _write_regfusion(left_path)
    _write_regfusion(right_path)
    registry_path = _write_registry(tmp_path, transform_root=transform_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()

    tool = ResolveTransformTool()
    result = tool._run(
        source_space="MNI152",
        target_space="fsLR",
        resolution="32k",
        output_dir=str(tmp_path / "outputs"),
    )
    assert result.status == "success"
    assert result.data["outputs"]["transform_left"].endswith("_hemi-L_regfusion.txt")
    assert result.data["outputs"]["transform_right"].endswith("_hemi-R_regfusion.txt")
    assert result.data["summary"]["asset_id"] == (
        "warp.regfusion.mni152nlin2009casym.fslr.32k"
    )
    assert result.data["summary"]["density"] == "32k"


def test_resolve_reference_map_registry_backed_volume(monkeypatch, tmp_path):
    reference_root = tmp_path / "annotations"
    _write_nifti(
        reference_root
        / "neurosynth"
        / "cogpc1"
        / "MNI152"
        / "source-neurosynth_desc-cogpc1_space-MNI152_res-2mm_feature.nii.gz"
    )
    registry_path = _write_registry(tmp_path, reference_root=reference_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    tool = ResolveReferenceMapTool()
    result = tool._run(
        map_name="cogpc1",
        space="MNI152",
        resolution="2mm",
        output_dir=str(tmp_path / "outputs"),
    )
    assert result.status == "success"
    assert result.data["outputs"]["reference_map"].endswith("_res-2mm_feature.nii.gz")
    assert result.data["summary"]["asset_id"] == (
        "neuromaps.annotation.neurosynth.cogpc1.mni152.2mm"
    )
    assert result.data["summary"]["space_kind"] == "volume"


def test_resolve_reference_map_registry_backed_neurosynth_bundle(monkeypatch, tmp_path):
    neurosynth_root = tmp_path / "neurosynth_nimare"
    _write_bytes(neurosynth_root / "neurosynth_dataset_v7.pkl.gz")
    _write_bytes(neurosynth_root / "neurosynth_dataset_v7.json.gz")
    _write_bytes(
        neurosynth_root / "neurosynth" / "data-neurosynth_version-7_coordinates.tsv.gz"
    )
    _write_bytes(
        neurosynth_root / "neurosynth" / "data-neurosynth_version-7_metadata.tsv.gz"
    )
    registry_path = _write_registry(tmp_path, neurosynth_root=neurosynth_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    tool = ResolveReferenceMapTool()
    result = tool._run(
        map_name="nimare_dataset",
        output_dir=str(tmp_path / "outputs"),
    )
    assert result.status == "success"
    assert result.data["outputs"]["reference_map"].endswith(
        "neurosynth_dataset_v7.pkl.gz"
    )
    assert result.data["summary"]["asset_id"] == "neurosynth.nimare.dataset.v7"
    assert result.data["summary"]["bundle_kind"] == "dataset_v7"


def test_resolve_reference_map_registry_backed_openneuro_stat_map(
    monkeypatch, tmp_path
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
            }
        ),
        encoding="utf-8",
    )
    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    tool = ResolveReferenceMapTool()
    result = tool._run(
        map_name="taskvbaseline",
        space="MNI152",
        output_dir=str(tmp_path / "outputs"),
    )
    assert result.status == "success"
    assert result.data["outputs"]["reference_map"].endswith(
        "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz"
    )
    assert result.data["summary"]["dataset_id"] == "ds000114"
    assert result.data["summary"]["task"] == "linebisection"
    assert result.data["summary"]["statistic"] == "z"


def test_resolve_neuroimage_asset_auto_template(monkeypatch, tmp_path):
    template_root = tmp_path / "templates" / "MNI152"
    template_root.mkdir(parents=True, exist_ok=True)
    _write_nifti(template_root / "tpl-MNI152NLin2009cAsym_res-2mm_T1w.nii.gz")
    _write_nifti(
        template_root / "tpl-MNI152NLin2009cAsym_res-2mm_desc-brain_mask.nii.gz"
    )
    registry_path = _write_registry(tmp_path, template_root=template_root.parent)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    tool = ResolveNeuroimageAssetTool()
    result = tool._run(name="MNI152")
    assert result.status == "success"
    assert "template_volume" in result.data["outputs"]
    assert result.data["summary"]["resolved_kind"] == "template"
    assert result.data["summary"]["resolver_tool"] == "resolve_space"


def test_resolve_neuroimage_asset_auto_atlas(monkeypatch, tmp_path):
    atlas_root = tmp_path / "atlases"
    msdl_dir = atlas_root / "msdl_atlas" / "MSDL_rois"
    msdl_dir.mkdir(parents=True, exist_ok=True)
    _write_nifti(msdl_dir / "msdl_rois.nii")
    (msdl_dir / "msdl_rois_labels.csv").write_text(
        "x,y,z,name,net name\n-1,0,0,L Aud,Aud\n1,0,0,R Aud,Aud\n",
        encoding="utf-8",
    )
    registry_path = _write_registry(tmp_path, atlas_root=atlas_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    tool = ResolveNeuroimageAssetTool()
    result = tool._run(
        name="msdl",
        space="MNI152",
        output_dir=str(tmp_path / "outputs"),
    )
    assert result.status == "success"
    assert "parcellation_volume" in result.data["outputs"]
    assert result.data["summary"]["resolved_kind"] == "atlas"
    assert result.data["summary"]["resolver_tool"] == "parcellation_fetch"


def test_resolve_neuroimage_asset_explicit_transform(monkeypatch, tmp_path):
    transform_root = tmp_path / "regfusion"
    _write_regfusion(
        transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-L_regfusion.txt"
    )
    _write_regfusion(
        transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-R_regfusion.txt"
    )
    registry_path = _write_registry(tmp_path, transform_root=transform_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()

    tool = ResolveNeuroimageAssetTool()
    result = tool._run(
        kind="transform",
        source_space="MNI152",
        target_space="fsLR",
        resolution="32k",
        output_dir=str(tmp_path / "outputs"),
    )
    assert result.status == "success"
    assert result.data["outputs"]["transform_left"].endswith("_hemi-L_regfusion.txt")
    assert result.data["summary"]["resolved_kind"] == "transform"
    assert result.data["summary"]["resolver_tool"] == "resolve_transform"


def test_resolve_neuroimage_asset_auto_reference_map(monkeypatch, tmp_path):
    reference_root = tmp_path / "annotations"
    _write_nifti(
        reference_root
        / "neurosynth"
        / "cogpc1"
        / "MNI152"
        / "source-neurosynth_desc-cogpc1_space-MNI152_res-2mm_feature.nii.gz"
    )
    registry_path = _write_registry(tmp_path, reference_root=reference_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    tool = ResolveNeuroimageAssetTool()
    result = tool._run(
        name="cogpc1",
        space="MNI152",
        resolution="2mm",
        output_dir=str(tmp_path / "outputs"),
    )
    assert result.status == "success"
    assert result.data["outputs"]["reference_map"].endswith("_res-2mm_feature.nii.gz")
    assert result.data["summary"]["resolved_kind"] == "reference_map"
    assert result.data["summary"]["resolver_tool"] == "resolve_reference_map"


def test_resolve_neuroimage_asset_explicit_method_bundle(monkeypatch, tmp_path):
    reference_root = tmp_path / "reference_assets"
    source_root = reference_root / "repos" / "cbig" / "Standalone_An2024_DeepResBat"
    source_root.mkdir(parents=True, exist_ok=True)
    bundle_root = (
        reference_root
        / "materialized"
        / "method_bundles"
        / "method.deepresbat.reference"
    )
    bundle_root.mkdir(parents=True, exist_ok=True)
    (bundle_root / "asset.json").write_text(
        json.dumps({"id": "method.deepresbat.reference"}), encoding="utf-8"
    )
    (bundle_root / "source").symlink_to(source_root, target_is_directory=True)

    monkeypatch.setenv("BR_REFERENCE_ASSET_ROOTS", str(reference_root))
    clear_reference_asset_registry_cache()

    tool = ResolveNeuroimageAssetTool()
    result = tool._run(name="method.deepresbat.reference", kind="method_bundle")
    assert result.status == "success"
    assert result.data["outputs"]["bundle_root"] == str(bundle_root)
    assert result.data["outputs"]["bundle_manifest"] == str(bundle_root / "asset.json")
    assert result.data["outputs"]["source_root"] == str(bundle_root / "source")
    assert result.data["summary"]["asset_id"] == "method.deepresbat.reference"
    assert result.data["summary"]["resolved_kind"] == "method_bundle"
    assert result.data["summary"]["resolver_tool"] == "reference_asset_registry"


def test_list_neuroimage_assets_registry_backed_inventory(monkeypatch, tmp_path):
    template_root = tmp_path / "templates" / "MNI152"
    template_root.mkdir(parents=True, exist_ok=True)
    _write_nifti(template_root / "tpl-MNI152NLin2009cAsym_res-2mm_T1w.nii.gz")
    _write_nifti(
        template_root / "tpl-MNI152NLin2009cAsym_res-2mm_desc-brain_mask.nii.gz"
    )

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

    transform_root = tmp_path / "regfusion"
    _write_regfusion(
        transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-L_regfusion.txt"
    )
    _write_regfusion(
        transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-R_regfusion.txt"
    )

    registry_path = _write_registry(
        tmp_path,
        template_root=template_root.parent,
        atlas_root=atlas_root,
        reference_root=reference_root,
        transform_root=transform_root,
    )
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    monkeypatch.setenv(
        "BR_ATLAS_OUTPUT_ROOT",
        str(tmp_path / "unused_shared_atlases"),
    )
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    tool = ListNeuroimageAssetsTool()
    result = tool._run(limit=500)
    assert result.status == "success"

    assets = result.data["outputs"]["assets"]
    kinds = {asset["kind"] for asset in assets}
    assert {"template", "atlas", "reference_map", "warp"}.issubset(kinds)
    assert all("canonical_id" in asset for asset in assets)
    assert all("source" in asset for asset in assets)
    assert all("manifest_fields" in asset for asset in assets)
    assert any(asset["id"] == "template.mni152nlin2009casym.2mm" for asset in assets)
    assert any(asset["id"] == "nilearn.atlas.msdl" for asset in assets)
    assert any(
        asset["id"] == "neuromaps.annotation.neurosynth.cogpc1.mni152.2mm"
        for asset in assets
    )
    assert any(
        asset["id"] == "warp.regfusion.mni152nlin2009casym.fslr.32k" for asset in assets
    )
    assert result.data["summary"]["total_matches"] >= 4


def test_list_neuroimage_assets_all_view_includes_inventory_entries(
    monkeypatch, tmp_path
):
    template_root = tmp_path / "templates" / "MNI152"
    template_root.mkdir(parents=True, exist_ok=True)
    _write_nifti(template_root / "tpl-MNI152NLin2009cAsym_res-2mm_T1w.nii.gz")
    _write_nifti(
        template_root / "tpl-MNI152NLin2009cAsym_res-2mm_desc-brain_mask.nii.gz"
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
        template_root=template_root.parent,
        reference_root=reference_root,
    )
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    monkeypatch.setenv(
        "BR_ATLAS_OUTPUT_ROOT",
        str(tmp_path / "unused_shared_atlases"),
    )
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    tool = ListNeuroimageAssetsTool()
    result = tool._run(
        view="all",
        family="reference_maps_annotations",
        include_metadata=True,
        output_dir=str(tmp_path / "outputs"),
        limit=20,
    )
    assert result.status == "success"

    assets = result.data["outputs"]["assets"]
    assert any(asset["kind"] == "reference_map" for asset in assets)
    assert any(asset["kind"] == "inventory_entry" for asset in assets)
    assert Path(result.data["outputs"]["inventory_json"]).exists()
    assert result.data["summary"]["view"] == "all"
    assert result.data["summary"]["total_matches"] >= 2


def test_list_neuroimage_assets_supports_stat_map_kind_and_family(
    monkeypatch, tmp_path
):
    openneuro_root = tmp_path / "openneuro_glmfitlins" / "stat_maps"
    _write_nifti(
        openneuro_root
        / "ds000114"
        / "task-linebisection"
        / "node-subjectLevel"
        / "sub-01"
        / "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz"
    )
    (
        openneuro_root / "ds000114" / "task-linebisection" / "dataset_description.json"
    ).write_text(
        json.dumps(
            {
                "PipelineDescription": {
                    "Version": "0.11.0",
                    "Parameters": {"space": "MNI152NLin2009cAsym"},
                }
            }
        ),
        encoding="utf-8",
    )

    registry_path = _write_registry(tmp_path, openneuro_root=openneuro_root)
    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()

    tool = ListNeuroimageAssetsTool()
    result = tool._run(
        view="concrete",
        family="stat_maps",
        kind="stat_map",
        query="taskvbaseline",
        include_metadata=True,
    )

    assert result.status == "success"
    assets = result.data["outputs"]["assets"]
    assert len(assets) == 1
    assert assets[0]["kind"] == "stat_map"
    assert assets[0]["subfamily_id"] == "stat_maps"
    assert assets[0]["metadata"]["contrast"] == "taskvbaseline"
    assert assets[0]["canonical_id"]
    assert assets[0]["level"] == "subject"
    assert result.data["summary"]["kind_counts"]["stat_map"] == 1
    assert result.data["summary"]["subfamily_counts"]["stat_maps"] == 1


def test_smri_recon_stub(tmp_path):
    """Test sMRI reconstruction tool stub."""
    tool = SMRIReconTool()
    result = tool._run(
        t1w_image="sub-01_T1w.nii.gz",
        subject_id="01",
        output_dir=str(tmp_path),
    )
    outputs = result.data["outputs"]
    assert "surfaces_dir" in outputs
    assert "aseg_volume" in outputs
    assert "aparcaseg_volume" in outputs


def test_smri_parcellation_stats_stub(tmp_path):
    """Test sMRI parcellation statistics tool stub."""
    tool = SMRIParcellationStatsTool()
    result = tool._run(surfaces_dir="/tmp/fs-surf", output_dir=str(tmp_path))
    outputs = result.data["outputs"]
    assert "thickness_table" in outputs
    assert "volume_table" in outputs


def test_smri_surface_export_stub(tmp_path):
    """Test sMRI surface export tool stub."""
    tool = SMRISurfaceExportTool()
    result = tool._run(surfaces_dir="/tmp/fs-surf", output_dir=str(tmp_path))
    assert result.status == "success"
    assert result.data["outputs"]["surface_mesh"].endswith(".gii")


def test_pet_coreg_stub(tmp_path):
    """Test PET coregistration tool stub."""
    tool = PETCoregTool()
    result = tool._run(
        pet_image="sub-01_pet.nii.gz",
        t1w_image="sub-01_T1w.nii.gz",
        output_dir=str(tmp_path),
    )
    assert result.status == "success"
    assert "pet_in_t1" in result.data["outputs"]
    assert "transform_matrix" in result.data["outputs"]
    assert result.data["outputs"]["pet_in_t1"].endswith(".nii.gz")
    assert result.data["outputs"]["transform_matrix"].endswith(".mat")


def test_pet_suvr_stub(tmp_path):
    """Test PET SUVR computation tool stub."""
    tool = PETSUVRTool()
    result = tool._run(
        pet_image="pet_in_t1.nii.gz",
        reference_mask="cerebellum_mask.nii.gz",
        output_dir=str(tmp_path),
    )
    assert result.status == "success"
    assert result.data["outputs"]["suvr_map"].endswith(".nii.gz")
    assert result.data["outputs"]["qc_volume"].endswith(".nii.gz")
    assert result.data["summary"]["mean_suvr"] > 0


def test_pet_parcellate_stub(tmp_path):
    """Test PET ROI parcellation tool stub."""
    tool = PETParcellateTool()
    result = tool._run(
        suvr_map="suvr_map.nii.gz",
        parcellation_labels="Schaefer2018_200.nii.gz",
        atlas_name="Schaefer2018_200",
        output_dir=str(tmp_path),
    )
    assert result.status == "success"
    assert result.data["outputs"]["roi_suvr_table"].endswith(".csv")
    assert result.data["summary"]["n_regions"] == 200
    assert result.data["summary"]["atlas_name"] == "Schaefer2018_200"


def test_meta_brainmap_stub(tmp_path):
    tool = MetaBrainMapTool()
    result = tool._run(term="working memory", output_dir=str(tmp_path))
    outputs = result.data["outputs"]
    assert outputs["coord_table"].endswith("coordinates.csv")
    assert outputs["stat_map"].endswith("stat_map.nii.gz")


def test_meta_align_stub(tmp_path):
    tool = MetaAlignTool()
    result = tool._run(stat_map="wm_stat_map.nii.gz", output_dir=str(tmp_path))
    outputs = result.data["outputs"]
    assert outputs["aligned_map"].endswith("aligned_MNI152NLin2009cAsym.nii.gz")


def test_meta_combine_stub(tmp_path):
    tool = MetaCombineTool()
    result = tool._run(stat_map="aligned_map.nii.gz", output_dir=str(tmp_path))
    outputs = result.data["outputs"]
    assert outputs["meta_stat_map"].endswith("map.nii.gz")
    assert outputs["report_html"].endswith("report.html")


def test_kg_ingest_stub(tmp_path):
    nodes_file = str(tmp_path / "nodes.csv")
    edges_file = str(tmp_path / "edges.csv")
    tool = KGIngestTool()
    result = tool._run(nodes_file=nodes_file, edges_file=edges_file)
    outputs = result.data["outputs"]
    assert outputs["kg_nodes"]["total_count"] > 0
    assert outputs["kg_edges"]["total_count"] > 0


def test_kg_shacl_validate_stub(tmp_path):
    tool = KGSHACLValidateTool()
    result = tool._run(
        kg_nodes={"total_count": 10},
        kg_edges={"total_count": 5},
        output_dir=str(tmp_path),
    )
    outputs = result.data["outputs"]
    assert outputs["report_html"].endswith("validation_report.html")


def _patch_kg_multihop_query_service(
    monkeypatch, *, search_nodes, neighbors, multi_hop_traverse=None, node_details=None
):
    """Patch likely query-service import styles used by multihop tool code."""
    monkeypatch.setattr(query_service, "search_nodes", search_nodes)
    monkeypatch.setattr(query_service, "neighbors", neighbors)
    monkeypatch.setattr(
        query_service, "node_details", node_details or (lambda *_a, **_k: None)
    )
    if multi_hop_traverse is not None:
        monkeypatch.setattr(query_service, "multi_hop_traverse", multi_hop_traverse)
    monkeypatch.setattr(
        kg_multihop_module,
        "query_service",
        query_service,
        raising=False,
    )
    monkeypatch.setattr(
        kg_multihop_module,
        "search_nodes",
        search_nodes,
        raising=False,
    )
    monkeypatch.setattr(
        kg_multihop_module,
        "neighbors",
        neighbors,
        raising=False,
    )
    if multi_hop_traverse is not None:
        monkeypatch.setattr(
            kg_multihop_module,
            "multi_hop_traverse",
            multi_hop_traverse,
            raising=False,
        )


def _assert_kg_multihop_contract_payload(data):
    required_keys = {
        "answer",
        "seed_entities",
        "paths",
        "subgraph",
        "provenance",
        "confidence",
        "warnings",
        "summary",
    }
    assert required_keys.issubset(data.keys())
    assert isinstance(data["provenance"], list)
    assert all(isinstance(entry, dict) for entry in data["provenance"])
    assert isinstance(data["summary"], dict)
    assert data["summary"].get("completion_state") in {
        "complete",
        "partial",
        "degraded",
    }


def _assert_kg_multihop_outputs_fallback(data):
    outputs = data.get("outputs")
    if not isinstance(outputs, dict):
        return

    for key in (
        "answer",
        "seed_entities",
        "paths",
        "subgraph",
        "provenance",
        "confidence",
        "warnings",
        "summary",
    ):
        assert key in outputs
        assert outputs[key] == data[key]


def test_kg_multihop_qa_success_path_with_mocked_search_and_traversal(monkeypatch):
    question = "What connects working memory to PFC?"
    search_calls = []
    neighbor_calls = []

    def fake_search_nodes(query, **kwargs):
        search_calls.append({"query": query, **kwargs})
        return [
            query_service.KGNodeSummary(
                kg_id="cc:working_memory",
                label="working_memory",
                node_type="CognitiveConcept",
                score=0.98,
            ),
            query_service.KGNodeSummary(
                kg_id="br:pfc",
                label="prefrontal_cortex",
                node_type="BrainRegion",
                score=0.94,
            ),
        ]

    def fake_neighbors(kg_id, **kwargs):
        neighbor_calls.append({"kg_id": kg_id, **kwargs})
        if kg_id == "cc:working_memory":
            return [
                {
                    "kg_id": "pub:1",
                    "label": "WM study",
                    "node_type": "Publication",
                    "relation": "MENTIONED_IN",
                    "direction": "out",
                    "score": 1.0,
                    "properties": {"pmid": "12345"},
                }
            ]
        return [
            {
                "kg_id": "pub:1",
                "label": "WM study",
                "node_type": "Publication",
                "relation": "MENTIONED_IN",
                "direction": "out",
                "score": 1.0,
                "properties": {"pmid": "12345"},
            }
        ]

    def fake_multi_hop_traverse(*_args, **_kwargs):
        return {
            "paths": [],
            "subgraph": {"nodes": [], "edges": []},
            "provenance": [],
            "statistics": {"execution_time_ms": 0.0},
            "warnings": [],
            "mode": "breadth_first",
        }

    _patch_kg_multihop_query_service(
        monkeypatch,
        search_nodes=fake_search_nodes,
        neighbors=fake_neighbors,
        multi_hop_traverse=fake_multi_hop_traverse,
    )

    tool = KGMultihopQATool()
    result = tool._run(question=question, max_hops=2, return_subgraph=True)

    assert result.status == "success"
    assert search_calls
    assert neighbor_calls

    data = result.data or {}
    _assert_kg_multihop_contract_payload(data)
    _assert_kg_multihop_outputs_fallback(data)

    assert data["answer"]
    assert "nodes" in data["subgraph"]
    assert "edges" in data["subgraph"]
    assert data["summary"]["question"] == question
    assert data["summary"]["max_hops"] == 2
    assert data["summary"]["completion_state"] == "partial"


def test_kg_multihop_qa_seed_stage_uses_budgeted_timeouts(monkeypatch):
    node_timeout_calls = []
    search_timeout_calls = []
    search_call_count = {"value": 0}

    def fake_node_details(*_args, **kwargs):
        node_timeout_calls.append(kwargs.get("timeout_s"))
        return None

    def fake_search_nodes(*_args, **kwargs):
        search_timeout_calls.append(kwargs.get("timeout_s"))
        if search_call_count["value"] == 0:
            search_call_count["value"] += 1
            return [
                query_service.KGNodeSummary(
                    kg_id="cc:working_memory",
                    label="working_memory",
                    node_type="CognitiveConcept",
                    score=1.0,
                )
            ]
        return []

    def fake_neighbors(*_args, **_kwargs):
        return []

    def fake_multi_hop_traverse(*_args, **_kwargs):
        return {
            "paths": [],
            "subgraph": {"nodes": [], "edges": []},
            "provenance": [],
            "statistics": {"execution_time_ms": 0.0},
            "warnings": [],
            "mode": "breadth_first",
        }

    _patch_kg_multihop_query_service(
        monkeypatch,
        search_nodes=fake_search_nodes,
        neighbors=fake_neighbors,
        multi_hop_traverse=fake_multi_hop_traverse,
        node_details=fake_node_details,
    )
    monkeypatch.setenv("BR_KG_MULTIHOP_TOOL_BUDGET_S", "10")

    tool = KGMultihopQATool()
    result = tool._run(
        question="What links working memory and prefrontal cortex?",
        max_hops=2,
        return_subgraph=True,
    )

    assert result.data
    assert node_timeout_calls
    assert search_timeout_calls
    assert all(
        isinstance(timeout, float | int) and 0.0 < float(timeout) <= 3.0
        for timeout in node_timeout_calls
    )
    assert all(
        isinstance(timeout, float | int) and 0.0 < float(timeout) <= 3.0
        for timeout in search_timeout_calls
    )


def test_kg_multihop_qa_relation_questions_stop_seed_collection_early(monkeypatch):
    search_terms_seen = []

    def fake_node_details(*_args, **_kwargs):
        return None

    def fake_search_nodes(query, **_kwargs):
        search_terms_seen.append(query)
        idx = len(search_terms_seen)
        return [
            query_service.KGNodeSummary(
                kg_id=f"seed:{idx}",
                label=f"seed_{idx}",
                node_type="CognitiveConcept",
                score=1.0,
            )
        ]

    def fake_multi_hop_traverse(start_kg_ids, **_kwargs):
        return {
            "paths": [],
            "subgraph": {"nodes": [], "edges": []},
            "provenance": [],
            "statistics": {"execution_time_ms": 0.0},
            "warnings": [],
            "mode": "breadth_first",
            "error": None,
            "start_kg_ids": list(start_kg_ids or []),
        }

    _patch_kg_multihop_query_service(
        monkeypatch,
        search_nodes=fake_search_nodes,
        node_details=fake_node_details,
        multi_hop_traverse=fake_multi_hop_traverse,
        neighbors=lambda *_args, **_kwargs: [],
    )
    monkeypatch.setenv("NEUROKG_MULTIHOP_RUNTIME_SEED_MAPPER", "off")

    tool = KGMultihopQATool()
    result = tool._run(
        question="What links working memory and prefrontal cortex?",
        max_hops=2,
        return_subgraph=True,
    )

    assert result.data
    data = result.data
    # Relation question should stop around two seeds, not keep scanning many terms.
    assert len(data["seed_entities"]) == 2
    assert len(search_terms_seen) <= 2


def test_kg_multihop_qa_no_seed_entities_path(monkeypatch):
    def fake_search_nodes(*_args, **_kwargs):
        return []

    def fake_neighbors(*_args, **_kwargs):
        pytest.fail("neighbors() should not run when no seed entities are found")

    _patch_kg_multihop_query_service(
        monkeypatch,
        search_nodes=fake_search_nodes,
        neighbors=fake_neighbors,
    )

    tool = KGMultihopQATool()
    result = tool._run(
        question="qwertyuiop asdfghjkl", max_hops=2, return_subgraph=True
    )

    assert result.status == "error"
    assert result.error
    assert "seed" in result.error.lower()
    assert result.data

    data = result.data
    _assert_kg_multihop_contract_payload(data)
    _assert_kg_multihop_outputs_fallback(data)
    assert data["seed_entities"] == []
    assert data["paths"] == []


def test_kg_multihop_qa_invalid_max_hops_out_of_range():
    tool = KGMultihopQATool()
    result = tool.run(
        question="What connects working memory to PFC?",
        max_hops=0,
        return_subgraph=True,
    )
    assert result["status"] == "error"
    assert "max_hops" in (result.get("error") or "")


def test_kg_multihop_qa_output_contract_keys(monkeypatch):
    def fake_search_nodes(*_args, **_kwargs):
        return [
            query_service.KGNodeSummary(
                kg_id="cc:working_memory",
                label="working_memory",
                node_type="CognitiveConcept",
                score=1.0,
            )
        ]

    def fake_neighbors(*_args, **_kwargs):
        return []

    def fake_multi_hop_traverse(*_args, **_kwargs):
        return {
            "paths": [],
            "subgraph": {"nodes": [], "edges": []},
            "provenance": [],
            "statistics": {"execution_time_ms": 0.0},
            "warnings": [],
            "mode": "breadth_first",
        }

    _patch_kg_multihop_query_service(
        monkeypatch,
        search_nodes=fake_search_nodes,
        neighbors=fake_neighbors,
        multi_hop_traverse=fake_multi_hop_traverse,
    )

    tool = KGMultihopQATool()
    result = tool._run(
        question="What is working memory?",
        max_hops=1,
        return_subgraph=True,
    )

    assert result.status == "error"
    assert result.error
    assert "path" in result.error.lower()
    assert result.data

    data = result.data
    _assert_kg_multihop_contract_payload(data)
    _assert_kg_multihop_outputs_fallback(data)
    assert data["paths"] == []
    assert data["summary"]["question"] == "What is working memory?"
    assert data["summary"]["max_hops"] == 1


def test_kg_multihop_qa_degrades_when_runtime_budget_exhausted(monkeypatch):
    def fail_search_nodes(*_args, **_kwargs):
        pytest.fail("search_nodes() should not run once runtime budget is exhausted")

    def fail_neighbors(*_args, **_kwargs):
        pytest.fail("neighbors() should not run once runtime budget is exhausted")

    def fail_node_details(*_args, **_kwargs):
        pytest.fail("node_details() should not run once runtime budget is exhausted")

    _patch_kg_multihop_query_service(
        monkeypatch,
        search_nodes=fail_search_nodes,
        neighbors=fail_neighbors,
        node_details=fail_node_details,
    )

    ticks = iter([0.0, 3.0, 3.1, 3.2, 3.3, 3.4, 3.5])
    monkeypatch.setattr(
        kg_multihop_module.time,
        "monotonic",
        lambda: next(ticks, 3.6),
    )
    monkeypatch.setenv("BR_KG_MULTIHOP_TOOL_BUDGET_S", "2")

    tool = KGMultihopQATool()
    result = tool._run(
        question="What links working memory and prefrontal cortex?",
        max_hops=2,
        return_subgraph=True,
    )

    assert result.status == "success"
    assert result.error is None
    assert result.data

    data = result.data
    _assert_kg_multihop_contract_payload(data)
    _assert_kg_multihop_outputs_fallback(data)
    assert data["seed_entities"] == []
    assert data["paths"] == []
    assert data["summary"]["degraded"] is True
    assert str(data["summary"].get("degraded_reason", "")).startswith(
        "runtime_budget_exhausted:"
    )
    assert data["summary"]["completion_state"] == "degraded"
    assert data["summary"]["degraded_stage"] == "seed_search"
    assert data["summary"]["runtime_budget_s"] == 2.0
    assert "seed_extract_ms" in data["summary"]
    assert "seed_lookup_ms" in data["summary"]
    assert "traversal_ms" in data["summary"]
    assert "fallback_ms" in data["summary"]
    assert isinstance(data["summary"]["seed_extract_ms"], float)
    assert isinstance(data["summary"]["seed_lookup_ms"], float)
    assert isinstance(data["summary"]["traversal_ms"], float)
    assert isinstance(data["summary"]["fallback_ms"], float)
    assert any("Runtime budget exhausted" in str(msg) for msg in data["warnings"])


def test_registry_auto_discovers_modality_prefixed_tools():
    registry = ToolRegistry(
        auto_discover=False,
        use_capabilities=False,
        enable_integrations=False,
    )

    registry._register_prefixed_stub_tools()

    assert "ieeg_preprocess" in registry.tools
    assert "dmri_fit_model" in registry.tools
