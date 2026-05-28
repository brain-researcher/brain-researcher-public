"""Smoke test for MCP Google File Search (real API)."""

from __future__ import annotations

import os

import pytest


def test_google_file_search_list_stores_smoke(monkeypatch):
    if os.getenv("BR_REAL_FILE_SEARCH") != "1":
        pytest.skip("Set BR_REAL_FILE_SEARCH=1 to run real File Search API test")
    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        pytest.skip("Set GOOGLE_API_KEY or GEMINI_API_KEY to run real File Search API test")

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOW_NETWORK", True)

    resp = srv.google_file_search(operation="list_stores", page_size=5)

    assert resp["ok"] is True
    assert resp["result"]["status"] == "success"
