"""Unit tests for code tools and CodeOrchestrator."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from brain_researcher.services.agent.code_tool_registry import CodeToolRegistry
from brain_researcher.services.agent.code_tools import (
    ReadFileTool,
    ReadDirTool,
    ApplyPatchTool,
    CodeSearchTool,
    RunTestsTool,
    SandboxRunTool,
)
from brain_researcher.services.agent.code_tools.fs_tools import (
    _validate_path,
    _extract_patch_targets,
)


class TestValidatePath:
    """Test path validation helper."""

    def test_valid_path_under_root(self, tmp_path):
        """Paths under repo_root should be valid."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        assert _validate_path(subdir, tmp_path) is True

    def test_path_escape_rejected(self, tmp_path):
        """Paths outside repo_root should be rejected."""
        escape_path = tmp_path / ".." / "outside"
        assert _validate_path(escape_path, tmp_path) is False

    def test_absolute_path_outside_root(self, tmp_path):
        """Absolute paths outside root should be rejected."""
        outside = Path("/tmp/definitely-outside")
        assert _validate_path(outside, tmp_path) is False


class TestExtractPatchTargets:
    """Test patch target extraction."""

    def test_unified_diff_format(self):
        """Should extract target from unified diff."""
        patch = """--- a/old.py
+++ b/new.py
@@ -1,3 +1,4 @@
 line1
+added
 line2
"""
        targets = _extract_patch_targets(patch)
        assert "new.py" in targets

    def test_git_diff_format(self):
        """Should extract target from git diff format."""
        patch = """diff --git a/src/old.py b/src/new.py
--- a/src/old.py
+++ b/src/new.py
@@ -1 +1 @@
-old
+new
"""
        targets = _extract_patch_targets(patch)
        assert "src/new.py" in targets

    def test_dev_null_ignored(self):
        """Should ignore /dev/null targets."""
        patch = """+++ /dev/null
--- a/deleted.py
"""
        targets = _extract_patch_targets(patch)
        assert "/dev/null" not in targets


class TestCodeToolRegistry:
    """Test the code tool registry."""

    def test_list_tools_returns_six(self):
        """Registry should contain exactly 6 tools."""
        registry = CodeToolRegistry()
        tools = registry.list_tools()
        assert len(tools) == 6

    def test_get_tool_by_name(self):
        """Should retrieve tool by name."""
        registry = CodeToolRegistry()
        tool = registry.get_tool("code.fs.read_file")
        assert tool is not None
        assert tool.name == "code.fs.read_file"

    def test_unknown_tool_returns_none(self):
        """Should return None for unknown tool."""
        registry = CodeToolRegistry()
        tool = registry.get_tool("unknown.tool")
        assert tool is None


class TestReadFileTool:
    """Test ReadFileTool functionality."""

    def test_read_file_success(self, tmp_path):
        """Should read file within repo root."""
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        tool = ReadFileTool()
        result = tool.run(path=str(test_file), repo_root=str(tmp_path))

        assert result["status"] == "success"
        assert "print('hello')" in result["content"]

    def test_read_file_not_found(self, tmp_path):
        """Should return error for missing file."""
        tool = ReadFileTool()
        result = tool.run(path="nonexistent.py", repo_root=str(tmp_path))

        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    def test_reject_path_escape(self, tmp_path):
        """Should reject paths that escape repo_root."""
        tool = ReadFileTool()
        result = tool.run(path="../../../etc/passwd", repo_root=str(tmp_path))

        assert result["status"] == "error"
        assert "escape" in result["error"].lower()

    def test_line_range_filter(self, tmp_path):
        """Should respect line range parameters."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\nline4\n")

        tool = ReadFileTool()
        result = tool.run(
            path=str(test_file),
            repo_root=str(tmp_path),
            start_line=2,
            end_line=3,
        )

        assert result["status"] == "success"
        assert "line2" in result["content"]
        assert "line3" in result["content"]
        assert "line1" not in result["content"]


class TestReadDirTool:
    """Test ReadDirTool functionality."""

    def test_glob_pattern_success(self, tmp_path):
        """Should find files matching glob pattern."""
        (tmp_path / "test1.py").write_text("# test1")
        (tmp_path / "test2.py").write_text("# test2")
        (tmp_path / "other.txt").write_text("other")

        tool = ReadDirTool()
        result = tool.run(glob_pattern="*.py", repo_root=str(tmp_path))

        assert result["status"] == "success"
        assert result["count"] == 2

    def test_reject_absolute_path_pattern(self, tmp_path):
        """Should reject patterns starting with /."""
        tool = ReadDirTool()
        result = tool.run(glob_pattern="/etc/*.conf", repo_root=str(tmp_path))

        assert result["status"] == "error"
        assert "escape" in result["error"].lower()

    def test_reject_dotdot_pattern(self, tmp_path):
        """Should reject patterns with .. in them."""
        tool = ReadDirTool()
        result = tool.run(glob_pattern="../*.py", repo_root=str(tmp_path))

        assert result["status"] == "error"
        assert "escape" in result["error"].lower()


class TestApplyPatchTool:
    """Test ApplyPatchTool functionality."""

    def test_dry_run_success(self, tmp_path):
        """Should validate patch without applying in dry_run mode."""
        test_file = tmp_path / "test.py"
        test_file.write_text("old content\n")

        patch = f"""--- test.py
+++ test.py
@@ -1 +1 @@
-old content
+new content
"""
        tool = ApplyPatchTool()
        result = tool.run(patch=patch, dry_run=True, repo_root=str(tmp_path))

        # File should be unchanged
        assert test_file.read_text() == "old content\n"

    def test_reject_patch_escaping_repo(self, tmp_path):
        """Should reject patches targeting files outside repo_root."""
        patch = """--- /etc/passwd
+++ ../../../etc/passwd
@@ -1 +1 @@
-root:x:0:0
+hacked:x:0:0
"""
        tool = ApplyPatchTool()
        result = tool.run(patch=patch, dry_run=True, repo_root=str(tmp_path))

        assert result["status"] == "error"
        assert "escape" in result["error"].lower()


class TestCodeSearchTool:
    """Test CodeSearchTool functionality."""

    def test_search_finds_match(self, tmp_path):
        """Should find matching content."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello_world():\n    pass\n")

        tool = CodeSearchTool()
        result = tool.run(
            query="hello_world",
            glob_pattern="*.py",
            repo_root=str(tmp_path),
        )

        assert result["status"] == "success"
        assert result["count"] >= 1

    def test_reject_absolute_path_escape(self, tmp_path):
        """Should reject glob patterns starting with /."""
        tool = CodeSearchTool()
        result = tool.run(
            query="root",
            glob_pattern="/etc/*",
            repo_root=str(tmp_path),
        )

        assert result["status"] == "error"
        assert "escape" in result["error"].lower()

    def test_reject_dotdot_escape(self, tmp_path):
        """Should reject glob patterns with .. in them."""
        tool = CodeSearchTool()
        result = tool.run(
            query="content",
            glob_pattern="../*.py",
            repo_root=str(tmp_path),
        )

        assert result["status"] == "error"
        assert "escape" in result["error"].lower()


class TestRunTestsTool:
    """Test RunTestsTool functionality."""

    def test_allowed_command_pytest(self, tmp_path):
        """Should allow pytest commands."""
        tool = RunTestsTool()
        # This will fail because there are no tests, but command should be allowed
        result = tool.run(cmd="pytest --collect-only", repo_root=str(tmp_path))

        # Command was allowed, even if it fails to find tests
        assert result["status"] != "error" or "not allowed" not in result.get("error", "")

    def test_reject_disallowed_command(self, tmp_path):
        """Should reject commands that don't start with allowed prefix."""
        tool = RunTestsTool()
        result = tool.run(cmd="rm -rf /", repo_root=str(tmp_path))

        assert result["status"] == "error"
        assert "not allowed" in result["error"].lower()

    def test_reject_dangerous_patterns(self, tmp_path):
        """Should reject commands with dangerous patterns."""
        tool = RunTestsTool()

        # Test command chaining
        result = tool.run(cmd="pytest ; rm -rf /", repo_root=str(tmp_path))
        assert result["status"] == "error"
        assert "disallowed pattern" in result["error"].lower()

        # Test path escape
        result = tool.run(cmd="pytest ../../../etc/", repo_root=str(tmp_path))
        assert result["status"] == "error"
        assert "disallowed pattern" in result["error"].lower()

    def test_reject_python_c_flag(self, tmp_path):
        """Should reject python -c commands (arbitrary code execution)."""
        tool = RunTestsTool()

        # Test python -c (was previously allowed!)
        result = tool.run(cmd="python -c 'import os; os.system(\"rm -rf /\")'", repo_root=str(tmp_path))
        assert result["status"] == "error"
        assert "not allowed" in result["error"].lower() or "disallowed pattern" in result["error"].lower()

    def test_reject_python3_c_flag(self, tmp_path):
        """Should reject python3 -c commands (normalized to python -c)."""
        tool = RunTestsTool()

        # Test python3 -c (should be normalized and rejected)
        result = tool.run(cmd="python3 -c 'import os; print(os.getcwd())'", repo_root=str(tmp_path))
        assert result["status"] == "error"
        assert "not allowed" in result["error"].lower() or "disallowed pattern" in result["error"].lower()

    def test_reject_rootdir_equals_escape(self, tmp_path):
        """Should reject pytest --rootdir=/tmp (path escape via flag=value)."""
        tool = RunTestsTool()

        result = tool.run(cmd="pytest --rootdir=/tmp tests/", repo_root=str(tmp_path))
        assert result["status"] == "error"
        assert "escape" in result["error"].lower()

    def test_reject_rootdir_space_escape(self, tmp_path):
        """Should reject pytest --rootdir /tmp (path escape via flag value)."""
        tool = RunTestsTool()

        result = tool.run(cmd="pytest --rootdir /tmp tests/", repo_root=str(tmp_path))
        assert result["status"] == "error"
        assert "escape" in result["error"].lower()

    def test_reject_junitxml_path_escape(self, tmp_path):
        """Should reject pytest --junitxml=/tmp/out.xml (path escape via flag)."""
        tool = RunTestsTool()

        result = tool.run(cmd="pytest --junitxml=/tmp/out.xml tests/", repo_root=str(tmp_path))
        assert result["status"] == "error"
        assert "escape" in result["error"].lower()

    def test_allow_valid_paths_in_flags(self, tmp_path):
        """Should allow pytest with valid paths within repo_root."""
        tool = RunTestsTool()

        # Create a subdir within repo_root
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_dummy.py").write_text("def test_pass(): pass")

        # This should be allowed (--rootdir points within repo_root)
        result = tool.run(cmd=f"pytest --rootdir={tmp_path} tests/", repo_root=str(tmp_path))
        # Either succeeds or fails for non-escape reasons
        if result["status"] == "error":
            assert "escape" not in result["error"].lower()


class TestSandboxRunTool:
    """Test SandboxRunTool functionality."""

    def test_simple_expression(self):
        """Should evaluate and print simple expressions."""
        tool = SandboxRunTool()
        # exec mode doesn't return expression values, use print for verification
        result = tool.run(code="print(2 + 2)")

        assert result["status"] == "success"
        assert "4" in result["stdout"]

    def test_print_captured(self):
        """Should capture stdout from print statements."""
        tool = SandboxRunTool()
        result = tool.run(code="print('hello world')")

        assert result["status"] == "success"
        assert "hello world" in result["stdout"]

    def test_safe_imports_available(self):
        """Should have safe imports pre-loaded."""
        tool = SandboxRunTool()
        result = tool.run(code="len(json.dumps({'a': 1}))")

        assert result["status"] == "success"

    def test_output_truncation(self):
        """Should truncate very long output."""
        tool = SandboxRunTool()
        # Generate output longer than MAX_OUTPUT_SIZE (50000)
        result = tool.run(code="print('x' * 60000)")

        assert result["status"] == "success"
        assert len(result["stdout"]) <= 51000  # MAX_OUTPUT_SIZE + some buffer for truncation message
        assert "truncated" in result["stdout"]


class TestCodeOrchestratorEvents:
    """Test CodeOrchestrator event emission."""

    def test_emits_plan_patch_test_events(self):
        """CodeOrchestrator should emit plan/patch/test events via callback."""
        events_received: List[Dict[str, Any]] = []

        def capture_event(event: str, data: Dict[str, Any]):
            events_received.append({"event": event, "data": data})

        # Test that CodegenLoop accepts and uses event_callback
        from brain_researcher.services.agent.codegen.loop import CodegenLoop

        mock_router = MagicMock()
        mock_router.route_chat.return_value = MagicMock(
            text="```python\nprint('hello')\n```",
            metadata=MagicMock(provider="test", model="test", usage={}, fallback_reason=None),
        )

        loop = CodegenLoop(
            router=mock_router,
            max_iters=1,
            event_callback=capture_event,
        )

        # The loop should have the _emit method
        assert hasattr(loop, "_emit")
        assert callable(loop._emit)

        # Test that _emit works
        loop._emit("test_event", {"key": "value"})
        assert len(events_received) == 1
        assert events_received[0]["event"] == "test_event"

    def test_get_code_orchestrator_accepts_callback(self):
        """get_code_orchestrator should wire callback on a fresh instance per call."""
        from brain_researcher.services.agent.code_orchestrator import get_code_orchestrator

        events_a: List[Dict[str, Any]] = []

        def capture_a(event: str, data: Dict[str, Any]):
            events_a.append({"event": event, "data": data})

        orch_a = get_code_orchestrator(event_callback=capture_a)
        assert orch_a._emit == capture_a
        orch_a._emit("evt_a", {"a": True})
        assert len(events_a) == 1 and events_a[0]["event"] == "evt_a"

        events_b: List[Dict[str, Any]] = []

        def capture_b(event: str, data: Dict[str, Any]):
            events_b.append({"event": event, "data": data})

        orch_b = get_code_orchestrator(event_callback=capture_b)
        # Should be a different instance to avoid callback leakage
        assert orch_b is not orch_a
        assert orch_b._emit == capture_b
        orch_b._emit("evt_b", {"b": True})
        assert len(events_b) == 1 and events_b[0]["event"] == "evt_b"
