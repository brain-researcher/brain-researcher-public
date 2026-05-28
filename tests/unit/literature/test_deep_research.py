from datetime import datetime, timezone
import sys
from types import SimpleNamespace

from brain_researcher.core.literature import deep_research


def test_idempotency_key_stable():
    key1 = deep_research.build_idempotency_key(
        query="test query",
        intent="deep_research",
        recency_days=180,
        top_k=10,
        exclude_domains=["example.com"],
        language="en",
        provider="google_deep_research",
        model=None,
    )
    key2 = deep_research.build_idempotency_key(
        query="test query",
        intent="deep_research",
        recency_days=180,
        top_k=10,
        exclude_domains=["example.com"],
        language="en",
        provider="google_deep_research",
        model=None,
    )
    assert key1 == key2


def test_start_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_DEEP_RESEARCH_DIR", str(tmp_path))
    key = deep_research.build_idempotency_key(
        query="cached query",
        intent="deep_research",
        recency_days=180,
        top_k=10,
        exclude_domains=[],
        language="en",
        provider="google_deep_research",
        model=None,
    )
    deep_research.save_result(
        key,
        {"status": "ok", "summary": "cached", "documents": [], "claims": [], "raw": {}},
    )

    called = {"value": False}

    def _fake_start_google(**kwargs):
        called["value"] = True
        return {"ok": True, "data": {"interaction_id": "int1", "status": "pending"}}

    monkeypatch.setattr(deep_research, "_provider_start_google", _fake_start_google)

    result = deep_research.deep_research_start({"query": "cached query", "idempotency_key": key})
    assert result["status"] == "cached"
    assert result.get("cached") is True
    assert result["result"]["search_trails"][-1]["status"] == "cached"
    assert called["value"] is False


def test_start_rejects_deepxiv_even_if_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_DEEP_RESEARCH_DIR", str(tmp_path))
    key = deep_research.build_idempotency_key(
        query="cached query",
        intent="deep_research",
        recency_days=180,
        top_k=10,
        exclude_domains=[],
        language="en",
        provider="deepxiv",
        model=None,
    )
    deep_research.save_result(
        key,
        {
            "status": "ok",
            "summary": "cached",
            "documents": [],
            "claims": [],
            "raw": {},
        },
    )

    result = deep_research.deep_research_start(
        {"query": "cached query", "provider": "deepxiv"}
    )
    assert result["status"] == "error"
    assert result["error"] == "unsupported_provider"
    assert "cached" not in result


def test_sync_uses_env_default_provider_when_omitted(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_DEEP_RESEARCH_DIR", str(tmp_path))
    monkeypatch.setenv("BR_LITERATURE_PROVIDER", "deepxiv")

    expected = {
        "status": "ok",
        "idempotency_key": "deepxiv-idempotency",
        "result": {"status": "ok", "metadata": {"provider": "deepxiv"}},
    }

    def _fake_sync_deepxiv(request, *, idempotency_key):
        assert request.get("provider") is None
        assert idempotency_key
        return expected

    monkeypatch.setattr(deep_research, "_provider_sync_deepxiv", _fake_sync_deepxiv)

    result = deep_research.deep_research_sync({"query": "default provider route"})
    assert result == expected


def test_get_parses_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_DEEP_RESEARCH_DIR", str(tmp_path))
    key = deep_research.build_idempotency_key(
        query="another query",
        intent="deep_research",
        recency_days=180,
        top_k=10,
        exclude_domains=[],
        language="en",
        provider="google_deep_research",
        model=None,
    )

    def _fake_get_google(interaction_id: str):
        return {
            "ok": True,
            "data": {
                "interaction_id": interaction_id,
                "status": "completed",
                "response": {"text": "See https://example.com for details."},
            },
        }

    monkeypatch.setattr(deep_research, "_provider_get_google", _fake_get_google)

    result = deep_research.deep_research_get(interaction_id="int2", idempotency_key=key)
    assert result["status"] == "ok"
    assert result["result"]["documents"][0]["url"] == "https://example.com"
    assert result["result"]["synthesis_full_text"]
    assert result["result"]["search_trails"][-1]["stage"] == "poll"
    cached = deep_research.load_cached_result(key)
    assert cached is not None
    assert cached["summary"]


def test_get_extracts_citations_from_nested_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_DEEP_RESEARCH_DIR", str(tmp_path))
    key = deep_research.build_idempotency_key(
        query="decoding evidence",
        intent="deep_research",
        recency_days=180,
        top_k=10,
        exclude_domains=[],
        language="en",
        provider="google_deep_research",
        model=None,
    )

    def _fake_get_google(interaction_id: str):
        return {
            "ok": True,
            "data": {
                "interaction_id": interaction_id,
                "status": "completed",
                "response": {
                    "output": [
                        {
                            "content": [
                                {"text": "Executive summary without inline URL text."}
                            ],
                            "grounding_metadata": {
                                "grounding_chunks": [
                                    {
                                        "web": {
                                            "uri": "https://example.org/decoding-paper",
                                            "title": "Decoding paper",
                                        }
                                    },
                                    {
                                        "web": {
                                            "uri": "https://openneuro.org/datasets/ds000001",
                                            "title": "OpenNeuro dataset",
                                        }
                                    },
                                ]
                            },
                        }
                    ]
                },
            },
        }

    monkeypatch.setattr(deep_research, "_provider_get_google", _fake_get_google)

    result = deep_research.deep_research_get(
        interaction_id="int-citations", idempotency_key=key
    )
    assert result["status"] == "ok"
    urls = {doc["url"] for doc in result["result"]["documents"]}
    assert "https://example.org/decoding-paper" in urls
    assert "https://openneuro.org/datasets/ds000001" in urls
    quality = result["result"]["quality"]
    assert quality["citable_count"] >= 2
    assert quality["primary_count"] >= 1


def test_get_completed_with_empty_payload_marks_partial(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_DEEP_RESEARCH_DIR", str(tmp_path))
    key = deep_research.build_idempotency_key(
        query="empty response case",
        intent="deep_research",
        recency_days=180,
        top_k=10,
        exclude_domains=[],
        language="en",
        provider="google_deep_research",
        model=None,
    )

    def _fake_get_google(interaction_id: str):
        return {
            "ok": True,
            "data": {
                "interaction_id": interaction_id,
                "status": "completed",
                "response": {
                    "candidates": [
                        {"content": {"parts": [{"inline_data": {"x": 1}}]}}
                    ]
                },
            },
        }

    monkeypatch.setattr(deep_research, "_provider_get_google", _fake_get_google)

    result = deep_research.deep_research_get(
        interaction_id="int-empty", idempotency_key=key
    )
    assert result["status"] == "partial"
    payload = result["result"]
    assert payload["status_reason"] == "insufficient_content"
    assert payload["quality"]["has_text"] is False
    assert payload["quality"]["citable_count"] == 0
    assert payload["quality"]["primary_count"] == 0


def test_find_text_ignores_opaque_tokens_and_prefers_readable_content():
    token = "AUZIYQHBP-_O0sJIC0t9o9UyReI9jtsA6aLpvXi4nWfb7SIxGxvgB-PSt4oAICiZe"
    payload = {
        "summary": token,
        "output": [{"content": [{"text": "Readable synthesis text from Gemini output."}]}],
    }
    assert (
        deep_research._find_text(payload)  # type: ignore[attr-defined]
        == "Readable synthesis text from Gemini output."
    )


def test_get_completed_merges_pending_search_trails(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_DEEP_RESEARCH_DIR", str(tmp_path))
    key = "trail-merge-key"
    deep_research.save_pending(
        key,
        {
            "interaction_id": "int-trails",
            "search_trails": [
                {
                    "stage": "start",
                    "tool": "google_deep_research_start",
                    "status": "running",
                    "detail": "start",
                }
            ],
        },
    )

    def _fake_get_google(interaction_id: str):
        return {
            "ok": True,
            "data": {
                "interaction_id": interaction_id,
                "status": "completed",
                "response": {"text": "Completed with trail merge."},
            },
        }

    monkeypatch.setattr(deep_research, "_provider_get_google", _fake_get_google)
    result = deep_research.deep_research_get(interaction_id="int-trails", idempotency_key=key)
    trails = result["result"].get("search_trails") or []
    assert any(item.get("stage") == "start" for item in trails)
    assert any(item.get("stage") == "poll" for item in trails)


def test_get_returns_error_for_cancelled_terminal_status(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_DEEP_RESEARCH_DIR", str(tmp_path))
    key = "cancelled-terminal-key"
    deep_research.save_pending(
        key,
        {
            "interaction_id": "int-cancelled",
            "search_trails": [
                {
                    "stage": "start",
                    "tool": "google_deep_research_start",
                    "status": "pending",
                    "detail": "start",
                }
            ],
        },
    )

    def _fake_get_google(interaction_id: str):
        return {
            "ok": True,
            "data": {
                "interaction_id": interaction_id,
                "status": "cancelled",
                "response": {"message": "Interaction cancelled by user."},
            },
        }

    monkeypatch.setattr(deep_research, "_provider_get_google", _fake_get_google)
    result = deep_research.deep_research_get(
        interaction_id="int-cancelled", idempotency_key=key
    )

    assert result["status"] == "error"
    assert result["error"] == "interaction_cancelled"
    assert result["interaction_status"] == "cancelled"
    assert "cancelled" in result["message"].lower()
    pending = deep_research.load_pending(key)
    assert pending is not None
    assert pending["status"] == "cancelled"
    assert pending.get("terminal_error")


def test_save_pending_serializes_datetime_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_DEEP_RESEARCH_DIR", str(tmp_path))
    key = "pending-datetime"
    deep_research.save_pending(
        key,
        {"interaction_id": "int-1", "created_at": datetime.now(timezone.utc)},
    )
    pending = deep_research.load_pending(key)
    assert pending is not None
    assert isinstance(pending["created_at"], str)
    assert "T" in pending["created_at"]


def test_provider_start_google_retries_with_fallback_agent(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("BR_DEEP_RESEARCH_FALLBACK_AGENT", "deep-research")
    attempted_agents = []

    class FakeAgentError(RuntimeError):
        def __init__(self, message: str, status_code: int):
            super().__init__(message)
            self.status_code = status_code

    class FakeInteraction:
        id = "int-fallback"
        status = "pending"

        @staticmethod
        def model_dump():
            return {"id": "int-fallback", "status": "pending"}

    class FakeInteractions:
        @staticmethod
        def create(**kwargs):
            attempted_agents.append(kwargs.get("agent"))
            if kwargs.get("agent") == "invalid-agent":
                raise FakeAgentError("Invalid agent: invalid-agent", 400)
            return FakeInteraction()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.interactions = FakeInteractions()

    fake_genai = SimpleNamespace(Client=FakeClient)

    original_google = sys.modules.get("google")
    sys.modules["google"] = SimpleNamespace(genai=fake_genai)
    try:
        result = deep_research._provider_start_google(
            prompt="test prompt",
            agent="invalid-agent",
            file_search_store_names=None,
            previous_interaction_id=None,
        )
    finally:
        if original_google is None:
            sys.modules.pop("google", None)
        else:
            sys.modules["google"] = original_google

    assert result["ok"] is True
    assert attempted_agents == ["invalid-agent", "deep-research"]
    assert result["data"]["agent"] == "deep-research"
    assert result["data"]["fallback_agent_used"] is True


def test_resolve_file_search_stores_prefers_multi_store_env(monkeypatch):
    monkeypatch.setenv(
        "BR_FILE_SEARCH_STORE_NAMES",
        "papers-fmri-oa-20152025-uni-aqus07ky5cos, brain-researcher-codebase-5i70bkfmcumj",
    )
    monkeypatch.delenv("FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("BR_FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("BR_GOOGLE_FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("GOOGLE_FILE_SEARCH_STORE", raising=False)

    assert deep_research._resolve_file_search_stores(None) == [
        "fileSearchStores/papers-fmri-oa-20152025-uni-aqus07ky5cos",
        "fileSearchStores/brain-researcher-codebase-5i70bkfmcumj",
    ]


def test_sync_falls_back_when_google_search_exclude_domains_unsupported(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("BR_DEEP_RESEARCH_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeGoogleSearch:
        def __init__(self, **kwargs):
            if "exclude_domains" in kwargs:
                raise TypeError("exclude_domains unsupported")

    class FakeTool:
        def __init__(self, google_search):
            self.google_search = google_search

    class FakeGenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeResponse:
        text = "See https://example.com for details."

        @staticmethod
        def model_dump():
            return {"text": FakeResponse.text}

    class FakeModels:
        @staticmethod
        def generate_content(**kwargs):
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.models = FakeModels()

    fake_genai = SimpleNamespace(
        Client=FakeClient,
        types=SimpleNamespace(
            GoogleSearch=FakeGoogleSearch,
            Tool=FakeTool,
            GenerateContentConfig=FakeGenerateContentConfig,
        ),
    )

    original_google = sys.modules.get("google")
    sys.modules["google"] = SimpleNamespace(genai=fake_genai)
    try:
        result = deep_research.deep_research_sync(
            {
                "query": "fMRI decoding",
                "exclude_domains": ["example.com"],
            }
        )
    finally:
        if original_google is None:
            sys.modules.pop("google", None)
        else:
            sys.modules["google"] = original_google

    assert result["status"] == "ok"
    docs = result["result"]["documents"]
    assert docs and docs[0]["url"] == "https://example.com"
