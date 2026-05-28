from __future__ import annotations

import sys
import types


def test_resolve_python_tool_instance_from_module_prefers_matching_name():
    from pydantic import BaseModel, Field

    from brain_researcher.services.tools.executor import _resolve_python_tool_instance
    from brain_researcher.services.tools.spec import ToolSpec
    from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

    module_name = "br_test_dummy_tools_mod"
    mod = types.ModuleType(module_name)

    class Args(BaseModel):
        x: int = Field(..., description="x")

    class ToolA(NeuroToolWrapper):
        name = "dummy.a"

        def get_tool_name(self) -> str:
            return "dummy.a"

        def get_tool_description(self) -> str:
            return "A"

        def get_args_schema(self):
            return Args

        def _run(self, **kwargs) -> ToolResult:
            return ToolResult(status="success", data={"x": kwargs.get("x")})

    class ToolB(NeuroToolWrapper):
        name = "dummy.b"

        def get_tool_name(self) -> str:
            return "dummy.b"

        def get_tool_description(self) -> str:
            return "B"

        def get_args_schema(self):
            return Args

        def _run(self, **kwargs) -> ToolResult:
            return ToolResult(status="success", data={"x": kwargs.get("x")})

    mod.ToolA = ToolA
    mod.ToolB = ToolB
    sys.modules[module_name] = mod

    spec = ToolSpec(
        name="dummy.a",
        description="",
        backend="python",
        python_class=module_name,
        json_schema={},
    )
    tool = _resolve_python_tool_instance(spec)
    assert tool is not None
    assert tool.get_tool_name() == "dummy.a"


def test_resolve_python_tool_instance_uses_get_all_tools_factory():
    from pydantic import BaseModel, Field

    from brain_researcher.services.tools.executor import _resolve_python_tool_instance
    from brain_researcher.services.tools.spec import ToolSpec
    from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

    module_name = "br_test_dummy_tools_factory"
    mod = types.ModuleType(module_name)

    class Args(BaseModel):
        x: int = Field(..., description="x")

    class ToolC(NeuroToolWrapper):
        def get_tool_name(self) -> str:
            return "dummy.c"

        def get_tool_description(self) -> str:
            return "C"

        def get_args_schema(self):
            return Args

        def _run(self, **kwargs) -> ToolResult:
            return ToolResult(status="success", data={"x": kwargs.get("x")})

    def get_all_tools():
        return [ToolC()]

    mod.get_all_tools = get_all_tools
    sys.modules[module_name] = mod

    spec = ToolSpec(
        name="dummy.c",
        description="",
        backend="python",
        python_class=module_name,
        json_schema={},
    )
    tool = _resolve_python_tool_instance(spec)
    assert tool is not None
    assert tool.get_tool_name() == "dummy.c"


def test_resolve_python_tool_instance_supports_grandmaster_loader_bridge(
    monkeypatch,
):
    from pydantic import BaseModel, Field

    from brain_researcher.services.tools.executor import _resolve_python_tool_instance
    from brain_researcher.services.tools.grandmaster import loader as gm_loader
    from brain_researcher.services.tools.spec import ToolSpec
    from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

    class Args(BaseModel):
        bids_dir: str = Field(..., description="BIDS root")

    class MRIQCBridgeTool(NeuroToolWrapper):
        def get_tool_name(self) -> str:
            return "run_mriqc_workflow"

        def get_tool_description(self) -> str:
            return "MRIQC bridge"

        def get_args_schema(self):
            return Args

        def _run(self, **kwargs) -> ToolResult:
            return ToolResult(status="success", data={"bids_dir": kwargs.get("bids_dir")})

    class UnrelatedTool(NeuroToolWrapper):
        def get_tool_name(self) -> str:
            return "other_tool"

        def get_tool_description(self) -> str:
            return "Other"

        def get_args_schema(self):
            return Args

        def _run(self, **kwargs) -> ToolResult:
            return ToolResult(status="success", data={"ignored": True})

    class FakeRegistry:
        def get_tool(self, tool_id: str):
            if tool_id == "run_mriqc_workflow":
                return MRIQCBridgeTool()
            if tool_id == "other_tool":
                return UnrelatedTool()
            return None

    gm_loader._bridge_runtime_registry.cache_clear()
    monkeypatch.setattr(gm_loader, "_bridge_runtime_registry", lambda: FakeRegistry())
    monkeypatch.setattr(gm_loader, "_bridge_tool_ids", lambda: ("run_mriqc_workflow", "other_tool"))

    spec = ToolSpec(
        name="run_mriqc_workflow",
        description="",
        backend="python",
        python_class="brain_researcher.services.tools.grandmaster.loader",
        json_schema={},
    )
    tool = _resolve_python_tool_instance(spec)
    assert tool is not None
    assert tool.get_tool_name() == "run_mriqc_workflow"


def test_resolve_python_tool_instance_supports_ibl_tool_module():
    from brain_researcher.services.tools.executor import _resolve_python_tool_instance
    from brain_researcher.services.tools.spec import ToolSpec

    spec = ToolSpec(
        name="ibl_one",
        description="",
        backend="python",
        python_class="brain_researcher.services.tools.ibl_tools",
        json_schema={},
    )
    tool = _resolve_python_tool_instance(spec)
    assert tool is not None
    assert tool.get_tool_name() == "ibl_one"


def test_resolve_python_tool_instance_supports_ibl_neuropixels_workflow_tool():
    from brain_researcher.services.tools.executor import _resolve_python_tool_instance
    from brain_researcher.services.tools.spec import ToolSpec

    spec = ToolSpec(
        name="ibl_neuropixels_workflow",
        description="",
        backend="python",
        python_class="brain_researcher.services.tools.ibl_tools",
        json_schema={},
    )
    tool = _resolve_python_tool_instance(spec)
    assert tool is not None
    assert tool.get_tool_name() == "ibl_neuropixels_workflow"
