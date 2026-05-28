from brain_researcher.services.agent.codegen.context import FileSnippet
from brain_researcher.services.tools.llm_router_tool import CodingAgentTool


class DummyResult:
    def __init__(self):
        self.status = "success"
        self.response_text = "ok"
        self.patches = []
        self.files_touched = []
        self.iterations = 1
        self.exec_result = None
        self.errors = None
        self.provider = "test"
        self.model = "test-model"
        self.usage = {}
        self.fallback_reason = None


class DummyLoop:
    def __init__(self):
        self.last_context = None
        self.max_iters = 1

    def run(self, context, **kwargs):
        self.last_context = context
        return DummyResult()


def test_coding_agent_tool_enriches_context_with_fs(monkeypatch):
    dummy_loop = DummyLoop()

    # Patch FS helper to return a synthetic snippet
    def fake_build_fs_context_for_task_sync(**kwargs):
        return [
            FileSnippet(
                path="foo.py",
                snippet="print('hi')",
                language="python",
                start_line=1,
                end_line=1,
            )
        ]

    monkeypatch.setattr(
        "brain_researcher.services.tools.llm_router_tool.build_fs_context_for_task_sync",
        fake_build_fs_context_for_task_sync,
    )

    tool = CodingAgentTool()
    tool._code_loop = dummy_loop  # replace to avoid real LLM call

    result = tool._run(instruction="print hello", code_context=None, file_paths=None)

    assert result.status == "success"
    assert dummy_loop.last_context is not None
    assert dummy_loop.last_context.files
    assert dummy_loop.last_context.files[0].path == "foo.py"


def test_coding_agent_tool_gemini_only_sets_provider_lock(monkeypatch):
    dummy_loop = DummyLoop()
    tool = CodingAgentTool()
    tool._code_loop = dummy_loop

    result = tool._run(
        instruction="print hello",
        code_context=None,
        file_paths=None,
        auto_fs_context=False,
        gemini_only=True,
    )

    assert result.status == "success"
    assert dummy_loop.last_context is not None
    assert dummy_loop.last_context.provider_lock == "gemini"
    assert dummy_loop.last_context.model_hint is not None
    assert "gemini" in dummy_loop.last_context.model_hint.lower()


def test_coding_agent_tool_gemini_only_overrides_non_gemini_hint(monkeypatch):
    dummy_loop = DummyLoop()
    tool = CodingAgentTool()
    tool._code_loop = dummy_loop

    result = tool._run(
        instruction="print hello",
        code_context=None,
        file_paths=None,
        auto_fs_context=False,
        model_hint="gpt-5",
        gemini_only=True,
    )

    assert result.status == "success"
    assert dummy_loop.last_context is not None
    assert dummy_loop.last_context.provider_lock == "gemini"
    assert dummy_loop.last_context.model_hint is not None
    assert "gemini" in dummy_loop.last_context.model_hint.lower()
