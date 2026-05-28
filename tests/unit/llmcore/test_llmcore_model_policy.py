import sys
import types

from brain_researcher.services.agent.codegen.context import CodegenContext
from brain_researcher.services.agent.codegen.model_policy import (
    choose_model_for_code_task,
    select_model,
)


def test_llm_router_forwards_budget_id_to_gemini_router(monkeypatch):
    from brain_researcher.services.agent.router import (
        LLMChatResult,
        LLMRouteMetadata,
        LLMRouter,
    )

    router = LLMRouter(use_gemini_cli=True)
    captured = {}

    def fake_route_chat(**kwargs):
        captured.update(kwargs)
        return LLMChatResult(
            text="ok",
            metadata=LLMRouteMetadata(provider="google", model=kwargs["model_hint"]),
        )

    monkeypatch.setattr(router._gemini_router, "route_chat", fake_route_chat)

    result = router.route_chat(
        "hello",
        model_hint="gemini-3-flash-preview",
        budget_id="budget-1",
    )

    assert result.text == "ok"
    assert captured["budget_id"] == "budget-1"


def test_managed_gemini_uses_sdk_and_records_billable_cost(monkeypatch):
    from brain_researcher.services.agent.router import GeminiCLIRouter
    from brain_researcher.services.agent.credential_resolver import ResolvedCredential

    calls = {}

    class FakeGenerativeModel:
        def __init__(self, model):
            calls["model"] = model

        def generate_content(self, prompt):
            calls["prompt"] = prompt
            return types.SimpleNamespace(
                text="ok",
                usage_metadata=types.SimpleNamespace(
                    prompt_token_count=1000,
                    candidates_token_count=200,
                    total_token_count=1200,
                ),
            )

    fake_genai = types.ModuleType("google.generativeai")

    def fake_configure(*, api_key):
        calls["api_key"] = api_key

    fake_genai.configure = fake_configure
    fake_genai.GenerativeModel = FakeGenerativeModel
    google_pkg = types.ModuleType("google")
    google_pkg.generativeai = fake_genai
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)

    router = GeminiCLIRouter()
    result = router._attempt_gemini(
        prompt="hello",
        model="gemini-2.5-flash",
        route="primary",
        credential=ResolvedCredential(
            kind="managed_gemini",
            api_key="managed-key",
            metadata={"is_managed": True},
        ),
        thinking_budget=None,
        budget_id="budget-1",
    )

    assert result is not None
    assert result.text == "ok"
    assert calls == {
        "api_key": "managed-key",
        "model": "gemini-2.5-flash",
        "prompt": "hello",
    }
    assert result.metadata.credential == "managed_gemini"
    assert result.metadata.bill_to == "managed:budget-1"
    assert result.metadata.usage == {
        "prompt_tokens": 1000,
        "completion_tokens": 200,
        "total_tokens": 1200,
    }
    assert result.metadata.estimated_cost
    assert result.metadata.estimated_cost > 0


def test_choose_model_strict_json_prefers_gpt():
    ctx = CodegenContext(user_query="fix", instruction="fix")
    model = choose_model_for_code_task(ctx, prompt_tokens_estimate=10_000, strict_json=True)
    assert "gpt-5" in model


def test_choose_model_long_context_prefers_gemini():
    ctx = CodegenContext(user_query="refactor", instruction="refactor")
    model = choose_model_for_code_task(ctx, prompt_tokens_estimate=150_000, strict_json=False)
    assert "gemini" in model.lower()


def test_select_model_respects_hint():
    model = select_model("custom-model", task_type="code", strict_json=None, ctx_tokens=None, ctx=None)
    assert model == "custom-model"
