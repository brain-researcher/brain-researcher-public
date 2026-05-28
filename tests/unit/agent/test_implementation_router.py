from dataclasses import asdict

import pytest

from brain_researcher.services.agent.planner.catalog_loader import (
    CapabilityIndex,
    ToolCapability,
)
from brain_researcher.services.agent.planner.implementation_router import (
    EnvContext,
    choose_tool_for_operation,
)
from brain_researcher.services.agent.planner.intents import Operation, Intent


def _fake_capability(id: str, runtime: str, intents=None) -> ToolCapability:
    return ToolCapability(
        id=id,
        name=id,
        package="test",
        runtime_kind=runtime,
        modality=["fmri"],
        capabilities=["glm_first_level"],
        intents=intents or [],
        consumes=["volume_4d"],
        produces=["stats_map"],
        resources={"cpu_min": 1, "mem_mb_min": 1024, "gpu": False, "time_min_default": 5},
        container=None,
        python=None,
        metadata=None,
        constraints={},
        source="test",
    )


def _build_index(*tools: ToolCapability) -> CapabilityIndex:
    idx = CapabilityIndex()
    for tool in tools:
        idx.by_id[tool.id] = tool
        for intent in tool.intents:
            idx.by_intent.setdefault(intent, []).append(tool.id)
    return idx


@pytest.fixture
def glm_operation():
    intent = Intent(
        id="glm_first_level_fmri",
        name="GLM First Level",
        description="",
        domains=["neuroimaging"],
        modalities=["fmri"],
        inputs=[],
        outputs=[],
        parents=[],
    )
    return Operation(op_id=intent.id, intent=intent)


def test_choose_tool_prefers_python(monkeypatch, glm_operation):
    py_tool = _fake_capability("python.nilearn_glm.run", "python", ["glm_first_level_fmri"])
    fsl_tool = _fake_capability("fsl.feat.run", "container", ["glm_first_level_fmri"])
    idx = _build_index(py_tool, fsl_tool)
    monkeypatch.setattr(
        "brain_researcher.services.agent.planner.implementation_router.search_by_intent",
        lambda _id: [py_tool, fsl_tool],
    )
    env = EnvContext(available_runtimes=["python", "container"], preferences={"prefer_runtime": "python"})
    chosen = choose_tool_for_operation(glm_operation, env)
    assert chosen.id == "python.nilearn_glm.run"


def test_choose_tool_falls_back_to_container(monkeypatch, glm_operation):
    fsl_tool = _fake_capability("fsl.feat.run", "container", ["glm_first_level_fmri"])
    monkeypatch.setattr(
        "brain_researcher.services.agent.planner.implementation_router.search_by_intent",
        lambda _id: [fsl_tool],
    )
    env = EnvContext(available_runtimes=["container"])
    chosen = choose_tool_for_operation(glm_operation, env)
    assert chosen.id == "fsl.feat.run"


def test_choose_tool_supports_mcp(monkeypatch, glm_operation):
    mcp_tool = _fake_capability("mcp.neurosynth_meta.run", "mcp", ["meta_analysis_cbma"])
    monkeypatch.setattr(
        "brain_researcher.services.agent.planner.implementation_router.search_by_intent",
        lambda _id: [mcp_tool],
    )
    op = Operation(op_id="meta_analysis_cbma", intent=Intent(
        id="meta_analysis_cbma", name="meta", description="", domains=["neuroimaging"], modalities=["fmri"],
        inputs=[], outputs=[], parents=[]))
    env = EnvContext(available_runtimes=["mcp"], preferences={"prefer_runtime": "mcp"})
    chosen = choose_tool_for_operation(op, env)
    assert chosen.id == "mcp.neurosynth_meta.run"
