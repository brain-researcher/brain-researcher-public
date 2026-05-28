"""Non-happy path tests for the coding agent codegen loop."""

from __future__ import annotations

from types import SimpleNamespace

from brain_researcher.services.agent.codegen.context import CodegenContext, ExecutionResult
from brain_researcher.services.agent.codegen.loop import CodegenLoop


def _wrap_patch(patch_text: str) -> str:
    return f"""
Here is the patch:
```
{patch_text}
```
"""


class SequenceRouter:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)

    def route_chat(self, *_, **__):
        if self._responses:
            text = self._responses.pop(0)
        else:
            text = ""
        return SimpleNamespace(
            text=text,
            metadata=SimpleNamespace(
                provider="test",
                model="test-model",
                usage={},
                fallback_reason=None,
            ),
        )


class FailingPatchWorkspace:
    def __init__(self, repo_root):
        self.repo_root = repo_root
        self._touched: list[str] = []

    def materialize_files(self, files):
        return None

    def apply_patch(self, patch_text: str):
        raise RuntimeError("patch failed")

    def run_checks(self, test_command=None):
        return ExecutionResult(success=True, stdout="", stderr="", exit_code=0)

    def files_touched(self):
        return self._touched or ["dummy.py"]


class FlakyTestWorkspace:
    def __init__(self, repo_root):
        self.repo_root = repo_root
        self._touched: list[str] = []
        self._runs = 0

    def materialize_files(self, files):
        return None

    def apply_patch(self, patch_text: str):
        self._touched.append("dummy.py")

    def run_checks(self, test_command=None):
        self._runs += 1
        if self._runs == 1:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="tests failed",
                exit_code=1,
            )
        return ExecutionResult(success=True, stdout="", stderr="", exit_code=0)

    def files_touched(self):
        return self._touched or ["dummy.py"]


class NoopWorkspace:
    def __init__(self, repo_root):
        self.repo_root = repo_root
        self._touched: list[str] = []

    def materialize_files(self, files):
        return None

    def apply_patch(self, patch_text: str):
        self._touched.append("dummy.py")

    def run_checks(self, test_command=None):
        return ExecutionResult(success=False, stdout="", stderr="tests failed", exit_code=1)

    def files_touched(self):
        return self._touched or ["dummy.py"]


class PermissionDeniedWorkspace(NoopWorkspace):
    def apply_patch(self, patch_text: str):
        raise PermissionError("Permission denied while applying patch")


class CommandNotFoundWorkspace(NoopWorkspace):
    def run_checks(self, test_command=None):
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="command not found",
            exit_code=127,
        )


class MissingDependencyWorkspace(NoopWorkspace):
    def run_checks(self, test_command=None):
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="ModuleNotFoundError: No module named 'foo'",
            exit_code=1,
        )


class EmptyStderrWorkspace(NoopWorkspace):
    def run_checks(self, test_command=None):
        return ExecutionResult(success=False, stdout="", stderr="", exit_code=1)


def test_codegen_loop_returns_failed_after_patch_apply_errors():
    patch = """--- foo.txt\n+++ foo.txt\n@@\n-foo\n+bar\n"""
    router = SequenceRouter([_wrap_patch(patch), _wrap_patch(patch)])
    events: list[tuple[str, dict]] = []

    loop = CodegenLoop(
        router,
        max_iters=2,
        workspace_cls=FailingPatchWorkspace,
        event_callback=lambda e, d: events.append((e, d)),
    )
    ctx = CodegenContext(user_query="test", instruction="apply patch", repo_root=".")

    result = loop.run(ctx)

    assert result.status == "failed"
    assert result.iterations == 2
    assert "patch failed" in (result.errors or "")
    assert any(
        ev[0] == "test" and ev[1].get("status") == "skipped" for ev in events
    )


def test_codegen_loop_recovers_after_test_failure():
    patch = """--- foo.txt\n+++ foo.txt\n@@\n-foo\n+bar\n"""
    router = SequenceRouter([_wrap_patch(patch), _wrap_patch(patch)])
    events: list[tuple[str, dict]] = []

    loop = CodegenLoop(
        router,
        max_iters=2,
        workspace_cls=FlakyTestWorkspace,
        event_callback=lambda e, d: events.append((e, d)),
    )
    ctx = CodegenContext(user_query="test", instruction="fix tests", repo_root=".")

    result = loop.run(ctx)

    assert result.status == "success"
    assert result.iterations == 2
    statuses = [ev[1].get("status") for ev in events if ev[0] == "test"]
    assert "failed" in statuses
    assert "passed" in statuses


def test_codegen_loop_blocks_patch_too_large():
    patch = "x" * 50
    router = SequenceRouter([_wrap_patch(patch)])
    events: list[tuple[str, dict]] = []

    loop = CodegenLoop(
        router,
        max_iters=1,
        patch_char_limit=10,
        workspace_cls=NoopWorkspace,
        event_callback=lambda e, d: events.append((e, d)),
    )
    ctx = CodegenContext(user_query="test", instruction="apply patch", repo_root=".")

    result = loop.run(ctx)

    assert result.status == "failed"
    assert "Patch too large" in (result.errors or "")
    assert any(ev[0] == "test" and ev[1].get("status") == "skipped" for ev in events)


def test_codegen_loop_blocks_patch_too_many_lines():
    patch = "\n".join(["x"] * 6)
    router = SequenceRouter([_wrap_patch(patch)])
    events: list[tuple[str, dict]] = []

    loop = CodegenLoop(
        router,
        max_iters=1,
        patch_line_limit=3,
        workspace_cls=NoopWorkspace,
        event_callback=lambda e, d: events.append((e, d)),
    )
    ctx = CodegenContext(user_query="test", instruction="apply patch", repo_root=".")

    result = loop.run(ctx)

    assert result.status == "failed"
    assert "Patch too large" in (result.errors or "")
    assert any(ev[0] == "test" and ev[1].get("status") == "skipped" for ev in events)


def test_codegen_loop_reports_permission_denied_on_patch():
    patch = """--- foo.txt\n+++ foo.txt\n@@\n-foo\n+bar\n"""
    router = SequenceRouter([_wrap_patch(patch)])

    loop = CodegenLoop(
        router,
        max_iters=1,
        workspace_cls=PermissionDeniedWorkspace,
    )
    ctx = CodegenContext(user_query="test", instruction="apply patch", repo_root=".")

    result = loop.run(ctx)

    assert result.status == "failed"
    assert "Permission denied" in (result.errors or "")


def test_codegen_loop_surfaces_command_not_found():
    patch = """--- foo.txt\n+++ foo.txt\n@@\n-foo\n+bar\n"""
    router = SequenceRouter([_wrap_patch(patch)])

    loop = CodegenLoop(
        router,
        max_iters=1,
        workspace_cls=CommandNotFoundWorkspace,
    )
    ctx = CodegenContext(user_query="test", instruction="run tests", repo_root=".")

    result = loop.run(ctx)

    assert result.status == "failed"
    assert "command not found" in (result.errors or "")


def test_codegen_loop_surfaces_missing_dependency():
    patch = """--- foo.txt\n+++ foo.txt\n@@\n-foo\n+bar\n"""
    router = SequenceRouter([_wrap_patch(patch)])

    loop = CodegenLoop(
        router,
        max_iters=1,
        workspace_cls=MissingDependencyWorkspace,
    )
    ctx = CodegenContext(user_query="test", instruction="run tests", repo_root=".")

    result = loop.run(ctx)

    assert result.status == "failed"
    assert "ModuleNotFoundError" in (result.errors or "")


def test_codegen_loop_uses_unknown_failure_when_stderr_empty():
    patch = """--- foo.txt\n+++ foo.txt\n@@\n-foo\n+bar\n"""
    router = SequenceRouter([_wrap_patch(patch)])

    loop = CodegenLoop(
        router,
        max_iters=1,
        workspace_cls=EmptyStderrWorkspace,
    )
    ctx = CodegenContext(user_query="test", instruction="run tests", repo_root=".")

    result = loop.run(ctx)

    assert result.status == "failed"
    assert result.errors == "Unknown execution failure"
