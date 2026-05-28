from __future__ import annotations

from brain_researcher.services.tools.literature_tool import GLMLiteratureTool


def test_resolve_file_search_store_prefers_multi_store_env(monkeypatch):
    monkeypatch.setenv(
        "BR_FILE_SEARCH_STORE_NAMES",
        "papers-fmri-oa-20152025-uni-aqus07ky5cos, brain-researcher-codebase-5i70bkfmcumj",
    )
    monkeypatch.delenv("FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("BR_FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("BR_GOOGLE_FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("GOOGLE_FILE_SEARCH_STORE", raising=False)

    assert GLMLiteratureTool._resolve_file_search_store(None) == (
        "papers-fmri-oa-20152025-uni-aqus07ky5cos,"
        "brain-researcher-codebase-5i70bkfmcumj"
    )


def test_resolve_file_search_store_override_wins(monkeypatch):
    monkeypatch.setenv("BR_FILE_SEARCH_STORE_NAMES", "papers,codebase")
    assert GLMLiteratureTool._resolve_file_search_store("explicit-store") == (
        "explicit-store"
    )
