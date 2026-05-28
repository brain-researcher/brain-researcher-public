from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np

from scripts.atlas.seed_repo_atlas_assets import (
    detect_storage_scope,
    seed_repo_atlas_assets,
)


def _write_nifti(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.zeros((4, 4, 4), dtype="int16")
    data[:2, :, :] = 1
    data[2:, :, :] = 2
    nib.save(nib.Nifti1Image(data, np.eye(4)), path)
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_detect_storage_scope_parses_known_mount_types(tmp_path: Path) -> None:
    node_local_line = (
        "123 456 0:44 / /app/data/atlases rw,relatime - ext4 "
        "/var/lib/kubelet/pods/abc/volumes/kubernetes.io~host-path/atlases rw"
    )
    shared_line = (
        "123 456 0:44 / /app/data/atlases rw,relatime - ext4 "
        "/var/lib/kubelet/pods/abc/volumes/kubernetes.io~csi/pvc-123/mount rw"
    )

    assert (
        detect_storage_scope(tmp_path, mountinfo_line=node_local_line) == "node_local"
    )
    assert detect_storage_scope(tmp_path, mountinfo_line=shared_line) == "shared"


def test_seed_repo_atlas_assets_reuses_local_trees(tmp_path: Path) -> None:
    output_root = tmp_path / "atlases_out"
    nilearn_root = tmp_path / "nilearn_src"
    neuromaps_root = tmp_path / "neuromaps_src"
    niclip_root = tmp_path / "niclip_src"

    # Schaefer
    for n_rois, n_networks in ((100, 7), (200, 7), (200, 17), (400, 7), (1000, 7)):
        _write_nifti(
            nilearn_root
            / "schaefer_2018"
            / (
                f"Schaefer2018_{n_rois}Parcels_{n_networks}Networks_"
                "order_FSLMNI152_2mm.nii.gz"
            )
        )

    # AAL
    _write_nifti(nilearn_root / "aal_SPM12" / "aal" / "atlas" / "AAL.nii")
    _write_text(
        nilearn_root / "aal_SPM12" / "aal" / "atlas" / "AAL.xml",
        """<?xml version="1.0"?>
<atlas><data>
<label><index>1</index><name>Region_A</name></label>
<label><index>2</index><name>Region_B</name></label>
</data></atlas>
""",
    )

    # Harvard-Oxford
    _write_nifti(
        nilearn_root
        / "fsl"
        / "data"
        / "atlases"
        / "HarvardOxford"
        / "HarvardOxford-cort-maxprob-thr25-2mm.nii.gz"
    )
    _write_nifti(
        nilearn_root
        / "fsl"
        / "data"
        / "atlases"
        / "HarvardOxford"
        / "HarvardOxford-sub-maxprob-thr25-2mm.nii.gz"
    )
    _write_text(
        nilearn_root / "fsl" / "data" / "atlases" / "HarvardOxford-Cortical.xml",
        """<?xml version="1.0"?>
<atlas><data>
<label index="0">Cortex_A</label>
<label index="1">Cortex_B</label>
</data></atlas>
""",
    )
    _write_text(
        nilearn_root / "fsl" / "data" / "atlases" / "HarvardOxford-Subcortical.xml",
        """<?xml version="1.0"?>
<atlas><data>
<label index="0">Sub_A</label>
<label index="1">Sub_B</label>
</data></atlas>
""",
    )

    # Yeo
    yeo_dir = nilearn_root / "yeo_2011" / "Yeo_JNeurophysiol11_MNI152"
    _write_nifti(
        yeo_dir / "Yeo2011_7Networks_MNI152_FreeSurferConformed1mm_LiberalMask.nii.gz"
    )
    _write_nifti(
        yeo_dir / "Yeo2011_17Networks_MNI152_FreeSurferConformed1mm_LiberalMask.nii.gz"
    )
    _write_text(
        yeo_dir / "Yeo2011_7Networks_ColorLUT.txt",
        "0 NONE 0 0 0 0\n1 Network_1 0 0 0 0\n2 Network_2 0 0 0 0\n",
    )
    _write_text(
        yeo_dir / "Yeo2011_17Networks_ColorLUT.txt",
        "0 NONE 0 0 0 0\n1 Net17_1 0 0 0 0\n2 Net17_2 0 0 0 0\n",
    )

    # Extended Nilearn assets
    _write_nifti(nilearn_root / "destrieux_2009" / "destrieux2009_rois.nii.gz")
    _write_text(
        nilearn_root / "destrieux_2009" / "destrieux2009_rois_labels.csv",
        "index,name\n1,Region1\n2,Region2\n",
    )
    _write_nifti(
        nilearn_root
        / "basc_multiscale_2015"
        / "template_cambridge_basc_multiscale_nii_sym"
        / "template_cambridge_basc_multiscale_sym_scale122.nii.gz"
    )
    _write_nifti(nilearn_root / "msdl_atlas" / "MSDL_rois" / "msdl_rois.nii")

    # Neuromaps and NiCLIP
    _write_text(neuromaps_root / "atlases" / "atlas_a.txt", "atlas-a")
    _write_text(neuromaps_root / "annotations" / "annot_a.txt", "annot-a")
    _write_text(
        niclip_root
        / "osf_data"
        / "dsj56"
        / "osfstorage"
        / "osfstorage"
        / "data"
        / "image"
        / "sample.npy",
        "sample",
    )

    summary = seed_repo_atlas_assets(
        output_root=output_root,
        nilearn_source_root=nilearn_root,
        neuromaps_source_root=neuromaps_root,
        niclip_source_root=niclip_root,
        download_missing=False,
        storage_scope="shared",
    )

    for directory in (
        "schaefer_2018",
        "aal",
        "harvard_oxford",
        "yeo_2011",
        "nilearn",
        "neuromaps",
        "niclip",
        "manifests",
    ):
        assert (output_root / directory).exists()

    assert (
        output_root
        / "schaefer_2018"
        / "Schaefer2018_200Parcels_17Networks_order_FSLMNI152_2mm.nii.gz"
    ).exists()
    assert (output_root / "aal" / "AAL_labels.tsv").exists()
    assert (
        output_root
        / "harvard_oxford"
        / "HarvardOxford-sub-maxprob-thr25-2mm_labels.json"
    ).exists()
    assert (
        output_root
        / "yeo_2011"
        / "Yeo2011_17Networks_MNI152_FreeSurferConformed1mm_LiberalMask_labels.tsv"
    ).exists()
    assert (
        output_root
        / "niclip"
        / "osf_data"
        / "dsj56"
        / "osfstorage"
        / "osfstorage"
        / "data"
        / "image"
        / "sample.npy"
    ).exists()

    manifests = summary["manifests"]
    inventory = json.loads(
        Path(manifests["atlas_inventory_json"]).read_text(encoding="utf-8")
    )
    assert any(record["asset_group"] == "niclip" for record in inventory)
    assert any(record["asset_group"] == "neuromaps" for record in inventory)
    assert any(record["asset_group"] == "schaefer_2018" for record in inventory)
    assert summary["counts"]["tool_facing_seeded"] == 10


def test_seed_repo_atlas_assets_skips_symlinked_directories(tmp_path: Path) -> None:
    output_root = tmp_path / "atlases_out"
    nilearn_root = tmp_path / "nilearn_src"
    neuromaps_root = tmp_path / "neuromaps_src"
    niclip_root = tmp_path / "niclip_src"

    _write_nifti(
        nilearn_root
        / "schaefer_2018"
        / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    _write_text(neuromaps_root / "atlases" / "atlas_a.txt", "atlas-a")
    real_niclip_data = niclip_root / "data" / "image"
    _write_text(real_niclip_data / "sample.npy", "sample")
    symlink_target = niclip_root / "dsj56" / "osfstorage" / "osfstorage" / "data"
    symlink_target.parent.mkdir(parents=True, exist_ok=True)
    symlink_target.symlink_to(real_niclip_data.parent, target_is_directory=True)

    summary = seed_repo_atlas_assets(
        output_root=output_root,
        nilearn_source_root=nilearn_root,
        neuromaps_source_root=neuromaps_root,
        niclip_source_root=niclip_root,
        download_missing=False,
        storage_scope="shared",
    )

    assert (output_root / "niclip" / "data" / "image" / "sample.npy").exists()
    assert not (
        output_root / "niclip" / "dsj56" / "osfstorage" / "osfstorage" / "data"
    ).is_file()
    assert summary["counts"]["niclip_synced"] >= 1
