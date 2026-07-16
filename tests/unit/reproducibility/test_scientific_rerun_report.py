from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILDER_PATH = REPO_ROOT / "scripts" / "ci" / "build_scientific_rerun_report.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "scheduled-scientific-rerun.yml"


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("scientific_rerun_report", BUILDER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def builder() -> ModuleType:
    return _load_builder()


def _write(path: Path, content: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _write_json(path: Path, payload: Any) -> Path:
    return _write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _init_repo(repo: Path, tracked_paths: list[str]) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "--", *tracked_paths], cwd=repo, check=True)


def _manifest_entry(builder: ModuleType, pack_root: Path, relative_path: str) -> dict[str, Any]:
    path = pack_root / relative_path
    return {
        "path": relative_path,
        "sha256": f"sha256:{builder.sha256_file(path)}",
        "size_bytes": path.stat().st_size,
    }


def _a1_fixture(builder: ModuleType, root: Path) -> dict[str, Path]:
    repo = root / "repo"
    pack = repo / "reproducibility" / "bounded_autoresearch_a1"
    digest = "a" * 64
    lock = _write(pack / "requirements-py311.lock", "numpy==1.0\n")
    _write(
        pack / "scripts" / "fetch_fc_features.py",
        "\n".join(
            (
                'DEFAULT_URL = "https://example.invalid/features.tar.gz"',
                f'ARCHIVE_SHA256 = "{digest}"',
                "EXPECTED_TERM_FILES = 76",
                "",
            )
        ),
    )
    _write(pack / "artifacts" / "liu_component_behavior_residualised_cognition.csv", "y\n1\n")
    _write_json(pack / "manifests" / "fold_manifest.json", {"folds": []})
    _write_json(pack / "manifests" / "liu_component_target_manifest.json", {"targets": []})
    terms = pack / "inputs" / "liu_fc_pyspi_terms"
    for index in range(76):
        _write(terms / f"term_{index}_iu.h5", f"h5-{index}".encode())
        _write_json(terms / f"term_{index}_iu.meta.json", {"term_name": f"term-{index}"})

    manifest_paths = (
        "requirements-py311.lock",
        "artifacts/liu_component_behavior_residualised_cognition.csv",
        "manifests/fold_manifest.json",
        "manifests/liu_component_target_manifest.json",
    )
    _write_json(
        pack / "manifest.json",
        {
            "artifacts": [
                _manifest_entry(builder, pack, relative_path)
                for relative_path in manifest_paths
            ],
            "pack_id": "bounded_autoresearch_a1",
        },
    )
    _init_repo(repo, [lock.relative_to(repo).as_posix()])

    raw = root / "raw"
    _write_json(
        raw / "result.json",
        {
            "aggregate_mean_r": 0.150847,
            "n_terms_available": 76,
            "per_component": [
                {"component": "ICA_Cognition", "fold_mean_r": 0.183158}
            ],
            "status": "ok",
        },
    )
    stdout = _write(root / "stdout.log", f"[fetch] sha256 OK ({digest[:16]}…)\n")
    stderr = _write(root / "stderr.log", "")
    freeze = _write(root / "pip-freeze.txt", "numpy==1.0\npip==25.0\n")
    return {
        "repo": repo,
        "raw": raw,
        "stdout": stdout,
        "stderr": stderr,
        "freeze": freeze,
    }


def _claim_fixture(builder: ModuleType, root: Path) -> dict[str, Path]:
    repo = root / "repo"
    lock = _write(
        repo / "reproducibility" / "auditable_claim_record" / "constraints-py311.txt",
        "numpy==1.0\n",
    )
    source_dir = repo / "data" / "neurosynth_nimare" / "neurosynth_v7"
    source_file = _write(source_dir / "coordinates.tsv.gz", b"coordinates")
    source_manifest_path = _write_json(
        source_dir / "source_manifest.json",
        {
            "files": [
                {
                    "filename": source_file.name,
                    "sha256": builder.sha256_file(source_file),
                    "size_bytes": source_file.stat().st_size,
                }
            ],
            "schema_version": "brain-researcher.neurosynth-source-manifest.v1",
        },
    )
    dataset = _write(
        repo / "data" / "neurosynth_nimare" / "neurosynth_dataset_v7.pkl",
        b"converted-dataset",
    )
    provenance_path = _write_json(
        dataset.with_name(dataset.name + ".provenance.json"),
        {
            "artifact": {
                "filename": dataset.name,
                "sha256": builder.sha256_file(dataset),
                "size_bytes": dataset.stat().st_size,
            },
            "source_manifest": {
                "filename": source_manifest_path.name,
                "sha256": builder.sha256_file(source_manifest_path),
            },
        },
    )
    _init_repo(repo, [lock.relative_to(repo).as_posix()])

    record = root / "raw" / "record"
    commitment_hash = "commitment-123"
    _write(record / "README.md", "# Generated record\n")
    _write_json(
        record / "claim_card.json",
        {"commitment_hash": commitment_hash, "status": "supported_within_scope"},
    )
    _write_json(
        record / "commitment_card.json",
        {
            "commitment_hash": commitment_hash,
            "evidence_engine": {"name": "nimare", "version": "0.test"},
        },
    )
    _write_json(
        record / "evidence_verdicts.json",
        {
            "forward_default": {
                "raw": {"n_studies": 12},
                "status": "supported_within_scope",
            },
            "forward_strict": {
                "raw": {"n_studies": 12},
                "status": "supported_within_scope",
            },
            "network_coactivation": {
                "raw": {"n_joint": 3},
                "status": "supported_within_scope",
            },
            "specificity_excluding_rivals": {
                "raw": {"n_specific": 4},
                "status": "supported_within_scope",
            },
        },
    )
    _write_json(
        record / "demo_bundle.json",
        {
            "corpus_ref": {
                "verified_source": {"manifest_sha256": builder.sha256_file(source_manifest_path)}
                | {
                    "converted_provenance_sha256": builder.sha256_file(
                        provenance_path
                    )
                }
            }
        },
    )
    stdout = _write(root / "stdout.log", "OK: claim -> grounded evidence\n")
    stderr = _write(root / "stderr.log", "")
    freeze = _write(root / "pip-freeze.txt", "nimare==0.test\npip==25.0\n")
    return {
        "repo": repo,
        "raw": root / "raw",
        "stdout": stdout,
        "stderr": stderr,
        "freeze": freeze,
    }


def _build(
    builder: ModuleType,
    fixture: dict[str, Path],
    artifact_dir: Path,
    *,
    pack_id: str,
    exit_code: int,
) -> dict[str, Any]:
    return builder.build_report(
        pack_id=pack_id,
        repo_root=fixture["repo"],
        artifact_dir=artifact_dir,
        raw_output_dir=fixture["raw"],
        stdout_path=fixture["stdout"],
        stderr_path=fixture["stderr"],
        exit_code=exit_code,
        source_commit="1" * 40,
        pip_freeze_path=fixture["freeze"],
    )


def test_successful_a1_report_is_deterministic_and_scientifically_explicit(
    builder: ModuleType, tmp_path: Path
) -> None:
    fixture = _a1_fixture(builder, tmp_path / "fixture")
    first = _build(
        builder,
        fixture,
        tmp_path / "artifact-one",
        pack_id="bounded_autoresearch_a1",
        exit_code=0,
    )
    second = _build(
        builder,
        fixture,
        tmp_path / "artifact-two",
        pack_id="bounded_autoresearch_a1",
        exit_code=0,
    )

    assert first == second
    assert first["executed"] is True
    assert first["integrity_verified"] is True
    assert first["scientifically_reproduced"] is True
    assert first["environment"]["python"]["version"].count(".") == 2
    assert first["environment"]["runner"]["architecture"]
    assert first["environment"]["runner"]["platform_system"]
    assert first["environment"]["runner"]["os_release"]
    assert first["comparison"]["all_passed"] is True
    numeric_check = next(
        row
        for row in first["comparison"]["checks"]
        if row["name"] == "ICA_Cognition.fold_mean_r"
    )
    assert numeric_check["expected"] == 0.183158
    assert numeric_check["observed"] == 0.183158
    assert numeric_check["tolerance"] == {"absolute_exclusive": 0.0001}
    artifact = tmp_path / "artifact-one"
    assert (artifact / "source-commit.txt").read_text().strip() == "1" * 40
    assert (artifact / "environment" / "requirements-py311.lock").is_file()
    assert (artifact / "environment" / "pip-freeze.txt").is_file()
    assert (artifact / "source-manifest.json").is_file()
    assert (artifact / "input-manifest.json").is_file()
    assert (artifact / "comparison.json").is_file()
    assert not list(artifact.rglob("term_*_iu.h5")), "large inputs must not be copied"


def test_successful_claim_report_requires_integrity_and_comparison(
    builder: ModuleType, tmp_path: Path
) -> None:
    fixture = _claim_fixture(builder, tmp_path / "fixture")
    report = _build(
        builder,
        fixture,
        tmp_path / "artifact",
        pack_id="auditable_claim_record",
        exit_code=0,
    )

    assert report["executed"] is True
    assert report["integrity_verified"] is True
    assert report["integrity"]["checks"]["record_source_binding_verified"] is True
    assert report["scientifically_reproduced"] is True
    assert report["integrity"]["source"]["verified"] is True
    assert report["comparison"]["all_passed"] is True


def test_failed_execution_stays_distinct_from_valid_evidence(
    builder: ModuleType, tmp_path: Path
) -> None:
    fixture = _a1_fixture(builder, tmp_path / "fixture")
    report = _build(
        builder,
        fixture,
        tmp_path / "artifact",
        pack_id="bounded_autoresearch_a1",
        exit_code=7,
    )

    assert report["execution"]["attempted"] is True
    assert report["execution"]["exit_code"] == 7
    assert report["executed"] is False
    assert report["integrity_verified"] is True
    assert report["comparison"]["all_passed"] is True
    assert report["scientifically_reproduced"] is False


def test_missing_outputs_still_emit_report_without_claiming_reproduction(
    builder: ModuleType, tmp_path: Path
) -> None:
    fixture = _claim_fixture(builder, tmp_path / "fixture")
    (fixture["raw"] / "record" / "claim_card.json").unlink()
    artifact = tmp_path / "artifact"
    report = _build(
        builder,
        fixture,
        artifact,
        pack_id="auditable_claim_record",
        exit_code=0,
    )

    assert report["executed"] is True
    assert report["integrity_verified"] is False
    assert report["scientifically_reproduced"] is False
    assert report["comparison"]["all_passed"] is False
    assert "raw_outputs/record/claim_card.json" in report["missing_artifacts"]
    saved = json.loads((artifact / "scientific-rerun-report.json").read_text())
    assert saved == report


def test_main_returns_nonzero_after_writing_a_failed_report(
    builder: ModuleType, tmp_path: Path
) -> None:
    fixture = _claim_fixture(builder, tmp_path / "fixture")
    (fixture["raw"] / "record" / "claim_card.json").unlink()
    artifact = tmp_path / "artifact"

    exit_code = builder.main(
        [
            "--pack-id",
            "auditable_claim_record",
            "--repo-root",
            str(fixture["repo"]),
            "--artifact-dir",
            str(artifact),
            "--raw-output-dir",
            str(fixture["raw"]),
            "--stdout",
            str(fixture["stdout"]),
            "--stderr",
            str(fixture["stderr"]),
            "--exit-code",
            "0",
            "--source-commit",
            "1" * 40,
            "--pip-freeze",
            str(fixture["freeze"]),
        ]
    )

    assert exit_code == 1
    report = json.loads((artifact / "scientific-rerun-report.json").read_text())
    assert report["executed"] is True
    assert report["scientifically_reproduced"] is False


def test_tampered_bundle_source_hash_fails_scientific_comparison(
    builder: ModuleType, tmp_path: Path
) -> None:
    fixture = _claim_fixture(builder, tmp_path / "fixture")
    bundle_path = fixture["raw"] / "record" / "demo_bundle.json"
    bundle = json.loads(bundle_path.read_text())
    bundle["corpus_ref"]["verified_source"]["manifest_sha256"] = "0" * 64
    _write_json(bundle_path, bundle)

    report = _build(
        builder,
        fixture,
        tmp_path / "artifact",
        pack_id="auditable_claim_record",
        exit_code=0,
    )

    assert report["executed"] is True
    assert report["integrity_verified"] is False
    assert report["integrity"]["checks"]["record_source_binding_verified"] is False
    assert report["comparison"]["all_passed"] is False
    assert report["scientifically_reproduced"] is False
    hash_check = next(
        row
        for row in report["comparison"]["checks"]
        if row["name"] == "source_manifest_sha256_bound"
    )
    assert hash_check["passed"] is False


def test_empty_required_verdict_fails_scientific_comparison(
    builder: ModuleType, tmp_path: Path
) -> None:
    fixture = _claim_fixture(builder, tmp_path / "fixture")
    verdict_path = fixture["raw"] / "record" / "evidence_verdicts.json"
    verdicts = json.loads(verdict_path.read_text())
    verdicts["network_coactivation"] = {}
    _write_json(verdict_path, verdicts)

    report = _build(
        builder,
        fixture,
        tmp_path / "artifact",
        pack_id="auditable_claim_record",
        exit_code=0,
    )

    assert report["executed"] is True
    assert report["integrity_verified"] is True
    assert report["integrity"]["checks"]["record_source_binding_verified"] is True
    assert report["comparison"]["all_passed"] is False
    assert report["scientifically_reproduced"] is False
    verdict_checks = {
        row["name"]: row["passed"] for row in report["comparison"]["checks"]
    }
    assert verdict_checks["network_coactivation.nonempty"] is False
    assert verdict_checks["network_coactivation.status"] is False
    assert verdict_checks["network_coactivation.raw_nonempty"] is False


def test_workflow_is_scheduled_manual_small_and_fail_after_upload() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)

    assert set(workflow["on"]) == {"schedule", "workflow_dispatch"}
    assert workflow["on"]["schedule"] == [{"cron": "17 9 * * 1"}]
    assert "pull_request" not in text
    assert "push:" not in text
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["rerun-public-pack"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert "runner." not in json.dumps(job.get("env", {})), (
        "the runner context is unavailable in job-level env"
    )
    matrix = job["strategy"]["matrix"]
    assert matrix == {
        "pack_id": ["bounded_autoresearch_a1", "auditable_claim_record"]
    }
    assert "secrets." not in text

    expected_actions = (
        "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2",
        "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6.2.0",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1",
    )
    assert all(action in text for action in expected_actions)
    checkout_step = next(
        step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout_step["with"]["persist-credentials"] == "false"
    assert "bash reproducibility/bounded_autoresearch_a1/run_end_to_end.sh" in text
    assert "bash reproducibility/auditable_claim_record/run_end_to_end.sh" in text
    assert "retention-days: 30" in text
    assert "path: ${{ env.RUN_ROOT }}" in text
    assert 'run_root="${RUNNER_TEMP}/scientific-rerun/${{ matrix.pack_id }}"' in text
    assert '>> "${GITHUB_ENV}"' in text
    assert "inputs/liu_fc_pyspi_terms" not in text

    report_index = text.index("- name: Build the evidence report")
    upload_index = text.index("- name: Upload the small evidence bundle")
    final_index = text.index("- name: Propagate the saved rerun status")
    assert report_index < upload_index < final_index
    assert text.count("if: ${{ always() }}") == 3
    assert 'cat "${RUN_ROOT}/exit-code.txt"' in text
