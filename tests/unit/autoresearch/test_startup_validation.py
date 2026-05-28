from __future__ import annotations

import json
import os
from pathlib import Path

from brain_researcher.autoresearch.artifact_schema import resolve_line_paths
from brain_researcher.autoresearch.startup_validation import (
    SecretRequirement,
    validate_discovery_startup,
    validate_predictive_startup,
)


def _mkdirs(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def test_validate_predictive_startup_requires_term_cache(tmp_path: Path) -> None:
    data_root = tmp_path / "brain_researcher"
    paths = resolve_line_paths("predictive", data_root=data_root)
    _mkdirs(
        paths.line_root,
        paths.project_root,
        paths.artifact_root,
        paths.status_root,
        paths.inputs_root,
        paths.project_root / "manifests",
    )
    cache_dir = data_root / "fc_benchmarking" / "inputs" / "lane_b_cache"
    manifest_path = paths.project_root / "manifests" / "lane_b_data_manifest.json"
    manifest_path.write_text(
        json.dumps({"term_cache_dir": str(cache_dir)}, indent=2),
        encoding="utf-8",
    )

    result = validate_predictive_startup(
        paths,
        secret_requirements=(
            SecretRequirement(name="TEST_AUTORESEARCH_MISSING_SECRET"),
        ),
        env={},
    )

    codes = {issue.code for issue in result.issues}
    assert "missing_term_cache_dir" in codes
    assert "missing_secret" in codes
    assert result.passed is False


def test_validate_discovery_startup_blocks_legacy_biological_motion(tmp_path: Path) -> None:
    data_root = tmp_path / "brain_researcher"
    paths = resolve_line_paths("discovery", data_root=data_root)
    manifests_root = paths.project_root / "manifests"
    _mkdirs(
        paths.line_root,
        paths.project_root,
        paths.artifact_root,
        paths.status_root,
        paths.inputs_root,
        manifests_root,
    )
    biological_motion_manifest = manifests_root / "ibc_biological_motion_manifest.json"
    biological_motion_manifest.write_text(
        json.dumps(
            {
                "task_id": "ibc_biological_motion",
                "condition_counts": {"biomo_type1": 1, "biomo_type2": 1},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest_index = manifests_root / "wave1_manifest_index.json"
    manifest_index.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "ibc_biological_motion",
                        "manifest_path": str(biological_motion_manifest),
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = validate_discovery_startup(paths)

    assert any(
        issue.code == "biological_motion_harness_unresolved" for issue in result.issues
    )
    assert result.passed is False


def test_validate_secret_requirement_runs_validator(tmp_path: Path) -> None:
    data_root = tmp_path / "brain_researcher"
    paths = resolve_line_paths("predictive", data_root=data_root)
    cache_dir = data_root / "fc_benchmarking" / "inputs" / "lane_b_cache"
    _mkdirs(
        paths.line_root,
        paths.project_root,
        paths.artifact_root,
        paths.status_root,
        paths.inputs_root,
        paths.project_root / "manifests",
        cache_dir,
    )
    (cache_dir / "term_1_iu.h5").write_text("ok", encoding="utf-8")
    manifest_path = paths.project_root / "manifests" / "lane_b_data_manifest.json"
    manifest_path.write_text(
        json.dumps({"term_cache_dir": str(cache_dir)}, indent=2),
        encoding="utf-8",
    )

    validator = tmp_path / "validate_secret.sh"
    validator.write_text("#!/usr/bin/env bash\n[[ -n \"$HF_TOKEN\" ]]\n", encoding="utf-8")
    os.chmod(validator, 0o755)

    result = validate_predictive_startup(
        paths,
        secret_requirements=(
            SecretRequirement(
                name="HF_TOKEN",
                validator_command=(str(validator),),
            ),
        ),
        env={"HF_TOKEN": "set"},
    )

    assert result.passed is True
