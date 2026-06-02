from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.io import savemat

from scripts.tribe_closed_loop.materialize_biological_motion import main


def _write_config(
    path: Path, source_root: Path, manifest_path: Path, materialized_root: Path
) -> None:
    payload = {
        "library_id": "tribe_ibc_paradigm_sweep_v1",
        "brain_researcher_paths": {
            "data_root": str(source_root.parent.parent),
            "project_root": str(materialized_root.parent.parent),
            "source_checkout_root": str(source_root.parent),
            "materialized_library_root": str(materialized_root.parent),
            "manifests_root": str(manifest_path.parent),
            "derived_media_root": str(materialized_root.parent / "derived_media"),
            "analysis_root": str(
                materialized_root.parent.parent / "artifacts" / "analysis"
            ),
            "prediction_root": str(
                materialized_root.parent.parent / "artifacts" / "predictions"
            ),
            "tribe_cache_root": str(
                materialized_root.parent.parent / "artifacts" / "tmp" / "tribe_cache"
            ),
        },
        "tasks": [
            {
                "task_id": "ibc_biological_motion",
                "priority": "wave1",
                "family": "motion",
                "readiness": "ready_now",
                "source_subdir": "BiologicalMotion",
                "modality": {
                    "source": "video",
                    "preferred_tribe_input": "video_path",
                },
                "source_assets": {"root": str(source_root)},
                "ingestion": {
                    "source_glob": str(
                        source_root / "video_annotations" / "biomo_type*.mp4"
                    ),
                    "manifest_path": str(manifest_path),
                    "materialized_root": str(materialized_root),
                    "note": "upgrade later to condition-resolved renderings from walkerdata.mat if finer contrasts are needed",
                },
                "contrasts": [
                    {
                        "contrast_id": "intact_motion_vs_scrambled_motion",
                        "positive_conditions": ["intact_biological_motion"],
                        "negative_conditions": ["spatial_or_phase_scrambled_motion"],
                    },
                    {
                        "contrast_id": "biological_motion_type1_vs_type2",
                        "positive_conditions": ["biomo_type1"],
                        "negative_conditions": ["biomo_type2"],
                    },
                ],
                "expected_rois": [
                    "hMT_plus_V5",
                    "posterior_superior_temporal_sulcus",
                    "extrastriate_body_area",
                ],
                "br_kg_tags": [
                    "biological_motion",
                    "motion_localizer",
                    "social_perception",
                ],
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _synthetic_walker(phase_shift: float) -> np.ndarray:
    frames = 32
    markers = 11
    time = np.linspace(0.0, 2.0 * np.pi, frames, endpoint=False)
    walker = np.zeros((frames, markers, 3), dtype=np.float32)
    for marker in range(markers):
        offset = phase_shift + (marker * 0.25)
        walker[:, marker, 0] = np.sin(time + offset) * (marker + 1)
        walker[:, marker, 1] = np.cos(time + offset) * (marker + 1) * 0.5
        walker[:, marker, 2] = np.sin((time * 2.0) + offset) * 0.25 + marker
    return walker


def test_materialize_biological_motion_generates_manifest_and_videos(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "public_protocols" / "BiologicalMotion"
    protocol_root = source_root / "protocol"
    protocol_root.mkdir(parents=True)
    manifest_path = (
        tmp_path / "project" / "manifests" / "ibc_biological_motion_manifest.json"
    )
    materialized_root = (
        tmp_path / "project" / "inputs" / "materialized" / "ibc_biological_motion"
    )
    config_path = tmp_path / "tribe_stimulus_library.yaml"
    _write_config(config_path, source_root, manifest_path, materialized_root)

    walkerdata = np.empty((3,), dtype=object)
    walkerdata[0] = _synthetic_walker(0.0)
    walkerdata[1] = _synthetic_walker(0.3)
    walkerdata[2] = _synthetic_walker(0.6)
    savemat(protocol_root / "walkerdata.mat", {"walkerdata": walkerdata})

    exit_code = main(
        [
            "--stimulus-library",
            str(config_path),
            "--duration-seconds",
            "1.0",
            "--fps",
            "8",
            "--frame-width",
            "128",
            "--frame-height",
            "128",
            "--dot-radius",
            "3",
            "--seed",
            "11",
        ]
    )

    assert exit_code == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest["items"]
    assert manifest["task_id"] == "ibc_biological_motion"
    assert manifest["source_subdir"] == "BiologicalMotion"
    assert manifest["preferred_tribe_input"] == "video_path"
    assert manifest["item_count"] == 12
    assert manifest["condition_counts"] == {
        "intact_biological_motion": 2,
        "spatial_or_phase_scrambled_motion": 4,
        "biomo_type1": 2,
        "biomo_type2": 4,
    }
    assert len(items) == 12
    assert {item["condition"] for item in items} == {
        "intact_biological_motion",
        "spatial_or_phase_scrambled_motion",
        "biomo_type1",
        "biomo_type2",
    }
    for item in items:
        assert Path(item["tribe_args"]["video_path"]).exists()
        assert Path(item["source"]["path"]).exists()
        assert Path(item["video_path"]).exists()
        assert Path(item["frame_dir"]).exists()
        assert item["labels"]["run_type"] in {"1", "2"}


def test_materialize_biological_motion_can_disable_legacy_labels(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "public_protocols" / "BiologicalMotion"
    protocol_root = source_root / "protocol"
    protocol_root.mkdir(parents=True)
    manifest_path = (
        tmp_path / "project" / "manifests" / "ibc_biological_motion_manifest.json"
    )
    materialized_root = (
        tmp_path / "project" / "inputs" / "materialized" / "ibc_biological_motion"
    )
    config_path = tmp_path / "tribe_stimulus_library.yaml"
    _write_config(config_path, source_root, manifest_path, materialized_root)

    walkerdata = np.empty((3,), dtype=object)
    walkerdata[0] = _synthetic_walker(0.0)
    walkerdata[1] = _synthetic_walker(0.2)
    walkerdata[2] = _synthetic_walker(0.4)
    savemat(protocol_root / "walkerdata.mat", {"walkerdata": walkerdata})

    exit_code = main(
        [
            "--stimulus-library",
            str(config_path),
            "--duration-seconds",
            "0.5",
            "--fps",
            "6",
            "--frame-width",
            "96",
            "--frame-height",
            "96",
            "--dot-radius",
            "2",
            "--no-emit-legacy-biomo-types",
        ]
    )

    assert exit_code == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    conditions = {item["condition"] for item in manifest["items"]}
    assert "biomo_type1" not in conditions
    assert "biomo_type2" not in conditions
    assert manifest["item_count"] == 6
    assert "biomo_type1" not in manifest["condition_counts"]
    assert "biomo_type2" not in manifest["condition_counts"]


def test_materialize_biological_motion_clears_stale_frames_on_rerun(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "public_protocols" / "BiologicalMotion"
    protocol_root = source_root / "protocol"
    protocol_root.mkdir(parents=True)
    manifest_path = (
        tmp_path / "project" / "manifests" / "ibc_biological_motion_manifest.json"
    )
    materialized_root = (
        tmp_path / "project" / "inputs" / "materialized" / "ibc_biological_motion"
    )
    config_path = tmp_path / "tribe_stimulus_library.yaml"
    _write_config(config_path, source_root, manifest_path, materialized_root)

    walkerdata = np.empty((3,), dtype=object)
    walkerdata[0] = _synthetic_walker(0.0)
    walkerdata[1] = _synthetic_walker(0.3)
    walkerdata[2] = _synthetic_walker(0.6)
    savemat(protocol_root / "walkerdata.mat", {"walkerdata": walkerdata})

    assert (
        main(
            [
                "--stimulus-library",
                str(config_path),
                "--duration-seconds",
                "1.0",
                "--fps",
                "8",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--stimulus-library",
                str(config_path),
                "--duration-seconds",
                "0.5",
                "--fps",
                "8",
            ]
        )
        == 0
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    intact_item = next(
        item
        for item in manifest["items"]
        if item["item_id"] == "intact_biological_motion_az090"
    )
    frame_dir = Path(intact_item["frame_dir"])
    assert intact_item["n_frames"] == 4
    assert len(sorted(frame_dir.glob("*.png"))) == 4
