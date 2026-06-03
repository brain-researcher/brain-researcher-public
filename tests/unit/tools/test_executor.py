"""Tests for unified tool executor.

Tests the execute_tool dispatcher and backend-specific execution paths.
"""

import os
import warnings
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from brain_researcher.config.paths import get_outputs_root
from brain_researcher.services.tools.executor import (
    _default_execution_pack_dir,
    _execute_python,
    _resolve_niwrap_tool_name,
    _tool_supports_execution_parameter,
    execute_tool,
    get_available_backends,
)
from brain_researcher.services.tools.result import ToolResult


class TestExecuteTool:
    """Tests for execute_tool dispatcher."""

    def test_default_execution_pack_dir_uses_outputs_root(self):
        path = _default_execution_pack_dir(
            "python.fetch_atlas.run",
            {},
            work_dir=None,
            output_dir=None,
        )
        assert path == (
            get_outputs_root()
            / "execution_packs"
            / "python.fetch_atlas.run_execution_pack"
        )

    def test_unknown_tool_returns_error(self):
        """Unknown tool ID returns error ToolResult."""
        result = execute_tool("nonexistent.tool.xyz", {})

        assert result.status == "error"
        assert "Unknown tool" in result.error
        assert result.metadata["tool_id"] == "nonexistent.tool.xyz"
        assert result.metadata["failure_category"] == "invocation_error"
        assert result.metadata["repair_eligible"] is False
        assert (
            result.data["failure_diagnostics"]["failure_category"] == "invocation_error"
        )

    def test_unknown_tool_attaches_codebase_diagnostics_from_code_store(
        self, monkeypatch
    ):
        calls = {}

        def _fake_search_gfs_auto(query, **kwargs):
            calls["query"] = query
            calls["kwargs"] = kwargs
            return {
                "status": "ok",
                "summary": "Look at executor remap handling.",
                "stores_hit": ["fileSearchStores/brain-researcher-codebase-abc"],
                "reason": "intent_code",
                "hits": [
                    {
                        "doc_id": "doc-1",
                        "title": "executor.py",
                        "snippet": "resolve_runtime_tool_ids remap path",
                        "score": 0.91,
                        "store": "fileSearchStores/brain-researcher-codebase-abc",
                    }
                ],
            }

        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv(
            "BR_FILE_SEARCH_STORE_NAMES",
            "fileSearchStores/papers-fmri-oa-xyz,fileSearchStores/brain-researcher-codebase-abc",
        )
        with patch(
            "brain_researcher.core.literature.gfs_store.search_gfs_auto",
            side_effect=_fake_search_gfs_auto,
        ):
            result = execute_tool("nonexistent.tool.xyz", {})

        assert result.status == "error"
        assert "Unknown tool" in (result.error or "")
        assert result.data["codebase_diagnostics"]["summary"] == (
            "Look at executor remap handling."
        )
        assert result.data["codebase_diagnostics"]["stores_hit"] == [
            "fileSearchStores/brain-researcher-codebase-abc"
        ]
        assert (
            calls["kwargs"]["store"] == "fileSearchStores/brain-researcher-codebase-abc"
        )
        assert "tool nonexistent.tool.xyz" in calls["query"]

    def test_unknown_tool_falls_back_to_default_codebase_store_when_env_only_has_papers(
        self, monkeypatch
    ):
        calls = {}

        def _fake_search_gfs_auto(query, **kwargs):
            calls["query"] = query
            calls["kwargs"] = kwargs
            return {
                "status": "ok",
                "summary": "Default codebase fallback.",
                "stores_hit": [
                    "fileSearchStores/brain-researcher-codebase-5i70bkfmcumj"
                ],
                "reason": "intent_code",
                "hits": [],
            }

        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv(
            "BR_FILE_SEARCH_STORE_NAMES",
            "fileSearchStores/papers-fmri-oa-xyz",
        )
        with patch(
            "brain_researcher.core.literature.gfs_store.search_gfs_auto",
            side_effect=_fake_search_gfs_auto,
        ):
            result = execute_tool("nonexistent.tool.xyz", {})

        assert result.status == "error"
        assert result.data["codebase_diagnostics"]["summary"] == (
            "Default codebase fallback."
        )
        assert (
            calls["kwargs"]["store"]
            == "fileSearchStores/brain-researcher-codebase-5i70bkfmcumj"
        )

    def test_execution_policy_violation_is_classified_as_invocation_error(self):
        from brain_researcher.services.tools.execution_policy import (
            ExecutionPolicyError,
        )
        from brain_researcher.services.tools.spec import ToolSpec

        mock_spec = ToolSpec(
            name="test.tool",
            description="Test tool",
            backend="python",
            python_class="test.module.TestTool",
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            with patch(
                "brain_researcher.services.tools.executor.enforce_allowed_paths",
                side_effect=ExecutionPolicyError(["path not allowed"]),
            ):
                result = execute_tool("test.tool", {"input_file": "/etc/passwd"})

        assert result.status == "error"
        assert result.error == "execution_policy_violation"
        assert result.metadata["failure_category"] == "invocation_error"
        assert result.metadata["repair_eligible"] is False
        assert (
            result.data["failure_diagnostics"]["failure_category"] == "invocation_error"
        )

    def test_unknown_tool_skips_codebase_diagnostics_when_mcp_network_disabled(
        self, monkeypatch
    ):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("BR_MCP_ALLOW_NETWORK", "0")
        monkeypatch.setenv(
            "BR_FILE_SEARCH_STORE_NAMES",
            "fileSearchStores/brain-researcher-codebase-abc",
        )
        with patch(
            "brain_researcher.core.literature.gfs_store.search_gfs_auto"
        ) as search_mock:
            result = execute_tool("nonexistent.tool.xyz", {})

        assert result.status == "error"
        assert "codebase_diagnostics" not in (result.data or {})
        search_mock.assert_not_called()

    def test_unknown_backend_returns_error(self):
        """Tool with unknown backend returns error."""
        # Create a mock spec with an invalid backend (bypassing Pydantic validation)
        mock_spec = MagicMock()
        mock_spec.name = "test.tool"
        mock_spec.backend = "unknown_backend"
        mock_spec.niwrap_id = None
        mock_spec.python_class = None

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            result = execute_tool("test.tool", {})

        assert result.status == "error"
        assert "Unknown backend" in result.error
        assert result.metadata["failure_category"] == "environment_issue"
        assert result.metadata["repair_eligible"] is False

    def test_python_runtime_exception_is_classified_as_implementation_bug(self):
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeTool:
            def run(self, **_kwargs):
                raise RuntimeError("boom")

        mock_spec = ToolSpec(
            name="test.tool",
            description="Test tool",
            backend="python",
            python_class="test.module.TestTool",
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            with patch("pydoc.locate") as mock_locate:
                mock_locate.return_value = FakeTool
                result = execute_tool("test.tool", {"param": "value"})

        assert result.status == "error"
        assert "boom" in (result.error or "")
        assert result.metadata["failure_category"] == "implementation_bug"
        assert result.metadata["repair_eligible"] is True
        assert result.metadata["failure_diagnostics"]["repair_mode"] == "diagnose_only"
        assert (
            result.data["failure_diagnostics"]["failure_category"]
            == "implementation_bug"
        )

    def test_exception_handling(self):
        """Exceptions during execution are caught and returned as error."""
        from brain_researcher.services.tools.spec import ToolSpec

        mock_spec = ToolSpec(
            name="test.tool",
            description="Test tool",
            backend="python",
            python_class="nonexistent.module.Class",
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            result = execute_tool("test.tool", {})

        assert result.status == "error"
        # Should catch import error gracefully

    def test_auto_remap_resolves_candidate_and_adds_metadata(self):
        """Execution should remap tool ID candidates only when explicitly allowed."""
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeTool:
            def run(self, **_kwargs):
                return ToolResult(
                    status="success",
                    data={"ok": True},
                    error=None,
                    metadata={"source": "fake"},
                )

        mapped_spec = ToolSpec(
            name="python.fetch_atlas.run",
            description="Mapped fetch atlas",
            backend="python",
            python_class="test.module.FetchAtlasTool",
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.side_effect = lambda name: (
                mapped_spec if name == "python.fetch_atlas.run" else None
            )
            with patch(
                "brain_researcher.services.tools.executor.resolve_runtime_tool_ids",
                return_value=["fetch_atlas", "python.fetch_atlas.run"],
            ):
                with patch("pydoc.locate") as mock_locate:
                    mock_locate.return_value = FakeTool
                    result = execute_tool(
                        "fetch_atlas",
                        {"atlas": "MNI152"},
                        allow_remap=True,
                    )

        assert result.status == "success"
        assert result.metadata["resolver_mode"] == "auto_remap"
        assert result.metadata["resolved_tool_id"] == "python.fetch_atlas.run"
        assert result.metadata["remap_applied"] is True
        assert result.metadata["source"] == "fake"

    def test_successful_execution_attaches_execution_pack_metadata_by_default(self):
        """Successful non-preview executions should expose execution pack metadata."""
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeTool:
            def run(self, **_kwargs):
                return ToolResult(
                    status="success",
                    data={"ok": True},
                    error=None,
                    metadata={"source": "fake"},
                )

        mapped_spec = ToolSpec(
            name="python.fetch_atlas.run",
            description="Mapped fetch atlas",
            backend="python",
            python_class="test.module.FetchAtlasTool",
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mapped_spec
            with patch("pydoc.locate") as mock_locate:
                mock_locate.return_value = FakeTool
                with patch(
                    "brain_researcher.services.tools.executor.materialize_execution_pack",
                    return_value={
                        "workspace": "/tmp/pack",
                        "pack_manifest": "/tmp/pack/pack_manifest.json",
                    },
                ):
                    result = execute_tool(
                        "python.fetch_atlas.run",
                        {"atlas": "MNI152"},
                    )

        assert result.status == "success"
        assert result.metadata["source"] == "fake"
        assert result.metadata["execution_pack"]["workspace"] == "/tmp/pack"

    def test_successful_execution_skips_codebase_failure_diagnostics(self, monkeypatch):
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeTool:
            def run(self, **_kwargs):
                return ToolResult(
                    status="success",
                    data={"ok": True},
                    error=None,
                    metadata={"source": "fake"},
                )

        mapped_spec = ToolSpec(
            name="python.fetch_atlas.run",
            description="Mapped fetch atlas",
            backend="python",
            python_class="test.module.FetchAtlasTool",
        )

        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv(
            "BR_FILE_SEARCH_STORE_NAMES",
            "fileSearchStores/papers-fmri-oa-xyz,fileSearchStores/brain-researcher-codebase-abc",
        )
        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mapped_spec
            with patch("pydoc.locate") as mock_locate:
                mock_locate.return_value = FakeTool
                with patch(
                    "brain_researcher.core.literature.gfs_store.search_gfs_auto"
                ) as search_mock:
                    result = execute_tool(
                        "python.fetch_atlas.run",
                        {"atlas": "MNI152"},
                    )

        assert result.status == "success"
        assert "codebase_diagnostics" not in (result.data or {})
        search_mock.assert_not_called()

    def test_preview_execution_does_not_attach_execution_pack_metadata(self):
        """Preview mode should skip execution pack materialization."""
        mock_spec = MagicMock()
        mock_spec.name = "fsl.bet"
        mock_spec.backend = "niwrap"
        mock_spec.niwrap_id = None
        mock_spec.python_class = None

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            with patch(
                "brain_researcher.services.tools.executor._execute_niwrap",
                return_value=ToolResult(
                    status="success",
                    data={"command": "bet input output"},
                    error=None,
                    metadata={"mode": "preview"},
                ),
            ):
                with patch(
                    "brain_researcher.services.tools.executor.materialize_execution_pack"
                ) as materialize:
                    result = execute_tool(
                        "fsl.bet", {"input": "input.nii"}, preview=True
                    )

        assert result.status == "success"
        assert result.metadata["mode"] == "preview"
        assert "execution_pack" not in result.metadata
        materialize.assert_not_called()

    def test_tool_supports_execution_parameter_avoids_pydantic_v2_fields_warning(self):
        """Pydantic v2 schema classes should not touch deprecated __fields__."""

        class Schema(BaseModel):
            output_dir: str | None = None

        class FakeTool:
            def get_args_schema(self):
                return Schema

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert _tool_supports_execution_parameter(FakeTool(), "output_dir") is True

        assert not [
            warning for warning in caught if "__fields__" in str(warning.message)
        ]

    def test_auto_remap_unknown_returns_intercept_metadata(self):
        """Unknown tool with remap candidates should return intercept-style error."""
        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = None
            with patch(
                "brain_researcher.services.tools.executor.resolve_runtime_tool_ids",
                return_value=["missing.tool", "fallback.tool"],
            ):
                result = execute_tool("missing.tool", {}, allow_remap=True)

        assert result.status == "error"
        assert "Unknown tool" in (result.error or "")
        assert result.metadata["intercept_reason"] == "unknown_or_unmapped_tool"
        assert result.metadata["resolver_mode"] == "auto_remap"
        assert result.metadata["resolved_tool_id"] is None
        assert result.metadata["remap_applied"] is False
        assert result.data["candidate_tool_ids"] == ["missing.tool", "fallback.tool"]
        assert (
            result.data["failure_diagnostics"]["failure_category"] == "invocation_error"
        )

    def test_auto_remap_is_disabled_by_default(self):
        """Execution should stay direct unless allow_remap=True is passed."""
        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = None
            with patch(
                "brain_researcher.services.tools.executor.resolve_runtime_tool_ids"
            ) as resolver:
                result = execute_tool("missing.tool", {})

        assert result.status == "error"
        assert "Unknown tool" in (result.error or "")
        assert result.metadata["tool_id"] == "missing.tool"
        assert result.metadata["failure_category"] == "invocation_error"
        assert result.metadata["repair_eligible"] is False
        resolver.assert_not_called()

    def test_auto_remap_skips_unexecutable_python_candidate(self):
        """Remap should continue to next candidate when first python spec is unexecutable."""
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeTool:
            def run(self, **_kwargs):
                return ToolResult(
                    status="success",
                    data={"ok": True},
                    error=None,
                    metadata={"source": "callable_candidate"},
                )

        unresolved_spec = ToolSpec(
            name="fmri.connectivity_client.light",
            description="Alias without python class",
            backend="python",
            python_class=None,
        )
        resolved_spec = ToolSpec(
            name="connectivity_matrix",
            description="Callable connectivity tool",
            backend="python",
            python_class="test.module.ConnectivityTool",
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.side_effect = lambda name: (
                unresolved_spec
                if name == "fmri.connectivity_client.light"
                else resolved_spec if name == "connectivity_matrix" else None
            )
            with patch(
                "brain_researcher.services.tools.executor.resolve_runtime_tool_ids",
                return_value=["fmri.connectivity_client.light", "connectivity_matrix"],
            ):
                with patch("pydoc.locate") as mock_locate:
                    mock_locate.return_value = FakeTool
                    result = execute_tool(
                        "fmri.connectivity_client.light",
                        {"dataset": "ds:openneuro:ds000224"},
                        allow_remap=True,
                    )

        assert result.status == "success"
        assert result.metadata["resolved_tool_id"] == "connectivity_matrix"
        assert result.metadata["remap_applied"] is True
        assert result.metadata["source"] == "callable_candidate"

    def test_code_agent_tool_disabled_by_default(self, monkeypatch):
        """code_agent should be blocked unless BR_ENABLE_CODE_AGENT_TOOL=1."""
        monkeypatch.delenv("BR_ENABLE_CODE_AGENT_TOOL", raising=False)
        from brain_researcher.services.tools.spec import ToolSpec

        spec = ToolSpec(
            name="code_agent",
            description="coding tool",
            backend="python",
            python_class="brain_researcher.services.tools.llm_router_tool.CodingAgentTool",
        )
        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = spec
            result = execute_tool("code_agent", {"task": "test"})

        assert result.status == "error"
        assert result.error == "tool_disabled"
        assert result.data["reason_code"] == "code_agent_disabled"


class _OutputDirArgs(BaseModel):
    input_file: str
    output_dir: str | None = None
    work_dir: str | None = None


class _RecordingPythonTool:
    def __init__(self):
        self.calls = []

    def get_args_schema(self):
        return _OutputDirArgs

    def run(self, **kwargs):
        self.calls.append(dict(kwargs))
        return ToolResult(
            status="success",
            data={"kwargs": dict(kwargs)},
            error=None,
            metadata={"source": "recording"},
        )


class _AtlasLikePythonTool(_RecordingPythonTool):
    inject_execution_output_dir = False


def test_execute_python_injects_output_and_work_dir_when_supported():
    from brain_researcher.services.tools.spec import ToolSpec

    spec = ToolSpec(
        name="recording.python.tool",
        description="recording",
        backend="python",
        python_class="fake.module.RecordingTool",
    )
    tool = _RecordingPythonTool()

    with (
        patch(
            "brain_researcher.services.tools.executor.audit_python_backend_configuration",
            return_value=None,
        ),
        patch(
            "brain_researcher.services.tools.executor._resolve_python_tool_instance",
            return_value=tool,
        ),
    ):
        result = _execute_python(
            spec,
            {"input_file": "bold.nii.gz"},
            work_dir="/tmp/work",
            output_dir="/tmp/out",
        )

    assert result.status == "success"
    assert tool.calls == [
        {
            "input_file": "bold.nii.gz",
            "output_dir": "/tmp/out",
            "work_dir": "/tmp/work",
        }
    ]


def test_execute_python_preserves_explicit_output_dir():
    from brain_researcher.services.tools.spec import ToolSpec

    spec = ToolSpec(
        name="recording.python.tool",
        description="recording",
        backend="python",
        python_class="fake.module.RecordingTool",
    )
    tool = _RecordingPythonTool()

    with (
        patch(
            "brain_researcher.services.tools.executor.audit_python_backend_configuration",
            return_value=None,
        ),
        patch(
            "brain_researcher.services.tools.executor._resolve_python_tool_instance",
            return_value=tool,
        ),
    ):
        result = _execute_python(
            spec,
            {"input_file": "bold.nii.gz", "output_dir": "/caller/out"},
            output_dir="/mcp/out",
        )

    assert result.status == "success"
    assert tool.calls == [{"input_file": "bold.nii.gz", "output_dir": "/caller/out"}]


def test_execute_python_honors_output_dir_opt_out():
    from brain_researcher.services.tools.spec import ToolSpec

    spec = ToolSpec(
        name="fetch_atlas",
        description="atlas",
        backend="python",
        python_class="fake.module.FetchAtlasTool",
    )
    tool = _AtlasLikePythonTool()

    with (
        patch(
            "brain_researcher.services.tools.executor.audit_python_backend_configuration",
            return_value=None,
        ),
        patch(
            "brain_researcher.services.tools.executor._resolve_python_tool_instance",
            return_value=tool,
        ),
    ):
        result = _execute_python(
            spec,
            {"input_file": "atlas"},
            output_dir="/mcp/out",
            work_dir="/mcp/work",
        )

    assert result.status == "success"
    assert tool.calls == [{"input_file": "atlas", "work_dir": "/mcp/work"}]


class TestPythonBackend:
    """Tests for Python backend execution."""

    def test_missing_python_class_returns_error(self):
        """Python tool without python_class returns error."""
        from brain_researcher.services.tools.spec import ToolSpec

        mock_spec = ToolSpec(
            name="test.tool",
            description="Test tool",
            backend="python",
            python_class=None,  # No class defined
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            result = execute_tool("test.tool", {"query": "test"})

        assert result.status == "error"
        assert result.error == "tool_registry_misconfigured"
        assert result.data["reason_code"] == "python_backend_unresolvable"
        assert "missing python_class" in (result.data.get("message") or "")
        assert result.metadata["failure_category"] == "environment_issue"
        assert result.metadata["repair_eligible"] is False

    def test_workflow_fallback_injects_pipeline_output_dir(self):
        """Workflow runtime fallback should inherit pipeline work/output dirs."""
        from brain_researcher.services.tools.spec import ToolSpec

        captured = {}

        class FakeWorkflowTool:
            def _run(self, **kwargs):
                captured.update(kwargs)
                return ToolResult(status="success", data={"ok": True})

        mock_spec = ToolSpec(
            name="workflow_rest_connectome_e2e",
            description="Workflow tool",
            backend="python",
            python_class=None,
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            with patch(
                "brain_researcher.services.tools.catalog_loader.is_workflow_tool_id",
                return_value=True,
            ):
                with patch(
                    "brain_researcher.services.tools.executor._resolve_workflow_runtime_tool",
                    return_value=FakeWorkflowTool(),
                ):
                    result = execute_tool(
                        "workflow_rest_connectome_e2e",
                        {"img": "bold.nii.gz", "atlas_name": "synthetic"},
                        work_dir="/tmp/workflow-work",
                        output_dir="/tmp/workflow-out",
                    )

        assert result.status == "success"
        assert captured["img"] == "bold.nii.gz"
        assert captured["atlas_name"] == "synthetic"
        assert captured["work_dir"] == "/tmp/workflow-work"
        assert captured["output_dir"] == "/tmp/workflow-out"

    def test_workflow_missing_python_class_falls_back_to_runtime_registry(self):
        """Workflow tools without python_class should execute via runtime registry fallback."""
        from brain_researcher.services.tools.spec import ToolSpec

        mock_spec = ToolSpec(
            name="workflow_visual_decoding",
            description="Workflow visual decoding",
            backend="python",
            python_class=None,
        )

        class FakeWorkflowTool:
            def _run(self, **kwargs):
                return ToolResult(
                    status="success",
                    data={
                        "workflow": "workflow_visual_decoding",
                        "received": kwargs,
                    },
                    error=None,
                    metadata={"source": "runtime_registry"},
                )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            with patch(
                "brain_researcher.services.tools.catalog_loader.is_workflow_tool_id",
                return_value=True,
            ):
                with patch(
                    "brain_researcher.services.tools.executor._workflow_runtime_registry",
                    return_value=MagicMock(
                        get_tool=MagicMock(return_value=FakeWorkflowTool())
                    ),
                ):
                    result = execute_tool(
                        "workflow_visual_decoding",
                        {"features": "/tmp/features.npy", "labels": "/tmp/labels.npy"},
                    )

        assert result.status == "success"
        assert result.data["workflow"] == "workflow_visual_decoding"
        assert "received" in result.data

    def test_workflow_missing_python_class_returns_runtime_error_when_not_resolved(
        self,
    ):
        """Workflow fallback should emit actionable error when runtime tool is absent."""
        from brain_researcher.services.tools.spec import ToolSpec

        mock_spec = ToolSpec(
            name="workflow_hypothesis_candidate_cards",
            description="Workflow candidate cards",
            backend="python",
            python_class=None,
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            with patch(
                "brain_researcher.services.tools.catalog_loader.is_workflow_tool_id",
                return_value=True,
            ):
                with patch(
                    "brain_researcher.services.tools.executor._workflow_runtime_registry",
                    return_value=MagicMock(get_tool=MagicMock(return_value=None)),
                ):
                    result = execute_tool(
                        "workflow_hypothesis_candidate_cards",
                        {"query": "fmri based image decoding"},
                    )

        assert result.status == "error"
        assert result.error == "tool_registry_misconfigured"
        assert result.data["reason_code"] == "python_backend_unresolvable"
        assert "missing python_class" in (result.data.get("message") or "")

    def test_invalid_python_class_returns_error(self):
        """Python tool with invalid class path returns error."""
        from brain_researcher.services.tools.spec import ToolSpec

        mock_spec = ToolSpec(
            name="test.tool",
            description="Test tool",
            backend="python",
            python_class="nonexistent.module.NonexistentClass",
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            result = execute_tool("test.tool", {"query": "test"})

        assert result.status == "error"
        assert result.error == "tool_registry_misconfigured"
        assert result.data["reason_code"] == "python_backend_unresolvable"
        assert "could not be resolved" in (result.data.get("message") or "").lower()

    def test_python_execution_success(self):
        """Successful Python tool execution returns success."""
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeTool:
            def run(self, **_kwargs):
                return ToolResult(
                    status="success",
                    data={"output": "test_value"},
                    error=None,
                    metadata=None,
                )

        mock_spec = ToolSpec(
            name="test.tool",
            description="Test tool",
            backend="python",
            python_class="test.module.TestTool",
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec

            with patch("pydoc.locate") as mock_locate:
                mock_locate.return_value = FakeTool
                result = execute_tool("test.tool", {"param": "value"})

        assert result.status == "success"
        assert result.data == {"output": "test_value"}

    def test_task_mapping_success_without_data_returns_error(self):
        """task_to_concept_mapping must not pass through success/null payloads."""
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeTool:
            def run(self, **_kwargs):
                return {
                    "status": "success",
                    "data": None,
                    "error": None,
                    "metadata": None,
                }

        mock_spec = ToolSpec(
            name="task_to_concept_mapping",
            description="Task mapper",
            backend="python",
            python_class="test.module.TaskMapper",
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec

            with patch("pydoc.locate") as mock_locate:
                mock_locate.return_value = FakeTool
                result = execute_tool(
                    "task_to_concept_mapping", {"task_name": "n-back"}
                )

        assert result.status == "error"
        assert "empty data payload" in (result.error or "")
        assert result.metadata["tool_id"] == "task_to_concept_mapping"
        assert result.metadata["error_category"] == "invalid_result"


class TestNiWrapBackend:
    """Tests for NiWrap backend execution."""

    def test_niwrap_tool_not_found_returns_error(self):
        """NiWrap tool not in catalog returns error."""
        from brain_researcher.services.tools.spec import ToolSpec

        mock_spec = ToolSpec(
            name="fsl.nonexistent",
            description="Nonexistent FSL tool",
            backend="niwrap",
            niwrap_id="fsl.nonexistent.run",
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec

            with patch(
                "brain_researcher.services.tools.niwrap.catalog.get_tool_by_name"
            ) as mock_get:
                mock_get.return_value = None

                with patch(
                    "brain_researcher.services.tools.executor._resolve_niwrap_tool_name"
                ) as mock_resolve:
                    mock_resolve.return_value = None
                    result = execute_tool("fsl.nonexistent", {"input": "test.nii"})

        assert result.status == "error"
        assert "NiWrap tool not found" in result.error

    def test_niwrap_preview_mode(self):
        """Preview mode returns command without execution."""
        from brain_researcher.services.tools.spec import ToolSpec

        mock_spec = ToolSpec(
            name="fsl.bet",
            description="FSL BET",
            backend="niwrap",
            niwrap_id="fsl.bet.run",
        )

        mock_tool_def = {
            "name": "fsl.6.0.7.bet.run",
            "metadata": {"command_line": "bet [INPUT] [OUTPUT]"},
        }

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec

            with patch(
                "brain_researcher.services.tools.niwrap.catalog.get_tool_by_name"
            ) as mock_get:
                mock_get.return_value = mock_tool_def

                with patch(
                    "brain_researcher.services.tools.niwrap.executor.preview_niwrap_tool"
                ) as mock_preview:
                    mock_preview.return_value = {
                        "command": "bet input.nii output.nii",
                        "preview": True,
                    }
                    result = execute_tool(
                        "fsl.bet", {"input": "input.nii"}, preview=True
                    )

        assert result.status == "success"
        assert result.metadata.get("mode") == "preview"
        assert "command" in result.data

    def test_niwrap_execution_success(self):
        """Successful NiWrap execution returns success."""
        from brain_researcher.services.tools.spec import ToolSpec

        mock_spec = ToolSpec(
            name="fsl.bet",
            description="FSL BET",
            backend="niwrap",
            niwrap_id="fsl.bet.run",
        )

        mock_tool_def = {
            "name": "fsl.6.0.7.bet.run",
            "metadata": {"command_line": "bet [INPUT] [OUTPUT]"},
        }

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec

            with patch(
                "brain_researcher.services.tools.niwrap.catalog.get_tool_by_name"
            ) as mock_get:
                mock_get.return_value = mock_tool_def

                with patch(
                    "brain_researcher.services.tools.niwrap.executor.execute_niwrap_tool"
                ) as mock_exec:
                    mock_exec.return_value = {
                        "exit_code": 0,
                        "stdout": "Success",
                        "stderr": "",
                    }
                    result = execute_tool("fsl.bet", {"input": "input.nii"})

        assert result.status == "success"
        assert result.data["exit_code"] == 0

    def test_niwrap_execution_failure(self):
        """Failed NiWrap execution returns error with stderr."""
        from brain_researcher.services.tools.spec import ToolSpec

        mock_spec = ToolSpec(
            name="fsl.bet",
            description="FSL BET",
            backend="niwrap",
            niwrap_id="fsl.bet.run",
        )

        mock_tool_def = {
            "name": "fsl.6.0.7.bet.run",
            "metadata": {"command_line": "bet [INPUT] [OUTPUT]"},
        }

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec

            with patch(
                "brain_researcher.services.tools.niwrap.catalog.get_tool_by_name"
            ) as mock_get:
                mock_get.return_value = mock_tool_def

                with patch(
                    "brain_researcher.services.tools.niwrap.executor.execute_niwrap_tool"
                ) as mock_exec:
                    mock_exec.return_value = {
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": "Error: Input file not found",
                    }
                    result = execute_tool("fsl.bet", {"input": "missing.nii"})

        assert result.status == "error"
        assert "Error: Input file not found" in result.error


class TestExternalAPIBackend:
    """Tests for external API backend execution."""

    def test_external_api_no_handler_returns_error(self):
        """External API tool without handler returns error."""
        from brain_researcher.services.tools.spec import ToolSpec

        mock_spec = ToolSpec(
            name="unknown.api",
            description="Unknown API",
            backend="external_api",
            python_class=None,
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            result = execute_tool("unknown.api", {"query": "test"})

        assert result.status == "error"
        assert "No handler" in result.error

    def test_external_api_fallback_to_python(self):
        """External API with python_class falls back to Python execution."""
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeTool:
            def run(self, **_kwargs):
                return {"status": "success", "data": {"result": "ok"}}

        mock_spec = ToolSpec(
            name="custom.api",
            description="Custom API",
            backend="external_api",
            python_class="test.module.CustomAPI",
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec

            with patch("pydoc.locate") as mock_locate:
                mock_locate.return_value = FakeTool
                result = execute_tool("custom.api", {"param": "value"})

        assert result.status == "success"
        assert result.data == {"result": "ok"}

    def test_external_api_mcp_bridge_server_info(self):
        """MCP external_api tools should execute via the registered bridge."""
        from brain_researcher.services.shared import mcp_runtime_bridge
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeProvider:
            def call_tool(self, tool_name, arguments=None):
                assert tool_name == "server_info"
                assert dict(arguments or {}) == {}
                return {"ok": True, "data": {"name": "brain-researcher"}}

        mock_spec = ToolSpec(
            name="mcp.server_info",
            description="MCP info",
            backend="external_api",
            python_class=None,
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            with patch.object(
                mcp_runtime_bridge,
                "_registered_provider",
                FakeProvider(),
            ):
                result = execute_tool("mcp.server_info", {})

        assert result.status == "success"
        assert isinstance(result.data, dict)
        assert result.data.get("ok") is True

    def test_external_api_mcp_bridge_sherlock_guide(self):
        """Aggregated Sherlock MCP tools should execute via the bridge."""
        from brain_researcher.services.shared import mcp_runtime_bridge
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeProvider:
            def call_tool(self, tool_name, arguments=None):
                assert tool_name == "sherlock_guide"
                assert dict(arguments or {})["action"] == "command"
                return {"ok": True, "commands": ["srun --pty bash"]}

        mock_spec = ToolSpec(
            name="mcp.sherlock_guide",
            description="Sherlock guide",
            backend="external_api",
            python_class=None,
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            with patch.object(
                mcp_runtime_bridge,
                "_registered_provider",
                FakeProvider(),
            ):
                result = execute_tool(
                    "mcp.sherlock_guide",
                    {
                        "action": "command",
                        "intent": "interactive_cpu",
                        "pi_group": "russpold",
                    },
                )

        assert result.status == "success"
        assert result.data["commands"] == ["srun --pty bash"]

    def test_external_api_mcp_bridge_sherlock_slurm(self):
        """Aggregated Sherlock Slurm MCP tool should execute via the bridge."""
        from brain_researcher.services.shared import mcp_runtime_bridge
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeProvider:
            def call_tool(self, tool_name, arguments=None):
                assert tool_name == "sherlock_slurm"
                assert dict(arguments or {})["action"] == "render_script"
                return {
                    "ok": True,
                    "script_text": "#!/bin/bash\n#SBATCH --time=24:00:00\n",
                }

        mock_spec = ToolSpec(
            name="mcp.sherlock_slurm",
            description="Sherlock slurm helper",
            backend="external_api",
            python_class=None,
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            with patch.object(
                mcp_runtime_bridge,
                "_registered_provider",
                FakeProvider(),
            ):
                result = execute_tool(
                    "mcp.sherlock_slurm",
                    {
                        "action": "render_script",
                        "template_kind": "cpu_single",
                        "job_name": "analysis",
                        "command": "python run.py",
                    },
                )

        assert result.status == "success"
        assert "#SBATCH --time=24:00:00" in result.data["script_text"]

    def test_external_api_mcp_bridge_system_self_test_in_band_error(self):
        """system_self_test is supported and ok:false payloads stay in-band."""
        from brain_researcher.services.shared import mcp_runtime_bridge
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeProvider:
            def call_tool(self, tool_name, arguments=None):
                assert tool_name == "system_self_test"
                assert dict(arguments or {})["mode"] == "quick"
                return {"ok": False, "error": "self_test_disabled"}

        mock_spec = ToolSpec(
            name="mcp.system_self_test",
            description="MCP self-test",
            backend="external_api",
            python_class=None,
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            with patch.object(
                mcp_runtime_bridge,
                "_registered_provider",
                FakeProvider(),
            ):
                result = execute_tool("mcp.system_self_test", {"mode": "quick"})

        assert result.status == "error"
        assert result.error == "self_test_disabled"
        assert result.data["ok"] is False
        assert result.data["error"] == "self_test_disabled"
        assert "failure_diagnostics" in result.data

    def test_external_api_gemini_uses_gemini_cli_tools(self):
        """Gemini external_api tools should resolve via gemini_cli_tools registry."""
        from brain_researcher.services.tools.spec import ToolSpec

        class FakeGeminiTool:
            def get_tool_name(self):
                return "gemini.search_text"

            def run(self, **_kwargs):
                return ToolResult(
                    status="success",
                    data={"matches": ["a.py:1:test"]},
                    error=None,
                    metadata={"source": "fake_gemini"},
                )

        mock_spec = ToolSpec(
            name="gemini.search_text",
            description="Gemini search",
            backend="external_api",
            python_class=None,
        )

        with patch(
            "brain_researcher.services.tools.executor.UnifiedToolRegistry"
        ) as MockRegistry:
            MockRegistry.return_value.get_toolspec_by_name.return_value = mock_spec
            with patch(
                "brain_researcher.services.tools.gemini_cli_tools.get_all_tools",
                return_value=[FakeGeminiTool()],
            ):
                result = execute_tool("gemini.search_text", {"query": "test"})

        assert result.status == "success"
        assert result.data == {"matches": ["a.py:1:test"]}


class TestResolveNiwrapToolName:
    """Tests for NiWrap tool name resolution."""

    def test_resolve_short_to_versioned_name(self):
        """Short ID resolves to full versioned name."""
        mock_tools = [
            {"name": "fsl.6.0.7.bet.run"},
            {"name": "fsl.6.0.7.flirt.run"},
        ]

        with patch(
            "brain_researcher.services.tools.niwrap.catalog.get_niwrap_tools"
        ) as mock_get:
            mock_get.return_value = mock_tools
            resolved = _resolve_niwrap_tool_name("fsl.bet.run")

        assert resolved == "fsl.6.0.7.bet.run"

    def test_resolve_returns_none_for_invalid_id(self):
        """Invalid short ID returns None."""
        resolved = _resolve_niwrap_tool_name("invalid")
        assert resolved is None

    def test_resolve_returns_none_when_not_found(self):
        """Short ID not in catalog returns None."""
        mock_tools = [
            {"name": "fsl.6.0.7.bet.run"},
        ]

        with patch(
            "brain_researcher.services.tools.niwrap.catalog.get_niwrap_tools"
        ) as mock_get:
            mock_get.return_value = mock_tools
            resolved = _resolve_niwrap_tool_name("fsl.nonexistent.run")

        assert resolved is None


class TestGetAvailableBackends:
    """Tests for get_available_backends."""

    def test_returns_all_backends(self):
        """Returns list of all supported backends."""
        backends = get_available_backends()

        assert "niwrap" in backends
        assert "python" in backends
        assert "external_api" in backends
        assert len(backends) == 3


class TestIntegrationWithCatalog:
    """Integration tests with the real NiWrap catalog when available.

    These tests are disabled by default; set RUN_NIWRAP_INTEGRATION=1 to enable.
    They assume configs/catalog/boutiques_index.json is present and that
    container runtimes are available (preview mode avoids actually running them).
    """

    @pytest.mark.skipif(
        os.getenv("RUN_NIWRAP_INTEGRATION") != "1",
        reason="Set RUN_NIWRAP_INTEGRATION=1 to run NiWrap catalog integration tests",
    )
    def test_execute_real_niwrap_tool_preview(self):
        """Execute a real NiWrap tool (fsl.bet) in preview mode."""
        # Minimal parameters for BET descriptor; preview avoids running the container.
        params = {
            "input": "/tmp/dummy_t1.nii.gz",
            "output": "/tmp/dummy_t1_brain.nii.gz",
        }

        result = execute_tool("fsl.bet", params, preview=True)

        assert result.status == "success"
        assert result.metadata.get("backend") == "niwrap"
        assert result.metadata.get("mode") == "preview"
