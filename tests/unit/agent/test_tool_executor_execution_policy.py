import socket

from pydantic import BaseModel


class _Args(BaseModel):
    pass


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


def _make_executor(*, tool, monkeypatch, tmp_path):
    from brain_researcher.config.run_artifacts import reset_recorder_config

    monkeypatch.setenv("BR_ENFORCE_EXECUTION_POLICY", "1")
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
    reset_recorder_config()

    from brain_researcher.services.agent.tool_executor import ToolExecutor

    # Avoid spinning up an async background loop in unit tests.
    monkeypatch.setattr(ToolExecutor, "_start_background_loop", lambda _self: None)

    return ToolExecutor(
        tool_registry=_ToolRegistry(tool),
        neurodesk_tools=_NeurodeskTools(),
        enable_caching=False,
        safe_mode=True,
        max_workers=1,
        default_timeout=1.0,
    )


def test_tool_executor_blocks_filesystem_access_outside_allowed_roots(
    monkeypatch, tmp_path
):
    class Tool:
        EXAMPLES = []

        def get_tool_name(self) -> str:
            return "demo.policy.fs_block"

        def get_tool_description(self) -> str:
            return "Reads /etc/passwd (should be blocked under policy)."

        def get_args_schema(self):
            return _Args

        def _run(self):
            return {
                "status": "success",
                "data": {"contents": open("/etc/passwd").read()},
            }

    executor = _make_executor(tool=Tool(), monkeypatch=monkeypatch, tmp_path=tmp_path)

    from brain_researcher.services.agent.tool_executor import ToolExecutionRequest

    req = ToolExecutionRequest(
        tool_name="demo.policy.fs_block",
        parameters={},
        runtime_kind="python",
    )
    res = executor.execute(req)
    assert res.status == "error"
    assert isinstance(res.result, dict)
    assert res.result.get("error") == "execution_policy_violation"
    issues = res.result.get("policy_issues") or []
    assert any(i.get("code") == "path_outside_allowed_roots" for i in issues)


def test_tool_executor_blocks_network_by_default(monkeypatch, tmp_path):
    class Tool:
        EXAMPLES = []

        def get_tool_name(self) -> str:
            return "demo.policy.net_block"

        def get_tool_description(self) -> str:
            return "Resolves example.com (should be blocked by default)."

        def get_args_schema(self):
            return _Args

        def _run(self):
            socket.getaddrinfo("example.com", 443)
            return {"status": "success"}

    executor = _make_executor(tool=Tool(), monkeypatch=monkeypatch, tmp_path=tmp_path)

    from brain_researcher.services.agent.tool_executor import ToolExecutionRequest

    req = ToolExecutionRequest(
        tool_name="demo.policy.net_block",
        parameters={},
        runtime_kind="python",
    )
    res = executor.execute(req)
    assert res.status == "error"
    assert isinstance(res.result, dict)
    assert res.result.get("error") == "execution_policy_violation"
    issues = res.result.get("policy_issues") or []
    assert any(i.get("code") == "network_blocked_by_policy" for i in issues)


def test_tool_executor_allows_filesystem_access_within_allowed_roots(
    monkeypatch, tmp_path
):
    allowed = tmp_path / "allowed.txt"
    allowed.write_text("ok", encoding="utf-8")

    class Tool:
        EXAMPLES = []

        def get_tool_name(self) -> str:
            return "demo.policy.fs_allow"

        def get_tool_description(self) -> str:
            return "Reads a temp file under /tmp (allowed root)."

        def get_args_schema(self):
            return _Args

        def _run(self):
            return {
                "status": "success",
                "data": {"text": allowed.read_text(encoding="utf-8")},
            }

    executor = _make_executor(tool=Tool(), monkeypatch=monkeypatch, tmp_path=tmp_path)

    from brain_researcher.services.agent.tool_executor import ToolExecutionRequest

    req = ToolExecutionRequest(
        tool_name="demo.policy.fs_allow",
        parameters={},
        runtime_kind="python",
    )
    res = executor.execute(req)
    assert res.status == "success"
    assert isinstance(res.result, dict)
    assert res.result.get("status") == "success"
    assert res.result.get("data", {}).get("text") == "ok"


def test_mcp_execution_gate_uses_tools_policy_without_mcp_import(monkeypatch, tmp_path):
    import sys

    from brain_researcher.services.tools.spec import ToolSpec

    class Tool:
        EXAMPLES = []

        def get_tool_name(self) -> str:
            return "demo.policy.dangerous"

        def get_tool_description(self) -> str:
            return "Should be rejected before tool lookup executes."

        def get_args_schema(self):
            return _Args

        def _run(self):  # pragma: no cover - gate returns first
            raise AssertionError("tool should not execute")

    class FakeUnifiedToolRegistry:
        def get_toolspec_by_name(self, name: str):
            assert name == "demo.policy.dangerous"
            return ToolSpec(
                name=name,
                description="dangerous test spec",
                dangerous=True,
            )

    monkeypatch.setenv("BR_MCP_EXECUTION_GATE", "1")
    monkeypatch.delenv("BR_MCP_ALLOW_DANGEROUS", raising=False)

    import brain_researcher.services.tools.registry as registry_module

    monkeypatch.setattr(
        registry_module,
        "UnifiedToolRegistry",
        FakeUnifiedToolRegistry,
    )
    sys.modules.pop("brain_researcher.services.mcp.server", None)

    executor = _make_executor(tool=Tool(), monkeypatch=monkeypatch, tmp_path=tmp_path)

    from brain_researcher.services.agent.tool_executor import ToolExecutionRequest

    req = ToolExecutionRequest(
        tool_name="demo.policy.dangerous",
        parameters={},
        runtime_kind="python",
    )
    res = executor.execute(req)

    assert res.status == "error"
    assert res.error == "policy_rejected"
    assert "brain_researcher.services.mcp.server" not in sys.modules
