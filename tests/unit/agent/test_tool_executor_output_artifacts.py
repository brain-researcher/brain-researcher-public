from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class _Args(BaseModel):
    output_dir: str | None = None


class _ToolRegistry:
    def __init__(self, tool):
        self._tool = tool

    def get_tool(self, name: str):
        if name == self._tool.get_tool_name():
            return self._tool
        return None

    def register_tool(self, _tool):  # pragma: no cover - not used in these tests
        return None


class _NeurodeskTools:
    def get_all_tools(self):  # pragma: no cover - deterministic for tests
        return []

    def get_tool_by_name(self, _name: str):
        return None


class _OutputTool:
    EXAMPLES = []

    def get_tool_name(self) -> str:
        return "demo.output.capture"

    def get_tool_description(self) -> str:
        return "Writes a connectivity matrix under output_dir."

    def get_args_schema(self):
        return _Args

    def _run(self, output_dir: str | None = None):
        out_dir = Path(output_dir or (Path.cwd() / "outputs_default"))
        out_dir.mkdir(parents=True, exist_ok=True)
        matrix_path = out_dir / "connectivity_matrix.npy"
        matrix_path.write_bytes(b"1234")
        return {
            "status": "success",
            "data": {"outputs": {"connectivity_matrix": str(matrix_path)}},
        }


class _RelativePayloadOutputTool:
    EXAMPLES = []

    def get_tool_name(self) -> str:
        return "demo.output.relative_payload"

    def get_tool_description(self) -> str:
        return "Writes outputs to output_dir but reports a run-relative payload path."

    def get_args_schema(self):
        return _Args

    def _run(self, output_dir: str | None = None):
        out_dir = Path(output_dir or (Path.cwd() / "outputs_default"))
        out_dir.mkdir(parents=True, exist_ok=True)
        matrix_path = out_dir / "connectivity_matrix.npy"
        matrix_path.write_bytes(b"5678")
        return {
            "status": "success",
            "data": {
                "outputs": {
                    "connectivity_matrix": f"outputs/{out_dir.name}/connectivity_matrix.npy"
                }
            },
        }


def _make_executor(monkeypatch, tmp_path, tool=None):
    from brain_researcher.config.run_artifacts import reset_recorder_config
    from brain_researcher.services.agent.tool_executor import ToolExecutor

    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
    reset_recorder_config()
    monkeypatch.setattr(ToolExecutor, "_start_background_loop", lambda _self: None)
    selected_tool = tool or _OutputTool()

    return ToolExecutor(
        tool_registry=_ToolRegistry(selected_tool),
        neurodesk_tools=_NeurodeskTools(),
        enable_caching=False,
        safe_mode=True,
        max_workers=1,
        default_timeout=5.0,
    )


def test_python_execution_anchors_relative_output_dir_to_run_dir(monkeypatch, tmp_path):
    from brain_researcher.services.agent.tool_executor import ToolExecutionRequest

    executor = _make_executor(monkeypatch, tmp_path)
    try:
        request = ToolExecutionRequest(
            tool_name="demo.output.capture",
            parameters={"output_dir": "outputs/nilearn_connectivity"},
            runtime_kind="python",
        )
        result = executor.execute(request)
        assert result.status == "success"

        run_dir = Path(result.metadata["run_dir"]).resolve()
        outputs = result.result.get("data", {}).get("outputs", {})
        matrix_path = Path(outputs["connectivity_matrix"]).resolve()

        assert matrix_path.exists()
        assert matrix_path.is_relative_to(run_dir)
    finally:
        executor.shutdown()


def test_python_execution_discovers_output_files_for_provenance(monkeypatch, tmp_path):
    from brain_researcher.services.agent.tool_executor import ToolExecutionRequest

    executor = _make_executor(monkeypatch, tmp_path)
    try:
        request = ToolExecutionRequest(
            tool_name="demo.output.capture",
            parameters={"output_dir": "outputs/nilearn_connectivity"},
            runtime_kind="python",
        )
        result = executor.execute(request)
        assert result.status == "success"

        outputs = result.result.get("data", {}).get("outputs", {})
        matrix_path = str(Path(outputs["connectivity_matrix"]).resolve())

        provenance_path = Path(result.metadata["provenance_path"])
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        artifact_paths = {
            item.get("path")
            for item in provenance.get("artifacts", [])
            if isinstance(item, dict)
        }

        assert matrix_path in artifact_paths
    finally:
        executor.shutdown()


def test_python_execution_discovers_relative_payload_outputs(monkeypatch, tmp_path):
    from brain_researcher.services.agent.tool_executor import ToolExecutionRequest

    executor = _make_executor(monkeypatch, tmp_path, tool=_RelativePayloadOutputTool())
    try:
        request = ToolExecutionRequest(
            tool_name="demo.output.relative_payload",
            parameters={"output_dir": "outputs/nilearn_connectivity"},
            runtime_kind="python",
        )
        result = executor.execute(request)
        assert result.status == "success"

        run_dir = Path(result.metadata["run_dir"]).resolve()
        expected_matrix = (
            run_dir / "outputs" / "nilearn_connectivity" / "connectivity_matrix.npy"
        ).resolve()
        assert expected_matrix.exists()

        provenance_path = Path(result.metadata["provenance_path"])
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        artifact_paths = {
            item.get("path")
            for item in provenance.get("artifacts", [])
            if isinstance(item, dict)
        }

        assert str(expected_matrix) in artifact_paths
    finally:
        executor.shutdown()
