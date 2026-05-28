from __future__ import annotations

import json
from pathlib import Path

from scripts.tribe_closed_loop.validate_artifact_root import main


def _write_config(
    path: Path,
    project_root: Path,
    data_root: Path,
    source_root: Path,
    *,
    materialized_library_root: Path | None = None,
    manifests_root: Path | None = None,
    derived_media_root: Path | None = None,
    analysis_root: Path | None = None,
    prediction_root: Path | None = None,
    tribe_cache_root: Path | None = None,
) -> None:
    payload = {
        "brain_researcher_paths": {
            "data_root": str(data_root),
            "project_root": str(project_root),
            "source_checkout_root": str(source_root),
            "materialized_library_root": str(
                materialized_library_root or (project_root / "inputs" / "materialized")
            ),
            "manifests_root": str(manifests_root or (project_root / "manifests")),
            "derived_media_root": str(
                derived_media_root or (project_root / "inputs" / "derived_media")
            ),
            "analysis_root": str(
                analysis_root or (project_root / "artifacts" / "analysis")
            ),
            "prediction_root": str(
                prediction_root or (project_root / "artifacts" / "predictions")
            ),
            "tribe_cache_root": str(
                tribe_cache_root or (project_root / "artifacts" / "tmp" / "tribe_cache")
            ),
        },
        "tasks": [],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_validate_artifact_root_passes_for_canonical_layout(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    source_root = data_root / "inputs" / "public_protocols"
    closed_loop_root = project_root / "artifacts" / "closed_loop"
    closed_loop_root.mkdir(parents=True)
    ledger_path = closed_loop_root / "tribe_hypothesis_ledger.jsonl"
    ledger_path.write_text(
        json.dumps({"hypothesis_id": "hyp_001"}) + "\n", encoding="utf-8"
    )
    (closed_loop_root / "state.json").write_text(
        json.dumps(
            {
                "ledger_path": str(ledger_path),
                "manifest_path": str(
                    project_root / "manifests" / "ibc_biological_motion_manifest.json"
                ),
                "source_root": str(source_root),
            }
        ),
        encoding="utf-8",
    )

    config_path = tmp_path / "tribe_stimulus_library.yaml"
    _write_config(config_path, project_root, data_root, source_root)

    assert main(["--stimulus-library", str(config_path), "--json"]) == 0


def test_validate_artifact_root_flags_stray_ledger(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    source_root = data_root / "inputs" / "public_protocols"
    closed_loop_root = project_root / "artifacts" / "closed_loop"
    closed_loop_root.mkdir(parents=True)
    (closed_loop_root / "tribe_hypothesis_ledger.jsonl").write_text(
        json.dumps({"hypothesis_id": "hyp_001"}) + "\n",
        encoding="utf-8",
    )
    (project_root / "tribe_hypothesis_ledger.jsonl").parent.mkdir(
        parents=True, exist_ok=True
    )
    (project_root / "tribe_hypothesis_ledger.jsonl").write_text(
        json.dumps({"hypothesis_id": "hyp_wrong"}) + "\n",
        encoding="utf-8",
    )

    config_path = tmp_path / "tribe_stimulus_library.yaml"
    _write_config(config_path, project_root, data_root, source_root)

    assert main(["--stimulus-library", str(config_path), "--json"]) == 1


def test_validate_artifact_root_flags_embedded_alias_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    source_root = data_root / "inputs" / "public_protocols"
    closed_loop_root = project_root / "artifacts" / "closed_loop"
    closed_loop_root.mkdir(parents=True)
    (closed_loop_root / "tribe_hypothesis_ledger.jsonl").write_text(
        json.dumps({"hypothesis_id": "hyp_001"}) + "\n",
        encoding="utf-8",
    )
    (closed_loop_root / "state.json").write_text(
        json.dumps(
            {
                "ledger_path": "/home/ubuntu/tribe_encoding/project/tribe_hypothesis_ledger.jsonl"
            }
        ),
        encoding="utf-8",
    )

    config_path = tmp_path / "tribe_stimulus_library.yaml"
    _write_config(config_path, project_root, data_root, source_root)

    assert (
        main(
            [
                "--stimulus-library",
                str(config_path),
                "--alias-project-root",
                "/home/ubuntu/tribe_encoding/project",
                "--json",
            ]
        )
        == 1
    )


def test_validate_artifact_root_ignores_runtime_dependency_paths(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    source_root = data_root / "inputs" / "public_protocols"
    closed_loop_root = project_root / "artifacts" / "closed_loop"
    closed_loop_root.mkdir(parents=True)
    ledger_path = closed_loop_root / "tribe_hypothesis_ledger.jsonl"
    ledger_path.write_text(
        json.dumps({"hypothesis_id": "hyp_001"}) + "\n", encoding="utf-8"
    )
    (closed_loop_root / "state.json").write_text(
        json.dumps(
            {
                "ledger_path": str(ledger_path),
                "ffmpeg_path": "/opt/conda/bin/ffmpeg",
                "runtime_tmp_dir": "/run/user/1004/tribe_tmp",
            }
        ),
        encoding="utf-8",
    )

    config_path = tmp_path / "tribe_stimulus_library.yaml"
    _write_config(config_path, project_root, data_root, source_root)

    assert main(["--stimulus-library", str(config_path), "--json"]) == 0


def test_validate_artifact_root_allows_configured_roots_outside_project_root(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    data_root = tmp_path / "data"
    source_root = data_root / "inputs" / "public_protocols"
    materialized_root = tmp_path / "shared_materialized"
    derived_media_root = tmp_path / "shared_media"
    tribe_cache_root = tmp_path / "shared_cache"
    closed_loop_root = project_root / "artifacts" / "closed_loop"
    closed_loop_root.mkdir(parents=True)
    ledger_path = closed_loop_root / "tribe_hypothesis_ledger.jsonl"
    ledger_path.write_text(
        json.dumps({"hypothesis_id": "hyp_001"}) + "\n", encoding="utf-8"
    )

    materialized_file = materialized_root / "ibc_biological_motion" / "stimuli.jsonl"
    derived_media_file = derived_media_root / "ibc_biological_motion" / "clip.mp4"
    tribe_cache_file = tribe_cache_root / "cache.sqlite"
    materialized_file.parent.mkdir(parents=True, exist_ok=True)
    derived_media_file.parent.mkdir(parents=True, exist_ok=True)
    tribe_cache_file.parent.mkdir(parents=True, exist_ok=True)
    materialized_file.write_text("", encoding="utf-8")
    derived_media_file.write_text("", encoding="utf-8")
    tribe_cache_file.write_text("", encoding="utf-8")

    (closed_loop_root / "state.json").write_text(
        json.dumps(
            {
                "ledger_path": str(ledger_path),
                "materialized_file": str(materialized_file),
                "derived_media_file": str(derived_media_file),
                "tribe_cache_file": str(tribe_cache_file),
            }
        ),
        encoding="utf-8",
    )

    config_path = tmp_path / "tribe_stimulus_library.yaml"
    _write_config(
        config_path,
        project_root,
        data_root,
        source_root,
        materialized_library_root=materialized_root,
        derived_media_root=derived_media_root,
        tribe_cache_root=tribe_cache_root,
    )

    assert main(["--stimulus-library", str(config_path), "--json"]) == 0
