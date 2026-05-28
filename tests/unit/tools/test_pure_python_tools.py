from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd

import brain_researcher.services.tools.atlas_utils as atlas_utils
import brain_researcher.services.tools.fetch_atlas_tool as fetch_module
from brain_researcher.services.tools.extract_timeseries_tool import (
    ExtractTimeseriesTool,
)
from brain_researcher.services.tools.fetch_atlas_tool import FetchAtlasTool
from brain_researcher.services.tools.multimodal_fusion_tool import (
    FusionMethod,
    MultimodalFusionTool,
)
from brain_researcher.services.tools.nilearn_connectivity_matrix_tool import (
    NilearnConnectivityMatrixTool,
)
from brain_researcher.services.tools.nilearn_ica_tool import NilearnICATool
from brain_researcher.services.tools.nilearn_preprocessing_tool import (
    NilearnPreprocessingTool,
)
from brain_researcher.services.tools.nwb_tool import NWBOperation, NWBTool
from brain_researcher.services.tools.reference_asset_registry import (
    clear_reference_asset_registry_cache,
)
from brain_researcher.services.tools.resolve_bids_tool import ResolveBIDSTool


def _write_nifti(path: Path, shape=(4, 4, 4, 10)) -> Path:
    data = np.random.rand(*shape).astype("float32")
    img = nib.Nifti1Image(data, affine=np.eye(4))
    nib.save(img, path)
    return path


def _write_atlas(path: Path) -> Path:
    data = np.zeros((4, 4, 4), dtype="int16")
    data[:2, :, :] = 1
    data[2:, :, :] = 2
    img = nib.Nifti1Image(data, affine=np.eye(4))
    nib.save(img, path)
    return path


def _write_labels(path: Path, labels: list[str]) -> None:
    stem = path.name[:-7] if path.name.endswith(".nii.gz") else path.stem
    (path.parent / f"{stem}_labels.tsv").write_text(
        "\n".join(labels),
        encoding="utf-8",
    )


def _write_templateflow_tsv(path: Path, header: str, rows: list[str]) -> None:
    stem = path.name[:-7] if path.name.endswith(".nii.gz") else path.stem
    (path.parent / f"{stem}.tsv").write_text(
        "\n".join([header, *rows]),
        encoding="utf-8",
    )


def test_multimodal_fusion_tool(tmp_path):
    tool = MultimodalFusionTool()
    mod1 = tmp_path / "mod1.npy"
    mod2 = tmp_path / "mod2.npy"
    np.save(mod1, np.random.randn(20, 5))
    np.save(mod2, np.random.randn(20, 4))

    result = tool._run(
        modality_files={"mod1": str(mod1), "mod2": str(mod2)},
        output_dir=str(tmp_path),
        method=FusionMethod.CCA,
        n_components=3,
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    assert Path(outputs["fused"]).exists()
    assert Path(outputs["similarity"]).exists()
    assert Path(outputs["summary"]).exists()


def test_nilearn_ica_tool(tmp_path):
    tool = NilearnICATool()
    img_path = _write_nifti(tmp_path / "bold.nii.gz", shape=(4, 4, 4, 20))
    result = tool._run(
        input_files=[str(img_path)],
        output_dir=str(tmp_path),
        n_components=3,
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    assert Path(outputs["components"]).exists()
    assert Path(outputs["time_series"]).exists()


def test_nilearn_preprocessing_tool(tmp_path):
    tool = NilearnPreprocessingTool()
    img_path = _write_nifti(tmp_path / "bold.nii.gz", shape=(4, 4, 4, 30))
    confounds = pd.DataFrame(
        {
            "trans_x": np.random.randn(30),
            "trans_y": np.random.randn(30),
        }
    )
    confounds_path = tmp_path / "confounds.tsv"
    confounds.to_csv(confounds_path, sep="\t", index=False)

    result = tool._run(
        input_file=str(img_path),
        output_dir=str(tmp_path),
        confounds_file=str(confounds_path),
        tr=2.0,
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    assert Path(outputs["preprocessed_file"]).exists()
    assert Path(outputs["summary"]).exists()


def test_nilearn_connectivity_matrix_tool(tmp_path):
    tool = NilearnConnectivityMatrixTool()
    ts_path = tmp_path / "timeseries.npy"
    np.save(ts_path, np.random.randn(30, 6))

    result = tool._run(
        timeseries=str(ts_path),
        method="correlation",
        output_dir=str(tmp_path / "connectivity"),
    )
    assert result.status == "success"
    outputs = result.data["outputs"]
    assert Path(outputs["connectivity_matrix"]).exists()
    assert Path(outputs["connectivity_matrix_json"]).exists()
    assert Path(outputs["feature_contract"]).exists()


def test_fetch_atlas_tool_local(tmp_path):
    atlas_path = _write_atlas(tmp_path / "local_atlas.nii.gz")
    tool = FetchAtlasTool()
    result = tool._run(
        atlas_name="local",
        atlas_path=str(atlas_path),
        output_dir=str(tmp_path),
    )
    assert result.status == "success"
    outputs = result.data["outputs"]
    assert Path(outputs["atlas_path"]).exists()
    assert Path(outputs["labels_tsv"]).exists()


def test_fetch_atlas_tool_schaefer_local_first(tmp_path, monkeypatch):
    atlas_root = tmp_path / "atlas_root"
    schaefer_dir = atlas_root / "neurokg" / "raw" / "nilearn_atlases" / "schaefer_2018"
    schaefer_dir.mkdir(parents=True)
    schaefer_100 = (
        schaefer_dir / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    _write_atlas(schaefer_100)

    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)

    tool = FetchAtlasTool()
    result = tool._run(
        atlas_name="Schaefer2018_100",
        output_dir=str(tmp_path / "out"),
    )

    assert result.status == "success"
    assert result.data["summary"]["source"] == "local_cache"
    outputs = result.data["outputs"]
    assert Path(outputs["atlas_path"]).exists()
    assert Path(outputs["labels_tsv"]).exists()


def test_fetch_atlas_tool_schaefer_prefers_templateflow_api_over_legacy_local(
    tmp_path, monkeypatch
):
    atlas_root = tmp_path / "atlas_root"
    schaefer_dir = atlas_root / "schaefer_2018"
    schaefer_dir.mkdir(parents=True)
    legacy = _write_atlas(
        schaefer_dir / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )

    fetched_dir = tmp_path / "fetched"
    fetched_dir.mkdir(parents=True)
    fetched = _write_atlas(
        fetched_dir
        / "tpl-MNI152NLin2009cAsym_res-02_atlas-Schaefer2018_desc-100Parcels7Networks_dseg.nii.gz"
    )
    _write_templateflow_tsv(
        fetched,
        "index\tname\tcolor",
        [
            "1\t7Networks_LH_Vis_1\t#111111",
            "2\t7Networks_RH_Vis_2\t#222222",
        ],
    )

    def _fail_if_called(**kwargs):
        raise AssertionError("unexpected schaefer nilearn fetch")

    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.delenv("TEMPLATEFLOW_HOME", raising=False)
    monkeypatch.setenv("BR_FETCH_ATLAS_ALLOW_NETWORK", "1")
    monkeypatch.setattr(
        fetch_module,
        "fetch_templateflow_schaefer_atlas",
        lambda **kwargs: fetched,
    )
    monkeypatch.setattr(
        fetch_module.datasets,
        "fetch_atlas_schaefer_2018",
        _fail_if_called,
    )

    tool = FetchAtlasTool()
    result = tool._run(
        atlas_name="Schaefer2018_100",
        output_dir=str(tmp_path / "out"),
        reference_img=str(
            tmp_path
            / "sub-01_ses-rest_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
        ),
    )

    assert Path(legacy).exists()
    assert result.status == "success"
    assert result.data["summary"]["source"] == "templateflow_api_download"
    outputs = result.data["outputs"]
    assert Path(outputs["atlas_path"]).name == Path(fetched).name
    assert Path(outputs["labels_tsv"]).exists()


def test_fetch_atlas_tool_schaefer_missing_fails_fast(tmp_path, monkeypatch):
    empty_root = tmp_path / "empty"
    empty_root.mkdir(parents=True)
    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(empty_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)
    monkeypatch.setattr(
        fetch_module,
        "existing_search_roots",
        lambda data_dir, output_root: [empty_root],
    )

    tool = FetchAtlasTool()
    result = tool._run(
        atlas_name="Schaefer2018_400",
        output_dir=str(tmp_path / "out"),
    )

    assert result.status == "error"
    assert result.error == "atlas_not_found_local"
    assert result.data["requested_resolution"] == 400
    assert str(empty_root) in result.data["searched_roots"]
    assert isinstance(result.data["available_schaefer_resolutions"], list)
    assert result.data["available_schaefer_resolutions"] == []


def test_fetch_atlas_tool_real_atlases_default_to_shared_root(tmp_path, monkeypatch):
    atlas_root = tmp_path / "atlas_root"
    schaefer_dir = atlas_root / "neurokg" / "raw" / "nilearn_atlases" / "schaefer_2018"
    schaefer_dir.mkdir(parents=True)
    schaefer_100 = (
        schaefer_dir / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    _write_atlas(schaefer_100)

    shared_root = tmp_path / "shared_atlases"
    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.setenv("BR_ATLAS_OUTPUT_ROOT", str(shared_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)
    clear_reference_asset_registry_cache()

    tool = FetchAtlasTool()
    result = tool._run(atlas_name="Schaefer2018_100")

    assert result.status == "success"
    outputs = result.data["outputs"]
    assert Path(outputs["atlas_path"]).parent == shared_root / "schaefer_2018"
    assert Path(outputs["labels_tsv"]).parent == shared_root / "schaefer_2018"


def test_fetch_atlas_tool_demo_atlases_stay_in_demo_root(tmp_path, monkeypatch):
    demo_root = tmp_path / "br_demo"
    shared_root = tmp_path / "shared_atlases"
    monkeypatch.setenv("BR_ATLAS_OUTPUT_ROOT", str(shared_root))
    monkeypatch.setenv("BR_DEMO_ARTIFACT_DIR", str(demo_root))
    monkeypatch.setattr(fetch_module, "_OUTPUT_ROOT", demo_root)

    tool = FetchAtlasTool()
    result = tool._run(atlas_name="synthetic")

    assert result.status == "success"
    outputs = result.data["outputs"]
    assert Path(outputs["atlas_path"]).parent == demo_root
    assert Path(outputs["labels_tsv"]).parent == demo_root


def test_fetch_atlas_tool_aal_local_first(tmp_path, monkeypatch):
    atlas_root = tmp_path / "atlas_root"
    aal_dir = atlas_root / "aal"
    aal_dir.mkdir(parents=True)
    atlas_path = _write_atlas(aal_dir / "AAL.nii.gz")
    _write_labels(atlas_path, ["background", "Region_A", "Region_B"])
    shared_root = tmp_path / "shared_atlases"

    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.setenv("BR_ATLAS_OUTPUT_ROOT", str(shared_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)

    tool = FetchAtlasTool()
    result = tool._run(atlas_name="AAL")

    assert result.status == "success"
    assert result.data["summary"]["source"] == "local_cache"
    outputs = result.data["outputs"]
    assert Path(outputs["atlas_path"]).parent == shared_root / "aal"
    assert Path(outputs["labels_tsv"]).exists()


def test_fetch_atlas_tool_harvard_local_first(tmp_path, monkeypatch):
    atlas_root = tmp_path / "atlas_root"
    ho_dir = atlas_root / "harvard_oxford"
    ho_dir.mkdir(parents=True)
    atlas_path = _write_atlas(ho_dir / "HarvardOxford-sub-maxprob-thr25-2mm.nii.gz")
    _write_labels(atlas_path, ["Background", "Sub_A", "Sub_B"])
    shared_root = tmp_path / "shared_atlases"

    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.setenv("BR_ATLAS_OUTPUT_ROOT", str(shared_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)

    tool = FetchAtlasTool()
    result = tool._run(atlas_name="harvard_oxford_sub25")

    assert result.status == "success"
    assert result.data["summary"]["source"] == "local_cache"
    assert (
        Path(result.data["outputs"]["atlas_path"]).parent
        == shared_root / "harvard_oxford"
    )


def test_fetch_atlas_tool_yeo_local_first(tmp_path, monkeypatch):
    atlas_root = tmp_path / "atlas_root"
    yeo_dir = atlas_root / "yeo_2011"
    yeo_dir.mkdir(parents=True)
    atlas_path = _write_atlas(
        yeo_dir / "Yeo2011_17Networks_MNI152_FreeSurferConformed1mm_LiberalMask.nii.gz"
    )
    _write_labels(atlas_path, ["NONE", "Net17_1", "Net17_2"])
    shared_root = tmp_path / "shared_atlases"

    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.setenv("BR_ATLAS_OUTPUT_ROOT", str(shared_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)

    tool = FetchAtlasTool()
    result = tool._run(atlas_name="yeo17")

    assert result.status == "success"
    assert result.data["summary"]["source"] == "local_cache"
    assert Path(result.data["outputs"]["atlas_path"]).parent == shared_root / "yeo_2011"
    assert (
        result.data["summary"]["reference_asset"]["id"]
        == "atlas.yeo2011.17networks.bundle"
    )


def test_fetch_atlas_tool_msdl_local_first(tmp_path, monkeypatch):
    atlas_root = tmp_path / "atlas_root"
    msdl_dir = atlas_root / "msdl_atlas" / "MSDL_rois"
    msdl_dir.mkdir(parents=True)
    _write_atlas(msdl_dir / "msdl_rois.nii")
    (msdl_dir / "msdl_rois_labels.csv").write_text(
        "x,y,z,name,net name\n-1,0,0,L Aud,Aud\n1,0,0,R Aud,Aud\n",
        encoding="utf-8",
    )
    shared_root = tmp_path / "shared_atlases"

    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.setenv("BR_ATLAS_OUTPUT_ROOT", str(shared_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)

    tool = FetchAtlasTool()
    result = tool._run(atlas_name="msdl")

    assert result.status == "success"
    assert result.data["summary"]["source"] == "local_cache"
    assert result.data["summary"]["family"] == "msdl_atlas"
    assert result.data["summary"]["reference_asset"]["id"] == "nilearn.atlas.msdl"
    assert (
        Path(result.data["outputs"]["atlas_path"]).parent == shared_root / "msdl_atlas"
    )


def test_fetch_atlas_tool_schaefer_prefers_templateflow(tmp_path, monkeypatch):
    templateflow_root = tmp_path / "templateflow"
    templateflow_dir = templateflow_root / "tpl-MNI152NLin2009cAsym"
    templateflow_dir.mkdir(parents=True)
    templateflow_atlas = (
        templateflow_dir
        / "tpl-MNI152NLin2009cAsym_res-02_atlas-Schaefer2018_desc-100Parcels7Networks_dseg.nii.gz"
    )
    _write_atlas(templateflow_atlas)
    distractor_dir = templateflow_root / "tpl-MNI152NLin6Asym"
    distractor_dir.mkdir(parents=True)
    _write_atlas(
        distractor_dir
        / "tpl-MNI152NLin6Asym_res-01_atlas-Schaefer2018_desc-100Parcels7Networks_dseg.nii.gz"
    )

    atlas_root = tmp_path / "atlas_root"
    schaefer_dir = atlas_root / "neurokg" / "raw" / "nilearn_atlases" / "schaefer_2018"
    schaefer_dir.mkdir(parents=True)
    _write_atlas(
        schaefer_dir / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )

    monkeypatch.setenv("TEMPLATEFLOW_HOME", str(templateflow_root))
    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)
    clear_reference_asset_registry_cache()

    tool = FetchAtlasTool()
    reference_img = _write_nifti(
        tmp_path
        / "sub-01_ses-rest_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    result = tool._run(
        atlas_name="Schaefer2018_100",
        output_dir=str(tmp_path / "out"),
        reference_img=str(reference_img),
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    assert Path(outputs["atlas_path"]).name == templateflow_atlas.name
    assert result.data["summary"]["source"] == "local_cache"
    assert result.data["summary"]["reference_space"] == "MNI152NLin2009cAsym"
    assert result.data["summary"]["reference_resolution"] == "2"


def test_fetch_atlas_tool_difumo_local_first(tmp_path, monkeypatch):
    templateflow_root = tmp_path / "templateflow"
    templateflow_dir = templateflow_root / "tpl-MNI152NLin2009cAsym"
    templateflow_dir.mkdir(parents=True)
    difumo_atlas = (
        templateflow_dir
        / "tpl-MNI152NLin2009cAsym_res-02_atlas-DiFuMo_desc-4dimensions_probseg.nii.gz"
    )
    _write_nifti(difumo_atlas, shape=(2, 2, 2, 4))
    _write_templateflow_tsv(
        difumo_atlas,
        "Component\tDifumo_names",
        [
            "1\tRegion_A",
            "2\tRegion_B",
            "3\tRegion_C",
            "4\tRegion_D",
        ],
    )
    distractor_dir = templateflow_root / "tpl-MNI152NLin6Asym"
    distractor_dir.mkdir(parents=True)
    _write_nifti(
        distractor_dir
        / "tpl-MNI152NLin6Asym_res-01_atlas-DiFuMo_desc-4dimensions_probseg.nii.gz",
        shape=(2, 2, 2, 4),
    )

    monkeypatch.setenv("TEMPLATEFLOW_HOME", str(templateflow_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)
    clear_reference_asset_registry_cache()

    tool = FetchAtlasTool()
    reference_img = _write_nifti(
        tmp_path
        / "sub-01_ses-rest_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    result = tool._run(
        atlas_name="DiFuMo_4",
        output_dir=str(tmp_path / "out"),
        reference_img=str(reference_img),
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    atlas_path = Path(outputs["atlas_path"])
    assert atlas_path.name == difumo_atlas.name
    labels = Path(outputs["labels_tsv"]).read_text(encoding="utf-8").splitlines()
    assert labels == ["background", "Region_A", "Region_B", "Region_C", "Region_D"]
    assert result.data["summary"]["family"] == "difumo"


def test_fetch_atlas_tool_schaefer_uses_templateflow_api_when_cache_placeholder(
    tmp_path, monkeypatch
):
    templateflow_root = tmp_path / "templateflow"
    templateflow_dir = templateflow_root / "tpl-MNI152NLin2009cAsym"
    templateflow_dir.mkdir(parents=True)
    placeholder = (
        templateflow_dir
        / "tpl-MNI152NLin2009cAsym_res-02_atlas-Schaefer2018_desc-100Parcels7Networks_dseg.nii.gz"
    )
    placeholder.write_bytes(b"")
    api_calls: list[dict[str, object]] = []

    class FakeTemplateFlowAPI:
        def get(self, template, raise_empty=False, **kwargs):
            api_calls.append({"template": template, **kwargs})
            assert template == "MNI152NLin2009cAsym"
            assert kwargs["atlas"] == "Schaefer2018"
            assert kwargs["desc"] == "100Parcels7Networks"
            assert kwargs["suffix"] == "dseg"
            if kwargs["extension"] == [".nii.gz", ".nii"]:
                _write_atlas(placeholder)
                return placeholder
            assert kwargs["extension"] == ".tsv"
            _write_templateflow_tsv(
                placeholder,
                "index\tname\tcolor",
                [
                    "1\t7Networks_LH_Vis_1\t#111111",
                    "2\t7Networks_RH_Vis_2\t#222222",
                ],
            )
            return placeholder.with_name(f"{placeholder.name[:-7]}.tsv")

    monkeypatch.setenv("TEMPLATEFLOW_HOME", str(templateflow_root))
    monkeypatch.setenv("BR_FETCH_ATLAS_ALLOW_NETWORK", "1")
    monkeypatch.setattr(
        fetch_module,
        "resolve_local_volume_atlas",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    monkeypatch.setattr(
        fetch_module,
        "find_local_schaefer_atlas",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        atlas_utils,
        "_import_templateflow_api",
        lambda: FakeTemplateFlowAPI(),
    )
    clear_reference_asset_registry_cache()

    reference_img = _write_nifti(
        tmp_path
        / "sub-01_ses-rest_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    result = FetchAtlasTool()._run(
        atlas_name="Schaefer2018_100",
        output_dir=str(tmp_path / "out"),
        reference_img=str(reference_img),
    )

    assert result.status == "success"
    assert result.data["summary"]["source"] == "templateflow_api_download"
    labels = (
        Path(result.data["outputs"]["labels_tsv"])
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert labels == [
        "background",
        "7Networks_LH_Vis_1",
        "7Networks_RH_Vis_2",
    ]
    assert any(call["extension"] == ".tsv" for call in api_calls)


def test_fetch_atlas_tool_difumo_uses_templateflow_api_when_cache_placeholder(
    tmp_path, monkeypatch
):
    templateflow_root = tmp_path / "templateflow"
    templateflow_dir = templateflow_root / "tpl-MNI152NLin2009cAsym"
    templateflow_dir.mkdir(parents=True)
    placeholder = (
        templateflow_dir
        / "tpl-MNI152NLin2009cAsym_res-02_atlas-DiFuMo_desc-4dimensions_probseg.nii.gz"
    )
    placeholder.write_bytes(b"")

    class FakeTemplateFlowAPI:
        def get(self, template, raise_empty=False, **kwargs):
            assert template == "MNI152NLin2009cAsym"
            assert kwargs["atlas"] == "DiFuMo"
            assert kwargs["desc"] == "4dimensions"
            assert kwargs["suffix"] == "probseg"
            _write_nifti(placeholder, shape=(2, 2, 2, 4))
            _write_templateflow_tsv(
                placeholder,
                "Component\tDifumo_names",
                [
                    "1\tRegion_A",
                    "2\tRegion_B",
                    "3\tRegion_C",
                    "4\tRegion_D",
                ],
            )
            return placeholder

    monkeypatch.setenv("TEMPLATEFLOW_HOME", str(templateflow_root))
    monkeypatch.setenv("BR_FETCH_ATLAS_ALLOW_NETWORK", "1")
    monkeypatch.setattr(
        fetch_module,
        "resolve_local_volume_atlas",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    monkeypatch.setattr(
        atlas_utils,
        "_import_templateflow_api",
        lambda: FakeTemplateFlowAPI(),
    )
    clear_reference_asset_registry_cache()

    reference_img = _write_nifti(
        tmp_path
        / "sub-01_ses-rest_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    result = FetchAtlasTool()._run(
        atlas_name="DiFuMo_4",
        output_dir=str(tmp_path / "out"),
        reference_img=str(reference_img),
    )

    assert result.status == "success"
    assert result.data["summary"]["source"] == "templateflow_api_download"
    labels = (
        Path(result.data["outputs"]["labels_tsv"])
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert labels == ["background", "Region_A", "Region_B", "Region_C", "Region_D"]


def test_extract_timeseries_tool(tmp_path):
    atlas_path = _write_atlas(tmp_path / "atlas.nii.gz")
    img_path = _write_nifti(tmp_path / "bold.nii.gz", shape=(4, 4, 4, 20))
    tool = ExtractTimeseriesTool()
    result = tool._run(
        img=str(img_path),
        atlas=str(atlas_path),
        output_dir=str(tmp_path),
        tr=2.0,
    )
    assert result.status == "success"
    outputs = result.data["outputs"]
    ts = np.load(outputs["timeseries"])
    assert ts.shape[0] == 20


def test_resolve_bids_tool(tmp_path):
    bids_root = tmp_path / "bids"
    bids_root.mkdir()
    (bids_root / "dataset_description.json").write_text(
        json.dumps({"Name": "TestDataset", "BIDSVersion": "1.8.0"})
    )
    anat_dir = bids_root / "sub-01" / "anat"
    anat_dir.mkdir(parents=True)
    img_path = _write_nifti(anat_dir / "sub-01_T1w.nii.gz", shape=(2, 2, 2, 1))

    tool = ResolveBIDSTool()
    result = tool._run(
        bids_root=str(bids_root),
        subject_id="01",
        datatype="anat",
        suffix="T1w",
    )
    assert result.status == "success"
    assert Path(result.data["outputs"]["resolved_path"]) == img_path


def test_nwb_tool_write_read(tmp_path):
    tool = NWBTool()
    out_file = tmp_path / "test.nwb"
    metadata = {
        "session_description": "unit test session",
        "identifier": "test-nwb",
        "session_start_time": datetime.now(timezone.utc).isoformat(),
    }
    data = {"name": "series", "data": [0.1, 0.2, 0.3], "rate": 1.0, "unit": "mV"}

    write_result = tool._run(
        operation=NWBOperation.WRITE,
        output_file=str(out_file),
        metadata=metadata,
        data=data,
    )
    assert write_result.status == "success"
    assert out_file.exists()

    inspect_result = tool._run(operation=NWBOperation.INSPECT, input_file=str(out_file))
    assert inspect_result.status == "success"

    read_result = tool._run(
        operation=NWBOperation.READ,
        input_file=str(out_file),
        data_path="acquisition/series",
    )
    assert read_result.status == "success"
    assert np.allclose(read_result.data["data"], data["data"])
