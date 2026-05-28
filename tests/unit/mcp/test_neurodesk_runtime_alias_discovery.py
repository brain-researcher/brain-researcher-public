from __future__ import annotations

import re
import pytest

from brain_researcher.services.mcp import server as srv
from brain_researcher.services.tools.registry import UnifiedToolRegistry


_CANONICAL_RUNTIME_TOOL_ID_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def _assert_canonical_runtime_tool_id(tool_id: str) -> None:
    normalized = str(tool_id or "").strip()
    assert normalized
    assert ".run" not in normalized
    assert _CANONICAL_RUNTIME_TOOL_ID_RE.fullmatch(normalized), normalized


def test_registry_resolves_cat12_alias_to_runtime_canonical_toolspec():
    spec = UnifiedToolRegistry().get_toolspec_by_name("cat12")

    assert spec is not None
    assert spec.name == "spm12_vbm"


def test_tool_search_surfaces_spm12_vbm_for_cat12_alias_query():
    resp = srv.tool_search("cat12", limit=5, exposed_only=True)

    assert resp["ok"] is True
    assert resp["tools"]
    assert resp["tools"][0]["name"] == "spm12_vbm"


def test_tool_search_surfaces_spm12_vbm_for_vbm_query():
    resp = srv.tool_search("VBM grey matter volume", limit=5, exposed_only=True)

    assert resp["ok"] is True
    assert resp["tools"]
    assert resp["tools"][0]["name"] == "spm12_vbm"


def test_get_execution_recipe_resolves_cat12_alias_to_runtime_canonical_id():
    resp = srv.get_execution_recipe(
        "cat12",
        params={
            "structural_images": ["/tmp/sub-01_T1w.nii.gz"],
            "output_dir": "/tmp/br-spm12-vbm",
        },
        target_runtime="neurodesk",
    )

    assert resp["ok"] is True
    assert resp["requested_tool_id"] == "cat12"
    assert resp["resolved_tool_id"] == "spm12_vbm"
    assert resp["canonical_tool_id"] == "spm12_vbm"
    _assert_canonical_runtime_tool_id(resp["resolved_tool_id"])
    _assert_canonical_runtime_tool_id(resp["canonical_tool_id"])
    assert resp["neurodesk_module_name"] == "cat12"
    assert resp["neurodesk_recommended_module"] == "cat12/12.9"
    assert "run_spm12_vbm.py" in str(resp.get("recipe", {}).get("run_command") or "")


@pytest.mark.parametrize(
    ("tool_id", "expected_package", "expected_module"),
    [
        ("fsl_bet", "fsl", "fsl/6.0.7.18"),
        ("fsl_fast", "fsl", "fsl/6.0.7.18"),
        ("ants_registration", "ants", "ants/2.6.0"),
        ("spm12_vbm", "cat12", "cat12/12.9"),
    ],
)
def test_get_execution_recipe_resolves_runtime_ids_to_neurodesk_metadata(
    tool_id: str,
    expected_package: str,
    expected_module: str,
) -> None:
    resp = srv.get_execution_recipe(
        tool_id,
        params={"output_dir": "/tmp/br-runtime-meta"},
        target_runtime="neurodesk",
    )

    assert resp["ok"] is True
    assert resp["requested_tool_id"] == tool_id
    assert resp["resolved_tool_id"] == tool_id
    assert resp["canonical_tool_id"] == tool_id
    _assert_canonical_runtime_tool_id(resp["resolved_tool_id"])
    _assert_canonical_runtime_tool_id(resp["canonical_tool_id"])
    assert resp["neurodesk_package_name"] == expected_package
    assert resp["neurodesk_module_name"] == expected_package
    assert resp["neurodesk_recommended_module"] == expected_module


def test_get_execution_recipe_contract_keeps_requested_alias_but_emits_canonical_runtime_ids():
    resp = srv.get_execution_recipe(
        "fsl.bet.run",
        params={
            "input_file": "/tmp/sub-01_T1w.nii.gz",
            "output_dir": "/tmp/br-fsl-bet",
        },
        target_runtime="neurodesk",
    )

    assert resp["ok"] is True
    assert resp["requested_tool_id"] == "fsl.bet.run"
    assert resp["resolved_tool_id"] == "fsl_bet"
    assert resp["canonical_tool_id"] == "fsl_bet"
    _assert_canonical_runtime_tool_id(resp["resolved_tool_id"])
    _assert_canonical_runtime_tool_id(resp["canonical_tool_id"])
    assert "run_fsl_bet.py" in str(resp.get("recipe", {}).get("run_command") or "")


def test_get_execution_recipe_resolves_fsl_bet_human_alias_to_supported_recipe():
    resp = srv.get_execution_recipe(
        "fsl BET",
        params={
            "input_file": "/tmp/sub-01_T1w.nii.gz",
            "output_file": "/tmp/sub-01_T1w_brain.nii.gz",
        },
        target_runtime="neurodesk",
    )

    assert resp["ok"] is True
    assert resp["requested_tool_id"] == "fsl BET"
    assert resp["resolved_tool_id"] == "fsl_bet"
    assert resp["canonical_tool_id"] == "fsl_bet"
    assert resp["supported_recipe_targets"] == ["neurodesk", "container", "slurm"]
    assert resp["neurodesk_recommended_module"] == "fsl/6.0.7.18"
    assert "run_fsl_bet.py" in str(resp.get("recipe", {}).get("run_command") or "")


def test_get_execution_recipe_defaults_to_primary_target_for_fsl_bet():
    resp = srv.get_execution_recipe(
        "FSL BET",
        params={
            "input_file": "/tmp/sub-01_T1w.nii.gz",
            "output_file": "/tmp/sub-01_T1w_brain.nii.gz",
        },
    )

    assert resp["ok"] is True
    assert resp["requested_tool_id"] == "FSL BET"
    assert resp["resolved_tool_id"] == "fsl_bet"
    assert resp["canonical_tool_id"] == "fsl_bet"
    assert resp["target_runtime"] == "neurodesk"
    assert resp["supported_recipe_targets"] == ["neurodesk", "container", "slurm"]
    assert resp["backend_options"]["command"] == "bet"
    assert resp["neurodesk_recommended_module"] == "fsl/6.0.7.18"
    assert "run_fsl_bet.py" in str(resp.get("recipe", {}).get("run_command") or "")


@pytest.mark.parametrize("target_runtime", ["default", "auto", ""])
def test_get_execution_recipe_auto_targets_use_primary_target_for_fsl_bet(
    target_runtime: str,
) -> None:
    resp = srv.get_execution_recipe(
        "FSL BET",
        params={
            "input_file": "/tmp/sub-01_T1w.nii.gz",
            "output_file": "/tmp/sub-01_T1w_brain.nii.gz",
        },
        target_runtime=target_runtime,
    )

    assert resp["ok"] is True
    assert resp["resolved_tool_id"] == "fsl_bet"
    assert resp["target_runtime"] == "neurodesk"
    assert resp["supported_recipe_targets"] == ["neurodesk", "container", "slurm"]


def test_get_execution_recipe_explicit_python_target_still_validates_for_fsl_bet():
    resp = srv.get_execution_recipe(
        "FSL BET",
        params={
            "input_file": "/tmp/sub-01_T1w.nii.gz",
            "output_file": "/tmp/sub-01_T1w_brain.nii.gz",
        },
        target_runtime="python",
    )

    assert resp["ok"] is False
    assert resp["error"] == "unsupported_recipe_target"
    assert resp["resolved_tool_id"] == "fsl_bet"
    assert resp["target_runtime"] == "python"
    assert resp["supported_recipe_targets"] == ["neurodesk", "container", "slurm"]
    assert "Supported targets" in resp["unsupported_reason"]


@pytest.mark.parametrize(
    ("requested_tool_id", "params", "expected_canonical_tool_id"),
    [
        (
            "cat12",
            {
                "structural_images": ["/tmp/sub-01_T1w.nii.gz"],
                "output_dir": "/tmp/br-contract-vbm",
            },
            "spm12_vbm",
        ),
        (
            "fsl_bet",
            {
                "input_file": "/tmp/sub-01_T1w.nii.gz",
                "output_dir": "/tmp/br-contract-bet",
            },
            "fsl_bet",
        ),
        (
            "ants_registration",
            {
                "moving_image": "/tmp/moving.nii.gz",
                "fixed_image": "/tmp/fixed.nii.gz",
                "output_prefix": "/tmp/br-contract-ants/out_",
            },
            "ants_registration",
        ),
    ],
)
def test_get_execution_recipe_contract_returns_canonical_runtime_tool_id(
    requested_tool_id: str,
    params: dict,
    expected_canonical_tool_id: str,
) -> None:
    resp = srv.get_execution_recipe(
        requested_tool_id,
        params=params,
        target_runtime="neurodesk",
    )

    assert resp["ok"] is True
    assert resp["resolved_tool_id"] == expected_canonical_tool_id
    assert resp["canonical_tool_id"] == expected_canonical_tool_id
    assert not str(resp["resolved_tool_id"]).endswith(".run")
    assert not str(resp["canonical_tool_id"]).endswith(".run")
