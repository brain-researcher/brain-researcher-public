from brain_researcher.services.agent.codegen.context import CodegenResult, ExecutionResult
from brain_researcher.services.agent.codegen.render import render_result_for_chat


def test_render_success_message():
    result = CodegenResult(
        status="success",
        iterations=2,
        response_text="done",
        patches=["patch1"],
        files_touched=["a.py", "b.py"],
        exec_result=ExecutionResult(success=True, stdout="ok", stderr="", exit_code=0),
    )
    rendered = render_result_for_chat(result)
    assert "✅" in rendered
    assert "a.py" in rendered
    assert "Iterations: 2" in rendered


def test_render_failure_message():
    result = CodegenResult(
        status="failed",
        iterations=3,
        response_text="",
        patches=[],
        files_touched=["c.py"],
        exec_result=ExecutionResult(success=False, stdout="", stderr="boom", exit_code=1),
        errors="boom",
    )
    rendered = render_result_for_chat(result)
    assert "❌" in rendered
    assert "boom" in rendered
    assert "c.py" in rendered
