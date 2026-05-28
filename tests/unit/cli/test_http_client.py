from __future__ import annotations

from brain_researcher.cli.utils.http_client import get_orchestrator_url


def test_get_orchestrator_url_prefers_shared_internal_envs(monkeypatch) -> None:
    monkeypatch.setenv("BR_ORCHESTRATOR_URL", "http://brain-researcher-orchestrator:3001")
    monkeypatch.setenv("ORCHESTRATOR_URL", "http://legacy-orchestrator:9999")

    assert get_orchestrator_url() == "http://brain-researcher-orchestrator:3001"


def test_get_orchestrator_url_ignores_browser_public_envs(monkeypatch) -> None:
    monkeypatch.delenv("BR_ORCHESTRATOR_URL", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_API", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_URL", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_API_URL", raising=False)
    monkeypatch.setenv("NEXT_PUBLIC_ORCHESTRATOR_URL", "https://public-orchestrator.example.com")
    monkeypatch.setenv("NEXT_PUBLIC_API_URL", "https://legacy-public.example.com")

    assert get_orchestrator_url() == "http://localhost:3001"
