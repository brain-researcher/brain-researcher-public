"""Tests for agent tool allowlist loading and registry pruning."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from brain_researcher.services.agent.tool_allowlist_loader import (
    expand_plan_tool_ids,
    filter_local_first_tool_ids,
    is_local_first_blocked_tool,
    load_chat_tools_allowlist,
    resolve_plan_tool_allowlist,
    resolve_runtime_tool_allowlist,
)


_CANONICAL_RUNTIME_TOOL_ID_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def _assert_canonical_runtime_tool_ids(tool_ids: list[str]) -> None:
    for tool_id in tool_ids:
        normalized = str(tool_id or "").strip()
        assert normalized
        assert ".run" not in normalized
        assert _CANONICAL_RUNTIME_TOOL_ID_RE.fullmatch(normalized), normalized


def test_load_chat_tools_allowlist_reads_yaml(tmp_path, monkeypatch):
    """Ensure chat_tools.yaml is parsed and local-first blocking is applied."""

    catalog_dir = tmp_path / "configs" / "catalog"
    catalog_dir.mkdir(parents=True)
    yaml_path = catalog_dir / "chat_tools.yaml"
    yaml_path.write_text(
        """
chat_tools:
  - gemini.fs
  - graph_query
  - code_agent
"""
    )

    # Point loader to the temp YAML
    monkeypatch.setenv("CHAT_TOOLS_PATH", str(yaml_path))
    tools = load_chat_tools_allowlist()
    assert tools == ["gemini.read_file", "graph_query"]


def test_load_chat_tools_allowlist_filters_blocked_execution_tools(
    tmp_path, monkeypatch
):
    catalog_dir = tmp_path / "configs" / "catalog"
    catalog_dir.mkdir(parents=True)
    yaml_path = catalog_dir / "chat_tools.yaml"
    yaml_path.write_text(
        """
chat_tools:
  - graph_query
  - workflow_rest_connectome_e2e
  - niwrap_execute
  - run_local_script
"""
    )

    monkeypatch.setenv("CHAT_TOOLS_PATH", str(yaml_path))
    tools = load_chat_tools_allowlist()
    assert tools == ["graph_query", "workflow_rest_connectome_e2e"]


def test_local_first_filter_blocks_known_execution_tools():
    assert is_local_first_blocked_tool("workflow_rest_connectome_e2e") is False
    assert is_local_first_blocked_tool("fetch_atlas") is False
    assert is_local_first_blocked_tool("extract_timeseries") is False
    assert is_local_first_blocked_tool("compute_connectivity") is False
    assert is_local_first_blocked_tool("connectivity_matrix") is False
    assert is_local_first_blocked_tool("workflow_realtime_twophoton_closed_loop") is False
    assert is_local_first_blocked_tool("workflow_realtime_twophoton_file_replay") is False
    assert is_local_first_blocked_tool("niwrap_execute") is True
    assert is_local_first_blocked_tool("ants_registration") is True
    assert is_local_first_blocked_tool("fsl_bet") is True
    assert is_local_first_blocked_tool("glm_multiverse") is True
    assert is_local_first_blocked_tool("afni_3dReHo") is True
    assert is_local_first_blocked_tool("run_local_script") is True
    assert is_local_first_blocked_tool("run_glm_first_level") is True
    assert is_local_first_blocked_tool("run_suite2p") is True
    assert is_local_first_blocked_tool("run_spike_sorting") is True
    assert is_local_first_blocked_tool("code_agent") is True
    assert is_local_first_blocked_tool("bidsapp.fmriprep.run") is True
    assert is_local_first_blocked_tool("bidsapp.mriqc.run") is True
    assert is_local_first_blocked_tool("python.fmriprep.run") is True
    assert is_local_first_blocked_tool("fitlins.recipe.run") is True
    assert is_local_first_blocked_tool("container.fitlins.recipe.run") is True
    assert is_local_first_blocked_tool("gemini.run_shell") is True
    assert is_local_first_blocked_tool("run_fmriprep") is True
    assert is_local_first_blocked_tool("run_qsiprep") is True
    assert is_local_first_blocked_tool("run_mriqc") is True
    assert is_local_first_blocked_tool("run_xcp_d") is True
    assert is_local_first_blocked_tool("run_searchlight") is True
    assert is_local_first_blocked_tool("fsl.fslFixText") is True
    assert is_local_first_blocked_tool("niwrap_search") is False
    assert is_local_first_blocked_tool("niwrap_schema") is False
    assert is_local_first_blocked_tool("mcp.server_info") is False
    assert is_local_first_blocked_tool("graph_query") is False
    assert is_local_first_blocked_tool("kg_hypothesis_candidate_cards") is False
    assert is_local_first_blocked_tool("kg_hypothesis_candidate_cards_start") is False
    assert is_local_first_blocked_tool("kg_hypothesis_candidate_cards_get") is False
    assert is_local_first_blocked_tool("hypothesis_hot_load_research") is False
    assert is_local_first_blocked_tool("hypothesis_run_start") is False
    assert is_local_first_blocked_tool("hypothesis_run_get") is False

    filtered = filter_local_first_tool_ids(
        [
            "graph_query",
            "kg_hypothesis_candidate_cards",
            "hypothesis_hot_load_research",
            "niwrap_search",
            "niwrap_execute",
            "run_glm_first_level",
            "ants_registration",
            "workflow_rest_connectome_e2e",
            "fetch_atlas",
            "extract_timeseries",
            "compute_connectivity",
            "connectivity_matrix",
            "workflow_realtime_twophoton_closed_loop",
            "workflow_realtime_twophoton_file_replay",
            "bidsapp.fmriprep.run",
            "python.fmriprep.run",
            "fitlins.recipe.run",
            "code_agent",
            "gemini.run_shell",
            "run_fmriprep",
            "graph_query",
        ]
    )
    assert filtered == [
        "graph_query",
        "kg_hypothesis_candidate_cards",
        "hypothesis_hot_load_research",
        "niwrap_search",
        "workflow_rest_connectome_e2e",
        "fetch_atlas",
        "extract_timeseries",
        "compute_connectivity",
        "connectivity_matrix",
        "workflow_realtime_twophoton_closed_loop",
        "workflow_realtime_twophoton_file_replay",
    ]


def test_resolve_runtime_tool_allowlist_merges_and_filters(monkeypatch, tmp_path):
    yaml_path = tmp_path / "chat_tools.yaml"
    yaml_path.write_text(
        """
chat_tools:
  - kg_search_nodes
  - code_agent
  - datasets.describe_resources
"""
    )

    monkeypatch.setenv("CHAT_TOOLS_PATH", str(yaml_path))
    monkeypatch.setenv("AGENT_TOOL_ALLOWLIST_STRICT", "0")

    resolved = resolve_runtime_tool_allowlist(
        ["kg_search_nodes", "workflow_rest_connectome_e2e", "run_local_script"]
    )

    assert resolved == [
        "kg_search_nodes",
        "workflow_rest_connectome_e2e",
        "datasets.describe_resources",
    ]


@pytest.mark.parametrize(
    "env_list, strict_mode, expected",
    [
        ("a,b", False, ["a", "b", "yaml_tool"]),
        ("a,b", True, ["a", "b"]),
        ("", False, []),
        (None, False, ["yaml_tool"]),
    ],
)
def test_env_tool_allowlist_merge_behavior(
    monkeypatch, tmp_path, env_list, strict_mode, expected
):
    """Env allowlist merges with chat_tools by default; strict mode keeps env only."""

    # Minimal YAML fallback
    monkeypatch.setenv("PWD", "/")  # avoid chdir surprises
    monkeypatch.setenv("BRAIN_RESEARCHER_ENV", "test")

    from brain_researcher.services.agent import web_service as ws

    # Stub _agent_settings to control tool_allowlist directly (avoids cached get_settings)
    if env_list is None:
        stub = SimpleNamespace(tool_allowlist=None)
    else:
        parsed: list[str] = [t for t in env_list.split(",") if t]
        stub = SimpleNamespace(tool_allowlist=parsed)
    monkeypatch.setattr(ws, "_agent_settings", lambda: stub)

    # Provide a temp YAML path for fallback
    tmp_yaml = tmp_path / "chat_tools.yaml"
    tmp_yaml.write_text("chat_tools:\n  - yaml_tool\n")
    monkeypatch.setenv("CHAT_TOOLS_PATH", str(tmp_yaml))

    monkeypatch.setenv("AGENT_TOOL_ALLOWLIST_STRICT", "1" if strict_mode else "0")

    result = ws._env_tool_allowlist()
    assert result == expected


def test_env_tool_allowlist_filters_remote_execution_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("PWD", "/")
    monkeypatch.setenv("BRAIN_RESEARCHER_ENV", "test")

    from brain_researcher.services.agent import web_service as ws

    stub = SimpleNamespace(
        tool_allowlist=["graph_query", "niwrap_execute", "workflow_rest_connectome_e2e"]
    )
    monkeypatch.setattr(ws, "_agent_settings", lambda: stub)

    tmp_yaml = tmp_path / "chat_tools.yaml"
    tmp_yaml.write_text("chat_tools:\n  - datasets.describe_resources\n")
    monkeypatch.setenv("CHAT_TOOLS_PATH", str(tmp_yaml))
    monkeypatch.setenv("AGENT_TOOL_ALLOWLIST_STRICT", "0")
    monkeypatch.delenv("BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", raising=False)

    result = ws._env_tool_allowlist()
    assert result == [
        "graph_query",
        "workflow_rest_connectome_e2e",
        "datasets.describe_resources",
    ]


def test_resolve_runtime_tool_allowlist_filters_executor_style_ids(
    monkeypatch, tmp_path
):
    yaml_path = tmp_path / "chat_tools.yaml"
    yaml_path.write_text("chat_tools:\n  - datasets.describe_resources\n")

    monkeypatch.setenv("CHAT_TOOLS_PATH", str(yaml_path))
    monkeypatch.delenv("BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", raising=False)

    resolved = resolve_runtime_tool_allowlist(
        ["graph_query", "code_agent", "gemini.run_shell", "run_xcp_d"],
        strict=True,
    )

    assert resolved == ["graph_query"]


def test_resolve_plan_tool_allowlist_diagnostic_bypasses_chat_fallback(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_allowlist_loader.load_full_tool_allowlist",
        lambda include_workflows=True: ["fetch_atlas", "graph_query"],
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_allowlist_loader.resolve_runtime_tool_allowlist",
        lambda env_tool_allowlist, strict=None: ["chat_tool"],
    )

    resolved = resolve_plan_tool_allowlist(
        None,
        allowlist_mode="diagnostic",
    )

    assert resolved == ["fetch_atlas", "graph_query"]


def test_expand_plan_tool_ids_keeps_runtime_canonical_ids():
    expanded = expand_plan_tool_ids(
        ["fetch_atlas", "extract_timeseries", "fsl_bet", "graph_query"]
    )

    assert expanded == [
        "fetch_atlas",
        "extract_timeseries",
        "fsl_bet",
        "graph_query",
    ]


def test_expand_plan_tool_ids_canonicalizes_legacy_ids():
    expanded = expand_plan_tool_ids(
        ["python.searchlight_fmri.run", "cat12", "python.fetch_atlas.run"]
    )

    assert expanded == ["searchlight_analysis", "spm12_vbm", "fetch_atlas"]


def test_runtime_allowlist_returns_canonical_runtime_ids_only():
    resolved = resolve_runtime_tool_allowlist(
        ["python.searchlight_fmri.run", "cat12", "fsl.bet.run"],
        strict=True,
    )

    assert resolved == ["searchlight_analysis", "spm12_vbm"]
    assert "fsl_bet" not in resolved
    _assert_canonical_runtime_tool_ids(resolved)


def test_expand_plan_tool_ids_contract_outputs_canonical_names_only():
    expanded = expand_plan_tool_ids(
        [
            "python.searchlight_fmri.run",
            "fsl.bet.run",
            "ants.antsRegistration.run",
            "cat12",
        ]
    )

    assert expanded == [
        "searchlight_analysis",
        "fsl_bet",
        "ants_registration",
        "spm12_vbm",
    ]
    assert all(not tool_id.endswith(".run") for tool_id in expanded)


def test_resolve_runtime_tool_allowlist_allow_all_runtime_override(monkeypatch):
    monkeypatch.setenv("BR_AGENT_ALLOW_ALL_RUNTIME_TOOLS", "1")

    resolved = resolve_runtime_tool_allowlist(None)

    assert resolved is None


def test_chat_allowlist_covers_steps_for_allowlisted_workflows(monkeypatch):
    """If a workflow is allowlisted for chat, its runtime step tools must be allowlisted too."""

    monkeypatch.delenv("CHAT_TOOLS_PATH", raising=False)
    allowset = set(load_chat_tools_allowlist())

    repo_root = Path(__file__).resolve().parents[3]
    catalog_path = repo_root / "configs" / "workflows" / "workflow_catalog.yaml"
    data = yaml.safe_load(catalog_path.read_text()) or {}
    workflows = data.get("workflows") or []

    missing: dict[str, list[str]] = {}
    for workflow in workflows:
        workflow_id = str(workflow.get("id") or "").strip()
        if not workflow_id or workflow_id not in allowset:
            continue
        runtime = workflow.get("runtime") or {}
        for step in runtime.get("steps") or []:
            tool_id = str(step.get("tool") or "").strip()
            if tool_id and tool_id not in allowset:
                missing.setdefault(workflow_id, []).append(tool_id)

    assert not missing, (
        f"Allowlisted workflows have missing step tools in chat allowlist: {missing}"
    )


def test_chat_allowlist_includes_kg_multihop_qa(monkeypatch):
    """kg_multihop_qa must stay on the default chat tool surface."""

    monkeypatch.delenv("CHAT_TOOLS_PATH", raising=False)
    allowset = set(load_chat_tools_allowlist())

    assert "kg_multihop_qa" in allowset


def test_chat_allowlist_includes_dataset_describe_resources(monkeypatch):
    """datasets.describe_resources must stay on the default chat tool surface."""

    monkeypatch.delenv("CHAT_TOOLS_PATH", raising=False)
    allowset = set(load_chat_tools_allowlist())

    assert "datasets.describe_resources" in allowset


def test_chat_allowlist_includes_list_dataset_assets(monkeypatch):
    """list_dataset_assets should be exposed for browse-before-resolve flows."""

    monkeypatch.delenv("AGENT_TOOL_ALLOWLIST", raising=False)
    monkeypatch.delenv("AGENT_TOOL_ALLOWLIST_STRICT", raising=False)
    monkeypatch.delenv("BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", raising=False)
    allowset = set(load_chat_tools_allowlist())

    assert "list_dataset_assets" in allowset


def test_chat_allowlist_includes_hypothesis_hot_load_tools(monkeypatch):
    """Keep one high-level hypothesis entrypoint on the default chat surface."""

    monkeypatch.delenv("CHAT_TOOLS_PATH", raising=False)
    monkeypatch.delenv("AGENT_TOOL_ALLOWLIST", raising=False)
    monkeypatch.delenv("AGENT_TOOL_ALLOWLIST_STRICT", raising=False)
    monkeypatch.delenv("BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", raising=False)
    allowset = set(load_chat_tools_allowlist())

    assert "hypothesis_hot_load_research" in allowset


def test_chat_allowlist_stays_small_and_high_level(monkeypatch):
    """The default chat surface should stay intentionally small."""

    monkeypatch.delenv("CHAT_TOOLS_PATH", raising=False)
    monkeypatch.delenv("AGENT_TOOL_ALLOWLIST", raising=False)
    monkeypatch.delenv("AGENT_TOOL_ALLOWLIST_STRICT", raising=False)
    monkeypatch.delenv("BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", raising=False)

    tools = load_chat_tools_allowlist()

    assert len(tools) <= 20, tools


def test_chat_allowlist_excludes_rest_connectome_workflow_and_steps(monkeypatch):
    """Heavy workflow IDs and runtime steps should not be on the default chat surface."""

    monkeypatch.delenv("CHAT_TOOLS_PATH", raising=False)
    allowset = set(load_chat_tools_allowlist())

    blocked = {
        "workflow_rest_connectome_e2e",
        "fetch_atlas",
        "extract_timeseries",
        "compute_connectivity",
    }
    present = sorted(blocked & allowset)
    assert not present, f"Heavy default chat tools should be excluded: {present}"


def test_chat_allowlist_excludes_heavy_execution_tools(monkeypatch):
    """Default chat surface should stay query/control-plane only."""

    monkeypatch.delenv("CHAT_TOOLS_PATH", raising=False)
    allowset = set(load_chat_tools_allowlist())

    blocked = {
        "bidsapp.fmriprep.run",
        "fitlins.recipe.run",
        "niwrap_execute",
        "run_bids_app",
        "run_fitlins_recipe",
        "run_mriqc_workflow",
        "run_aslprep",
        "run_local_script",
        "run_tractography",
    }
    present = sorted(blocked & allowset)
    assert not present, f"Heavy execution tools should be excluded: {present}"


def test_chat_allowlist_excludes_low_level_support_and_ops_tools(monkeypatch):
    """Default chat surface should avoid low-level support and ops surfaces."""

    monkeypatch.delenv("CHAT_TOOLS_PATH", raising=False)
    monkeypatch.delenv("AGENT_TOOL_ALLOWLIST", raising=False)
    monkeypatch.delenv("AGENT_TOOL_ALLOWLIST_STRICT", raising=False)
    monkeypatch.delenv("BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", raising=False)
    allowset = set(load_chat_tools_allowlist())

    blocked = {
        "niwrap_search",
        "niwrap_schema",
        "mcp.server_info",
        "mcp.system_self_test",
        "mcp.sherlock_guide",
        "mcp.sherlock_slurm",
        "kg_hypothesis_candidate_cards",
        "kg_hypothesis_candidate_cards_start",
        "kg_hypothesis_candidate_cards_get",
        "hypothesis_run_start",
        "hypothesis_run_get",
    }
    present = sorted(blocked & allowset)
    assert not present, f"Low-level default chat tools should be excluded: {present}"
