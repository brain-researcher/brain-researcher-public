from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
import pytest

import brain_researcher.services.tools.atlas_utils as atlas_utils
from brain_researcher.services.tools.params import (
    NiftiMaskerParameters,
    ROIExtractionParameters,
    run_nifti_masker,
    run_roi_extraction,
)
import brain_researcher.services.tools.params.nilearn_preprocessing as nilearn_preprocessing
from brain_researcher.services.tools.params.nilearn_preprocessing import _resolve_atlas


def _make_nifti(path: Path, shape: tuple[int, int, int, int] = (5, 5, 5, 10)) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.random.randn(*shape)
    img = nib.Nifti1Image(data, np.eye(4))
    img.header.set_zooms((2.0, 2.0, 2.0, 2.0))
    nib.save(img, path)
    return str(path)


def _make_atlas(path: Path) -> str:
    labels = np.zeros((5, 5, 5), dtype=np.int16)
    labels[:3, :, :] = 1
    labels[3:, :, :] = 2
    img = nib.Nifti1Image(labels, np.eye(4))
    nib.save(img, path)
    return str(path)


def _make_mask(path: Path, shape: tuple[int, int, int] = (5, 5, 5)) -> str:
    mask = np.ones(shape, dtype=np.int16)
    img = nib.Nifti1Image(mask, np.eye(4))
    nib.save(img, path)
    return str(path)


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


def test_run_nifti_masker(tmp_path):
    img = _make_nifti(tmp_path / "image.nii.gz")
    mask = _make_mask(tmp_path / "mask.nii.gz")
    confounds = tmp_path / "confounds.tsv"
    df = pd.DataFrame(
        {
            "trans_x": np.random.randn(10),
            "wm_csf": np.random.randn(10),
            "motion": np.random.randn(10),
        }
    )
    df.to_csv(confounds, sep="\t", index=False)
    params = NiftiMaskerParameters(
        img=img,
        mask_img=mask,
        confounds=str(confounds),
        output_file=str(tmp_path / "signals.npy"),
    )
    result = run_nifti_masker(params)
    outputs = result["outputs"]
    assert Path(outputs["signals"]).exists()


def test_run_roi_extraction(tmp_path):
    img = _make_nifti(tmp_path / "image.nii.gz")
    atlas = _make_atlas(tmp_path / "atlas.nii.gz")
    params = ROIExtractionParameters(
        img=img,
        atlas=atlas,
        output_dir=str(tmp_path / "roi_out"),
        output_file=str(tmp_path / "roi.npy"),
        n_parcels=5,
    )
    result = run_roi_extraction(params)
    outputs = result["outputs"]
    assert Path(outputs["signals"]).exists()
    if outputs.get("labels"):
        assert Path(outputs["labels"]).exists()


def test_resolve_atlas_missing_explicit_path_fails_closed(tmp_path, monkeypatch):
    def _fail_if_called(**kwargs):
        raise AssertionError("unexpected schaefer network fetch")

    monkeypatch.setattr(
        "brain_researcher.services.tools.params.nilearn_preprocessing.datasets.fetch_atlas_schaefer_2018",
        _fail_if_called,
    )

    missing_path = tmp_path / "missing_atlas.nii.gz"
    with pytest.raises(FileNotFoundError, match=str(missing_path)):
        _resolve_atlas(str(missing_path), None)


def test_resolve_atlas_schaefer_symbolic_name_prefers_local_cache(
    tmp_path, monkeypatch
):
    atlas_root = tmp_path / "atlas_root"
    schaefer_dir = atlas_root / "neurokg" / "raw" / "nilearn_atlases" / "schaefer_2018"
    schaefer_dir.mkdir(parents=True)
    schaefer_100 = (
        schaefer_dir / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    _make_atlas(schaefer_100)

    def _fail_if_called(**kwargs):
        raise AssertionError("unexpected schaefer network fetch")

    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)
    monkeypatch.setattr(
        "brain_researcher.services.tools.params.nilearn_preprocessing.datasets.fetch_atlas_schaefer_2018",
        _fail_if_called,
    )

    atlas_path, labels = _resolve_atlas("Schaefer2018_100", 100)
    assert Path(atlas_path) == schaefer_100
    assert labels == ["background", "roi_001", "roi_002"]


def test_resolve_atlas_schaefer_17n_prefers_matching_variant(tmp_path, monkeypatch):
    atlas_root = tmp_path / "atlas_root"
    schaefer_dir = atlas_root / "schaefer_2018"
    schaefer_dir.mkdir(parents=True)
    schaefer_200_7 = (
        schaefer_dir / "Schaefer2018_200Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    schaefer_200_17 = (
        schaefer_dir / "Schaefer2018_200Parcels_17Networks_order_FSLMNI152_2mm.nii.gz"
    )
    _make_atlas(schaefer_200_7)
    _make_atlas(schaefer_200_17)

    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)

    atlas_path, _ = _resolve_atlas("Schaefer2018_200_17n", 200)
    assert Path(atlas_path) == schaefer_200_17


def test_resolve_atlas_schaefer_prefers_reference_matched_templateflow(
    tmp_path, monkeypatch
):
    templateflow_root = tmp_path / "templateflow"
    wanted_dir = templateflow_root / "tpl-MNI152NLin2009cAsym"
    distractor_dir = templateflow_root / "tpl-MNI152NLin6Asym"
    wanted_dir.mkdir(parents=True)
    distractor_dir.mkdir(parents=True)
    wanted = _make_atlas(
        wanted_dir
        / "tpl-MNI152NLin2009cAsym_res-02_atlas-Schaefer2018_desc-100Parcels7Networks_dseg.nii.gz"
    )
    _make_atlas(
        distractor_dir
        / "tpl-MNI152NLin6Asym_res-01_atlas-Schaefer2018_desc-100Parcels7Networks_dseg.nii.gz"
    )

    monkeypatch.setenv("TEMPLATEFLOW_HOME", str(templateflow_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)

    reference_img = _make_nifti(
        tmp_path
        / "sub-01_ses-rest_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    atlas_path, _ = _resolve_atlas(
        "Schaefer2018_100",
        100,
        reference_img=reference_img,
    )
    assert Path(atlas_path) == Path(wanted)


def test_resolve_atlas_schaefer_uses_templateflow_api_when_cache_placeholder(
    tmp_path, monkeypatch
):
    templateflow_root = tmp_path / "templateflow"
    tf_dir = templateflow_root / "tpl-MNI152NLin2009cAsym"
    tf_dir.mkdir(parents=True)
    placeholder = (
        tf_dir
        / "tpl-MNI152NLin2009cAsym_res-02_atlas-Schaefer2018_desc-100Parcels7Networks_dseg.nii.gz"
    )
    placeholder.write_bytes(b"")

    class FakeTemplateFlowAPI:
        def get(self, template, raise_empty=False, **kwargs):
            assert template == "MNI152NLin2009cAsym"
            assert kwargs["atlas"] == "Schaefer2018"
            _make_atlas(placeholder)
            _write_templateflow_tsv(
                placeholder,
                "index\tname\tcolor",
                [
                    "1\t7Networks_LH_Vis_1\t#111111",
                    "2\t7Networks_RH_Vis_2\t#222222",
                ],
            )
            return placeholder

    monkeypatch.setenv("TEMPLATEFLOW_HOME", str(templateflow_root))
    monkeypatch.setenv("BR_FETCH_ATLAS_ALLOW_NETWORK", "1")
    monkeypatch.setattr(
        nilearn_preprocessing,
        "find_local_schaefer_atlas",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        atlas_utils,
        "_import_templateflow_api",
        lambda: FakeTemplateFlowAPI(),
    )

    reference_img = _make_nifti(
        tmp_path
        / "sub-01_ses-rest_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    atlas_path, labels = _resolve_atlas(
        "Schaefer2018_100",
        100,
        reference_img=reference_img,
    )
    assert Path(atlas_path) == placeholder
    assert labels == [
        "background",
        "7Networks_LH_Vis_1",
        "7Networks_RH_Vis_2",
    ]


def test_resolve_atlas_schaefer_prefers_templateflow_api_over_legacy_local(
    tmp_path, monkeypatch
):
    atlas_root = tmp_path / "atlas_root"
    schaefer_dir = atlas_root / "schaefer_2018"
    schaefer_dir.mkdir(parents=True)
    legacy = _make_atlas(
        schaefer_dir / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )

    templateflow_root = tmp_path / "templateflow"
    tf_dir = templateflow_root / "tpl-MNI152NLin2009cAsym"
    tf_dir.mkdir(parents=True)
    fetched = tf_dir / (
        "tpl-MNI152NLin2009cAsym_res-02_atlas-Schaefer2018_"
        "desc-100Parcels7Networks_dseg.nii.gz"
    )

    class FakeTemplateFlowAPI:
        def get(self, template, raise_empty=False, **kwargs):
            assert template == "MNI152NLin2009cAsym"
            assert kwargs["atlas"] == "Schaefer2018"
            _make_atlas(fetched)
            _write_templateflow_tsv(
                fetched,
                "index\tname\tcolor",
                [
                    "1\t7Networks_LH_Vis_1\t#111111",
                    "2\t7Networks_RH_Vis_2\t#222222",
                ],
            )
            return fetched

    def _fail_if_called(**kwargs):
        raise AssertionError("unexpected schaefer nilearn fetch")

    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.setenv("TEMPLATEFLOW_HOME", str(templateflow_root))
    monkeypatch.setenv("BR_FETCH_ATLAS_ALLOW_NETWORK", "1")
    monkeypatch.setattr(
        atlas_utils,
        "_import_templateflow_api",
        lambda: FakeTemplateFlowAPI(),
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.params.nilearn_preprocessing.datasets.fetch_atlas_schaefer_2018",
        _fail_if_called,
    )

    reference_img = _make_nifti(
        tmp_path
        / "sub-01_ses-rest_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    atlas_path, labels = _resolve_atlas(
        "Schaefer2018_100",
        100,
        reference_img=reference_img,
    )
    assert Path(legacy).exists()
    assert Path(atlas_path) == fetched
    assert labels == [
        "background",
        "7Networks_LH_Vis_1",
        "7Networks_RH_Vis_2",
    ]


@pytest.mark.parametrize(
    ("atlas_name", "family_dir", "filename", "labels"),
    [
        ("AAL", "aal", "AAL.nii.gz", ["background", "Region_A", "Region_B"]),
        (
            "harvard_oxford_sub25",
            "harvard_oxford",
            "HarvardOxford-sub-maxprob-thr25-2mm.nii.gz",
            ["Background", "Sub_A", "Sub_B"],
        ),
        (
            "yeo17",
            "yeo_2011",
            "Yeo2011_17Networks_MNI152_FreeSurferConformed1mm_LiberalMask.nii.gz",
            ["NONE", "Net17_1", "Net17_2"],
        ),
    ],
)
def test_resolve_atlas_symbolic_name_prefers_local_family_dirs(
    tmp_path,
    monkeypatch,
    atlas_name,
    family_dir,
    filename,
    labels,
):
    atlas_root = tmp_path / "atlas_root"
    family_path = atlas_root / family_dir
    family_path.mkdir(parents=True)
    atlas_path = Path(_make_atlas(family_path / filename))
    _write_labels(atlas_path, labels)

    monkeypatch.setenv("BR_ATLAS_SEARCH_ROOTS", str(atlas_root))
    monkeypatch.delenv("BR_FETCH_ATLAS_ALLOW_NETWORK", raising=False)

    resolved_path, resolved_labels = _resolve_atlas(atlas_name, None)
    assert Path(resolved_path) == atlas_path
    assert resolved_labels == labels
