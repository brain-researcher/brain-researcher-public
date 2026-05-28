"""Regression tests for python import preflight checks."""

import sys
import types

from brain_researcher.services.agent.planner.catalog_loader import (
    PythonRunnerSpec,
    ResourceSpec,
    ToolCapability,
)
from brain_researcher.services.agent.planner.preflight import _check_python_import


def make_python_tool(module: str, func: str = "run") -> ToolCapability:
    """Helper to build a python ToolCapability."""
    return ToolCapability(
        id=f"python.test.{func}",
        name="python-test",
        package="python",
        runtime_kind="python",
        modality=["fmri"],
        capabilities=["test"],
        consumes=["timeseries"],
        produces=["connectivity_matrix"],
        resources=ResourceSpec(cpu_min=1, mem_mb_min=128, gpu=False, time_min_default=1.0),
        python=PythonRunnerSpec(module=module, function=func, entry_type="function"),
    )


def test_check_python_import_success(monkeypatch):
    """Module and function present -> success."""
    mod = types.ModuleType("brain_researcher.services.tools.fake_tool")
    mod.run = lambda: None  # type: ignore[attr-defined]
    sys.modules[mod.__name__] = mod
    try:
        tool = make_python_tool(mod.__name__, "run")
        result = _check_python_import(tool)
        assert result.passed is True
        assert "module imported successfully" in (result.detail or "")
    finally:
        sys.modules.pop(mod.__name__, None)


def test_check_python_import_missing_module(monkeypatch):
    """Missing module -> import failed."""
    tool = make_python_tool("brain_researcher.services.tools.missing_tool", "run")
    result = _check_python_import(tool)
    assert result.passed is False
    assert (result.status_code.value if result.status_code else "") in ("IMPORT_FAILED", "import_failed")
    assert "import failed" in (result.detail or "").lower()


def test_check_python_import_missing_function(monkeypatch):
    """Module present but function absent -> failure."""
    mod = types.ModuleType("brain_researcher.services.tools.fake_tool_nofunc")
    sys.modules[mod.__name__] = mod
    try:
        tool = make_python_tool(mod.__name__, "run")
        result = _check_python_import(tool)
        assert result.passed is False
        assert "function 'run' not found" in (result.detail or "")
    finally:
        sys.modules.pop(mod.__name__, None)
