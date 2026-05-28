from __future__ import annotations

from brain_researcher.services.tools import rag_tools


def test_get_rag_system_returns_none_when_dependency_missing(monkeypatch):
    monkeypatch.setattr(rag_tools, "RAGKnowledgeSystem", None, raising=False)
    rag_tools._rag_system = None  # reset cache
    assert rag_tools.get_rag_system() is None


def test_pubmed_tool_reports_error_without_rag(monkeypatch):
    monkeypatch.setattr(rag_tools, "RAGKnowledgeSystem", None, raising=False)
    rag_tools._rag_system = None
    tool = rag_tools.PubMedSearchTool()

    result = tool._run(query_text="fmri")

    assert result.status == "error"
    assert "RAG system not available" in (result.error or "")
