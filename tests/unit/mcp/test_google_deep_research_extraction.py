import sys
from types import SimpleNamespace


def test_google_deep_research_assembles_candidate_parts_and_grounding_sources(
    monkeypatch,
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)
    monkeypatch.setattr(
        srv,
        "call_mcp_platform_api_with_fee",
        lambda call, **_kwargs: call(),
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    partial_text = "The n-back task is primarily used to measure **working"
    full_parts = [
        "The n-back task is primarily used to measure working memory updating.",
        "It also engages sustained attention and executive control.",
        "Increasing n changes online maintenance and manipulation demands.",
    ]

    class FakeGoogleSearch:
        def __init__(self, exclude_domains=None):
            self.exclude_domains = exclude_domains

    class FakeTool:
        def __init__(self, google_search):
            self.google_search = google_search

    class FakeGenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeResponse:
        text = partial_text
        candidates = [
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text=full_parts[0]),
                        SimpleNamespace(text=full_parts[1]),
                    ]
                ),
            ),
            SimpleNamespace(
                content=SimpleNamespace(parts=[SimpleNamespace(text=full_parts[2])]),
            ),
        ]

        @staticmethod
        def model_dump():
            return {
                "text": partial_text,
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": full_parts[0]},
                                {"text": full_parts[1]},
                            ]
                        },
                        "grounding_metadata": {
                            "grounding_chunks": [
                                {
                                    "web": {
                                        "uri": "https://example.org/n-back-review",
                                        "title": "N-back review",
                                    }
                                }
                            ]
                        },
                    },
                    {
                        "content": {"parts": [{"text": full_parts[2]}]},
                        "groundingMetadata": {
                            "groundingChunks": [
                                {
                                    "web": {
                                        "uri": "https://example.org/working-memory",
                                        "title": "Working memory source",
                                    }
                                }
                            ]
                        },
                    },
                ],
            }

    class FakeModels:
        @staticmethod
        def generate_content(**_kwargs):
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
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    resp = srv.google_deep_research(
        query="What is the n-back task used to measure in cognitive neuroscience?",
        max_output_tokens=512,
    )

    assert resp["ok"] is True
    data = resp["data"]
    expected_text = "\n".join(full_parts)
    assert data["text"] == expected_text
    assert data["synthesis_full_text"] == expected_text
    assert data["summary"] == expected_text
    assert partial_text not in data["text"]
    assert data["sources"] == [
        {"url": "https://example.org/n-back-review", "title": "N-back review"},
        {
            "url": "https://example.org/working-memory",
            "title": "Working memory source",
        },
    ]
    assert data["diagnostics"]["source_count"] == 2
    assert data["diagnostics"]["summary_truncated"] is False
