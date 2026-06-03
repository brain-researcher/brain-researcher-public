"""Structural tests for `notebooks/templates/behavior_task_builder.py`.

These tests are pattern-matched on the other notebook template tests in this
directory. They do not spin up a marimo kernel. Instead they import the
template module and inspect its marimo ``App`` cell graph to assert:

* the file imports without syntax errors,
* cells have no duplicate `defs` (marimo would fail at runtime otherwise),
* every unresolved ref is either a builtin or defined by a sibling cell,
* the five behavior tool names are reachable via `_behavior_execute(...)` calls,
* the approval gate preconditions are wired into the `generate` cell.
"""

from __future__ import annotations

import ast
import os
from collections import Counter
from pathlib import Path

import pytest


TEMPLATE_PATH = (
    Path(__file__).resolve().parents[3]
    / "notebooks"
    / "templates"
    / "behavior_task_builder.py"
)

EXPECTED_TOOL_NAMES = {
    "behavior.paradigm_planner",
    "behavior.resolve_task_spec",
    "behavior.validate_task_spec",
    "behavior.generate_psyflow_task",
    "behavior.ingest_psyflow_run",
}


def _iter_app_cells():
    from notebooks.templates.behavior_task_builder import app

    return list(app._cell_manager.cells())


def test_template_imports_cleanly() -> None:
    import notebooks.templates.behavior_task_builder as mod  # noqa: F401

    assert hasattr(mod, "app"), "marimo App instance missing"


def test_cell_graph_has_no_duplicate_defs() -> None:
    cells = _iter_app_cells()
    all_defs = [d for c in cells for d in c.defs]
    dup = {k: v for k, v in Counter(all_defs).items() if v > 1}
    assert not dup, f"marimo would reject duplicate defs across cells: {dup}"


def test_cell_graph_references_are_resolvable() -> None:
    cells = _iter_app_cells()
    defined = {d for c in cells for d in c.defs}
    # Builtins and common types marimo does not count as cross-cell refs but
    # surfaces through `refs` in older versions. Whitelist a minimal set.
    builtin_whitelist = {
        "bool",
        "dict",
        "float",
        "getattr",
        "int",
        "isinstance",
        "len",
        "list",
        "str",
        "tuple",
    }
    for cell in cells:
        unresolved = [
            r for r in cell.refs if r not in defined and r not in builtin_whitelist
        ]
        assert not unresolved, (
            f"cell {cell.name!r} references undefined names: {unresolved}"
        )


def test_template_references_every_expected_tool_name_via_behavior_execute() -> None:
    """Each behavior.* tool must be called via `_behavior_execute(...)`."""

    source = TEMPLATE_PATH.read_text()
    tree = ast.parse(source)

    executed_tool_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_behavior_execute = isinstance(func, ast.Name) and func.id == "_behavior_execute"
        if not is_behavior_execute:
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            executed_tool_names.add(first.value)

    missing = EXPECTED_TOOL_NAMES - executed_tool_names
    assert not missing, (
        f"expected _behavior_execute(...) calls for: {sorted(missing)}; "
        f"found: {sorted(executed_tool_names)}"
    )


def test_template_uses_no_br_call_invocations() -> None:
    """The approval-gate flow must route through tool_execute, not raw MCP calls."""

    source = TEMPLATE_PATH.read_text()
    tree = ast.parse(source)

    br_call_names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "call"
            and isinstance(func.value, ast.Name)
            and func.value.id == "br"
        ):
            if node.args and isinstance(node.args[0], ast.Constant):
                br_call_names.append(str(node.args[0].value))
            else:
                br_call_names.append("<dynamic>")

    assert not br_call_names, (
        "template must not use br.call() for behavior tools; "
        f"found: {br_call_names}"
    )


def test_template_uses_no_raw_br_execute_invocations() -> None:
    source = TEMPLATE_PATH.read_text()
    tree = ast.parse(source)

    br_execute_names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "execute"
            and isinstance(func.value, ast.Name)
            and func.value.id == "br"
        ):
            if node.args and isinstance(node.args[0], ast.Constant):
                br_execute_names.append(str(node.args[0].value))
            else:
                br_execute_names.append("<dynamic>")

    assert not br_execute_names, (
        "template must route behavior execution through _behavior_execute(); "
        f"found raw br.execute() calls: {br_execute_names}"
    )


def test_generate_cell_enforces_approval_preconditions() -> None:
    """The `generate` cell must block on empty digest / unchecked approval."""

    cells = _iter_app_cells()
    generate = next((c for c in cells if c.name == "generate"), None)
    assert generate is not None, "generate cell is missing"

    # Cell code is compiled; re-parse the source to check precondition strings.
    source = TEMPLATE_PATH.read_text()
    tree = ast.parse(source)
    gen_func = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "generate"
        ),
        None,
    )
    assert gen_func is not None

    literal_strings: list[str] = []
    for node in ast.walk(gen_func):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literal_strings.append(node.value)

    blob = " ".join(literal_strings)
    assert "approval checkbox is unchecked" in blob
    assert "validator did not return a digest" in blob
    assert "reviewer name is empty" in blob
    assert "output root is empty" in blob


def test_generate_cell_uses_force_true_to_skip_cache() -> None:
    """Generate and ingest are side-effecting — they must bypass the SDK cache."""

    source = TEMPLATE_PATH.read_text()
    tree = ast.parse(source)

    forced_execute_tool_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_behavior_execute = (
            isinstance(func, ast.Name) and func.id == "_behavior_execute"
        )
        if not is_behavior_execute or not node.args:
            continue
        force_kw = next((kw for kw in node.keywords if kw.arg == "force"), None)
        if force_kw is None:
            continue
        if isinstance(force_kw.value, ast.Constant) and force_kw.value.value is True:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                forced_execute_tool_names.add(first.value)

    required = {
        "behavior.generate_psyflow_task",
        "behavior.ingest_psyflow_run",
    }
    missing = required - forced_execute_tool_names
    assert not missing, (
        "side-effecting behavior tools must pass force=True to _behavior_execute; "
        f"missing: {sorted(missing)}"
    )


def test_unwrap_helper_handles_tool_level_failure() -> None:
    """The setup-block `_unwrap` helper must flag inner ToolResult errors."""

    from notebooks.templates import behavior_task_builder as mod

    class _FakeOk:
        ok = True
        output = {"status": "success", "data": {"paradigm": "n_back"}}

    class _FakeToolFail:
        ok = True
        output = {"status": "error", "error": "approval_gate_failed", "data": {}}

    class _FakeMcpFail:
        ok = False
        output = {"error": "unknown_tool"}

    # Helper is defined inside `with app.setup:` so it lives on the module.
    unwrap = getattr(mod, "_unwrap", None)
    assert unwrap is not None, "_unwrap helper must be module-level for tests"

    ok, data, err = unwrap(_FakeOk())
    assert ok and data == {"paradigm": "n_back"} and err is None

    ok, _, err = unwrap(_FakeToolFail())
    assert not ok and err == "approval_gate_failed"

    ok, _, err = unwrap(_FakeMcpFail())
    assert not ok and err == "unknown_tool"


def test_behavior_execute_helper_uses_local_stdio_client(monkeypatch) -> None:
    from notebooks.templates import behavior_task_builder as mod

    mod._behavior_client = None
    init_calls = []
    execute_calls = []

    class FakeClient:
        def __init__(self, server_command=None, mcp_http_url=None, mcp_http_headers=None):
            init_calls.append(
                {
                    "server_command": server_command,
                    "mcp_http_url": mcp_http_url,
                    "mcp_http_headers": mcp_http_headers,
                }
            )

        def execute(self, tool_id, params=None, **kwargs):
            execute_calls.append(
                {
                    "tool_id": tool_id,
                    "params": params,
                    "kwargs": kwargs,
                }
            )
            return {"ok": True}

    monkeypatch.setattr(mod.br, "BRClient", FakeClient)
    with monkeypatch.context() as m:
        m.setenv("BR_MCP_TRANSPORT", "streamable-http")
        m.setenv("BR_MCP_HTTP_URL", "https://${PUBLIC_HOSTNAME}/mcp")
        m.delenv("BR_MCP_ENABLE_TOOL_EXECUTE", raising=False)
        m.delenv("BR_MCP_TOOL_EXECUTE_ALLOWLIST", raising=False)
        m.setenv("BR_RUNTIME_SEMANTIC_MATCHING", "1")
        m.chdir(Path("/tmp"))
        result = mod._behavior_execute(
            "behavior.resolve_task_spec",
            {"paradigm": "n_back", "overrides": {}},
        )

    assert result == {"ok": True}
    assert init_calls and init_calls[0]["mcp_http_url"] is None
    assert init_calls[0]["server_command"][1:] == [
        "-m",
        "brain_researcher.services.mcp.server",
    ]
    assert execute_calls == [
        {
            "tool_id": "behavior.resolve_task_spec",
            "params": {"paradigm": "n_back", "overrides": {}},
            "kwargs": {"work_dir": "/tmp", "force": False},
        }
    ]


def test_behavior_mcp_env_context_restores_process_env(monkeypatch) -> None:
    from notebooks.templates import behavior_task_builder as mod

    monkeypatch.setenv("BR_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("BR_MCP_HTTP_URL", "https://${PUBLIC_HOSTNAME}/mcp")
    monkeypatch.setenv("BR_MCP_ENABLE_TOOL_EXECUTE", "0")
    monkeypatch.setenv("BR_MCP_TOOL_EXECUTE_ALLOWLIST", "extract_timeseries")
    monkeypatch.setenv("BR_MCP_ALLOWED_ROOTS", "/srv/data")
    monkeypatch.setenv("BR_RUNTIME_SEMANTIC_MATCHING", "1")
    monkeypatch.chdir(Path("/tmp"))

    with mod._behavior_mcp_env():
        expected_roots = [
            "/srv/data",
            str((mod.REPO_ROOT / "artifacts").resolve()),
            str((mod.REPO_ROOT / "data").resolve()),
            str((mod.REPO_ROOT / "tmp").resolve()),
            "/tmp",
        ]
        assert os.environ["BR_MCP_TRANSPORT"] == "stdio"
        assert os.environ["BR_MCP_HTTP_URL"] == ""
        assert os.environ["BR_MCP_ENABLE_TOOL_EXECUTE"] == "1"
        assert os.environ["BR_MCP_TOOL_EXECUTE_ALLOWLIST"] == (
            "extract_timeseries,behavior.*"
        )
        assert os.environ["BR_MCP_ALLOWED_ROOTS"] == ",".join(expected_roots)
        assert os.environ["BR_RUNTIME_SEMANTIC_MATCHING"] == "0"

    assert os.environ["BR_MCP_TRANSPORT"] == "streamable-http"
    assert os.environ["BR_MCP_HTTP_URL"] == "https://${PUBLIC_HOSTNAME}/mcp"
    assert os.environ["BR_MCP_ENABLE_TOOL_EXECUTE"] == "0"
    assert os.environ["BR_MCP_TOOL_EXECUTE_ALLOWLIST"] == "extract_timeseries"
    assert os.environ["BR_MCP_ALLOWED_ROOTS"] == "/srv/data"
    assert os.environ["BR_RUNTIME_SEMANTIC_MATCHING"] == "1"


def test_resolve_workspace_path_normalizes_relative_input(monkeypatch) -> None:
    from notebooks.templates import behavior_task_builder as mod

    monkeypatch.chdir(Path("/tmp"))
    resolved = mod._resolve_workspace_path("./behavior_tasks")
    assert resolved == "/tmp/behavior_tasks"


def test_behavior_mcp_env_preserves_server_default_roots(monkeypatch) -> None:
    from notebooks.templates import behavior_task_builder as mod

    monkeypatch.delenv("BR_MCP_ALLOWED_ROOTS", raising=False)
    monkeypatch.chdir(Path("/tmp"))

    with mod._behavior_mcp_env():
        roots = os.environ["BR_MCP_ALLOWED_ROOTS"].split(",")

    assert str((mod.REPO_ROOT / "artifacts").resolve()) in roots
    assert str((mod.REPO_ROOT / "data").resolve()) in roots
    assert str((mod.REPO_ROOT / "tmp").resolve()) in roots
    assert "/tmp" in roots


@pytest.mark.parametrize(
    "cell_name",
    [
        "_intro",
        "inputs",
        "plan",
        "resolve",
        "validate",
        "digest_display",
        "generate",
        "ingest_stub",
    ],
)
def test_expected_cells_are_present(cell_name: str) -> None:
    cells = {c.name for c in _iter_app_cells()}
    assert cell_name in cells, f"missing cell {cell_name!r}; have {sorted(cells)}"
