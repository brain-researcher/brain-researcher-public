from brain_researcher.services.agent.codegen.model_policy import select_model


def test_select_model_prefers_gpt_for_strict_json(monkeypatch):
    monkeypatch.delenv("DEFAULT_CODING_MODEL", raising=False)
    monkeypatch.delenv("CODE_AGENT_MODEL", raising=False)
    monkeypatch.delenv("DEFAULT_LLM_MODEL", raising=False)
    model = select_model(None, task_type="code", strict_json=True, ctx_tokens=10_000)
    assert model == "gpt-5"


def test_select_model_prefers_gemini_for_long_context(monkeypatch):
    monkeypatch.delenv("DEFAULT_CODING_MODEL", raising=False)
    monkeypatch.delenv("CODE_AGENT_MODEL", raising=False)
    monkeypatch.delenv("DEFAULT_LLM_MODEL", raising=False)
    model = select_model(None, task_type="code", strict_json=False, ctx_tokens=150_000)
    assert "gemini" in model


def test_select_model_non_code_passthrough():
    model = select_model("deepseek-chat", task_type="chat", strict_json=False, ctx_tokens=1_000)
    assert model == "deepseek-chat"


def test_select_model_uses_env_override(monkeypatch):
    monkeypatch.setenv("DEFAULT_CODING_MODEL", "env-model")
    model = select_model(None, task_type="code", strict_json=True, ctx_tokens=1_000)
    assert model == "env-model"
