import os
import time

import pytest


@pytest.mark.integration
@pytest.mark.network
@pytest.mark.requires_api
def test_google_deep_research_interactions_smoke(monkeypatch):
    """Smoke-test Gemini Interactions API via MCP Deep Research start/get.

    Requires:
    - BR_REAL_DEEP_RESEARCH=1
    - GOOGLE_API_KEY or GEMINI_API_KEY
    Optional:
    - BR_GOOGLE_FILE_SEARCH_STORE / GOOGLE_FILE_SEARCH_STORE
    """
    if os.getenv("BR_REAL_DEEP_RESEARCH") != "1":
        pytest.skip("Set BR_REAL_DEEP_RESEARCH=1 to run real Deep Research API test")

    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        pytest.skip("Set GOOGLE_API_KEY or GEMINI_API_KEY to run real Deep Research API test")

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)

    store = os.getenv("BR_GOOGLE_FILE_SEARCH_STORE") or os.getenv("GOOGLE_FILE_SEARCH_STORE")
    store_names = [store] if store else None

    resp = srv.google_deep_research_start(
        input="Summarize recent neuroimaging QA tooling. Provide 3 bullets.",
        store_names=store_names,
    )
    if not resp.get("ok"):
        if resp.get("error") == "interactions_not_supported":
            pytest.skip("google-genai Interactions API not available in this env")
        pytest.fail(f"Deep research start failed: {resp}")

    interaction_id = resp.get("data", {}).get("interaction_id")
    assert interaction_id, f"Missing interaction_id in response: {resp}"

    # One or two polling attempts to verify get() path works end-to-end.
    last = None
    for _ in range(2):
        last = srv.google_deep_research_get(interaction_id)
        if not last.get("ok"):
            if last.get("error") == "interactions_not_supported":
                pytest.skip("google-genai Interactions API not available in this env")
            pytest.fail(f"Deep research get failed: {last}")
        status = last.get("data", {}).get("status")
        if status:
            break
        time.sleep(1.0)

    assert last is not None
    assert last.get("data", {}).get("interaction_id")
