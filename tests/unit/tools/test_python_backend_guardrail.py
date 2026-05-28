from __future__ import annotations

from brain_researcher.services.tools.executor import (
    PYTHON_BACKEND_UNRESOLVABLE,
    TOOL_REGISTRY_MISCONFIGURED,
    _resolve_workflow_runtime_tool,
    audit_python_backend_configuration,
)
from brain_researcher.services.tools.spec import ToolSpec


def test_resolve_workflow_runtime_tool_uses_cached_runtime_registry(monkeypatch):
    class _RuntimeRegistry:
        def get_tool(self, name: str):
            return {"tool": name}

    monkeypatch.setattr(
        "brain_researcher.services.tools.catalog_loader.is_workflow_tool_id",
        lambda _name: True,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.executor._workflow_runtime_registry",
        lambda: _RuntimeRegistry(),
    )

    resolved = _resolve_workflow_runtime_tool("workflow_visual_decoding")

    assert resolved == {"tool": "workflow_visual_decoding"}


def test_audit_python_backend_flags_missing_python_class(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.tools.executor._resolve_workflow_runtime_tool",
        lambda _name: None,
    )
    spec = ToolSpec(
        name="python.misconfigured_tool",
        description="stub",
        backend="python",
        python_class=None,
    )

    issue = audit_python_backend_configuration(spec)
    assert issue is not None
    assert issue["code"] == TOOL_REGISTRY_MISCONFIGURED
    assert issue["reason_code"] == PYTHON_BACKEND_UNRESOLVABLE
    assert "missing python_class" in issue["message"]


def test_audit_python_backend_allows_workflow_runtime_fallback(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.tools.executor._resolve_workflow_runtime_tool",
        lambda _name: object(),
    )
    spec = ToolSpec(
        name="workflow_example",
        description="stub",
        backend="python",
        python_class=None,
    )

    assert audit_python_backend_configuration(spec) is None


def test_audit_python_backend_flags_unresolvable_python_class(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.tools.executor._resolve_python_tool_instance",
        lambda _spec: None,
    )
    spec = ToolSpec(
        name="python.broken_class",
        description="stub",
        backend="python",
        python_class="missing.module.Class",
    )

    issue = audit_python_backend_configuration(spec)
    assert issue is not None
    assert issue["code"] == TOOL_REGISTRY_MISCONFIGURED
    assert issue["reason_code"] == PYTHON_BACKEND_UNRESOLVABLE
    assert "missing.module.Class" in issue["message"]
