from dataclasses import dataclass

import pytest

from brain_researcher.services.agent.codegen.context import CodegenContext, ExecutionResult
from brain_researcher.services.agent.codegen.loop import CodegenLoop


@dataclass
class DummyMeta:
    provider: str = "openai"
    model: str = "gpt-5"
    usage: dict = None
    fallback_reason: str | None = None


@dataclass
class DummyResult:
    text: str
    metadata: DummyMeta


class DummyRouter:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def route_chat(self, *args, **kwargs):
        resp = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return resp


class DummyWorkspace:
    def __init__(self, repo_root):
        self.repo_root = repo_root
        self.apply_calls = 0
        self._materialized = []
        self._touched = []

    def materialize_files(self, files):
        self._materialized.extend(files)

    def apply_patch(self, patch_text):
        self.apply_calls += 1
        # no-op; pretend patch applied

    def run_checks(self, test_command=None):
        return ExecutionResult(success=True, stdout="", stderr="", exit_code=0)

    def files_touched(self):
        return self._touched or ["foo.py"]


def test_loop_stops_on_success():
    router = DummyRouter([DummyResult("```diff\n+ok\n```", DummyMeta())])
    loop = CodegenLoop(router, max_iters=3, workspace_cls=DummyWorkspace)
    ctx = CodegenContext(user_query="", instruction="do it", file_paths=["foo.py"], code_context=None)
    result = loop.run(ctx)

    assert result.status == "success"
    assert result.iterations == 1
    assert result.patches, "should extract patch fenced code"


def test_loop_retries_on_failure():
    router = DummyRouter([DummyResult("attempt1", DummyMeta()), DummyResult("attempt2", DummyMeta())])

    class FlakyWorkspace(DummyWorkspace):
        def __init__(self, repo_root):
            super().__init__(repo_root)
            self.outcomes = [False, True]

        def run_checks(self, test_command=None):
            success = self.outcomes.pop(0)
            return ExecutionResult(success=success, stdout="", stderr="boom" if not success else "", exit_code=0)

    loop = CodegenLoop(router, max_iters=2, workspace_cls=FlakyWorkspace)
    ctx = CodegenContext(user_query="", instruction="", file_paths=["foo.py"], code_context=None)
    result = loop.run(ctx)

    assert result.status == "success"
    assert result.iterations == 2
    assert router.calls == 2


def test_loop_rejects_oversized_patch():
    router = DummyRouter([DummyResult("```diff\n" + ("x" * 5000) + "\n```", DummyMeta())])

    loop = CodegenLoop(router, max_iters=1, workspace_cls=DummyWorkspace, patch_char_limit=100, patch_line_limit=50)
    ctx = CodegenContext(user_query="", instruction="big patch", file_paths=["foo.py"], code_context=None)
    result = loop.run(ctx)

    assert result.status == "failed"
    assert "too large" in (result.errors or "")
