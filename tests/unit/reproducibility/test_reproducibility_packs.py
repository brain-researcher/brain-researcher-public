"""Regression guard for the public clone-and-verify contract."""

from __future__ import annotations

import hashlib
import json
import re
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
REPRO_ROOT = REPO_ROOT / "reproducibility"
PACKS = sorted(
    path
    for path in REPRO_ROOT.iterdir()
    if path.is_dir() and (path / "manifest.json").is_file()
)
A1_PACK = REPRO_ROOT / "bounded_autoresearch_a1"
FITLINS_PACK = REPRO_ROOT / "fitlins_multiverse_yeo17"
HCP_PACK = REPRO_ROOT / "hcp_workflow_search"
TRIBE_PACK = REPRO_ROOT / "tribe_speech_tools"
CLAIM_TUTORIAL = REPRO_ROOT / "auditable_claim_record"
VERIFY = runpy.run_path(str(REPRO_ROOT / "verify.py"))
VERIFY_MANIFEST = VERIFY["_verify_manifest"]
VERIFY_PACK = VERIFY["verify_pack"]
VERIFY_MAIN = VERIFY["main"]
VALIDATE_V2 = VERIFY["_validate_v2_manifest"]
V2_SCHEMA = "br.reproducibility_pack_manifest.v2"
LEVELS = [
    "inspectable",
    "integrity_verified",
    "public_runnable",
    "governed_rerun",
    "fully_reproduced",
]


def _checksum(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _write_manifest(pack_dir: Path, artifacts: list[dict]) -> None:
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "manifest.json").write_text(
        json.dumps({"artifacts": artifacts}), encoding="utf-8"
    )


def test_reproducibility_packs_exist() -> None:
    assert {path.name for path in PACKS} == {
        "bounded_autoresearch_a1",
        "fitlins_multiverse_yeo17",
        "hcp_workflow_search",
        "tribe_speech_tools",
    }
    assert (REPRO_ROOT / "verify.py").is_file()
    assert not (REPRO_ROOT / "packs").exists()
    assert not (REPRO_ROOT / "tutorials").exists()


def test_auditable_claim_tutorial_is_colocated() -> None:
    assert CLAIM_TUTORIAL.is_dir()
    assert not (REPO_ROOT / "examples" / "auditable_claim_record").exists()
    assert not (CLAIM_TUTORIAL / "manifest.json").exists()
    assert not (CLAIM_TUTORIAL / "provenance_card.md").exists()
    assert not (CLAIM_TUTORIAL / "environment.lock.json").exists()

    generator = (
        REPO_ROOT / "scripts" / "autoresearch" / "run_auditable_claim_demo.py"
    ).read_text(encoding="utf-8")
    assert '"cd brain-researcher-public"' in generator
    assert "constraints-py311.txt" in generator
    assert (CLAIM_TUTORIAL / "constraints-py311.txt").is_file()


def test_v2_schema_and_pack_contracts_are_present() -> None:
    schema = json.loads(
        (REPRO_ROOT / "manifest.schema.json").read_text(encoding="utf-8")
    )
    assert schema["properties"]["schema_version"]["const"] == V2_SCHEMA
    assert {
        "source",
        "maturity",
        "environment_lock",
        "tools",
        "inputs",
        "seeds",
        "tolerances",
        "attestation",
    }.issubset(schema["required"])
    assert (
        schema["$defs"]["attestation"]["properties"]["current_level"]["enum"] == LEVELS
    )

    for pack_dir in PACKS:
        manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["$schema"] == "../manifest.schema.json"
        assert manifest["schema_version"] == V2_SCHEMA
        assert VALIDATE_V2(manifest, pack_dir) == []


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda path: path.name)
def test_each_pack_has_a_bound_environment_lock(pack_dir: Path) -> None:
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    binding = manifest["environment_lock"]
    lock_path = pack_dir / binding["path"]
    assert lock_path.is_file()
    assert _checksum(lock_path.read_bytes()) == binding["sha256"]
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock["schema_version"] == "br.reproducibility_environment_lock.v1"
    assert lock["status"] == binding["status"]


def test_pack_attestations_state_the_honest_boundary() -> None:
    a1_manifest = json.loads((A1_PACK / "manifest.json").read_text(encoding="utf-8"))
    assert a1_manifest["maturity"] == "stable"
    a1 = a1_manifest["attestation"]
    assert a1["current_level"] == "public_runnable"
    assert list(a1["levels"]) == LEVELS
    assert [a1["levels"][level]["status"] for level in LEVELS] == [
        "attained",
        "attained",
        "attained",
        "partial",
        "not_claimed",
    ]

    fitlins_manifest = json.loads(
        (FITLINS_PACK / "manifest.json").read_text(encoding="utf-8")
    )
    assert fitlins_manifest["maturity"] == "historical"
    fitlins = fitlins_manifest["attestation"]
    assert fitlins["current_level"] == "inspectable"
    assert list(fitlins["levels"]) == LEVELS
    assert [fitlins["levels"][level]["status"] for level in LEVELS] == [
        "attained",
        "partial",
        "not_claimed",
        "not_claimed",
        "not_claimed",
    ]

    for pack_dir in (HCP_PACK, TRIBE_PACK):
        manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["maturity"] == "stable"
        attestation = manifest["attestation"]
        assert attestation["current_level"] == "integrity_verified"
        assert list(attestation["levels"]) == LEVELS
        assert [attestation["levels"][level]["status"] for level in LEVELS] == [
            "attained",
            "attained",
            "partial",
            "not_claimed",
            "not_claimed",
        ]


def test_a1_records_source_tools_inputs_seeds_and_tolerances() -> None:
    manifest = json.loads((A1_PACK / "manifest.json").read_text(encoding="utf-8"))
    source = manifest["source"]
    assert re.fullmatch(r"[0-9a-f]{40}", source["contract_authored_against_commit"])
    assert source["artifact_authoring_commit"] is None
    assert source["artifact_authoring_commit_status"] == "unavailable"
    assert source["release_containing_commit"] is None
    assert source["release_containing_commit_status"] == "resolved_by_release_gate"
    assert all(tool["version_status"] == "recorded" for tool in manifest["tools"])

    inputs = {item["id"]: item for item in manifest["inputs"]}
    assert inputs["public_fc_feature_archive"]["sha256"] == (
        "sha256:ac3d0f369ea99e0f7587a2bb144664a3a2ea490e7ebfafac1ecf22bf14e811f5"
    )
    assert all(
        re.fullmatch(r"sha256:[0-9a-f]{64}", item["sha256"]) for item in inputs.values()
    )

    seeds = {item["id"]: item for item in manifest["seeds"]}
    assert seeds["outer_cv_split"]["values"] == [42]
    assert seeds["inner_cv_selection"]["values"] == [42]
    assert seeds["family_block_permutation"]["range"] == {
        "start": 1,
        "end": 1000,
        "step": 1,
    }
    assert seeds["family_block_permutation"]["public_rerun_range"] == {
        "start": 1,
        "end": 30,
        "step": 1,
    }

    tolerances = {item["id"]: item for item in manifest["tolerances"]}
    assert tolerances["headline_cognition_fold_mean_r"] == {
        "id": "headline_cognition_fold_mean_r",
        "status": "recorded",
        "metric": "ICA_Cognition fold_mean_r",
        "expected": 0.183158,
        "absolute_tolerance": 0.0001,
        "comparison": "abs(observed - expected) < absolute_tolerance",
        "evidence": "run_end_to_end.sh",
    }
    assert tolerances["headline_aggregate_mean_r"]["expected"] == 0.150847
    assert tolerances["headline_aggregate_mean_r"]["absolute_tolerance"] == 0.0001


def test_navigation_distinguishes_nimare_and_historical_neurolang() -> None:
    root_readme = (REPRO_ROOT / "README.md").read_text(encoding="utf-8")
    docs = (REPO_ROOT / "docs" / "reproducibility_packs.md").read_text(encoding="utf-8")
    assert "NiMARE light path" in root_readme
    assert "`public_runnable` tutorial path" in docs
    assert "historical NeuroLang snapshot" in root_readme
    assert "`inspectable` only" in docs
    assert "## Reproduction Status Vocabulary" in docs
    assert "`hcp_workflow_search`" in root_readme
    assert "`tribe_speech_tools`" in docs


@pytest.mark.parametrize(
    "example_dir", [A1_PACK, CLAIM_TUTORIAL], ids=lambda path: path.name
)
def test_agentic_driver_resolves_repository_root(example_dir: Path) -> None:
    driver = runpy.run_path(str(example_dir / "drive_from_language.py"))
    assert driver["REPO_ROOT"] == REPO_ROOT
    assert driver["CALL_TOOL"] == REPO_ROOT / "scripts" / "mcp" / "call_http_tool.py"
    assert driver["CALL_TOOL"].is_file()


@pytest.mark.parametrize(
    ("pack_dir", "expected_exit", "integrity_verified", "n_indeterminate"),
    [
        (A1_PACK, 0, True, 0),
        (FITLINS_PACK, 2, None, 2),
        (HCP_PACK, 0, True, 0),
        (TRIBE_PACK, 0, True, 0),
    ],
    ids=[
        "bounded_autoresearch_a1",
        "fitlins_multiverse_yeo17",
        "hcp_workflow_search",
        "tribe_speech_tools",
    ],
)
def test_reproducibility_pack_reports_its_integrity_boundary(
    pack_dir: Path,
    expected_exit: int,
    integrity_verified: bool | None,
    n_indeterminate: int,
) -> None:
    proc = subprocess.run(
        [sys.executable, str(REPRO_ROOT / "verify.py"), str(pack_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert proc.returncode == expected_exit, (
        f"{pack_dir.name} failed verification (exit {proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    report = json.loads(proc.stdout)
    assert report["integrity_verified"] is integrity_verified
    assert report["executed"] is False
    assert report["scientifically_reproduced"] is False
    assert report["reproduced"] is False
    assert report["n_mismatched"] == 0
    assert report["n_missing"] == 0
    assert report["n_matched"] > 0
    assert report["n_indeterminate"] == n_indeterminate


def test_manifest_match_only_proves_integrity(tmp_path: Path) -> None:
    payload = b"recorded result\n"
    (tmp_path / "result.txt").write_bytes(payload)
    _write_manifest(tmp_path, [{"path": "result.txt", "sha256": _checksum(payload)}])

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is True
    assert report["executed"] is False
    assert report["scientifically_reproduced"] is False
    assert report["reproduced"] is False
    assert report["artifacts"][0]["status"] == "match"
    assert VERIFY_MAIN([str(tmp_path)]) == 0


def test_legacy_minimal_manifest_remains_compatible(tmp_path: Path) -> None:
    payload = b"legacy\n"
    (tmp_path / "result.txt").write_bytes(payload)
    _write_manifest(tmp_path, [{"path": "result.txt", "sha256": _checksum(payload)}])

    report = VERIFY_MANIFEST(tmp_path)

    assert report["manifest_schema_version"] is None
    assert report["integrity_verified"] is True
    assert "manifest_contract_valid" not in report


def test_explicit_v1_manifest_remains_compatible(tmp_path: Path) -> None:
    payload = b"v1\n"
    (tmp_path / "result.txt").write_bytes(payload)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "br.reproducibility_pack_manifest.v1",
                "artifacts": [{"path": "result.txt", "sha256": _checksum(payload)}],
            }
        ),
        encoding="utf-8",
    )

    report = VERIFY_MANIFEST(tmp_path)

    assert report["manifest_schema_version"] == ("br.reproducibility_pack_manifest.v1")
    assert report["integrity_verified"] is True


def test_malformed_v2_manifest_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"schema_version": V2_SCHEMA, "artifacts": []}),
        encoding="utf-8",
    )

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is False
    assert report["manifest_contract_valid"] is False
    assert report["reason"] == "invalid v2 manifest contract"
    assert "missing required field: source" in report["manifest_contract_errors"]
    assert VERIFY_MAIN([str(tmp_path)]) == 1


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"schema_version": "br.reproducibility_pack_manifest.v999"}, "unsupported"),
        (
            {"schema_version": "br.reproducibility_pack_manifest.v1"},
            "v1 manifest contains v2-only fields",
        ),
        ({"schema_version": None}, "missing schema_version"),
    ],
)
def test_v2_manifest_cannot_downgrade_to_legacy(
    tmp_path: Path, mutation: dict[str, str | None], reason: str
) -> None:
    manifest = json.loads((A1_PACK / "manifest.json").read_text(encoding="utf-8"))
    if mutation["schema_version"] is None:
        manifest.pop("schema_version")
    else:
        manifest.update(mutation)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is False
    assert reason in report["reason"]
    assert report["manifest_contract_valid"] is False


def test_malformed_v2_field_types_fail_closed_instead_of_crashing(
    tmp_path: Path,
) -> None:
    manifest = json.loads((A1_PACK / "manifest.json").read_text(encoding="utf-8"))
    manifest["pack_id"] = tmp_path.name
    manifest["source"]["pack_path"] = f"reproducibility/{tmp_path.name}"
    manifest["pack_type"] = []
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is False
    assert report["reason"] == "invalid v2 manifest contract"
    assert report["manifest_contract_errors"][0].startswith(
        "manifest validation error: TypeError:"
    )


def test_v2_manifest_rejects_unsafe_artifact_paths() -> None:
    manifest = json.loads((A1_PACK / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifacts"][0]["path"] = "../README.md"

    errors = VALIDATE_V2(manifest, A1_PACK)

    assert "artifacts[0].path must be pack-relative" in errors


def test_v2_manifest_binds_shipped_tool_and_input_checksums() -> None:
    tool_manifest = json.loads((A1_PACK / "manifest.json").read_text(encoding="utf-8"))
    tool_manifest["tools"][0]["version"] = "sha256:" + "0" * 64
    assert "tools[0].version must match its artifact checksum" in VALIDATE_V2(
        tool_manifest, A1_PACK
    )

    input_manifest = json.loads((A1_PACK / "manifest.json").read_text(encoding="utf-8"))
    shipped_index = next(
        index
        for index, item in enumerate(input_manifest["inputs"])
        if item["availability"] == "shipped"
    )
    input_manifest["inputs"][shipped_index]["sha256"] = "sha256:" + "0" * 64
    expected = f"inputs[{shipped_index}].sha256 must match its artifact checksum"
    assert expected in VALIDATE_V2(input_manifest, A1_PACK)


def test_v2_manifest_rejects_symbolic_link_artifacts(tmp_path: Path) -> None:
    outside = tmp_path.with_name(f"{tmp_path.name}-outside.txt")
    outside.write_text("outside\n", encoding="utf-8")
    (tmp_path / "escape.txt").symlink_to(outside)
    manifest = json.loads((A1_PACK / "manifest.json").read_text(encoding="utf-8"))
    manifest["pack_id"] = tmp_path.name
    manifest["source"]["pack_path"] = f"reproducibility/{tmp_path.name}"
    manifest["artifacts"][0]["path"] = "escape.txt"

    errors = VALIDATE_V2(manifest, tmp_path)

    assert "artifact 'escape.txt' must not be a symbolic link" in errors


def test_legacy_manifest_rejects_symbolic_link_escape(tmp_path: Path) -> None:
    outside = tmp_path.with_name(f"{tmp_path.name}-outside.txt")
    payload = b"outside\n"
    outside.write_bytes(payload)
    (tmp_path / "escape.txt").symlink_to(outside)
    _write_manifest(tmp_path, [{"path": "escape.txt", "sha256": _checksum(payload)}])

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is False
    assert report["artifacts"][0]["status"] == "mismatch"
    assert report["artifacts"][0]["reason"] == "unsafe_path"


def test_legacy_manifest_rejects_parent_path_escape(tmp_path: Path) -> None:
    outside = tmp_path.with_name(f"{tmp_path.name}-outside.txt")
    payload = b"outside\n"
    outside.write_bytes(payload)
    _write_manifest(
        tmp_path,
        [{"path": f"../{outside.name}", "sha256": _checksum(payload)}],
    )

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is False
    assert report["artifacts"][0]["reason"] == "unsafe_path"


def test_manifest_mismatch_fails_integrity(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text("changed\n", encoding="utf-8")
    _write_manifest(
        tmp_path,
        [{"path": "result.txt", "sha256": _checksum(b"recorded result\n")}],
    )

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is False
    assert report["scientifically_reproduced"] is False
    assert report["artifacts"][0]["status"] == "mismatch"
    assert VERIFY_MAIN([str(tmp_path)]) == 1


def test_manifest_missing_file_fails_integrity(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        [{"path": "missing.txt", "sha256": _checksum(b"recorded result\n")}],
    )

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is False
    assert report["scientifically_reproduced"] is False
    assert report["artifacts"][0]["status"] == "missing"
    assert VERIFY_MAIN([str(tmp_path)]) == 1


@pytest.mark.parametrize("hash_state", ["schema_only", "skipped", "error"])
def test_indeterminate_entry_never_claims_complete_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hash_state: str
) -> None:
    entry = {"path": "result.bin", "sha256": _checksum(b"recorded result\n")}
    if hash_state == "schema_only":
        entry = {"path": "result.bin", "schema_only": True}
    else:
        monkeypatch.setitem(
            VERIFY_MANIFEST.__globals__, "_sha256", lambda _path: (None, hash_state)
        )
    _write_manifest(tmp_path, [entry])

    report = VERIFY_MANIFEST(tmp_path)

    assert report["integrity_verified"] is None
    assert report["executed"] is False
    assert report["scientifically_reproduced"] is False
    assert report["reproduced"] is False
    assert report["n_indeterminate"] == 1
    assert report["artifacts"][0]["status"] == "indeterminate"
    assert VERIFY_MAIN([str(tmp_path)]) == 2


def test_execution_pack_can_record_scientific_reproduction(tmp_path: Path) -> None:
    execution_pack = tmp_path / "execution_pack"
    execution_pack.mkdir()
    (execution_pack / "expected_artifacts.json").write_text("{}\n", encoding="utf-8")
    (execution_pack / "run_pack.py").write_text(
        """\
import json
from pathlib import Path

Path("reproduction_report.json").write_text(json.dumps({
    "integrity_verified": True,
    "executed": True,
    "scientifically_reproduced": True,
}))
""",
        encoding="utf-8",
    )

    report = VERIFY_PACK(tmp_path)

    assert report["mode"] == "run_pack"
    assert report["exit_code"] == 0
    assert report["integrity_verified"] is True
    assert report["executed"] is True
    assert report["scientifically_reproduced"] is True
    assert report["reproduced"] is True
    assert VERIFY_MAIN([str(tmp_path)]) == 0


def test_legacy_execution_report_remains_compatible() -> None:
    report = VERIFY["_normalize_execution_report"]({"reproduced": True}, 0)

    assert report["integrity_verified"] is True
    assert report["executed"] is True
    assert report["scientifically_reproduced"] is True
    assert report["reproduced"] is True


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda path: path.name)
def test_manifest_covers_every_versioned_pack_file(pack_dir: Path) -> None:
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["artifacts"]
    assert manifest["artifact_count"] == len(entries)

    pack_rel = pack_dir.relative_to(REPO_ROOT)
    tracked_output = subprocess.check_output(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            str(pack_rel),
        ],
        cwd=REPO_ROOT,
        text=True,
    )
    tracked = {
        Path(line).relative_to(pack_rel).as_posix()
        for line in tracked_output.splitlines()
        if line
    }
    tracked -= {".gitignore", "manifest.json"}

    listed = {entry["path"] for entry in entries if not entry.get("schema_only")}
    assert listed == tracked, (
        f"manifest coverage drift for {pack_dir.name}: "
        f"unlisted={sorted(tracked - listed)}, stale={sorted(listed - tracked)}"
    )
