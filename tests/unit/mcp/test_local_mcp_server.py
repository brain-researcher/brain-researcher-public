from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import py_compile
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _stub_toolspec_registry(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    def fake_get_toolspec_with_schema(tool_id: str):
        if tool_id != "extract_timeseries":
            return None
        return ToolSpec(
            name="extract_timeseries",
            description="stub",
            backend="python",
            python_class="json:loads",
            required=["img", "atlas"],
        )

    monkeypatch.setattr(srv, "_get_toolspec_with_schema", fake_get_toolspec_with_schema)
    monkeypatch.setattr(
        srv, "load_orchestration_workflows", lambda: ["workflow_preprocessing_qc"]
    )


def _write_run_fixture(
    root: Path,
    run_id: str,
    *,
    status: str = "succeeded",
    steps: list[dict] | None = None,
    files: dict[str, object] | None = None,
) -> Path:
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "created_at": "2026-03-09T00:00:00Z",
        "status": status,
        "dry_run": False,
        "steps": steps or [],
    }
    (run_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")
    for relpath, content in (files or {}).items():
        path = run_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict | list):
            path.write_text(json.dumps(content), encoding="utf-8")
        else:
            path.write_text(str(content), encoding="utf-8")
    return run_dir


def _materialize_recipe_files(recipe: dict[str, object], workspace: Path) -> Path:
    files = recipe.get("files") if isinstance(recipe, dict) else None
    assert isinstance(files, dict)
    workspace.mkdir(parents=True, exist_ok=True)
    for relpath, text in files.items():
        path = workspace / str(relpath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(text), encoding="utf-8")
        if path.suffix == ".sh":
            path.chmod(path.stat().st_mode | 0o111)
    return workspace


def test_public_mcp_tool_filter_preserves_sync_tool_manager_contract():
    from brain_researcher.services.mcp import server as srv

    raw_tools = srv.mcp._tool_manager.list_tools()
    assert isinstance(raw_tools, list)
    assert raw_tools
    assert all(tool.name not in srv._MCP_COMPAT_TOOL_NAMES for tool in raw_tools)

    listed_tools = asyncio.run(srv.mcp.list_tools())
    listed_names = [tool.name for tool in listed_tools]
    assert listed_names == [tool.name for tool in raw_tools]

    cached_tool = asyncio.run(
        srv.mcp._mcp_server._get_cached_tool_definition(listed_names[0])
    )
    assert cached_tool is not None
    assert cached_tool.name == listed_names[0]


def test_public_mcp_resource_templates_exposed():
    from brain_researcher.services.mcp import server as srv

    templates = asyncio.run(srv.mcp.list_resource_templates())
    by_uri = {template.uriTemplate: template for template in templates}

    assert "tool://{tool_id}" in by_uri
    assert "dataset://{dataset_ref}" in by_uri
    assert "workflow://{workflow_id}" in by_uri
    assert by_uri["tool://{tool_id}"].mimeType == "application/json"


def test_tool_resource_returns_concise_agent_payload(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "tool_get",
        lambda tool_id, include_schema=True: {
            "ok": True,
            "tool": {
                "name": tool_id,
                "description": "Tool summary for agents.",
                "backend": "python",
                "requires_runtime": "python",
                "execution_story_kind": "portable_python_compute",
                "supported_recipe_targets": ["python"],
                "execution_recipe_available": True,
                "json_schema": {
                    "type": "object",
                    "required": ["img"],
                    "properties": {
                        "img": {
                            "type": "string",
                            "description": "Input image path.",
                        },
                        "atlas": {
                            "type": "string",
                            "description": "Atlas image path.",
                        },
                    },
                },
            },
        },
    )

    contents = list(asyncio.run(srv.mcp.read_resource("tool://extract_timeseries")))
    payload = json.loads(contents[0].content)

    assert contents[0].mime_type == "application/json"
    assert payload["ok"] is True
    assert payload["resource_kind"] == "tool"
    assert payload["tool_id"] == "extract_timeseries"
    assert payload["important_params"][0]["name"] == "img"
    assert payload["example_br_usage"]["execute"].startswith(
        'br.execute("extract_timeseries"'
    )


def test_tool_resource_returns_error_payload_for_unknown_tool(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "tool_get",
        lambda tool_id, include_schema=True: {
            "ok": False,
            "error": f"Unknown tool: {tool_id}",
        },
    )

    contents = list(asyncio.run(srv.mcp.read_resource("tool://missing_tool")))
    payload = json.loads(contents[0].content)

    assert payload == {
        "ok": False,
        "resource_kind": "tool",
        "tool_id": "missing_tool",
        "error": "Unknown tool: missing_tool",
        "message": None,
    }


def test_dataset_resource_returns_concise_agent_payload(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "dataset_get_resources",
        lambda dataset_ref: {
            "ok": True,
            "resources": {
                "resolved_dataset_id": "ds:openneuro:ds000001",
                "display_name": "Balloon Analog Risk Task",
                "source_repo": "openneuro",
                "dataset_metadata": {
                    "modalities": ["fmri"],
                    "tasks": ["bart"],
                },
                "local_path": "/data/ds000001",
                "bids_path": "/data/ds000001",
                "available_derivatives": ["fmriprep"],
                "remote_urls": {"primary": "https://openneuro.org/datasets/ds000001"},
                "readiness": {
                    "status": "ready",
                    "reason": "local_bids_available",
                    "note": "BIDS root resolved locally.",
                },
            },
        },
    )

    contents = list(asyncio.run(srv.mcp.read_resource("dataset://ds000001")))
    payload = json.loads(contents[0].content)

    assert payload["ok"] is True
    assert payload["resource_kind"] == "dataset"
    assert payload["dataset_ref"] == "ds000001"
    assert payload["display_name"] == "Balloon Analog Risk Task"
    assert payload["readiness"]["status"] == "ready"
    assert payload["example_br_usage"]["recipe"].startswith(
        'br.recipe("workflow_preprocessing_qc"'
    )


def test_workflow_resource_returns_concise_agent_payload(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "_workflow_search_rows",
        lambda: [
            {
                "id": "workflow_preprocessing_qc",
                "description": "Validate BIDS, run preprocessing, then aggregate QC.",
                "stage": "preprocessing",
                "modalities": ["fmri", "smri"],
                "params": {
                    "schema": {
                        "type": "object",
                        "required": ["bids_dir", "output_dir"],
                    }
                },
            }
        ],
    )
    monkeypatch.setattr(
        srv,
        "recipe_card_metadata",
        lambda workflow_id, workflow_entry=None: {
            "primary_target": "python",
            "supported_recipe_targets": ["python"],
        },
    )

    contents = list(
        asyncio.run(srv.mcp.read_resource("workflow://workflow_preprocessing_qc"))
    )
    payload = json.loads(contents[0].content)

    assert payload["ok"] is True
    assert payload["resource_kind"] == "workflow"
    assert payload["workflow_id"] == "workflow_preprocessing_qc"
    assert payload["stage"] == "preprocessing"
    assert payload["params_summary"]["required"] == ["bids_dir", "output_dir"]
    assert payload["example_br_usage"] == {
        "recipe": 'br.recipe("workflow_preprocessing_qc", {"...": "..."})'
    }


def test_tool_resource_omits_execute_example_for_workflow_only(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "tool_get",
        lambda tool_id, include_schema=True: {
            "ok": True,
            "workflow_only": True,
            "message": "Prefer recipe generation over direct execution.",
            "tool": {
                "name": tool_id,
                "description": "Workflow-only BR entry.",
                "backend": "python",
                "requires_runtime": "python",
                "execution_story_kind": "portable_python_compute",
                "supported_recipe_targets": ["python"],
                "execution_recipe_available": True,
                "json_schema": {"type": "object", "properties": {}},
            },
        },
    )

    contents = list(
        asyncio.run(srv.mcp.read_resource("tool://workflow_preprocessing_qc"))
    )
    payload = json.loads(contents[0].content)

    assert payload["workflow_only"] is True
    assert payload["example_br_usage"]["recipe"].startswith(
        'br.recipe("workflow_preprocessing_qc"'
    )
    assert "execute" not in payload["example_br_usage"]


def test_workflow_resource_direct_lookup_ignores_search_paging(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "_workflow_search_rows",
        lambda: [
            {"id": f"workflow_{idx}", "description": f"workflow {idx}"}
            for idx in range(25)
        ]
        + [
            {
                "id": "workflow_target",
                "description": "Target workflow beyond a first-page search window.",
                "stage": "preprocessing",
                "modalities": ["fmri"],
                "params": {"schema": {"type": "object", "required": ["bids_dir"]}},
            }
        ],
    )
    monkeypatch.setattr(
        srv,
        "recipe_card_metadata",
        lambda workflow_id, workflow_entry=None: {
            "primary_target": "python",
            "supported_recipe_targets": ["python"],
        },
    )

    contents = list(asyncio.run(srv.mcp.read_resource("workflow://workflow_target")))
    payload = json.loads(contents[0].content)

    assert payload["ok"] is True
    assert payload["workflow_id"] == "workflow_target"
    assert payload["params_summary"]["required"] == ["bids_dir"]
    assert payload["example_br_usage"] == {
        "recipe": 'br.recipe("workflow_target", {"...": "..."})'
    }


def _configure_tool_execute_test_env(
    monkeypatch,
    tmp_path: Path,
    *,
    allowlist: set[str],
    run_root: Path | None = None,
    use_real_toolspec_lookup: bool = False,
    enrich_real_toolspec_schema: bool = False,
    enable_multiagent: bool = False,
    enable_critic_gate: bool = False,
) -> SimpleNamespace:
    from brain_researcher.services.mcp import server as srv

    allowed_root = tmp_path.resolve()
    run_root_path = (run_root or tmp_path).resolve()

    monkeypatch.setenv("BR_ALLOWED_ROOTS", str(allowed_root))
    monkeypatch.setenv("BR_MCP_ALLOWED_ROOTS", str(allowed_root))
    monkeypatch.setattr(srv, "RUN_ROOT", run_root_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [allowed_root])
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", set(allowlist))
    monkeypatch.setattr(srv, "AGENT_MULTIAGENT_ENABLED", enable_multiagent)
    monkeypatch.setattr(srv, "AGENT_CRITIC_TOOL_GATE", enable_critic_gate)

    if use_real_toolspec_lookup:

        def _real_toolspec_with_schema(tool_id: str):
            spec = srv._get_registry().get_toolspec_by_name(tool_id)
            if spec is None:
                return None
            if not enrich_real_toolspec_schema:
                return spec
            return srv._enrich_toolspec_schema(spec.model_copy(deep=True))

        monkeypatch.setattr(
            srv, "_get_toolspec_with_schema", _real_toolspec_with_schema
        )

    return SimpleNamespace(
        allowed_root=allowed_root,
        run_root=run_root_path,
    )


def _tool_pack_script_name(tool_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(tool_id or "").strip()).strip("_")
    return f"run_{slug or 'tool'}.py"


def _assert_execution_pack(
    response: dict[str, object],
    *,
    expected_workspace: Path,
    tool_id: str,
    expected_script_name: str | None = None,
) -> dict[str, object]:
    result = response.get("result")
    assert isinstance(result, dict), response
    metadata = result.get("metadata")
    assert isinstance(metadata, dict), result

    pack = response.get("execution_pack")
    assert isinstance(pack, dict), response
    assert metadata.get("execution_pack") == pack

    workspace = expected_workspace.resolve()
    pack_manifest = workspace / "pack_manifest.json"
    run_pack = workspace / "run_pack.py"
    script_name = expected_script_name or _tool_pack_script_name(tool_id)
    script_path = workspace / script_name

    assert pack.get("tool_id") == tool_id
    assert pack.get("workspace") == str(workspace)
    assert pack.get("pack_manifest") == str(pack_manifest)
    assert pack.get("run_pack") == str(run_pack)
    assert pack.get("run_pack_command") == "python run_pack.py"

    files_written = set(pack.get("files_written") or [])
    assert {"pack_manifest.json", "params.json", "run_pack.py", script_name}.issubset(
        files_written
    )

    assert pack_manifest.is_file()
    assert run_pack.is_file()
    assert (workspace / "params.json").is_file()
    assert script_path.is_file()

    return pack


def test_load_workflow_catalog_infers_params_from_runtime_placeholders(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    catalog_path = tmp_path / "workflow_catalog.yaml"
    catalog_path.write_text("""
workflows:
  - id: workflow_inferred_params
    stage: interpretation
    cost_tier: cheap
    runtime:
      kind: declarative_workflow
      steps:
        - id: compare
          tool: compare_surface_maps
          params:
            map1: "${inputs.map_file}"
            map2: "${inputs.reference_map}"
            null_permutations: "${inputs.n_permutations:-250}"
            output_file: "${inputs.output_dir}/spatial_correlation.json"
            dry_run: "${inputs.dry_run:-false}"
""")
    monkeypatch.setattr(srv, "resolve_from_config", lambda *_args: catalog_path)

    srv._load_workflow_catalog.cache_clear()
    try:
        loaded = srv._load_workflow_catalog()
    finally:
        srv._load_workflow_catalog.cache_clear()

    assert len(loaded) == 1
    row = loaded[0]
    assert row["id"] == "workflow_inferred_params"
    assert isinstance(row["params"], dict)
    assert row["params"]["defaults"] == {
        "dry_run": False,
        "n_permutations": 250,
        "output_dir": "/tmp/brain-researcher/workflow_inferred_params",
    }
    assert row["params"]["schema"]["required"] == ["map_file", "reference_map"]
    assert row["params"]["schema"]["properties"]["dry_run"]["type"] == "boolean"
    assert row["params"]["schema"]["properties"]["n_permutations"]["type"] == "integer"
    assert row["params"]["schema"]["properties"]["output_dir"]["type"] == "string"


def test_load_workflow_catalog_keeps_explicit_params_untouched(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    catalog_path = tmp_path / "workflow_catalog.yaml"
    catalog_path.write_text("""
workflows:
  - id: workflow_explicit_params
    stage: interpretation
    cost_tier: moderate
    params:
      schema:
        type: object
        required: [reference_term]
        properties:
          reference_term:
            type: string
      defaults:
        n_perm: 1000
    runtime:
      kind: declarative_workflow
      steps:
        - id: fetch
          tool: query_neuromaps
          params:
            term: "${inputs.reference_term}"
            output_file: "${inputs.output_dir}/query.json"
""")
    monkeypatch.setattr(srv, "resolve_from_config", lambda *_args: catalog_path)

    srv._load_workflow_catalog.cache_clear()
    try:
        loaded = srv._load_workflow_catalog()
    finally:
        srv._load_workflow_catalog.cache_clear()

    assert len(loaded) == 1
    row = loaded[0]
    assert row["params"] == {
        "schema": {
            "type": "object",
            "required": ["reference_term"],
            "properties": {"reference_term": {"type": "string"}},
        },
        "defaults": {"n_perm": 1000},
    }


def test_load_workflow_catalog_preserves_recipe_metadata(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    catalog_path = tmp_path / "workflow_catalog.yaml"
    catalog_path.write_text("""
workflows:
  - id: workflow_declared_recipe_metadata
    stage: interpretation
    cost_tier: cheap
    execution_story_kind: portable_python_compute
    supported_recipe_targets: [python]
    primary_target: python
    recipe_family: connectivity
    stable_workflow_pack: true
    source_repo: https://github.com/example/workflow
    source_paper: Example et al. Workflow Paper
    tested_release: 2026-03-09
    backend_options:
      default: combat
      available: [combat, deepresbat_external]
    example_dataset:
      dataset_id: ds000114
    reference_assets:
      - nilearn.atlas.yeo2011.17networks.volume
    artifact_contract:
      required_outputs: [out.csv]
    acceptance_gate:
      script: scripts/workflows/run_workflow_realdata_gate.py
    runbook: docs/runbooks/example.md
    runtime:
      kind: declarative_workflow
      steps:
        - id: extract
          tool: extract_timeseries
          params:
            img: "${inputs.img}"
            atlas: "${inputs.atlas}"
""")
    monkeypatch.setattr(srv, "resolve_from_config", lambda *_args: catalog_path)

    srv._load_workflow_catalog.cache_clear()
    try:
        loaded = srv._load_workflow_catalog()
    finally:
        srv._load_workflow_catalog.cache_clear()

    assert len(loaded) == 1
    row = loaded[0]
    assert row["execution_story_kind"] == "portable_python_compute"
    assert row["supported_recipe_targets"] == ["python"]
    assert row["primary_target"] == "python"
    assert row["recipe_family"] == "connectivity"
    assert row["stable_workflow_pack"] is True
    assert row["source_repo"] == "https://github.com/example/workflow"
    assert row["source_paper"] == "Example et al. Workflow Paper"
    assert str(row["tested_release"]) == "2026-03-09"
    assert row["backend_options"]["default"] == "combat"
    assert row["example_dataset"]["dataset_id"] == "ds000114"
    assert row["reference_assets"] == ["nilearn.atlas.yeo2011.17networks.volume"]
    assert row["artifact_contract"]["required_outputs"] == ["out.csv"]
    assert (
        row["acceptance_gate"]["script"]
        == "scripts/workflows/run_workflow_realdata_gate.py"
    )
    assert row["runbook"] == "docs/runbooks/example.md"
    assert row["runtime"]["kind"] == "declarative_workflow"
    assert row["runtime"]["steps"][0]["tool"] == "extract_timeseries"


def test_load_workflow_catalog_omits_empty_stable_pack_provenance():
    from brain_researcher.services.mcp import server as srv

    rows = {
        workflow["id"]: workflow
        for workflow in srv._load_workflow_catalog()
        if workflow.get("id")
        in {
            "workflow_longitudinal_lme",
            "workflow_subtype_discovery",
            "workflow_precision_parcellation",
        }
    }

    assert set(rows) == {
        "workflow_longitudinal_lme",
        "workflow_subtype_discovery",
        "workflow_precision_parcellation",
    }
    for row in rows.values():
        assert "source_repo" not in row
        assert "source_paper" not in row
        assert "tested_release" not in row


def test_mcp_server_module_compiles():
    from brain_researcher.services.mcp import server as srv

    py_compile.compile(str(Path(srv.__file__).resolve()), doraise=True)


def test_pipeline_plan_validate_rejects_unknown_tool():
    from brain_researcher.services.mcp.server import pipeline_plan_validate

    resp = pipeline_plan_validate({"steps": [{"tool": "does.not.exist", "params": {}}]})
    assert resp["ok"] is False
    assert any(i.get("code") == "unknown_tool" for i in resp.get("issues", []))


def test_pipeline_plan_validate_reports_workflow_registry_mismatch(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "is_workflow_tool_id",
        lambda tool_id: tool_id == "workflow_broken_registry",
    )
    monkeypatch.setattr(
        srv,
        "_is_declared_workflow_id",
        lambda tool_id: tool_id == "workflow_broken_registry",
    )

    resp = srv.pipeline_plan_validate(
        {"steps": [{"tool": "workflow_broken_registry", "params": {}}]}
    )
    assert resp["ok"] is False
    assert any(
        i.get("code") == "workflow_registry_mismatch" for i in resp.get("issues", [])
    )


def test_pipeline_plan_validate_reports_python_backend_misconfiguration(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda _tool_id: ToolSpec(
            name="python.broken_tool",
            description="stub",
            backend="python",
            python_class="missing.module.Class",
        ),
    )

    resp = srv.pipeline_plan_validate(
        {"steps": [{"tool": "python.broken_tool", "params": {}}]}
    )
    assert resp["ok"] is False
    assert any(
        i.get("code") == "tool_registry_misconfigured"
        and i.get("reason_code") == "python_backend_unresolvable"
        for i in resp.get("issues", [])
    )


def test_pipeline_plan_validate_rejects_invalid_explicit_step_id(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda _tool_id: ToolSpec(name="fetch_atlas", description="stub"),
    )

    resp = srv.pipeline_plan_validate(
        {
            "steps": [
                {
                    "tool": "fetch_atlas",
                    "step_id": "fetch.atlas.100",
                    "params": {"atlas_name": "Schaefer2018_100"},
                }
            ]
        }
    )
    assert resp["ok"] is False
    assert "step_id must match" in resp["error"]


def test_pipeline_plan_validate_rejects_duplicate_step_ids(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda _tool_id: ToolSpec(name="fetch_atlas", description="stub"),
    )

    resp = srv.pipeline_plan_validate(
        {
            "steps": [
                {"tool": "fetch_atlas", "step_id": "atlas_fetch", "params": {}},
                {"tool": "fetch_atlas", "step_id": "atlas_fetch", "params": {}},
            ]
        }
    )
    assert resp["ok"] is False
    assert "duplicate step_id" in resp["error"]


def test_pipeline_plan_validate_supports_project_root_workspace(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path / "run_root")
    monkeypatch.setattr(
        srv,
        "ALLOWED_ROOTS",
        [(tmp_path / "run_root").resolve(), (tmp_path / "workspace").resolve()],
    )
    srv._ensure_dirs()

    resp = srv.pipeline_plan_validate(
        {
            "project_root": str(tmp_path / "workspace"),
            "run_tag": "construct audit",
            "steps": [
                {"tool": "extract_timeseries", "params": {"img": "x", "atlas": "y"}}
            ],
        }
    )

    assert resp["ok"] is True, resp
    run_workspace = Path(resp["run_workspace"])
    assert run_workspace == (tmp_path / "workspace" / "runs" / "construct-audit")
    first_step = resp["normalized_plan"]["steps"][0]
    assert first_step["work_dir"].startswith(str(run_workspace / "03_work"))
    assert first_step["output_dir"].startswith(str(run_workspace / "04_artifacts"))


def test_tool_execute_preflight_rejects_python_backend_misconfiguration(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"python.broken_tool"},
    )
    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda _tool_id: ToolSpec(
            name="python.broken_tool",
            description="stub",
            backend="python",
            python_class="missing.module.Class",
        ),
    )

    called = {"count": 0}

    def fail_if_called(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("execute_tool should not run when preflight rejects")

    monkeypatch.setattr(srv, "execute_tool", fail_if_called)

    resp = srv.tool_execute("python.broken_tool", params={"x": 1})
    assert resp["ok"] is False
    assert resp["error"] == "tool_registry_misconfigured"
    assert any(
        i.get("code") == "tool_registry_misconfigured"
        and i.get("reason_code") == "python_backend_unresolvable"
        for i in resp.get("issues", [])
    )
    assert called["count"] == 0


def test_server_info_and_guardrails_expose_rm_logging_settings(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RM_LOGGING_ENABLED", True)
    monkeypatch.setattr(srv, "RM_LOGGING_POLICY", "redact_raw_vault")

    guardrails = srv._mcp_guardrails_snapshot()
    assert guardrails["rm_logging_enabled"] is True
    assert guardrails["rm_logging_policy"] == "redact_raw_vault"

    info = srv.server_info()
    assert info["ok"] is True
    assert info["data"]["rm_logging_enabled"] is True
    assert info["data"]["rm_logging_policy"] == "redact_raw_vault"
    assert info["data"]["default_loop_profile_id"] == "external_coding_v1"
    assert "external_coding_v1" in info["data"]["available_loop_profiles"]
    snapshot = info["data"]["tool_registry_mode_snapshot"]
    assert "BR_TOOL_REGISTRY_BACKEND" in snapshot
    assert "BR_TOOL_REGISTRY_MUTATION_MODE" in snapshot
    assert "BR_TOOL_REGISTRY_FAIL_OPEN" in snapshot
    assert "BR_TOOL_EXECUTE_AUTO_REMAP" in snapshot


def test_server_info_includes_dependency_status(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    openneuro_mount = tmp_path / "openneuro_mount"
    openneuro_mount.mkdir(parents=True, exist_ok=True)
    public_s3_mount = tmp_path / "public_s3_mount"
    public_s3_mount.mkdir(parents=True, exist_ok=True)
    openneuro_metadata = tmp_path / "openneuro_metadata"
    openneuro_metadata.mkdir(parents=True, exist_ok=True)
    niclip_data = tmp_path / "niclip_data"
    niclip_data.mkdir(parents=True, exist_ok=True)
    niclip_models = tmp_path / "niclip_models"
    niclip_models.mkdir(parents=True, exist_ok=True)
    atlases_root = tmp_path / "atlases"
    atlases_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("NEO4J_URI", "bolt://neo4j:7687")
    monkeypatch.setenv("NEO4J_PASSWORD", "test-password")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")
    monkeypatch.setenv("OPENNEURO_MOUNT_ROOT", str(openneuro_mount))
    monkeypatch.setenv("PUBLIC_S3_ROOT", str(public_s3_mount))
    monkeypatch.setenv("OPENNEURO_METADATA_ROOT", str(openneuro_metadata))
    monkeypatch.setenv("NICLIP_DATA_PATH", str(niclip_data))
    monkeypatch.setenv("NICLIP_MODEL_DIR", str(niclip_models))
    monkeypatch.setenv("BR_ATLAS_OUTPUT_ROOT", str(atlases_root))

    info = srv.server_info()
    assert info["ok"] is True
    deps = info["data"]["dependency_status"]
    assert deps["neo4j"]["configured"] is True
    assert deps["neo4j"]["uri"] == "bolt://neo4j:7687"
    assert "active_check" in deps["neo4j"]
    assert "run_root" in deps
    assert deps["openneuro_mount"]["exists"] is True
    assert str(openneuro_mount) in deps["openneuro_mount"]["detected_paths"]
    assert deps["public_s3_mount"]["exists"] is True
    assert str(public_s3_mount) in deps["public_s3_mount"]["detected_paths"]
    assert deps["dataset_mounts"]["openneuro_metadata_mount"]["exists"] is True
    assert deps["dataset_mounts"]["openneuro_metadata_mount"]["detected_paths"][
        0
    ] == str(openneuro_metadata)
    assert deps["dataset_mounts"]["niclip_data_mount"]["exists"] is True
    assert deps["dataset_mounts"]["niclip_model_mount"]["exists"] is True
    assert deps["dataset_mounts"]["atlases_mount"]["exists"] is True
    assert "bids_validator_available" in deps["local_runtime"]


def test_server_info_exposes_tool_registry_mode_env_snapshot(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setenv("BR_TOOL_REGISTRY_BACKEND", "legacy")
    monkeypatch.setenv("BR_TOOL_REGISTRY_MUTATION_MODE", "readonly")
    monkeypatch.setenv("BR_TOOL_REGISTRY_FAIL_OPEN", "1")
    monkeypatch.setenv("BR_TOOL_EXECUTE_AUTO_REMAP", "1")

    info = srv.server_info()
    assert info["ok"] is True
    snapshot = info["data"]["tool_registry_mode_snapshot"]
    assert snapshot["BR_TOOL_REGISTRY_BACKEND"] == "legacy"
    assert snapshot["BR_TOOL_REGISTRY_MUTATION_MODE"] == "readonly"
    assert snapshot["BR_TOOL_REGISTRY_FAIL_OPEN"] == "1"
    assert snapshot["BR_TOOL_EXECUTE_AUTO_REMAP"] == "1"


def test_server_info_exposes_compat_alias_usage_snapshot(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    monkeypatch.setattr(
        srv,
        "_run_kg_probe",
        lambda **kwargs: {"ok": True, "result": {"items": [], "kwargs": kwargs}},
    )
    monkeypatch.setattr(
        srv,
        "_run_kg_hypothesis_workflow",
        lambda **kwargs: {"ok": True, "result": {"samples": [], "kwargs": kwargs}},
    )

    first = srv.kg_find_structural_leverage(start_kg_ids=["node:a"])
    second = srv.kg_find_structural_leverage(start_kg_ids=["node:b"])
    third = srv.kg_sample_ood_hypothesis(seed_kg_ids=["node:c"])

    assert first["ok"] is True
    assert second["ok"] is True
    assert third["ok"] is True

    info = srv.server_info()
    assert info["ok"] is True
    usage = info["data"]["compat_alias_usage"]

    assert usage["schema_version"] == "mcp-compat-alias-usage-v1"
    assert usage["total_calls"] == 3
    assert usage["distinct_aliases"] == 2
    assert usage["record_path"] == str(tmp_path / "compat_alias_usage.json")

    aliases = {row["alias_name"]: row for row in usage["aliases"]}
    assert aliases["kg_find_structural_leverage"]["canonical_name"] == "kg_probe"
    assert aliases["kg_find_structural_leverage"]["count"] == 2
    assert aliases["kg_find_structural_leverage"]["last_param_keys"] == [
        "allowed_edge_types",
        "kg_id",
        "max_hops",
        "seed_kg_ids",
        "start_kg_ids",
        "top_k",
    ]
    assert aliases["kg_sample_ood_hypothesis"]["canonical_name"] == (
        "kg_hypothesis_workflow"
    )
    assert aliases["kg_sample_ood_hypothesis"]["count"] == 1
    assert len(usage["recent_events"]) == 3


def test_run_request_summary_includes_compat_alias_usage(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    monkeypatch.setattr(
        srv,
        "_run_kg_probe",
        lambda **kwargs: {"ok": True, "result": {"motifs": [], "kwargs": kwargs}},
    )

    resp = srv.kg_detect_contradiction_motifs(
        hypothesis="task invariance",
        entity_hints=["concept:task"],
    )
    assert resp["ok"] is True

    summary = srv.run_request_summary(top_k=5)
    assert summary["ok"] is True
    compat = summary["compat_alias_usage"]
    assert compat["total_calls"] == 1
    assert compat["distinct_aliases"] == 1
    assert compat["aliases"] == [
        {
            "alias_name": "kg_detect_contradiction_motifs",
            "canonical_name": "kg_probe",
            "count": 1,
            "first_used_at": compat["aliases"][0]["first_used_at"],
            "last_used_at": compat["aliases"][0]["last_used_at"],
            "last_param_keys": ["claim", "entity_hints", "hypothesis", "max_results"],
        }
    ]


def test_loop_profile_get_returns_external_coding_harness():
    from brain_researcher.services.mcp import server as srv

    resp = srv.loop_profile_get()
    assert resp["ok"] is True
    profile = resp["profile"]
    assert profile["profile_id"] == "external_coding_v1"
    assert profile["mutation_policy"]["mcp_edits_repo"] is False
    assert profile["clarification_policy"]["mode"] == "single_question_blocking"
    assert profile["clarification_policy"]["question_extraction_order"] == [
        "metadata.questions[0]",
        "question",
    ]
    assert profile["clarification_policy"]["block_execution_until_answered"] is True
    assert profile["clarification_policy"]["resume_with_accumulated_answers"] is True
    assert (
        "Ask only one clarification question per turn."
        in profile["clarification_policy"]["rules"]
    )
    assert "run_compare" in profile["recommended_call_order"]


def test_loop_profile_get_rejects_unknown_profile():
    from brain_researcher.services.mcp import server as srv

    resp = srv.loop_profile_get("missing-profile")
    assert resp["ok"] is False
    assert "unknown loop profile" in resp["error"]


def test_startup_hard_health_checks_strict_dependency_failure(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "_assert_run_root_writable", lambda _path: None)
    monkeypatch.setattr(srv, "STARTUP_STRICT_DEPENDENCIES", True)
    monkeypatch.setattr(
        srv,
        "_dependency_status_snapshot",
        lambda: {
            "run_root": {"path": "/tmp", "writable": True, "error": None},
            "neo4j": {
                "configured": True,
                "uri": "bolt://localhost:7687",
                "active_check": {"reachable": False, "error": "connection_refused"},
            },
        },
    )

    with pytest.raises(RuntimeError, match="Configured Neo4j dependency failed"):
        srv._startup_hard_health_checks()


def test_startup_hard_health_checks_non_strict_allows_unreachable_dependency(
    monkeypatch,
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "_assert_run_root_writable", lambda _path: None)
    monkeypatch.setattr(srv, "STARTUP_STRICT_DEPENDENCIES", False)
    monkeypatch.setattr(
        srv,
        "_dependency_status_snapshot",
        lambda: {
            "run_root": {"path": "/tmp", "writable": True, "error": None},
            "neo4j": {
                "configured": True,
                "uri": "bolt://localhost:7687",
                "active_check": {"reachable": False, "error": "connection_refused"},
            },
        },
    )

    status = srv._startup_hard_health_checks()
    assert status["neo4j"]["configured"] is True
    assert status["neo4j"]["active_check"]["reachable"] is False


def test_system_self_test_quick_mode_passes_with_inventory(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "MCP_SELFTEST_ENABLED", True)
    monkeypatch.setattr(srv, "server_info", lambda: {"ok": True, "data": {}})

    def _fake_tool_search(**kwargs):
        query = kwargs.get("query", "")
        if query == "workflow":
            return {"ok": True, "count": 3, "tools": []}
        return {
            "ok": True,
            "count": 2,
            "tools": [
                {
                    "name": "extract_timeseries",
                    "backend": "python",
                    "kind": "atomic",
                    "implementation_level": "production",
                },
                {
                    "name": "workflow_rest_connectome_e2e",
                    "backend": "python",
                    "kind": "workflow",
                    "implementation_level": "production",
                },
            ],
        }

    monkeypatch.setattr(srv, "tool_search", _fake_tool_search)

    resp = srv.system_self_test(mode="quick", inventory_limit=2)

    assert resp["ok"] is True, resp
    assert resp["overall"] == "pass"
    assert resp["counts"]["fail"] == 0
    assert resp["counts"]["warn"] == 0
    assert len(resp["inventory"]) == 2


def test_system_self_test_active_mode_degraded_on_kg_or_container_warn(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "MCP_SELFTEST_ENABLED", True)
    monkeypatch.setattr(srv, "server_info", lambda: {"ok": True, "data": {}})
    monkeypatch.setattr(
        srv,
        "tool_search",
        lambda **_kwargs: {"ok": True, "count": 1, "tools": []},
    )
    monkeypatch.setattr(
        srv, "kg_search_nodes", lambda **_kwargs: {"ok": False, "error": "neo4j_down"}
    )

    def _fake_local_probe(probe: str):
        if probe == "script":
            return {"ok": True, "payload": {"ok": True, "probe": "script"}}
        return {
            "ok": False,
            "error": "container_runtime_or_cvmfs_unavailable",
            "payload": {"ok": False, "probe": "container"},
            "policy_issues": [],
        }

    monkeypatch.setattr(srv, "_selftest_run_local_probe", _fake_local_probe)

    resp = srv.system_self_test(
        mode="active",
        include_kg=True,
        include_script=True,
        include_container=True,
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["overall"] == "degraded"
    assert resp["counts"]["fail"] == 0
    assert resp["counts"]["warn"] >= 1


def test_system_self_test_propagates_script_policy_issues(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "MCP_SELFTEST_ENABLED", True)
    monkeypatch.setattr(srv, "server_info", lambda: {"ok": True, "data": {}})
    monkeypatch.setattr(
        srv,
        "tool_search",
        lambda **_kwargs: {"ok": True, "count": 1, "tools": []},
    )
    monkeypatch.setattr(
        srv,
        "_selftest_run_local_probe",
        lambda _probe: {
            "ok": False,
            "error": "tool_not_allowlisted",
            "policy_issues": [{"code": "tool_not_allowlisted", "step_id": "s1"}],
            "script_path": "/tmp/probe.py",
            "run_id": "br_test",
        },
    )

    resp = srv.system_self_test(
        mode="active",
        include_kg=False,
        include_script=True,
        include_container=False,
    )
    assert resp["ok"] is False
    assert resp["overall"] == "fail"
    script_probe = next(p for p in resp["probes"] if p.get("id") == "script_probe")
    assert script_probe["status"] == "fail"
    assert script_probe["policy_issues"][0]["code"] == "tool_not_allowlisted"


def test_system_self_test_strict_promotes_warn_to_fail(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "MCP_SELFTEST_ENABLED", True)
    monkeypatch.setattr(srv, "server_info", lambda: {"ok": True, "data": {}})
    monkeypatch.setattr(
        srv,
        "tool_search",
        lambda **_kwargs: {"ok": True, "count": 1, "tools": []},
    )
    monkeypatch.setattr(
        srv, "kg_search_nodes", lambda **_kwargs: {"ok": False, "error": "neo4j_down"}
    )

    resp = srv.system_self_test(
        mode="active",
        include_kg=True,
        include_script=False,
        include_container=False,
        strict=True,
    )

    assert resp["ok"] is False
    assert resp["overall"] == "fail"
    assert resp["counts"]["warn"] == 0
    assert resp["counts"]["fail"] >= 1
    kg_probe = next(p for p in resp["probes"] if p.get("id") == "kg_probe")
    assert kg_probe["strict_escalated"] is True


def test_tool_requires_network_allows_local_openneuro_catalog_tools():
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    spec = ToolSpec(
        name="openneuro.search",
        description="local OpenNeuro catalog search",
        backend="python",
        tags=["openneuro"],
    )

    assert srv._tool_requires_network(spec) is False


def test_tool_requires_network_blocks_non_local_openneuro_tools():
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    spec = ToolSpec(
        name="openneuro_list_files",
        description="remote OpenNeuro listing",
        backend="python",
    )

    assert srv._tool_requires_network(spec) is True


def test_tool_search_structured_marks_toolspec_availability(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as qs

    class StubRegistry:
        def get_tool(self, tool_id):
            raise AssertionError(
                f"tool_search_structured should not call get_tool({tool_id})"
            )

        def get_toolspec_by_name(self, tool_id):
            return object() if tool_id == "encoding_models" else None

        def is_tool_runtime_callable(self, tool_id):
            return tool_id == "encoding_models"

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(
        qs,
        "search_tools_structured",
        lambda **_kwargs: {
            "candidates": [{"tool_id": "encoding_models"}],
            "recommendation": {"tool_id": "encoding_models"},
            "source": "catalog_fallback",
            "confidence": "low",
        },
    )

    resp = srv.tool_search_structured(query="encoding", force_fallback=True)
    assert resp["ok"] is True, repr(resp)
    data = resp["data"]
    cand = data["candidates"][0]
    rec = data["recommendation"]
    assert data["resolver_mode"] == "catalog_fallback"
    assert data["fallback_reason"] == "force_fallback"
    assert cand["available"] is True
    assert cand["available_runtime"] is True
    assert cand["availability_source"] == "toolspec_registry"
    assert rec["available"] is True
    assert rec["available_runtime"] is True


def test_tool_search_structured_canonicalizes_legacy_tool_ids(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as qs

    class StubRegistry:
        def get_tool(self, tool_id):
            raise AssertionError(
                f"tool_search_structured should not call get_tool({tool_id})"
            )

        def get_toolspec_by_name(self, tool_id):
            return object() if tool_id == "run_mriqc" else None

        def is_tool_runtime_callable(self, tool_id):
            return tool_id == "run_mriqc"

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(
        qs,
        "search_tools_structured",
        lambda **_kwargs: {
            "candidates": [{"tool_id": "bidsapp.mriqc.run"}],
            "recommendation": {"tool_id": "bidsapp.mriqc.run"},
            "source": "neurokg",
            "confidence": "high",
        },
    )

    resp = srv.tool_search_structured(query="mriqc")
    assert resp["ok"] is True, repr(resp)
    data = resp["data"]
    cand = data["candidates"][0]
    rec = data["recommendation"]
    assert cand["raw_tool_id"] == "bidsapp.mriqc.run"
    assert cand["tool_id"] == "run_mriqc"
    assert cand["canonical_tool_id"] == "run_mriqc"
    assert cand["available"] is True
    assert cand["available_runtime"] is True
    assert rec["raw_tool_id"] == "bidsapp.mriqc.run"
    assert rec["tool_id"] == "run_mriqc"
    assert rec["canonical_tool_id"] == "run_mriqc"
    assert rec["available"] is True
    assert rec["available_runtime"] is True


def test_tool_search_structured_folds_versioned_candidates_to_public_ids(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as qs

    class StubRegistry:
        def get_tool(self, tool_id):
            raise AssertionError(
                f"tool_search_structured should not call get_tool({tool_id})"
            )

        def get_toolspec_by_name(self, tool_id):
            return object() if tool_id in {"ants_registration", "fsl_flirt"} else None

        def is_tool_runtime_callable(self, tool_id):
            return tool_id in {"ants_registration", "fsl_flirt"}

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(
        qs,
        "search_tools_structured",
        lambda **_kwargs: {
            "candidates": [
                {"tool_id": "ants.2.5.3.antsRegistration.run", "score": 12},
                {"tool_id": "ants.2.5.3.antsApplyTransforms.run", "score": 11},
                {"tool_id": "ants_registration", "score": 10},
                {"tool_id": "fsl.6.0.4.flirt.run", "score": 9},
                {"tool_id": "fsl.6.0.4.featregapply.run", "score": 8},
            ],
            "recommendation": {
                "tool_id": "ants.2.5.3.antsRegistration.run",
                "score": 12,
            },
            "source": "neurokg",
            "confidence": "high",
        },
    )

    resp = srv.tool_search_structured(query="registration")
    assert resp["ok"] is True, repr(resp)
    data = resp["data"]

    assert [cand["tool_id"] for cand in data["candidates"][:2]] == [
        "ants_registration",
        "fsl_flirt",
    ]

    ants = data["candidates"][0]
    assert ants["support_count"] == 3
    assert ants["raw_tool_ids"] == [
        "ants.2.5.3.antsRegistration.run",
        "ants.2.5.3.antsApplyTransforms.run",
    ]
    assert ants["available"] is True
    assert ants["available_runtime"] is True

    flirt = data["candidates"][1]
    assert flirt["support_count"] == 2
    assert flirt["raw_tool_ids"] == [
        "fsl.6.0.4.flirt.run",
        "fsl.6.0.4.featregapply.run",
    ]
    assert flirt["available"] is True
    assert flirt["available_runtime"] is True

    rec = data["recommendation"]
    assert rec["tool_id"] == "ants_registration"
    assert rec["support_count"] == 3


def test_tool_resolve_marks_toolspec_availability(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as qs

    class StubRegistry:
        def get_tool(self, tool_id):
            raise AssertionError(f"tool_resolve should not call get_tool({tool_id})")

        def get_toolspec_by_name(self, tool_id):
            return object() if tool_id == "encoding_models" else None

        def is_tool_runtime_callable(self, tool_id):
            return tool_id == "encoding_models"

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(
        qs,
        "resolve_tool_structured",
        lambda **_kwargs: {
            "recommendation": {"tool_id": "encoding_models"},
            "source": "catalog_fallback",
            "confidence": "low",
        },
    )

    resp = srv.tool_resolve(op_key="encoding_model", force_fallback=True)
    assert resp["ok"] is True, repr(resp)
    data = resp["data"]
    rec = data["recommendation"]
    assert data["resolver_mode"] == "catalog_fallback"
    assert data["fallback_reason"] == "force_fallback"
    assert rec["available"] is True
    assert rec["available_runtime"] is True
    assert rec["availability_source"] == "toolspec_registry"


def test_tool_resolve_canonicalizes_legacy_tool_ids(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as qs

    class StubRegistry:
        def get_tool(self, tool_id):
            raise AssertionError(f"tool_resolve should not call get_tool({tool_id})")

        def get_toolspec_by_name(self, tool_id):
            return object() if tool_id == "run_mriqc" else None

        def is_tool_runtime_callable(self, tool_id):
            return tool_id == "run_mriqc"

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(
        qs,
        "resolve_tool_structured",
        lambda **_kwargs: {
            "recommendation": {"tool_id": "bidsapp.mriqc.run"},
            "source": "neurokg",
            "confidence": "high",
        },
    )

    resp = srv.tool_resolve(op_key="mriqc")
    assert resp["ok"] is True, repr(resp)
    data = resp["data"]
    rec = data["recommendation"]
    assert rec["raw_tool_id"] == "bidsapp.mriqc.run"
    assert rec["tool_id"] == "run_mriqc"
    assert rec["canonical_tool_id"] == "run_mriqc"
    assert rec["available"] is True
    assert rec["available_runtime"] is True


def test_redact_for_logging_respects_allowlist(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "REDACTION_MASK", "<redacted>")
    monkeypatch.setattr(srv, "REDACTION_ALLOWLIST", {"safe_token"})
    monkeypatch.setattr(srv, "REDACTION_DENYLIST", {"token", "password", "safe_token"})

    payload = {
        "token": "s3cr3t",
        "safe_token": "keep-me",
        "nested": {"password": "pw"},
    }
    redacted = srv._redact_for_logging(payload)

    assert redacted["token"] == "<redacted>"
    assert redacted["safe_token"] == "keep-me"
    assert redacted["nested"]["password"] == "<redacted>"


def _pipeline_execution_contract(
    *allowed_tools: str,
    approval_level: str = "confirm",
    run_mode_hint: str = "confirm_before_execute",
) -> dict[str, object]:
    return {
        "schema_version": "br-plan-execution-v1",
        "allowed_tools": list(allowed_tools),
        "approval_level": approval_level,
        "run_mode_hint": run_mode_hint,
    }


def test_pipeline_execute_redacts_sensitive_fields_in_logging_outputs(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        return ToolResult(
            status="success", data={"stdout": "hello", "stderr": ""}, error=None
        )

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    secret_token = "secret-token-123"
    secret_auth = "Bearer very-secret"
    resp = srv.pipeline_execute(
        {
            "steps": [
                {
                    "tool": "extract_timeseries",
                    "params": {
                        "img": "x",
                        "atlas": "y",
                        "api_key": secret_token,
                        "nested": {"authorization": secret_auth},
                    },
                }
            ],
            "execution": _pipeline_execution_contract("extract_timeseries"),
        },
        approval_phrase=srv.PIPELINE_EXECUTE_CONFIRM_PHRASE,
    )
    assert resp["ok"] is True, repr(resp)
    run_id = resp["run_id"]

    deadline = time.time() + 5.0
    status = None
    while time.time() < deadline:
        run = srv.run_get(run_id)
        assert run["ok"] is True
        status = run["run"]["status"]
        if status in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    assert status == "succeeded"

    run_dir = tmp_path / "runs" / run_id
    deadline = time.time() + 5.0
    while time.time() < deadline and not (run_dir / "observation.json").exists():
        time.sleep(0.05)

    provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
    trace_text = (run_dir / "trace.jsonl").read_text(encoding="utf-8")
    observation_text = (run_dir / "observation.json").read_text(encoding="utf-8")

    params = provenance["request"]["plan"]["steps"][0]["params"]
    assert params["api_key"] == "[REDACTED]"
    assert params["nested"]["authorization"] == "[REDACTED]"

    assert secret_token not in trace_text
    assert secret_auth not in trace_text
    assert secret_token not in observation_text
    assert secret_auth not in observation_text
    assert "[REDACTED]" in trace_text
    assert "[REDACTED]" in observation_text


def test_pipeline_execute_creates_run_and_logs(tmp_path, monkeypatch):
    # Route all run artifacts into a temp directory so tests are isolated.
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    # Avoid executing real tools in a background thread; keep run semantics deterministic.
    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        # Emit a small file inside output_dir so artifact listing can see something.
        if output_dir:
            from pathlib import Path

            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "ok.txt").write_text("ok")
        return ToolResult(
            status="success", data={"stdout": "hello", "stderr": ""}, error=None
        )

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    resp = srv.pipeline_execute(
        {
            "steps": [
                {"tool": "extract_timeseries", "params": {"img": "x", "atlas": "y"}}
            ],
            "execution": _pipeline_execution_contract("extract_timeseries"),
        },
        approval_phrase=srv.PIPELINE_EXECUTE_CONFIRM_PHRASE,
    )
    assert resp["ok"] is True
    run_id = resp["run_id"]

    # Poll until background thread finishes.
    deadline = time.time() + 5.0
    status = None
    while time.time() < deadline:
        run = srv.run_get(run_id)
        assert run["ok"] is True
        status = run["run"]["status"]
        if status in {"succeeded", "failed"}:
            break
        time.sleep(0.05)

    assert status == "succeeded"

    # Ensure logs were written.
    run_dir = tmp_path / "runs" / run_id
    assert (run_dir / "run.json").exists()
    assert any(p.name.endswith(".json") for p in (run_dir / "logs").iterdir())

    artifacts = srv.artifact_list(run_id)
    assert artifacts["ok"] is True
    assert any(item["relpath"].endswith("ok.txt") for item in artifacts["items"])

    # New helper tools: run listing + logs + artifact helpers.
    run_list = srv.run_list(limit=10)
    assert run_list["ok"] is True
    assert any(r.get("run_id") == run_id for r in run_list.get("runs", []))

    run_logs = srv.run_logs(run_id)
    assert run_logs["ok"] is True
    assert any(
        item["relpath"].startswith("logs/") for item in run_logs.get("items", [])
    )

    ok_art = next(
        item for item in artifacts["items"] if item["relpath"].endswith("ok.txt")
    )
    meta = srv.artifact_get_metadata(run_id, ok_art["relpath"], include_sha256=True)
    assert meta["ok"] is True
    assert meta["metadata"]["sha256"]

    blob = srv.artifact_read_bytes(run_id, ok_art["relpath"], max_bytes=32)
    assert blob["ok"] is True
    assert base64.b64decode(blob["bytes"]) == b"ok"

    info = srv.server_info()
    assert info["ok"] is True
    assert info["data"]["run_root"]

    metrics = srv.run_metrics(run_id)
    assert metrics["ok"] is True
    assert metrics["metrics"]["totals"]["steps"] == 1


def test_pipeline_execute_interpolates_prior_step_outputs(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult
    from brain_researcher.services.tools.spec import ToolSpec

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    def fake_get_toolspec_with_schema(tool_id: str):
        if tool_id == "fetch_atlas":
            return ToolSpec(
                name="fetch_atlas",
                description="stub",
                backend="python",
                python_class="json:loads",
                required=["atlas_name"],
            )
        if tool_id == "extract_timeseries":
            return ToolSpec(
                name="extract_timeseries",
                description="stub",
                backend="python",
                python_class="json:loads",
                required=["img", "atlas"],
            )
        return None

    monkeypatch.setattr(srv, "_get_toolspec_with_schema", fake_get_toolspec_with_schema)

    calls = []

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        calls.append((tool_id, dict(parameters)))
        if tool_id == "fetch_atlas":
            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "atlas_path": "/mounted/atlases/Schaefer2018_100.nii.gz"
                    }
                },
            )
        return ToolResult(status="success", data={"stdout": "", "stderr": ""})

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    resp = srv.pipeline_execute(
        {
            "steps": [
                {
                    "name": "fetch_atlas_100",
                    "tool": "fetch_atlas",
                    "params": {"atlas_name": "Schaefer2018_100"},
                },
                {
                    "tool": "extract_timeseries",
                    "params": {
                        "img": "bold.nii.gz",
                        "atlas": "{fetch_atlas_100.atlas_path}",
                        "notes": "${steps.fetch_atlas_100.data.outputs.atlas_path}",
                    },
                },
            ],
            "execution": _pipeline_execution_contract(
                "fetch_atlas", "extract_timeseries"
            ),
        },
        approval_phrase=srv.PIPELINE_EXECUTE_CONFIRM_PHRASE,
    )
    assert resp["ok"] is True

    deadline = time.time() + 5.0
    status = None
    while time.time() < deadline:
        run = srv.run_get(resp["run_id"])
        assert run["ok"] is True
        status = run["run"]["status"]
        if status in {"succeeded", "failed"}:
            break
        time.sleep(0.05)

    assert status == "succeeded"
    assert calls[0][0] == "fetch_atlas"
    assert calls[1][0] == "extract_timeseries"
    assert calls[1][1]["atlas"] == "/mounted/atlases/Schaefer2018_100.nii.gz"
    assert calls[1][1]["notes"] == "/mounted/atlases/Schaefer2018_100.nii.gz"


def test_pipeline_execute_workspace_layout_under_project_root(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path / "run_root")
    monkeypatch.setattr(
        srv,
        "ALLOWED_ROOTS",
        [(tmp_path / "run_root").resolve(), (tmp_path / "workspace").resolve()],
    )
    srv._ensure_dirs()

    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        if output_dir:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "ok.txt").write_text("ok")
        return ToolResult(
            status="success", data={"stdout": "hello", "stderr": ""}, error=None
        )

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    resp = srv.pipeline_execute(
        {
            "project_root": str(tmp_path / "workspace"),
            "run_tag": "mindvis-test",
            "steps": [
                {"tool": "extract_timeseries", "params": {"img": "x", "atlas": "y"}}
            ],
            "execution": _pipeline_execution_contract("extract_timeseries"),
        },
        approval_phrase=srv.PIPELINE_EXECUTE_CONFIRM_PHRASE,
    )

    assert resp["ok"] is True
    workspace = Path(resp["run_workspace"])
    assert workspace == (tmp_path / "workspace" / "runs" / "mindvis-test")

    deadline = time.time() + 5.0
    status = None
    while time.time() < deadline:
        run = srv.run_get(resp["run_id"])
        assert run["ok"] is True
        status = run["run"]["status"]
        if status in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    assert status == "succeeded"

    for rel in (
        "00_manifest",
        "01_inputs",
        "02_cache",
        "03_work",
        "04_artifacts",
        "05_reports",
        "06_logs",
        "07_figures",
        "08_exports",
    ):
        assert (workspace / rel).exists()

    assert any((workspace / "04_artifacts").rglob("ok.txt"))


def test_pipeline_execute_dry_run_skips_execution(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    called = {"count": 0}
    thread_called = {"count": 0}

    def fail_if_called(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("execute_tool should not be called in dry_run")

    def fail_if_thread_started(*args, **kwargs):
        thread_called["count"] += 1
        raise AssertionError("background thread should not be started in dry_run")

    monkeypatch.setattr(srv, "execute_tool", fail_if_called)
    monkeypatch.setattr(srv.threading, "Thread", fail_if_thread_started)

    resp = srv.pipeline_execute(
        {
            "steps": [
                {"tool": "extract_timeseries", "params": {"img": "x", "atlas": "y"}}
            ]
        },
        dry_run=True,
    )
    assert resp["ok"] is True
    assert resp["status"] == "succeeded"
    run_id = resp["run_id"]

    deadline = time.time() + 5.0
    run = None
    while time.time() < deadline:
        run = srv.run_get(run_id)
        assert run["ok"] is True
        if run["run"]["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)

    assert run is not None
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["dry_run"] is True
    assert run["run"]["steps"][0]["status"] == "skipped"
    assert called["count"] == 0
    assert thread_called["count"] == 0

    run_dir = tmp_path / "runs" / run_id
    step_work = run_dir / "work" / "step-01-s1"
    step_art = run_dir / "artifacts" / "step-01-s1"
    assert not step_work.exists()
    assert not step_art.exists()

    logs = srv.artifact_read_text(run_id, "logs/step-01-s1.json")
    assert logs["ok"] is True
    payload = json.loads(logs["text"])
    assert payload["status"] == "success"
    assert payload["metadata"]["execution_mode"] == "dry_run_no_exec"
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["would_execute"]["tool_id"] == "extract_timeseries"


def test_pipeline_execute_requires_confirmation_phrase_for_confirm_contract(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    called = {"count": 0}

    def fail_if_called(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("execute_tool should not be called without confirmation")

    monkeypatch.setattr(srv, "execute_tool", fail_if_called)

    resp = srv.pipeline_execute(
        {
            "steps": [
                {"tool": "extract_timeseries", "params": {"img": "x", "atlas": "y"}}
            ],
            "execution": _pipeline_execution_contract("extract_timeseries"),
        }
    )

    assert resp["ok"] is False
    assert resp["error"] == "execution_confirmation_required"
    assert "approval_phrase" in resp["message"]
    assert called["count"] == 0


def test_pipeline_execute_requires_execution_contract_for_non_dry_run(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    called = {"count": 0}

    def fail_if_called(*args, **kwargs):
        called["count"] += 1
        raise AssertionError(
            "execute_tool should not be called without execution contract"
        )

    monkeypatch.setattr(srv, "execute_tool", fail_if_called)

    resp = srv.pipeline_execute(
        {
            "steps": [
                {"tool": "extract_timeseries", "params": {"img": "x", "atlas": "y"}}
            ]
        }
    )

    assert resp["ok"] is False
    assert resp["error"] == "execution_contract_required"
    assert any(
        i.get("code") == "execution_contract_required" for i in resp.get("issues", [])
    )
    assert "plan.execution" in resp["message"]
    assert called["count"] == 0

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "failed"
    assert run["run"]["steps"][0]["error"] == "execution_contract_required"


def test_pipeline_execute_recipe_required_contract_rejects_direct_execution(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    called = {"count": 0}

    def fail_if_called(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("execute_tool should not be called for recipe_required")

    monkeypatch.setattr(srv, "execute_tool", fail_if_called)

    resp = srv.pipeline_execute(
        {
            "steps": [
                {
                    "tool": "workflow_fmriprep_preprocessing",
                    "params": {"dataset_ref": "ds000114"},
                }
            ],
            "execution": _pipeline_execution_contract(
                "workflow_fmriprep_preprocessing",
                approval_level="none",
                run_mode_hint="recipe_required",
            ),
        }
    )

    assert resp["ok"] is False
    assert resp["error"] == "execution_recipe_required"
    assert "get_execution_recipe" in resp["message"]
    assert called["count"] == 0


def test_pipeline_execute_plan_invalid_surfaces_policy_issues_with_step_binding(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    run_root = tmp_path / "run_root"
    monkeypatch.setattr(srv, "RUN_ROOT", run_root)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [run_root.resolve()])
    srv._ensure_dirs()

    resp = srv.pipeline_execute(
        {
            "steps": [
                {
                    "tool": "extract_timeseries",
                    "params": {"img": "x", "atlas": "y"},
                    "work_dir": str(tmp_path / "outside_allowed_root"),
                }
            ]
        },
        dry_run=True,
    )

    assert resp["ok"] is False
    assert resp["error"] == "plan_invalid"
    assert any(i.get("code") == "path_not_allowed" for i in resp.get("issues", []))
    assert any(
        i.get("code") == "path_not_allowed" for i in resp.get("policy_issues", [])
    )

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    step = run["run"]["steps"][0]
    assert any(
        i.get("code") == "path_not_allowed" for i in step.get("policy_issues", [])
    )


def test_tool_execute_preview_python_backend_returns_synthetic_success(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"extract_timeseries"},
    )

    called = {"count": 0}

    def fail_if_called(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("execute_tool should not run for preview rejection")

    monkeypatch.setattr(srv, "execute_tool", fail_if_called)

    resp = srv.tool_execute(
        "extract_timeseries",
        params={"img": "x", "atlas": "y"},
        preview=True,
    )
    assert resp["ok"] is True
    assert resp["result"]["status"] == "success"
    assert resp["result"]["data"]["preview"] is True
    assert resp["result"]["data"]["synthetic_preview"] is True
    assert resp["result"]["data"]["executed"] is False
    assert resp["result"]["metadata"]["preview_mode"] == "synthetic_non_executing"
    assert any(
        i.get("code") == "preview_not_supported_for_backend"
        and i.get("level") == "warning"
        for i in resp.get("issues", [])
    )
    assert any(
        "synthetic and non-executing" in str(w) for w in resp.get("warnings", [])
    )
    assert called["count"] == 0

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["steps"][0]["status"] == "succeeded"
    assert run["run"]["steps"][0]["error"] is None
    assert run["run"]["steps"][0]["result_path"]


def test_tool_execute_preview_python_backend_still_applies_preflight(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"extract_timeseries"},
    )

    called = {"count": 0}

    def fail_if_called(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("execute_tool should not run when preflight fails")

    monkeypatch.setattr(srv, "execute_tool", fail_if_called)

    resp = srv.tool_execute(
        "extract_timeseries",
        params={"img": "x"},
        preview=True,
    )

    assert resp["ok"] is False
    assert resp["error"] == "params_invalid"
    assert any(
        i.get("code") == "params_missing_required" for i in resp.get("issues", [])
    )
    assert called["count"] == 0

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "failed"
    assert run["run"]["steps"][0]["status"] == "failed"


def test_tool_execute_coordinate_to_concept_accepts_hosted_execution_context(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"coordinate_to_concept"},
        use_real_toolspec_lookup=True,
    )

    mock_mapper = Mock()
    mock_mapper._loaded = True
    mock_mapper.map_with_metadata.return_value = {
        "mappings": [
            {
                "coordinate": (0.0, 20.0, 40.0),
                "backend": "full",
                "concepts": [
                    {
                        "concept": "cognitive control",
                        "score": 0.91,
                        "process": "Control",
                        "source_tasks": ["stroop"],
                    }
                ],
            }
        ],
        "backend": "full",
        "backend_counts": {"full": 1},
        "errors": [],
        "niclip_data_path": "/tmp/niclip",
        "niclip_model_path": "/tmp/model.pth",
    }

    monkeypatch.setattr(
        "brain_researcher.services.neurokg.etl.mappers.niclip_spatial_mapper_improved.get_improved_mapper",
        lambda: mock_mapper,
    )

    resp = srv.tool_execute(
        "coordinate_to_concept",
        params={"coordinates": [[0, 20, 40]], "radius": 10, "top_k": 3},
    )

    assert resp["ok"] is True
    assert resp.get("error") is None
    assert resp["result"]["status"] == "success"
    assert resp["result"]["data"]["n_coordinates"] == 1
    assert resp["result"]["metadata"]["tool"] == "coordinate_to_concept"


def test_execute_tool_with_timeout_returns_quickly_on_timeout(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    def slow_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del tool_id, parameters, work_dir, output_dir, preview
        time.sleep(1.2)
        return ToolResult(status="success", data={"ok": True}, error=None)

    monkeypatch.setattr(srv, "execute_tool", slow_execute_tool)
    monkeypatch.setattr(srv, "_resolve_tool_timeout", lambda _spec=None: 0.05)

    start = time.perf_counter()
    result = srv._execute_tool_with_timeout(
        tool_id="extract_timeseries",
        params={"img": "x", "atlas": "y"},
        work_dir=str(tmp_path),
        output_dir=str(tmp_path),
        preview=False,
        spec=None,
    )
    elapsed = time.perf_counter() - start

    assert result.status == "error"
    assert result.error == "tool_timeout_after_0.05s"
    assert result.metadata is not None
    assert result.metadata.get("timeout_outcome") == "timed_out_stopped"
    assert elapsed < 1.0


def test_execute_tool_with_timeout_stops_before_side_effect(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    marker = tmp_path / "timeout_marker.txt"

    def slow_side_effect_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del tool_id, parameters, work_dir, output_dir, preview
        time.sleep(0.8)
        marker.write_text("done", encoding="utf-8")
        return ToolResult(status="success", data={"ok": True}, error=None)

    monkeypatch.setattr(srv, "execute_tool", slow_side_effect_tool)
    monkeypatch.setattr(srv, "_resolve_tool_timeout", lambda _spec=None: 0.05)

    result = srv._execute_tool_with_timeout(
        tool_id="extract_timeseries",
        params={"img": "x", "atlas": "y"},
        work_dir=str(tmp_path),
        output_dir=str(tmp_path),
        preview=False,
        spec=None,
    )

    assert result.status == "error"
    assert result.metadata is not None
    assert result.metadata.get("timeout_outcome") == "timed_out_stopped"

    # If the timeout path truly stops execution, this file should never appear.
    time.sleep(0.2)
    assert marker.exists() is False


def test_execute_tool_with_timeout_kills_spawned_child_process(tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("process-group timeout termination is POSIX-specific")

    import subprocess
    import sys

    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    marker = tmp_path / "timeout_child_marker.txt"
    child_script = (
        "import pathlib,time;"
        "time.sleep(0.35);"
        f"pathlib.Path({str(marker)!r}).write_text('orphan', encoding='utf-8')"
    )

    def tool_spawns_child(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del tool_id, parameters, work_dir, output_dir, preview
        subprocess.Popen([sys.executable, "-c", child_script])
        time.sleep(1.0)
        return ToolResult(status="success", data={"ok": True}, error=None)

    monkeypatch.setattr(srv, "execute_tool", tool_spawns_child)
    monkeypatch.setattr(srv, "_resolve_tool_timeout", lambda _spec=None: 0.05)
    monkeypatch.setattr(srv, "_resolve_timeout_cancel_grace", lambda: 0.05)
    monkeypatch.setattr(srv, "_resolve_timeout_kill_grace", lambda: 0.05)

    result = srv._execute_tool_with_timeout(
        tool_id="extract_timeseries",
        params={"img": "x", "atlas": "y"},
        work_dir=str(tmp_path),
        output_dir=str(tmp_path),
        preview=False,
        spec=None,
    )

    assert result.status == "error"
    assert result.metadata is not None
    assert result.metadata.get("timeout_outcome") == "timed_out_stopped"

    # Child side effect should never appear if worker process group was stopped.
    time.sleep(0.7)
    assert marker.exists() is False


def test_agent_fallback_retries_tools_run_endpoint_on_405(monkeypatch):
    from urllib.error import HTTPError

    from brain_researcher.services.mcp import server as srv

    class _Resp:
        def __init__(self, body: dict):
            self._body = json.dumps(body).encode("utf-8")

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(req, timeout=0):  # noqa: ARG001
        if req.full_url.endswith("/tools/execute"):
            raise HTTPError(
                req.full_url,
                405,
                "Method Not Allowed",
                hdrs=None,
                fp=io.BytesIO(b"<html>405</html>"),
            )
        assert req.full_url.endswith("/tools/run")
        return _Resp({"result": {"status": "success", "data": {"ok": True}}})

    monkeypatch.setattr(srv, "AGENT_API_URL", "http://agent:8000")
    monkeypatch.setattr(srv, "AGENT_FALLBACK_PATHS", ["/tools/execute", "/tools/run"])
    monkeypatch.setattr(srv.urllib_request, "urlopen", _fake_urlopen)

    resp = srv._forward_tool_execute_to_agent(
        tool_id="niwrap_search",
        params={"query": "bet"},
        work_dir="/tmp/w",
        output_dir="/tmp/o",
        preview=False,
        fallback_reason="local_runtime_missing",
    )

    assert resp.status == "success"
    assert isinstance(resp.metadata, dict)
    assert resp.metadata.get("forward_target") == "http://agent:8000/tools/run"
    assert resp.metadata.get("attempted_endpoints") == [
        "http://agent:8000/tools/execute",
        "http://agent:8000/tools/run",
    ]


def test_resolve_agent_api_url_prefers_shared_agent_envs(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setenv("AGENT_API_URL", "http://legacy-agent:8000")
    monkeypatch.setenv("AGENT_URL", "http://agent-url:8000")
    monkeypatch.setenv("AGENT_BASE_URL", "http://agent-base:8000")
    monkeypatch.setenv("BR_AGENT_URL", "http://internal-agent:8000")

    assert srv._resolve_agent_api_url() == "http://internal-agent:8000"


def test_agent_fallback_failure_metadata_uses_actual_forward_target(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    monkeypatch.setattr(srv, "_resolve_tool_timeout", lambda _spec=None: 0)
    monkeypatch.setattr(srv, "_should_attempt_agent_fallback", lambda **_kwargs: True)
    monkeypatch.setattr(
        srv,
        "execute_tool",
        lambda *args, **kwargs: ToolResult(
            status="error", error="local_runtime_failed", metadata={}
        ),
    )
    monkeypatch.setattr(
        srv,
        "_forward_tool_execute_to_agent",
        lambda **_kwargs: ToolResult(
            status="error",
            error="agent_fallback_http_405",
            data={"detail": "Method Not Allowed"},
            metadata={
                "forward_target": "http://agent:8000/tools/run",
                "execution_mode": "agent_fallback",
            },
        ),
    )

    result = srv._execute_tool_with_timeout(
        tool_id="niwrap_search",
        params={"query": "bet"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
        preview=False,
        spec=None,
        allow_fallback=True,
    )

    assert result.status == "error"
    assert isinstance(result.metadata, dict)
    assert result.metadata.get("execution_mode") == "agent_fallback_failed"
    assert result.metadata.get("forward_target") == "http://agent:8000/tools/run"


def test_tool_execute_timeout_surfaces_outcome_and_auditable_error(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"extract_timeseries"},
    )
    monkeypatch.setattr(srv, "_resolve_tool_timeout", lambda _spec=None: 0.05)

    def slow_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del tool_id, parameters, work_dir, output_dir, preview
        time.sleep(1.2)
        return ToolResult(status="success", data={"ok": True}, error=None)

    monkeypatch.setattr(srv, "execute_tool", slow_execute_tool)

    resp = srv.tool_execute(
        "extract_timeseries",
        params={"img": "x", "atlas": "y"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is False
    assert "execution_stopped" in resp["error"]
    assert resp["execution_mode"] == "direct"
    assert "preflight_passed" in resp["execution_trace"]
    assert resp["result"]["metadata"]["timeout_outcome"] == "timed_out_stopped"
    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "failed"


def test_tool_execute_requires_enable_and_allowlist(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"extract_timeseries"},
    )

    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        return ToolResult(status="success", data={"tool_id": tool_id}, error=None)

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    blocked = srv.tool_execute("not.allowlisted", params={})
    assert blocked["ok"] is False
    assert blocked["error"] == "tool_not_allowlisted"
    assert any(
        i.get("code") == "tool_not_allowlisted"
        for i in blocked.get("policy_issues", [])
    )

    ok = srv.tool_execute(
        "extract_timeseries",
        params={"img": "x", "atlas": "y"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )
    assert ok["ok"] is True


def _write_mcp_neuroimage_registry(
    tmp_path,
    *,
    template_root=None,
    atlas_root=None,
    reference_root=None,
    neurosynth_root=None,
    openneuro_root=None,
    transform_root=None,
):
    import yaml

    families = []
    if template_root is not None or transform_root is not None:
        entries = []
        if template_root is not None:
            entries.extend(
                [
                    {
                        "asset_name": "local_volumetric_templates",
                        "current_state": "already_usable",
                        "evidence_paths": [str(template_root)],
                    },
                    {
                        "asset_name": "local_surface_templates",
                        "current_state": "already_usable",
                        "evidence_paths": [str(template_root)],
                    },
                ]
            )
        if transform_root is not None:
            entries.append(
                {
                    "asset_name": "regfusion_transform_files",
                    "current_state": "present_not_standardized",
                    "evidence_paths": [str(transform_root)],
                }
            )
        families.append(
            {
                "family_id": "templates_spaces_transforms",
                "entries": entries,
            }
        )
    if atlas_root is not None:
        families.append(
            {
                "family_id": "atlases_parcellations",
                "entries": [
                    {
                        "asset_name": "local_nilearn_atlas_cache",
                        "current_state": "already_usable",
                        "evidence_paths": [str(atlas_root)],
                    }
                ],
            }
        )
    if (
        reference_root is not None
        or neurosynth_root is not None
        or openneuro_root is not None
    ):
        entries = []
        if reference_root is not None:
            entries.append(
                {
                    "asset_name": "local_neuromaps_annotation_cache",
                    "current_state": "already_usable",
                    "evidence_paths": [str(reference_root)],
                }
            )
        if neurosynth_root is not None:
            entries.append(
                {
                    "asset_name": "local_neurosynth_and_nimare_assets",
                    "current_state": "already_usable",
                    "evidence_paths": [str(neurosynth_root)],
                }
            )
        if openneuro_root is not None:
            entries.append(
                {
                    "asset_name": "local_openneuro_glmfitlins_stat_map_corpus",
                    "current_state": "already_usable",
                    "evidence_paths": [str(openneuro_root)],
                }
            )
        families.append(
            {
                "family_id": "reference_maps_annotations",
                "entries": entries,
            }
        )

    registry_path = tmp_path / "neuroimage_assets_backlog.yaml"
    registry_path.write_text(
        yaml.safe_dump({"version": "test", "families": families}),
        encoding="utf-8",
    )
    return registry_path


def _write_mcp_nifti(path):
    import nibabel as nib
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    img = nib.Nifti1Image(np.zeros((2, 2, 2), dtype="float32"), affine=np.eye(4))
    nib.save(img, path)


def _write_mcp_surface_annot(path):
    import numpy as np
    from nibabel.freesurfer import io as fsio

    labels = np.array([0, 1, 1, 2, 2], dtype=np.int32)
    ctab = np.array(
        [
            [25, 5, 25, 0, 0],
            [125, 25, 125, 0, 0],
            [225, 5, 5, 0, 0],
        ],
        dtype=np.int32,
    )
    names = [b"unknown", b"net1", b"net2"]
    fsio.write_annot(path, labels, ctab, names)


def _write_mcp_gifti(path):
    import nibabel as nib
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    img = nib.gifti.GiftiImage(
        darrays=[nib.gifti.GiftiDataArray(np.zeros(5, dtype=np.float32))]
    )
    nib.save(img, path)


def _write_mcp_regfusion(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("0 0 0\n", encoding="utf-8")


def _write_mcp_bytes(path, payload=b"stub\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_tool_execute_resolve_space_uses_registry_backed_local_assets(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )

    template_root = tmp_path / "templates" / "MNI152"
    template_root.mkdir(parents=True, exist_ok=True)
    template_path = template_root / "tpl-MNI152NLin2009cAsym_res-2mm_T1w.nii.gz"
    mask_path = template_root / "tpl-MNI152NLin2009cAsym_res-2mm_desc-brain_mask.nii.gz"
    _write_mcp_nifti(template_path)
    _write_mcp_nifti(mask_path)
    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        template_root=template_root.parent,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_space"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_space",
        params={"space_name": "MNI152NLin2009cAsym"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["execution_mode"] == "direct"
    assert "preflight_passed" in resp["execution_trace"]
    assert resp["requested_tool_id"] == "resolve_space"
    assert resp["resolved_tool_id"] == "resolve_space"
    result = resp["result"]
    assert result["status"] == "success"
    outputs = result["data"]["outputs"]
    summary = result["data"]["summary"]
    assert outputs["template_volume"] == str(template_path)
    assert outputs["brain_mask"] == str(mask_path)
    assert summary["canonical_space"] == "MNI152NLin2009cAsym"
    assert summary["template_source"] == "registry_local_cache"

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["steps"][0]["status"] == "succeeded"


def test_tool_execute_resolve_neuroimage_asset_supports_auto_template(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )
    from brain_researcher.services.tools.reference_asset_registry import (
        clear_reference_asset_registry_cache,
    )

    template_root = tmp_path / "templates" / "MNI152"
    template_root.mkdir(parents=True, exist_ok=True)
    _write_mcp_nifti(template_root / "tpl-MNI152NLin2009cAsym_res-2mm_T1w.nii.gz")
    _write_mcp_nifti(
        template_root / "tpl-MNI152NLin2009cAsym_res-2mm_desc-brain_mask.nii.gz"
    )
    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        template_root=template_root.parent,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_neuroimage_asset"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_neuroimage_asset",
        params={"name": "MNI152"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["requested_tool_id"] == "resolve_neuroimage_asset"
    assert resp["resolved_tool_id"] == "resolve_neuroimage_asset"
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["summary"]["resolved_kind"] == "template"
    assert result["data"]["summary"]["resolver_tool"] == "resolve_space"
    assert "template_volume" in result["data"]["outputs"]


def test_tool_execute_resolve_transform_uses_registry_backed_local_assets(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )

    transform_root = tmp_path / "regfusion"
    left_path = transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-L_regfusion.txt"
    right_path = transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-R_regfusion.txt"
    _write_mcp_regfusion(left_path)
    _write_mcp_regfusion(right_path)
    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        transform_root=transform_root,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_transform"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_transform",
        params={
            "source_space": "MNI152",
            "target_space": "fsLR",
            "resolution": "32k",
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["execution_mode"] == "direct"
    assert "preflight_passed" in resp["execution_trace"]
    assert resp["requested_tool_id"] == "resolve_transform"
    assert resp["resolved_tool_id"] == "resolve_transform"
    result = resp["result"]
    assert result["status"] == "success"
    outputs = result["data"]["outputs"]
    summary = result["data"]["summary"]
    assert outputs["transform_left"].endswith("_hemi-L_regfusion.txt")
    assert outputs["transform_right"].endswith("_hemi-R_regfusion.txt")
    assert summary["asset_id"] == "warp.regfusion.mni152nlin2009casym.fslr.32k"
    assert summary["density"] == "32k"
    assert summary["source"] == "registry_local_cache"

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["steps"][0]["status"] == "succeeded"


def test_tool_execute_resolve_neuroimage_asset_supports_explicit_transform(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )

    transform_root = tmp_path / "regfusion"
    _write_mcp_regfusion(
        transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-L_regfusion.txt"
    )
    _write_mcp_regfusion(
        transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-R_regfusion.txt"
    )
    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        transform_root=transform_root,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_neuroimage_asset"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_neuroimage_asset",
        params={
            "kind": "transform",
            "source_space": "MNI152",
            "target_space": "fsLR",
            "resolution": "32k",
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["requested_tool_id"] == "resolve_neuroimage_asset"
    assert resp["resolved_tool_id"] == "resolve_neuroimage_asset"
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["summary"]["resolved_kind"] == "transform"
    assert result["data"]["summary"]["resolver_tool"] == "resolve_transform"
    assert result["data"]["outputs"]["transform_left"].endswith("_hemi-L_regfusion.txt")


def test_tool_execute_parcellation_fetch_uses_registry_backed_surface_assets(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )

    atlas_root = tmp_path / "atlases"
    label_dir = atlas_root / "Yeo_JNeurophysiol11_FreeSurfer" / "fsaverage5" / "label"
    label_dir.mkdir(parents=True, exist_ok=True)
    left_path = label_dir / "lh.Yeo2011_7Networks_N1000.annot"
    right_path = label_dir / "rh.Yeo2011_7Networks_N1000.annot"
    _write_mcp_surface_annot(left_path)
    _write_mcp_surface_annot(right_path)
    registry_path = _write_mcp_neuroimage_registry(tmp_path, atlas_root=atlas_root)

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"parcellation_fetch"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "parcellation_fetch",
        params={"atlas_name": "yeo", "space": "fsaverage"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["execution_mode"] == "direct"
    assert "preflight_passed" in resp["execution_trace"]
    assert resp["requested_tool_id"] == "parcellation_fetch"
    assert resp["resolved_tool_id"] == "parcellation_fetch"
    result = resp["result"]
    assert result["status"] == "success"
    outputs = result["data"]["outputs"]
    summary = result["data"]["summary"]
    assert outputs["surface_parcellation_left"].endswith(
        "lh.Yeo2011_7Networks_N1000.annot"
    )
    assert outputs["surface_parcellation_right"].endswith(
        "rh.Yeo2011_7Networks_N1000.annot"
    )
    assert outputs["labels_tsv"].endswith("_labels.tsv")
    assert summary["space_kind"] == "surface"
    assert summary["source"] == "registry_local_cache"
    assert summary["n_regions"] == 2

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["steps"][0]["status"] == "succeeded"


def test_tool_execute_resolve_reference_map_uses_registry_backed_surface_assets(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )
    from brain_researcher.services.tools.reference_asset_registry import (
        clear_reference_asset_registry_cache,
    )

    reference_root = tmp_path / "annotations"
    left_path = (
        reference_root
        / "hcps1200"
        / "myelinmap"
        / "fsLR"
        / "source-hcps1200_desc-myelinmap_space-fsLR_den-32k_hemi-L_feature.func.gii"
    )
    right_path = (
        reference_root
        / "hcps1200"
        / "myelinmap"
        / "fsLR"
        / "source-hcps1200_desc-myelinmap_space-fsLR_den-32k_hemi-R_feature.func.gii"
    )
    _write_mcp_gifti(left_path)
    _write_mcp_gifti(right_path)
    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        reference_root=reference_root,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    monkeypatch.setenv(
        "BR_ATLAS_OUTPUT_ROOT",
        str(tmp_path / "unused_shared_atlases"),
    )
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_reference_map"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_reference_map",
        params={"map_name": "myelinmap", "space": "fsLR", "resolution": "32k"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["execution_mode"] == "direct"
    assert "preflight_passed" in resp["execution_trace"]
    assert resp["requested_tool_id"] == "resolve_reference_map"
    assert resp["resolved_tool_id"] == "resolve_reference_map"
    result = resp["result"]
    assert result["status"] == "success"
    outputs = result["data"]["outputs"]
    summary = result["data"]["summary"]
    assert outputs["reference_map_left"].endswith("_hemi-L_feature.func.gii")
    assert outputs["reference_map_right"].endswith("_hemi-R_feature.func.gii")
    assert outputs["reference_map_files"] == [
        outputs["reference_map_left"],
        outputs["reference_map_right"],
    ]
    assert summary["space_kind"] == "surface"
    assert summary["density"] == "32k"
    assert summary["asset_id"] == ("neuromaps.annotation.hcps1200.myelinmap.fslr.32k")
    assert summary["source"] == "registry_local_cache"

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["steps"][0]["status"] == "succeeded"


def test_tool_execute_resolve_neuroimage_asset_supports_auto_reference_map(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )
    from brain_researcher.services.tools.reference_asset_registry import (
        clear_reference_asset_registry_cache,
    )

    reference_root = tmp_path / "annotations"
    _write_mcp_nifti(
        reference_root
        / "neurosynth"
        / "cogpc1"
        / "MNI152"
        / "source-neurosynth_desc-cogpc1_space-MNI152_res-2mm_feature.nii.gz"
    )
    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        reference_root=reference_root,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    monkeypatch.setenv(
        "BR_ATLAS_OUTPUT_ROOT",
        str(tmp_path / "unused_shared_atlases"),
    )
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_neuroimage_asset"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_neuroimage_asset",
        params={
            "name": "cogpc1",
            "space": "MNI152",
            "resolution": "2mm",
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["requested_tool_id"] == "resolve_neuroimage_asset"
    assert resp["resolved_tool_id"] == "resolve_neuroimage_asset"
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["summary"]["resolved_kind"] == "reference_map"
    assert result["data"]["summary"]["resolver_tool"] == "resolve_reference_map"
    assert result["data"]["outputs"]["reference_map"].endswith(
        "_res-2mm_feature.nii.gz"
    )


def _mock_resolve_dataset_asset_context(monkeypatch, tmp_path):
    from brain_researcher.services.tools import list_dataset_assets_tool as list_module
    from brain_researcher.services.tools import resolve_dataset_asset_tool as module

    bids_root = tmp_path / "ds000114"
    _write_mcp_bytes(
        bids_root / "dataset_description.json",
        b'{"Name":"Test","BIDSVersion":"1.9.0"}\n',
    )
    _write_mcp_bytes(
        bids_root / "participants.tsv",
        b"participant_id\tgroup\nsub-01\tcontrol\n",
    )
    _write_mcp_bytes(
        bids_root / "sub-01" / "func" / "sub-01_task-emotion_bold.nii.gz",
        b"bold\n",
    )
    _write_mcp_bytes(
        bids_root / "sub-01" / "func" / "sub-01_task-emotion_events.tsv",
        b"onset\tduration\ttrial_type\n0\t1\tgo\n",
    )

    fmriprep_root = tmp_path / "derivatives" / "fmriprep" / "ds000114"
    _write_mcp_bytes(
        fmriprep_root
        / "sub-01"
        / "func"
        / "sub-01_task-emotion_desc-confounds_timeseries.tsv",
        b"trans_x\ttrans_y\n0.1\t0.0\n",
    )
    glm_root = tmp_path / "derivatives" / "glmfitlins" / "ds000114"
    _write_mcp_bytes(
        glm_root
        / "task-emotion"
        / "node-subjectLevel"
        / "sub-01"
        / "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz",
        b"statmap\n",
    )
    _write_mcp_bytes(
        glm_root / "task-emotion" / "dataset_description.json",
        b'{"PipelineDescription":{"Version":"0.11.0","Parameters":{"space":"MNI152NLin2009cAsym"}}}\n',
    )

    resources = SimpleNamespace(
        bids_path=str(bids_root),
        derivatives={
            "fmriprep": str(fmriprep_root),
            "glmfitlins": str(glm_root),
        },
        remote_urls={"openneuro": "https://openneuro.org/datasets/ds000114"},
        size_bytes=123,
        is_bids_available=True,
        resolved_dataset_id="ds:openneuro:ds000114",
        resolution_mode="exact_simple_id",
        available_derivatives=["fmriprep", "glmfitlins"],
        analysis_goal="fmri-glm",
        readiness={"status": "ready"},
        source_repo="OpenNeuro",
        dataset_name="Emotion dataset",
        display_name="Emotion dataset",
        dataset_metadata={"tasks": ["emotion"], "modalities": ["fMRI"]},
    )

    monkeypatch.setattr(
        module.query_service,
        "dataset_resources",
        lambda *args, **kwargs: resources,
    )
    monkeypatch.setattr(
        list_module.query_service,
        "dataset_resources",
        lambda *args, **kwargs: resources,
    )
    return bids_root, fmriprep_root, glm_root


def test_tool_execute_resolve_dataset_asset_supports_auto_summary(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    bids_root, _fmriprep_root, _glm_root = _mock_resolve_dataset_asset_context(
        monkeypatch,
        tmp_path,
    )

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_dataset_asset"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_dataset_asset",
        params={"dataset_ref": "ds000114"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["requested_tool_id"] == "resolve_dataset_asset"
    assert resp["resolved_tool_id"] == "resolve_dataset_asset"
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["summary"]["resolved_kind"] == "dataset"
    assert result["data"]["outputs"]["bids_root"] == str(bids_root)
    assert result["data"]["outputs"]["dataset_description"].endswith(
        "dataset_description.json"
    )


def test_tool_execute_resolve_dataset_asset_supports_auto_bids_file(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    _mock_resolve_dataset_asset_context(monkeypatch, tmp_path)

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_dataset_asset"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_dataset_asset",
        params={
            "dataset_ref": "ds000114",
            "subject_id": "01",
            "datatype": "func",
            "suffix": "bold",
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["summary"]["resolved_kind"] == "bids"
    assert result["data"]["outputs"]["resolved_file"].endswith("_bold.nii.gz")
    assert Path(result["data"]["outputs"]["resolved_file"]).parent == tmp_path / "o"


def test_tool_execute_resolve_dataset_asset_supports_auto_confounds(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    _mock_resolve_dataset_asset_context(monkeypatch, tmp_path)

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_dataset_asset"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_dataset_asset",
        params={
            "dataset_ref": "ds000114",
            "asset_name": "confounds",
            "subject_id": "01",
            "task": "emotion",
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["summary"]["resolved_kind"] == "confounds"
    assert result["data"]["outputs"]["confounds_file"].endswith(
        "_desc-confounds_timeseries.tsv"
    )
    assert result["data"]["outputs"]["derivative_root"].endswith("/fmriprep/ds000114")


def test_tool_execute_list_dataset_assets_supports_targeted_browse(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    _mock_resolve_dataset_asset_context(monkeypatch, tmp_path)

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"list_dataset_assets"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "list_dataset_assets",
        params={
            "dataset_ref": "ds000114",
            "subject_id": "01",
            "task": "emotion",
            "contrast": "taskvbaseline",
            "statistic": "z",
            "include_metadata": True,
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["requested_tool_id"] == "list_dataset_assets"
    assert resp["resolved_tool_id"] == "list_dataset_assets"
    result = resp["result"]
    assert result["status"] == "success"
    assets = result["data"]["outputs"]["assets"]
    assert any(asset["kind"] == "events" for asset in assets)
    assert any(asset["kind"] == "confounds" for asset in assets)
    assert any(asset["kind"] == "stat_map" for asset in assets)
    assert result["data"]["summary"]["browse_kind"] == "all"
    assert Path(result["data"]["outputs"]["inventory_json"]).exists()


def test_tool_execute_list_dataset_assets_accepts_legacy_filter_aliases(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    _mock_resolve_dataset_asset_context(monkeypatch, tmp_path)

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"list_dataset_assets"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "list_dataset_assets",
        params={
            "dataset_ref": "ds000114",
            "asset_type": "derivatives",
            "derivative_type": "fmriprep",
            "subject_id": "01",
            "session_id": "ses-func01",
            "task": "emotion",
            "datatype": "func",
            "suffix": "bold",
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["summary"]["browse_kind"] == "derivative"
    assert result["data"]["summary"]["count"] == 1
    assert result["data"]["outputs"]["assets"][0]["derivative_kind"] == "fmriprep"


def test_tool_execute_list_dataset_assets_accepts_scope_query_and_subject_session_aliases(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    _mock_resolve_dataset_asset_context(monkeypatch, tmp_path)

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"list_dataset_assets"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "list_dataset_assets",
        params={
            "dataset_ref": "ds000114",
            "scope": "derivatives",
            "query": "fmriprep",
            "subject": "01",
            "session": "ses-func01",
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["summary"]["browse_kind"] == "derivative"
    assert result["data"]["summary"]["query"] == "fmriprep"
    assert result["data"]["summary"]["filters"]["subject_id"] == "sub-01"
    assert result["data"]["summary"]["filters"]["session_id"] == "ses-func01"
    assert result["data"]["summary"]["count"] == 1
    assert result["data"]["outputs"]["assets"][0]["derivative_kind"] == "fmriprep"


def test_tool_execute_list_dataset_assets_rejects_conflicting_scope_aliases(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    _mock_resolve_dataset_asset_context(monkeypatch, tmp_path)

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"list_dataset_assets"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "list_dataset_assets",
        params={
            "dataset_ref": "ds000114",
            "kind": "dataset",
            "scope": "derivatives",
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is False, repr(resp)
    result = resp["result"]
    assert result["status"] == "error"
    assert "Conflicting kind" in result["error"]


def test_tool_execute_list_dataset_assets_rejects_unknown_params(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    _mock_resolve_dataset_asset_context(monkeypatch, tmp_path)

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"list_dataset_assets"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "list_dataset_assets",
        params={"dataset_ref": "ds000114", "unexpected_filter": "oops"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is False, repr(resp)
    result = resp["result"]
    assert result["status"] == "error"
    assert "unexpected_filter" in result["error"]


def test_validate_tool_params_list_dataset_assets_accepts_legacy_filter_aliases():
    from brain_researcher.services.mcp import server as srv

    spec = srv._get_registry().get_toolspec_by_name("list_dataset_assets")
    assert spec is not None
    enriched = srv._enrich_toolspec_schema(spec)
    properties = enriched.json_schema.get("properties", {})
    assert "asset_type" in properties
    assert "scope" in properties
    assert "query" in properties
    assert "derivative_type" in properties
    assert "subject" in properties
    assert "session" in properties

    issues = srv._validate_tool_params(
        "list_dataset_assets",
        enriched,
        {
            "dataset_ref": "ds000114",
            "scope": "derivatives",
            "query": "fmriprep",
            "subject": "01",
            "session": "ses-func01",
        },
    )

    assert issues == []


def test_validate_tool_params_list_dataset_assets_rejects_unknown_params():
    from brain_researcher.services.mcp import server as srv

    spec = srv._get_registry().get_toolspec_by_name("list_dataset_assets")
    assert spec is not None
    enriched = srv._enrich_toolspec_schema(spec)

    issues = srv._validate_tool_params(
        "list_dataset_assets",
        enriched,
        {"dataset_ref": "ds000114", "unexpected_filter": "oops"},
    )

    assert any(issue["code"] == "params_invalid" for issue in issues)
    assert any("unexpected_filter" in issue["message"] for issue in issues)


def test_tool_execute_list_dataset_assets_requests_filters_for_broad_stat_map_browse(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    _mock_resolve_dataset_asset_context(monkeypatch, tmp_path)

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"list_dataset_assets"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "list_dataset_assets",
        params={"dataset_ref": "ds000114", "kind": "stat_map"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["outputs"]["assets"] == []
    assert result["data"]["summary"]["needs_filters"] is True


def test_tool_execute_resolve_neuroimage_asset_supports_explicit_model_bundle(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.reference_asset_registry import (
        clear_reference_asset_registry_cache,
    )

    reference_root = tmp_path / "reference_assets"
    source_root = reference_root / "repos" / "cbig" / "Standalone_Nguyen2020_RNNAD"
    source_root.mkdir(parents=True, exist_ok=True)
    bundle_root = (
        reference_root
        / "materialized"
        / "model_bundles"
        / "model.longitudinal_progression.reference"
    )
    bundle_root.mkdir(parents=True, exist_ok=True)
    (bundle_root / "asset.json").write_text(
        json.dumps({"id": "model.longitudinal_progression.reference"}), encoding="utf-8"
    )
    (bundle_root / "source").symlink_to(source_root, target_is_directory=True)

    monkeypatch.setenv("BR_REFERENCE_ASSET_ROOTS", str(reference_root))
    clear_reference_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_neuroimage_asset"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_neuroimage_asset",
        params={
            "name": "model.longitudinal_progression.reference",
            "kind": "model_bundle",
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["requested_tool_id"] == "resolve_neuroimage_asset"
    assert resp["resolved_tool_id"] == "resolve_neuroimage_asset"
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["summary"]["resolved_kind"] == "model_bundle"
    assert result["data"]["summary"]["resolver_tool"] == "reference_asset_registry"
    outputs = result["data"]["outputs"]
    assert outputs["bundle_root"] == str(bundle_root)
    assert outputs["bundle_manifest"] == str(bundle_root / "asset.json")
    assert outputs["source_root"] == str(bundle_root / "source")

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["steps"][0]["status"] == "succeeded"


def test_tool_execute_resolve_reference_map_uses_registry_backed_openneuro_stat_maps(
    tmp_path, monkeypatch
):
    import json

    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )
    from brain_researcher.services.tools.reference_asset_registry import (
        clear_reference_asset_registry_cache,
    )

    openneuro_root = tmp_path / "openneuro_glmfitlins" / "stat_maps"
    stat_path = (
        openneuro_root
        / "ds000114"
        / "task-linebisection"
        / "node-subjectLevel"
        / "sub-01"
        / "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz"
    )
    _write_mcp_nifti(stat_path)
    (
        openneuro_root / "ds000114" / "task-linebisection" / "dataset_description.json"
    ).write_text(
        json.dumps(
            {
                "BIDSVersion": "1.1.0",
                "License": "CC0",
                "PipelineDescription": {
                    "Version": "0.11.0",
                    "Parameters": {"space": "MNI152NLin2009cAsym"},
                },
            }
        ),
        encoding="utf-8",
    )
    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        openneuro_root=openneuro_root,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_reference_map"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_reference_map",
        params={"map_name": "taskvbaseline", "space": "MNI152"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["requested_tool_id"] == "resolve_reference_map"
    assert resp["resolved_tool_id"] == "resolve_reference_map"
    result = resp["result"]
    assert result["status"] == "success"
    outputs = result["data"]["outputs"]
    summary = result["data"]["summary"]
    assert outputs["reference_map"].endswith(
        "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz"
    )
    assert summary["dataset_id"] == "ds000114"
    assert summary["task"] == "linebisection"
    assert summary["statistic"] == "z"
    assert summary["source"] == "registry_local_cache"

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["steps"][0]["status"] == "succeeded"


def test_tool_execute_resolve_reference_map_uses_registry_backed_neurosynth_bundle_assets(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )
    from brain_researcher.services.tools.reference_asset_registry import (
        clear_reference_asset_registry_cache,
    )

    neurosynth_root = tmp_path / "neurosynth_nimare"
    _write_mcp_bytes(neurosynth_root / "neurosynth_dataset_v7.pkl.gz")
    _write_mcp_bytes(neurosynth_root / "neurosynth_dataset_v7.json.gz")
    _write_mcp_bytes(
        neurosynth_root / "neurosynth" / "data-neurosynth_version-7_coordinates.tsv.gz"
    )
    _write_mcp_bytes(
        neurosynth_root / "neurosynth" / "data-neurosynth_version-7_metadata.tsv.gz"
    )
    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        neurosynth_root=neurosynth_root,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_reference_map"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_reference_map",
        params={"map_name": "nimare_dataset"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["requested_tool_id"] == "resolve_reference_map"
    assert resp["resolved_tool_id"] == "resolve_reference_map"
    result = resp["result"]
    assert result["status"] == "success"
    outputs = result["data"]["outputs"]
    summary = result["data"]["summary"]
    assert outputs["reference_map"].endswith("neurosynth_dataset_v7.pkl.gz")
    assert summary["asset_id"] == "neurosynth.nimare.dataset.v7"
    assert summary["bundle_kind"] == "dataset_v7"
    assert summary["source"] == "registry_local_cache"

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["steps"][0]["status"] == "succeeded"


def test_tool_execute_resolve_reference_map_uses_registry_backed_neurosynth_stat_maps(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )
    from brain_researcher.services.tools.reference_asset_registry import (
        clear_reference_asset_registry_cache,
    )

    neurosynth_root = tmp_path / "neurosynth_assets"
    stat_path = (
        neurosynth_root
        / "neurosynth_maps"
        / "terms_abstract_tfidf__attention"
        / "neurosynth_terms_abstract_tfidf__attention_z.nii.gz"
    )
    roi_summary = stat_path.parent / "roi_summary.tsv"
    _write_mcp_nifti(stat_path)
    roi_summary.write_text("term\tscore\nattention\t1.0\n", encoding="utf-8")
    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        neurosynth_root=neurosynth_root,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_reference_map"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "resolve_reference_map",
        params={"map_name": "attention", "space": "MNI152"},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    result = resp["result"]
    assert result["status"] == "success"
    outputs = result["data"]["outputs"]
    summary = result["data"]["summary"]
    assert outputs["reference_map"].endswith(
        "neurosynth_terms_abstract_tfidf__attention_z.nii.gz"
    )
    assert any(
        path.endswith("roi_summary.tsv") for path in outputs["reference_map_files"]
    )
    assert summary["source_dataset"] == "neurosynth"
    assert summary["statistic"] == "z"

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["steps"][0]["status"] == "succeeded"


def test_tool_execute_list_neuroimage_assets_supports_inventory_and_concrete_views(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )
    from brain_researcher.services.tools.reference_asset_registry import (
        clear_reference_asset_registry_cache,
    )

    reference_root = tmp_path / "annotations"
    _write_mcp_nifti(
        reference_root
        / "neurosynth"
        / "cogpc1"
        / "MNI152"
        / "source-neurosynth_desc-cogpc1_space-MNI152_res-2mm_feature.nii.gz"
    )
    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        reference_root=reference_root,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    monkeypatch.setenv(
        "BR_ATLAS_OUTPUT_ROOT",
        str(tmp_path / "unused_shared_atlases"),
    )
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"list_neuroimage_assets"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "list_neuroimage_assets",
        params={
            "view": "all",
            "family": "reference_maps_annotations",
            "include_metadata": True,
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["execution_mode"] == "direct"
    assert "preflight_passed" in resp["execution_trace"]
    assert resp["requested_tool_id"] == "list_neuroimage_assets"
    assert resp["resolved_tool_id"] == "list_neuroimage_assets"
    result = resp["result"]
    assert result["status"] == "success"
    outputs = result["data"]["outputs"]
    summary = result["data"]["summary"]
    assets = outputs["assets"]
    assert outputs["inventory_json"].endswith("neuroimage_asset_inventory.json")
    assert any(asset["kind"] == "reference_map" for asset in assets)
    assert any(asset["kind"] == "inventory_entry" for asset in assets)
    assert summary["view"] == "all"
    assert summary["family"] == "reference_maps_annotations"
    assert summary["total_matches"] >= 2

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["steps"][0]["status"] == "succeeded"


def test_tool_execute_list_neuroimage_assets_supports_stat_map_family_filter(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )
    from brain_researcher.services.tools.reference_asset_registry import (
        clear_reference_asset_registry_cache,
    )

    openneuro_root = tmp_path / "openneuro_glmfitlins" / "stat_maps"
    _write_mcp_nifti(
        openneuro_root
        / "ds000114"
        / "task-linebisection"
        / "node-subjectLevel"
        / "sub-01"
        / "sub-01_contrast-taskvbaseline_stat-z_statmap.nii.gz"
    )
    (
        openneuro_root / "ds000114" / "task-linebisection" / "dataset_description.json"
    ).write_text(
        json.dumps(
            {
                "PipelineDescription": {
                    "Version": "0.11.0",
                    "Parameters": {"space": "MNI152NLin2009cAsym"},
                }
            }
        ),
        encoding="utf-8",
    )
    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        openneuro_root=openneuro_root,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"list_neuroimage_assets"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "list_neuroimage_assets",
        params={
            "view": "concrete",
            "family": "stat_maps",
            "kind": "stat_map",
            "query": "taskvbaseline",
            "include_metadata": True,
        },
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    result = resp["result"]
    assert result["status"] == "success"
    assets = result["data"]["outputs"]["assets"]
    assert len(assets) == 1
    assert assets[0]["kind"] == "stat_map"
    assert assets[0]["subfamily_id"] == "stat_maps"
    assert assets[0]["metadata"]["contrast"] == "taskvbaseline"
    assert result["data"]["summary"]["subfamily_counts"]["stat_maps"] == 1


def test_tool_execute_list_neuroimage_assets_uses_registry_backed_inventory(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )
    from brain_researcher.services.tools.reference_asset_registry import (
        clear_reference_asset_registry_cache,
    )

    template_root = tmp_path / "templates" / "MNI152"
    template_root.mkdir(parents=True, exist_ok=True)
    _write_mcp_nifti(template_root / "tpl-MNI152NLin2009cAsym_res-2mm_T1w.nii.gz")
    _write_mcp_nifti(
        template_root / "tpl-MNI152NLin2009cAsym_res-2mm_desc-brain_mask.nii.gz"
    )

    atlas_root = tmp_path / "atlases"
    msdl_dir = atlas_root / "msdl_atlas" / "MSDL_rois"
    msdl_dir.mkdir(parents=True, exist_ok=True)
    _write_mcp_nifti(msdl_dir / "msdl_rois.nii")
    (msdl_dir / "msdl_rois_labels.csv").write_text(
        "x,y,z,name,net name\n-1,0,0,L Aud,Aud\n1,0,0,R Aud,Aud\n",
        encoding="utf-8",
    )

    reference_root = tmp_path / "annotations"
    _write_mcp_nifti(
        reference_root
        / "neurosynth"
        / "cogpc1"
        / "MNI152"
        / "source-neurosynth_desc-cogpc1_space-MNI152_res-2mm_feature.nii.gz"
    )

    transform_root = tmp_path / "regfusion"
    _write_mcp_regfusion(
        transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-L_regfusion.txt"
    )
    _write_mcp_regfusion(
        transform_root / "tpl-MNI152_space-fsLR_den-32k_hemi-R_regfusion.txt"
    )

    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        template_root=template_root.parent,
        atlas_root=atlas_root,
        reference_root=reference_root,
        transform_root=transform_root,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    monkeypatch.setenv(
        "BR_ATLAS_OUTPUT_ROOT",
        str(tmp_path / "unused_shared_atlases"),
    )
    clear_neuroimage_asset_registry_cache()
    clear_reference_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"list_neuroimage_assets"},
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "list_neuroimage_assets",
        params={"limit": 20},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True, repr(resp)
    assert resp["execution_mode"] == "direct"
    assert "preflight_passed" in resp["execution_trace"]
    assert resp["requested_tool_id"] == "list_neuroimage_assets"
    assert resp["resolved_tool_id"] == "list_neuroimage_assets"
    result = resp["result"]
    assert result["status"] == "success"
    outputs = result["data"]["outputs"]
    summary = result["data"]["summary"]
    assets = outputs["assets"]
    kinds = {asset["kind"] for asset in assets}
    assert {"template", "atlas", "reference_map", "warp"}.issubset(kinds)
    assert "template.mni152nlin2009casym.2mm" in outputs["asset_ids"]
    assert any(
        asset_id.startswith("nilearn.atlas.") for asset_id in outputs["asset_ids"]
    )
    assert "neuromaps.annotation.neurosynth.cogpc1.mni152.2mm" in outputs["asset_ids"]
    assert "warp.regfusion.mni152nlin2009casym.fslr.32k" in outputs["asset_ids"]
    assert summary["count"] >= 4
    assert summary["family_counts"]["templates_spaces_transforms"] >= 2

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    assert run["run"]["status"] == "succeeded"
    assert run["run"]["steps"][0]["status"] == "succeeded"


def test_tool_execute_multiagent_critic_block(tmp_path, monkeypatch):
    from brain_researcher.services.agent.subagents.contracts import CriticVerdict
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"extract_timeseries"},
        enable_multiagent=True,
        enable_critic_gate=True,
    )

    class StubRouter:
        def review_tool_call(self, **kwargs):
            return CriticVerdict(
                decision="block",
                risk_level="high",
                reason="blocked_for_test",
            )

    monkeypatch.setattr(srv, "_get_multiagent_router", lambda: StubRouter())
    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda _tool_id: ToolSpec(
            name="extract_timeseries",
            description="stub",
            backend="python",
            python_class="json:loads",
        ),
    )

    resp = srv.tool_execute("extract_timeseries", params={"img": "x", "atlas": "y"})

    assert resp["ok"] is False
    assert resp["error"] == "policy_rejected"
    assert resp["critic_verdict"] == "block"
    assert "blocked_for_test" in resp["critic_reason"]
    assert resp["revised_params"] is None
    assert any(
        i.get("code") == "multiagent_critic_blocked" for i in resp.get("issues", [])
    )


def test_pipeline_plan_validate_multiagent_critic_block(monkeypatch):
    from brain_researcher.services.agent.subagents.contracts import CriticVerdict
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    monkeypatch.setattr(srv, "AGENT_MULTIAGENT_ENABLED", True)
    monkeypatch.setattr(srv, "AGENT_CRITIC_TOOL_GATE", True)

    class StubRouter:
        def review_tool_call(self, **kwargs):
            return CriticVerdict(
                decision="block",
                risk_level="high",
                reason="blocked_for_test",
            )

    monkeypatch.setattr(srv, "_get_multiagent_router", lambda: StubRouter())
    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda _tool_id: ToolSpec(
            name="extract_timeseries",
            description="stub",
            backend="python",
            python_class="json:loads",
        ),
    )

    resp = srv.pipeline_plan_validate(
        {
            "steps": [
                {"tool": "extract_timeseries", "params": {"img": "x", "atlas": "y"}}
            ]
        }
    )

    assert resp["ok"] is False
    assert resp["critic_feedback"][0]["critic_verdict"] == "block"
    assert any(
        i.get("code") == "multiagent_critic_blocked" for i in resp.get("issues", [])
    )
    assert any(
        i.get("code") == "multiagent_critic_blocked"
        for i in resp.get("policy_issues", [])
    )


def test_tool_execute_surfaces_revised_params_from_critic(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"extract_timeseries"},
    )

    def fake_preflight(tool_id, params, **kwargs):
        params["atlas"] = "revised_atlas"
        return (
            ToolSpec(
                name=tool_id,
                description="stub",
                backend="python",
                python_class="json:loads",
            ),
            [
                {
                    "level": "warn",
                    "code": "multiagent_critic_revised_params",
                    "message": "critic revised params",
                    "step_id": "s1",
                }
            ],
        )

    monkeypatch.setattr(srv, "_call_preflight_tool_call", fake_preflight)

    resp = srv.tool_execute(
        "extract_timeseries",
        params={"img": "x", "atlas": "y"},
        preview=True,
    )

    assert resp["ok"] is True
    assert resp["critic_verdict"] == "revise"
    assert resp["revised_params"]["atlas"] == "revised_atlas"


def test_pipeline_plan_validate_surfaces_revised_params_from_critic(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    def fake_preflight(tool_id, params, allowlist=None, step_id=None):
        params["atlas"] = "revised_atlas"
        return (
            ToolSpec(
                name=tool_id,
                description="stub",
                backend="python",
                python_class="json:loads",
            ),
            [
                {
                    "level": "warn",
                    "code": "multiagent_critic_revised_params",
                    "message": "critic revised params",
                    "step_id": step_id,
                }
            ],
        )

    monkeypatch.setattr(srv, "_preflight_tool_call", fake_preflight)

    resp = srv.pipeline_plan_validate(
        {
            "steps": [
                {"tool": "extract_timeseries", "params": {"img": "x", "atlas": "y"}}
            ]
        }
    )

    assert resp["ok"] is True
    assert resp["normalized_plan"]["steps"][0]["params"]["atlas"] == "revised_atlas"
    assert resp["critic_feedback"][0]["critic_verdict"] == "revise"
    assert resp["critic_feedback"][0]["revised_params"]["atlas"] == "revised_atlas"


def test_tool_execute_rejects_workflow_ids(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"*"},
    )

    resp = srv.tool_execute("workflow_preprocessing_qc", params={})
    assert resp["ok"] is False
    assert resp["error"] == "workflow_requires_pipeline_execute"
    assert resp["execution_recipe_available"] is True
    assert resp["recipe_lookup"]["tool"] == "get_execution_recipe"
    assert resp["recipe_lookup"]["args"]["target_runtime"] == "neurodesk"


def test_get_latest_plan_prefers_thread_filtered_agent_plan_cache(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "_PLAN_CACHE",
        {
            "plan_other": {
                "plan_id": "plan_other",
                "context": {"thread_id": "thread_other"},
                "inputs": {"dataset_ref": "ds:openneuro:ds000114"},
                "dag": {"steps": [{"tool": "workflow_task_glm_group"}]},
            },
            "plan_target": {
                "plan_id": "plan_target",
                "context": {"thread_id": "thread_target"},
                "inputs": {
                    "dataset_ref": "ds:openneuro:ds000224",
                    "atlas": "Schaefer2018_200",
                },
                "warnings": ["Check confounds before execution."],
                "dag": {"steps": [{"tool": "workflow_rest_connectome_e2e"}]},
            },
        },
    )
    monkeypatch.setattr(srv, "_get_latest_plan_job_store", lambda: None)

    resp = srv.get_latest_plan("thread_target")

    assert resp["ok"] is True, repr(resp)
    assert resp["source"] == "agent_plan_cache"
    assert resp["thread_id"] == "thread_target"
    assert resp["plan_id"] == "plan_target"
    assert resp["handoff"]["workflow_id"] == "workflow_rest_connectome_e2e"
    assert resp["handoff"]["dataset_ref"] == "ds:openneuro:ds000224"
    assert 'get_latest_plan(thread_id="thread_target")' in resp["continuation_prompt"]


def test_get_latest_plan_falls_back_to_job_store(monkeypatch):
    from brain_researcher.core.contracts.job import JobRecordV1
    from brain_researcher.services.mcp import server as srv

    class FakeJobStore:
        async def list_all(self, limit: int = 100, offset: int = 0):
            return [
                JobRecordV1(
                    job_id="job_old",
                    status="succeeded",
                    created_at=10,
                    session_id="thread_target",
                    payload_json=json.dumps(
                        {
                            "metadata": {
                                "thread_id": "thread_target",
                                "plan_of_record": {
                                    "plan_id": "plan_old",
                                    "inputs": {"dataset_ref": "ds:openneuro:ds000114"},
                                    "dag": {
                                        "steps": [{"tool": "workflow_preprocessing_qc"}]
                                    },
                                },
                            }
                        }
                    ),
                ),
                JobRecordV1(
                    job_id="job_new",
                    status="succeeded",
                    created_at=20,
                    session_id="thread_target",
                    payload_json=json.dumps(
                        {
                            "metadata": {
                                "thread_id": "thread_target",
                                "plan_of_record": {
                                    "plan_id": "plan_new",
                                    "inputs": {"dataset_ref": "ds:openneuro:ds000224"},
                                    "dag": {
                                        "steps": [
                                            {"tool": "workflow_rest_connectome_e2e"}
                                        ]
                                    },
                                },
                            }
                        }
                    ),
                ),
            ]

    monkeypatch.setattr(srv, "_PLAN_CACHE", {})
    monkeypatch.setattr(srv, "_get_latest_plan_job_store", lambda: FakeJobStore())

    resp = srv.get_latest_plan("thread_target")

    assert resp["ok"] is True, repr(resp)
    assert resp["source"] == "job_store"
    assert resp["source_job_id"] == "job_new"
    assert resp["plan_id"] == "plan_new"
    assert resp["handoff"]["workflow_id"] == "workflow_rest_connectome_e2e"
    assert resp["handoff"]["dataset_ref"] == "ds:openneuro:ds000224"


def test_get_latest_plan_returns_not_found_when_no_cached_or_recorded_plan(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "_PLAN_CACHE", {})
    monkeypatch.setattr(srv, "_get_latest_plan_job_store", lambda: None)

    resp = srv.get_latest_plan("thread_missing")

    assert resp["ok"] is False, repr(resp)
    assert resp["error"] == "plan_not_found"
    assert resp["thread_id"] == "thread_missing"
    assert 'get_latest_plan(thread_id="thread_missing")' in resp["continuation_prompt"]


def test_get_execution_recipe_for_workflow_rest_connectome_e2e():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_rest_connectome_e2e",
        params={"img": "/data/bold.nii.gz", "output_dir": "/data/out"},
        target_runtime="python",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "python"
    assert resp["recipe_depth"] == "runnable"
    assert resp["execution_story_kind"] == "portable_python_compute"
    assert resp["agent_mode"] == "local_recipe"
    assert resp["supports_preview"] is True
    assert resp["preview_kind"] == "real"
    assert resp["for_agents"] is True
    recipe = resp["recipe"]
    script = recipe["files"]["run_workflow_rest_connectome_e2e.py"]
    assert "from nilearn.connectome import ConnectivityMeasure" in script
    assert "from nilearn.maskers import NiftiLabelsMasker" in script
    assert "templateflow.api" in script
    assert "brain_researcher.public" not in script
    assert "params.json" in recipe["files"]
    assert "run_pack.py" in recipe["files"]
    assert "pack_manifest.json" in recipe["files"]
    assert 'pip install -e "${BRAIN_RESEARCHER_REPO}"' in " ".join(
        recipe["setup_commands"]
    )
    pack_manifest = json.loads(recipe["files"]["pack_manifest.json"])
    assert pack_manifest["schema_version"] == "br-pack-contract-v1"
    assert pack_manifest["steps"][0]["execution_mode"] == "embedded_python"
    assert pack_manifest["steps"][0]["script"] == "run_workflow_rest_connectome_e2e.py"
    assert pack_manifest["handoff"]["schema_version"] == "br-plan-handoff-v1"
    assert pack_manifest["handoff"]["workflow_id"] == "workflow_rest_connectome_e2e"
    assert pack_manifest["handoff"]["inputs"]["img"] == "/data/bold.nii.gz"
    assert resp["runbook"] == "docs/runbooks/workflow_rest_connectome_e2e.md"
    assert resp["artifact_contract"]["required_outputs"] == [
        "timeseries/timeseries.npy",
        "timeseries/timeseries.csv",
        "connectivity_matrix.npy",
        "feature_contract.json",
    ]
    assert (
        resp["acceptance_gate"]["script"]
        == "scripts/workflows/run_workflow_realdata_gate.py"
    )
    assert resp["run_pack"]["runtime"]["target"] == "python"
    assert resp["run_pack"]["required_env_vars"] == ["BRAIN_RESEARCHER_REPO"]
    assert resp["run_pack"]["entrypoint"] == "run_pack.py"
    assert resp["run_pack"]["pack_manifest_file"] == "pack_manifest.json"
    assert resp["run_pack"]["handoff"]["workflow_id"] == "workflow_rest_connectome_e2e"
    assert resp["run_pack"]["resume_supported"] is True
    assert resp["run_pack"]["preflight"]["blocking_levels"] == ["L1", "L2"]
    assert resp["run_pack"]["commands"][-1] == "python run_pack.py"
    assert resp["run_pack"]["environment"]["required"][0]["name"] == (
        "BRAIN_RESEARCHER_REPO"
    )
    assert (
        "conda environment or Python venv"
        in resp["run_pack"]["prerequisites"]["setup_once"][0]
    )
    assert resp["local_run"]["required_env_vars"] == ["BRAIN_RESEARCHER_REPO"]


def test_get_execution_recipe_for_workflow_seed_based_connectivity_python():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_seed_based_connectivity",
        params={
            "img": "/data/bold.nii.gz",
            "seed_coords": [0.0, -52.0, 18.0],
            "output_dir": "/tmp/seed_fc_out",
        },
        target_runtime="python",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "python"
    assert resp["recipe_depth"] == "runnable"
    assert resp["runbook"] == "docs/runbooks/workflow_seed_based_connectivity.md"
    assert resp["artifact_contract"]["required_outputs"] == ["seed_based_fc.nii.gz"]
    recipe = resp["recipe"]
    assert recipe["run_command"] == "python run_workflow_seed_based_connectivity.py"
    assert "params.json" in recipe["files"]
    assert "run_workflow_seed_based_connectivity.py" in recipe["files"]
    assert "run_pack.py" in recipe["files"]
    assert "pack_manifest.json" in recipe["files"]
    assert "NiftiMasker" in recipe["files"]["run_workflow_seed_based_connectivity.py"]
    pack_manifest = json.loads(recipe["files"]["pack_manifest.json"])
    assert pack_manifest["steps"][0]["execution_mode"] == "embedded_python"
    assert resp["run_pack"]["commands"][-1] == "python run_pack.py"


def test_get_execution_recipe_for_clean_confounds_emits_local_tool_pack_contract():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "clean_confounds",
        params={
            "img": "/tmp/sub-01_bold.nii.gz",
            "confounds": "/tmp/sub-01_confounds.tsv",
            "output_file": "/tmp/cleaned_bold.nii.gz",
        },
        target_runtime="python",
    )

    assert resp["ok"] is True
    recipe = resp["recipe"]
    assert recipe["run_command"] == "python run_clean_confounds.py"
    assert "run_pack.py" in recipe["files"]
    assert "pack_manifest.json" in recipe["files"]
    pack_manifest = json.loads(recipe["files"]["pack_manifest.json"])
    assert pack_manifest["schema_version"] == "br-pack-contract-v1"
    assert pack_manifest["steps"][0]["execution_mode"] == "local_tool"
    assert pack_manifest["steps"][0]["tool_manifest"]["tool_id"] == "clean_confounds"
    assert pack_manifest["handoff"]["schema_version"] == "br-plan-handoff-v1"
    assert pack_manifest["handoff"]["chosen_tool"] == "clean_confounds"
    assert pack_manifest["handoff"]["dataset_ref"] is None
    assert (
        pack_manifest["steps"][0]["domain_policy"]["confounds_non_finite"]
        == "sanitize_non_finite_to_zero"
    )
    assert pack_manifest["preflight"]["blocking_levels"] == ["L1", "L2"]
    assert resp["run_pack"]["entrypoint"] == "run_pack.py"
    assert resp["run_pack"]["handoff"]["chosen_tool"] == "clean_confounds"


@pytest.mark.parametrize(
    ("workflow_id", "params", "runbook", "required_outputs"),
    [
        (
            "workflow_network_based_statistics",
            {
                "timeseries": "/data/timeseries.npy",
                "labels": [0, 0, 1, 1],
                "output_dir": "/tmp/nbs_out",
            },
            "docs/runbooks/workflow_network_based_statistics.md",
            [
                "group_connectivity.npy",
                "nbs.npy",
                "nbs.mask.npy",
                "nbs.components.json",
            ],
        ),
        (
            "workflow_connectivity_gradients",
            {
                "timeseries": "/data/timeseries.npy",
                "output_dir": "/tmp/grad_out",
            },
            "docs/runbooks/workflow_connectivity_gradients.md",
            [
                "connectivity.npy",
                "gradients/graph_metrics.json",
                "gradients/graph_summary.json",
            ],
        ),
        (
            "workflow_group_ica",
            {
                "img": ["/data/sub-01_bold.nii.gz", "/data/sub-02_bold.nii.gz"],
                "labels": [0, 1],
                "output_dir": "/tmp/group_ica_out",
            },
            "docs/runbooks/workflow_group_ica.md",
            [
                "group_ica/canica_components.nii.gz",
                "group_ica/canica_timecourses.npy",
                "group_ica/connectivity.npy",
                "group_ica/nbs.npy",
            ],
        ),
    ],
)
def test_get_execution_recipe_for_active_connectivity_python_workflows(
    workflow_id, params, runbook, required_outputs
):
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        workflow_id,
        params=params,
        target_runtime="python",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "python"
    assert resp["execution_story_kind"] == "composite_workflow"
    assert resp["supported_recipe_targets"] == ["python"]
    assert resp["agent_mode"] == "local_recipe"
    assert resp["supports_preview"] is True
    assert resp["preview_kind"] == "real"
    assert resp["for_agents"] is True
    assert resp["runbook"] == runbook
    assert resp["artifact_contract"]["required_outputs"] == required_outputs
    assert (
        resp["acceptance_gate"]["script"]
        == "scripts/workflows/run_workflow_realdata_gate.py"
    )
    recipe = resp["recipe"]
    script_name = f"run_{workflow_id}.py"
    assert recipe["run_command"] == f"python {script_name}"
    assert script_name in recipe["files"]
    assert "params.json" in recipe["files"]
    assert f'execute_tool("{workflow_id}", params)' in recipe["files"][script_name]


def test_get_execution_recipe_for_workflow_preprocessing_qc():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_preprocessing_qc",
        params={"bids_dir": "/data/bids", "output_dir": "/data/out"},
        target_runtime="neurodesk",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "neurodesk"
    assert resp["recipe_depth"] == "runnable"
    assert "neurodesk" in resp["supported_recipe_targets"]
    assert resp["agent_mode"] == "local_recipe"
    assert resp["supports_preview"] is True
    assert resp["preview_kind"] == "real"
    assert resp["runbook"] == "docs/runbooks/workflow_preprocessing_qc.md"
    assert resp["acceptance_gate"]["execute_gate_script"] == (
        "scripts/workflows/run_external_repo_minimal_execute_gate.py"
    )
    recipe = resp["recipe"]
    assert recipe["run_command"] == "bash run_workflow_preprocessing_qc.sh"
    assert "README.md" in recipe["files"]
    assert "post_qc.py" in recipe["files"]
    assert "run_workflow_preprocessing_qc.sh" in recipe["files"]
    assert "run_fmriprep.sh" in recipe["files"]
    assert "run_mriqc.sh" in recipe["files"]
    assert "brain_researcher.public" not in recipe["files"]["post_qc.py"]
    assert "single-subject fMRIPrep + MRIQC example" in recipe["files"]["README.md"]
    assert "participant_label" in recipe["files"]["params.json"]
    assert "--no-sub" in recipe["files"]["run_mriqc.sh"]
    assert any(
        cmd.startswith("module load fmriprep/") for cmd in recipe["setup_commands"]
    )
    run_pack = resp["run_pack"]
    assert run_pack["runtime"]["target"] == "neurodesk"
    assert run_pack["environment"]["required"][0]["name"] == "FS_LICENSE"
    assert "Open a Neurodesk shell" in run_pack["prerequisites"]["setup_once"][0]
    local_run = resp["local_run"]
    assert local_run["workspace"].endswith("workflow_preprocessing_qc_neurodesk_recipe")
    assert "run_workflow_preprocessing_qc.sh" in local_run["write_files"]
    assert "run_fmriprep.sh" in local_run["write_files"]
    assert "run_mriqc.sh" in local_run["write_files"]
    assert "FS_LICENSE" in local_run["required_env_vars"]
    assert 'export FS_LICENSE="<set-me>"' in local_run["env_exports"]
    assert "chmod +x" in local_run["shell_snippet"]
    assert '# export FS_LICENSE="<set-me>"' in local_run["shell_snippet"]
    assert "bash run_workflow_preprocessing_qc.sh" in local_run["shell_snippet"]
    assert "Set required environment variables before running:" in (
        local_run["materialize_python"]
    )
    assert "recipe_resp = ...  # JSON returned by get_execution_recipe(...)" in (
        local_run["materialize_python"]
    )


def test_workflow_preprocessing_qc_exposes_dry_run_passthrough():
    from brain_researcher.services.mcp import server as srv

    row = next(
        workflow
        for workflow in srv._load_workflow_catalog()
        if workflow.get("id") == "workflow_preprocessing_qc"
    )

    assert row["params"]["defaults"]["dry_run"] is True
    assert row["params"]["schema"]["properties"]["dry_run"]["type"] == "boolean"
    assert row["artifact_contract"]["required_outputs"] == [
        "qc_table.csv",
        "qc_outliers.csv",
        "qc_summary.json",
        "index.html",
    ]
    assert row["runbook"] == "docs/runbooks/workflow_preprocessing_qc.md"

    steps = {step["id"]: step for step in row["runtime"]["steps"]}
    assert steps["fmriprep"]["params"]["dry_run"] == "${inputs.dry_run:-true}"
    assert steps["mriqc"]["params"]["dry_run"] == "${inputs.dry_run:-true}"
    assert steps["fmriprep"]["params"]["participant_label"] == (
        "${inputs.participant_label}"
    )
    assert steps["mriqc"]["params"]["modalities"] == "${inputs.modalities}"


def test_get_execution_recipe_for_workflow_fmriprep_preprocessing_container():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_fmriprep_preprocessing",
        params={
            "bids_dir": "/data/openneuro/ds000114/bids",
            "output_dir": "/tmp/fmriprep_out",
            "participant_label": ["01"],
        },
        target_runtime="container",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "container"
    assert resp["recipe_depth"] == "runnable"
    assert resp["source_repo"] == "https://github.com/nipreps/fmriprep"
    assert resp["runbook"] == "docs/runbooks/workflow_fmriprep_preprocessing.md"
    assert resp["artifact_contract"]["required_outputs"] == [
        "dataset_description",
        "derivatives_dir",
    ]
    recipe = resp["recipe"]
    assert recipe["run_command"] == "bash run_workflow_fmriprep_preprocessing.sh"
    assert "README.md" in recipe["files"]
    assert "run_workflow_fmriprep_preprocessing.sh" in recipe["files"]
    assert "docker pull nipreps/fmriprep:23.2.3" in recipe["setup_commands"]
    assert "docker" in recipe["files"]["run_workflow_fmriprep_preprocessing.sh"]
    assert (
        "--participant-label"
        in recipe["files"]["run_workflow_fmriprep_preprocessing.sh"]
    )
    assert (
        "--fs-no-reconall" in recipe["files"]["run_workflow_fmriprep_preprocessing.sh"]
    )
    assert "FS_LICENSE" in recipe["required_env_vars"]
    local_run = resp["local_run"]
    assert local_run["workspace"].endswith(
        "workflow_fmriprep_preprocessing_container_recipe"
    )
    assert local_run["required_env_vars"] == ["FS_LICENSE"]
    assert local_run["env_exports"] == ['export FS_LICENSE="<set-me>"']
    assert "bash run_workflow_fmriprep_preprocessing.sh" in local_run["shell_snippet"]
    assert '# export FS_LICENSE="<set-me>"' in local_run["shell_snippet"]
    assert "docker pull nipreps/fmriprep:23.2.3" in local_run["commands"]
    assert "run_workflow_fmriprep_preprocessing.sh" in local_run["write_files"]


def test_get_execution_recipe_for_workflow_mriqc_neurodesk():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_mriqc",
        params={
            "bids_dir": "/data/openneuro/ds000114/bids",
            "output_dir": "/tmp/mriqc_out",
            "participant_label": ["01"],
        },
        target_runtime="neurodesk",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "neurodesk"
    assert resp["recipe_depth"] == "runnable"
    assert resp["source_repo"] == "https://github.com/nipreps/mriqc"
    assert resp["runbook"] == "docs/runbooks/workflow_mriqc.md"
    recipe = resp["recipe"]
    assert recipe["run_command"] == "bash run_workflow_mriqc.sh"
    assert "README.md" in recipe["files"]
    assert "run_workflow_mriqc.sh" in recipe["files"]
    assert any(cmd.startswith("module load mriqc/") for cmd in recipe["setup_commands"])
    assert "--modalities" in recipe["files"]["run_workflow_mriqc.sh"]
    assert "--mem" in recipe["files"]["run_workflow_mriqc.sh"]
    assert "--no-sub" in recipe["files"]["run_workflow_mriqc.sh"]
    assert "--mem_gb" not in recipe["files"]["run_workflow_mriqc.sh"]
    assert "single-subject MRIQC example" in recipe["files"]["README.md"]
    local_run = resp["local_run"]
    assert local_run["workspace"].endswith("workflow_mriqc_neurodesk_recipe")
    assert local_run["required_env_vars"] == []
    assert local_run["env_exports"] == []
    assert "bash run_workflow_mriqc.sh" in local_run["commands"]
    assert "module load mriqc/24.0.2" in local_run["shell_snippet"]


def test_get_execution_recipe_for_workflow_preprocessing_qc_includes_minimal_flags():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_preprocessing_qc",
        params={
            "bids_dir": "/data/openneuro/ds000114/bids",
            "output_dir": "/tmp/preproc_qc_out",
            "participant_label": ["01"],
        },
        target_runtime="neurodesk",
    )

    assert resp["ok"] is True
    recipe = resp["recipe"]
    assert "--fs-no-reconall" in recipe["files"]["run_fmriprep.sh"]
    assert "--no-sub" in recipe["files"]["run_mriqc.sh"]


def test_get_execution_recipe_for_workflow_fastsurfer_container():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_fastsurfer",
        params={
            "t1w_image": "/data/openneuro/ds000114/bids/sub-01/anat/sub-01_T1w.nii.gz",
            "subject_id": "sub-01",
            "output_dir": "/tmp/fastsurfer_out",
        },
        target_runtime="container",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "container"
    assert resp["recipe_depth"] == "runnable"
    assert resp["source_repo"] == "https://github.com/Deep-MI/FastSurfer"
    assert resp["acceptance_gate"]["execute_gate_script"] == (
        "scripts/workflows/run_external_repo_minimal_execute_gate.py"
    )
    recipe = resp["recipe"]
    assert recipe["run_command"] == "bash run_workflow_fastsurfer.sh"
    assert "README.md" in recipe["files"]
    assert "run_workflow_fastsurfer.sh" in recipe["files"]
    assert recipe["setup_commands"] == ["docker pull deepmi/fastsurfer:latest"]
    assert "run_fastsurfer.sh" in recipe["files"]["run_workflow_fastsurfer.sh"]
    assert "FS_LICENSE" in recipe["required_env_vars"]


def test_get_execution_recipe_for_workflow_qsiprep_neurodesk():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_qsiprep",
        params={
            "bids_dir": "/data/openneuro/ds000114/bids",
            "output_dir": "/tmp/qsiprep_out",
            "participant_label": ["01"],
        },
        target_runtime="neurodesk",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "neurodesk"
    assert resp["recipe_depth"] == "runnable"
    assert resp["source_repo"] == "https://github.com/PennLINC/qsiprep"
    assert resp["runbook"] == "docs/runbooks/workflow_qsiprep.md"
    recipe = resp["recipe"]
    assert recipe["run_command"] == "bash run_workflow_qsiprep.sh"
    assert "README.md" in recipe["files"]
    assert "params.json" in recipe["files"]
    assert "run_workflow_qsiprep.sh" in recipe["files"]
    assert any(
        cmd.startswith("module load qsiprep/") for cmd in recipe["setup_commands"]
    )
    assert "FS_LICENSE" in recipe["required_env_vars"]
    assert "--participant-label" in recipe["files"]["run_workflow_qsiprep.sh"]
    assert "--skip-bids-validation" in recipe["files"]["run_workflow_qsiprep.sh"]


def test_get_execution_recipe_for_workflow_qsiprep_container():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_qsiprep",
        params={
            "bids_dir": "/data/openneuro/ds000114/bids",
            "output_dir": "/tmp/qsiprep_out",
            "participant_label": ["01"],
        },
        target_runtime="container",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "container"
    recipe = resp["recipe"]
    assert recipe["run_command"] == "bash run_workflow_qsiprep.sh"
    assert "docker pull pennbbl/qsiprep:latest" in recipe["setup_commands"]
    assert "docker" in recipe["files"]["run_workflow_qsiprep.sh"]


def test_get_execution_recipe_for_workflow_smriprep_container():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_smriprep",
        params={
            "bids_dir": "/data/openneuro/ds000114/bids",
            "output_dir": "/tmp/smriprep_out",
            "participant_label": ["01"],
        },
        target_runtime="container",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "container"
    assert resp["source_repo"] == "https://github.com/nipreps/smriprep"
    assert resp["runbook"] == "docs/runbooks/workflow_smriprep.md"
    recipe = resp["recipe"]
    assert recipe["run_command"] == "bash run_workflow_smriprep.sh"
    assert "README.md" in recipe["files"]
    assert "params.json" in recipe["files"]
    assert "run_workflow_smriprep.sh" in recipe["files"]
    assert "docker pull nipreps/smriprep:0.19.1" in recipe["setup_commands"]
    assert "docker" in recipe["files"]["run_workflow_smriprep.sh"]
    assert "FS_LICENSE" in recipe["required_env_vars"]


def test_get_execution_recipe_for_workflow_smriprep_slurm():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_smriprep",
        params={
            "bids_dir": "/data/openneuro/ds000114/bids",
            "output_dir": "/tmp/smriprep_out",
            "participant_label": ["01"],
        },
        target_runtime="slurm",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "slurm"
    recipe = resp["recipe"]
    assert recipe["run_command"] == "sbatch job.sbatch"
    assert "job.sbatch" in recipe["files"]
    assert "apptainer" in recipe["files"]["job.sbatch"]
    assert "docker://nipreps/smriprep:0.19.1" in recipe["files"]["job.sbatch"]
    assert "FS_LICENSE_FILE" in recipe["files"]["job.sbatch"]


def test_get_execution_recipe_for_workflow_qsirecon_container():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_qsirecon",
        params={
            "qsiprep_dir": "/data/openneuro/ds000114/derivatives/qsiprep",
            "output_dir": "/tmp/qsirecon_out",
            "recon_spec": "mrtrix_multishell_msmt_ACT-hsvs",
            "participant_label": ["01"],
        },
        target_runtime="container",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "container"
    assert resp["source_repo"] == "https://github.com/PennLINC/qsirecon"
    assert resp["runbook"] == "docs/runbooks/workflow_qsirecon.md"
    recipe = resp["recipe"]
    assert recipe["run_command"] == "bash run_workflow_qsirecon.sh"
    assert "README.md" in recipe["files"]
    assert "params.json" in recipe["files"]
    assert "run_workflow_qsirecon.sh" in recipe["files"]
    assert "docker pull pennlinc/qsirecon:1.1.1" in recipe["setup_commands"]
    assert "--recon-spec" in recipe["files"]["run_workflow_qsirecon.sh"]


def test_get_execution_recipe_omits_empty_stable_pack_provenance():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_longitudinal_lme",
        params={
            "data_file": "/tmp/longitudinal.csv",
            "subject_col": "subject_id",
            "time_col": "visit_month",
            "output_dir": "/tmp/lme_out",
        },
        target_runtime="python",
    )

    assert resp["ok"] is True
    assert "source_repo" not in resp
    assert "source_paper" not in resp
    assert "tested_release" not in resp
    provenance = resp.get("run_pack", {}).get("provenance", {})
    assert "source_repo" not in provenance
    assert "source_paper" not in provenance


def test_get_execution_recipe_rejects_neurodesk_for_workflow_qsirecon():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_qsirecon",
        params={
            "qsiprep_dir": "/data/openneuro/ds000114/derivatives/qsiprep",
            "output_dir": "/tmp/qsirecon_out",
            "recon_spec": "mrtrix_multishell_msmt_ACT-hsvs",
        },
        target_runtime="neurodesk",
    )

    assert resp["ok"] is False
    assert resp["error"] == "unsupported_recipe_target"
    assert resp["supported_recipe_targets"] == ["container", "slurm"]


def test_workflow_search_keeps_python_target_for_recipe_safe_workflow(monkeypatch):
    from brain_researcher.services.mcp import execution_recipes as recipes
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    monkeypatch.setattr(
        srv,
        "load_orchestration_workflows",
        lambda: ["workflow_safe_python"],
    )
    monkeypatch.setattr(
        srv,
        "_load_workflow_catalog",
        lambda: [
            {
                "id": "workflow_safe_python",
                "stage": "interpretation",
                "cost_tier": "moderate",
                "description": "safe python workflow",
                "modalities": [],
                "runtime": {
                    "kind": "declarative_workflow",
                    "steps": [{"tool": "extract_timeseries", "params": {}}],
                },
            }
        ],
    )
    monkeypatch.setattr(
        recipes,
        "_all_toolspecs_by_name",
        lambda: {
            "extract_timeseries": ToolSpec(
                name="extract_timeseries",
                description="stub",
                backend="python",
                python_class="json:loads",
            )
        },
    )
    resp = srv.workflow_search("workflow_safe_python", limit=10)
    assert resp["ok"] is True
    row = next(
        workflow
        for workflow in resp["workflows"]
        if workflow.get("id") == "workflow_safe_python"
    )
    assert row["supported_recipe_targets"] == ["python"]


def test_resolve_recipe_metadata_prefers_declared_workflow_story_over_inference(
    monkeypatch,
):
    from brain_researcher.services.mcp import execution_recipes as recipes
    from brain_researcher.services.tools.spec import ToolSpec

    monkeypatch.setattr(
        recipes,
        "_all_toolspecs_by_name",
        lambda: {
            "extract_timeseries": ToolSpec(
                name="extract_timeseries",
                description="stub",
                backend="python",
                python_class="json:loads",
            )
        },
    )

    workflow_entry = {
        "id": "workflow_declared_composite",
        "stage": "interpretation",
        "cost_tier": "cheap",
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": [],
        "primary_target": "",
        "runtime": {
            "kind": "declarative_workflow",
            "steps": [{"tool": "extract_timeseries", "params": {}}],
        },
    }
    metadata = recipes.resolve_recipe_metadata(
        "workflow_declared_composite",
        workflow_entry=workflow_entry,
    )

    assert metadata["execution_story_kind"] == "composite_workflow"
    assert metadata["supported_recipe_targets"] == []
    assert metadata["primary_target"] == ""
    assert metadata["declared_execution_story_kind"] == "composite_workflow"
    assert metadata["inferred_execution_story_kind"] == "portable_python_compute"
    assert metadata["inferred_supported_recipe_targets"] == ["python"]


def test_get_execution_recipe_returns_story_for_kg_multihop_qa():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "kg_multihop_qa",
        params={"question": "What links S1 and S2?"},
        target_runtime="python",
    )

    assert resp["ok"] is True
    assert resp["recipe"] is None
    assert resp["supported_recipe_targets"] == []
    assert resp["execution_story_kind"] == "hosted_or_stateful_service"
    assert resp["hosted_via_br_mcp_service"] is True
    assert resp["agent_mode"] == "hosted_call"
    assert resp["supports_preview"] is False
    assert resp["preview_kind"] == "none"
    assert resp["for_agents"] is True
    assert "Neo4j" in resp["execution_story"]["summary"]


@pytest.mark.parametrize(
    ("tool_id", "params"),
    [
        ("graph_query", {"query_type": "neighbors", "start_node": "working memory"}),
        ("pipeline.search", {"task": "t1 preprocessing", "limit": 3}),
        ("datasets.client", {"text": "memory", "limit": 5}),
        ("datasets.list_resources", {"dataset_ref": "ds000001"}),
        ("datasets.describe_resources", {"dataset_ref": "ds000001"}),
        ("literature_mining", {"search_query": "working memory"}),
        ("query_neuromaps", {"term": "default mode"}),
    ],
)
def test_get_execution_recipe_returns_story_for_hosted_facade_tools(tool_id, params):
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        tool_id,
        params=params,
        target_runtime="python",
    )

    assert resp["ok"] is True
    assert resp["recipe"] is None
    assert resp["execution_story_kind"] == "hosted_or_stateful_service"
    assert resp["supported_recipe_targets"] == []
    assert resp["hosted_via_br_mcp_service"] is True
    assert resp["agent_mode"] == "hosted_call"
    assert resp["for_agents"] is True


def test_get_execution_recipe_rejects_python_for_workflow_dwi_connectome():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_dwi_connectome",
        params={"dwi": "/data/dwi.nii.gz", "atlas": "/data/atlas.nii.gz"},
        target_runtime="python",
    )

    assert resp["ok"] is False
    assert resp["execution_story_kind"] == "composite_workflow"
    assert resp["supported_recipe_targets"] == ["neurodesk", "container", "slurm"]
    assert resp["agent_mode"] == "local_recipe"
    assert resp["supports_preview"] is True
    assert resp["preview_kind"] == "synthetic"
    assert resp["runbook"] == "docs/runbooks/workflow_dwi_connectome.md"
    assert (
        resp["acceptance_gate"]["script"]
        == "scripts/workflows/run_workflow_realdata_gate.py"
    )


def test_get_execution_recipe_for_workflow_dwi_connectome_neurodesk():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_dwi_connectome",
        params={
            "qsiprep_dir": "/data/openneuro/ds000117/derivatives/qsiprep",
            "qsirecon_dir": "/data/openneuro/ds000117/derivatives/qsirecon",
            "atlas": "/data/atlas.nii.gz",
            "output_dir": "/tmp/dwi_connectome_out",
        },
        target_runtime="neurodesk",
    )

    assert resp["ok"] is True
    assert resp["target_runtime"] == "neurodesk"
    assert resp["recipe_depth"] == "runnable"
    assert resp["runbook"] == "docs/runbooks/workflow_dwi_connectome.md"
    assert resp["artifact_contract"]["required_outputs"] == [
        "sc/connectivity_matrix.csv",
        "sc/connectivity_matrix.npy",
        "sc/graph_metrics.json",
        "sc/connectome_manifest.json",
    ]
    assert resp["acceptance_gate"]["smoke_test"] == (
        "tests/integration/realdata/test_workflow_dwi_connectome_ds000117_smoke.py"
    )
    recipe = resp["recipe"]
    assert recipe["run_command"] == "python run_workflow_dwi_connectome.py"
    assert "README.md" in recipe["files"]
    assert "params.json" in recipe["files"]
    assert "run_workflow_dwi_connectome.py" in recipe["files"]
    assert "run_workflow_dwi_connectome.sh" in recipe["files"]
    assert "postprocess_dwi_connectome.py" in recipe["files"]
    assert "derivative-first DWI connectome example" in recipe["files"]["README.md"]
    assert any(
        cmd.startswith("module load qsirecon/") for cmd in recipe["setup_commands"]
    )
    assert any(
        cmd.startswith("module load mrtrix3/") for cmd in recipe["setup_commands"]
    )


def test_workflow_dwi_connectome_exposes_composite_metadata_contract():
    from brain_researcher.services.mcp import server as srv

    row = next(
        workflow
        for workflow in srv._load_workflow_catalog()
        if workflow.get("id") == "workflow_dwi_connectome"
    )

    assert row["recipe_family"] == "dwi_connectome"
    assert row["lifecycle"] == "candidate_pack"
    assert row["source_repo"] == "https://github.com/MRtrix3/mrtrix3"
    assert row["example_dataset"]["dataset_id"] == "ds000117"
    assert row["artifact_contract"]["required_outputs"] == [
        "sc/connectivity_matrix.csv",
        "sc/connectivity_matrix.npy",
        "sc/graph_metrics.json",
        "sc/connectome_manifest.json",
    ]
    assert (
        row["acceptance_gate"]["script"]
        == "scripts/workflows/run_workflow_realdata_gate.py"
    )
    assert row["runbook"] == "docs/runbooks/workflow_dwi_connectome.md"
    assert row["params"]["defaults"]["output_dir"] == (
        "/tmp/brain-researcher/workflow_dwi_connectome"
    )
    assert row["params"]["defaults"]["recon_spec"] == "mrtrix_multishell_msmt_ACT-hsvs"
    assert row["params"]["defaults"]["dry_run"] is False
    assert row["params"]["schema"]["required"] == ["atlas", "output_dir"]


def test_connectivity_workflow_catalog_rows_keep_contract_surfaces_aligned():
    from brain_researcher.services.mcp import server as srv

    expected = {
        "workflow_rest_connectome_e2e": {
            "execution_story_kind": "portable_python_compute",
            "supported_recipe_targets": ["python"],
            "primary_target": "python",
            "recipe_family": "rest_connectome",
            "runbook": "docs/runbooks/workflow_rest_connectome_e2e.md",
            "smoke_test": (
                "tests/integration/realdata/test_workflow_rest_connectome_ds000114_smoke.py"
            ),
            "required_outputs": [
                "timeseries/timeseries.npy",
                "timeseries/timeseries.csv",
                "connectivity_matrix.npy",
                "feature_contract.json",
            ],
        },
        "workflow_seed_based_connectivity": {
            "execution_story_kind": "portable_python_compute",
            "supported_recipe_targets": ["python"],
            "primary_target": "python",
            "recipe_family": "seed_based_connectivity",
            "runbook": "docs/runbooks/workflow_seed_based_connectivity.md",
            "smoke_test": (
                "tests/integration/realdata/"
                "test_workflow_seed_based_connectivity_ds000114_smoke.py"
            ),
            "required_outputs": ["seed_based_fc.nii.gz"],
        },
        "workflow_network_based_statistics": {
            "execution_story_kind": "composite_workflow",
            "supported_recipe_targets": ["python"],
            "primary_target": "python",
            "recipe_family": "network_based_statistics",
            "runbook": "docs/runbooks/workflow_network_based_statistics.md",
            "smoke_test": (
                "tests/integration/realdata/"
                "test_workflow_network_based_statistics_ds000114_smoke.py"
            ),
            "required_outputs": [
                "group_connectivity.npy",
                "nbs.npy",
                "nbs.mask.npy",
                "nbs.components.json",
            ],
        },
        "workflow_connectivity_gradients": {
            "execution_story_kind": "composite_workflow",
            "supported_recipe_targets": ["python"],
            "primary_target": "python",
            "recipe_family": "connectivity_gradients",
            "runbook": "docs/runbooks/workflow_connectivity_gradients.md",
            "smoke_test": (
                "tests/integration/realdata/"
                "test_workflow_connectivity_gradients_ds000114_smoke.py"
            ),
            "required_outputs": [
                "connectivity.npy",
                "gradients/graph_metrics.json",
                "gradients/graph_summary.json",
            ],
        },
        "workflow_group_ica": {
            "execution_story_kind": "composite_workflow",
            "supported_recipe_targets": ["python"],
            "primary_target": "python",
            "recipe_family": "group_ica",
            "runbook": "docs/runbooks/workflow_group_ica.md",
            "smoke_test": (
                "tests/integration/realdata/test_workflow_group_ica_ds000114_smoke.py"
            ),
            "required_outputs": [
                "group_ica/canica_components.nii.gz",
                "group_ica/canica_timecourses.npy",
                "group_ica/connectivity.npy",
                "group_ica/nbs.npy",
            ],
        },
    }

    rows = {
        workflow["id"]: workflow
        for workflow in srv._load_workflow_catalog()
        if workflow.get("id") in expected
    }
    assert set(rows) == set(expected)

    for workflow_id, spec in expected.items():
        row = rows[workflow_id]
        assert row["execution_story_kind"] == spec["execution_story_kind"]
        assert row["supported_recipe_targets"] == spec["supported_recipe_targets"]
        assert row["primary_target"] == spec["primary_target"]
        assert row["recipe_family"] == spec["recipe_family"]

        assert row["runbook"] == spec["runbook"]
        assert row["example_dataset"]["dataset_id"] == "ds000114"
        assert row["example_dataset"]["smoke_test"] == spec["smoke_test"]
        assert (
            row["acceptance_gate"]["script"]
            == "scripts/workflows/run_workflow_realdata_gate.py"
        )
        assert row["acceptance_gate"]["smoke_test"] == spec["smoke_test"]
        assert row["artifact_contract"]["required_outputs"] == spec["required_outputs"]


def test_get_execution_recipe_for_workflow_task_glm_group_python():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_task_glm_group",
        params={
            "bids_dir": "/data/bids",
            "fmriprep_dir": "/data/fmriprep",
            "task": "linebisection",
            "output_dir": "/tmp/task_glm_group_out",
        },
        target_runtime="python",
    )

    assert resp["ok"] is True
    assert resp["execution_story_kind"] == "composite_workflow"
    assert resp["supported_recipe_targets"] == ["python"]
    assert resp["agent_mode"] == "local_recipe"
    assert resp["preview_kind"] == "real"
    assert resp["runbook"] == "docs/runbooks/workflow_task_glm_group.md"
    assert (
        resp["acceptance_gate"]["script"]
        == "scripts/workflows/run_workflow_realdata_gate.py"
    )
    recipe = resp["recipe"]
    assert resp["target_runtime"] == "python"
    assert recipe["run_command"] == "python run_workflow_task_glm_group.py"
    assert "params.json" in recipe["files"]
    assert "run_workflow_task_glm_group.py" in recipe["files"]
    assert '"task": "linebisection"' in recipe["files"]["params.json"]
    assert (
        'execute_tool("workflow_task_glm_group", params)'
        in recipe["files"]["run_workflow_task_glm_group.py"]
    )


def test_get_execution_recipe_rejects_non_python_for_workflow_task_glm_group():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_task_glm_group",
        params={},
        target_runtime="container",
    )

    assert resp["ok"] is False
    assert resp["supported_recipe_targets"] == ["python"]
    assert resp["error"] == "unsupported_recipe_target"
    assert resp["runbook"] == "docs/runbooks/workflow_task_glm_group.md"


def test_workflow_task_glm_group_exposes_mature_metadata_contract():
    from brain_researcher.services.mcp import server as srv

    row = next(
        workflow
        for workflow in srv._load_workflow_catalog()
        if workflow.get("id") == "workflow_task_glm_group"
    )

    assert row["recipe_family"] == "task_glm_group"
    assert row["supported_recipe_targets"] == ["python"]
    assert row["example_dataset"]["dataset_id"] == "ds000114"
    assert row["artifact_contract"]["required_outputs"] == [
        "first_level_dirs",
        "selected_zmaps",
        "second_level/group_zmap.nii.gz",
        "second_level/glm_second_level_summary.json",
    ]
    assert row["artifact_contract"]["report_files"] == [
        "second_level/glm_second_level_summary.json"
    ]
    assert (
        row["acceptance_gate"]["script"]
        == "scripts/workflows/run_workflow_realdata_gate.py"
    )
    assert row["runbook"] == "docs/runbooks/workflow_task_glm_group.md"
    assert row["params"]["defaults"]["output_dir"] == (
        "/tmp/brain-researcher/workflow_task_glm_group"
    )
    assert row["params"]["schema"]["required"] == ["output_dir"]


def test_get_execution_recipe_for_workflow_fitlins_direct_python():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_fitlins_direct",
        params={
            "bids_dir": "/data/bids",
            "fmriprep_dir": "/data/fmriprep",
            "output_dir": "/tmp/fitlins_direct_out",
            "dry_run": True,
        },
        target_runtime="python",
    )

    assert resp["ok"] is True
    assert resp["supported_recipe_targets"] == ["python"]
    assert resp["runbook"] == "docs/runbooks/workflow_fitlins_direct.md"
    recipe = resp["recipe"]
    assert recipe["run_command"] == "python run_workflow_fitlins_direct.py"
    assert "run_workflow_fitlins_direct.py" in recipe["files"]
    assert '"runtime": "apptainer"' in recipe["files"]["params.json"]


def test_get_execution_recipe_for_workflow_fitlins_multiverse_python():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_fitlins_multiverse_yeo17",
        params={
            "bids_dir": "/data/bids",
            "fmriprep_dir": "/data/fmriprep",
            "output_dir": "/tmp/fitlins_multiverse_out",
            "task": "linebisection",
        },
        target_runtime="python",
    )

    assert resp["ok"] is True
    assert resp["supported_recipe_targets"] == ["python"]
    assert resp["runbook"] == "docs/runbooks/workflow_fitlins_multiverse_yeo17.md"
    recipe = resp["recipe"]
    assert recipe["run_command"] == "python run_workflow_fitlins_multiverse_yeo17.py"
    assert "run_workflow_fitlins_multiverse_yeo17.py" in recipe["files"]
    assert '"task": "linebisection"' in recipe["files"]["params.json"]
    assert '"runtime": "apptainer"' in recipe["files"]["params.json"]


def test_get_execution_recipe_for_workflow_realtime_twophoton_file_replay_python():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_realtime_twophoton_file_replay",
        params={
            "input_file": "/data/replay_bundle.npz",
            "reference_template": "/data/reference_template.npy",
            "roi_manifest": "/data/roi_manifest.npz",
            "decoder_path": "/data/decoder.joblib",
            "output_dir": "/tmp/rt2p_replay_out",
        },
        target_runtime="python",
    )

    assert resp["ok"] is True
    assert resp["execution_story_kind"] == "portable_python_compute"
    assert resp["supported_recipe_targets"] == ["python"]
    assert resp["hosted_via_br_mcp_service"] is False
    assert resp["agent_mode"] == "local_recipe"
    assert resp["preview_kind"] == "real"
    assert resp["runbook"] == "docs/runbooks/workflow_realtime_twophoton_file_replay.md"
    assert resp["artifact_contract"]["required_outputs"] == [
        "summary.json",
        "motion.jsonl",
        "decoder.jsonl",
        "controller.jsonl",
        "trace_df_f.npy",
    ]
    recipe = resp["recipe"]
    assert (
        recipe["run_command"] == "python run_workflow_realtime_twophoton_file_replay.py"
    )
    assert "params.json" in recipe["files"]
    assert "run_workflow_realtime_twophoton_file_replay.py" in recipe["files"]
    assert "run_pack.py" in recipe["files"]
    assert "pack_manifest.json" in recipe["files"]
    assert (
        'execute_tool("workflow_realtime_twophoton_file_replay", params)'
        in recipe["files"]["run_workflow_realtime_twophoton_file_replay.py"]
    )
    assert '"input_file": "/data/replay_bundle.npz"' in recipe["files"]["params.json"]
    assert resp["run_pack"]["runtime"]["target"] == "python"
    assert resp["run_pack"]["entrypoint"] == "run_pack.py"
    assert resp["local_run"]["commands"][-1] == "python run_pack.py"


def test_workflow_search_surfaces_realtime_twophoton_file_replay_recipe_metadata(
    monkeypatch,
):
    from brain_researcher.services.mcp import server as srv

    row = next(
        workflow
        for workflow in srv._load_workflow_catalog()
        if workflow.get("id") == "workflow_realtime_twophoton_file_replay"
    )
    monkeypatch.setattr(
        srv,
        "load_orchestration_workflows",
        lambda: ["workflow_realtime_twophoton_file_replay"],
    )
    monkeypatch.setattr(srv, "_load_workflow_catalog", lambda: [row])

    resp = srv.workflow_search("workflow_realtime_twophoton_file_replay", limit=10)

    assert resp["ok"] is True
    rows = resp["workflows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "workflow_realtime_twophoton_file_replay"
    assert row["execution_story_kind"] == "portable_python_compute"
    assert row["supported_recipe_targets"] == ["python"]
    assert row["hosted_via_br_mcp_service"] is False
    assert row["recipe_depth"] == "runnable"
    assert row["runbook"] == "docs/runbooks/workflow_realtime_twophoton_file_replay.md"
    assert row["expected_artifacts"] == [
        "summary.json",
        "motion.jsonl",
        "decoder.jsonl",
        "controller.jsonl",
        "trace_df_f.npy",
    ]


@pytest.mark.parametrize(
    ("tool_id", "expected_family"),
    [
        ("advanced_analysis.client", "mvpa"),
        ("openneuro.client", "openneuro_catalog"),
        ("fmri.connectivity_client.light", "connectivity_matrix"),
    ],
)
def test_resolve_recipe_metadata_keeps_local_python_aliases_portable(
    tool_id, expected_family
):
    from brain_researcher.services.mcp.execution_recipes import resolve_recipe_metadata

    metadata = resolve_recipe_metadata(tool_id)

    assert metadata["execution_story_kind"] == "portable_python_compute"
    assert metadata["supported_recipe_targets"] == ["python"]
    assert metadata["primary_target"] == "python"
    assert metadata["recipe_family"] == expected_family
    assert metadata["hosted_via_br_mcp_service"] is False


@pytest.mark.parametrize(
    "tool_id",
    [
        "coordinate_to_concept",
        "task_to_concept_mapping",
    ],
)
def test_resolve_recipe_metadata_keeps_niclip_tools_local_capable(tool_id):
    from brain_researcher.services.mcp.execution_recipes import resolve_recipe_metadata

    metadata = resolve_recipe_metadata(tool_id)

    assert metadata["execution_story_kind"] == "portable_python_compute"
    assert metadata["supported_recipe_targets"] == ["python"]
    assert metadata["primary_target"] == "python"
    assert metadata["hosted_via_br_mcp_service"] is False
    assert metadata["recipe_family"] == ""


def test_tool_get_surfaces_hosted_service_contract_for_datasets_list_resources():
    from brain_researcher.services.mcp import server as srv

    resp = srv.tool_get("datasets.list_resources")

    assert resp["ok"] is True
    assert resp["tool"]["execution_recipe_available"] is False
    assert resp["tool"]["hosted_via_br_mcp_service"] is True
    assert resp["tool"]["execution_story_kind"] == "hosted_or_stateful_service"
    assert resp["tool"]["supported_recipe_targets"] == []
    assert resp["tool"]["requires_runtime"] == "network"


def test_dataset_get_resources_preserves_non_bids_notes(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg.query_service import DatasetResourceSummary

    monkeypatch.setattr(
        "brain_researcher.services.neurokg.query_service.dataset_resources",
        lambda *args, **kwargs: DatasetResourceSummary(
            dataset_id="ibl",
            resolved_dataset_id="ds:manual:ibl_brainwide",
            resolution_mode="exact_alias",
            resolver_warnings=[],
            local_path="/mnt/public_s3/ibl-brain-wide-map-public",
            bids_path=None,
            is_bids_available=False,
            derivatives={},
            available_derivatives=[],
            remote_urls={"primary": "https://www.internationalbrainlab.com/data"},
            size_bytes=None,
            analysis_goal="generic",
            required_files={
                "analysis_goal": "generic",
                "groups": [],
                "missing_patterns": [],
                "required_total": 0,
                "required_passed": 0,
                "all_required_passed": False,
                "skipped": True,
                "note": (
                    "Mounted dataset is readable but does not expose a BIDS root. "
                    "Returning local resources and skipping BIDS-specific required-file checks."
                ),
            },
            readiness={
                "status": "partial",
                "reason": "Resources available with non-blocking dataset notes",
                "note": (
                    "Mounted dataset is readable but does not expose a BIDS root. "
                    "Returning local resources and skipping BIDS-specific required-file checks."
                ),
                "notes": [
                    "Mounted dataset is readable but does not expose a BIDS root. "
                    "Returning local resources and skipping BIDS-specific required-file checks."
                ],
                "local_path_available": True,
                "bids_validator": {"ran": False, "errors": 0, "warnings": 0},
            },
            auto_heal={},
            semantic_match={"matched": True},
            source_access={},
            dataset_name="IBL Brain-Wide Map",
            display_name="IBL Brain-Wide Map",
            source_repo="project / AWS",
            dataset_metadata={"modalities": ["Behavior"], "tasks": ["decision-making"]},
            mount_status={
                "mounted": True,
                "mount_kind": "public_s3",
                "local_path": "/mnt/public_s3/ibl-brain-wide-map-public",
            },
        ),
    )

    resp = srv.dataset_get_resources("ibl")

    assert resp["ok"] is True
    assert resp["resources"]["readiness"]["status"] == "partial"
    assert "does not expose a BIDS root" in resp["resources"]["readiness"]["note"]
    assert resp["resources"]["required_files"]["skipped"] is True


@pytest.mark.parametrize(
    ("tool_id", "params", "expected_snippets"),
    [
        (
            "glm_first_level",
            {"img": "/tmp/sub-01_bold.nii.gz"},
            [
                "from nilearn.glm.first_level import FirstLevelModel",
                'params["img"]',
                "glm_first_level_summary.json",
            ],
        ),
        (
            "fmri.connectivity_client.light",
            {"timeseries": "/tmp/timeseries.npy"},
            [
                "from nilearn.connectome import ConnectivityMeasure",
                'params["timeseries"]',
                "connectivity_matrix.npy",
            ],
        ),
        (
            "advanced_analysis.client",
            {"img": "/tmp/features.npy", "labels": [0, 1, 0, 1]},
            [
                "from sklearn.model_selection import StratifiedKFold, cross_val_score",
                "MVPA decoding completed.",
                'params["labels"]',
            ],
        ),
        (
            "temporal_decoding",
            {
                "data_file": "/tmp/data.npy",
                "labels_file": "/tmp/labels.npy",
            },
            [
                "def _nearest_centroid_cv_accuracy",
                "Temporal decoding completed",
                'params["data_file"]',
            ],
        ),
        (
            "encoding_models",
            {
                "brain_data_file": "/tmp/brain.npy",
                "stimulus_file": "/tmp/stim.npy",
            },
            [
                "encoding_summary.json",
                'params["brain_data_file"]',
                "r2_scores",
            ],
        ),
        (
            "searchlight_analysis",
            {
                "func_file": "/tmp/sub-01_bold.nii.gz",
                "labels": [0, 1, 0, 1],
                "output_dir": "/tmp/searchlight",
            },
            [
                "from nilearn.searchlight import SearchLight",
                'params["func_file"]',
                "Searchlight",
            ],
        ),
    ],
)
def test_get_execution_recipe_uses_direct_python_family_scripts(
    tool_id, params, expected_snippets
):
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(tool_id, params=params, target_runtime="python")

    assert resp["ok"] is True
    recipe = resp["recipe"]
    assert recipe is not None
    script_name, script_text = next(
        (name, text)
        for name, text in recipe["files"].items()
        if name.startswith("run_") and name.endswith(".py") and name != "run_pack.py"
    )
    assert script_name.endswith(".py")
    assert "execute_tool" not in script_text
    assert "from brain_researcher.services.tools.executor" not in script_text
    assert "brain_researcher" not in recipe["dependencies"]["python_packages"]
    for snippet in expected_snippets:
        assert snippet in script_text


def test_generated_run_pack_preflight_surfaces_missing_local_tool(tmp_path):
    from brain_researcher.services.mcp import server as srv

    recipe_resp = srv.get_execution_recipe(
        "clean_confounds",
        params={
            "img": "/tmp/sub-01_bold.nii.gz",
            "confounds": "/tmp/sub-01_confounds.tsv",
            "output_file": "/tmp/cleaned_bold.nii.gz",
        },
        target_runtime="python",
    )

    workspace = _materialize_recipe_files(recipe_resp["recipe"], tmp_path / "pack")
    proc = subprocess.run(
        [sys.executable, "run_pack.py", "--preflight"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["passed"] is False
    assert any(
        issue["code"] == "tool_unavailable" and "clean_confounds" in issue["message"]
        for issue in payload["issues"]
    )


def test_generated_run_pack_embedded_python_supports_resume(tmp_path):
    import numpy as np

    from brain_researcher.services.mcp import server as srv

    timeseries_path = tmp_path / "timeseries.npy"
    np.save(timeseries_path, np.arange(12, dtype=float).reshape(4, 3))
    output_file = tmp_path / "connectivity_matrix.npy"

    recipe_resp = srv.get_execution_recipe(
        "fmri.connectivity_client.light",
        params={
            "timeseries": str(timeseries_path),
            "output_file": str(output_file),
            "kind": "correlation",
            "fisher_z": True,
        },
        target_runtime="python",
    )

    workspace = _materialize_recipe_files(recipe_resp["recipe"], tmp_path / "pack")
    first = subprocess.run(
        [sys.executable, "run_pack.py"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0
    first_payload = json.loads(first.stdout)
    assert first_payload["steps"][0]["status"] == "success"
    assert output_file.exists()

    second = subprocess.run(
        [sys.executable, "run_pack.py"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0
    second_payload = json.loads(second.stdout)
    assert second_payload["steps"][0]["status"] == "skipped"
    assert second_payload["steps"][0]["reason"] == "resume_from_success_log"


def test_tool_execute_rejects_hosted_tool_local_execution(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"*"},
    )
    monkeypatch.setattr(srv, "is_workflow_tool_id", lambda _tool_id: False)
    monkeypatch.setattr(
        srv,
        "_call_preflight_tool_call",
        lambda *args, **kwargs: (
            ToolSpec(
                name="datasets.list_resources",
                description="stub",
                backend="python",
            ),
            [],
        ),
    )

    def _unexpected_execute(**kwargs):
        raise AssertionError("hosted tool should not reach local execution")

    monkeypatch.setattr(srv, "_execute_tool_with_timeout", _unexpected_execute)

    resp = srv.tool_execute(
        "datasets.list_resources",
        params={"dataset_ref": "ds000001"},
    )

    assert resp["ok"] is False
    assert resp["error"] == "hosted_execution_required"
    assert resp["resolved_tool_id"] == "datasets.list_resources"
    assert resp["hosted_via_br_mcp_service"] is True
    assert resp["execution_recipe_available"] is False
    assert resp["supported_recipe_targets"] == []
    assert "hosted by default" in resp["message"]


def test_tool_execute_rejects_binary_backed_tool_local_execution(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"*"},
    )
    monkeypatch.setattr(srv, "is_workflow_tool_id", lambda _tool_id: False)
    monkeypatch.setattr(
        srv,
        "_call_preflight_tool_call",
        lambda *args, **kwargs: (
            ToolSpec(
                name="fsl.bet",
                description="stub",
                backend="python",
            ),
            [],
        ),
    )

    def _unexpected_execute(**kwargs):
        raise AssertionError("binary-backed tool should not reach local execution")

    monkeypatch.setattr(srv, "_execute_tool_with_timeout", _unexpected_execute)

    resp = srv.tool_execute(
        "fsl.bet",
        params={"in_file": "/tmp/in.nii.gz", "out_file": "/tmp/out.nii.gz"},
    )

    assert resp["ok"] is False
    assert resp["error"] == "binary_execution_recipe_required"
    assert resp["resolved_tool_id"] == "fsl.bet"
    assert resp["execution_story_kind"] == "binary_backed_atomic"
    assert resp["execution_recipe_available"] is True
    assert resp["supported_recipe_targets"] == ["neurodesk", "container", "slurm"]
    assert resp["recipe_lookup"]["tool"] == "get_execution_recipe"
    assert resp["recipe_lookup"]["args"]["target_runtime"] == "neurodesk"
    assert "runtime-specific binaries" in resp["message"]


def test_tool_execute_surfaces_policy_issues_and_persists_to_run(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec
    from brain_researcher.services.tools.tool_base import ToolResult

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"*"},
    )
    monkeypatch.setattr(srv, "is_workflow_tool_id", lambda _tool_id: False)
    monkeypatch.setattr(
        srv,
        "_preflight_tool_call",
        lambda tool_id, params, allowlist=None, step_id=None: (
            ToolSpec(name=tool_id, description="stub", backend="python"),
            [],
        ),
    )
    monkeypatch.setattr(
        srv,
        "_execute_tool_with_timeout",
        lambda **kwargs: ToolResult(
            status="error",
            error="execution_policy_violation",
            data={
                "policy_issues": [
                    {
                        "level": "error",
                        "code": "network_blocked_by_policy",
                        "message": "network blocked by policy",
                    }
                ]
            },
            metadata={"backend": "python"},
        ),
    )

    resp = srv.tool_execute("python.test_policy.run", params={"x": 1})
    assert resp["ok"] is False
    assert resp["error"] == "execution_policy_violation"
    assert isinstance(resp.get("policy_issues"), list)
    assert any(
        i.get("code") == "network_blocked_by_policy"
        for i in resp.get("policy_issues", [])
    )
    assert any(
        i.get("code") == "network_blocked_by_policy" for i in resp.get("issues", [])
    )

    run = srv.run_get(resp["run_id"])
    assert run["ok"] is True
    step = run["run"]["steps"][0]
    assert isinstance(step.get("policy_issues"), list)
    assert any(
        i.get("code") == "network_blocked_by_policy"
        for i in step.get("policy_issues", [])
    )


def test_tool_execute_allows_local_mcp_bridge_without_network(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec
    from brain_researcher.services.tools.tool_base import ToolResult

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"mcp.tool_search"},
    )
    monkeypatch.setattr(srv, "ALLOW_NETWORK", False)
    called: dict[str, str] = {}
    monkeypatch.setattr(
        srv,
        "_call_preflight_tool_call",
        lambda tool_id, params, allowlist=None, step_id=None, allow_remap=False: (
            ToolSpec(name=tool_id, description="stub", backend="external_api"),
            [],
        ),
    )

    def _fake_execute(**kwargs):
        called["tool_id"] = kwargs["tool_id"]
        return ToolResult(
            status="success",
            data={"ok": True, "tools": [{"name": "mcp.sherlock_slurm"}]},
            metadata={"tool_id": kwargs["tool_id"], "execution_mode": "direct"},
        )

    monkeypatch.setattr(srv, "_execute_tool_with_timeout", _fake_execute)

    resp = srv.tool_execute(
        "mcp.tool_search",
        params={"query": "patch sbatch script", "limit": 3},
        work_dir=str(tmp_path / "w"),
        output_dir=str(tmp_path / "o"),
    )

    assert resp["ok"] is True
    assert resp["execution_mode"] == "direct"
    assert "preflight_passed" in resp["execution_trace"]
    assert resp["requested_tool_id"] == "mcp.tool_search"
    assert resp["resolved_tool_id"] == "mcp.tool_search"
    assert resp["remap_applied"] is False
    assert called["tool_id"] == "mcp.tool_search"

    result = resp.get("result") or {}
    data = result.get("data") or {}
    assert data.get("ok") is True
    assert any(
        isinstance(tool, dict) and tool.get("name") == "mcp.sherlock_slurm"
        for tool in data.get("tools", [])
    )


def test_tool_execute_promotes_execution_pack_to_top_level_response(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec
    from brain_researcher.services.tools.tool_base import ToolResult

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"python.test_pack.run"},
    )
    monkeypatch.setattr(
        srv,
        "_call_preflight_tool_call",
        lambda tool_id, params, allowlist=None, step_id=None, allow_remap=False: (
            ToolSpec(name=tool_id, description="stub", backend="python"),
            [],
        ),
    )

    pack_info = {
        "workspace": str(tmp_path / "artifacts" / "step-01-s1" / "execution_pack"),
        "pack_manifest": str(
            tmp_path
            / "artifacts"
            / "step-01-s1"
            / "execution_pack"
            / "pack_manifest.json"
        ),
        "run_pack": str(
            tmp_path / "artifacts" / "step-01-s1" / "execution_pack" / "run_pack.py"
        ),
        "run_pack_command": "python run_pack.py",
    }

    monkeypatch.setattr(
        srv,
        "_execute_tool_with_timeout",
        lambda **kwargs: ToolResult(
            status="success",
            data={"ok": True},
            metadata={
                "backend": "python",
                "execution_mode": "direct",
                "execution_pack": pack_info,
            },
        ),
    )

    resp = srv.tool_execute("python.test_pack.run", params={"x": 1})

    assert resp["ok"] is True
    assert resp["execution_pack"] == pack_info
    assert resp["result"]["metadata"]["execution_pack"] == pack_info


def test_tool_execute_real_connectivity_execution_returns_execution_pack(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    run_root = tmp_path / "runs"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "artifacts"
    ts_path = tmp_path / "timeseries.npy"
    out_file = output_dir / "connectivity_matrix_fisherz.npy"

    run_root.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(0)
    np.save(ts_path, rng.normal(size=(60, 8)))

    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"connectivity_matrix"},
        run_root=run_root,
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "connectivity_matrix",
        params={
            "timeseries": str(ts_path),
            "kind": "correlation",
            "fisher_z": True,
            "output_file": str(out_file),
        },
        work_dir=str(work_dir),
        output_dir=str(output_dir),
    )

    assert resp["ok"] is True, resp
    assert resp["resolved_tool_id"] == "connectivity_matrix"
    assert resp["execution_mode"] == "direct"

    pack_workspace = output_dir / "execution_pack"
    _assert_execution_pack(
        resp,
        expected_workspace=pack_workspace,
        tool_id="connectivity_matrix",
    )
    assert out_file.is_file()


def test_tool_execute_real_registry_resolve_space_returns_execution_pack(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.neuroimage_asset_registry import (
        clear_neuroimage_asset_registry_cache,
    )

    template_root = tmp_path / "templates" / "MNI152"
    template_root.mkdir(parents=True, exist_ok=True)
    template_path = template_root / "tpl-MNI152NLin2009cAsym_res-2mm_T1w.nii.gz"
    mask_path = template_root / "tpl-MNI152NLin2009cAsym_res-2mm_desc-brain_mask.nii.gz"
    _write_mcp_nifti(template_path)
    _write_mcp_nifti(mask_path)
    registry_path = _write_mcp_neuroimage_registry(
        tmp_path,
        template_root=template_root.parent,
    )

    monkeypatch.setenv("BR_NEUROIMAGE_ASSET_REGISTRY", str(registry_path))
    clear_neuroimage_asset_registry_cache()
    _configure_tool_execute_test_env(
        monkeypatch,
        tmp_path,
        allowlist={"resolve_space"},
        use_real_toolspec_lookup=True,
    )

    output_dir = tmp_path / "artifacts"
    resp = srv.tool_execute(
        "resolve_space",
        params={"space_name": "MNI152NLin2009cAsym"},
        work_dir=str(tmp_path / "work"),
        output_dir=str(output_dir),
    )

    assert resp["ok"] is True, resp
    assert resp["resolved_tool_id"] == "resolve_space"
    assert resp["execution_mode"] == "direct"
    result = resp["result"]
    assert result["status"] == "success"
    assert result["data"]["outputs"]["template_volume"] == str(template_path)
    assert result["data"]["outputs"]["brain_mask"] == str(mask_path)

    _assert_execution_pack(
        resp,
        expected_workspace=output_dir / "execution_pack",
        tool_id="resolve_space",
    )


def test_tool_search_includes_transparency_metadata_fields(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    class StubRegistry:
        def search_toolspecs(self, **_kwargs):
            return (
                [
                    ToolSpec(
                        name="python_tool", description="python", backend="python"
                    ),
                    ToolSpec(
                        name="container_tool", description="niwrap", backend="niwrap"
                    ),
                    ToolSpec(
                        name="remote_tool",
                        description="external",
                        backend="external_api",
                    ),
                ],
                3,
            )

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(srv, "_load_grandmaster_atomic_tool_metadata", lambda: {})

    resp = srv.tool_search("tool", limit=10, exposed_only=False)
    assert resp["ok"] is True

    tools = {row["name"]: row for row in resp["tools"]}
    assert tools["python_tool"]["implementation_level"] == "production"
    assert tools["python_tool"]["requires_runtime"] == "python"
    assert tools["python_tool"]["hard_dependencies"] == []
    assert tools["container_tool"]["requires_runtime"] == "neurodesk"
    assert tools["remote_tool"]["requires_runtime"] == "network"


def test_google_file_search_is_runtime_registered_but_not_exposed():
    from brain_researcher.services.mcp import server as srv

    reg = srv._get_registry()
    reg.get_all_toolspecs(force_reload=True)
    reg.get_exposed_toolspecs(force_reload=True)

    hidden = srv.tool_search("google file search", limit=20, exposed_only=True)
    assert all(tool["name"] != "google.file_search" for tool in hidden["tools"])

    visible = srv.tool_search("google file search", limit=50, exposed_only=False)
    tool_names = [tool["name"] for tool in visible["tools"]]
    assert "google.file_search" in tool_names

    detail = srv.tool_get("google.file_search")
    assert detail["ok"] is True
    assert detail["tool"]["name"] == "google.file_search"
    assert detail["tool"]["requires_runtime"] == "network"


def test_tool_get_applies_grandmaster_metadata_overlay(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    class StubRegistry:
        def get_toolspec_by_name(self, name: str):
            if name == "individual_parcellation":
                return ToolSpec(
                    name="individual_parcellation",
                    description="stub",
                    backend="python",
                    requires_runtime=None,
                )
            return None

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda _tool_id: ToolSpec(
            name="individual_parcellation",
            description="stub",
            backend="python",
            requires_runtime=None,
        ),
    )
    monkeypatch.setattr(
        srv,
        "_load_grandmaster_atomic_tool_metadata",
        lambda: {
            "individual_parcellation": {
                "implementation_level": "production",
                "requires_runtime": "python",
                "hard_dependencies": ["numpy", "scikit-learn"],
            }
        },
    )

    resp = srv.tool_get("individual_parcellation")
    assert resp["ok"] is True
    tool = resp["tool"]
    assert tool["name"] == "individual_parcellation"
    assert tool["backend"] == "python"
    assert tool["implementation_level"] == "production"
    assert tool["requires_runtime"] == "python"
    assert tool["hard_dependencies"] == ["numpy", "scikit-learn"]


def test_tool_get_warns_agents_for_workflows(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    workflow_spec = ToolSpec(
        name="workflow_visual_decoding",
        description="Run the visual decoding workflow.",
        backend="python",
        python_class="pkg.Workflow",
        kind="analysis",
    )

    class StubRegistry:
        def get_toolspec_by_name(self, name: str):
            return workflow_spec if name == "workflow_visual_decoding" else None

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(
        srv, "_get_toolspec_with_schema", lambda _tool_id: workflow_spec
    )
    monkeypatch.setattr(srv, "_is_declared_workflow_id", lambda _tool_id: True)
    monkeypatch.setattr(srv, "_toolspec_runtime_callable", lambda _spec: True)
    monkeypatch.setattr(srv, "_load_grandmaster_atomic_tool_metadata", lambda: {})

    resp = srv.tool_get("workflow_visual_decoding")

    assert resp["ok"] is True
    assert srv.AGENT_LOCAL_EXECUTION_WARNING in resp["tool"]["description"]
    assert srv.AGENT_LOCAL_EXECUTION_WARNING in resp["message"]
    assert resp["tool"]["execution_recipe_available"] is False
    assert resp["tool"]["execution_story_kind"] == "composite_workflow"
    assert resp["tool"]["supported_recipe_targets"] == []


def test_tool_get_marks_first_wave_heavy_workflows_recipe_first():
    from brain_researcher.services.mcp import server as srv

    resp = srv.tool_get("workflow_mriqc")

    assert resp["ok"] is True
    assert resp["workflow_only"] is True
    assert resp["tool"]["heavy_runtime_workflow"] is True
    assert resp["tool"]["mcp_execution_posture"] == "recipe_first"
    assert resp["tool"]["direct_tool_execution_supported"] is False
    assert resp["tool"]["manual_pipeline_execution_only"] is True
    assert resp["tool"]["recommended_mcp_entrypoint"] == "get_execution_recipe"
    assert "recipe_first" in resp["tool"]["tags"]
    assert "external_runtime" in resp["tool"]["tags"]
    assert "heavy runtime workflow" in resp["message"]
    assert "get_execution_recipe" in resp["message"]
    assert "manual/admin approval paths" in resp["message"]


def test_tool_search_includes_workflows_by_default(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    class StubRegistry:
        def search_toolspecs(
            self,
            goal,
            modalities=None,
            kind=None,
            limit=20,
            offset=0,
            exposed_only=True,
            include_workflows=False,
        ):
            del goal, modalities, kind, limit, offset, exposed_only
            assert include_workflows is True
            return ([], 0)

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(srv, "load_orchestration_workflows", lambda: ["workflow_mriqc"])
    monkeypatch.setattr(
        srv,
        "_load_workflow_catalog",
        lambda: [
            {
                "id": "workflow_mriqc",
                "stage": "qc",
                "cost_tier": "moderate",
                "description": "MRIQC workflow",
                "modalities": ["fmri"],
            }
        ],
    )
    monkeypatch.setattr(srv, "_load_grandmaster_atomic_tool_metadata", lambda: {})

    resp = srv.tool_search("mriqc", limit=20, exposed_only=True)
    assert resp["ok"] is True
    names = {tool.get("name") for tool in resp.get("tools", [])}
    assert "workflow_mriqc" in names


def test_tool_get_marks_long_running_batch_workflows_recipe_first():
    from brain_researcher.services.mcp import server as srv

    resp = srv.tool_get("workflow_task_glm_group")

    assert resp["ok"] is True
    assert resp["workflow_only"] is True
    assert resp["tool"]["recipe_first_workflow"] is True
    assert resp["tool"]["batch_analysis_workflow"] is True
    assert resp["tool"]["workflow_surface_class"] == "batch_analysis"
    assert resp["tool"]["mcp_execution_posture"] == "recipe_first"
    assert resp["tool"]["direct_tool_execution_supported"] is False
    assert resp["tool"]["manual_pipeline_execution_only"] is True
    assert resp["tool"]["recommended_mcp_entrypoint"] == "get_execution_recipe"
    assert "recipe_first" in resp["tool"]["tags"]
    assert "batch_analysis" in resp["tool"]["tags"]
    assert "external_runtime" not in resp["tool"]["tags"]
    assert "long-running batch analysis workflow" in resp["message"]
    assert "python execution recipe" in resp["message"]


def test_tool_search_exposes_recipe_first_metadata_for_heavy_workflows(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    workflow_spec = ToolSpec(
        name="workflow_mriqc",
        description="MRIQC workflow",
        backend="python",
        python_class="pkg.Workflow",
        kind="analysis",
    )

    class StubRegistry:
        def search_toolspecs(
            self,
            goal,
            modalities=None,
            kind=None,
            limit=20,
            offset=0,
            exposed_only=True,
            include_workflows=False,
            phases=None,
        ):
            del goal, modalities, kind, limit, offset, exposed_only, phases
            assert include_workflows is True
            return ([workflow_spec], 1)

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(srv, "load_orchestration_workflows", lambda: ["workflow_mriqc"])
    monkeypatch.setattr(
        srv,
        "_load_workflow_catalog",
        lambda: [
            {
                "id": "workflow_mriqc",
                "stage": "qc",
                "cost_tier": "expensive",
                "description": "MRIQC workflow",
                "modalities": ["fmri"],
            }
        ],
    )
    monkeypatch.setattr(srv, "_load_grandmaster_atomic_tool_metadata", lambda: {})

    resp = srv.tool_search("mriqc", limit=20, exposed_only=True)

    assert resp["ok"] is True
    card = next(tool for tool in resp["tools"] if tool["name"] == "workflow_mriqc")
    assert card["heavy_runtime_workflow"] is True
    assert card["mcp_execution_posture"] == "recipe_first"
    assert card["recommended_mcp_entrypoint"] == "get_execution_recipe"
    assert card["direct_tool_execution_supported"] is False
    assert card["manual_pipeline_execution_only"] is True
    assert "recipe_first" in card["tags"]
    assert "external_runtime" in card["tags"]


def test_tool_search_exposes_recipe_first_metadata_for_batch_workflows(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    workflow_spec = ToolSpec(
        name="workflow_group_ica",
        description="Group ICA workflow",
        backend="python",
        python_class="pkg.Workflow",
        kind="analysis",
    )

    class StubRegistry:
        def search_toolspecs(
            self,
            goal,
            modalities=None,
            kind=None,
            limit=20,
            offset=0,
            exposed_only=True,
            include_workflows=False,
            phases=None,
        ):
            del goal, modalities, kind, limit, offset, exposed_only, phases
            assert include_workflows is True
            return ([workflow_spec], 1)

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(
        srv, "load_orchestration_workflows", lambda: ["workflow_group_ica"]
    )
    monkeypatch.setattr(
        srv,
        "_load_workflow_catalog",
        lambda: [
            {
                "id": "workflow_group_ica",
                "stage": "analysis",
                "cost_tier": "expensive",
                "description": "Group ICA workflow",
                "modalities": ["fmri"],
            }
        ],
    )
    monkeypatch.setattr(srv, "_load_grandmaster_atomic_tool_metadata", lambda: {})

    resp = srv.tool_search("group ica", limit=20, exposed_only=True)

    assert resp["ok"] is True
    card = next(tool for tool in resp["tools"] if tool["name"] == "workflow_group_ica")
    assert card["recipe_first_workflow"] is True
    assert card["batch_analysis_workflow"] is True
    assert card["workflow_surface_class"] == "batch_analysis"
    assert card["mcp_execution_posture"] == "recipe_first"
    assert card["recommended_mcp_entrypoint"] == "get_execution_recipe"
    assert card["direct_tool_execution_supported"] is False
    assert card["manual_pipeline_execution_only"] is True
    assert "recipe_first" in card["tags"]
    assert "batch_analysis" in card["tags"]
    assert "external_runtime" not in card["tags"]


def test_tool_search_phase_filter_supports_legacy_registry_signature(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    class StubRegistry:
        def search_toolspecs(
            self,
            goal,
            modalities=None,
            kind=None,
            limit=20,
            offset=0,
            exposed_only=True,
            include_workflows=False,
        ):
            del goal, modalities, kind, limit, offset, exposed_only, include_workflows
            return (
                [
                    ToolSpec(
                        name="datasets.describe_resources",
                        description="Describe mounted dataset resources",
                        backend="python",
                        category="data",
                    ),
                    ToolSpec(
                        name="extract_timeseries",
                        description="Extract atlas timeseries from fMRI data",
                        backend="python",
                        category="analysis",
                    ),
                ],
                2,
            )

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(srv, "_load_grandmaster_atomic_tool_metadata", lambda: {})
    monkeypatch.setattr(srv, "load_orchestration_workflows", lambda: [])
    monkeypatch.setattr(srv, "_load_workflow_catalog", lambda: [])
    monkeypatch.setattr(
        srv,
        "_tool_search_family_ranked_ids",
        lambda query, limit: [],
    )

    resp = srv.tool_search("timeseries", phases=["execute"], include_workflows=False)

    assert resp["ok"] is True
    assert [tool["name"] for tool in resp["tools"]] == ["extract_timeseries"]
    card = resp["tools"][0]
    assert card["allowed_phases"] == ["execute"]
    assert card["approval_level"] == "confirm"
    assert isinstance(card["search_hint"], str)
    assert card["search_hint"]


def test_tool_search_mixes_workflow_results_by_relevance(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    class StubRegistry:
        def search_toolspecs(
            self,
            goal,
            modalities=None,
            kind=None,
            limit=20,
            offset=0,
            exposed_only=True,
            include_workflows=False,
        ):
            del goal, modalities, kind, limit, offset, exposed_only, include_workflows
            return (
                [
                    ToolSpec(
                        name="datasets.list_resources",
                        description="Resolve mounted datasets and derivative resources",
                        backend="python",
                        category="data",
                    ),
                    ToolSpec(
                        name="pipeline.search",
                        description="Search pipeline definitions and execution plans",
                        backend="python",
                        category="analysis",
                    ),
                    ToolSpec(
                        name="mcp.server_info",
                        description="Return MCP server configuration and capabilities",
                        backend="external_api",
                        category="meta",
                    ),
                ],
                3,
            )

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(srv, "load_orchestration_workflows", lambda: ["workflow_mriqc"])
    monkeypatch.setattr(
        srv,
        "_load_workflow_catalog",
        lambda: [
            {
                "id": "workflow_mriqc",
                "stage": "qc",
                "cost_tier": "moderate",
                "description": "Run the MRIQC workflow for BIDS quality control reports",
                "modalities": ["fmri", "smri"],
                "supported_recipe_targets": ["container", "slurm"],
            }
        ],
    )
    monkeypatch.setattr(srv, "_load_grandmaster_atomic_tool_metadata", lambda: {})

    resp = srv.tool_search("mriqc workflow", limit=5, exposed_only=True)

    assert resp["ok"] is True
    tools = resp.get("tools", [])
    assert tools
    assert tools[0]["name"] == "workflow_mriqc"


def test_tool_search_family_router_backfills_and_reranks_cards(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    class StubRegistry:
        def search_toolspecs(
            self,
            goal,
            modalities=None,
            kind=None,
            limit=20,
            offset=0,
            exposed_only=True,
            include_workflows=False,
        ):
            del goal, modalities, kind, limit, offset, exposed_only, include_workflows
            return (
                [
                    ToolSpec(
                        name="datasets.list_resources",
                        description="Resolve mounted datasets and derivative resources",
                        backend="python",
                        category="data",
                    )
                ],
                1,
            )

        def get_toolspec_by_name(self, name: str):
            if name == "seed_based_fc":
                return ToolSpec(
                    name="seed_based_fc",
                    description="Seed-based resting-state connectivity analysis",
                    backend="python",
                    category="analysis",
                    intents=["seed_connectivity"],
                )
            if name == "datasets.list_resources":
                return ToolSpec(
                    name="datasets.list_resources",
                    description="Resolve mounted datasets and derivative resources",
                    backend="python",
                    category="data",
                )
            return None

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(srv, "_load_grandmaster_atomic_tool_metadata", lambda: {})
    monkeypatch.setattr(srv, "load_orchestration_workflows", lambda: [])
    monkeypatch.setattr(srv, "_load_workflow_catalog", lambda: [])
    monkeypatch.setattr(
        "brain_researcher.services.tools.catalog_loader.load_tool_specs",
        lambda **kwargs: [
            ToolSpec(
                name="seed_based_fc",
                description="Seed-based resting-state connectivity analysis",
                backend="python",
                category="analysis",
                intents=["seed_connectivity"],
            ),
            ToolSpec(
                name="datasets.list_resources",
                description="Resolve mounted datasets and derivative resources",
                backend="python",
                category="data",
            ),
        ],
    )
    monkeypatch.setattr(
        srv,
        "_tool_search_family_ranked_ids",
        lambda query, limit: ["seed_based_fc", "datasets.list_resources"],
    )

    resp = srv.tool_search("resting-state connectivity", limit=5, exposed_only=True)

    assert resp["ok"] is True
    names = [tool.get("name") for tool in resp.get("tools", [])]
    assert "seed_based_fc" in names
    assert names[0] == "seed_based_fc"


def test_plan_preflight_returns_facts_and_phase_filtered_candidates(monkeypatch):
    from brain_researcher.services.agent.tool_candidate_service import (
        ToolCandidateBundle,
    )
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_candidate_service.generate_tool_candidates",
        lambda query, **kwargs: ToolCandidateBundle(
            ctx={"runtime_surface": "plan_preflight"},
            query_understanding={
                "resolved_datasets": [{"dataset_id": "ds000114"}],
                "available_derivatives": ["fmriprep"],
                "blockers": ["events.tsv missing for sub-04"],
                "data_quality_flags": ["high motion"],
            },
            tool_candidates=[{"tool_id": "datasets.describe_resources"}],
            tool_candidate_diagnostics={"candidate_count": 1, "retrieval_path": "stub"},
            resolution_state={"pending_decisions": []},
        ),
    )
    monkeypatch.setattr(
        srv,
        "tool_search",
        lambda *args, **kwargs: {
            "ok": True,
            "tools": [
                {
                    "name": "datasets.describe_resources",
                    "allowed_phases": ["explore", "plan"],
                    "approval_level": "none",
                }
            ],
        },
    )

    resp = srv.plan_preflight(
        "summarize ds000114",
        modality=["fmri"],
        inputs={"dataset_ref": "ds000114"},
    )

    assert resp["ok"] is True
    assert resp["facts"]["dataset_refs"] == ["ds000114"]
    assert resp["facts"]["derivatives"] == ["fmriprep"]
    assert resp["facts"]["blockers"] == ["events.tsv missing for sub-04"]
    assert resp["facts"]["data_quality_concerns"] == ["high motion"]
    assert resp["tool_candidates"][0]["name"] == "datasets.describe_resources"
    assert resp["recommended_next_calls"][0]["tool_name"] == "dataset_get_resources"
    assert resp["recommended_next_calls"][0]["arguments"] == {"dataset_ref": "ds000114"}
    assert resp["recommended_next_calls"][1]["tool_name"] == "get_execution_recipe"
    assert resp["recommended_next_calls"][1]["arguments"]["tool_id"] == (
        "datasets.describe_resources"
    )
    assert resp["selection_contract"]["preferred_next_step"] == (
        "Call one recommended_next_calls entry next."
    )
    assert resp["routing_diagnostics"]["candidate_count"] == 1


def test_plan_preflight_defaults_semantic_scope_to_lightweight(monkeypatch):
    from brain_researcher.services.agent.tool_candidate_service import (
        ToolCandidateBundle,
    )
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.shared.runtime_semantic import (
        semantic_matching_enabled,
    )

    captured: dict[str, object] = {}

    def fake_generate_tool_candidates(query, **kwargs):
        del query, kwargs
        captured["semantic_enabled"] = semantic_matching_enabled()
        return ToolCandidateBundle(
            ctx={"runtime_surface": "plan_preflight"},
            query_understanding={},
            tool_candidates=[],
            tool_candidate_diagnostics={},
            resolution_state={},
        )

    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_candidate_service.generate_tool_candidates",
        fake_generate_tool_candidates,
    )
    monkeypatch.setattr(
        srv,
        "tool_search",
        lambda *args, **kwargs: {"ok": True, "tools": []},
    )

    resp = srv.plan_preflight("summarize ds000114", selection_mode=True)

    assert resp["ok"] is True
    assert resp["selection_mode"] is True
    assert resp["selection_contract"]["do_not_probe_environment"] is True
    assert captured["semantic_enabled"] is False


def test_plan_preflight_selection_mode_injects_query_derived_next_calls(monkeypatch):
    from brain_researcher.services.agent.tool_candidate_service import (
        ToolCandidateBundle,
    )
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_candidate_service.generate_tool_candidates",
        lambda query, **kwargs: ToolCandidateBundle(
            ctx={"runtime_surface": "plan_preflight"},
            query_understanding={},
            tool_candidates=[],
            tool_candidate_diagnostics={"candidate_count": 0},
            resolution_state={"pending_decisions": []},
        ),
    )
    monkeypatch.setattr(
        srv,
        "tool_search",
        lambda *args, **kwargs: {"ok": True, "tools": []},
    )

    resp = srv.plan_preflight(
        "Run MRIQC on Haxby dataset and generate quality reports",
        selection_mode=True,
    )

    next_calls = resp["recommended_next_calls"]
    assert next_calls[0]["tool_name"] == "dataset_get_resources"
    assert next_calls[0]["arguments"] == {"dataset_ref": "haxby"}
    assert next_calls[1]["tool_name"] == "get_execution_recipe"
    assert next_calls[1]["purpose"] == "qc_reporting"
    assert next_calls[1]["arguments"]["tool_id"] == "mriqc"
    assert next_calls[1]["arguments"]["target_runtime"] == "neurodesk"


def test_plan_create_returns_display_and_execution_envelopes(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    class StubRegistry:
        def get_toolspec_by_name(self, name: str):
            if name == "extract_timeseries":
                return ToolSpec(
                    name="extract_timeseries",
                    description="Extract atlas timeseries from fMRI data",
                    backend="python",
                    category="analysis",
                )
            return None

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(
        srv,
        "_call_agent_plan_contract",
        lambda payload: (
            200,
            {
                "plan_id": "plan-123",
                "version": 2,
                "por_token": "por-token-123",
                "pipeline": payload["pipeline"],
                "chosen_tool": "extract_timeseries",
                "resolvable": True,
                "warnings": ["confirm atlas choice before execution"],
                "dag": {
                    "steps": [
                        {
                            "id": "001-main",
                            "tool": "extract_timeseries",
                            "params": {
                                "dataset_ref": "ds000114",
                                "atlas": "aal",
                            },
                            "runtime_kind": "python",
                        }
                    ]
                },
                "context": {
                    "pipeline": payload["pipeline"],
                    "inputs": {"dataset_ref": "ds000114", "atlas": "aal"},
                    "query_understanding": {
                        "resolved_datasets": [{"dataset_id": "ds000114"}]
                    },
                },
                "routing_diagnostics": {"candidate_count": 3},
                "planner_state": {"stage": "done"},
                "planner_events": [{"event": "selected_tool"}],
                "candidates": [{"tool_id": "extract_timeseries"}],
            },
        ),
    )

    resp = srv.plan_create(
        "extract ROI timeseries for ds000114",
        modality=["fmri"],
        inputs={"dataset_ref": "ds000114", "atlas": "aal"},
        include_debug=True,
    )

    assert resp["ok"] is True
    assert "display" in resp
    assert "execution" in resp
    assert "extract_timeseries" in resp["display"]["markdown"]
    assert resp["display"]["summary"]["dataset_scope"] == "ds000114"
    assert resp["execution"]["schema_version"] == "br-plan-execution-v1"
    assert resp["execution"]["plan_id"] == "plan-123"
    assert resp["execution"]["allowed_tools"] == ["extract_timeseries"]
    assert resp["execution"]["approval_level"] == "confirm"
    assert resp["execution"]["run_mode_hint"] == "confirm_before_execute"
    assert resp["execution"]["handoff"]["dataset_ref"] == "ds000114"
    assert resp["debug"]["routing_diagnostics"]["candidate_count"] == 3


def test_tool_search_family_router_skips_explicit_tool_queries(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setenv("BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE", "cards")
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.rank_family_card_entrypoints",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("family router should not be called")
        ),
    )

    ranked = srv._tool_search_family_ranked_ids("fsl.bet.run", limit=10)
    canonical_ranked = srv._tool_search_family_ranked_ids("fsl_bet", limit=10)
    alias_ranked = srv._tool_search_family_ranked_ids("cat12", limit=10)

    assert ranked == []
    assert canonical_ranked == []
    assert alias_ranked == []


def test_tool_search_family_router_does_not_leak_hidden_tools_when_exposed(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    class StubRegistry:
        def search_toolspecs(
            self,
            goal,
            modalities=None,
            kind=None,
            limit=20,
            offset=0,
            exposed_only=True,
            include_workflows=False,
        ):
            del goal, modalities, kind, limit, offset, exposed_only, include_workflows
            return ([], 0)

        def get_toolspec_by_name(self, name: str):
            if name == "hidden_tool":
                return ToolSpec(
                    name="hidden_tool",
                    description="not exposed but resolvable",
                    backend="python",
                    category="analysis",
                )
            return None

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(srv, "_load_grandmaster_atomic_tool_metadata", lambda: {})
    monkeypatch.setattr(
        "brain_researcher.services.tools.catalog_loader.load_tool_specs",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        srv,
        "_tool_search_family_ranked_ids",
        lambda query, limit: ["hidden_tool"],
    )

    resp = srv.tool_search("query", limit=5, exposed_only=True, include_workflows=False)

    assert resp["ok"] is True
    assert resp["tools"] == []


def test_tool_search_family_router_respects_offset_without_workflows(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    class StubRegistry:
        def search_toolspecs(
            self,
            goal,
            modalities=None,
            kind=None,
            limit=20,
            offset=0,
            exposed_only=True,
            include_workflows=False,
        ):
            del goal, modalities, kind, exposed_only, include_workflows
            specs = [
                ToolSpec(
                    name="a_tool",
                    description="alpha result",
                    backend="python",
                    category="analysis",
                ),
                ToolSpec(
                    name="b_tool",
                    description="beta result",
                    backend="python",
                    category="analysis",
                ),
                ToolSpec(
                    name="c_tool",
                    description="gamma result",
                    backend="python",
                    category="analysis",
                ),
            ]
            return (specs[offset : offset + limit], len(specs))

        def get_toolspec_by_name(self, name: str):
            if name == "family_tool":
                return ToolSpec(
                    name="family_tool",
                    description="family-ranked result",
                    backend="python",
                    category="analysis",
                )
            return None

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(srv, "_load_grandmaster_atomic_tool_metadata", lambda: {})
    monkeypatch.setattr(
        "brain_researcher.services.tools.catalog_loader.load_tool_specs",
        lambda **kwargs: [
            ToolSpec(
                name="a_tool",
                description="alpha result",
                backend="python",
                category="analysis",
            ),
            ToolSpec(
                name="b_tool",
                description="beta result",
                backend="python",
                category="analysis",
            ),
            ToolSpec(
                name="family_tool",
                description="family-ranked result",
                backend="python",
                category="analysis",
            ),
        ],
    )
    monkeypatch.setattr(
        srv,
        "_tool_search_family_ranked_ids",
        lambda query, limit: ["family_tool"],
    )

    resp = srv.tool_search(
        "alpha",
        limit=1,
        offset=1,
        exposed_only=True,
        include_workflows=False,
    )

    assert resp["ok"] is True
    assert [tool["name"] for tool in resp["tools"]] == ["a_tool"]


def test_workflow_search_lists_orchestration_workflows(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "load_orchestration_workflows",
        lambda: [
            "workflow_preprocessing_qc",
            "workflow_spatial_correlation",
            "workflow_gene_enrichment",
        ],
    )
    monkeypatch.setattr(
        srv,
        "_load_workflow_catalog",
        lambda: [
            {
                "id": "workflow_preprocessing_qc",
                "stage": "preprocess",
                "cost_tier": "cheap",
                "description": "preprocessing workflow",
                "modalities": [],
            },
            {
                "id": "workflow_spatial_correlation",
                "stage": "interpretation",
                "cost_tier": "moderate",
                "description": "spatial correlation workflow",
                "modalities": [],
            },
            {
                "id": "workflow_gene_enrichment",
                "stage": "interpretation",
                "cost_tier": "moderate",
                "description": "gene enrichment workflow",
                "modalities": [],
            },
            {
                "id": "workflow_not_allowed",
                "stage": "misc",
                "cost_tier": "cheap",
                "description": "should be filtered out",
                "modalities": [],
            },
        ],
    )

    resp = srv.workflow_search("workflow", limit=50)
    assert resp["ok"] is True
    workflow_ids = {w.get("id") for w in resp.get("workflows", [])}
    assert "workflow_preprocessing_qc" in workflow_ids
    assert "workflow_spatial_correlation" in workflow_ids
    assert "workflow_gene_enrichment" in workflow_ids
    assert "workflow_not_allowed" not in workflow_ids


def test_workflow_search_includes_recipe_metadata():
    from brain_researcher.services.mcp import server as srv

    resp = srv.workflow_search("workflow_preprocessing_qc", limit=10)
    assert resp["ok"] is True
    row = next(
        workflow
        for workflow in resp["workflows"]
        if workflow.get("id") == "workflow_preprocessing_qc"
    )
    assert row["execution_recipe_available"] is True
    assert row["execution_story_kind"] == "composite_workflow"
    assert row["supported_recipe_targets"] == ["neurodesk", "container", "slurm"]
    assert row["requires_runtime"] == "neurodesk"


def test_workflow_search_omits_empty_stable_pack_provenance(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "load_orchestration_workflows",
        lambda: ["workflow_precision_parcellation"],
    )

    resp = srv.workflow_search("precision", limit=10)
    assert resp["ok"] is True
    row = next(
        workflow
        for workflow in resp["workflows"]
        if workflow.get("id") == "workflow_precision_parcellation"
    )
    assert "source_repo" not in row
    assert "source_paper" not in row
    assert "tested_release" not in row


def test_workflow_search_surfaces_spd_connectome_analysis(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.catalog_loader import (
        load_orchestration_workflows as real_load_orchestration_workflows,
    )

    monkeypatch.setattr(
        srv, "load_orchestration_workflows", real_load_orchestration_workflows
    )

    resp = srv.workflow_search("spd_connectome", limit=10)
    assert resp["ok"] is True
    row = next(
        workflow
        for workflow in resp["workflows"]
        if workflow.get("id") == "workflow_spd_connectome_analysis"
    )
    assert row["execution_recipe_available"] is False
    assert row["execution_story_kind"] == "composite_workflow"
    assert row["supported_recipe_targets"] == []
    assert row["recipe_depth"] == "summary"
    assert "runtime" not in row
    assert "recipe_family" not in row


def test_execution_recipe_audit_reports_declared_and_inferred_metadata():
    from scripts.tools.audit_execution_recipes import build_audit

    payload = build_audit()

    assert "declared_story_kind_mismatches" in payload["summary"]
    assert "declared_supported_target_mismatches" in payload["summary"]
    assert "declared_primary_target_mismatches" in payload["summary"]

    spd_row = next(
        row
        for row in payload["workflows"]
        if row.get("id") == "workflow_spd_connectome_analysis"
    )
    assert spd_row["has_declared_recipe_metadata"] is True
    assert spd_row["declared_execution_story_kind"] == "composite_workflow"
    assert "inferred_execution_story_kind" in spd_row

    ds_row = next(
        row for row in payload["tools"] if row.get("id") == "datasets.list_resources"
    )
    assert ds_row["execution_story_kind"] == "hosted_or_stateful_service"
    assert ds_row["hosted_via_br_mcp_service"] is True


def test_workflow_search_exposes_lifecycle_and_params(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "load_orchestration_workflows",
        lambda: ["workflow_spatial_correlation"],
    )
    monkeypatch.setattr(
        srv,
        "_load_workflow_catalog",
        lambda: [
            {
                "id": "workflow_spatial_correlation",
                "stage": "interpretation",
                "cost_tier": "moderate",
                "origin": "trend_addition",
                "lifecycle": "active",
                "description": "Spatial correlation workflow",
                "modalities": ["fmri"],
                "est_runtime": "5-10 min",
                "params": {
                    "schema": {
                        "type": "object",
                        "required": ["reference_term", "map_file"],
                        "properties": {
                            "reference_term": {"type": "string"},
                            "map_file": {"type": "string"},
                        },
                    },
                    "defaults": {"n_perm": 1000},
                },
            }
        ],
    )

    resp = srv.workflow_search("spatial", limit=10)
    assert resp["ok"] is True
    workflows = resp.get("workflows", [])
    assert len(workflows) == 1
    row = workflows[0]
    assert row["id"] == "workflow_spatial_correlation"
    assert row["lifecycle"] == "active"
    assert row["params"]["defaults"]["n_perm"] == 1000
    assert row["params"]["schema"]["required"] == ["reference_term", "map_file"]


def test_workflow_search_can_include_param_schema_summary(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "load_orchestration_workflows",
        lambda: ["workflow_spatial_correlation"],
    )
    monkeypatch.setattr(
        srv,
        "_load_workflow_catalog",
        lambda: [
            {
                "id": "workflow_spatial_correlation",
                "stage": "interpretation",
                "cost_tier": "moderate",
                "description": "Spatial correlation workflow",
                "modalities": ["fmri"],
                "params": {
                    "schema": {
                        "type": "object",
                        "required": ["reference_term", "map_file"],
                        "properties": {
                            "reference_term": {"type": "string"},
                            "map_file": {"type": "string"},
                            "n_perm": {"type": "integer"},
                        },
                    },
                    "defaults": {"n_perm": 1000},
                },
            }
        ],
    )

    resp = srv.workflow_search(
        "spatial",
        limit=10,
        include_param_schema_summary=True,
    )
    assert resp["ok"] is True
    assert resp["include_param_schema_summary"] is True
    workflows = resp.get("workflows", [])
    assert len(workflows) == 1
    summary = workflows[0]["params_summary"]
    assert summary["required"] == ["reference_term", "map_file"]
    assert summary["properties"]["n_perm"] == "integer"
    assert summary["default_keys"] == ["n_perm"]
    assert summary["has_schema"] is True
    assert summary["has_defaults"] is True


def test_workflow_search_includes_orchestration_ids_missing_catalog_metadata(
    monkeypatch,
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "load_orchestration_workflows",
        lambda: ["workflow_visual_decoding", "workflow_missing_metadata"],
    )
    monkeypatch.setattr(
        srv,
        "_load_workflow_catalog",
        lambda: [
            {
                "id": "workflow_visual_decoding",
                "stage": "prediction",
                "cost_tier": "expensive",
                "description": "Visual decoding workflow",
                "modalities": ["fmri"],
                "params": None,
            }
        ],
    )

    resp = srv.workflow_search("workflow", limit=50)
    assert resp["ok"] is True
    workflows = resp.get("workflows", [])
    ids = [row.get("id") for row in workflows]
    assert "workflow_visual_decoding" in ids
    assert "workflow_missing_metadata" in ids

    missing_row = next(
        row for row in workflows if row.get("id") == "workflow_missing_metadata"
    )
    assert missing_row["description"] == "workflow_missing_metadata"
    assert missing_row["origin"] == "orchestration"
    assert missing_row["modalities"] == []


def test_workflow_discoverability_consistent_across_search_get_and_workflow_search(
    monkeypatch,
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    class StubRegistry:
        def search_toolspecs(
            self,
            goal,
            modalities=None,
            kind=None,
            limit=20,
            offset=0,
            exposed_only=True,
            include_workflows=False,
        ):
            del goal, modalities, kind, limit, offset, exposed_only
            if not include_workflows:
                return ([], 0)
            return (
                [
                    ToolSpec(
                        name="workflow_visual_decoding",
                        description="visual decoding workflow",
                        backend="python",
                        category="workflow",
                    )
                ],
                1,
            )

        def get_toolspec_by_name(self, _name: str):
            # Simulate registry miss despite search indexing.
            return None

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(
        srv,
        "load_orchestration_workflows",
        lambda: ["workflow_visual_decoding"],
    )
    monkeypatch.setattr(srv, "_load_workflow_catalog", lambda: [])
    monkeypatch.setattr(srv, "_load_grandmaster_atomic_tool_metadata", lambda: {})

    search = srv.tool_search("visual", exposed_only=True, limit=50)
    assert search["ok"] is True
    names = {tool.get("name") for tool in search.get("tools", [])}
    assert "workflow_visual_decoding" in names
    assert "filtered_uncallable_workflows" not in search

    get_resp = srv.tool_get("workflow_visual_decoding", include_schema=True)
    assert get_resp["ok"] is False
    assert get_resp["error"] == "workflow_registry_mismatch"

    workflow_resp = srv.workflow_search("visual", limit=50)
    assert workflow_resp["ok"] is True
    workflow_ids = {row.get("id") for row in workflow_resp.get("workflows", [])}
    assert "workflow_visual_decoding" in workflow_ids


def test_tool_get_returns_registry_mismatch_for_non_registry_workflow(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    class StubRegistry:
        def get_toolspec_by_name(self, _name: str):
            return None

    monkeypatch.setattr(srv, "_get_registry", lambda: StubRegistry())
    monkeypatch.setattr(
        srv,
        "is_workflow_tool_id",
        lambda tool_id: tool_id == "workflow_visual_decoding",
    )
    monkeypatch.setattr(
        srv,
        "_is_declared_workflow_id",
        lambda tool_id: tool_id == "workflow_visual_decoding",
    )
    monkeypatch.setattr(
        srv,
        "_load_workflow_catalog",
        lambda: [
            {
                "id": "workflow_visual_decoding",
                "description": "Visual decoding workflow",
                "cost_tier": "expensive",
                "modalities": ["fmri"],
                "lifecycle": "active",
                "params": {
                    "schema": {
                        "type": "object",
                        "required": ["features", "labels", "output_dir"],
                        "properties": {
                            "features": {"type": "string"},
                            "labels": {"type": "string"},
                            "output_dir": {"type": "string"},
                        },
                    }
                },
            }
        ],
    )
    monkeypatch.setattr(srv, "_load_grandmaster_atomic_tool_metadata", lambda: {})

    resp = srv.tool_get("workflow_visual_decoding", include_schema=True)
    assert resp["ok"] is False
    assert resp["error"] == "workflow_registry_mismatch"


def test_run_cancel_marks_run_cancelled(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()
    run_id = "cancel_test"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "created_at": "2025-12-20T00:00:00Z",
        "status": "running",
        "dry_run": False,
        "steps": [
            {"step_id": "s1", "tool_id": "extract_timeseries", "status": "queued"}
        ],
    }
    (run_dir / "run.json").write_text(json.dumps(payload))

    monkeypatch.setattr(srv, "_utc_iso", lambda: "2025-12-20T00:00:01Z")
    cancel = srv.run_cancel(run_id, reason="test")
    assert cancel == {"ok": True, "run_id": run_id, "status": "cancelled"}

    run = srv.run_get(run_id)
    assert run["run"]["status"] == "cancelled"
    assert run["progress"]["stalled"] is False
    assert run["progress"]["current_stage"] == "cancelled"
    assert run["progress"]["message"] == "test"


def test_run_get_reports_stalled_progress(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()
    run_id = "stalled_test"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "created_at": "2025-12-20T00:00:00Z",
        "started_at": "2025-12-20T00:00:10Z",
        "status": "running",
        "dry_run": False,
        "progress": {
            "current_stage": "deep_research",
            "message": "Waiting on provider",
            "last_progress_at": "2025-12-20T00:01:00Z",
        },
        "timing_policy": {
            "heartbeat_interval_seconds": 30,
            "stall_timeout_seconds": 120,
            "soft_timeout_seconds": 300,
            "hard_timeout_seconds": 1800,
        },
        "steps": [],
    }
    (run_dir / "run.json").write_text(json.dumps(payload))

    monkeypatch.setattr(
        srv, "_epoch_ms", lambda: srv._iso_to_epoch_ms("2025-12-20T00:04:00Z")
    )
    run = srv.run_get(run_id)
    assert run["ok"] is True
    assert run["progress"]["current_stage"] == "deep_research"
    assert run["progress"]["message"] == "Waiting on provider"
    assert run["progress"]["stalled"] is True
    assert run["progress"]["silence_seconds"] == 180.0


def test_run_heartbeat_preserves_latest_progress_stage(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    run_id = "heartbeat_preserve_stage"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    record = srv.RunRecord(
        run_id=run_id,
        created_at="2025-12-20T00:00:00Z",
        status="running",
        dry_run=False,
        progress={
            "current_stage": "candidate_cards",
            "message": "Running candidate cards generation",
            "progress_pct": 0.0,
            "last_progress_at": "2025-12-20T00:00:00Z",
        },
        timing_policy=srv._default_run_timing_policy(),
        steps=[
            srv.StepRecord(
                step_id="candidate_cards",
                tool_id="kg_hypothesis_candidate_cards",
                status="running",
                progress={
                    "current_stage": "candidate_cards",
                    "message": "Running candidate cards generation",
                    "progress_pct": 0.0,
                    "last_progress_at": "2025-12-20T00:00:00Z",
                },
            )
        ],
    )
    srv._save_run(record, run_dir=run_dir)

    stop = srv._start_run_heartbeat(
        run_id,
        stage="candidate_cards",
        message="Running candidate cards generation",
        progress_pct=0.0,
        step_index=0,
        run_dir=run_dir,
        interval_seconds=1,
    )
    try:
        srv._set_run_stage(
            run_id,
            stage="workflow_done",
            message="Workflow execution completed",
            progress_pct=30.0,
            step_index=0,
            run_dir=run_dir,
        )
        updated_at = srv._load_run(run_id).progress["last_progress_at"]

        deadline = time.time() + 3.0
        while time.time() < deadline:
            current = srv._load_run(run_id)
            if current.progress.get("last_progress_at") != updated_at:
                break
            time.sleep(0.05)

        current = srv._load_run(run_id)
        assert current.progress["last_progress_at"] != updated_at
        assert current.progress["current_stage"] == "workflow_done"
        assert current.progress["message"] == "Workflow execution completed"
        assert current.progress["progress_pct"] == 30.0
        assert current.steps[0].progress["current_stage"] == "workflow_done"
        assert current.steps[0].progress["message"] == "Workflow execution completed"
        assert current.steps[0].progress["progress_pct"] == 30.0
    finally:
        stop.set()


def test_run_get_falls_back_to_alias_root(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    primary_root = tmp_path / "primary"
    alias_root = tmp_path / "alias"
    monkeypatch.setattr(srv, "RUN_ROOT", primary_root)
    monkeypatch.setenv("BR_MCP_RUN_ROOT_ALIASES", str(alias_root))

    run_id = "legacy_run_001"
    run_dir = alias_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "created_at": "2025-12-20T00:00:00Z",
        "status": "succeeded",
        "dry_run": False,
        "steps": [],
    }
    (run_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")

    resp = srv.run_get(run_id)
    assert resp["ok"] is True
    assert resp["run"]["run_id"] == run_id
    assert resp["run_dir"] == str(run_dir)


def test_run_list_includes_alias_roots(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    primary_root = tmp_path / "primary"
    alias_root = tmp_path / "alias"
    monkeypatch.setattr(srv, "RUN_ROOT", primary_root)
    monkeypatch.setenv("BR_MCP_RUN_ROOT_ALIASES", str(alias_root))

    run_primary = primary_root / "runs" / "br_20260101_010101_primary"
    run_primary.mkdir(parents=True, exist_ok=True)
    (run_primary / "run.json").write_text(
        json.dumps(
            {
                "run_id": "br_20260101_010101_primary",
                "created_at": "2026-01-01T01:01:01Z",
                "status": "succeeded",
                "dry_run": False,
                "steps": [],
            }
        ),
        encoding="utf-8",
    )

    run_alias = alias_root / "runs" / "br_20251231_235959_alias"
    run_alias.mkdir(parents=True, exist_ok=True)
    (run_alias / "run.json").write_text(
        json.dumps(
            {
                "run_id": "br_20251231_235959_alias",
                "created_at": "2025-12-31T23:59:59Z",
                "status": "failed",
                "dry_run": False,
                "steps": [],
            }
        ),
        encoding="utf-8",
    )

    listed = srv.run_list(limit=10)
    assert listed["ok"] is True
    ids = {item.get("run_id") for item in listed.get("runs", [])}
    assert "br_20260101_010101_primary" in ids
    assert "br_20251231_235959_alias" in ids


def test_run_bundle_get_returns_normalized_bundle(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)

    run_dir = _write_run_fixture(
        tmp_path,
        "br_20260309_000001_bundle",
        files={
            "trace.jsonl": json.dumps({"event_type": "mcp.tool_execute.started"})
            + "\n",
            "trajectory.json": {"schema_version": "ATIF-v1.4", "steps": [{}]},
            "observation.json": {"schema_version": "observation-v1"},
            "analysis_bundle.json": {"schema_version": "analysis-bundle-v1"},
            "artifacts/step-01-s1/out.txt": "ok",
        },
    )

    resp = srv.run_bundle_get("br_20260309_000001_bundle")

    assert resp["ok"] is True
    assert resp["run_dir"] == str(run_dir)
    bundle = resp["bundle"]
    assert bundle["run"]["run_id"] == "br_20260309_000001_bundle"
    assert bundle["component_status"]["trace_jsonl"] == "present"
    assert bundle["trajectory_summary"]["step_count"] == 1
    assert bundle["trace_summary"]["line_count"] == 1
    assert bundle["artifact_contract"]["status"] == "degraded"
    assert bundle["artifact_contract"]["reviewability"] == "degraded_evaluable"
    assert bundle["artifact_contract"]["missing_by_policy"]["degraded"] == [
        "provenance.json"
    ]
    assert any(item["relpath"].endswith("out.txt") for item in bundle["artifact_index"])
    assert any("provenance_json is missing" in warning for warning in resp["warnings"])


def test_run_bundle_get_accepts_multiline_trace_jsonl(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)

    _write_run_fixture(
        tmp_path,
        "br_20260309_000001_jsonl_bundle",
        files={
            "trace.jsonl": "\n".join(
                [
                    json.dumps({"event_type": "mcp.tool_execute.started"}),
                    json.dumps({"event_type": "mcp.tool_execute.completed"}),
                ]
            )
            + "\n",
            "provenance.json": {"schema_version": "provenance-v1"},
            "trajectory.json": {"schema_version": "ATIF-v1.4", "steps": [{}]},
            "observation.json": {"schema_version": "observation-v1"},
            "analysis_bundle.json": {"schema_version": "analysis-bundle-v1"},
        },
    )

    resp = srv.run_bundle_get("br_20260309_000001_jsonl_bundle")

    assert resp["ok"] is True
    bundle = resp["bundle"]
    assert bundle["component_status"]["trace_jsonl"] == "present"
    assert bundle["trace_summary"]["line_count"] == 2
    assert not any(
        "trace_jsonl is unreadable" in warning for warning in resp["warnings"]
    )


def test_run_scorecard_reports_policy_and_artifact_completeness(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)

    steps = [
        {
            "step_id": "s1",
            "tool_id": "extract_timeseries",
            "status": "failed",
            "error": "policy_rejected",
            "policy_issues": [
                {"level": "error", "code": "path_not_allowed", "message": "nope"}
            ],
        }
    ]
    _write_run_fixture(
        tmp_path,
        "br_20260309_000002_scorecard",
        status="failed",
        steps=steps,
        files={
            "observation.json": {"schema_version": "observation-v1"},
            "analysis_bundle.json": {"schema_version": "analysis-bundle-v1"},
        },
    )

    resp = srv.run_scorecard("br_20260309_000002_scorecard")

    assert resp["ok"] is True
    scorecard = resp["scorecard"]
    assert scorecard["completion_state"] == "failed"
    assert scorecard["policy"]["issue_count"] == 1
    assert scorecard["artifacts"]["status"] == "skipped"
    assert scorecard["artifacts"]["missing"]
    assert scorecard["errors"] == ["policy_rejected"]


def test_generate_research_trajectory_and_insights_persists_run_artifacts(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setenv("BR_MCP_SUMMARY_LLM_ENABLED", "false")

    _write_run_fixture(
        tmp_path,
        "br_20260312_trajectory",
        status="failed",
        steps=[
            {
                "step_id": "s1",
                "tool_id": "workflow_visual_decoding",
                "status": "failed",
                "error": "File or directory not found: /tmp/f.npy",
            }
        ],
        files={
            "trace.jsonl": "\n".join(
                [
                    json.dumps(
                        {
                            "timestamp": "2026-03-12T21:49:07Z",
                            "event_type": "mcp.pipeline_execute.queued",
                            "payload": {
                                "raw_event_type": "mcp.pipeline_execute.queued"
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "timestamp": "2026-03-12T21:49:08Z",
                            "event_type": "mcp.run.started",
                            "payload": {"raw_event_type": "mcp.run.started"},
                        }
                    ),
                    json.dumps(
                        {
                            "timestamp": "2026-03-12T21:49:08Z",
                            "event_type": "mcp.step.finished",
                            "payload": {"raw_event_type": "mcp.step.finished"},
                        }
                    ),
                ]
            )
            + "\n",
            "trajectory.json": {
                "schema_version": "ATIF-v1.4",
                "steps": [{}],
                "status": "failed",
            },
            "observation.json": {
                "schema_version": "observation-v1",
                "provenance": {"route": "pipeline_execute"},
            },
            "analysis_bundle.json": {"schema_version": "analysis-bundle-v1"},
            "artifacts/step-01-s1/out.txt": "ok",
            "logs/step-01-s1.json": json.dumps(
                {"status": "failed", "error": "File or directory not found: /tmp/f.npy"}
            ),
        },
    )
    agent_log = tmp_path / "agent.ndjson"
    agent_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {"event_type": "assistant", "content": "Investigating failure"}
                ),
                json.dumps(
                    {
                        "event_type": "assistant",
                        "content": "Patched thread finalization",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    resp = srv.generate_research_trajectory_and_insights(
        run_id="br_20260312_trajectory",
        agent_log_paths=[str(agent_log)],
    )

    assert resp["ok"] is True
    assert resp["anchor_type"] == "run"
    assert resp["anchor_id"] == "br_20260312_trajectory"
    assert resp["summary_mode"] == "template_fallback"
    assert resp["trajectory_summary"]["final_status"] == "failed"
    assert resp["trajectory_summary"]["agent_log_paths"] == [str(agent_log)]
    assert len(resp["persisted_files"]) == 2
    for path in resp["persisted_files"]:
        assert Path(path).exists()

    artifact_paths = {
        item["relpath"] for item in srv.artifact_list("br_20260312_trajectory")["items"]
    }
    assert "artifacts/summaries/research_trajectory_and_insights.json" in artifact_paths
    assert "artifacts/summaries/research_trajectory_and_insights.md" in artifact_paths


def test_generate_bug_digest_supports_candidate_anchor_and_manifest(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import research_summaries as summaries
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setenv("BR_MCP_SUMMARY_LLM_ENABLED", "false")
    state_root = tmp_path / "autoresearch"
    candidate_root = state_root / "candidates" / "cand_bug_001"
    validation_root = state_root / "validations" / "cand_bug_001"
    benchmark_root = (
        state_root / "benchmark_workdirs" / "cand_bug_001" / "candidate" / "motif_slice"
    )
    candidate_root.mkdir(parents=True, exist_ok=True)
    validation_root.mkdir(parents=True, exist_ok=True)
    benchmark_root.mkdir(parents=True, exist_ok=True)

    (candidate_root / "candidate_fix.json").write_text(
        json.dumps(
            {
                "candidate_id": "cand_bug_001",
                "motif_id": "trace_or_bundle_corruption",
                "motif_family": "trace_or_bundle_corruption",
                "target_surface": "trace_bundle_integrity",
                "allowed_paths": ["src/brain_researcher/services/mcp/server.py"],
                "worktree_path": "/tmp/cand_bug_001",
                "patch_rationale": "Keep MCP run finalization intact",
                "validation_slice_id": "trace_or_bundle_corruption",
                "local_check_commands": [],
                "created_at": "2026-03-12T10:00:00Z",
                "status": "absorbed_upstream",
            }
        ),
        encoding="utf-8",
    )
    (validation_root / "validation_report.json").write_text(
        json.dumps(
            {
                "candidate_id": "cand_bug_001",
                "gate_verdict": "absorbed_upstream",
                "status_explanation": "Mainline already includes this repair.",
                "recommended_action": "Archive the candidate.",
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    act_log = benchmark_root / "act.ndjson"
    act_log.write_text(
        json.dumps({"event_type": "assistant", "content": "Validated HARNESS-001"})
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        summaries, "get_autoresearch_root", lambda _root=None: state_root
    )

    resp = srv.generate_bug_digest(candidate_id="cand_bug_001")

    assert resp["ok"] is True
    assert resp["anchor_type"] == "candidate"
    assert resp["anchor_id"] == "cand_bug_001"
    assert resp["summary_mode"] == "template_fallback"
    assert resp["bug_digest"]["fix_status"] == "absorbed_upstream"
    assert "Mainline already includes this repair." in resp["bug_digest"]["symptom"]
    assert any(
        path.endswith("summary_manifest.json") for path in resp["persisted_files"]
    )
    for path in resp["persisted_files"]:
        assert Path(path).exists()

    manifest = json.loads(
        (candidate_root / "summaries" / "summary_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert "bug_digest" in manifest["files"]


def test_generate_repo_repair_context_delegates_and_returns_payload(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(
        srv,
        "build_repo_repair_context",
        lambda **kwargs: {
            "ok": True,
            "repo_repair_context": {
                "generated_at": "2026-03-12T10:00:00Z",
                "summary": {
                    "failure_motif_count": 2,
                    "absorbed_upstream_candidate_count": 1,
                    "harness_task_count": 2,
                    "golden_principle_count": 3,
                },
            },
            "persisted_files": ["/tmp/repo_repair_context_latest.json"],
            "warnings": [],
        },
    )

    resp = srv.generate_repo_repair_context(top_n=5, persist=False)

    assert resp["ok"] is True
    assert resp["repo_repair_context"]["summary"]["failure_motif_count"] == 2
    assert resp["persisted_files"] == ["/tmp/repo_repair_context_latest.json"]


def test_run_compare_prefers_better_candidate(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)

    _write_run_fixture(
        tmp_path,
        "br_20260309_000003_baseline",
        status="failed",
        steps=[
            {
                "step_id": "s1",
                "tool_id": "extract_timeseries",
                "status": "failed",
                "error": "boom",
            }
        ],
        files={
            "observation.json": {"schema_version": "observation-v1"},
        },
    )
    _write_run_fixture(
        tmp_path,
        "br_20260309_000004_candidate",
        status="succeeded",
        steps=[
            {
                "step_id": "s1",
                "tool_id": "extract_timeseries",
                "status": "succeeded",
            }
        ],
        files={
            "trace.jsonl": json.dumps({"event_type": "done"}) + "\n",
            "provenance.json": {"run_id": "br_20260309_000004_candidate"},
            "trajectory.json": {"schema_version": "ATIF-v1.4", "steps": [{}]},
            "observation.json": {"schema_version": "observation-v1"},
            "analysis_bundle.json": {"schema_version": "analysis-bundle-v1"},
        },
    )

    resp = srv.run_compare(
        "br_20260309_000003_baseline",
        "br_20260309_000004_candidate",
        metric_keys=["artifact_completeness_ratio"],
    )

    assert resp["ok"] is True
    assert resp["decision_hint"] == "candidate_better"
    assert resp["comparison"]["criteria"]


def test_run_compare_reports_unsupported_metric_key(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)

    for run_id in ("br_20260309_000005_a", "br_20260309_000006_b"):
        _write_run_fixture(
            tmp_path,
            run_id,
            files={
                "trace.jsonl": json.dumps({"event_type": "done"}) + "\n",
                "provenance.json": {"run_id": run_id},
                "trajectory.json": {"schema_version": "ATIF-v1.4", "steps": []},
                "observation.json": {"schema_version": "observation-v1"},
                "analysis_bundle.json": {"schema_version": "analysis-bundle-v1"},
            },
        )

    resp = srv.run_compare(
        "br_20260309_000005_a",
        "br_20260309_000006_b",
        metric_keys=["not_a_metric"],
    )

    assert resp["ok"] is True
    assert any("unsupported metric key" in warning for warning in resp["warnings"])


def test_google_deep_research_requires_network(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", False)
    start = srv.google_deep_research_start(input="test")
    assert start["ok"] is False
    assert start["error"] == "network_blocked"

    get = srv.google_deep_research_get("interaction-id")
    assert get["ok"] is False
    assert get["error"] == "network_blocked"


def test_policy_check_tool_allows_loopback_when_network_disabled(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import (
        ToolExecutionCapabilities,
        ToolSpec,
    )

    monkeypatch.setattr(srv, "ALLOW_NETWORK", False)
    spec = ToolSpec(
        name="local.loopback.tool",
        description="loopback only",
        backend="python",
        execution_capabilities=ToolExecutionCapabilities(
            needs_network=True,
            allowed_domains=["localhost", "127.0.0.1", "::1"],
        ),
    )

    issues = srv._policy_check_tool(spec)
    assert not any(i.get("code") == "network_blocked" for i in issues)


def test_policy_check_tool_blocks_external_domain_when_network_disabled(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import (
        ToolExecutionCapabilities,
        ToolSpec,
    )

    monkeypatch.setattr(srv, "ALLOW_NETWORK", False)
    spec = ToolSpec(
        name="external.net.tool",
        description="external domain",
        backend="python",
        execution_capabilities=ToolExecutionCapabilities(
            needs_network=True,
            allowed_domains=["api.openai.com"],
        ),
    )

    issues = srv._policy_check_tool(spec)
    assert any(i.get("code") == "network_blocked" for i in issues)


def test_policy_check_tool_allows_local_runtime_marker(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    monkeypatch.setattr(srv, "ALLOW_NETWORK", False)
    spec = ToolSpec(
        name="neo4j.local_runtime.lookup",
        description="local runtime marker",
        backend="python",
        tags=["local_runtime"],
        side_effects=["network"],
    )

    issues = srv._policy_check_tool(spec)
    assert not any(i.get("code") == "network_blocked" for i in issues)

    prepared = srv._prepare_spec_for_network_policy(spec, patch_catalog=False)
    caps = prepared.execution_capabilities
    assert caps is not None
    assert caps.needs_network is True
    assert {"localhost", "127.0.0.1", "::1"}.issubset(set(caps.allowed_domains))


def test_policy_check_tool_allows_local_mcp_bridge_when_network_disabled(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    monkeypatch.setattr(srv, "ALLOW_NETWORK", False)
    spec = ToolSpec(
        name="mcp.tool_search",
        description="local mcp bridge",
        backend="external_api",
    )

    issues = srv._policy_check_tool(spec)
    assert not any(i.get("code") == "network_blocked" for i in issues)

    prepared = srv._prepare_spec_for_network_policy(spec, patch_catalog=False)
    caps = prepared.execution_capabilities
    assert caps is not None
    assert caps.needs_network is True
    assert {"localhost", "127.0.0.1", "::1"}.issubset(set(caps.allowed_domains))


def test_prepare_spec_for_network_policy_patches_catalog_for_pipeline_search(
    monkeypatch,
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools import catalog_loader
    from brain_researcher.services.tools.spec import ToolSpec

    fake_catalog = {
        "pipeline.search": {
            "name": "pipeline.search",
            "runtime_kind": "python",
            "python_module": "brain_researcher.services.tools.pipeline_search_tool",
        }
    }
    monkeypatch.setattr(catalog_loader, "load_tools_catalog", lambda: fake_catalog)

    spec = ToolSpec(
        name="pipeline.search",
        description="pipeline search",
        backend="python",
        side_effects=["network"],
    )
    prepared = srv._prepare_spec_for_network_policy(spec, patch_catalog=True)

    caps = prepared.execution_capabilities
    assert caps is not None
    assert caps.needs_network is True
    assert {"localhost", "127.0.0.1", "::1"}.issubset(set(caps.allowed_domains))
    assert (
        fake_catalog["pipeline.search"]["execution_capabilities"]["needs_network"]
        is True
    )
    assert {"localhost", "127.0.0.1", "::1"}.issubset(
        set(
            fake_catalog["pipeline.search"]["execution_capabilities"]["allowed_domains"]
        )
    )


def test_policy_check_tool_does_not_override_explicit_external_domains(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import (
        ToolExecutionCapabilities,
        ToolSpec,
    )

    monkeypatch.setattr(srv, "ALLOW_NETWORK", False)
    spec = ToolSpec(
        name="pipeline.search",
        description="explicitly external for test",
        backend="python",
        execution_capabilities=ToolExecutionCapabilities(
            needs_network=True,
            allowed_domains=["example.org"],
        ),
    )

    issues = srv._policy_check_tool(spec)
    assert any(i.get("code") == "network_blocked" for i in issues)


def test_google_deep_research_falls_back_to_candidate_parts(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeGoogleSearch:
        def __init__(self, exclude_domains=None):
            self.exclude_domains = exclude_domains

    class FakeTool:
        def __init__(self, google_search):
            self.google_search = google_search

    class FakeGenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeResponse:
        text = None
        candidates = [
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text="Nested summary line 1."),
                        SimpleNamespace(text="Nested summary line 2."),
                    ]
                )
            )
        ]

        @staticmethod
        def model_dump():
            return {
                "text": None,
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Nested summary line 1."},
                                {"text": "Nested summary line 2."},
                            ]
                        },
                        "grounding_metadata": {
                            "grounding_chunks": [
                                {
                                    "web": {
                                        "uri": "https://example.org/source",
                                        "title": "Example source",
                                    }
                                }
                            ]
                        },
                    }
                ],
            }

    class FakeModels:
        @staticmethod
        def generate_content(**kwargs):
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.models = FakeModels()

    fake_genai = SimpleNamespace(
        Client=FakeClient,
        types=SimpleNamespace(
            GoogleSearch=FakeGoogleSearch,
            Tool=FakeTool,
            GenerateContentConfig=FakeGenerateContentConfig,
        ),
    )
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    resp = srv.google_deep_research(query="test nested parts")

    assert resp["ok"] is True
    data = resp["data"]
    assert data["summary"] == "Nested summary line 1.\nNested summary line 2."
    assert data["text"] == data["summary"]
    assert data["sources"] == [
        {"url": "https://example.org/source", "title": "Example source"}
    ]
    assert data["documents"] == [
        {
            "doc_id": "src_1",
            "title": "Example source",
            "url": "https://example.org/source",
        }
    ]
    assert data["diagnostics"]["status_normalized"] == "completed"
    assert data["diagnostics"]["extractable_text"] is True
    assert data["diagnostics"]["source_count"] == 1
    assert data["diagnostics"]["raw_included"] is False
    assert "raw_response" not in data
    assert "response" not in data


def test_google_deep_research_returns_empty_response_error(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeGoogleSearch:
        def __init__(self, exclude_domains=None):
            self.exclude_domains = exclude_domains

    class FakeTool:
        def __init__(self, google_search):
            self.google_search = google_search

    class FakeGenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeResponse:
        text = None
        candidates = [
            SimpleNamespace(
                content=SimpleNamespace(parts=[SimpleNamespace(inline_data={"x": 1})])
            )
        ]

        @staticmethod
        def model_dump():
            return {
                "text": None,
                "candidates": [{"content": {"parts": [{"inline_data": {"x": 1}}]}}],
            }

    class FakeModels:
        @staticmethod
        def generate_content(**kwargs):
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.models = FakeModels()

    fake_genai = SimpleNamespace(
        Client=FakeClient,
        types=SimpleNamespace(
            GoogleSearch=FakeGoogleSearch,
            Tool=FakeTool,
            GenerateContentConfig=FakeGenerateContentConfig,
        ),
    )
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    resp = srv.google_deep_research(query="test empty nested response")

    assert resp["ok"] is False
    assert resp["error"] == "empty_response"
    assert "empty text" in resp["message"]
    data = resp["data"]
    assert data["summary"] == ""
    assert data["text"] == ""
    assert data["sources"] == []
    assert data["documents"] == []
    assert data["diagnostics"]["extractable_text"] is False
    assert data["diagnostics"]["source_count"] == 0
    assert data["diagnostics"]["raw_included"] is False
    assert "raw_response" not in data
    assert "response" not in data


def test_google_deep_research_start_returns_structured_error(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeStartError(RuntimeError):
        def __init__(self, message: str, status_code: int):
            super().__init__(message)
            self.status_code = status_code

    class FakeInteractions:
        @staticmethod
        def create(**kwargs):
            del kwargs
            raise FakeStartError("Rate limit exceeded", 429)

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.interactions = FakeInteractions()

    fake_genai = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    resp = srv.google_deep_research_start(input="test request")
    assert resp["ok"] is False
    assert resp["error_type"] == "FakeStartError"
    assert resp["status_code"] == 429
    assert resp["retryable"] is True
    assert "Rate limit" in resp["error"]


def test_google_deep_research_start_creates_local_run_and_syncs(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()
    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeCreateInteraction:
        id = "int-queued"
        status = "queued"

        @staticmethod
        def model_dump():
            return {"id": "int-queued", "status": "queued"}

    class FakeGetInteraction:
        id = "int-queued"
        status = "completed"

        @staticmethod
        def model_dump():
            return {
                "id": "int-queued",
                "status": "completed",
                "outputs": [{"text": "Final deep research summary."}],
                "references": [{"url": "https://example.org/final"}],
            }

    class FakeInteractions:
        @staticmethod
        def create(**kwargs):
            del kwargs
            return FakeCreateInteraction()

        @staticmethod
        def get(*args, **kwargs):
            del args, kwargs
            return FakeGetInteraction()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.interactions = FakeInteractions()

    fake_genai = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    start = srv.google_deep_research_start(input="test request")
    assert start["ok"] is True
    assert start["status"] == "queued"
    assert start["execution_mode"] == "background"
    assert start["execution_trace"] == [
        "validated",
        "provider_request_accepted",
        "queued_background_run",
    ]
    assert start["poll_tool"] == "run_get"
    assert start["compat_poll_tool"] == "google_deep_research_get"
    assert start["interaction_id"] == "int-queued"
    assert start["data"]["interaction_id"] == "int-queued"
    run_id = start["run_id"]

    polled = srv.run_get(run_id)
    assert polled["ok"] is True
    assert polled["run"]["status"] == "succeeded"
    assert polled["progress"]["current_stage"] == "google_deep_research"
    assert polled["progress"]["stalled"] is False
    assert polled["interaction_id"] == "int-queued"
    assert polled["data"]["interaction_id"] == "int-queued"
    assert polled["data"]["summary"] == "Final deep research summary."

    get_by_run = srv.google_deep_research_get(run_id)
    assert get_by_run["ok"] is True
    assert get_by_run["status"] == "succeeded"
    assert get_by_run["scientific_mode"] is False
    assert get_by_run["data"]["summary"] == "Final deep research summary."
    assert get_by_run["data"]["scientific_mode"] is False
    assert get_by_run["data"]["sources"] == [
        {"url": "https://example.org/final", "title": None}
    ]


def test_google_deep_research_start_scientific_mode_persists_to_run_and_get(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()
    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured: dict[str, object] = {}

    class FakeCreateInteraction:
        id = "int-sci"
        status = "queued"

        @staticmethod
        def model_dump():
            return {"id": "int-sci", "status": "queued"}

    class FakeGetInteraction:
        id = "int-sci"
        status = "completed"

        @staticmethod
        def model_dump():
            return {
                "id": "int-sci",
                "status": "completed",
                "outputs": [{"text": "Scientific deep research summary."}],
                "references": [{"url": "https://pubmed.ncbi.nlm.nih.gov/40147442/"}],
            }

    class FakeInteractions:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return FakeCreateInteraction()

        @staticmethod
        def get(*args, **kwargs):
            del args, kwargs
            return FakeGetInteraction()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.interactions = FakeInteractions()

    fake_genai = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    start = srv.google_deep_research_start(
        input="Summarize findings for PMID 40147442.",
        scientific_mode=True,
    )

    assert start["ok"] is True
    assert start["scientific_mode"] is True
    assert start["data"]["scientific_mode"] is True
    assert "Scientific research mode." in str(captured["input"])
    assert "PubMed" in str(captured["input"])
    assert start["execution_trace"] == [
        "validated",
        "scientific_mode_enabled",
        "provider_request_accepted",
        "queued_background_run",
    ]

    get_by_run = srv.google_deep_research_get(start["run_id"])
    assert get_by_run["ok"] is True
    assert get_by_run["scientific_mode"] is True
    assert get_by_run["data"]["scientific_mode"] is True
    assert get_by_run["data"]["summary"] == "Scientific deep research summary."


def test_google_deep_research_start_auto_detects_scientific_queries(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured: dict[str, object] = {}

    class FakeInteraction:
        id = "int-auto-sci"
        status = "pending"

        @staticmethod
        def model_dump():
            return {"id": "int-auto-sci", "status": "pending"}

    class FakeInteractions:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return FakeInteraction()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.interactions = FakeInteractions()

    fake_genai = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    resp = srv.google_deep_research_start(
        input="Review neuroimaging biomarker papers for autism with PMID 40147442."
    )

    assert resp["ok"] is True
    assert resp["scientific_mode"] is True
    assert "Scientific research mode." in str(captured["input"])


def test_google_deep_research_get_includes_diagnostics(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeInteraction:
        id = "int-cancelled"
        status = "cancelled"

        @staticmethod
        def model_dump():
            return {
                "message": "Interaction cancelled by user.",
                "references": [
                    {"url": "https://example.org/ref1"},
                ],
            }

    class FakeInteractions:
        @staticmethod
        def get(*args, **kwargs):
            del args, kwargs
            return FakeInteraction()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.interactions = FakeInteractions()

    fake_genai = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    resp = srv.google_deep_research_get("int-cancelled")
    assert resp["ok"] is True
    assert resp["data"]["summary"] == "Interaction cancelled by user."
    assert resp["data"]["sources"] == [
        {"url": "https://example.org/ref1", "title": None}
    ]
    diagnostics = resp["data"]["diagnostics"]
    assert diagnostics["status_normalized"] == "cancelled"
    assert diagnostics["terminal"] is True
    assert diagnostics["terminal_error"] is True
    assert diagnostics["extractable_text"] is True
    assert diagnostics["source_count"] == 1
    assert diagnostics["raw_included"] is False
    assert "response" not in resp["data"]
    assert "raw_response" not in resp["data"]


def test_google_deep_research_get_prefers_outputs_text_over_interaction_id(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeInteraction:
        id = "v1_ChdtRk8zYWRxYk05WEUtc0FQOG9qZzZRaxIXbUZPM2FkcWJNOVhFLXNBUDhvamc2UWs"
        status = "completed"

        @staticmethod
        def model_dump():
            return {
                "id": FakeInteraction.id,
                "status": "completed",
                "outputs": [
                    {
                        "text": (
                            "# Methodological Approaches for Controlling "
                            "Response Streaks in Pupillometry"
                        )
                    }
                ],
            }

    class FakeInteractions:
        @staticmethod
        def get(*args, **kwargs):
            del args, kwargs
            return FakeInteraction()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.interactions = FakeInteractions()

    fake_genai = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    resp = srv.google_deep_research_get(FakeInteraction.id)
    assert resp["ok"] is True
    assert resp["data"]["interaction_id"] == FakeInteraction.id
    assert resp["data"]["summary"].startswith(
        "# Methodological Approaches for Controlling Response Streaks"
    )
    assert resp["data"]["text"] == resp["data"]["summary"]
    assert resp["data"]["diagnostics"]["extractable_text"] is True


def test_google_deep_research_get_extracts_output_annotation_sources(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeInteraction:
        id = "int-with-annotations"
        status = "completed"

        @staticmethod
        def model_dump():
            return {
                "id": FakeInteraction.id,
                "status": "completed",
                "outputs": [
                    {
                        "type": "output_text",
                        "text": "Report body with grounded citations.",
                        "annotations": [
                            {
                                "start_index": 17,
                                "end_index": 26,
                                "source": "https://example.org/citation-1",
                            }
                        ],
                    }
                ],
            }

    class FakeInteractions:
        @staticmethod
        def get(*args, **kwargs):
            del args, kwargs
            return FakeInteraction()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.interactions = FakeInteractions()

    fake_genai = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    resp = srv.google_deep_research_get(FakeInteraction.id)
    assert resp["ok"] is True
    assert resp["data"]["summary"] == "Report body with grounded citations."
    assert resp["data"]["sources"] == [
        {"url": "https://example.org/citation-1", "title": None}
    ]
    assert resp["data"]["documents"] == [
        {
            "doc_id": "src_1",
            "title": None,
            "url": "https://example.org/citation-1",
        }
    ]
    assert resp["data"]["diagnostics"]["source_count"] == 1


def test_deep_research_payload_helpers_accept_data_shape():
    from brain_researcher.services.mcp import server as srv

    payload = {
        "ok": True,
        "data": {
            "interaction_id": "int-123",
            "status": "completed",
            "summary": "Grounded deep research summary",
            "text": "Grounded deep research summary",
            "sources": [{"url": "https://example.org/paper", "title": "Paper"}],
            "raw_response": {"outputs": [{"text": "Grounded deep research summary"}]},
        },
    }

    normalized = srv._deep_research_result_payload(payload)
    assert normalized is not None
    assert normalized["summary"] == "Grounded deep research summary"
    assert normalized["synthesis_full_text"] == "Grounded deep research summary"
    assert normalized["raw"] == {
        "outputs": [{"text": "Grounded deep research summary"}]
    }
    assert normalized["metadata"] == {"interaction_id": "int-123"}
    assert normalized["documents"] == [
        {
            "doc_id": "doc_1",
            "title": "Paper",
            "url": "https://example.org/paper",
            "raw_url": "https://example.org/paper",
            "publisher": None,
            "published_at": None,
            "snippets": [],
        }
    ]
    compact = srv._compact_deep_research_payload(payload)
    assert compact["report"]["summary"] == "Grounded deep research summary"
    assert compact["report"]["documents"] == normalized["documents"]
    assert compact["report"]["metadata"] == {"interaction_id": "int-123"}


def test_google_deep_research_include_raw_sanitizes_provider_payload(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeGoogleSearch:
        def __init__(self, exclude_domains=None):
            self.exclude_domains = exclude_domains

    class FakeTool:
        def __init__(self, google_search):
            self.google_search = google_search

    class FakeGenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeResponse:
        text = "Binary-safe summary."

        @staticmethod
        def model_dump():
            return {
                "text": "Binary-safe summary.",
                "blob": b"\xffbad",
            }

    class FakeModels:
        @staticmethod
        def generate_content(**kwargs):
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.models = FakeModels()

    fake_genai = SimpleNamespace(
        Client=FakeClient,
        types=SimpleNamespace(
            GoogleSearch=FakeGoogleSearch,
            Tool=FakeTool,
            GenerateContentConfig=FakeGenerateContentConfig,
        ),
    )
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    resp = srv.google_deep_research(query="binary payload", include_raw=True)

    assert resp["ok"] is True
    data = resp["data"]
    assert data["diagnostics"]["raw_included"] is True
    assert data["raw_response"]["blob"] == "\ufffdbad"
    assert data["response"] == data["raw_response"]


def test_google_deep_research_scientific_mode_prefers_primary_sources(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured: dict[str, object] = {}

    class FakeGoogleSearch:
        def __init__(self, exclude_domains=None):
            captured["exclude_domains"] = exclude_domains

    class FakeTool:
        def __init__(self, google_search):
            self.google_search = google_search

    class FakeGenerateContentConfig:
        def __init__(self, **kwargs):
            captured["config"] = kwargs

    class FakeResponse:
        text = "Primary-source summary."

        @staticmethod
        def model_dump():
            return {"text": "Primary-source summary."}

    class FakeModels:
        @staticmethod
        def generate_content(**kwargs):
            captured["generate_content"] = kwargs
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.models = FakeModels()

    fake_genai = SimpleNamespace(
        Client=FakeClient,
        types=SimpleNamespace(
            GoogleSearch=FakeGoogleSearch,
            Tool=FakeTool,
            GenerateContentConfig=FakeGenerateContentConfig,
        ),
    )
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    resp = srv.google_deep_research(
        query="autism neuroimaging paper DOI 10.1016/j.cell.2025.02.025",
        scientific_mode=True,
        exclude_domains=["example.com"],
    )

    assert resp["ok"] is True
    config = captured["config"]
    assert isinstance(config, dict)
    assert "PubMed" in str(config["system_instruction"])
    assert "secondary coverage only" in str(config["system_instruction"])
    domains = captured["exclude_domains"]
    assert isinstance(domains, list)
    assert "example.com" in domains
    assert "researchgate.net" in domains
    assert "sciencedaily.com" in domains
    request = captured["generate_content"]
    assert isinstance(request, dict)
    assert "no primary paper/page was found" in str(request["contents"])


def test_google_deep_research_auto_detects_scientific_queries(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured: dict[str, object] = {}

    class FakeGoogleSearch:
        def __init__(self, exclude_domains=None):
            captured["exclude_domains"] = exclude_domains

    class FakeTool:
        def __init__(self, google_search):
            self.google_search = google_search

    class FakeGenerateContentConfig:
        def __init__(self, **kwargs):
            captured["config"] = kwargs

    class FakeResponse:
        text = "Auto scientific summary."

        @staticmethod
        def model_dump():
            return {"text": "Auto scientific summary."}

    class FakeModels:
        @staticmethod
        def generate_content(**kwargs):
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.models = FakeModels()

    fake_genai = SimpleNamespace(
        Client=FakeClient,
        types=SimpleNamespace(
            GoogleSearch=FakeGoogleSearch,
            Tool=FakeTool,
            GenerateContentConfig=FakeGenerateContentConfig,
        ),
    )
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    resp = srv.google_deep_research(
        query=(
            "Neuroimaging biomarkers for autism spectrum disorder diagnosis: "
            "include recent studies and PMID 40147442."
        )
    )

    assert resp["ok"] is True
    config = captured["config"]
    assert isinstance(config, dict)
    assert "scientific research assistant" in str(config["system_instruction"])
    domains = captured["exclude_domains"]
    assert isinstance(domains, list)
    assert "researchgate.net" in domains


def test_deepxiv_resolve_pmc_identifier_from_pii(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "_deepxiv_pubmed_esearch_pmid", lambda term: "40147442")
    monkeypatch.setattr(
        srv,
        "_deepxiv_pmc_idconv",
        lambda identifier: {
            "pmcid": "PMC1234567",
            "pmid": "40147442",
            "doi": "10.1016/j.cell.2025.02.025",
        },
    )

    resolved = srv._deepxiv_resolve_pmc_identifier("S0092-8674(25)00213-2")

    assert resolved["ok"] is True
    assert resolved["paper_id"] == "PMC1234567"
    resolution = resolved["resolution"]
    assert resolution["identifier_type"] == "pii"
    assert resolution["pii"] == "S0092-8674(25)00213-2"
    assert resolution["pmid"] == "40147442"
    assert resolution["doi"] == "10.1016/j.cell.2025.02.025"
    assert resolution["in_pmc"] is True


def test_deepxiv_pmc_head_uses_resolved_pmcid(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    called: dict[str, str] = {}

    class FakeReader:
        def pmc_head(self, paper_id):
            called["paper_id"] = paper_id
            return {"paper_id": paper_id}

    monkeypatch.setattr(srv, "_get_deepxiv_reader", lambda: FakeReader())
    monkeypatch.setattr(
        srv,
        "_deepxiv_resolve_pmc_identifier",
        lambda paper_id: {
            "ok": True,
            "paper_id": "PMC7654321",
            "resolution": {"requested_id": paper_id, "identifier_type": "doi"},
        },
    )

    resp = srv.deepxiv(action="pmc_head", paper_id="10.1234/example")

    assert resp["ok"] is True
    assert called["paper_id"] == "PMC7654321"
    assert resp["paper_id"] == "PMC7654321"


def test_deepxiv_pmc_full_returns_structured_unavailable_error(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)

    class FakeReader:
        def pmc_json(self, paper_id):
            raise AssertionError(f"pmc_json should not be called: {paper_id}")

    monkeypatch.setattr(srv, "_get_deepxiv_reader", lambda: FakeReader())
    monkeypatch.setattr(
        srv,
        "_deepxiv_resolve_pmc_identifier",
        lambda paper_id: {
            "ok": False,
            "error": "deepxiv_pmc_unavailable",
            "data": {
                "requested_id": paper_id,
                "identifier_type": "pii",
                "pii": paper_id,
                "pmid": "40147442",
                "doi": "10.1016/j.cell.2025.02.025",
                "in_pmc": False,
            },
        },
    )

    resp = srv.deepxiv(action="pmc_full", paper_id="S0092-8674(25)00213-2")

    assert resp["ok"] is False
    assert resp["error"] == "deepxiv_pmc_unavailable"
    assert "requires a PMCID" in resp["message"]
    assert "40147442" in resp["message"]
    assert "PubMed Central" in resp["message"]
    assert resp["data"]["identifier_type"] == "pii"


def test_kg_multihop_qa_mcp_success_summary_first(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools import kg_multihop_qa_tool as qa_tool_module

    captured: dict[str, object] = {}

    class FakeKGMultihopQATool:
        def run(self, **kwargs):
            captured["kwargs"] = kwargs
            return {
                "status": "success",
                "data": {
                    "answer": "mocked answer",
                    "summary": {"n_paths": 4, "max_hops": 3},
                    "seed_entities": [{"kg_id": "S1"}, {"kg_id": "S2"}],
                    "paths": [
                        {"id": "p1"},
                        {"id": "p2"},
                        {"id": "p3"},
                        {"id": "p4"},
                    ],
                    "warnings": ["w1"],
                    "subgraph": {"nodes": [{"kg_id": "S1"}], "edges": []},
                    "outputs": {
                        "answer": "legacy answer",
                        "summary": {"n_paths": 1, "max_hops": 1},
                        "seed_entities": [{"kg_id": "LEGACY"}],
                        "paths": [{"id": "legacy-path"}],
                        "warnings": ["legacy warning"],
                        "subgraph": {"nodes": [{"kg_id": "LEGACY"}], "edges": []},
                    },
                },
            }

    monkeypatch.setattr(qa_tool_module, "KGMultihopQATool", FakeKGMultihopQATool)

    resp = srv.kg_multihop_qa(
        question="What links S1 and S2?",
        max_hops=3,
        mode="breadth_first",
        max_results=50,
        allowed_edge_types=["RELATED_TO"],
    )

    assert resp["ok"] is True
    assert captured["kwargs"] == {
        "question": "What links S1 and S2?",
        "max_hops": 3,
        "mode": "breadth_first",
        "max_results": 50,
        "allowed_edge_types": ["RELATED_TO"],
        "return_subgraph": False,
        "semantic": False,
    }
    result = resp["result"]
    assert result["answer"] == "mocked answer"
    assert result["summary"]["n_paths"] == 4
    assert result["summary"]["max_hops"] == 3
    assert result["summary"]["completion_state"] == "complete"
    assert result["summary"]["degraded"] is False
    assert result["seed_entities"] == [{"kg_id": "S1"}, {"kg_id": "S2"}]
    assert result["top_paths"] == [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]
    assert result["warnings"] == ["w1"]
    assert "subgraph" not in result

    resp_with_subgraph = srv.kg_multihop_qa(
        question="What links S1 and S2?",
        return_subgraph=True,
    )
    assert resp_with_subgraph["ok"] is True
    assert resp_with_subgraph["result"]["subgraph"] == {
        "nodes": [{"kg_id": "S1"}],
        "edges": [],
    }


def test_kg_multihop_qa_mcp_legacy_outputs_fallback_adds_warning(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools import kg_multihop_qa_tool as qa_tool_module

    class FakeKGMultihopQATool:
        def run(self, **kwargs):
            return {
                "status": "success",
                "data": {
                    "outputs": {
                        "answer": "legacy answer",
                        "summary": {"n_paths": 2, "max_hops": 3},
                        "seed_entities": [{"kg_id": "S1"}, {"kg_id": "S2"}],
                        "paths": [{"id": "p1"}, {"id": "p2"}],
                        "warnings": ["legacy warning"],
                        "subgraph": {"nodes": [{"kg_id": "S1"}], "edges": []},
                    }
                },
            }

    monkeypatch.setattr(qa_tool_module, "KGMultihopQATool", FakeKGMultihopQATool)

    resp = srv.kg_multihop_qa(question="What links S1 and S2?", return_subgraph=True)
    assert resp["ok"] is True
    result = resp["result"]
    assert result["answer"] == "legacy answer"
    assert result["summary"]["n_paths"] == 2
    assert result["summary"]["max_hops"] == 3
    assert result["summary"]["completion_state"] == "complete"
    assert result["summary"]["degraded"] is False
    assert result["seed_entities"] == [{"kg_id": "S1"}, {"kg_id": "S2"}]
    assert result["top_paths"] == [{"id": "p1"}, {"id": "p2"}]
    assert result["subgraph"] == {"nodes": [{"kg_id": "S1"}], "edges": []}
    assert "legacy warning" in result["warnings"]
    assert srv.KG_MULTIHOP_LEGACY_OUTPUTS_WARNING in result["warnings"]


def test_kg_multihop_qa_mcp_error_path(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools import kg_multihop_qa_tool as qa_tool_module

    class FakeKGMultihopQATool:
        def run(self, **kwargs):
            return {"status": "error", "error": "No seed entities found"}

    monkeypatch.setattr(qa_tool_module, "KGMultihopQATool", FakeKGMultihopQATool)

    resp = srv.kg_multihop_qa(question="unknown question")
    assert resp == {"ok": False, "error": "No seed entities found"}


def test_kg_multihop_qa_mcp_timeout_fails_fast_by_default(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools import kg_multihop_qa_tool as qa_tool_module

    monkeypatch.setenv("BR_MCP_KG_MULTIHOP_TIMEOUT_S", "1")

    class SlowKGMultihopQATool:
        def run(self, **kwargs):
            del kwargs
            time.sleep(1.4)
            return {"status": "success", "data": {"answer": "late answer"}}

    monkeypatch.setattr(qa_tool_module, "KGMultihopQATool", SlowKGMultihopQATool)

    resp = srv.kg_multihop_qa(question="What links S1 and S2?", return_subgraph=True)

    assert resp["ok"] is False
    assert resp["error"] == "kg_query_timeout"
    assert resp["degraded_reason"] == "mcp_timeout"
    assert "kg_degraded_blocked" in resp["execution_trace"]


def test_kg_multihop_qa_mcp_timeout_returns_degraded_when_allowed(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools import kg_multihop_qa_tool as qa_tool_module

    monkeypatch.setenv("BR_MCP_KG_MULTIHOP_TIMEOUT_S", "1")

    class SlowKGMultihopQATool:
        def run(self, **kwargs):
            del kwargs
            time.sleep(1.4)
            return {"status": "success", "data": {"answer": "late answer"}}

    monkeypatch.setattr(qa_tool_module, "KGMultihopQATool", SlowKGMultihopQATool)

    resp = srv.kg_multihop_qa(
        question="What links S1 and S2?",
        return_subgraph=True,
        allow_degraded=True,
    )

    assert resp["ok"] is True
    assert resp["completion_state"] == "degraded"
    assert resp["degraded_reason"] == "mcp_timeout"
    assert "degraded_returned" in resp["execution_trace"]
    result = resp["result"]
    assert result["summary"]["degraded"] is True
    assert result["summary"]["degraded_reason"] == "mcp_timeout"
    assert result["summary"]["completion_state"] == "degraded"
    assert result["summary"]["degraded_stage"] == "mcp_timeout"
    assert result["seed_entities"] == []
    assert result["top_paths"] == []
    assert "timed out" in result["answer"].lower()
    assert any("timed out" in str(w).lower() for w in result["warnings"])
    assert result["subgraph"] == {"nodes": [], "edges": []}


def test_kg_multihop_qa_mcp_normalizes_degraded_summary_from_tool(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools import kg_multihop_qa_tool as qa_tool_module

    class FakeKGMultihopQATool:
        def run(self, **kwargs):
            del kwargs
            return {
                "status": "success",
                "data": {
                    "answer": "degraded answer",
                    "summary": {
                        "n_paths": 0,
                        "max_hops": 2,
                        "degraded": True,
                        "degraded_reason": "runtime_budget_exhausted:seed_search",
                    },
                    "seed_entities": [],
                    "paths": [],
                    "warnings": ["w1"],
                },
            }

    monkeypatch.setattr(qa_tool_module, "KGMultihopQATool", FakeKGMultihopQATool)

    resp = srv.kg_multihop_qa(question="What links S1 and S2?")
    assert resp["ok"] is False
    assert resp["error"] == "kg_query_degraded"
    assert resp["degraded_reason"] == "runtime_budget_exhausted:seed_search"
    assert "kg_degraded_blocked" in resp["execution_trace"]


def test_kg_multihop_qa_mcp_allows_degraded_summary_when_requested(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools import kg_multihop_qa_tool as qa_tool_module

    class FakeKGMultihopQATool:
        def run(self, **kwargs):
            del kwargs
            return {
                "status": "success",
                "data": {
                    "answer": "degraded answer",
                    "summary": {
                        "n_paths": 0,
                        "max_hops": 2,
                        "degraded": True,
                        "degraded_reason": "runtime_budget_exhausted:seed_search",
                    },
                    "seed_entities": [],
                    "paths": [],
                    "warnings": ["w1"],
                },
            }

    monkeypatch.setattr(qa_tool_module, "KGMultihopQATool", FakeKGMultihopQATool)

    resp = srv.kg_multihop_qa(
        question="What links S1 and S2?",
        allow_degraded=True,
    )
    assert resp["ok"] is True
    assert resp["completion_state"] == "degraded"
    assert resp["degraded_reason"] == "runtime_budget_exhausted:seed_search"
    assert "degraded_returned" in resp["execution_trace"]
    summary = resp["result"]["summary"]
    assert summary["degraded"] is True
    assert summary["degraded_reason"] == "runtime_budget_exhausted:seed_search"
    assert summary["completion_state"] == "degraded"
    assert summary["degraded_stage"] == "seed_search"


def test_kg_verify_hypothesis_mcp_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_verify_hypothesis(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "hypothesis": kwargs["hypothesis"],
            "verdict": "insufficient_evidence",
            "confidence": 0.41,
            "evidence_mode": "union",
            "evidence_source_scope": "expanded_family",
            "summary": {
                "n_supporting": 2,
                "n_conflicting": 0,
                "n_neutral": 1,
                "evidence_scope": "union",
                "evidence_source_scope": "expanded_family",
            },
            "supporting_evidence": [{"evidence_id": "e1", "score": 0.82}],
            "conflicting_evidence": [],
            "neutral_evidence": [{"evidence_id": "n1", "score": 0.4}],
            "top_paths": [{"preview": "DLPFC -> Working memory"}],
            "subgraph": {"nodes": [{"kg_id": "region:dlpfc"}], "edges": []},
            "warnings": [],
            "provenance": [],
            "normalized_claim": {
                "subject": {"kg_id": "region:dlpfc"},
                "object": {"kg_id": "task:nback"},
                "predicate": "involved_in",
                "raw": kwargs["hypothesis"],
            },
            "strictness": kwargs.get("strictness"),
        }

    monkeypatch.setattr(_query_service, "verify_hypothesis", fake_verify_hypothesis)

    resp = srv.kg_verify_hypothesis(
        hypothesis="DLPFC is involved in n-back",
        entity_hints=["DLPFC", "n-back"],
        strictness="high_recall",
        candidate_lane_mode="strict",
        include_subgraph=True,
        include_path_details=False,
    )
    assert resp["ok"] is True
    assert resp["result"]["verdict"] == "insufficient_evidence"
    assert resp["result"]["evidence_mode"] == "union"
    assert resp["result"]["evidence_source_scope"] == "expanded_family"
    assert resp["result"]["summary"]["evidence_scope"] == "union"
    assert resp["result"]["summary"]["evidence_source_scope"] == "expanded_family"
    assert captured["kwargs"]["hypothesis"] == "DLPFC is involved in n-back"
    assert captured["kwargs"]["entity_hints"] == ["DLPFC", "n-back"]
    assert captured["kwargs"]["strictness"] == "high_recall"
    assert captured["kwargs"]["candidate_lane_mode"] == "strict"
    assert captured["kwargs"]["include_subgraph"] is True
    assert captured["kwargs"]["include_path_details"] is False


def test_kg_verify_hypothesis_honors_explicit_semantic_override(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service
    from brain_researcher.services.shared.runtime_semantic import (
        semantic_matching_enabled,
    )

    captured: dict[str, object] = {}

    def fake_verify_hypothesis(**kwargs):
        captured["semantic_enabled"] = semantic_matching_enabled(default=False)
        return {
            "hypothesis": kwargs["hypothesis"],
            "verdict": "insufficient_evidence",
            "summary": {"n_supporting": 0, "n_conflicting": 0, "n_neutral": 0},
            "supporting_evidence": [],
            "conflicting_evidence": [],
            "neutral_evidence": [],
            "warnings": [],
            "provenance": [],
        }

    monkeypatch.setattr(_query_service, "verify_hypothesis", fake_verify_hypothesis)

    resp = srv.kg_verify_hypothesis(
        hypothesis="DLPFC is involved in n-back",
        semantic=True,
    )

    assert resp["ok"] is True
    assert captured["semantic_enabled"] is True


def test_kg_verify_hypothesis_mcp_requires_hypothesis():
    from brain_researcher.services.mcp import server as srv

    resp = srv.kg_verify_hypothesis(hypothesis="   ")
    assert resp == {"ok": False, "error": "hypothesis is required"}


def test_kg_verify_hypothesis_mcp_error_path(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    def fail_verify_hypothesis(**kwargs):
        raise RuntimeError("kg backend unavailable")

    monkeypatch.setattr(_query_service, "verify_hypothesis", fail_verify_hypothesis)

    resp = srv.kg_verify_hypothesis(hypothesis="test")
    assert resp == {"ok": False, "error": "kg backend unavailable"}


def test_verify_hypothesis_with_kg_alias(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    captured: dict[str, object] = {}

    def fake_kg_verify_hypothesis(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "ok": True,
            "result": {
                "verdict": "insufficient_evidence",
                "hypothesis": kwargs["hypothesis"],
                "evidence_mode": "union",
                "evidence_source_scope": "expanded_family",
                "summary": {
                    "evidence_scope": "union",
                    "evidence_source_scope": "expanded_family",
                },
            },
        }

    monkeypatch.setattr(srv, "kg_verify_hypothesis", fake_kg_verify_hypothesis)

    resp = srv.verify_hypothesis_with_kg(
        hypothesis="DLPFC is involved in n-back",
        entity_hints=["DLPFC", "n-back"],
        strictness="high_recall",
        candidate_lane_mode="broad",
    )
    assert resp["ok"] is True
    assert resp["result"]["verdict"] == "insufficient_evidence"
    assert resp["result"]["evidence_mode"] == "union"
    assert resp["result"]["evidence_source_scope"] == "expanded_family"
    assert resp["result"]["summary"]["evidence_scope"] == "union"
    assert resp["result"]["summary"]["evidence_source_scope"] == "expanded_family"
    assert captured["kwargs"]["hypothesis"] == "DLPFC is involved in n-back"
    assert captured["kwargs"]["entity_hints"] == ["DLPFC", "n-back"]
    assert captured["kwargs"]["strictness"] == "high_recall"
    assert captured["kwargs"]["candidate_lane_mode"] == "broad"


def test_kg_get_node_resolves_identifier_variants(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service
    from brain_researcher.services.neurokg.query_service import KGNodeSummary

    def fake_node_details(kg_id):
        if kg_id == "pmid:19778619":
            return KGNodeSummary(
                kg_id="pmid:19778619",
                element_id="4:abcd-ef01:99",
                label="example publication",
                node_type="Publication",
                score=1.0,
                properties={"id": "pmid:19778619"},
            )
        return None

    monkeypatch.setattr(_query_service, "node_details", fake_node_details)

    resp = srv.kg_get_node("19778619")
    assert resp["ok"] is True
    assert resp["node"]["kg_id"] == "pmid:19778619"
    assert resp["node"]["node_type"] == "Publication"


@pytest.mark.parametrize(
    ("tool_name", "call_kwargs", "patch_name"),
    [
        ("kg_search_nodes", {"query": "motor"}, "search_nodes"),
        ("kg_get_node", {"kg_id": "node:1"}, "node_details"),
        ("kg_neighbors", {"kg_id": "node:1"}, "neighbors"),
        ("kg_search_datasets", {"text": "motor"}, "search_datasets"),
        ("kg_related_datasets", {"kg_id": "node:1"}, "related_datasets"),
        (
            "kg_behavior_to_fmri_retrieval",
            {"seed_id": "psych101:task:go-no-go"},
            "behavior_to_fmri_retrieval",
        ),
    ],
)
def test_direct_kg_tools_timeout_fail_fast_by_default(
    monkeypatch,
    tool_name,
    call_kwargs,
    patch_name,
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    monkeypatch.setenv("BR_MCP_KG_READ_TIMEOUT_S", "1")

    def raise_timeout(*_args, **_kwargs):
        raise TimeoutError("neo4j timed out")

    monkeypatch.setattr(_query_service, patch_name, raise_timeout)

    resp = getattr(srv, tool_name)(**call_kwargs)

    assert resp["ok"] is False
    assert resp["error"] == "kg_query_timeout"
    assert resp["degraded_reason"] == "mcp_timeout"
    assert resp["query_time_s"] >= 0
    assert "kg_degraded_blocked" in resp["execution_trace"]


@pytest.mark.parametrize(
    ("tool_name", "call_kwargs", "patch_name", "payload_key", "payload_value"),
    [
        (
            "kg_search_nodes",
            {"query": "motor", "allow_degraded": True},
            "search_nodes",
            "items",
            [],
        ),
        (
            "kg_get_node",
            {"kg_id": "node:1", "allow_degraded": True},
            "node_details",
            "node",
            None,
        ),
        (
            "kg_neighbors",
            {"kg_id": "node:1", "allow_degraded": True},
            "neighbors",
            "items",
            [],
        ),
        (
            "kg_search_datasets",
            {"text": "motor", "allow_degraded": True},
            "search_datasets",
            "items",
            [],
        ),
        (
            "kg_related_datasets",
            {"kg_id": "node:1", "allow_degraded": True},
            "related_datasets",
            "items",
            [],
        ),
        (
            "kg_behavior_to_fmri_retrieval",
            {"seed_id": "psych101:task:go-no-go", "allow_degraded": True},
            "behavior_to_fmri_retrieval",
            "items",
            [],
        ),
    ],
)
def test_direct_kg_tools_timeout_return_degraded_when_allowed(
    monkeypatch,
    tool_name,
    call_kwargs,
    patch_name,
    payload_key,
    payload_value,
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    monkeypatch.setenv("BR_MCP_KG_READ_TIMEOUT_S", "1")

    def raise_timeout(*_args, **_kwargs):
        raise TimeoutError("neo4j timed out")

    monkeypatch.setattr(_query_service, patch_name, raise_timeout)

    resp = getattr(srv, tool_name)(**call_kwargs)

    assert resp["ok"] is True
    assert resp[payload_key] == payload_value
    assert resp["completion_state"] == "degraded"
    assert resp["degraded_reason"] == "mcp_timeout"
    assert resp["query_time_s"] >= 0
    assert "degraded_returned" in resp["execution_trace"]
    assert any("timed out" in str(w).lower() for w in resp["warnings"])


def test_kg_behavior_to_fmri_retrieval_returns_payload(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    monkeypatch.setattr(
        _query_service,
        "behavior_to_fmri_retrieval",
        lambda **_kwargs: {
            "seed": {"id": "psych101:task:go-no-go"},
            "seed_tasks": [{"task_id": "psych101:task:go-no-go"}],
            "items": [{"item_id": "ta:go-no-go"}],
            "summary": {"item_count": 1},
        },
    )

    resp = srv.kg_behavior_to_fmri_retrieval(seed_id="psych101:task:go-no-go")

    assert resp["ok"] is True
    assert resp["seed"]["id"] == "psych101:task:go-no-go"
    assert resp["summary"]["item_count"] == 1


def test_kg_list_dataset_onvoc_links_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service
    from brain_researcher.services.neurokg.query_service import DatasetOnvocLinkSummary

    captured: dict[str, object] = {}

    def fake_list_dataset_onvoc_links(**kwargs):
        captured.update(kwargs)
        return {
            "items": [
                DatasetOnvocLinkSummary(
                    dataset_id="ds000001",
                    title="Motor fMRI",
                    kg_id="ds:1",
                    primary_onvoc_id="ONVOC_0001",
                    primary_onvoc_confidence=0.98,
                    onvoc_links=[
                        {
                            "id": "ONVOC_0001",
                            "label": "Working Memory",
                            "confidence": 0.98,
                        }
                    ],
                )
            ],
            "page": 2,
            "page_size": 500,
            "total": 1,
            "has_more": False,
        }

    monkeypatch.setattr(
        _query_service,
        "list_dataset_onvoc_links",
        fake_list_dataset_onvoc_links,
    )

    resp = srv.kg_list_dataset_onvoc_links(onvoc_id="ONVOC_0001", page=2, page_size=999)

    assert resp["ok"] is True
    assert resp["page"] == 2
    assert resp["page_size"] == 500
    assert resp["total"] == 1
    assert resp["has_more"] is False
    assert resp["items"][0]["dataset_id"] == "ds000001"
    assert captured["onvoc_id"] == "ONVOC_0001"
    assert captured["page"] == 2
    assert captured["page_size"] == 500
    assert captured["timeout_s"] == 15.0


def test_kg_list_dataset_onvoc_links_timeout_fails_fast_by_default(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    monkeypatch.setenv("BR_MCP_KG_READ_TIMEOUT_S", "1")

    def raise_timeout(**_kwargs):
        raise TimeoutError("neo4j timed out")

    monkeypatch.setattr(
        _query_service,
        "list_dataset_onvoc_links",
        raise_timeout,
    )

    resp = srv.kg_list_dataset_onvoc_links(onvoc_id="ONVOC_0001", page=3, page_size=777)

    assert resp["ok"] is False
    assert resp["error"] == "kg_query_timeout"
    assert resp["degraded_reason"] == "mcp_timeout"
    assert "kg_degraded_blocked" in resp["execution_trace"]


def test_kg_list_dataset_onvoc_links_timeout_returns_degraded_when_allowed(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    monkeypatch.setenv("BR_MCP_KG_READ_TIMEOUT_S", "1")

    def raise_timeout(**_kwargs):
        raise TimeoutError("neo4j timed out")

    monkeypatch.setattr(
        _query_service,
        "list_dataset_onvoc_links",
        raise_timeout,
    )

    resp = srv.kg_list_dataset_onvoc_links(
        onvoc_id="ONVOC_0001",
        page=3,
        page_size=777,
        allow_degraded=True,
    )

    assert resp["ok"] is True
    assert resp["items"] == []
    assert resp["page"] == 3
    assert resp["page_size"] == 500
    assert resp["total"] == 0
    assert resp["has_more"] is False
    assert resp["completion_state"] == "degraded"
    assert resp["degraded_reason"] == "mcp_timeout"
    assert "degraded_returned" in resp["execution_trace"]


def test_kg_probe_structural_leverage_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_find_structural_leverage(
        seed_kg_ids,
        *,
        relation_types=None,
        direction="both",
        limit=25,
        taste=None,
    ):
        captured["kwargs"] = {
            "seed_kg_ids": list(seed_kg_ids),
            "relation_types": relation_types,
            "direction": direction,
            "limit": limit,
            "taste": taste,
        }
        return {"ranked_nodes": [{"kg_id": "node:1", "score": 0.91}]}

    monkeypatch.setattr(
        _query_service,
        "find_structural_leverage",
        fake_find_structural_leverage,
        raising=False,
    )

    resp = srv.kg_probe(
        probe_type="structural_leverage",
        seed_kg_ids=["node:a", "node:b"],
        max_hops=3,
        max_results=5,
        allowed_edge_types=["SUPPORTS"],
    )

    assert resp["ok"] is True
    assert resp["result"]["ranked_nodes"][0]["kg_id"] == "node:1"
    assert captured["kwargs"] == {
        "seed_kg_ids": ["node:a", "node:b"],
        "relation_types": ["SUPPORTS"],
        "direction": "both",
        "limit": 5,
        "taste": None,
    }
    assert "max_hops is currently informational" in " ".join(
        resp["result"].get("warnings", [])
    )


def test_kg_probe_contradiction_frontiers_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_find_contradiction_frontiers(
        *,
        query=None,
        seed_kg_ids=None,
        relation_types=None,
        limit=10,
        max_evidence=80,
        db=None,
    ):
        del db
        captured["kwargs"] = {
            "query": query,
            "seed_kg_ids": seed_kg_ids,
            "relation_types": relation_types,
            "limit": limit,
            "max_evidence": max_evidence,
        }
        return {"frontiers": [{"frontier_label": "weights are required"}]}

    monkeypatch.setattr(
        _query_service,
        "find_contradiction_frontiers",
        fake_find_contradiction_frontiers,
        raising=False,
    )

    resp = srv.kg_probe(
        probe_type="contradiction_frontiers",
        query="structural prior",
        entity_hints=["concept:structural_prior"],
        allowed_edge_types=["ASSOCIATED_WITH"],
        max_results=7,
    )

    assert resp["ok"] is True
    assert resp["result"]["frontiers"][0]["frontier_label"] == "weights are required"
    assert captured["kwargs"] == {
        "query": "structural prior",
        "seed_kg_ids": ["concept:structural_prior"],
        "relation_types": ["ASSOCIATED_WITH"],
        "limit": 7,
        "max_evidence": 7,
    }


def test_kg_probe_rejects_unsupported_probe_type():
    from brain_researcher.services.mcp import server as srv

    resp = srv.kg_probe(probe_type="mystery_probe")

    assert resp["ok"] is False
    assert "unsupported probe_type" in resp["error"]


def test_kg_probe_requires_query_or_entity_hints():
    from brain_researcher.services.mcp import server as srv

    resp = srv.kg_probe(probe_type="assumption_cracks")

    assert resp == {"ok": False, "error": "query or entity_hints is required"}


def test_kg_find_structural_leverage_mcp_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_find_structural_leverage(
        seed_kg_ids,
        *,
        relation_types=None,
        direction="both",
        limit=25,
        taste=None,
    ):
        captured["kwargs"] = {
            "seed_kg_ids": list(seed_kg_ids),
            "relation_types": relation_types,
            "direction": direction,
            "limit": limit,
            "taste": taste,
        }
        return {"ranked_nodes": [{"kg_id": "node:1", "score": 0.91}]}

    monkeypatch.setattr(
        _query_service,
        "find_structural_leverage",
        fake_find_structural_leverage,
        raising=False,
    )

    resp = srv.kg_find_structural_leverage(
        start_kg_ids=["node:a", "node:b"],
        max_hops=3,
        top_k=5,
        allowed_edge_types=["SUPPORTS"],
    )

    assert resp["ok"] is True
    assert resp["result"]["ranked_nodes"][0]["kg_id"] == "node:1"
    assert captured["kwargs"] == {
        "seed_kg_ids": ["node:a", "node:b"],
        "relation_types": ["SUPPORTS"],
        "direction": "both",
        "limit": 5,
        "taste": None,
    }
    assert "max_hops is currently informational" in " ".join(
        resp["result"].get("warnings", [])
    )


def test_kg_find_structural_leverage_mcp_validation_error():
    from brain_researcher.services.mcp import server as srv

    resp = srv.kg_find_structural_leverage(start_kg_ids=[])
    assert resp == {"ok": False, "error": "start_kg_ids is required"}


def test_kg_detect_contradiction_motifs_mcp_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_detect_contradiction_motifs(
        *,
        hypothesis=None,
        seed_kg_ids=None,
        evidence_items=None,
        max_evidence=80,
        db=None,
    ):
        del db
        captured["kwargs"] = {
            "hypothesis": hypothesis,
            "seed_kg_ids": seed_kg_ids,
            "evidence_items": evidence_items,
            "max_evidence": max_evidence,
        }
        return {"motifs": [{"id": "motif:1", "kind": "support_vs_conflict"}]}

    monkeypatch.setattr(
        _query_service,
        "detect_contradiction_motifs",
        fake_detect_contradiction_motifs,
        raising=False,
    )

    resp = srv.kg_detect_contradiction_motifs(
        hypothesis="Region A supports process X",
        entity_hints=["Region A", "process X"],
        max_results=9,
    )

    assert resp["ok"] is True
    assert resp["result"]["motifs"] == [
        {"id": "motif:1", "kind": "support_vs_conflict"}
    ]
    assert captured["kwargs"] == {
        "hypothesis": "Region A supports process X",
        "seed_kg_ids": ["Region A", "process X"],
        "evidence_items": None,
        "max_evidence": 9,
    }


def test_kg_detect_contradiction_motifs_mcp_validation_error():
    from brain_researcher.services.mcp import server as srv

    resp = srv.kg_detect_contradiction_motifs(hypothesis="   ")
    assert resp == {"ok": False, "error": "hypothesis is required"}


def test_kg_find_contradiction_frontiers_mcp_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_find_contradiction_frontiers(
        *,
        query=None,
        seed_kg_ids=None,
        relation_types=None,
        limit=10,
        max_evidence=80,
        db=None,
    ):
        del db
        captured["kwargs"] = {
            "query": query,
            "seed_kg_ids": seed_kg_ids,
            "relation_types": relation_types,
            "limit": limit,
            "max_evidence": max_evidence,
        }
        return {"frontiers": [{"frontier_label": "weights are required"}]}

    monkeypatch.setattr(
        _query_service,
        "find_contradiction_frontiers",
        fake_find_contradiction_frontiers,
        raising=False,
    )

    resp = srv.kg_find_contradiction_frontiers(
        hypothesis="structural prior",
        entity_hints=["concept:structural_prior"],
        allowed_edge_types=["ASSOCIATED_WITH"],
        max_results=7,
    )

    assert resp["ok"] is True
    assert resp["result"]["frontiers"][0]["frontier_label"] == "weights are required"
    assert captured["kwargs"] == {
        "query": "structural prior",
        "seed_kg_ids": ["concept:structural_prior"],
        "relation_types": ["ASSOCIATED_WITH"],
        "limit": 7,
        "max_evidence": 7,
    }


def test_kg_mine_assumption_cracks_mcp_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_mine_assumption_cracks(
        *,
        query=None,
        seed_kg_ids=None,
        contradiction_frontiers=None,
        limit=10,
        db=None,
    ):
        del contradiction_frontiers, db
        captured["kwargs"] = {
            "query": query,
            "seed_kg_ids": seed_kg_ids,
            "limit": limit,
        }
        return {"cracks": [{"assumption_text": "weights are required"}]}

    monkeypatch.setattr(
        _query_service,
        "mine_assumption_cracks",
        fake_mine_assumption_cracks,
        raising=False,
    )

    resp = srv.kg_mine_assumption_cracks(
        hypothesis="structural prior",
        entity_hints=["concept:structural_prior"],
        max_results=6,
    )

    assert resp["ok"] is True
    assert resp["result"]["cracks"][0]["assumption_text"] == "weights are required"
    assert captured["kwargs"] == {
        "query": "structural prior",
        "seed_kg_ids": ["concept:structural_prior"],
        "limit": 6,
    }


def test_kg_find_analogy_transfers_mcp_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_find_analogy_transfers(
        *,
        query=None,
        seed_kg_ids=None,
        relation_types=None,
        limit=10,
        db=None,
    ):
        del db
        captured["kwargs"] = {
            "query": query,
            "seed_kg_ids": seed_kg_ids,
            "relation_types": relation_types,
            "limit": limit,
        }
        return {"transfers": [{"method_family": "reinforcement_learning"}]}

    monkeypatch.setattr(
        _query_service,
        "find_analogy_transfers",
        fake_find_analogy_transfers,
        raising=False,
    )

    resp = srv.kg_find_analogy_transfers(
        hypothesis="connectomics simulation",
        entity_hints=["concept:connectomics"],
        allowed_edge_types=["USES_METHOD"],
        max_results=4,
    )

    assert resp["ok"] is True
    assert resp["result"]["transfers"][0]["method_family"] == "reinforcement_learning"
    assert captured["kwargs"] == {
        "query": "connectomics simulation",
        "seed_kg_ids": ["concept:connectomics"],
        "relation_types": ["USES_METHOD"],
        "limit": 4,
    }


def test_kg_hypothesis_workflow_sample_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_sample_ood_hypothesis(
        seed_kg_ids,
        *,
        relation_types=None,
        limit=5,
        taste=None,
        db=None,
    ):
        del db
        captured["kwargs"] = {
            "seed_kg_ids": list(seed_kg_ids),
            "relation_types": relation_types,
            "limit": limit,
            "taste": taste,
        }
        return {"samples": [{"hypothesis": "H1"}, {"hypothesis": "H2"}]}

    monkeypatch.setattr(
        _query_service,
        "sample_ood_hypothesis",
        fake_sample_ood_hypothesis,
        raising=False,
    )

    resp = srv.kg_hypothesis_workflow(
        operation="sample",
        seed_kg_ids=["node:seed"],
        n_samples=2,
        max_hops=3,
    )

    assert resp["ok"] is True
    assert resp["result"]["samples"] == [{"hypothesis": "H1"}, {"hypothesis": "H2"}]
    assert captured["kwargs"] == {
        "seed_kg_ids": ["node:seed"],
        "relation_types": None,
        "limit": 2,
        "taste": {"mode": "novelty_first"},
    }
    assert "max_hops is currently informational" in " ".join(
        resp["result"].get("warnings", [])
    )


def test_kg_hypothesis_workflow_verify_candidates_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_verify_sampled_hypotheses(
        sampled_hypotheses,
        *,
        query=None,
        seed_kg_ids=None,
        verify_top_k=None,
        strictness="high_recall",
        allowed_node_types=None,
        max_evidence=60,
        max_paths=60,
        min_evidence_score=None,
        include_subgraph=False,
        include_path_details=False,
        confidence_scoring_version="v2",
        candidate_lane_mode="broad",
        use_external_literature=False,
        external_literature_top_k=5,
        external_literature_recency_days=365,
        external_literature_exclude_domains=None,
        db=None,
    ):
        del db
        captured["kwargs"] = {
            "sampled_hypotheses": sampled_hypotheses,
            "query": query,
            "seed_kg_ids": seed_kg_ids,
            "verify_top_k": verify_top_k,
            "strictness": strictness,
            "allowed_node_types": allowed_node_types,
            "max_evidence": max_evidence,
            "max_paths": max_paths,
            "min_evidence_score": min_evidence_score,
            "include_subgraph": include_subgraph,
            "include_path_details": include_path_details,
            "confidence_scoring_version": confidence_scoring_version,
            "candidate_lane_mode": candidate_lane_mode,
            "use_external_literature": use_external_literature,
            "external_literature_top_k": external_literature_top_k,
            "external_literature_recency_days": external_literature_recency_days,
            "external_literature_exclude_domains": external_literature_exclude_domains,
        }
        return {
            "tested_hypotheses": [
                {
                    "rank": 1,
                    "candidate_kg_id": "node:candidate",
                    "kg_verification": {"verdict": "supported", "confidence": 0.61},
                }
            ],
            "summary": {"n_tested": 1, "n_supported": 1},
        }

    monkeypatch.setattr(
        _query_service,
        "verify_sampled_hypotheses",
        fake_verify_sampled_hypotheses,
        raising=False,
    )

    resp = srv.kg_hypothesis_workflow(
        operation="verify_candidates",
        sampled_hypotheses=[{"rank": 1, "statement": "H1"}],
        seed_kg_ids=["node:seed"],
        verify_top_k=1,
        strictness="conservative",
        candidate_lane_mode="strict",
        allowed_node_types=["Task"],
        include_subgraph=True,
    )

    assert resp["ok"] is True
    assert resp["result"]["summary"] == {"n_tested": 1, "n_supported": 1}
    assert captured["kwargs"] == {
        "sampled_hypotheses": [{"rank": 1, "statement": "H1"}],
        "query": None,
        "seed_kg_ids": ["node:seed"],
        "verify_top_k": 1,
        "strictness": "conservative",
        "allowed_node_types": ["Task"],
        "max_evidence": 60,
        "max_paths": 60,
        "min_evidence_score": None,
        "include_subgraph": True,
        "include_path_details": False,
        "confidence_scoring_version": "v2",
        "candidate_lane_mode": "strict",
        "use_external_literature": False,
        "external_literature_top_k": 5,
        "external_literature_recency_days": 365,
        "external_literature_exclude_domains": None,
    }


def test_kg_hypothesis_workflow_sample_and_verify_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_sample_and_verify_hypotheses(
        seed_kg_ids,
        *,
        query=None,
        relation_types=None,
        sample_limit=5,
        verify_top_k=None,
        taste=None,
        strictness="high_recall",
        allowed_node_types=None,
        max_evidence=60,
        max_paths=60,
        min_evidence_score=None,
        include_subgraph=False,
        include_path_details=False,
        confidence_scoring_version="v2",
        candidate_lane_mode="broad",
        use_external_literature=False,
        external_literature_top_k=5,
        external_literature_recency_days=365,
        external_literature_exclude_domains=None,
        db=None,
    ):
        del db
        captured["kwargs"] = {
            "seed_kg_ids": list(seed_kg_ids),
            "query": query,
            "relation_types": relation_types,
            "sample_limit": sample_limit,
            "verify_top_k": verify_top_k,
            "taste": taste,
            "strictness": strictness,
            "allowed_node_types": allowed_node_types,
            "max_evidence": max_evidence,
            "max_paths": max_paths,
            "min_evidence_score": min_evidence_score,
            "include_subgraph": include_subgraph,
            "include_path_details": include_path_details,
            "confidence_scoring_version": confidence_scoring_version,
            "candidate_lane_mode": candidate_lane_mode,
            "use_external_literature": use_external_literature,
            "external_literature_top_k": external_literature_top_k,
            "external_literature_recency_days": external_literature_recency_days,
            "external_literature_exclude_domains": external_literature_exclude_domains,
        }
        return {
            "sampled_hypotheses": [{"rank": 1, "statement": "H1"}],
            "tested_hypotheses": [{"rank": 1, "statement": "H1"}],
            "summary": {"n_tested": 1},
        }

    monkeypatch.setattr(
        _query_service,
        "sample_and_verify_hypotheses",
        fake_sample_and_verify_hypotheses,
        raising=False,
    )

    resp = srv.kg_hypothesis_workflow(
        operation="sample_and_verify",
        seed_kg_ids=["node:seed"],
        n_samples=3,
        verify_top_k=2,
        max_hops=3,
        strategy="evidence_first",
        strictness="conservative",
        candidate_lane_mode="strict",
        allowed_node_types=["Task", "Concept"],
        include_subgraph=True,
    )

    assert resp["ok"] is True
    assert captured["kwargs"] == {
        "seed_kg_ids": ["node:seed"],
        "query": None,
        "relation_types": None,
        "sample_limit": 3,
        "verify_top_k": 2,
        "taste": {"mode": "evidence_first"},
        "strictness": "conservative",
        "allowed_node_types": ["Task", "Concept"],
        "max_evidence": 60,
        "max_paths": 60,
        "min_evidence_score": None,
        "include_subgraph": True,
        "include_path_details": False,
        "confidence_scoring_version": "v2",
        "candidate_lane_mode": "strict",
        "use_external_literature": False,
        "external_literature_top_k": 5,
        "external_literature_recency_days": 365,
        "external_literature_exclude_domains": None,
    }
    assert "max_hops is currently informational" in " ".join(
        resp["result"].get("warnings", [])
    )


def test_kg_hypothesis_workflow_validation_errors():
    from brain_researcher.services.mcp import server as srv

    assert srv.kg_hypothesis_workflow(operation="mystery") == {
        "ok": False,
        "error": (
            "unsupported operation: 'mystery'. Supported values: "
            "sample, verify_candidates, sample_and_verify"
        ),
    }
    assert srv.kg_hypothesis_workflow(operation="verify_candidates") == {
        "ok": False,
        "error": "sampled_hypotheses is required",
    }


def test_kg_sample_ood_hypothesis_mcp_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_sample_ood_hypothesis(
        seed_kg_ids,
        *,
        relation_types=None,
        limit=5,
        taste=None,
        db=None,
    ):
        del db
        captured["kwargs"] = {
            "seed_kg_ids": list(seed_kg_ids),
            "relation_types": relation_types,
            "limit": limit,
            "taste": taste,
        }
        return {"samples": [{"hypothesis": "H1"}, {"hypothesis": "H2"}]}

    monkeypatch.setattr(
        _query_service,
        "sample_ood_hypothesis",
        fake_sample_ood_hypothesis,
        raising=False,
    )

    resp = srv.kg_sample_ood_hypothesis(
        seed_kg_ids=["node:seed"],
        n_samples=2,
        max_hops=3,
        strategy="frontier",
    )

    assert resp["ok"] is True
    assert resp["result"]["samples"] == [{"hypothesis": "H1"}, {"hypothesis": "H2"}]
    assert captured["kwargs"] == {
        "seed_kg_ids": ["node:seed"],
        "relation_types": None,
        "limit": 2,
        "taste": {"mode": "novelty_first"},
    }
    assert "max_hops is currently informational" in " ".join(
        resp["result"].get("warnings", [])
    )


def test_kg_sample_ood_hypothesis_mcp_validation_error():
    from brain_researcher.services.mcp import server as srv

    resp = srv.kg_sample_ood_hypothesis(seed_kg_ids=[])
    assert resp == {"ok": False, "error": "seed_kg_ids is required"}


def test_kg_hypothesis_candidate_cards_mcp_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    captured: dict[str, object] = {}

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del work_dir, output_dir, preview
        captured["tool_id"] = tool_id
        captured["parameters"] = dict(parameters)
        return ToolResult(
            status="success",
            data={
                "workflow": "workflow_hypothesis_candidate_cards",
                "steps": {
                    "leverage": {
                        "data": {
                            "resolved_anchor_bundle": [
                                {
                                    "kg_id": "concept:attention",
                                    "label": "Attention",
                                    "node_type": "Concept",
                                    "matched_queries": ["attention control"],
                                }
                            ]
                        }
                    }
                },
            },
        )

    def fake_build_candidate_cards_from_workflow_result(
        workflow_result, *, query, top_n=5, memory_store=None
    ):
        del memory_store
        captured["build_query"] = query
        captured["build_top_n"] = top_n
        assert workflow_result["workflow"] == "workflow_hypothesis_candidate_cards"
        return [
            {
                "card_id": "cand_01",
                "title": "Attention control OOD hypothesis",
                "hypothesis": "Attention may shift under OOD settings.",
                "taste_axis": "controlled_ood_search",
                "minimal_discriminating_test": "Run the smallest split first.",
                "falsifier_hint": "Reject if the effect disappears under controls.",
                "kg_verification": {"verdict": "insufficient_evidence"},
                "provenance": {"seed_kg_id": "concept:attention"},
            }
        ]

    def fake_deep_research_sync(request):
        captured["deep_research_request"] = dict(request)
        return {
            "status": "cached",
            "idempotency_key": "dr:test",
            "result": {
                "status": "ok",
                "summary": "Recent literature suggests attention effects depend on task framing.",
                "synthesis_full_text": "Recent literature suggests attention effects depend on task framing.",
                "documents": [{"url": "https://example.org/paper"}],
                "quality": {"citable_count": 1},
                "metadata": {"provider": "google_deep_research"},
                "search_trails": [],
            },
        }

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(
        srv,
        "build_candidate_cards_from_workflow_result",
        fake_build_candidate_cards_from_workflow_result,
    )
    monkeypatch.setattr(srv, "deep_research_sync", fake_deep_research_sync)
    monkeypatch.setattr(
        srv,
        "generate_deep_research_idea_cards_from_result",
        lambda **kwargs: {"candidate_cards": [], "summary": {"n_candidate_cards": 0}},
    )

    original_execute_candidate_cards_core = srv._execute_candidate_cards_core

    def fake_execute_candidate_cards_core(*args, **kwargs):
        result = original_execute_candidate_cards_core(*args, **kwargs)
        result["novelty_calibration_questions"] = [
            {
                "id": "ncq_01",
                "targets_card_id": "cand_01",
                "novelty_dimension": "overall_combination",
                "question": "Is this a genuine advance or a stacking of known ideas?",
            }
        ]
        result["novelty_calibration_meta"] = {
            "total_questions": 1,
            "dimensions_covered": ["overall_combination"],
            "kg_evidence_used": True,
        }
        return result

    monkeypatch.setattr(
        srv, "_execute_candidate_cards_core", fake_execute_candidate_cards_core
    )

    resp = srv.kg_hypothesis_candidate_cards(
        query="attention control",
        seed_kg_ids=["concept:attention"],
        relation_types=["ASSOCIATED_WITH"],
        top_n=1,
        top_k=8,
        taste_mode="balanced",
        controller_mode="principle_v0",
        candidate_lane_mode="strict",
        exclude_domains=["example.com"],
    )

    assert resp["ok"] is True
    assert captured["tool_id"] == "workflow_hypothesis_candidate_cards"
    assert captured["parameters"] == {
        "query": "attention control",
        "seed_kg_ids": ["concept:attention"],
        "relation_types": ["ASSOCIATED_WITH"],
        "top_k": 8,
        "n_samples": 1,
        "taste_mode": "balanced",
        "controller_mode": "principle_v0",
        "candidate_lane_mode": "strict",
        "use_external_literature": True,
        "verify_use_external_literature": False,
        "external_literature_top_k": 5,
        "external_literature_recency_days": 365,
        "external_literature_exclude_domains": ["example.com"],
    }
    assert captured["build_query"] == "attention control"
    assert captured["build_top_n"] == 1
    assert captured["deep_research_request"] == {
        "query": "attention control",
        "recency_days": 365,
        "top_k": 8,
        "exclude_domains": ["example.com"],
    }
    assert resp["result"]["summary"] == {
        "n_candidate_cards": 1,
        "n_grounded_cards": 0,
        "n_degraded_cards": 1,
        "candidate_lane_mode": "strict",
        "deep_research_requested": True,
        "deep_research_idea_cards_used": False,
        "quality_bucket_counts": {},
        "rewrite_status_counts": {},
        "gap_type_counts": {},
    }
    assert resp["result"]["resolved_anchor_bundle"] == [
        {
            "kg_id": "concept:attention",
            "label": "Attention",
            "node_type": "Concept",
            "matched_queries": ["attention control"],
        }
    ]
    card = resp["result"]["candidate_cards"][0]
    assert card["kg_verification"] == {"verdict": "insufficient_evidence"}
    assert card["grounding_status"] == "degraded"
    assert card["grounding_basis"] == "report_only"
    assert (
        card["evidence_summary"]
        == "Recent literature suggests attention effects depend on task framing."
    )
    assert card["deep_research_status"] == "ok"
    assert card["deep_research_idempotency_key"] == "dr:test"
    assert resp["result"]["deep_research"]["report"]["summary"].startswith(
        "Recent literature suggests"
    )
    assert resp["result"]["novelty_calibration_questions"] == [
        {
            "id": "ncq_01",
            "targets_card_id": "cand_01",
            "novelty_dimension": "overall_combination",
            "question": "Is this a genuine advance or a stacking of known ideas?",
        }
    ]
    assert resp["result"]["novelty_calibration_meta"] == {
        "total_questions": 1,
        "dimensions_covered": ["overall_combination"],
        "kg_evidence_used": True,
    }


def test_kg_hypothesis_candidate_cards_mcp_filters_raw_template_cards(
    monkeypatch,
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del tool_id, parameters, work_dir, output_dir, preview
        return ToolResult(
            status="success",
            data={
                "workflow": "workflow_hypothesis_candidate_cards",
                "candidate_cards": [
                    {
                        "card_id": "raw_weak_01",
                        "title": "Weak raw workflow candidate",
                        "hypothesis": (
                            "Effects may transfer because both are in the same family."
                        ),
                        "idea": "Test whether the node provides a tighter handle.",
                        "mechanism": "Shared latent mechanism.",
                        "quality_bucket": "template_only",
                        "rewrite_status": "needs_rewrite",
                        "kg_verification": {
                            "verdict": "insufficient_evidence",
                            "confidence": 0.03,
                            "evidence_source_scope": "expanded_family",
                            "summary": {
                                "n_supporting": 1,
                                "n_conflicting": 8,
                            },
                        },
                    }
                ],
            },
        )

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(
        srv,
        "build_candidate_cards_from_workflow_result",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("workflow fallback should not be used")
        ),
    )
    monkeypatch.setattr(
        srv,
        "generate_deep_research_idea_cards_from_result",
        lambda **kwargs: {"candidate_cards": [], "summary": {"n_candidate_cards": 0}},
    )

    resp = srv.kg_hypothesis_candidate_cards(
        query="attention control",
        top_n=1,
        top_k=8,
        with_deep_research=False,
    )

    assert resp["ok"] is True
    assert resp["result"]["candidate_cards"] == []
    assert resp["result"]["summary"]["n_candidate_cards"] == 0
    assert resp["result"]["warnings"] == ["no_candidate_cards"]


def test_kg_hypothesis_candidate_cards_mcp_preserves_gap_fields_and_reranks(
    monkeypatch,
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del tool_id, parameters, work_dir, output_dir, preview
        return ToolResult(
            status="success",
            data={
                "workflow": "workflow_hypothesis_candidate_cards",
                "candidate_cards": [
                    {
                        "card_id": "cand_01",
                        "title": "Ontology-gap candidate",
                        "hypothesis": "Hypothesis 1",
                        "grounding_status": "grounded",
                        "quality_bucket": "actual_idea_like",
                        "rewrite_status": "rewritten",
                        "gap_type": "ontology",
                        "gap_specification": "Needs a named mechanism.",
                        "gap_actionable": False,
                        "provenance": {
                            "sampled_hypothesis_verification": {
                                "gap_type": "ontology",
                                "gap_specification": "Needs a named mechanism.",
                                "gap_actionable": False,
                            }
                        },
                    },
                    {
                        "card_id": "cand_02",
                        "title": "Evidence-gap candidate",
                        "hypothesis": "Hypothesis 2",
                        "grounding_status": "grounded",
                        "quality_bucket": "actual_idea_like",
                        "rewrite_status": "rewritten",
                        "gap_type": "evidence",
                        "gap_specification": "Needs a discriminating experiment.",
                        "gap_actionable": True,
                        "provenance": {
                            "sampled_hypothesis_verification": {
                                "gap_type": "evidence",
                                "gap_specification": (
                                    "Needs a discriminating experiment."
                                ),
                                "gap_actionable": True,
                            }
                        },
                    },
                ],
            },
        )

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(
        srv,
        "generate_deep_research_idea_cards_from_result",
        lambda **kwargs: {"candidate_cards": [], "summary": {"n_candidate_cards": 0}},
    )

    resp = srv.kg_hypothesis_candidate_cards(
        query="attention control",
        top_n=2,
        top_k=8,
        with_deep_research=False,
    )

    assert resp["ok"] is True
    assert resp["result"]["summary"]["gap_type_counts"] == {
        "evidence": 1,
        "ontology": 1,
    }
    assert [card["card_id"] for card in resp["result"]["candidate_cards"]] == [
        "cand_02",
        "cand_01",
    ]
    first = resp["result"]["candidate_cards"][0]
    second = resp["result"]["candidate_cards"][1]
    assert first["gap_type"] == "evidence"
    assert first["gap_specification"] == "Needs a discriminating experiment."
    assert first["gap_actionable"] is True
    assert first["provenance"]["sampled_hypothesis_verification"] == {
        "gap_type": "evidence",
        "gap_specification": "Needs a discriminating experiment.",
        "gap_actionable": True,
    }
    assert second["gap_type"] == "ontology"
    assert second["gap_specification"] == "Needs a named mechanism."
    assert second["gap_actionable"] is False
    assert second["provenance"]["sampled_hypothesis_verification"] == {
        "gap_type": "ontology",
        "gap_specification": "Needs a named mechanism.",
        "gap_actionable": False,
    }


def test_kg_hypothesis_candidate_cards_mcp_deep_research_error_degrades_cards(
    monkeypatch,
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del tool_id, parameters, work_dir, output_dir, preview
        return ToolResult(
            status="success",
            data={
                "workflow": "workflow_hypothesis_candidate_cards",
                "candidate_cards": [
                    {
                        "card_id": "cand_01",
                        "title": "Candidate 1",
                        "hypothesis": "Hypothesis 1",
                        "taste_axis": "bridge_disconnected_regions",
                    }
                ],
            },
        )

    def fake_deep_research_sync(request):
        del request
        return {"status": "error", "error": "missing_api_key"}

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(srv, "deep_research_sync", fake_deep_research_sync)
    monkeypatch.setattr(
        srv,
        "generate_deep_research_idea_cards_from_result",
        lambda **kwargs: {"candidate_cards": [], "summary": {"n_candidate_cards": 0}},
    )

    resp = srv.kg_hypothesis_candidate_cards(query="reward learning")

    assert resp["ok"] is True
    assert "deep_research_error" in resp["result"]["warnings"]
    assert resp["result"]["summary"]["n_candidate_cards"] == 1
    assert resp["result"]["summary"]["n_grounded_cards"] == 0
    assert resp["result"]["summary"]["n_degraded_cards"] == 1
    assert resp["result"]["summary"]["deep_research_idea_cards_used"] is False
    assert resp["result"]["summary"]["quality_bucket_counts"] == {}
    assert resp["result"]["summary"]["rewrite_status_counts"] == {}
    card = resp["result"]["candidate_cards"][0]
    assert card["grounding_status"] == "degraded"
    assert card["deep_research_error"] == "missing_api_key"
    assert resp["result"]["deep_research"]["status"] == "error"


def test_kg_hypothesis_candidate_cards_includes_frontier_mode_when_requested(
    monkeypatch,
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    captured: dict[str, object] = {}

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del work_dir, output_dir, preview
        captured["tool_id"] = tool_id
        captured["parameters"] = dict(parameters)
        return ToolResult(
            status="success",
            data={
                "workflow": "workflow_hypothesis_candidate_cards",
                "candidate_cards": [],
            },
        )

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(
        srv, "deep_research_sync", lambda request: {"status": "error", "error": "skip"}
    )
    monkeypatch.setattr(
        srv,
        "generate_deep_research_idea_cards_from_result",
        lambda **kwargs: {"candidate_cards": [], "summary": {"n_candidate_cards": 0}},
    )

    resp = srv.kg_hypothesis_candidate_cards(
        query="attention control",
        frontier_mode="frontier",
        with_deep_research=False,
    )

    assert resp["ok"] is True
    assert captured["tool_id"] == "workflow_hypothesis_candidate_cards"
    assert captured["parameters"]["frontier_mode"] == "frontier"


def test_kg_hypothesis_candidate_cards_keeps_workflow_cards_when_deep_research_cards_exist(
    monkeypatch,
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    captured: dict[str, object] = {}

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del tool_id, parameters, work_dir, output_dir, preview
        return ToolResult(
            status="success",
            data={
                "workflow": "workflow_hypothesis_candidate_cards",
                "candidate_cards": [
                    {
                        "card_id": "workflow_01",
                        "title": "Workflow candidate",
                        "hypothesis": "Workflow hypothesis",
                        "taste_axis": "workflow_default",
                    }
                ],
            },
        )

    def fake_deep_research_get(*, interaction_id=None, idempotency_key=None):
        del idempotency_key
        captured["interaction_id"] = interaction_id
        return {
            "status": "cached",
            "idempotency_key": "dr:idea",
            "result": {
                "status": "ok",
                "summary": "Deep research summary",
                "synthesis_full_text": "Deep research summary",
                "documents": [{"url": "https://example.org/paper"}],
                "raw": {"outputs": []},
                "metadata": {
                    "provider": "google_deep_research",
                    "interaction_id": interaction_id,
                },
            },
        }

    def fake_generate_deep_research_idea_cards_from_result(**kwargs):
        captured["idea_query"] = kwargs["query"]
        return {
            "candidate_cards": [
                {
                    "card_id": "dr_01",
                    "title": "Deep research card",
                    "hypothesis": "Grounded deep research hypothesis",
                    "taste_axis": "deep_research_mechanism",
                    "minimal_discriminating_test": "Run the bounded comparison.",
                    "falsifier_hint": "Reject if the grounded contrast vanishes.",
                    "novelty_signals": {"controlled_ood_score": 0.73},
                    "topology_subgraph": {
                        "focus_node_id": "drn_focus",
                        "node_ids": ["drn_focus", "drn_pub"],
                        "edge_ids": ["dre_supports"],
                    },
                    "provenance": {"object_label": "surprise"},
                }
            ],
            "summary": {"n_candidate_cards": 1},
            "artifacts": {"idea_cards_path": "/tmp/idea_cards.json"},
            "ephemeral_weighted_subgraph": {
                "summary": {
                    "node_count": 2,
                    "edge_count": 1,
                    "card_subgraph_count": 1,
                }
            },
        }

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(srv, "deep_research_get", fake_deep_research_get)
    monkeypatch.setattr(
        srv,
        "generate_deep_research_idea_cards_from_result",
        fake_generate_deep_research_idea_cards_from_result,
    )

    resp = srv.kg_hypothesis_candidate_cards(
        query="attention control",
        with_deep_research=False,
        deep_research_interaction_id="int-123",
        top_n=1,
    )

    assert resp["ok"] is True
    assert captured["interaction_id"] == "int-123"
    assert captured["idea_query"] == "attention control"
    assert resp["result"]["candidate_cards"][0]["card_id"] == "workflow_01"
    assert resp["result"]["candidate_cards"][0]["grounding_status"] == "degraded"
    assert resp["result"]["candidate_cards"][0]["grounding_basis"] == "report_only"
    assert resp["result"]["summary"]["deep_research_requested"] is True
    assert resp["result"]["summary"]["deep_research_idea_cards_used"] is False
    assert resp["result"]["deep_research"]["idea_cards"]["status"] == "ok"
    assert resp["result"]["deep_research"]["idea_cards"]["used_as_primary"] is False
    assert resp["result"]["ephemeral_weighted_subgraph"]["summary"]["node_count"] == 2


def test_kg_hypothesis_candidate_cards_promotes_deep_research_cards_over_weak_workflow_cards(
    monkeypatch,
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    captured: dict[str, object] = {}

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del tool_id, parameters, work_dir, output_dir, preview
        return ToolResult(
            status="success",
            data={
                "workflow": "workflow_hypothesis_candidate_cards",
                "candidate_cards": [
                    {
                        "card_id": "workflow_01",
                        "title": "Weak workflow candidate",
                        "hypothesis": "Weak workflow hypothesis",
                        "taste_axis": "workflow_default",
                        "quality_bucket": "template_only",
                        "rewrite_status": "needs_rewrite",
                        "kg_verification": {"verdict": "insufficient_evidence"},
                    }
                ],
            },
        )

    def fake_deep_research_get(*, interaction_id=None, idempotency_key=None):
        del idempotency_key
        captured["interaction_id"] = interaction_id
        return {
            "status": "cached",
            "idempotency_key": "dr:idea",
            "result": {
                "status": "ok",
                "summary": "Deep research summary",
                "synthesis_full_text": "Deep research summary",
                "documents": [{"url": "https://example.org/paper"}],
                "raw": {"outputs": []},
                "metadata": {
                    "provider": "google_deep_research",
                    "interaction_id": interaction_id,
                },
            },
        }

    def fake_generate_deep_research_idea_cards_from_result(**kwargs):
        captured["idea_query"] = kwargs["query"]
        return {
            "candidate_cards": [
                {
                    "card_id": "dr_01",
                    "title": "Deep research card",
                    "hypothesis": "Grounded deep research hypothesis",
                    "taste_axis": "deep_research_mechanism",
                    "minimal_discriminating_test": "Run the bounded comparison.",
                    "falsifier_hint": "Reject if the grounded contrast vanishes.",
                    "novelty_signals": {"controlled_ood_score": 0.73},
                    "topology_subgraph": {
                        "focus_node_id": "drn_focus",
                        "node_ids": ["drn_focus", "drn_pub"],
                        "edge_ids": ["dre_supports"],
                    },
                    "evidence_source_scope": "cross_source",
                    "supporting_paper_titles": [
                        "Mitochondrial Energy Transformation Capacity Influences Brain Activation"
                    ],
                    "provenance": {
                        "object_label": "surprise",
                        "supporting_paper_ids": ["paper:1", "paper:2"],
                    },
                }
            ],
            "summary": {"n_candidate_cards": 1},
            "artifacts": {"idea_cards_path": "/tmp/idea_cards.json"},
            "ephemeral_weighted_subgraph": {
                "summary": {
                    "node_count": 2,
                    "edge_count": 1,
                    "card_subgraph_count": 1,
                }
            },
        }

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(srv, "deep_research_get", fake_deep_research_get)
    monkeypatch.setattr(
        srv,
        "generate_deep_research_idea_cards_from_result",
        fake_generate_deep_research_idea_cards_from_result,
    )

    resp = srv.kg_hypothesis_candidate_cards(
        query="attention control",
        with_deep_research=False,
        deep_research_interaction_id="int-456",
        top_n=1,
    )

    assert resp["ok"] is True
    assert captured["interaction_id"] == "int-456"
    assert captured["idea_query"] == "attention control"
    assert resp["result"]["candidate_cards"][0]["card_id"] == "dr_01"
    assert resp["result"]["candidate_cards"][0]["grounding_status"] == "grounded"
    assert (
        resp["result"]["candidate_cards"][0]["grounding_basis"]
        == "card_specific_evidence"
    )
    assert resp["result"]["candidate_cards"][0]["supporting_paper_titles"] == [
        "Mitochondrial Energy Transformation Capacity Influences Brain Activation"
    ]
    assert resp["result"]["summary"]["deep_research_requested"] is True
    assert resp["result"]["summary"]["deep_research_idea_cards_used"] is True
    assert resp["result"]["deep_research"]["idea_cards"]["status"] == "ok"
    assert resp["result"]["deep_research"]["idea_cards"]["used_as_primary"] is True
    assert resp["result"]["ephemeral_weighted_subgraph"]["summary"]["node_count"] == 2


def test_is_weak_baseline_candidate_card_marks_net_negative_evidence_as_weak():
    from brain_researcher.services.mcp import server as srv

    assert (
        srv._is_weak_baseline_candidate_card(
            {
                "quality_bucket": "actual_idea_like",
                "rewrite_status": "rewritten",
                "kg_verification": {
                    "verdict": "insufficient_evidence",
                    "confidence": 0.45,
                    "summary": {
                        "n_supporting": 2,
                        "n_external_literature_supporting": 0,
                        "n_conflicting": 50,
                    },
                },
            }
        )
        is True
    )


def test_kg_hypothesis_candidate_cards_start_and_get_success(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    captured: dict[str, object] = {}

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del work_dir, output_dir, preview
        captured["tool_id"] = tool_id
        captured["parameters"] = dict(parameters)
        progress_callback = parameters.get("_progress_callback")
        if callable(progress_callback):
            progress_callback(
                {
                    "workflow_id": "workflow_hypothesis_candidate_cards",
                    "step_id": "verify_sampled_hypotheses",
                    "tool_name": "neurokg.verify_sampled_hypotheses",
                    "step_index": 2,
                    "total_steps": 5,
                    "status": "running",
                    "progress_pct": 50.0,
                }
            )
            progress_callback(
                {
                    "workflow_id": "workflow_hypothesis_candidate_cards",
                    "step_id": "verify_sampled_hypotheses",
                    "tool_name": "neurokg.verify_sampled_hypotheses",
                    "step_index": 2,
                    "total_steps": 5,
                    "status": "completed",
                    "progress_pct": 60.0,
                }
            )
        return ToolResult(
            status="success",
            data={
                "workflow": "workflow_hypothesis_candidate_cards",
                "steps": {
                    "leverage": {
                        "data": {
                            "resolved_anchor_bundle": [
                                {
                                    "kg_id": "concept:attention",
                                    "label": "Attention",
                                    "node_type": "Concept",
                                    "matched_queries": ["attention control"],
                                }
                            ]
                        }
                    }
                },
            },
        )

    def fake_build_candidate_cards_from_workflow_result(
        workflow_result, *, query, top_n=5, memory_store=None
    ):
        del query, top_n, memory_store
        return [
            {
                "card_id": "cand_01",
                "title": "Attention control OOD hypothesis",
                "hypothesis": "Attention may shift under OOD settings.",
                "taste_axis": "controlled_ood_search",
                "minimal_discriminating_test": "Run the smallest split first.",
                "falsifier_hint": "Reject if the effect disappears.",
                "kg_verification": {"verdict": "insufficient_evidence"},
                "provenance": {"seed_kg_id": "concept:attention"},
            }
        ]

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(
        srv,
        "build_candidate_cards_from_workflow_result",
        fake_build_candidate_cards_from_workflow_result,
    )

    original_execute_candidate_cards_core = srv._execute_candidate_cards_core

    def fake_execute_candidate_cards_core(*args, **kwargs):
        result = original_execute_candidate_cards_core(*args, **kwargs)
        result["novelty_calibration_questions"] = [
            {
                "id": "ncq_01",
                "targets_card_id": "cand_01",
                "novelty_dimension": "overall_combination",
                "question": "Is this a genuine advance or a stacking of known ideas?",
            }
        ]
        result["novelty_calibration_meta"] = {
            "total_questions": 1,
            "dimensions_covered": ["overall_combination"],
            "kg_evidence_used": True,
        }
        return result

    monkeypatch.setattr(
        srv, "_execute_candidate_cards_core", fake_execute_candidate_cards_core
    )

    resp = srv.kg_hypothesis_candidate_cards_start(
        query="attention control",
        seed_kg_ids=["concept:attention"],
        top_n=1,
        top_k=8,
        with_deep_research=False,
        candidate_lane_mode="strict",
    )

    assert resp["ok"] is True
    assert resp["status"] == "queued"
    assert resp["execution_mode"] == "background"
    assert resp["execution_trace"] == ["validated", "queued_background_run"]
    assert resp["poll_tool"] == "run_get"
    assert resp["compat_poll_tool"] == "kg_hypothesis_candidate_cards_get"
    run_id = resp["run_id"]

    deadline = time.time() + 5.0
    result = None
    status = None
    while time.time() < deadline:
        result = srv.run_get(run_id)
        assert result["ok"] is True
        status = result["status"]
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.05)

    assert status == "succeeded"
    assert result["done"] is True
    assert "result" in result
    assert result["result"]["query"] == "attention control"
    assert result["result"]["summary"]["n_candidate_cards"] == 1
    assert result["result"]["candidate_cards"][0]["card_id"] == "cand_01"
    assert result["result"]["novelty_calibration_questions"] == [
        {
            "id": "ncq_01",
            "targets_card_id": "cand_01",
            "novelty_dimension": "overall_combination",
            "question": "Is this a genuine advance or a stacking of known ideas?",
        }
    ]
    assert result["result"]["novelty_calibration_meta"] == {
        "total_questions": 1,
        "dimensions_covered": ["overall_combination"],
        "kg_evidence_used": True,
    }
    assert result["run"]["steps"][0]["tool_id"] == "kg_hypothesis_candidate_cards"
    assert result["run"]["steps"][0]["result_path"] == (
        "artifacts/candidate_cards_result.json"
    )
    assert result["progress"]["stalled"] is False
    assert result["progress"]["current_stage"] == "completed"
    assert result["progress"]["message"] == "Candidate cards generation completed"
    # Verify stage_timings observability
    assert "stage_timings" in result
    stage_names = [t["stage"] for t in result["stage_timings"]]
    assert "workflow_start" in stage_names
    assert "workflow_step:verify_sampled_hypotheses" in stage_names
    assert "workflow_step:verify_sampled_hypotheses:completed" in stage_names
    assert "workflow_done" in stage_names
    assert "completed" in stage_names
    for timing in result["stage_timings"]:
        assert "started_at" in timing
        assert "elapsed_s" in timing
        assert isinstance(timing["elapsed_s"], float)


def test_kg_hypothesis_candidate_cards_start_background_failure(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del tool_id, parameters, work_dir, output_dir, preview
        raise RuntimeError("workflow_exploded")

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    resp = srv.kg_hypothesis_candidate_cards_start(
        query="reward learning",
        with_deep_research=False,
    )
    assert resp["ok"] is True
    run_id = resp["run_id"]

    deadline = time.time() + 5.0
    result = None
    status = None
    while time.time() < deadline:
        result = srv.run_get(run_id)
        assert result["ok"] is True
        status = result["status"]
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.05)

    assert status == "failed"
    assert result["run"]["error"] == "workflow_exploded"
    assert "result" not in result
    assert result["progress"]["current_stage"] == "failed"
    assert result["progress"]["message"] == "workflow_exploded"
    # stage_timings should be present even on failure (from error artifact)
    assert "stage_timings" in result
    stage_names = [t["stage"] for t in result["stage_timings"]]
    assert "workflow_start" in stage_names


def test_kg_hypothesis_candidate_cards_start_validation_error():
    from brain_researcher.services.mcp import server as srv

    assert srv.kg_hypothesis_candidate_cards_start(query="") == {
        "ok": False,
        "error": "query is required",
    }
    assert srv.kg_hypothesis_candidate_cards_start(query="attention", top_n="abc") == {
        "ok": False,
        "error": "top_n must be an integer",
    }
    assert srv.kg_hypothesis_candidate_cards_start(query="attention", top_n=0) == {
        "ok": False,
        "error": "top_n must be >= 1",
    }


def test_kg_hypothesis_candidate_cards_get_missing_run(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "_proxy_agent_run_status", lambda run_id: None)
    result = srv.kg_hypothesis_candidate_cards_get("nonexistent_run_id")
    assert result["ok"] is False
    assert "run not found" in result["error"]


def test_kg_hypothesis_candidate_cards_get_compat_alias_matches_run_get(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()
    run_id = "candidate_cards_alias_run"
    run_dir = tmp_path / "runs" / run_id
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "created_at": "2026-01-01T00:00:00Z",
                "status": "succeeded",
                "dry_run": False,
                "steps": [
                    {
                        "step_id": "candidate_cards",
                        "tool_id": "kg_hypothesis_candidate_cards",
                        "status": "succeeded",
                        "result_path": "artifacts/candidate_cards_result.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "artifacts" / "candidate_cards_result.json").write_text(
        json.dumps(
            {
                "query": "attention control",
                "summary": {"n_candidate_cards": 1},
                "warnings": ["deep_research_warning"],
                "novelty_calibration_questions": [
                    {
                        "id": "ncq_01",
                        "targets_card_id": "cand_01",
                        "claim_surface": "overall_combination",
                        "question": "Is this a genuine advance or a stacking of known ideas?",
                    }
                ],
                "novelty_calibration_meta": {
                    "total_questions": 1,
                    "dimensions_covered": ["overall_combination"],
                    "source": "candidate_cards_v1",
                    "schema_version": "v1",
                },
                "_stage_timings": [{"stage": "completed", "elapsed_s": 1.0}],
            }
        ),
        encoding="utf-8",
    )

    compat = srv.kg_hypothesis_candidate_cards_get(run_id)
    generic = srv.run_get(run_id)

    assert compat["ok"] is True
    assert compat["run_id"] == generic["run_id"] == run_id
    assert compat["status"] == generic["status"] == "succeeded"
    assert compat["done"] is True
    assert compat["summary"] == generic["summary"] == {"n_candidate_cards": 1}
    assert compat["warnings"] == generic["warnings"] == ["deep_research_warning"]
    assert (
        compat["novelty_calibration_questions"]
        == generic["novelty_calibration_questions"]
        == [
            {
                "id": "ncq_01",
                "targets_card_id": "cand_01",
                "claim_surface": "overall_combination",
                "question": "Is this a genuine advance or a stacking of known ideas?",
            }
        ]
    )
    assert (
        compat["novelty_calibration_meta"]
        == generic["novelty_calibration_meta"]
        == {
            "total_questions": 1,
            "dimensions_covered": ["overall_combination"],
            "source": "candidate_cards_v1",
            "schema_version": "v1",
        }
    )
    assert compat["stage_timings"] == generic["stage_timings"]


def test_hypothesis_hot_load_research_mcp_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    captured: dict[str, object] = {}

    def fake_kg_hypothesis_candidate_cards(**kwargs):
        captured["kwargs"] = dict(kwargs)
        return {
            "ok": True,
            "result": {
                "query": "attention control",
                "resolved_anchor_bundle": [
                    {
                        "kg_id": "concept:attention",
                        "label": "Attention",
                        "node_type": "Concept",
                    },
                    {
                        "kg_id": "task:selective_attention",
                        "label": "Selective attention",
                        "node_type": "Task",
                    },
                ],
                "candidate_cards": [
                    {
                        "card_id": "cand_01",
                        "title": "Attention control candidate",
                        "kg_verification": {
                            "verdict": "uncertain",
                            "evidence_source_scope": "hybrid_kg_literature",
                        },
                        "grounding_status": "grounded",
                    },
                    {
                        "card_id": "cand_02",
                        "title": "Attention conflict candidate",
                        "kg_verification": {
                            "verdict": "insufficient_evidence",
                            "evidence_source_scope": "kg_only",
                        },
                        "grounding_status": "degraded",
                    },
                ],
                "summary": {
                    "n_candidate_cards": 2,
                    "n_grounded_cards": 1,
                    "n_degraded_cards": 1,
                    "candidate_lane_mode": "strict",
                    "deep_research_requested": True,
                },
                "workflow": {"workflow_id": "workflow_hypothesis_candidate_cards"},
                "deep_research": {"status": "ok"},
                "warnings": ["deep_research_warning"],
            },
        }

    monkeypatch.setattr(
        srv, "kg_hypothesis_candidate_cards", fake_kg_hypothesis_candidate_cards
    )

    resp = srv.hypothesis_hot_load_research(
        query="attention control",
        max_cards=2,
        depth="deep",
        candidate_lane_mode="strict",
        seed_kg_ids=["concept:attention"],
        exclude_domains=["example.com"],
    )

    assert resp["ok"] is True
    assert captured["kwargs"] == {
        "query": "attention control",
        "seed_kg_ids": ["concept:attention"],
        "top_n": 2,
        "top_k": 30,
        "taste_mode": "balanced",
        "controller_mode": "principle_v0",
        "candidate_lane_mode": "strict",
        "with_deep_research": True,
        "recency_days": 730,
        "exclude_domains": ["example.com"],
    }
    assert resp["result"]["status"] == "completed"
    assert resp["result"]["mode"] == "sync"
    assert resp["result"]["depth"] == "deep"
    assert resp["result"]["research_profile"] == {
        "top_k": 30,
        "deep_research_requested": True,
        "recency_days": 730,
        "candidate_lane_mode": "strict",
    }
    assert resp["result"]["summary"] == {
        "n_candidate_cards": 2,
        "n_grounded_cards": 1,
        "n_degraded_cards": 1,
        "candidate_lane_mode": "strict",
        "deep_research_requested": True,
        "depth": "deep",
        "top_anchor_labels": ["Attention", "Selective attention"],
        "n_resolved_anchors": 2,
        "verdict_counts": {
            "uncertain": 1,
            "insufficient_evidence": 1,
        },
        "evidence_source_scope_counts": {
            "hybrid_kg_literature": 1,
            "kg_only": 1,
        },
        "gap_type_counts": {},
        "deep_research_status": "ok",
    }
    assert resp["result"]["next_actions"] == [
        "Inspect grounded candidate cards first and choose one minimal test.",
        "Review degraded cards for missing evidence before promoting any idea.",
    ]
    assert resp["result"]["warnings"] == ["deep_research_warning"]


def test_hypothesis_hot_load_research_mcp_validation_error():
    from brain_researcher.services.mcp import server as srv

    assert srv.hypothesis_hot_load_research(query="") == {
        "ok": False,
        "error": "query is required",
    }
    assert srv.hypothesis_hot_load_research(query="attention", max_cards="abc") == {
        "ok": False,
        "error": "max_cards must be an integer",
    }
    assert srv.hypothesis_hot_load_research(query="attention", max_cards=0) == {
        "ok": False,
        "error": "max_cards must be >= 1",
    }
    assert srv.hypothesis_hot_load_research(query="attention", depth="wide") == {
        "ok": False,
        "error": "depth must be one of: shallow, balanced, deep",
    }


def test_hypothesis_run_start_and_get_success(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    captured: dict[str, object] = {}

    def fake_execute(request):
        captured["request"] = dict(request)
        return {
            "ok": True,
            "result": {
                "query": request["query"],
                "status": "completed",
                "mode": "sync",
                "depth": request["depth"],
                "research_profile": {
                    "top_k": request["profile"]["top_k"],
                    "deep_research_requested": request["profile"]["with_deep_research"],
                    "recency_days": request["profile"]["recency_days"],
                    "candidate_lane_mode": request["candidate_lane_mode"],
                },
                "resolved_anchor_bundle": [
                    {
                        "kg_id": "concept:attention",
                        "label": "Attention",
                        "node_type": "Concept",
                    }
                ],
                "candidate_cards": [
                    {
                        "card_id": "cand_01",
                        "kg_verification": {
                            "verdict": "uncertain",
                            "evidence_source_scope": "external_literature",
                        },
                        "grounding_status": "grounded",
                    }
                ],
                "summary": {
                    "n_candidate_cards": 1,
                    "n_grounded_cards": 1,
                    "n_degraded_cards": 0,
                    "candidate_lane_mode": request["candidate_lane_mode"],
                    "deep_research_requested": request["profile"]["with_deep_research"],
                    "depth": request["depth"],
                    "top_anchor_labels": ["Attention"],
                    "n_resolved_anchors": 1,
                    "verdict_counts": {"uncertain": 1},
                    "evidence_source_scope_counts": {"external_literature": 1},
                    "gap_type_counts": {},
                    "deep_research_status": "ok",
                },
                "next_actions": ["Inspect grounded candidate cards first."],
                "workflow": {"workflow_id": "workflow_hypothesis_candidate_cards"},
                "deep_research": {"status": "ok"},
            },
        }

    monkeypatch.setattr(srv, "_execute_hypothesis_hot_load_request", fake_execute)

    resp = srv.hypothesis_run_start(
        query="attention control",
        max_cards=2,
        depth="balanced",
        candidate_lane_mode="strict",
        seed_kg_ids=["concept:attention"],
        exclude_domains=["example.com"],
    )

    assert resp["ok"] is True
    assert resp["status"] == "queued"
    assert resp["execution_mode"] == "background"
    assert resp["execution_trace"] == ["validated", "queued_background_run"]
    assert resp["poll_tool"] == "run_get"
    assert resp["compat_poll_tool"] == "hypothesis_run_get"
    run_id = resp["run_id"]

    deadline = time.time() + 5.0
    result = None
    status = None
    while time.time() < deadline:
        result = srv.run_get(run_id)
        assert result["ok"] is True
        status = result["status"]
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.05)

    assert status == "succeeded"
    assert captured["request"] == {
        "query": "attention control",
        "max_cards": 2,
        "depth": "balanced",
        "candidate_lane_mode": "strict",
        "seed_kg_ids": ["concept:attention"],
        "exclude_domains": ["example.com"],
        "profile": {
            "top_k": 20,
            "with_deep_research": True,
            "recency_days": 365,
        },
    }
    assert result["summary"] == {
        "n_candidate_cards": 1,
        "n_grounded_cards": 1,
        "n_degraded_cards": 0,
        "candidate_lane_mode": "strict",
        "deep_research_requested": True,
        "depth": "balanced",
        "top_anchor_labels": ["Attention"],
        "n_resolved_anchors": 1,
        "verdict_counts": {"uncertain": 1},
        "evidence_source_scope_counts": {"external_literature": 1},
        "gap_type_counts": {},
        "deep_research_status": "ok",
    }
    assert result["result"]["deep_research"]["status"] == "ok"
    assert result["run"]["steps"][0]["tool_id"] == "hypothesis_hot_load_research"
    assert result["run"]["steps"][0]["result_path"] == (
        "artifacts/hypothesis_hot_load.result.json"
    )
    assert result["progress"]["stalled"] is False
    assert result["progress"]["current_stage"] == "completed"
    assert result["progress"]["message"] == "Hot-load hypothesis research completed"
    assert result["progress"]["timing_policy"]["stall_timeout_seconds"] >= 30


def test_hypothesis_run_start_preserves_frontier_mode_when_requested(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    captured: dict[str, object] = {}

    def fake_execute(request):
        captured["request"] = dict(request)
        return {
            "ok": True,
            "result": {
                "query": request["query"],
                "status": "completed",
                "mode": "sync",
                "depth": request["depth"],
                "research_profile": {
                    "top_k": request["profile"]["top_k"],
                    "deep_research_requested": request["profile"]["with_deep_research"],
                    "recency_days": request["profile"]["recency_days"],
                    "candidate_lane_mode": request["candidate_lane_mode"],
                    "frontier_mode": request["frontier_mode"],
                },
                "resolved_anchor_bundle": [],
                "candidate_cards": [],
                "summary": {
                    "n_candidate_cards": 0,
                    "n_grounded_cards": 0,
                    "n_degraded_cards": 0,
                    "candidate_lane_mode": request["candidate_lane_mode"],
                    "deep_research_requested": request["profile"]["with_deep_research"],
                    "depth": request["depth"],
                    "top_anchor_labels": [],
                    "n_resolved_anchors": 0,
                    "verdict_counts": {},
                    "evidence_source_scope_counts": {},
                    "deep_research_status": None,
                },
                "next_actions": [
                    "Retry with a narrower query or provide manual seed_kg_ids."
                ],
                "workflow": {"workflow_id": "workflow_hypothesis_candidate_cards"},
            },
        }

    monkeypatch.setattr(srv, "_execute_hypothesis_hot_load_request", fake_execute)

    resp = srv.hypothesis_run_start(
        query="attention control",
        frontier_mode="frontier",
    )

    assert resp["ok"] is True
    run_id = resp["run_id"]

    deadline = time.time() + 5.0
    status = None
    while time.time() < deadline:
        result = srv.run_get(run_id)
        assert result["ok"] is True
        status = result["status"]
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.05)

    assert status == "succeeded"
    assert captured["request"]["frontier_mode"] == "frontier"
    assert result["result"]["research_profile"]["frontier_mode"] == "frontier"


def test_hypothesis_run_start_background_failure(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    def fake_execute(request):
        del request
        return {"ok": False, "error": "downstream_failed"}

    monkeypatch.setattr(srv, "_execute_hypothesis_hot_load_request", fake_execute)

    resp = srv.hypothesis_run_start(query="attention control")
    assert resp["ok"] is True
    run_id = resp["run_id"]

    deadline = time.time() + 5.0
    result = None
    status = None
    while time.time() < deadline:
        result = srv.run_get(run_id)
        assert result["ok"] is True
        status = result["status"]
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.05)

    assert status == "failed"
    assert result["run"]["error"] == "downstream_failed"
    assert "result" not in result
    assert result["progress"]["current_stage"] == "failed"
    assert result["progress"]["message"] == "downstream_failed"


def test_hypothesis_run_start_validation_error(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    assert srv.hypothesis_run_start(query="") == {
        "ok": False,
        "error": "query is required",
    }
    assert srv.hypothesis_run_start(query="attention", max_cards="abc") == {
        "ok": False,
        "error": "max_cards must be an integer",
    }
    assert srv.hypothesis_run_start(query="attention", max_cards=0) == {
        "ok": False,
        "error": "max_cards must be >= 1",
    }
    assert srv.hypothesis_run_start(query="attention", depth="wide") == {
        "ok": False,
        "error": "depth must be one of: shallow, balanced, deep",
    }
    monkeypatch.setattr(srv, "_proxy_agent_run_status", lambda run_id: None)
    missing = srv.hypothesis_run_get("missing_run")
    assert missing["ok"] is False
    assert "run not found" in missing["error"]


def test_hypothesis_run_get_compat_alias_matches_run_get(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()
    run_id = "hypothesis_alias_run"
    run_dir = tmp_path / "runs" / run_id
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "created_at": "2026-01-01T00:00:00Z",
                "status": "succeeded",
                "dry_run": False,
                "steps": [
                    {
                        "step_id": "hypothesis_hot_load",
                        "tool_id": "hypothesis_hot_load_research",
                        "status": "succeeded",
                        "result_path": "artifacts/hypothesis_hot_load.result.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "artifacts" / "hypothesis_hot_load.result.json").write_text(
        json.dumps(
            {
                "query": "attention control",
                "summary": {"n_candidate_cards": 1},
                "warnings": ["deep_research_warning"],
            }
        ),
        encoding="utf-8",
    )

    compat = srv.hypothesis_run_get(run_id)
    generic = srv.run_get(run_id)

    assert compat["ok"] is True
    assert compat["run_id"] == generic["run_id"] == run_id
    assert compat["status"] == generic["status"] == "succeeded"
    assert compat["done"] is True
    assert compat["summary"] == generic["summary"] == {"n_candidate_cards": 1}
    assert compat["warnings"] == generic["warnings"] == ["deep_research_warning"]


def test_kg_sample_and_verify_hypotheses_mcp_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_sample_and_verify_hypotheses(
        seed_kg_ids,
        *,
        query=None,
        relation_types=None,
        sample_limit=5,
        verify_top_k=None,
        taste=None,
        strictness="high_recall",
        allowed_node_types=None,
        max_evidence=60,
        max_paths=60,
        min_evidence_score=None,
        include_subgraph=False,
        include_path_details=False,
        confidence_scoring_version="v2",
        candidate_lane_mode="broad",
        use_external_literature=False,
        external_literature_top_k=5,
        external_literature_recency_days=365,
        external_literature_exclude_domains=None,
        db=None,
    ):
        del db
        captured["kwargs"] = {
            "seed_kg_ids": list(seed_kg_ids),
            "query": query,
            "relation_types": relation_types,
            "sample_limit": sample_limit,
            "verify_top_k": verify_top_k,
            "taste": taste,
            "strictness": strictness,
            "allowed_node_types": allowed_node_types,
            "max_evidence": max_evidence,
            "max_paths": max_paths,
            "min_evidence_score": min_evidence_score,
            "include_subgraph": include_subgraph,
            "include_path_details": include_path_details,
            "confidence_scoring_version": confidence_scoring_version,
            "candidate_lane_mode": candidate_lane_mode,
            "use_external_literature": use_external_literature,
            "external_literature_top_k": external_literature_top_k,
            "external_literature_recency_days": external_literature_recency_days,
            "external_literature_exclude_domains": external_literature_exclude_domains,
        }
        return {
            "sampled_hypotheses": [{"rank": 1, "statement": "H1"}],
            "tested_hypotheses": [
                {
                    "rank": 1,
                    "statement": "H1",
                    "kg_verification": {
                        "verdict": "insufficient_evidence",
                        "confidence": 0.38,
                        "evidence_mode": "union",
                        "evidence_source_scope": "expanded_family",
                        "summary": {
                            "evidence_scope": "union",
                            "evidence_source_scope": "expanded_family",
                        },
                    },
                }
            ],
            "summary": {"n_tested": 1, "n_insufficient_evidence": 1},
        }

    monkeypatch.setattr(
        _query_service,
        "sample_and_verify_hypotheses",
        fake_sample_and_verify_hypotheses,
        raising=False,
    )

    resp = srv.kg_sample_and_verify_hypotheses(
        seed_kg_ids=["node:seed"],
        n_samples=3,
        verify_top_k=2,
        max_hops=3,
        strategy="evidence_first",
        strictness="conservative",
        candidate_lane_mode="strict",
        allowed_node_types=["Task", "Concept"],
        include_subgraph=True,
    )

    assert resp["ok"] is True
    assert resp["result"]["sampled_hypotheses"] == [{"rank": 1, "statement": "H1"}]
    assert resp["result"]["tested_hypotheses"][0]["kg_verification"] == {
        "verdict": "insufficient_evidence",
        "confidence": 0.38,
        "evidence_mode": "union",
        "evidence_source_scope": "expanded_family",
        "summary": {
            "evidence_scope": "union",
            "evidence_source_scope": "expanded_family",
        },
    }
    assert captured["kwargs"] == {
        "seed_kg_ids": ["node:seed"],
        "query": None,
        "relation_types": None,
        "sample_limit": 3,
        "verify_top_k": 2,
        "taste": {"mode": "evidence_first"},
        "strictness": "conservative",
        "allowed_node_types": ["Task", "Concept"],
        "max_evidence": 60,
        "max_paths": 60,
        "min_evidence_score": None,
        "include_subgraph": True,
        "include_path_details": False,
        "confidence_scoring_version": "v2",
        "candidate_lane_mode": "strict",
        "use_external_literature": False,
        "external_literature_top_k": 5,
        "external_literature_recency_days": 365,
        "external_literature_exclude_domains": None,
    }
    assert "max_hops is currently informational" in " ".join(
        resp["result"].get("warnings", [])
    )


def test_kg_sample_and_verify_hypotheses_mcp_validation_error():
    from brain_researcher.services.mcp import server as srv

    resp = srv.kg_sample_and_verify_hypotheses(seed_kg_ids=[])
    assert resp == {"ok": False, "error": "seed_kg_ids is required"}


def test_kg_verify_sampled_hypotheses_mcp_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_verify_sampled_hypotheses(
        sampled_hypotheses,
        *,
        query=None,
        seed_kg_ids=None,
        verify_top_k=None,
        strictness="high_recall",
        allowed_node_types=None,
        max_evidence=60,
        max_paths=60,
        min_evidence_score=None,
        include_subgraph=False,
        include_path_details=False,
        confidence_scoring_version="v2",
        candidate_lane_mode="broad",
        use_external_literature=False,
        external_literature_top_k=5,
        external_literature_recency_days=365,
        external_literature_exclude_domains=None,
        db=None,
    ):
        del db
        captured["kwargs"] = {
            "sampled_hypotheses": sampled_hypotheses,
            "query": query,
            "seed_kg_ids": seed_kg_ids,
            "verify_top_k": verify_top_k,
            "strictness": strictness,
            "allowed_node_types": allowed_node_types,
            "max_evidence": max_evidence,
            "max_paths": max_paths,
            "min_evidence_score": min_evidence_score,
            "include_subgraph": include_subgraph,
            "include_path_details": include_path_details,
            "confidence_scoring_version": confidence_scoring_version,
            "candidate_lane_mode": candidate_lane_mode,
            "use_external_literature": use_external_literature,
            "external_literature_top_k": external_literature_top_k,
            "external_literature_recency_days": external_literature_recency_days,
            "external_literature_exclude_domains": external_literature_exclude_domains,
        }
        return {
            "tested_hypotheses": [
                {
                    "rank": 1,
                    "candidate_kg_id": "node:candidate",
                    "kg_verification": {
                        "verdict": "supported",
                        "confidence": 0.61,
                        "evidence_mode": "shared",
                        "evidence_source_scope": "direct",
                    },
                }
            ],
            "summary": {"n_tested": 1, "n_supported": 1},
        }

    monkeypatch.setattr(
        _query_service,
        "verify_sampled_hypotheses",
        fake_verify_sampled_hypotheses,
        raising=False,
    )

    resp = srv.kg_verify_sampled_hypotheses(
        sampled_hypotheses=[{"rank": 1, "statement": "H1"}],
        seed_kg_ids=["node:seed"],
        verify_top_k=1,
        strictness="conservative",
        candidate_lane_mode="strict",
        allowed_node_types=["Task"],
        include_subgraph=True,
    )

    assert resp["ok"] is True
    assert resp["result"]["summary"] == {"n_tested": 1, "n_supported": 1}
    assert resp["result"]["tested_hypotheses"][0]["kg_verification"]["verdict"] == (
        "supported"
    )
    assert captured["kwargs"] == {
        "sampled_hypotheses": [{"rank": 1, "statement": "H1"}],
        "query": None,
        "seed_kg_ids": ["node:seed"],
        "verify_top_k": 1,
        "strictness": "conservative",
        "allowed_node_types": ["Task"],
        "max_evidence": 60,
        "max_paths": 60,
        "min_evidence_score": None,
        "include_subgraph": True,
        "include_path_details": False,
        "confidence_scoring_version": "v2",
        "candidate_lane_mode": "strict",
        "use_external_literature": False,
        "external_literature_top_k": 5,
        "external_literature_recency_days": 365,
        "external_literature_exclude_domains": None,
    }


def test_kg_verify_sampled_hypotheses_mcp_validation_error():
    from brain_researcher.services.mcp import server as srv

    resp = srv.kg_verify_sampled_hypotheses(sampled_hypotheses=[])
    assert resp == {"ok": False, "error": "sampled_hypotheses is required"}


def test_kg_detect_topology_shifts_mcp_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_detect_topology_shifts(
        seed_kg_ids=None,
        *,
        limit=50,
        taste=None,
        mode="proposal",
        patch_id=None,
        update_reason=None,
        now_iso=None,
    ):
        captured["kwargs"] = {
            "seed_kg_ids": seed_kg_ids,
            "limit": limit,
            "taste": taste,
            "mode": mode,
            "patch_id": patch_id,
            "update_reason": update_reason,
            "now_iso": now_iso,
        }
        return {"shift_count": 3, "mode": mode}

    monkeypatch.setattr(
        _query_service,
        "detect_topology_shifts",
        fake_detect_topology_shifts,
        raising=False,
    )

    resp = srv.kg_detect_topology_shifts(
        mode="detect",
        baseline_ref="snapshot:v1",
        current_ref="snapshot:v2",
        scope="dataset",
    )

    assert resp["ok"] is True
    assert resp["result"] == {"shift_count": 3, "mode": "proposal"}
    assert captured["kwargs"] == {
        "seed_kg_ids": None,
        "limit": 50,
        "taste": None,
        "mode": "proposal",
        "patch_id": None,
        "update_reason": "baseline=snapshot:v1;current=snapshot:v2;scope=dataset",
        "now_iso": None,
    }


def test_kg_detect_topology_shifts_mcp_apply_success(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    captured: dict[str, object] = {}

    def fake_detect_topology_shifts(**kwargs):
        captured["kwargs"] = kwargs
        return {"applied": True}

    monkeypatch.setattr(
        _query_service,
        "detect_topology_shifts",
        fake_detect_topology_shifts,
        raising=False,
    )
    monkeypatch.setenv("BR_KG_TOPOLOGY_WRITE_ENABLED", "1")
    monkeypatch.setenv("BR_MCP_ALLOW_DANGEROUS", "1")

    resp = srv.kg_detect_topology_shifts(
        mode="apply",
        approval_phrase="I_UNDERSTAND_WRITE_RISK",
    )

    assert resp["ok"] is True
    assert resp["result"] == {"applied": True}
    assert captured["kwargs"] == {"mode": "apply"}


@pytest.mark.parametrize(
    ("topology_write", "allow_dangerous", "approval_phrase"),
    [
        ("0", "1", "I_UNDERSTAND_WRITE_RISK"),
        ("1", "0", "I_UNDERSTAND_WRITE_RISK"),
        ("1", "1", "wrong"),
    ],
)
def test_kg_detect_topology_shifts_mcp_policy_rejected_apply(
    monkeypatch, topology_write, allow_dangerous, approval_phrase
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.neurokg import query_service as _query_service

    called = {"count": 0}

    def fake_detect_topology_shifts(**kwargs):
        called["count"] += 1
        return {"unexpected": True}

    monkeypatch.setattr(
        _query_service,
        "detect_topology_shifts",
        fake_detect_topology_shifts,
        raising=False,
    )
    monkeypatch.setenv("BR_KG_TOPOLOGY_WRITE_ENABLED", topology_write)
    monkeypatch.setenv("BR_MCP_ALLOW_DANGEROUS", allow_dangerous)

    resp = srv.kg_detect_topology_shifts(
        mode="apply",
        approval_phrase=approval_phrase,
    )

    assert resp == {"ok": False, "error": "policy_rejected"}
    assert called["count"] == 0


def test_kg_detect_topology_shifts_mcp_validation_error():
    from brain_researcher.services.mcp import server as srv

    resp = srv.kg_detect_topology_shifts(mode="invalid")
    assert resp == {"ok": False, "error": "mode must be one of: detect, apply"}


def test_doc_examples_are_valid(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    # Stub KG search/get to validate ID round-trip fields.
    def fake_search_nodes(query, node_types=None, limit=20):
        from brain_researcher.services.neurokg.query_service import KGNodeSummary

        return [
            KGNodeSummary(
                kg_id="CONCEPT_001",
                element_id="4:abcd-ef01:1",
                label="motor cortex",
                node_type="Concept",
                score=1.0,
                properties={"id": "CONCEPT_001"},
            )
        ]

    def fake_node_details(kg_id):
        from brain_researcher.services.neurokg.query_service import KGNodeSummary

        if kg_id in {"CONCEPT_001", "4:abcd-ef01:1"}:
            return KGNodeSummary(
                kg_id="CONCEPT_001",
                element_id="4:abcd-ef01:1",
                label="motor cortex",
                node_type="Concept",
                score=1.0,
                properties={"id": "CONCEPT_001"},
            )
        return None

    from brain_researcher.services.neurokg import query_service as _query_service

    monkeypatch.setattr(_query_service, "search_nodes", fake_search_nodes)
    monkeypatch.setattr(_query_service, "node_details", fake_node_details)

    doc_path = Path(__file__).resolve().parents[3] / "docs" / "mcp_tools.schema.json"
    doc = json.loads(doc_path.read_text())

    examples = {}
    for tool in doc.get("tools", []):
        tested = [ex for ex in tool.get("examples", []) if ex.get("tested")]
        if tested:
            examples[tool["name"]] = tested
    handled_tools = set()

    # Prepare state for artifact_read_bytes example.
    for example in examples.get("artifact_read_bytes", []):
        handled_tools.add("artifact_read_bytes")
        run_id = example["input"]["run_id"]
        relpath = example["input"]["relpath"]
        run_dir = tmp_path / "runs" / run_id
        target = run_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"abcdef")

        blob = srv.artifact_read_bytes(**example["input"])
        assert blob == example["output"]

    # Prepare state for run_metrics example.
    for example in examples.get("run_metrics", []):
        handled_tools.add("run_metrics")
        run_id = example["input"]["run_id"]
        metrics_dir = tmp_path / "runs" / run_id
        (metrics_dir / "logs").mkdir(parents=True, exist_ok=True)
        (metrics_dir / "work").mkdir(parents=True, exist_ok=True)
        (metrics_dir / "artifacts").mkdir(parents=True, exist_ok=True)

        log_payload = {
            "status": "success",
            "data": {"execution_time": 1.5},
            "metadata": {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.02},
        }
        (metrics_dir / "logs" / "step-01-s1.json").write_text(json.dumps(log_payload))
        run_payload = {
            "run_id": run_id,
            "created_at": example["output"]["metrics"]["started_at"],
            "status": example["output"]["metrics"]["status"],
            "dry_run": False,
            "started_at": example["output"]["metrics"]["started_at"],
            "finished_at": example["output"]["metrics"]["finished_at"],
            "steps": [
                {
                    "step_id": "s1",
                    "tool_id": "extract_timeseries",
                    "params": {},
                    "status": "succeeded",
                    "started_at": example["output"]["metrics"]["started_at"],
                    "finished_at": example["output"]["metrics"]["finished_at"],
                    "result_path": "logs/step-01-s1.json",
                }
            ],
            "error": None,
        }
        (metrics_dir / "run.json").write_text(json.dumps(run_payload))

        metrics = srv.run_metrics(run_id)
        assert metrics == example["output"]

    # Prepare state for run_cancel example.
    for example in examples.get("run_cancel", []):
        handled_tools.add("run_cancel")
        run_id = example["input"]["run_id"]
        run_dir = tmp_path / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        cancel_payload = {
            "run_id": run_id,
            "created_at": "2025-12-20T00:00:00Z",
            "status": "queued",
            "dry_run": False,
            "steps": [{"step_id": "s1", "tool_id": "extract_timeseries"}],
        }
        (run_dir / "run.json").write_text(json.dumps(cancel_payload))

        cancelled = srv.run_cancel(**example["input"])
        assert cancelled == example["output"]

    # Prepare state for kg_neighbors example (stubbed).
    for example in examples.get("kg_neighbors", []):
        handled_tools.add("kg_neighbors")

        def fake_neighbors(
            kg_id,
            relation_types=None,
            direction="both",
            limit=25,
            _items=example["output"]["items"],
        ):
            return _items

        from brain_researcher.services.neurokg import query_service as _query_service

        monkeypatch.setattr(_query_service, "neighbors", fake_neighbors)
        neighbors = srv.kg_neighbors(**example["input"])
        assert neighbors == example["output"]

    unsupported = set(examples) - handled_tools
    assert not unsupported, f"tested examples not validated: {sorted(unsupported)}"
