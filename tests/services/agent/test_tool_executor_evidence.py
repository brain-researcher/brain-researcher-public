from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.services.agent.evidence_collection import (
    EvidenceCollector,
    EvidenceType,
)
from brain_researcher.services.agent.tool_executor import (
    ExecutionMode,
    ToolCategory,
    ToolExecutionRequest,
    ToolExecutor,
)
from brain_researcher.services.tools.tool_base import BRKGToolWrapper, ToolResult
from brain_researcher.services.tools.tool_registry import ToolRegistry


class _Args(BaseModel):
    value: int = Field(..., description="a value")


class FakeTool(BRKGToolWrapper):
    def get_tool_name(self) -> str:
        return "fake_tool"

    def get_tool_description(self) -> str:
        return "A simple fake tool"

    def get_args_schema(self) -> type[BaseModel]:
        return _Args

    def _run(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", data={"echo": kwargs, "version": "0.1.0"})


def test_tool_executor_records_evidence(tmp_path: Path):
    reg = ToolRegistry(auto_discover=False)
    reg.register_tool(FakeTool())
    collector = EvidenceCollector(storage_path=tmp_path, auto_persist=False)
    collector.clear()
    exec = ToolExecutor(
        tool_registry=reg,
        enable_caching=False,
        safe_mode=True,
        evidence_collector=collector,
    )

    req = ToolExecutionRequest(
        tool_name="fake_tool",
        parameters={"value": 42},
        mode=ExecutionMode.API_CALL,
        category=ToolCategory.DATA_PROCESSING,
    )
    res = exec.execute(req)
    assert res.status == "success"

    tools = collector.get_evidence_by_type(EvidenceType.TOOL)
    params = collector.get_evidence_by_type(EvidenceType.PARAMETER)
    assert len(tools) == 1
    assert tools[0].content.get("name") == "fake_tool"
    assert tools[0].content.get("version") == "0.1.0"
    assert len(params) >= 1


def test_tool_executor_records_output_files(tmp_path: Path):
    class OutputTool(BRKGToolWrapper):
        def __init__(self, output_path: Path):
            super().__init__()
            self.output_path = output_path

        def get_tool_name(self) -> str:
            return "output_tool"

        def get_tool_description(self) -> str:
            return "Tool that writes an output file"

        def get_args_schema(self) -> type[BaseModel]:
            return _Args

        def _run(self, **kwargs) -> ToolResult:
            self.output_path.write_text("ok", encoding="utf-8")
            return ToolResult(
                status="success",
                data={
                    "outputs": {"artifact": str(self.output_path)},
                    "version": "0.1.0",
                },
            )

    output_path = tmp_path / "artifact.txt"
    reg = ToolRegistry(auto_discover=False)
    reg.register_tool(OutputTool(output_path))
    collector = EvidenceCollector(storage_path=tmp_path, auto_persist=False)
    collector.clear()
    exec = ToolExecutor(
        tool_registry=reg,
        enable_caching=False,
        safe_mode=True,
        evidence_collector=collector,
    )

    req = ToolExecutionRequest(
        tool_name="output_tool",
        parameters={"value": 1},
        mode=ExecutionMode.API_CALL,
        category=ToolCategory.DATA_PROCESSING,
    )
    res = exec.execute(req)
    assert res.status == "success"

    files = collector.get_evidence_by_type(EvidenceType.FILE)
    assert any(f.content.get("path") == str(output_path) for f in files)
