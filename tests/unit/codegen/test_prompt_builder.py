from brain_researcher.services.agent.codegen.context import CodegenContext, FileSnippet
from brain_researcher.services.agent.codegen.prompt_builder import build_prompt


def test_prompt_builder_includes_core_sections():
    ctx = CodegenContext(
        user_query="fix bug",
        instruction="fix bug",
        code_context="def foo(): pass",
        plan_steps=[{"step_number": 1, "description": "do x"}],
        files=[FileSnippet(path="app.py", snippet="print('hi')", language="python")],
    )

    prompt = build_prompt(ctx, mode="fresh")

    assert "User Request" in prompt
    assert "Constitution" in prompt
    assert "Plan" in prompt
    assert "Relevant Files" in prompt
    assert "def foo" in prompt
    assert "Silent failure is unacceptable" in prompt
    assert "Failed Cases Matter More" in prompt


def test_prompt_builder_truncates_long_context():
    long_code = "x" * 5000
    ctx = CodegenContext(user_query="", instruction="", code_context=long_code)
    prompt = build_prompt(ctx, mode="fresh")

    # Should be truncated with ellipsis marker
    assert "(truncated)" in prompt
