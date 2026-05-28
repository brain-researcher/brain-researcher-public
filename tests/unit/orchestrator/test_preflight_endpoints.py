from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import brain_researcher.services.orchestrator.preflight_endpoints as preflight_mod


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(preflight_mod.router)
    return TestClient(app)


def test_studio_alias_map_includes_rest_connectome_workflow_path():
    preflight_mod._load_studio_tool_alias_map.cache_clear()
    mapping = preflight_mod._load_studio_tool_alias_map()

    assert mapping.get("workflow_rest_connectome_e2e") == "workflow_rest_connectome_e2e"
    assert mapping.get("workflow_connectivity") == "workflow_rest_connectome_e2e"


def test_runtime_allowlist_prefers_agent_env(monkeypatch):
    preflight_mod._load_runtime_allowlist.cache_clear()
    monkeypatch.setenv(
        "AGENT_TOOL_ALLOWLIST",
        "workflow_rest_connectome_e2e,fetch_atlas,extract_timeseries,compute_connectivity,connectivity_matrix",
    )
    monkeypatch.setenv("AGENT_TOOL_ALLOWLIST_STRICT", "1")

    try:
        allowlist = preflight_mod._load_runtime_allowlist()
    finally:
        preflight_mod._load_runtime_allowlist.cache_clear()

    assert {
        "workflow_rest_connectome_e2e",
        "fetch_atlas",
        "extract_timeseries",
        "compute_connectivity",
        "connectivity_matrix",
    }.issubset(allowlist)


def test_preflight_resolves_workflow_tools_and_passes(monkeypatch):
    monkeypatch.setattr(
        preflight_mod,
        "_load_workflow_catalog",
        lambda: {
            "workflows": [
                {
                    "id": "workflow_preprocessing_qc",
                    "runtime": {
                        "kind": "declarative_workflow",
                        "steps": [
                            {"id": "validate", "tool": "validate_bids_structure"},
                            {"id": "qc", "tool": "run_mriqc_workflow"},
                        ],
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        preflight_mod,
        "_fetch_runtime_tool_status",
        AsyncMock(
            return_value=(
                {
                    "validate_bids_structure": "available",
                    "run_mriqc_workflow": "available",
                },
                [],
            )
        ),
    )
    monkeypatch.setattr(preflight_mod, "_load_runtime_allowlist", lambda: set())

    client = _make_client()
    response = client.post("/api/preflight/check", json={"workflow_id": "workflow_preprocessing_qc"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["executable"] is True
    assert payload["resolved_from_workflow"] is True
    assert [row["tool_id"] for row in payload["checks"]] == [
        "validate_bids_structure",
        "run_mriqc_workflow",
    ]
    assert all(row["status"] == "available" for row in payload["checks"])


def test_preflight_blocks_when_tool_missing(monkeypatch):
    monkeypatch.setattr(
        preflight_mod,
        "_fetch_runtime_tool_status",
        AsyncMock(
            return_value=(
                {
                    "run_bids_app": "available",
                },
                [],
            )
        ),
    )
    monkeypatch.setattr(preflight_mod, "_load_runtime_allowlist", lambda: set())

    client = _make_client()
    response = client.post(
        "/api/preflight/check",
        json={"tool_ids": ["run_bids_app", "run_mriqc_workflow"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["executable"] is False
    by_tool = {row["tool_id"]: row for row in payload["checks"]}
    assert by_tool["run_bids_app"]["status"] == "available"
    assert by_tool["run_mriqc_workflow"]["status"] == "missing"
    assert by_tool["run_mriqc_workflow"]["exists"] is False


def test_preflight_returns_warning_when_runtime_inventory_unavailable(monkeypatch):
    monkeypatch.setattr(
        preflight_mod,
        "_fetch_runtime_tool_status",
        AsyncMock(return_value=({}, ["Runtime tool inventory unavailable: timeout"])),
    )
    monkeypatch.setattr(preflight_mod, "_load_runtime_allowlist", lambda: set())

    client = _make_client()
    response = client.post("/api/preflight/check", json={"tool_ids": ["run_bids_app"]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["executable"] is False
    assert payload["checks"] == []
    assert payload["warnings"]
    assert "Runtime tool inventory unavailable" in payload["warnings"][0]


def test_preflight_returns_neurodesk_setup_guidance_for_neurodesk_workflow(monkeypatch):
    monkeypatch.setattr(
        preflight_mod,
        "_load_workflow_catalog",
        lambda: {
            "workflows": [
                {
                    "id": "workflow_preprocessing_qc",
                    "primary_target": "neurodesk",
                    "supported_recipe_targets": ["neurodesk", "container", "slurm"],
                    "runtime": {
                        "kind": "declarative_workflow",
                        "steps": [
                            {"id": "validate", "tool": "validate_bids_structure"},
                            {"id": "fmriprep", "tool": "run_bids_app"},
                        ],
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        preflight_mod,
        "get_tool_recipe_override",
        lambda tool_id: {
            "neurodesk_modules": ["fmriprep/23.2.3", "mriqc/24.0.2"],
            "required_env_vars": ["FS_LICENSE"],
            "container_images": {"fmriprep": "nipreps/fmriprep:23.2.3"},
        }
        if tool_id == "workflow_preprocessing_qc"
        else {},
    )
    monkeypatch.setattr(
        preflight_mod,
        "_fetch_runtime_tool_status",
        AsyncMock(
            return_value=(
                {
                    "validate_bids_structure": "available",
                },
                [],
            )
        ),
    )
    monkeypatch.setattr(preflight_mod, "_load_runtime_allowlist", lambda: set())

    client = _make_client()
    response = client.post("/api/preflight/check", json={"workflow_id": "workflow_preprocessing_qc"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["executable"] is False
    assert payload["guidance"]["kind"] == "neurodesk_setup_required"
    assert payload["guidance"]["access_mode"] == "self_setup_required"
    assert payload["guidance"]["runtime_target"] == "neurodesk"
    assert payload["guidance"]["install_path"] == "app"
    assert payload["guidance"]["required_modules"] == ["fmriprep/23.2.3", "mriqc/24.0.2"]
    assert payload["guidance"]["required_env_vars"] == ["FS_LICENSE"]
    assert payload["guidance"]["next_action_url"].startswith("https://neurodesk.org/")
    assert len(payload["guidance"]["actions"]) == 3
    assert payload["guidance"]["actions"][0]["href"] == "https://play.neurodesk.org/"


def test_preflight_returns_recipe_handoff_guidance_for_container_workflow(monkeypatch):
    monkeypatch.setattr(
        preflight_mod,
        "_load_workflow_catalog",
        lambda: {
            "workflows": [
                {
                    "id": "workflow_fastsurfer",
                    "primary_target": "container",
                    "supported_recipe_targets": ["container"],
                    "runtime": {
                        "kind": "declarative_workflow",
                        "steps": [{"id": "fastsurfer", "tool": "run_fastsurfer"}],
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        preflight_mod,
        "get_tool_recipe_override",
        lambda tool_id: {
            "required_env_vars": ["FS_LICENSE"],
            "container_images": {"fastsurfer": "deepmi/fastsurfer:latest"},
        }
        if tool_id == "workflow_fastsurfer"
        else {},
    )
    monkeypatch.setattr(
        preflight_mod,
        "_fetch_runtime_tool_status",
        AsyncMock(return_value=({"run_fastsurfer": "available"}, [])),
    )
    monkeypatch.setattr(preflight_mod, "_load_runtime_allowlist", lambda: {"fetch_atlas"})

    client = _make_client()
    response = client.post("/api/preflight/check", json={"workflow_id": "workflow_fastsurfer"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["executable"] is False
    assert payload["checks"][0]["code"] == "RUNTIME_TOOL_NOT_ALLOWED"
    assert payload["guidance"]["kind"] == "recipe_handoff_required"
    assert payload["guidance"]["runtime_target"] == "container"
    assert payload["guidance"]["install_path"] == "external"
    assert payload["guidance"]["supported_recipe_targets"] == ["container"]
    assert payload["guidance"]["required_env_vars"] == ["FS_LICENSE"]
    assert payload["guidance"]["container_images"] == {
        "fastsurfer": "deepmi/fastsurfer:latest"
    }


def test_preflight_omits_recipe_guidance_when_container_workflow_is_executable(monkeypatch):
    monkeypatch.setattr(
        preflight_mod,
        "_load_workflow_catalog",
        lambda: {
            "workflows": [
                {
                    "id": "workflow_fastsurfer",
                    "primary_target": "container",
                    "supported_recipe_targets": ["container"],
                    "runtime": {
                        "kind": "declarative_workflow",
                        "steps": [{"id": "fastsurfer", "tool": "run_fastsurfer"}],
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        preflight_mod,
        "get_tool_recipe_override",
        lambda tool_id: {
            "required_env_vars": ["FS_LICENSE"],
            "container_images": {"fastsurfer": "deepmi/fastsurfer:latest"},
        }
        if tool_id == "workflow_fastsurfer"
        else {},
    )
    monkeypatch.setattr(
        preflight_mod,
        "_fetch_runtime_tool_status",
        AsyncMock(return_value=({"run_fastsurfer": "available"}, [])),
    )
    monkeypatch.setattr(preflight_mod, "_load_runtime_allowlist", lambda: {"run_fastsurfer"})

    client = _make_client()
    response = client.post("/api/preflight/check", json={"workflow_id": "workflow_fastsurfer"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["executable"] is True
    assert payload["checks"][0]["status"] == "available"
    assert payload["guidance"] is None


def test_preflight_canonicalizes_alias_tool_ids(monkeypatch):
    monkeypatch.setattr(
        preflight_mod,
        "_load_studio_tool_alias_map",
        lambda: {
            "fmriprep": "run_bids_app",
            "nilearn.glm.first_level.run": "glm_first_level",
        },
    )
    monkeypatch.setattr(
        preflight_mod,
        "_fetch_runtime_tool_status",
        AsyncMock(
            return_value=(
                {
                    "run_bids_app": "available",
                    "glm_first_level": "available",
                },
                [],
            )
        ),
    )
    monkeypatch.setattr(preflight_mod, "_load_runtime_allowlist", lambda: set())

    client = _make_client()
    response = client.post(
        "/api/preflight/check",
        json={"tool_ids": ["fmriprep", "nilearn.glm.first_level.run"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["executable"] is True
    assert [row["tool_id"] for row in payload["checks"]] == [
        "run_bids_app",
        "glm_first_level",
    ]
    assert any(
        "Canonicalized tool IDs" in warning for warning in payload.get("warnings", [])
    )


def test_preflight_canonicalizes_connectivity_workflow_alias(monkeypatch):
    monkeypatch.setattr(
        preflight_mod,
        "_load_studio_tool_alias_map",
        lambda: {
            "workflow_connectivity": "workflow_rest_connectome_e2e",
            "workflow_rest_connectome_e2e": "workflow_rest_connectome_e2e",
        },
    )
    monkeypatch.setattr(
        preflight_mod,
        "_fetch_runtime_tool_status",
        AsyncMock(
            return_value=(
                {
                    "workflow_rest_connectome_e2e": "available",
                },
                [],
            )
        ),
    )
    monkeypatch.setattr(
        preflight_mod,
        "_load_runtime_allowlist",
        lambda: {"workflow_rest_connectome_e2e"},
    )

    client = _make_client()
    response = client.post(
        "/api/preflight/check",
        json={"tool_ids": ["workflow_connectivity"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["executable"] is True
    assert [row["tool_id"] for row in payload["checks"]] == [
        "workflow_rest_connectome_e2e",
    ]
    assert payload["checks"][0]["requested_tool_id"] == "workflow_connectivity"
    assert any(
        "Canonicalized tool IDs" in warning for warning in payload.get("warnings", [])
    )


def test_preflight_flags_unknown_alias_with_explicit_code(monkeypatch):
    monkeypatch.setattr(
        preflight_mod,
        "_load_studio_tool_alias_map",
        lambda: {
            "run_bids_app": "run_bids_app",
        },
    )
    monkeypatch.setattr(
        preflight_mod,
        "_fetch_runtime_tool_status",
        AsyncMock(
            return_value=(
                {
                    "run_bids_app": "available",
                },
                [],
            )
        ),
    )
    monkeypatch.setattr(preflight_mod, "_load_runtime_allowlist", lambda: set())

    client = _make_client()
    response = client.post("/api/preflight/check", json={"tool_ids": ["mystery_tool_id"]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["executable"] is False
    check = payload["checks"][0]
    assert check["tool_id"] == "mystery_tool_id"
    assert check["status"] == "missing"
    assert check["code"] == "UNKNOWN_TOOL_ALIAS"


def test_preflight_blocks_when_tool_is_not_allowlisted(monkeypatch):
    monkeypatch.setattr(
        preflight_mod,
        "_fetch_runtime_tool_status",
        AsyncMock(
            return_value=(
                {
                    "run_bids_app": "available",
                    "connectivity_matrix": "available",
                },
                [],
            )
        ),
    )
    monkeypatch.setattr(
        preflight_mod,
        "_load_runtime_allowlist",
        lambda: {"run_bids_app"},
    )

    client = _make_client()
    response = client.post(
        "/api/preflight/check",
        json={"tool_ids": ["run_bids_app", "connectivity_matrix"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["executable"] is False
    by_tool = {row["tool_id"]: row for row in payload["checks"]}
    assert by_tool["run_bids_app"]["status"] == "available"
    assert by_tool["connectivity_matrix"]["status"] == "blocked"
    assert by_tool["connectivity_matrix"]["code"] == "RUNTIME_TOOL_NOT_ALLOWED"
