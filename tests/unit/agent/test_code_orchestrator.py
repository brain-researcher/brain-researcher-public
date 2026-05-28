"""Unit tests for the coding agent tools and orchestrator."""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

import brain_researcher.services.agent.codegen.loop as codegen_loop
from brain_researcher.services.agent.codegen.context import ExecutionResult
from brain_researcher.services.agent.codegen.loop import CodegenLoop
from brain_researcher.services.agent.code_orchestrator import CodeOrchestrator
from brain_researcher.services.agent.code_tool_registry import CodeToolRegistry
from brain_researcher.services.agent.code_tools.fs_tools import ApplyPatchTool, ReadFileTool
from brain_researcher.services.agent.code_tools.sandbox_tool import SandboxRunTool, MAX_OUTPUT_SIZE
from brain_researcher.services.agent.code_tools.search_tool import CodeSearchTool
from brain_researcher.services.agent.code_tools.test_tool import RunTestsTool


# ---------------------------------------------------------------------------
# Registry basics
# ---------------------------------------------------------------------------


class TestCodeToolRegistry:
    def test_list_tools_returns_six(self):
        registry = CodeToolRegistry()
        tools = set(registry.list_tools())
        assert tools == {
            "code.fs.read_file",
            "code.fs.read_dir",
            "code.fs.apply_patch",
            "code.search",
            "code.shell.run_tests",
            "code.sandbox.run",
        }

    def test_execute_read_file_success(self, tmp_path):
        file_path = tmp_path / "sample.txt"
        file_path.write_text("hello")

        registry = CodeToolRegistry()
        result = registry.execute(
            "code.fs.read_file",
            {"path": str(file_path), "repo_root": str(tmp_path)},
        )

        assert result["status"] == "success"
        assert "hello" in result["content"]

    def test_execute_read_file_not_found(self, tmp_path):
        registry = CodeToolRegistry()
        missing = tmp_path / "missing.txt"

        result = registry.execute(
            "code.fs.read_file",
            {"path": str(missing), "repo_root": str(tmp_path)},
        )

        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# File tools
# ---------------------------------------------------------------------------


class TestReadFileTool:
    def test_read_within_repo_root(self, tmp_path):
        file_path = tmp_path / "a.txt"
        file_path.write_text("line1\nline2\nline3\n")

        tool = ReadFileTool()
        res = tool.run(path=str(file_path), repo_root=str(tmp_path))

        assert res["status"] == "success"
        assert "line2" in res["content"]

    def test_reject_path_escape(self, tmp_path):
        tool = ReadFileTool()
        res = tool.run(path="../evil.txt", repo_root=str(tmp_path))
        assert res["status"] == "error"
        assert "Path escape rejected" in res["error"]

    def test_line_range_filter(self, tmp_path):
        file_path = tmp_path / "b.txt"
        file_path.write_text("a\nb\nc\n")

        tool = ReadFileTool()
        res = tool.run(
            path=str(file_path),
            repo_root=str(tmp_path),
            start_line=2,
            end_line=3,
        )

        assert res["status"] == "success"
        assert res["content"] == "b\nc\n"


class TestApplyPatchTool:
    def test_dry_run_success(self, tmp_path):
        target = tmp_path / "hello.txt"
        target.write_text("hello\n")

        patch = textwrap.dedent(
            """
            --- hello.txt
            +++ hello.txt
            @@ -1 +1 @@
            -hello
            +world
            """
        )

        tool = ApplyPatchTool()
        res = tool.run(patch=patch, dry_run=True, repo_root=str(tmp_path))

        assert res["status"] == "success"
        assert res["dry_run"] is True

    def test_dry_run_failure(self, tmp_path):
        target = tmp_path / "hello.txt"
        target.write_text("hello\n")

        bad_patch = textwrap.dedent(
            """
            --- hello.txt
            +++ hello.txt
            @@
            -missing
            +world
            """
        )

        tool = ApplyPatchTool()
        res = tool.run(patch=bad_patch, dry_run=True, repo_root=str(tmp_path))

        assert res["status"] == "error"

    def test_reject_patch_escaping_repo(self, tmp_path):
        patch = textwrap.dedent(
            """
            --- ../evil.txt
            +++ ../evil.txt
            @@
            -a
            +b
            """
        )

        tool = ApplyPatchTool()
        res = tool.run(patch=patch, dry_run=True, repo_root=str(tmp_path))

        assert res["status"] == "error"
        assert "Path escape" in res["error"]


# ---------------------------------------------------------------------------
# Search tool
# ---------------------------------------------------------------------------


class TestCodeSearchTool:
    def test_search_finds_match(self, tmp_path):
        (tmp_path / "one.txt").write_text("alpha beta")
        (tmp_path / "two.txt").write_text("alpha gamma")

        tool = CodeSearchTool()
        res = tool.run(
            "alpha",
            glob_pattern="*.txt",
            repo_root=str(tmp_path),
            context_lines=0,
        )

        assert res["status"] == "success"
        assert res["count"] == 2

    def test_search_respects_max_matches(self, tmp_path):
        (tmp_path / "one.txt").write_text("alpha beta")
        (tmp_path / "two.txt").write_text("alpha gamma")

        tool = CodeSearchTool()
        res = tool.run(
            "alpha",
            glob_pattern="*.txt",
            max_matches=1,
            context_lines=0,
            repo_root=str(tmp_path),
        )

        assert res["status"] == "success"
        assert len(res["matches"]) == 1

    def test_reject_absolute_path_escape(self, tmp_path):
        tool = CodeSearchTool()
        res = tool.run("alpha", glob_pattern="/etc/passwd", repo_root=str(tmp_path))
        assert res["status"] == "error"


# ---------------------------------------------------------------------------
# Run tests tool
# ---------------------------------------------------------------------------


class TestRunTestsTool:
    def test_allowed_command_py_compile(self, tmp_path):
        script = tmp_path / "mod.py"
        script.write_text("x = 1\n")

        tool = RunTestsTool()
        res = tool.run(
            cmd=f"python -m py_compile {script.name}",
            repo_root=str(tmp_path),
        )

        assert res["status"] == "success"
        assert res["success"] is True

    def test_reject_disallowed_command(self, tmp_path):
        tool = RunTestsTool()
        res = tool.run(cmd="rm -rf /", repo_root=str(tmp_path))

        assert res["status"] == "error"

    def test_timeout_handling(self, tmp_path):
        test_file = tmp_path / "sleep_test.py"
        test_file.write_text(
            "import time\nimport unittest\n\n"
            "class SleepTest(unittest.TestCase):\n"
            "    def test_sleep(self):\n"
            "        time.sleep(5)\n"
        )

        tool = RunTestsTool()
        res = tool.run(
            cmd="python -m unittest sleep_test.SleepTest.test_sleep",
            repo_root=str(tmp_path),
            timeout=1,
        )

        assert res["status"] == "timeout"


# ---------------------------------------------------------------------------
# Sandbox tool
# ---------------------------------------------------------------------------


class TestSandboxRunTool:
    def test_simple_expression(self):
        tool = SandboxRunTool()
        res = tool.run("1+1", timeout=5)

        assert res["status"] == "success"
        assert res["result"] in {None, "2", "None"}

    def test_timeout_kills_infinite_loop(self):
        tool = SandboxRunTool()
        res = tool.run("while True: pass", timeout=1)

        assert res["status"] == "timeout"

    def test_output_truncation(self):
        tool = SandboxRunTool()
        res = tool.run("print('x'*60000)", timeout=5)

        assert res["status"] == "success"
        assert len(res["stdout"]) <= MAX_OUTPUT_SIZE + 50
        assert "truncated" in res["stdout"]


# ---------------------------------------------------------------------------
# Code orchestrator
# ---------------------------------------------------------------------------


class FakeRouter:
    def __init__(self, text: str):
        self.text = text

    def route_chat(self, *args, **kwargs):
        return SimpleNamespace(
            text=self.text,
            metadata=SimpleNamespace(
                provider="test",
                model="test-model",
                usage={},
                fallback_reason=None,
            ),
        )


class FakeWorkspace:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.touched: list[str] = []

    def materialize_files(self, files):  # pragma: no cover - no-op for tests
        return None

    def apply_patch(self, patch: str):
        self.touched.append("dummy.py")

    def run_checks(self, test_command=None) -> ExecutionResult:
        return ExecutionResult(success=True, stdout="", stderr="", exit_code=0)

    def files_touched(self):
        return self.touched or ["dummy.py"]


class TestCodeOrchestrator:
    def test_run_task_returns_code_result(self, monkeypatch, tmp_path):
        patch_text = textwrap.dedent(
            """
            here is the patch
            ```
            --- dummy.py
            +++ dummy.py
            @@
            -print("a")
            +print("b")
            ```
            """
        )

        events: list[tuple[str, dict]] = []

        monkeypatch.setattr(codegen_loop, "build_prompt", lambda ctx, mode="fresh": "prompt")
        monkeypatch.setattr(
            codegen_loop,
            "choose_model_for_code_task",
            lambda ctx, prompt_tokens_estimate, strict_json=True: "test-model",
        )

        loop = CodegenLoop(
            FakeRouter(patch_text),
            workspace_cls=FakeWorkspace,
            event_callback=lambda e, d: events.append((e, d)),
        )

        orchestrator = CodeOrchestrator(event_callback=lambda e, d: events.append((e, d)))
        orchestrator._code_loop = loop

        ctx = {
            "repo_root": str(tmp_path),
            "auto_fs_context": False,
            "apply": False,
            "dry_run": True,
        }

        result = orchestrator.run_task("update dummy", ctx, thread_id="t1")

        assert result.status == "success"
        assert result.requires_confirmation is True
        assert any(ev[0] == "plan" for ev in events)
        assert any(ev[0] == "patch" for ev in events)
        assert any(ev[0] == "test" for ev in events)
        assert any(ev[0] == "done" for ev in events)
