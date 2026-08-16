"""Focused public-boundary checks for the shipped historical HCP drivers."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from brain_researcher.research.predictive import (
    hcp_calibration_equivalence_r2 as r2,
)
from brain_researcher.research.predictive.foundation_episode import codex_cli
from brain_researcher.research.predictive.foundation_episode.contracts import (
    build_episode_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DRIVERS = REPO_ROOT / "scripts" / "autoresearch" / "foundation_exploration"
FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "public_hcp_predictive"
    / "synthetic_governed_form_r3_source.json"
)
FROZEN_R2_SEEDS = (
    20260810,
    20260811,
    20260812,
    20260813,
    20260814,
    20260815,
    20260816,
    20260817,
    20260818,
    20260819,
)


def _driver_module(name: str) -> ModuleType:
    path = DRIVERS / name
    spec = importlib.util.spec_from_file_location(f"test_driver_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_synthetic_governed_form_r3_source(root: Path) -> Path:
    """Materialize only structural source metadata required by prepare.

    The tracked fixture contains counts and labels, not identifiers, HCP input
    rows, target values, or prediction vectors.  This temporary structure is
    sufficient because transfer-inference prepare intentionally does not read
    persisted predictions.
    """

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = root / "synthetic-r3-source"
    subject_count = int(fixture["subject_count"])
    family_count = int(fixture["family_count"])
    subject_ids = [f"synthetic-row-{index:03d}" for index in range(subject_count)]
    family_ids = [
        f"synthetic-cluster-{index:03d}" for index in range(family_count)
    ] + ["synthetic-cluster-000"]
    _write_json(
        source / "cross_component_result.json",
        {
            "phase": "AWAITING_HUMAN_SCIENTIFIC_REVIEW",
            "p_values": "not_computed",
            "scientific_acceptance": False,
            "analysis_label": "synthetic_governed_form_fixture_not_a_run",
        },
    )
    _write_json(
        source / "private" / "development_identity.json",
        {"subject_ids": subject_ids, "family_ids": family_ids},
    )
    _write_json(
        source / "private" / "development_target_snapshots.json",
        {"targets": {name: [] for name in fixture["target_names"]}},
    )
    return source


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    source = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = source + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    return env


def test_exact_mve_driver_binds_injected_runtime_to_contract_and_child_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    driver = _driver_module("run_mve24.py")
    original = {
        "binary": codex_cli.CODEX_CLI_BINARY,
        "version": codex_cli.CODEX_CLI_VERSION,
        "model": codex_cli.CODEX_CLI_MODEL,
        "reasoning": codex_cli.CODEX_CLI_REASONING_EFFORT,
    }
    for name, value in (
        ("CODEX_CLI_BINARY", original["binary"]),
        ("CODEX_CLI_VERSION", original["version"]),
        ("CODEX_CLI_MODEL", original["model"]),
        ("CODEX_CLI_REASONING_EFFORT", original["reasoning"]),
    ):
        monkeypatch.setattr(codex_cli, name, value)

    observed: dict[str, object] = {}

    def fake_preflight(request: object) -> object:
        del request
        observed["contract"] = build_episode_contract(seed=20260809)
        return type("Result", (), {"phase": "AWAITING_DISCOVERY_AUTHORIZATION", "launch_ready": True})()

    monkeypatch.setattr(driver, "run_preflight", fake_preflight)
    common = [
        "--term-cache-dir", str(tmp_path / "terms"),
        "--subject-ids", str(tmp_path / "subjects.txt"),
        "--target-table", str(tmp_path / "targets.csv"),
        "--target-manifest", str(tmp_path / "targets.json"),
        "--subject-intersection", str(tmp_path / "intersection.json"),
        "--exchangeability-manifest", str(tmp_path / "families.json"),
        "--catalog", str(tmp_path / "catalog.json"),
        "--output-dir", str(tmp_path / "bundle"),
        "--term-names-file", str(tmp_path / "terms.txt"),
        "--term-prefixes-file", str(tmp_path / "prefixes.txt"),
        "--kernel-source", str(tmp_path / "engine.py"),
        "--codex-binary", "/opt/governed/codex",
        "--codex-version", "0.146.1",
        "--codex-model", "fixture-model",
        "--codex-reasoning-effort", "fixture-effort",
    ]

    assert driver.main(["preflight", *common]) == 0
    contract = observed["contract"]
    assert isinstance(contract, dict)
    assert contract["controller"]["cli_binary"] == "/opt/governed/codex"
    assert contract["controller"]["model"] == "fixture-model"
    assert contract["controller"]["reasoning_effort"] == "fixture-effort"
    assert (
        contract["resource_tool_gate"]["controller_transport"]["cli_binary"]
        == "/opt/governed/codex"
    )
    assert codex_cli.CODEX_CLI_TIMEOUT_SECONDS == 120.0

    launch = driver.parse_args(
        [
            "launch",
            "--bundle-dir", str(tmp_path / "bundle"),
            "--authorization-path", str(tmp_path / "authorization.json"),
            "--codex-binary", "/opt/governed/codex",
            "--codex-version", "0.146.1",
            "--codex-model", "fixture-model",
            "--codex-reasoning-effort", "fixture-effort",
        ]
    )
    command = driver._supervised_worker_command(launch)
    assert command[2:4] == ["discover", "--bundle-dir"]
    assert command[-8:] == [
        "--codex-binary", "/opt/governed/codex",
        "--codex-version", "0.146.1",
        "--codex-model", "fixture-model",
        "--codex-reasoning-effort", "fixture-effort",
    ]
    with pytest.raises(SystemExit):
        driver.parse_args(["preflight", *common, "--seed", "20260810"])
    assert "invalid choice" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        driver.parse_args(
            [
                "launch",
                "--bundle-dir", str(tmp_path / "bundle"),
                "--authorization-path", str(tmp_path / "authorization.json"),
                "--codex-timeout-seconds", "77",
            ]
        )
    assert "--codex-timeout-seconds" in capsys.readouterr().err


def test_exact_recovery_driver_records_injected_binary_and_version_without_release_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from brain_researcher.research.predictive.foundation_episode import recovery

    driver = _driver_module("run_mve100_recovery12.py")
    original_binary = recovery.RECOVERY_PINNED_CODEX_CLI_BINARY
    original_version = recovery.RECOVERY_PINNED_CODEX_CLI_VERSION
    original_codex_binary = codex_cli.CODEX_CLI_BINARY
    original_codex_version = codex_cli.CODEX_CLI_VERSION
    monkeypatch.setattr(recovery, "RECOVERY_PINNED_CODEX_CLI_BINARY", original_binary)
    monkeypatch.setattr(recovery, "RECOVERY_PINNED_CODEX_CLI_VERSION", original_version)
    monkeypatch.setattr(codex_cli, "CODEX_CLI_BINARY", original_codex_binary)
    monkeypatch.setattr(codex_cli, "CODEX_CLI_VERSION", original_codex_version)
    observed: dict[str, object] = {}

    def fake_prepare(*, source_bundle: Path, output_bundle: Path) -> Path:
        del source_bundle
        observed["transport"] = recovery._recovery_controller_transport()
        return output_bundle

    monkeypatch.setattr(driver, "prepare_recovery_bundle", fake_prepare)
    assert driver.main(
        [
            "preflight",
            "--source-bundle", str(tmp_path / "source"),
            "--output-dir", str(tmp_path / "recovery"),
            "--codex-binary", "/opt/governed/codex",
            "--codex-version", "0.146.1",
        ]
    ) == 0
    transport = observed["transport"]
    assert isinstance(transport, dict)
    assert transport["pinned_cli_binary"] == "/opt/governed/codex"
    assert transport["pinned_cli_version"] == "0.146.1"
    assert "pinned_cli_release" not in transport


def test_exact_r2_and_r3_prepare_paths_keep_historical_r2_seeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    r2_driver = _driver_module("run_hcp_calibration_equivalence_r2.py")
    r3_driver = _driver_module("run_hcp_cross_component_transfer_r3.py")
    observed: dict[str, object] = {}

    def fake_r2_prepare(args: object) -> dict[str, Path]:
        observed["r2_seeds"] = r2.REPEAT_SEEDS
        observed["r2_workers"] = getattr(args, "repeat_workers")
        return {
            "contract": tmp_path / "r2_contract.json",
            "splits": tmp_path / "r2_splits.json",
            "authorization": tmp_path / "authorization.template.json",
            "development_target_snapshot": tmp_path / "snapshot.json",
        }

    def fake_r3_prepare(args: object) -> dict[str, Path]:
        observed["r3_workers"] = getattr(args, "workers")
        return {
            "contract": tmp_path / "r3_contract.json",
            "splits": tmp_path / "r3_splits.json",
            "authorization_template": tmp_path / "authorization.template.json",
        }

    monkeypatch.setattr(r2_driver, "_prepare", fake_r2_prepare)
    monkeypatch.setattr(r3_driver, "_prepare", fake_r3_prepare)
    source_args = [
        "--source-bundle", str(tmp_path / "source"),
        "--nested100-result", str(tmp_path / "nested.json"),
        "--r1-result", str(tmp_path / "r1.json"),
        "--liu-frozen-contract", str(tmp_path / "liu-contract.json"),
    ]
    assert r2_driver.main(
        [
            "prepare", *source_args,
            "--liu-result", str(tmp_path / "liu-result.json"),
            "--output-dir", str(tmp_path / "r2"),
            "--repeat-workers", "2",
        ]
    ) == 0
    assert observed["r2_seeds"] == FROZEN_R2_SEEDS
    assert observed["r2_workers"] == 2
    assert not hasattr(r2, "configure_repeat_runtime")
    capsys.readouterr()
    with pytest.raises(SystemExit):
        r2_driver._parser().parse_args(
            [
                "prepare",
                *source_args,
                "--liu-result", str(tmp_path / "liu-result.json"),
                "--output-dir", str(tmp_path / "r2"),
                "--repeat-seed", "20270001",
            ]
        )
    assert "--repeat-seed" in capsys.readouterr().err

    assert r3_driver.main(
        [
            "prepare",
            "--source-bundle", str(tmp_path / "source"),
            "--r2-contract", str(tmp_path / "r2-contract.json"),
            "--r2-result", str(tmp_path / "r2-result.json"),
            "--liu-frozen-contract", str(tmp_path / "liu-contract.json"),
            "--output-dir", str(tmp_path / "r3"),
            "--workers", "2",
        ]
    ) == 0
    assert observed["r3_workers"] == 2


def test_hcp_predictive_runtime_defaults_are_frozen_across_processes() -> None:
    env = _subprocess_env()
    env["BR_HCP_CODEX_TIMEOUT_SECONDS"] = "77"
    env["BR_HCP_CODEX_VERSION_TIMEOUT_SECONDS"] = "8"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from brain_researcher.research.predictive import "
                "hcp_calibration_equivalence_r2 as r2; "
                "from brain_researcher.research.predictive.foundation_episode "
                "import codex_cli; "
                "print(json.dumps({'r2_seeds': r2.REPEAT_SEEDS, "
                "'timeout': codex_cli.CODEX_CLI_TIMEOUT_SECONDS, "
                "'version_timeout': codex_cli.CODEX_CLI_VERSION_TIMEOUT_SECONDS}))"
            ),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(completed.stdout)
    assert observed == {
        "r2_seeds": list(FROZEN_R2_SEEDS),
        "timeout": 120.0,
        "version_timeout": 10.0,
    }


def test_hcp_predictive_extra_covers_direct_runtime_imports() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        extras = tomllib.load(handle)["project"]["optional-dependencies"]
    assert extras["hcp-predictive"] == [
        "h5py>=3.8",
        "jsonschema>=4.0",
        "numpy>=1.24.0",
        "scikit-learn>=1.6",
        "torch>=2.0",
    ]


def test_exact_transfer_inference_prepare_and_validate_against_governed_form_fixture(
    tmp_path: Path,
) -> None:
    source = _write_synthetic_governed_form_r3_source(tmp_path)
    output = tmp_path / "transfer-inference"
    command = [
        sys.executable,
        str(DRIVERS / "run_hcp_cross_component_transfer_inference.py"),
        "prepare",
        "--source-r3", str(source),
        "--output-dir", str(output),
        "--draws", "99",
        "--permutation-seed", "20270003",
        "--bootstrap-seed", "20270004",
    ]
    prepared = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        check=True,
        capture_output=True,
        text=True,
    )
    assert "AWAITING_TRANSFER_INFERENCE_AUTHORIZATION" in prepared.stdout
    contract = json.loads(
        (output / "transfer_inference_contract.json").read_text(encoding="utf-8")
    )
    assert contract["permutation_sensitivity"]["seed"] == 20270003
    assert contract["bootstrap_uncertainty"]["seed"] == 20270004
    assert contract["source"]["subject_count"] == 244
    assert (output / "state.json").read_text(encoding="utf-8").find(
        '"source_predictions_read": false'
    ) >= 0

    authorization = json.loads(
        (output / "authorization.template.json").read_text(encoding="utf-8")
    )
    authorization.update(
        {
            "authorized": True,
            "authorized_by": "synthetic-fixture-authorizer",
            "conditional_sensitivity_acknowledged": True,
            "joint_exchangeability_assumption_acknowledged": True,
            "weak_fwer_only_acknowledged": True,
            "not_search_adjusted_acknowledged": True,
            "same_cohort_retrospective_acknowledged": True,
        }
    )
    _write_json(output / "authorization.json", authorization)
    validated = subprocess.run(
        [
            sys.executable,
            str(DRIVERS / "run_hcp_cross_component_transfer_inference.py"),
            "validate-authorization",
            "--output-dir", str(output),
        ],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        check=True,
        capture_output=True,
        text=True,
    )
    assert "authorization: valid" in validated.stdout
