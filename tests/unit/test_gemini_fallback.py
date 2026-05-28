import types

from brain_researcher.services.agent.router import (
    GeminiCLIRouter,
    LLMChatResult,
    LLMRouteMetadata,
    LLMRouter,
)
from brain_researcher.services.agent.credential_resolver import ResolvedCredential
from brain_researcher.services.agent.utils import gemini_cli
from brain_researcher.services.agent.utils.gemini_fallback import (
    _set_router_for_testing,
    chat_with_fallback,
)


class DummyLLM:
    def __init__(self, text: str):
        self._text = text

    def invoke(self, prompt: str):
        return types.SimpleNamespace(content=self._text)


class StubResolver:
    def __init__(self, *, has_local=True):
        self.has_local = has_local

    def resolve_for_chat(
        self,
        model_hint=None,
        credential_name=None,
        budget_id=None,
        **kwargs,
    ):
        if model_hint and model_hint.lower().startswith("gemini") and self.has_local:
            return ResolvedCredential(kind="local_gemini", metadata={})
        return None


def test_fallback_to_flash(monkeypatch, request):
    # First gemini call (flash-preview) fails with quota, second (flash-lite) succeeds
    calls = {"count": 0}

    def fake_execute_chat(prompt, model, **kwargs):
        calls["count"] += 1
        if model == "gemini-3-flash-preview":
            raise gemini_cli.GeminiQuotaError("quota")
        return gemini_cli.GeminiResult(
            text="ok flash", usage={"total_tokens": 5}, model=model
        )

    monkeypatch.setattr(gemini_cli, "execute_chat", fake_execute_chat)

    resolver = StubResolver(has_local=True)
    router = LLMRouter(credential_resolver=resolver, use_gemini_cli=True)
    router._gemini_router = GeminiCLIRouter(credential_resolver=resolver)
    _set_router_for_testing(router)
    request.addfinalizer(lambda: _set_router_for_testing(LLMRouter()))

    text, provider, model_used, usage, reason = chat_with_fallback(
        "hi", initial_model="gemini-3-flash-preview"
    )
    assert text == "ok flash"
    assert provider == "google"
    assert model_used == "gemini-3.1-flash-lite-preview"
    assert usage.get("total_tokens") == 5
    assert calls["count"] == 2
    assert reason == "quota_exhausted"


def test_fallback_to_gpt(monkeypatch, request):
    # Both gemini fail, then GPT succeeds
    def fake_execute_chat(prompt, model, **kwargs):
        raise gemini_cli.GeminiQuotaError("quota")

    monkeypatch.setattr(gemini_cli, "execute_chat", fake_execute_chat)

    # Patch get_llm to return a dummy LLM
    import brain_researcher.services.agent.llm as llm_mod

    monkeypatch.setattr(llm_mod, "get_llm", lambda model=None: DummyLLM("gpt ok"))
    monkeypatch.setattr(
        "brain_researcher.services.agent.router.get_llm",
        lambda model=None: DummyLLM("gpt ok"),
    )

    resolver = StubResolver(has_local=True)
    router = LLMRouter(credential_resolver=resolver, use_gemini_cli=True)
    router._gemini_router = GeminiCLIRouter(credential_resolver=resolver)
    _set_router_for_testing(router)
    request.addfinalizer(lambda: _set_router_for_testing(LLMRouter()))

    text, provider, model_used, usage, reason = chat_with_fallback(
        "hi", initial_model="gemini-3-flash-preview"
    )
    assert text == "gpt ok"
    assert provider == "openai"
    assert model_used == "gpt-5"
    assert usage == {}
    assert reason in {"quota_exhausted", "exception"}


def test_gemini_provider_lock_omits_gpt_from_cascade():
    router = GeminiCLIRouter(credential_resolver=StubResolver(has_local=True))
    cascade = tuple(
        router._cascade_for("gemini-3-flash-preview", provider_lock="gemini")
    )
    assert cascade == ("gemini-3-flash-preview", "gemini-3.1-flash-lite-preview")
    assert all("gpt" not in model for model in cascade)


def test_gemini_code_task_keeps_explicit_hint_and_omits_flash_lite():
    router = GeminiCLIRouter(credential_resolver=StubResolver(has_local=True))
    cascade = tuple(router._cascade_for("gemini-2.0-flash", task_type="code"))
    assert cascade == ("gemini-2.0-flash", "gemini-3-flash-preview", "gpt-5")
    assert all("flash-lite" not in model for model in cascade)


def test_gemini_provider_lock_code_task_omits_flash_lite():
    router = GeminiCLIRouter(credential_resolver=StubResolver(has_local=True))
    cascade = tuple(
        router._cascade_for(
            "gemini-2.0-flash",
            provider_lock="gemini",
            task_type="code",
        )
    )
    assert cascade == ("gemini-2.0-flash", "gemini-3-flash-preview")
    assert all("flash-lite" not in model for model in cascade)


def test_llm_router_provider_lock_forces_gemini_model():
    captured: dict[str, str] = {}

    class StubGeminiRouter:
        def route_chat(self, **kwargs):
            captured["model_hint"] = kwargs.get("model_hint")
            captured["provider_lock"] = kwargs.get("provider_lock")
            return LLMChatResult(
                text="ok",
                metadata=LLMRouteMetadata(
                    provider="google",
                    model=kwargs.get("model_hint") or "gemini-3-flash-preview",
                ),
            )

    router = LLMRouter(use_gemini_cli=True)
    router._gemini_router = StubGeminiRouter()
    result = router.route_chat(
        "hello",
        model_hint="gpt-5",
        provider_lock="gemini",
    )

    assert result.metadata.provider == "google"
    assert "gemini" in result.metadata.model.lower()
    assert captured["provider_lock"] == "gemini"
    assert "gemini" in captured["model_hint"].lower()


def test_llm_router_code_task_defaults_to_coding_model(monkeypatch):
    captured: dict[str, str | None] = {}

    class StubGeminiRouter:
        def route_chat(self, **kwargs):
            captured["model_hint"] = kwargs.get("model_hint")
            return LLMChatResult(
                text="ok",
                metadata=LLMRouteMetadata(
                    provider="google",
                    model=kwargs.get("model_hint") or "gemini-3-flash-preview",
                ),
            )

    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gemini-3.1-flash-lite-preview")
    monkeypatch.setenv("DEFAULT_CODING_MODEL", "gemini-3-flash-preview")
    router = LLMRouter(use_gemini_cli=True)
    router._gemini_router = StubGeminiRouter()

    result = router.route_chat("write code", task_type="code")

    assert result.metadata.model == "gemini-3-flash-preview"
    assert captured["model_hint"] == "gemini-3-flash-preview"
