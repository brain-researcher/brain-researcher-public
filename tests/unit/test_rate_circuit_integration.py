import types

import pytest

from brain_researcher.services.agent.router import GeminiCLIRouter, LLMRouter
from brain_researcher.services.agent import telemetry
from brain_researcher.services.agent.credential_resolver import ResolvedCredential
from brain_researcher.services.agent.utils import gemini_cli
from brain_researcher.services.agent.utils.gemini_fallback import (
    chat_with_fallback,
    _set_router_for_testing,
)


@pytest.fixture(autouse=True)
def _stub_telemetry(monkeypatch):
    monkeypatch.setattr(telemetry, "record_event", lambda *a, **k: None)


class FakeLimiter:
    def __init__(self, fail_first_n=1):
        self.remaining_fails = fail_first_n

    def try_acquire(self):
        if self.remaining_fails > 0:
            self.remaining_fails -= 1
            from brain_researcher.services.agent.utils.rate_limit import (
                RateLimitExceeded,
            )

            raise RateLimitExceeded("test exceed")


class FakeBreaker:
    def __init__(self, fail=False):
        self.fail = fail

    def call(self, func):
        if self.fail:
            raise RuntimeError("breaker open")
        return func()


class DummyLLM:
    def __init__(self, text: str):
        self._text = text

    def invoke(self, prompt: str):
        return types.SimpleNamespace(content=self._text)


class StubResolver:
    """Resolver that yields the same credential type for all Gemini requests."""

    def __init__(self, *, local=True, openai=False):
        self.local = local
        self.openai = openai

    def resolve_for_chat(
        self,
        model_hint=None,
        credential_name=None,
        budget_id=None,
        **kwargs,
    ):
        if model_hint and model_hint.lower().startswith("gemini") and self.local:
            return ResolvedCredential(kind="local_gemini", metadata={})
        if model_hint and model_hint.lower().startswith("gpt") and self.openai:
            return ResolvedCredential(
                kind="byok_openai",
                api_key="stub",
                metadata={"source": "test"},
            )
        return None


def test_rate_limit_skips_to_next(monkeypatch, request):
    # Limit first Gemini attempt, then allow second (flash-lite)
    import brain_researcher.services.agent.utils.gemini_fallback as gf

    resolver = StubResolver(local=True)
    router = LLMRouter(credential_resolver=resolver, use_gemini_cli=True)
    router._gemini_router = GeminiCLIRouter(
        credential_resolver=resolver,
        rate_limiter=FakeLimiter(fail_first_n=1),
        circuit_breaker=FakeBreaker(fail=False),
    )
    _set_router_for_testing(router)
    request.addfinalizer(lambda: _set_router_for_testing(LLMRouter()))

    def fake_execute_chat(prompt, model, **kwargs):
        if model == "gemini-3.1-flash-lite-preview":
            return gemini_cli.GeminiResult(
                text="ok after rate", usage={"total_tokens": 2}, model=model
            )
        raise AssertionError(
            "Flash-preview call should have been rate-limited before execute_chat"
        )

    monkeypatch.setattr(gemini_cli, "execute_chat", fake_execute_chat)

    text, provider, model_used, usage, reason = chat_with_fallback(
        "hi", initial_model="gemini-3-flash-preview"
    )
    assert text == "ok after rate"
    assert provider == "google"
    assert model_used == "gemini-3.1-flash-lite-preview"
    assert reason == "local_rate_limited"


def test_breaker_opens_then_gpt(monkeypatch, request):
    import brain_researcher.services.agent.utils.gemini_fallback as gf

    resolver = StubResolver(local=True, openai=False)
    router = LLMRouter(credential_resolver=resolver, use_gemini_cli=True)
    router._gemini_router = GeminiCLIRouter(
        credential_resolver=resolver,
        rate_limiter=FakeLimiter(fail_first_n=0),
        circuit_breaker=FakeBreaker(fail=True),
    )
    _set_router_for_testing(router)
    request.addfinalizer(lambda: _set_router_for_testing(LLMRouter()))

    # Patch get_llm to return a dummy LLM
    import brain_researcher.services.agent.llm as llm_mod
    from brain_researcher.services.agent import router as router_mod

    monkeypatch.setattr(llm_mod, "get_llm", lambda model=None: DummyLLM("from gpt"))
    monkeypatch.setattr(router_mod, "get_llm", lambda model=None: DummyLLM("from gpt"))

    text, provider, model_used, usage, reason = chat_with_fallback(
        "hi", initial_model="gemini-3-flash-preview"
    )
    assert text == "from gpt"
    assert provider == "openai"
    assert model_used == "gpt-5"
    assert reason in {"circuit_open", "exception"}
