#!/usr/bin/env python3
"""Build a deterministic evidence bundle for scheduled public scientific reruns."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "br.scheduled_scientific_rerun.v1"
INPUT_SCHEMA = "br.scheduled_scientific_rerun.inputs.v1"
SOURCE_SCHEMA = "br.scheduled_scientific_rerun.source.v1"
COMPARISON_SCHEMA = "br.scheduled_scientific_rerun.comparison.v1"

PACK_SPECS: dict[str, dict[str, Any]] = {
    "bounded_autoresearch_a1": {
        "lock_path": "reproducibility/bounded_autoresearch_a1/requirements-py311.lock",
        "command": (
            "BR_A1_E2E_RESULT=<artifact>/raw_outputs/result.json bash "
            "reproducibility/bounded_autoresearch_a1/run_end_to_end.sh"
        ),
        "boundary": (
            "Re-runs the public evaluator port with the shipped de-identified target "
            "and public FC features. It does not reconstruct the governed target or "
            "re-run the complete 1,000-seed confirmatory null."
        ),
    },
    "auditable_claim_record": {
        "lock_path": "reproducibility/auditable_claim_record/constraints-py311.txt",
        "command": (
            "bash reproducibility/auditable_claim_record/run_end_to_end.sh "
            "<artifact>/raw_outputs/record"
        ),
        "boundary": (
            "Re-runs the supported public NiMARE path and checks the finding plus an "
            "internally consistent record. It does not recreate a byte-identical "
            "NeuroLang reference record."
        ),
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _file_record(path: Path, display_path: str) -> dict[str, Any]:
    if not path.is_file():
        return {
            "exists": False,
            "path": display_path,
            "sha256": None,
            "size_bytes": None,
        }
    return {
        "exists": True,
        "path": display_path,
        "sha256": f"sha256:{sha256_file(path)}",
        "size_bytes": path.stat().st_size,
    }


def _artifact_record(path: Path, artifact_dir: Path) -> dict[str, Any]:
    return _file_record(path, path.relative_to(artifact_dir).as_posix())


def _repo_record(path: Path, repo_root: Path, *, role: str) -> dict[str, Any]:
    record = _file_record(path, path.relative_to(repo_root).as_posix())
    record["role"] = role
    return record


def _load_json(path: Path) -> tuple[Any | None, str | None]:
    if not path.is_file():
        return None, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, type(exc).__name__


def _is_git_tracked(repo_root: Path, relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative_path],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _copy_file_if_present(source: Path, destination: Path) -> None:
    if source.is_file() and source.resolve() != destination.resolve():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _prepare_raw_outputs(source: Path, artifact_dir: Path) -> Path:
    destination = artifact_dir / "raw_outputs"
    if source.resolve() == destination.resolve():
        destination.mkdir(parents=True, exist_ok=True)
        return destination
    if destination.exists():
        shutil.rmtree(destination)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        destination.mkdir(parents=True, exist_ok=True)
    return destination


def _directory_records(directory: Path, base: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    return [
        _file_record(path, path.relative_to(base).as_posix())
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    ]


def _tracked_environment(
    *,
    repo_root: Path,
    artifact_dir: Path,
    lock_relative_path: str,
    pip_freeze_path: Path,
) -> dict[str, Any]:
    environment_dir = artifact_dir / "environment"
    environment_dir.mkdir(parents=True, exist_ok=True)

    lock_source = repo_root / lock_relative_path
    lock_destination = environment_dir / Path(lock_relative_path).name
    _copy_file_if_present(lock_source, lock_destination)
    lock_record = _artifact_record(lock_destination, artifact_dir)
    lock_record.update(
        {
            "source_path": lock_relative_path,
            "tracked": _is_git_tracked(repo_root, lock_relative_path),
        }
    )

    freeze_destination = environment_dir / "pip-freeze.txt"
    _copy_file_if_present(pip_freeze_path, freeze_destination)
    return {
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "runner": _runner_context(),
        "tracked_lock": lock_record,
        "pip_freeze": _artifact_record(freeze_destination, artifact_dir),
    }


def _os_release() -> dict[str, str]:
    path = Path("/etc/os-release")
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return {
        key.lower(): values[key]
        for key in ("ID", "VERSION_ID", "PRETTY_NAME")
        if key in values
    }


def _runner_context() -> dict[str, Any]:
    return {
        "architecture": platform.machine(),
        "github": {
            "image_os": os.environ.get("ImageOS"),
            "image_version": os.environ.get("ImageVersion"),
            "runner_arch": os.environ.get("RUNNER_ARCH"),
            "runner_os": os.environ.get("RUNNER_OS"),
        },
        "os_release": _os_release(),
        "platform_release": platform.release(),
        "platform_system": platform.system(),
    }


def _a1_source_constants(repo_root: Path) -> dict[str, Any]:
    source_path = (
        repo_root
        / "reproducibility"
        / "bounded_autoresearch_a1"
        / "scripts"
        / "fetch_fc_features.py"
    )
    if not source_path.is_file():
        return {}
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        return {}
    wanted = {"DEFAULT_URL", "ARCHIVE_SHA256", "EXPECTED_TERM_FILES"}
    values: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in wanted:
            continue
        try:
            values[target.id] = ast.literal_eval(node.value)
        except (TypeError, ValueError):
            continue
    return values


def _build_a1_inputs(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    pack_root = repo_root / "reproducibility" / "bounded_autoresearch_a1"
    terms_dir = pack_root / "inputs" / "liu_fc_pyspi_terms"
    records = [
        _repo_record(path, repo_root, role="public_downloaded_feature")
        for path in sorted(terms_dir.glob("term_*_iu.h5"))
    ]
    records.extend(
        _repo_record(path, repo_root, role="public_downloaded_metadata")
        for path in sorted(terms_dir.glob("term_*_iu.meta.json"))
    )
    for relative_path, role in (
        (
            "artifacts/liu_component_behavior_residualised_cognition.csv",
            "shipped_deidentified_target",
        ),
        ("manifests/fold_manifest.json", "shipped_fold_manifest"),
        (
            "manifests/liu_component_target_manifest.json",
            "shipped_component_manifest",
        ),
    ):
        records.append(_repo_record(pack_root / relative_path, repo_root, role=role))
    records.sort(key=lambda row: row["path"])

    constants = _a1_source_constants(repo_root)
    expected_terms = constants.get("EXPECTED_TERM_FILES")
    h5_count = sum(row["path"].endswith("_iu.h5") for row in records)
    metadata_count = sum(row["path"].endswith("_iu.meta.json") for row in records)
    inputs = {
        "schema_version": INPUT_SCHEMA,
        "pack_id": "bounded_autoresearch_a1",
        "expected": {
            "term_h5_count": expected_terms,
            "term_metadata_count": expected_terms,
        },
        "observed": {
            "file_count": len(records),
            "term_h5_count": h5_count,
            "term_metadata_count": metadata_count,
            "total_size_bytes": sum(
                int(row["size_bytes"] or 0) for row in records
            ),
        },
        "files": records,
    }
    source = {
        "schema_version": SOURCE_SCHEMA,
        "pack_id": "bounded_autoresearch_a1",
        "source_type": "checksum_pinned_public_release_repackaged_from_osf",
        "source_url": constants.get("DEFAULT_URL"),
        "expected_archive_sha256": (
            f"sha256:{constants['ARCHIVE_SHA256']}"
            if constants.get("ARCHIVE_SHA256")
            else None
        ),
        "expected_term_files": expected_terms,
        "input_inventory_sha256": None,
    }
    return inputs, source


def _build_claim_inputs(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    source_dir = repo_root / "data" / "neurosynth_nimare" / "neurosynth_v7"
    dataset_path = (
        repo_root / "data" / "neurosynth_nimare" / "neurosynth_dataset_v7.pkl"
    )
    provenance_path = dataset_path.with_name(dataset_path.name + ".provenance.json")
    records = [
        _repo_record(path, repo_root, role="pinned_public_source")
        for path in sorted(source_dir.glob("*"))
        if path.is_file()
    ]
    records.extend(
        (
            _repo_record(dataset_path, repo_root, role="converted_corpus"),
            _repo_record(provenance_path, repo_root, role="converted_provenance"),
        )
    )
    records.sort(key=lambda row: row["path"])
    inputs = {
        "schema_version": INPUT_SCHEMA,
        "pack_id": "auditable_claim_record",
        "observed": {
            "file_count": len(records),
            "total_size_bytes": sum(
                int(row["size_bytes"] or 0) for row in records
            ),
        },
        "files": records,
    }
    upstream_path = source_dir / "source_manifest.json"
    upstream, upstream_error = _load_json(upstream_path)
    source = {
        "schema_version": SOURCE_SCHEMA,
        "pack_id": "auditable_claim_record",
        "source_type": "pinned_neurosynth_source_bundle",
        "upstream_manifest": upstream if isinstance(upstream, dict) else None,
        "upstream_manifest_error": upstream_error,
        "upstream_manifest_record": _repo_record(
            upstream_path, repo_root, role="source_manifest"
        ),
        "input_inventory_sha256": None,
    }
    return inputs, source


def _verify_pack_manifest(pack_root: Path) -> dict[str, Any]:
    manifest_path = pack_root / "manifest.json"
    manifest, error = _load_json(manifest_path)
    rows: list[dict[str, Any]] = []
    if not isinstance(manifest, dict):
        return {"error": error or "not_an_object", "files": rows, "verified": False}
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or not entries:
        return {"error": "no_artifacts", "files": rows, "verified": False}
    for entry in entries:
        if not isinstance(entry, dict):
            rows.append({"path": None, "verified": False})
            continue
        relative_path = entry.get("path")
        expected_sha = entry.get("sha256")
        expected_size = entry.get("size_bytes")
        if not isinstance(relative_path, str):
            rows.append({"path": None, "verified": False})
            continue
        path = pack_root / relative_path
        observed = _file_record(path, relative_path)
        verified = bool(
            observed["exists"]
            and observed["sha256"] == expected_sha
            and observed["size_bytes"] == expected_size
        )
        rows.append(
            {
                "expected_sha256": expected_sha,
                "expected_size_bytes": expected_size,
                "observed_sha256": observed["sha256"],
                "observed_size_bytes": observed["size_bytes"],
                "path": relative_path,
                "verified": verified,
            }
        )
    return {
        "error": None,
        "files": rows,
        "verified": bool(rows) and all(row["verified"] for row in rows),
    }


def _verify_a1_source(
    source_manifest: dict[str, Any], inputs: dict[str, Any], stdout_text: str
) -> dict[str, Any]:
    expected_terms = source_manifest.get("expected_term_files")
    observed = inputs["observed"]
    expected_digest = str(source_manifest.get("expected_archive_sha256") or "")
    digest_prefix = expected_digest.removeprefix("sha256:")[:16]
    archive_verified = bool(
        digest_prefix
        and f"[fetch] sha256 OK ({digest_prefix}" in stdout_text
    )
    checks = {
        "archive_checksum_verified_during_run": archive_verified,
        "term_h5_count_matches": (
            isinstance(expected_terms, int)
            and observed["term_h5_count"] == expected_terms
        ),
        "term_metadata_count_matches": (
            isinstance(expected_terms, int)
            and observed["term_metadata_count"] == expected_terms
        ),
        "all_input_files_hashed": bool(inputs["files"])
        and all(row["sha256"] for row in inputs["files"] if row["exists"]),
        "required_shipped_inputs_present": all(
            row["exists"]
            for row in inputs["files"]
            if row["role"].startswith("shipped_")
        ),
    }
    return {"checks": checks, "verified": all(checks.values())}


def _verify_claim_source(
    *, repo_root: Path, source_manifest: dict[str, Any]
) -> dict[str, Any]:
    source_dir = repo_root / "data" / "neurosynth_nimare" / "neurosynth_v7"
    upstream = source_manifest.get("upstream_manifest")
    rows: list[dict[str, Any]] = []
    if isinstance(upstream, dict) and isinstance(upstream.get("files"), list):
        for entry in upstream["files"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("filename"), str):
                rows.append({"path": None, "verified": False})
                continue
            path = source_dir / entry["filename"]
            observed = _file_record(path, entry["filename"])
            rows.append(
                {
                    "expected_sha256": (
                        f"sha256:{entry.get('sha256')}" if entry.get("sha256") else None
                    ),
                    "expected_size_bytes": entry.get("size_bytes"),
                    "observed_sha256": observed["sha256"],
                    "observed_size_bytes": observed["size_bytes"],
                    "path": entry["filename"],
                    "verified": bool(
                        observed["exists"]
                        and observed["sha256"] == f"sha256:{entry.get('sha256')}"
                        and observed["size_bytes"] == entry.get("size_bytes")
                    ),
                }
            )

    upstream_path = source_dir / "source_manifest.json"
    dataset_path = (
        repo_root / "data" / "neurosynth_nimare" / "neurosynth_dataset_v7.pkl"
    )
    provenance_path = dataset_path.with_name(dataset_path.name + ".provenance.json")
    provenance, provenance_error = _load_json(provenance_path)
    provenance_verified = False
    if isinstance(provenance, dict) and upstream_path.is_file() and dataset_path.is_file():
        source_ref = provenance.get("source_manifest") or {}
        artifact_ref = provenance.get("artifact") or {}
        provenance_verified = bool(
            source_ref.get("sha256") == sha256_file(upstream_path)
            and artifact_ref.get("sha256") == sha256_file(dataset_path)
            and artifact_ref.get("size_bytes") == dataset_path.stat().st_size
        )
    checks = {
        "converted_provenance_verified": provenance_verified,
        "source_files_match_manifest": bool(rows)
        and all(row["verified"] for row in rows),
        "source_manifest_loaded": isinstance(upstream, dict),
    }
    return {
        "checks": checks,
        "converted_provenance_error": provenance_error,
        "files": rows,
        "verified": all(checks.values()),
    }


def _exact_check(name: str, expected: Any, observed: Any) -> dict[str, Any]:
    return {
        "comparator": "exact",
        "expected": expected,
        "name": name,
        "observed": observed,
        "passed": observed == expected,
        "tolerance": None,
    }


def _absolute_check(
    name: str, expected: float, observed: Any, tolerance: float
) -> dict[str, Any]:
    is_number = isinstance(observed, int | float) and not isinstance(observed, bool)
    difference = abs(float(observed) - expected) if is_number else None
    return {
        "absolute_difference": difference,
        "comparator": "absolute_difference_lt",
        "expected": expected,
        "name": name,
        "observed": observed,
        "passed": bool(difference is not None and difference < tolerance),
        "tolerance": {"absolute_exclusive": tolerance},
    }


def _minimum_check(name: str, observed: Any, minimum: float) -> dict[str, Any]:
    is_number = isinstance(observed, int | float) and not isinstance(observed, bool)
    return {
        "comparator": "greater_than",
        "expected": {"minimum_exclusive": minimum},
        "name": name,
        "observed": observed,
        "passed": bool(is_number and float(observed) > minimum),
        "tolerance": {"minimum_exclusive": minimum},
    }


def _sha_binding_check(
    name: str, *, actual_path: Path, recorded_sha256: Any
) -> dict[str, Any]:
    expected = sha256_file(actual_path) if actual_path.is_file() else None
    return {
        "comparator": "exact_sha256",
        "expected": expected,
        "name": name,
        "observed": recorded_sha256,
        "passed": bool(expected and recorded_sha256 == expected),
        "tolerance": None,
    }


def _a1_comparisons(raw_outputs: Path) -> tuple[dict[str, Any], bool]:
    result, error = _load_json(raw_outputs / "result.json")
    payload = result if isinstance(result, dict) else {}
    components = payload.get("per_component")
    by_component = {
        row.get("component"): row
        for row in components
        if isinstance(row, dict) and isinstance(row.get("component"), str)
    } if isinstance(components, list) else {}
    cognition = by_component.get("ICA_Cognition") or {}
    checks = [
        _exact_check("result_status", "ok", payload.get("status")),
        _exact_check("n_terms_available", 76, payload.get("n_terms_available")),
        _absolute_check(
            "ICA_Cognition.fold_mean_r",
            0.183158,
            cognition.get("fold_mean_r"),
            0.0001,
        ),
        _absolute_check(
            "aggregate_mean_r",
            0.150847,
            payload.get("aggregate_mean_r"),
            0.0001,
        ),
    ]
    comparison = {
        "schema_version": COMPARISON_SCHEMA,
        "all_passed": all(check["passed"] for check in checks),
        "checks": checks,
        "observed_output_error": error,
        "pack_id": "bounded_autoresearch_a1",
    }
    output_complete = error is None and isinstance(result, dict)
    return comparison, output_complete


def _claim_comparisons(
    raw_outputs: Path, repo_root: Path
) -> tuple[dict[str, Any], bool]:
    record_dir = raw_outputs / "record"
    expected_files = (
        "README.md",
        "claim_card.json",
        "commitment_card.json",
        "demo_bundle.json",
        "evidence_verdicts.json",
    )
    loaded: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name in expected_files:
        if name.endswith(".json"):
            payload, error = _load_json(record_dir / name)
            loaded[name] = payload
            if error:
                errors[name] = error
        elif not (record_dir / name).is_file():
            errors[name] = "missing"

    card = loaded.get("claim_card.json")
    commitment = loaded.get("commitment_card.json")
    verdicts = loaded.get("evidence_verdicts.json")
    bundle = loaded.get("demo_bundle.json")
    card = card if isinstance(card, dict) else {}
    commitment = commitment if isinstance(commitment, dict) else {}
    verdicts = verdicts if isinstance(verdicts, dict) else {}
    bundle = bundle if isinstance(bundle, dict) else {}
    forward = verdicts.get("forward_default")
    forward = forward if isinstance(forward, dict) else {}
    raw = forward.get("raw")
    raw = raw if isinstance(raw, dict) else {}
    required_verdicts = {
        "forward_default",
        "forward_strict",
        "network_coactivation",
        "specificity_excluding_rivals",
    }
    verified_source = (bundle.get("corpus_ref") or {}).get("verified_source") or {}
    checks = [
        _exact_check(
            "claim_status", "supported_within_scope", card.get("status")
        ),
        _exact_check(
            "commitment_hash_consistent",
            True,
            bool(
                card.get("commitment_hash")
                and card.get("commitment_hash") == commitment.get("commitment_hash")
            ),
        ),
        _exact_check(
            "evidence_engine", "nimare", (commitment.get("evidence_engine") or {}).get("name")
        ),
        _minimum_check("forward_default.n_studies", raw.get("n_studies"), 0),
        _sha_binding_check(
            "source_manifest_sha256_bound",
            actual_path=(
                repo_root
                / "data"
                / "neurosynth_nimare"
                / "neurosynth_v7"
                / "source_manifest.json"
            ),
            recorded_sha256=verified_source.get("manifest_sha256"),
        ),
        _sha_binding_check(
            "converted_provenance_sha256_bound",
            actual_path=(
                repo_root
                / "data"
                / "neurosynth_nimare"
                / "neurosynth_dataset_v7.pkl.provenance.json"
            ),
            recorded_sha256=verified_source.get("converted_provenance_sha256"),
        ),
    ]
    for verdict_name in sorted(required_verdicts):
        verdict = verdicts.get(verdict_name)
        verdict = verdict if isinstance(verdict, dict) else {}
        raw_evidence = verdict.get("raw")
        checks.extend(
            (
                _exact_check(
                    f"{verdict_name}.nonempty",
                    True,
                    bool(verdict),
                ),
                _exact_check(
                    f"{verdict_name}.status",
                    "supported_within_scope",
                    verdict.get("status"),
                ),
                _exact_check(
                    f"{verdict_name}.raw_nonempty",
                    True,
                    isinstance(raw_evidence, dict) and bool(raw_evidence),
                ),
            )
        )
    comparison = {
        "schema_version": COMPARISON_SCHEMA,
        "all_passed": all(check["passed"] for check in checks),
        "checks": checks,
        "observed_output_errors": errors,
        "pack_id": "auditable_claim_record",
    }
    output_complete = not errors
    return comparison, output_complete


def _missing_artifacts(
    *,
    pack_id: str,
    environment: dict[str, Any],
    raw_outputs: Path,
    stdout_path: Path,
    stderr_path: Path,
    source_verified: bool,
) -> list[str]:
    missing: list[str] = []
    if not environment["tracked_lock"]["exists"]:
        missing.append(environment["tracked_lock"]["path"])
    if not environment["pip_freeze"]["exists"]:
        missing.append(environment["pip_freeze"]["path"])
    if not stdout_path.is_file():
        missing.append("stdout.log")
    if not stderr_path.is_file():
        missing.append("stderr.log")
    if pack_id == "bounded_autoresearch_a1":
        if not (raw_outputs / "result.json").is_file():
            missing.append("raw_outputs/result.json")
        if not source_verified:
            missing.append("verified A1 source/input contract")
    else:
        for name in (
            "README.md",
            "claim_card.json",
            "commitment_card.json",
            "demo_bundle.json",
            "evidence_verdicts.json",
        ):
            if not (raw_outputs / "record" / name).is_file():
                missing.append(f"raw_outputs/record/{name}")
        if not source_verified:
            missing.append("verified Neurosynth source/provenance contract")
    return sorted(set(missing))


def build_report(
    *,
    pack_id: str,
    repo_root: Path,
    artifact_dir: Path,
    raw_output_dir: Path,
    stdout_path: Path,
    stderr_path: Path,
    exit_code: int,
    source_commit: str,
    pip_freeze_path: Path,
) -> dict[str, Any]:
    if pack_id not in PACK_SPECS:
        raise ValueError(f"unsupported pack: {pack_id}")
    repo_root = repo_root.resolve()
    artifact_dir = artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    raw_outputs = _prepare_raw_outputs(raw_output_dir, artifact_dir)
    stdout_destination = artifact_dir / "stdout.log"
    stderr_destination = artifact_dir / "stderr.log"
    _copy_file_if_present(stdout_path, stdout_destination)
    _copy_file_if_present(stderr_path, stderr_destination)
    (artifact_dir / "source-commit.txt").write_text(
        source_commit.strip() + "\n", encoding="utf-8"
    )
    (artifact_dir / "exit-code.txt").write_text(f"{exit_code}\n", encoding="utf-8")

    spec = PACK_SPECS[pack_id]
    environment = _tracked_environment(
        repo_root=repo_root,
        artifact_dir=artifact_dir,
        lock_relative_path=spec["lock_path"],
        pip_freeze_path=pip_freeze_path,
    )
    stdout_text = (
        stdout_destination.read_text(encoding="utf-8", errors="replace")
        if stdout_destination.is_file()
        else ""
    )

    if pack_id == "bounded_autoresearch_a1":
        inputs, source_manifest = _build_a1_inputs(repo_root)
    else:
        inputs, source_manifest = _build_claim_inputs(repo_root)
    input_manifest_path = artifact_dir / "input-manifest.json"
    _write_json(input_manifest_path, inputs)
    source_manifest["input_inventory_sha256"] = f"sha256:{sha256_file(input_manifest_path)}"
    source_manifest_path = artifact_dir / "source-manifest.json"
    _write_json(source_manifest_path, source_manifest)

    if pack_id == "bounded_autoresearch_a1":
        source_verification = _verify_a1_source(
            source_manifest, inputs, stdout_text
        )
        pack_verification: dict[str, Any] | None = _verify_pack_manifest(
            repo_root / "reproducibility" / "bounded_autoresearch_a1"
        )
        comparison, raw_output_complete = _a1_comparisons(raw_outputs)
    else:
        source_verification = _verify_claim_source(
            repo_root=repo_root, source_manifest=source_manifest
        )
        pack_verification = None
        comparison, raw_output_complete = _claim_comparisons(raw_outputs, repo_root)
    comparison_path = artifact_dir / "comparison.json"
    _write_json(comparison_path, comparison)

    source_commit_valid = bool(re.fullmatch(r"[0-9a-f]{40}", source_commit.strip()))
    integrity_checks = {
        "environment_lock_is_tracked": bool(
            environment["tracked_lock"]["exists"]
            and environment["tracked_lock"]["tracked"]
        ),
        "pip_freeze_saved": bool(
            environment["pip_freeze"]["exists"]
            and environment["pip_freeze"]["size_bytes"]
        ),
        "raw_outputs_complete": raw_output_complete,
        "source_commit_is_full_sha": source_commit_valid,
        "source_inputs_verified": bool(source_verification["verified"]),
        "stderr_saved": stderr_destination.is_file(),
        "stdout_saved": stdout_destination.is_file(),
    }
    if pack_verification is not None:
        integrity_checks["tracked_pack_manifest_verified"] = bool(
            pack_verification["verified"]
        )
    else:
        binding_checks = {
            row["name"]: row["passed"]
            for row in comparison["checks"]
            if row["name"]
            in {
                "converted_provenance_sha256_bound",
                "source_manifest_sha256_bound",
            }
        }
        integrity_checks["record_source_binding_verified"] = bool(
            len(binding_checks) == 2 and all(binding_checks.values())
        )
    integrity_verified = all(integrity_checks.values())
    executed = exit_code == 0
    scientifically_reproduced = bool(
        executed and integrity_verified and comparison["all_passed"]
    )
    missing = _missing_artifacts(
        pack_id=pack_id,
        environment=environment,
        raw_outputs=raw_outputs,
        stdout_path=stdout_destination,
        stderr_path=stderr_destination,
        source_verified=bool(source_verification["verified"]),
    )

    report = {
        "schema_version": REPORT_SCHEMA,
        "pack_id": pack_id,
        "source_commit": source_commit.strip(),
        "claim_boundary": spec["boundary"],
        "executed": executed,
        "integrity_verified": integrity_verified,
        "scientifically_reproduced": scientifically_reproduced,
        "execution": {
            "attempted": True,
            "command": spec["command"],
            "exit_code": exit_code,
            "raw_outputs": _directory_records(raw_outputs, artifact_dir),
            "stderr": _artifact_record(stderr_destination, artifact_dir),
            "stdout": _artifact_record(stdout_destination, artifact_dir),
        },
        "environment": environment,
        "evidence_files": {
            "comparison": _artifact_record(comparison_path, artifact_dir),
            "exit_code": _artifact_record(
                artifact_dir / "exit-code.txt", artifact_dir
            ),
            "input_manifest": _artifact_record(input_manifest_path, artifact_dir),
            "source_commit": _artifact_record(
                artifact_dir / "source-commit.txt", artifact_dir
            ),
            "source_manifest": _artifact_record(source_manifest_path, artifact_dir),
        },
        "integrity": {
            "checks": integrity_checks,
            "pack_manifest": pack_verification,
            "source": source_verification,
        },
        "comparison": comparison,
        "missing_artifacts": missing,
    }
    _write_json(artifact_dir / "scientific-rerun-report.json", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-id", required=True, choices=sorted(PACK_SPECS))
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--raw-output-dir", required=True, type=Path)
    parser.add_argument("--stdout", required=True, type=Path)
    parser.add_argument("--stderr", required=True, type=Path)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--pip-freeze", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        pack_id=args.pack_id,
        repo_root=args.repo_root,
        artifact_dir=args.artifact_dir,
        raw_output_dir=args.raw_output_dir,
        stdout_path=args.stdout,
        stderr_path=args.stderr,
        exit_code=args.exit_code,
        source_commit=args.source_commit,
        pip_freeze_path=args.pip_freeze,
    )
    print(args.artifact_dir / "scientific-rerun-report.json")
    return 0 if report["scientifically_reproduced"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
