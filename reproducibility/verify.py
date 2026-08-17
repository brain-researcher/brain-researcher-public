#!/usr/bin/env python3
"""Portable verifier for Brain Researcher reproducibility packs.

Given a pack directory, verify that the shipped artifacts match the sha256
checksums recorded at production time — i.e. that the bytes a reviewer holds are
the bytes the recorded result was computed from.

The report keeps three claims separate:

``integrity_verified``
    ``True`` only when every manifest entry is checksum-verifiable and matches,
    ``False`` for a mismatch or missing file, and ``None`` when any entry is
    indeterminate.
``executed``
    ``True`` only when a runnable execution pack records a completed execution.
``scientifically_reproduced``
    ``True`` only when an execution pack explicitly records that outcome and
    both execution and produced-artifact integrity succeeded.

Two modes are auto-detected:
  1. If the pack has ``execution_pack/run_pack.py`` (an emitted runnable pack),
     delegate to ``python execution_pack/run_pack.py --verify`` (which re-runs +
     diffs produced vs expected). Falls through to mode 2 if that pack has no
     expected_artifacts.json.
  2. Otherwise re-hash the entries in the pack's ``manifest.json`` against the
     shipped files.

Manifest entry: {"path": "<pack-relative>", "sha256": "sha256:<hex>",
                 "schema_only": <bool, optional>}. ``schema_only`` entries are
provenance keys whose bytes are NOT shipped (e.g. large NIfTI statmaps in a
synthetic schema exemplar). They are reported as ``indeterminate`` and prevent
the verifier from claiming complete integrity.

The deprecated ``reproduced`` field remains as an alias for
``scientifically_reproduced`` so old consumers do not mistake checksum success
for an analysis rerun.

Exit codes: 0 requested verification succeeded · 1 mismatch/failure ·
2 verification incomplete or unavailable.
With ``--all``, exit 1 takes precedence over exit 2; exit 2 means that at
least one pack is incomplete and none failed.
Stdlib only — a pack must verify in a bare clone with no brain_researcher install.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

_MAX_MB = 512  # generous cap; packs are small. Large files -> indeterminate.
_REPORT_SCHEMA = "br.reproducibility_verification.v2"
_MANIFEST_V1 = "br.reproducibility_pack_manifest.v1"
_MANIFEST_V2 = "br.reproducibility_pack_manifest.v2"
_MANIFEST_SCHEMA_REF = "../manifest.schema.json"
_ATTESTATION_LEVELS = (
    "inspectable",
    "integrity_verified",
    "public_runnable",
    "governed_rerun",
    "fully_reproduced",
)
_ATTESTATION_STATUSES = {"attained", "partial", "not_claimed"}
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_V2_ONLY_FIELDS = {
    "$schema",
    "maturity",
    "source",
    "environment_lock",
    "tools",
    "inputs",
    "seeds",
    "tolerances",
    "attestation",
}


def _sha256(path: Path) -> tuple[str | None, str]:
    if not path.exists():
        return None, "missing"
    try:
        if path.stat().st_size > _MAX_MB * 1024 * 1024:
            return None, "skipped"
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return f"sha256:{h.hexdigest()}", "ok"
    except Exception:
        return None, "error"


def _norm(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    v = value.strip().lower()
    v = v[7:] if v.startswith("sha256:") else v
    return f"sha256:{v}" if v else None


def _failure_report(reason: str, errors: list[str] | None = None) -> dict:
    return {
        "verification_schema_version": _REPORT_SCHEMA,
        "integrity_verified": False,
        "executed": False,
        "scientifically_reproduced": False,
        "reproduced": False,
        "reason": reason,
        "manifest_contract_valid": False,
        "manifest_contract_errors": errors or [],
        "n_expected": 0,
        "n_matched": 0,
        "n_mismatched": 0,
        "n_missing": 0,
        "n_indeterminate": 0,
        "artifacts": [],
    }


def _is_safe_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _resolves_within_pack(pack_dir: Path, value: object) -> bool:
    """Return whether a lexical pack-relative path also resolves inside the pack."""

    if not _is_safe_relative_path(value):
        return False
    try:
        (pack_dir / str(value)).resolve(strict=False).relative_to(pack_dir.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _validate_v2_manifest(manifest: dict, pack_dir: Path) -> list[str]:
    """Validate the stdlib-enforced v2 contract before trusting its entries.

    ``manifest.schema.json`` is the portable contract for external validators.
    This verifier deliberately implements the critical checks without a
    ``jsonschema`` dependency so a bare clone still fails closed.
    """

    errors: list[str] = []
    required = (
        "$schema",
        "schema_version",
        "pack_id",
        "pack_type",
        "maturity",
        "source",
        "environment_lock",
        "tools",
        "inputs",
        "seeds",
        "tolerances",
        "attestation",
        "artifact_count",
        "artifacts",
    )
    for key in required:
        if key not in manifest:
            errors.append(f"missing required field: {key}")

    if errors:
        return errors

    if manifest["$schema"] != _MANIFEST_SCHEMA_REF:
        errors.append(f"$schema must be {_MANIFEST_SCHEMA_REF!r}")
    if manifest["schema_version"] != _MANIFEST_V2:
        errors.append(f"schema_version must be {_MANIFEST_V2!r}")
    if manifest["pack_id"] != pack_dir.name:
        errors.append("pack_id must match the pack directory name")
    if manifest["pack_type"] not in {"recorded_result", "schema_exemplar"}:
        errors.append("pack_type must be recorded_result or schema_exemplar")
    if manifest["maturity"] not in {"stable", "historical"}:
        errors.append("maturity must be stable or historical")

    source = manifest["source"]
    if not isinstance(source, dict):
        errors.append("source must be an object")
    else:
        if not (
            isinstance(source.get("repository_url"), str)
            and source["repository_url"].startswith("https://")
        ):
            errors.append("source.repository_url must be an https URL")
        contract_commit = source.get("contract_authored_against_commit")
        if not (
            isinstance(contract_commit, str) and _COMMIT_RE.fullmatch(contract_commit)
        ):
            errors.append(
                "source.contract_authored_against_commit must be a full git SHA"
            )
        artifact_commit = source.get("artifact_authoring_commit")
        artifact_status = source.get("artifact_authoring_commit_status")
        if artifact_status not in {"recorded", "unavailable"}:
            errors.append("source.artifact_authoring_commit_status is invalid")
        elif artifact_status == "recorded" and not (
            isinstance(artifact_commit, str) and _COMMIT_RE.fullmatch(artifact_commit)
        ):
            errors.append(
                "source.artifact_authoring_commit must be a full git SHA when recorded"
            )
        elif artifact_status == "unavailable" and artifact_commit is not None:
            errors.append(
                "source.artifact_authoring_commit must be null when unavailable"
            )
        release_commit = source.get("release_containing_commit")
        release_status = source.get("release_containing_commit_status")
        if release_status not in {"recorded", "resolved_by_release_gate"}:
            errors.append("source.release_containing_commit_status is invalid")
        elif release_status == "recorded" and not (
            isinstance(release_commit, str) and _COMMIT_RE.fullmatch(release_commit)
        ):
            errors.append(
                "source.release_containing_commit must be a full git SHA when recorded"
            )
        elif (
            release_status == "resolved_by_release_gate" and release_commit is not None
        ):
            errors.append(
                "source.release_containing_commit must be null before the release gate"
            )
        expected_pack_path = f"reproducibility/{pack_dir.name}"
        if source.get("pack_path") != expected_pack_path:
            errors.append(f"source.pack_path must be {expected_pack_path!r}")
        provenance = source.get("provenance")
        if not (
            isinstance(provenance, list)
            and provenance
            and all(isinstance(item, str) and item for item in provenance)
        ):
            errors.append("source.provenance must be a non-empty string list")

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("artifacts must be a non-empty list")
        artifacts = []
    if not isinstance(manifest["artifact_count"], int) or (
        manifest["artifact_count"] != len(artifacts)
    ):
        errors.append("artifact_count must equal len(artifacts)")

    artifact_by_path: dict[str, dict] = {}
    for index, entry in enumerate(artifacts):
        if not isinstance(entry, dict):
            errors.append(f"artifacts[{index}] must be an object")
            continue
        path = entry.get("path")
        if not _is_safe_relative_path(path):
            errors.append(f"artifacts[{index}].path must be pack-relative")
            continue
        artifact_path = pack_dir / str(path)
        if artifact_path.is_symlink():
            errors.append(f"artifact {path!r} must not be a symbolic link")
            continue
        if not _resolves_within_pack(pack_dir, path):
            errors.append(f"artifact {path!r} resolves outside the pack")
            continue
        if path in artifact_by_path:
            errors.append(f"duplicate artifact path: {path}")
        artifact_by_path[path] = entry
        if entry.get("schema_only") is True:
            continue
        if not _is_sha256(entry.get("sha256") or entry.get("checksum")):
            errors.append(f"artifact {path!r} must have a full sha256 checksum")

    environment = manifest["environment_lock"]
    if not isinstance(environment, dict):
        errors.append("environment_lock must be an object")
    else:
        lock_path = environment.get("path")
        lock_hash = environment.get("sha256")
        if lock_path != "environment.lock.json":
            errors.append("environment_lock.path must be 'environment.lock.json'")
        if not _is_sha256(lock_hash):
            errors.append("environment_lock.sha256 must be a full sha256 checksum")
        if environment.get("status") not in {"locked", "unresolved_historical"}:
            errors.append("environment_lock.status is invalid")
        lock_artifact = artifact_by_path.get(str(lock_path))
        if not lock_artifact:
            errors.append("environment.lock.json must be listed as an artifact")
        elif lock_artifact.get("sha256") != lock_hash:
            errors.append("environment_lock.sha256 must match its artifact checksum")
    if "provenance_card.md" not in artifact_by_path:
        errors.append("provenance_card.md must be listed as an artifact")

    tools = manifest["tools"]
    if not isinstance(tools, list) or not tools:
        errors.append("tools must be a non-empty list")
    else:
        for index, tool in enumerate(tools):
            if not isinstance(tool, dict):
                errors.append(f"tools[{index}] must be an object")
                continue
            if not isinstance(tool.get("id"), str) or not tool["id"]:
                errors.append(f"tools[{index}].id must be non-empty")
            if not isinstance(tool.get("role"), str) or not tool["role"]:
                errors.append(f"tools[{index}].role must be non-empty")
            version_status = tool.get("version_status")
            version = tool.get("version")
            if version_status not in {"recorded", "not_recorded"}:
                errors.append(f"tools[{index}].version_status is invalid")
            elif version_status == "recorded" and not (
                isinstance(version, str) and version
            ):
                errors.append(f"tools[{index}].version is required when recorded")
            elif version_status == "not_recorded" and version is not None:
                errors.append(f"tools[{index}].version must be null when not_recorded")
            tool_path = tool.get("path")
            if tool_path is not None:
                if not _is_safe_relative_path(tool_path):
                    errors.append(f"tools[{index}].path must be pack-relative")
                    continue
                tool_artifact = artifact_by_path.get(tool_path)
                if not tool_artifact or tool_artifact.get("schema_only") is True:
                    errors.append(
                        f"tools[{index}].path must reference a shipped artifact"
                    )
                elif version_status == "recorded" and version != tool_artifact.get(
                    "sha256"
                ):
                    errors.append(
                        f"tools[{index}].version must match its artifact checksum"
                    )

    inputs = manifest["inputs"]
    if not isinstance(inputs, list) or not inputs:
        errors.append("inputs must be a non-empty list")
    else:
        availabilities = {
            "shipped",
            "public_download",
            "governed_not_shipped",
            "schema_only",
            "not_recorded",
        }
        for index, item in enumerate(inputs):
            if not isinstance(item, dict):
                errors.append(f"inputs[{index}] must be an object")
                continue
            availability = item.get("availability")
            digest = item.get("sha256")
            if not isinstance(item.get("id"), str) or not item["id"]:
                errors.append(f"inputs[{index}].id must be non-empty")
            if availability not in availabilities:
                errors.append(f"inputs[{index}].availability is invalid")
            if digest is None:
                if availability not in {"schema_only", "not_recorded"}:
                    errors.append(
                        f"inputs[{index}].sha256 is required for {availability}"
                    )
                if not isinstance(item.get("note"), str) or not item["note"]:
                    errors.append(
                        f"inputs[{index}] needs a note when sha256 is unavailable"
                    )
            elif not _is_sha256(digest):
                errors.append(f"inputs[{index}].sha256 must be a full checksum")
            if availability == "shipped":
                input_path = item.get("path")
                if not _is_safe_relative_path(input_path):
                    errors.append(
                        f"inputs[{index}].path must be pack-relative when shipped"
                    )
                    continue
                input_artifact = artifact_by_path.get(input_path)
                if not input_artifact or input_artifact.get("schema_only") is True:
                    errors.append(
                        f"inputs[{index}].path must reference a shipped artifact"
                    )
                elif digest != input_artifact.get("sha256"):
                    errors.append(
                        f"inputs[{index}].sha256 must match its artifact checksum"
                    )

    seeds = manifest["seeds"]
    if not isinstance(seeds, list) or not seeds:
        errors.append("seeds must be a non-empty list")
    else:
        for index, seed in enumerate(seeds):
            if not isinstance(seed, dict):
                errors.append(f"seeds[{index}] must be an object")
                continue
            if not isinstance(seed.get("id"), str) or not seed["id"]:
                errors.append(f"seeds[{index}].id must be non-empty")
            if not isinstance(seed.get("scope"), str) or not seed["scope"]:
                errors.append(f"seeds[{index}].scope must be non-empty")
            status = seed.get("status")
            values = seed.get("values")
            range_value = seed.get("range")
            if status not in {"recorded", "not_recorded"}:
                errors.append(f"seeds[{index}].status is invalid")
            elif status == "recorded":
                values_ok = (
                    isinstance(values, list)
                    and bool(values)
                    and all(isinstance(value, int) for value in values)
                )
                range_ok = (
                    isinstance(range_value, dict)
                    and all(
                        isinstance(range_value.get(key), int)
                        for key in ("start", "end", "step")
                    )
                    and range_value.get("step", 0) > 0
                    and range_value.get("end", -1) >= range_value.get("start", 0)
                )
                if not (values_ok or range_ok):
                    errors.append(
                        f"seeds[{index}] recorded entry needs integer values or range"
                    )

    tolerances = manifest["tolerances"]
    if not isinstance(tolerances, list) or not tolerances:
        errors.append("tolerances must be a non-empty list")
    else:
        for index, tolerance in enumerate(tolerances):
            if not isinstance(tolerance, dict):
                errors.append(f"tolerances[{index}] must be an object")
                continue
            if not isinstance(tolerance.get("id"), str) or not tolerance["id"]:
                errors.append(f"tolerances[{index}].id must be non-empty")
            if not isinstance(tolerance.get("metric"), str) or not tolerance["metric"]:
                errors.append(f"tolerances[{index}].metric must be non-empty")
            status = tolerance.get("status")
            if status not in {"recorded", "not_recorded"}:
                errors.append(f"tolerances[{index}].status is invalid")
            elif status == "recorded":
                if not isinstance(tolerance.get("expected"), int | float):
                    errors.append(
                        f"tolerances[{index}].expected must be numeric when recorded"
                    )
                absolute = tolerance.get("absolute_tolerance")
                if not isinstance(absolute, int | float) or absolute < 0:
                    errors.append(
                        f"tolerances[{index}].absolute_tolerance must be non-negative"
                    )

    attestation = manifest["attestation"]
    if not isinstance(attestation, dict):
        errors.append("attestation must be an object")
    else:
        if attestation.get("vocabulary_version") != (
            "br.reproducibility_attestation.v1"
        ):
            errors.append("attestation.vocabulary_version is invalid")
        current = attestation.get("current_level")
        levels = attestation.get("levels")
        if current not in _ATTESTATION_LEVELS:
            errors.append("attestation.current_level is invalid")
        if not isinstance(levels, dict) or set(levels) != set(_ATTESTATION_LEVELS):
            errors.append("attestation.levels must define exactly the five levels")
        else:
            for index, name in enumerate(_ATTESTATION_LEVELS):
                level = levels[name]
                if not isinstance(level, dict):
                    errors.append(f"attestation level {name} must be an object")
                    continue
                status = level.get("status")
                evidence = level.get("evidence")
                if status not in _ATTESTATION_STATUSES:
                    errors.append(f"attestation level {name} has invalid status")
                if not (
                    isinstance(evidence, list)
                    and evidence
                    and all(isinstance(item, str) and item for item in evidence)
                ):
                    errors.append(f"attestation level {name} needs non-empty evidence")
                if current in _ATTESTATION_LEVELS:
                    current_index = _ATTESTATION_LEVELS.index(current)
                    if index <= current_index and status != "attained":
                        errors.append(
                            f"attestation level {name} must be attained at or below "
                            f"current_level {current}"
                        )
                    if index > current_index and status == "attained":
                        errors.append(
                            f"attestation level {name} cannot be attained above "
                            f"current_level {current}"
                        )

    return errors


def _verify_manifest(pack_dir: Path) -> dict:
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.exists():
        return {
            "verification_schema_version": _REPORT_SCHEMA,
            "integrity_verified": None,
            "executed": False,
            "scientifically_reproduced": False,
            "reproduced": False,
            "reason": "no manifest.json",
            "artifacts": [],
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _failure_report(
            "manifest.json is unreadable or invalid JSON", [str(exc)]
        )
    if not isinstance(manifest, dict):
        return _failure_report("manifest.json must contain a JSON object")

    manifest_schema = manifest.get("schema_version")
    if manifest_schema == _MANIFEST_V2:
        try:
            contract_errors = _validate_v2_manifest(manifest, pack_dir)
        except Exception as exc:
            return _failure_report(
                "invalid v2 manifest contract",
                [f"manifest validation error: {type(exc).__name__}: {exc}"],
            )
        if contract_errors:
            return _failure_report("invalid v2 manifest contract", contract_errors)
    elif manifest_schema == _MANIFEST_V1:
        if _V2_ONLY_FIELDS.intersection(manifest):
            return _failure_report(
                "v1 manifest contains v2-only fields",
                ["v2-only fields require the v2 schema_version and contract"],
            )
    elif manifest_schema is not None:
        return _failure_report(
            "unsupported manifest schema_version",
            [f"unsupported schema_version: {manifest_schema!r}"],
        )
    elif _V2_ONLY_FIELDS.intersection(manifest):
        return _failure_report(
            "manifest with v2 fields is missing schema_version",
            ["schema_version is required when v2-only fields are present"],
        )

    entries = manifest.get("artifacts") or manifest.get("file_manifest") or []
    if not isinstance(entries, list) or not all(
        isinstance(entry, dict) for entry in entries
    ):
        return _failure_report("manifest artifact inventory must be a list of objects")
    rows = []
    n_match = n_mismatch = n_missing = n_indet = 0
    for e in entries:
        rel = e.get("path")
        expected = _norm(e.get("sha256") or e.get("checksum"))
        if not _resolves_within_pack(pack_dir, rel):
            rows.append(
                {
                    "path": rel,
                    "status": "mismatch",
                    "reason": "unsafe_path",
                    "expected": expected,
                    "observed": None,
                }
            )
            n_mismatch += 1
            continue
        if e.get("schema_only") or expected is None:
            rows.append(
                {
                    "path": rel,
                    "status": "indeterminate",
                    "reason": "schema_only" if e.get("schema_only") else "no_checksum",
                    "expected": expected,
                    "observed": None,
                }
            )
            n_indet += 1
            continue
        observed, st = _sha256(pack_dir / rel)
        if st == "missing":
            status = "missing"
            n_missing += 1
        elif st in ("skipped", "error"):
            status = "indeterminate"
            n_indet += 1
        elif _norm(observed) == expected:
            status = "match"
            n_match += 1
        else:
            status = "mismatch"
            n_mismatch += 1
        rows.append(
            {
                "path": rel,
                "status": status,
                "reason": st if status == "indeterminate" else None,
                "expected": expected,
                "observed": _norm(observed),
            }
        )
    if n_mismatch or n_missing:
        integrity_verified = False
    elif n_indet or n_match == 0:
        integrity_verified = None
    else:
        integrity_verified = True

    result = {
        "verification_schema_version": _REPORT_SCHEMA,
        "manifest_schema_version": manifest_schema,
        "integrity_verified": integrity_verified,
        "executed": False,
        "scientifically_reproduced": False,
        # Deprecated compatibility alias. Manifest hashing never establishes
        # scientific reproduction, even when every checksum matches.
        "reproduced": False,
        "n_expected": len(rows),
        "n_matched": n_match,
        "n_mismatched": n_mismatch,
        "n_missing": n_missing,
        "n_indeterminate": n_indet,
        "artifacts": rows,
    }
    if manifest_schema == _MANIFEST_V2:
        result.update(
            {
                "manifest_contract_valid": True,
                "manifest_contract_errors": [],
                "attestation": manifest["attestation"],
            }
        )
    return result


def _normalize_execution_report(raw: dict, exit_code: int) -> dict:
    """Normalize a runnable pack report without inventing execution evidence.

    Older runners only emitted ``reproduced``. A legacy ``True`` is accepted as
    evidence for all three claims because that mode historically meant rerun +
    produced-output comparison. A legacy ``False`` is a failure, but does not
    prove that execution completed.
    """

    out = dict(raw)
    legacy = raw.get("reproduced")

    integrity = raw.get("integrity_verified")
    if not isinstance(integrity, bool):
        integrity = legacy if isinstance(legacy, bool) else None

    executed = raw.get("executed")
    if not isinstance(executed, bool):
        executed = legacy is True

    scientific = raw.get("scientifically_reproduced")
    if not isinstance(scientific, bool):
        scientific = legacy is True

    scientifically_reproduced = bool(
        scientific is True and executed is True and integrity is True and exit_code == 0
    )

    out.update(
        {
            "verification_schema_version": _REPORT_SCHEMA,
            "integrity_verified": integrity,
            "executed": executed,
            "scientifically_reproduced": scientifically_reproduced,
            # Deprecated compatibility alias with the now-unambiguous meaning.
            "reproduced": scientifically_reproduced,
            "exit_code": exit_code,
            "mode": "run_pack",
        }
    )
    return out


def _verify_manifest_pack(pack_dir: Path) -> dict:
    """Verify one pack's recorded files without invoking an execution runner."""

    out = _verify_manifest(pack_dir)
    out["mode"] = "manifest"
    return out


def verify_pack(pack_dir: Path) -> dict:
    run_pack = pack_dir / "execution_pack" / "run_pack.py"
    expected = pack_dir / "execution_pack" / "expected_artifacts.json"
    if run_pack.exists() and expected.exists():
        proc = subprocess.run(
            [sys.executable, str(run_pack), "--verify"],
            cwd=str(run_pack.parent),
            capture_output=True,
            text=True,
        )
        report = pack_dir / "execution_pack" / "reproduction_report.json"
        try:
            raw = (
                json.loads(report.read_text(encoding="utf-8"))
                if report.exists()
                else {}
            )
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        return _normalize_execution_report(raw, proc.returncode)
    return _verify_manifest_pack(pack_dir)


def _verification_exit_code(result: dict) -> int:
    """Map one pack's existing verification result to its CLI exit code."""

    if result.get("mode") == "run_pack":
        if result.get("scientifically_reproduced") is True:
            return 0
        if result.get("integrity_verified") is None or result.get("exit_code") == 2:
            return 2
        return 1

    if result.get("integrity_verified") is True:
        return 0
    if result.get("integrity_verified") is None:
        return 2
    return 1


def _manifest_pack_dirs(reproducibility_dir: Path) -> list[Path]:
    """Return the immediate manifest-backed packs in stable name order."""

    return sorted(
        (
            path
            for path in reproducibility_dir.iterdir()
            if path.is_dir() and (path / "manifest.json").is_file()
        ),
        key=lambda path: path.name,
    )


def verify_all(reproducibility_dir: Path) -> tuple[dict, int]:
    """Verify every manifest-backed pack and return one compact status report."""

    packs = _manifest_pack_dirs(reproducibility_dir)
    rows: list[dict] = []
    counts = {"verified": 0, "incomplete": 0, "failed": 0}
    exit_code = 0

    for pack_dir in packs:
        # The newcomer aggregate is deliberately integrity-only. Individual
        # pack commands retain their existing ability to invoke a shipped
        # execution pack when explicitly requested.
        result = _verify_manifest_pack(pack_dir)
        pack_exit_code = _verification_exit_code(result)
        status = {0: "verified", 1: "failed", 2: "incomplete"}[pack_exit_code]
        counts[status] += 1
        # A checksum mismatch or failed execution takes precedence over an
        # otherwise expected incomplete pack such as the FitLins exemplar.
        if pack_exit_code == 1:
            exit_code = 1
        elif pack_exit_code == 2 and exit_code == 0:
            exit_code = 2
        rows.append(
            {
                "pack_id": pack_dir.name,
                "status": status,
                "exit_code": pack_exit_code,
                "integrity_verified": result.get("integrity_verified"),
                "executed": result.get("executed"),
                "scientifically_reproduced": result.get("scientifically_reproduced"),
            }
        )

    report = {
        "verification_schema_version": _REPORT_SCHEMA,
        "mode": "all_manifest_packs",
        "n_packs": len(rows),
        "summary": counts,
        "packs": rows,
    }
    if not rows:
        report["reason"] = "no manifest-backed packs found"
        report["exit_code"] = 2
        return report, 2
    report["exit_code"] = exit_code
    return report, exit_code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify a reproducibility pack.")
    ap.add_argument(
        "pack_dir",
        nargs="?",
        help="Path to a manifest-backed reproducibility/<id> directory",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Verify every immediate manifest-backed pack under reproducibility/",
    )
    args = ap.parse_args(argv)
    if args.all:
        if args.pack_dir is not None:
            ap.error("--all cannot be combined with pack_dir")
        report, exit_code = verify_all(Path(__file__).resolve().parent)
        print(json.dumps(report, indent=2))
        return exit_code
    if args.pack_dir is None:
        ap.error("provide pack_dir or use --all")
    pack = Path(args.pack_dir)
    if not pack.is_dir():
        print(f"not a directory: {pack}", file=sys.stderr)
        return 2
    result = verify_pack(pack)
    print(json.dumps(result, indent=2))
    return _verification_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
