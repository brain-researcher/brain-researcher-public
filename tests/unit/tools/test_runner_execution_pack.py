from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from brain_researcher.config.paths import get_outputs_root
from brain_researcher.services.mcp.execution_recipes import materialize_recipe_files
from brain_researcher.services.tools import runner
from brain_researcher.services.tools.tool_base import ToolResult


class _FakeTool:
    def _run(self, **kwargs):
        return ToolResult(status="success", data={"received": dict(kwargs)})


def _patch_runner_dependencies(monkeypatch):
    fake_registry = SimpleNamespace(get_tool=lambda tool_id: _FakeTool())
    monkeypatch.setattr(
        runner.ToolRegistry,
        "from_env",
        staticmethod(lambda light_mode=True: fake_registry),
    )
    monkeypatch.setattr(runner, "spec_from_tool", lambda tool: object())
    monkeypatch.setattr(
        runner,
        "enforce_allowed_paths",
        lambda spec, params, work_dir=None, output_dir=None: None,
    )
    monkeypatch.setattr(runner, "network_guard", lambda spec: nullcontext())


def test_default_execution_pack_dir_uses_outputs_root() -> None:
    path = runner._default_execution_pack_dir("test.tool", {})
    assert path == (
        get_outputs_root() / "execution_packs" / "test.tool_execution_pack"
    )


def test_execute_tool_emits_execution_pack_metadata_when_requested(
    monkeypatch, tmp_path
):
    _patch_runner_dependencies(monkeypatch)

    pack_dir = tmp_path / "pack"
    monkeypatch.setattr(
        runner,
        "materialize_execution_pack",
        lambda tool_id, params, workspace, target_runtime=None: {
            "tool_id": tool_id,
            "workspace": str(pack_dir),
            "run_pack": str(pack_dir / "run_pack.py"),
            "target_runtime": target_runtime or "python",
        },
    )

    result = runner.execute_tool(
        "test.tool",
        {"output_dir": str(tmp_path / "outputs")},
        emit_execution_pack=True,
    )

    assert result.status == "success"
    assert result.metadata is not None
    assert result.metadata["execution_pack"]["workspace"] == str(pack_dir)
    assert result.data is not None
    assert result.data["execution_pack"]["workspace"] == str(pack_dir)


def test_execute_tool_pack_materialization_error_is_nonfatal(monkeypatch, tmp_path):
    _patch_runner_dependencies(monkeypatch)

    def _raise(*args, **kwargs):
        raise ValueError("recipe unavailable")

    monkeypatch.setattr(runner, "materialize_execution_pack", _raise)

    result = runner.execute_tool(
        "test.tool",
        {"output_dir": str(tmp_path / "outputs")},
        emit_execution_pack=True,
    )

    assert result.status == "success"
    assert result.metadata is not None
    assert "recipe unavailable" in result.metadata["execution_pack_error"]


def test_materialize_recipe_files_writes_files_and_marks_shell_executable(tmp_path):
    workspace = materialize_recipe_files(
        {
            "files": {
                "run_pack.py": "print('ok')\n",
                "job.sh": "#!/usr/bin/env bash\necho ok\n",
            }
        },
        tmp_path / "pack",
    )

    run_pack = workspace / "run_pack.py"
    shell_script = workspace / "job.sh"
    assert run_pack.read_text(encoding="utf-8") == "print('ok')\n"
    assert shell_script.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
    assert shell_script.stat().st_mode & 0o111
