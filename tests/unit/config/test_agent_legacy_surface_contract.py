from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_legacy_agent_langgraph_owner_lives_under_legacy_package() -> None:
    legacy_path = REPO_ROOT / "src/brain_researcher/legacy/agent/web_service_langgraph.py"
    shim_path = REPO_ROOT / "src/brain_researcher/services/agent/web_service_langgraph.py"

    assert legacy_path.exists()
    assert not shim_path.exists()

    legacy_text = legacy_path.read_text(encoding="utf-8")

    assert "Legacy LangGraph compatibility entrypoint" in legacy_text
    assert "brain_researcher.services.agent.web_service import app, print_exposed_tools" in legacy_text
    assert "def main() -> None:" in legacy_text
    assert "logger.info(" in legacy_text


def test_agent_docker_runtime_uses_canonical_web_service_entrypoint() -> None:
    dockerfile_path = REPO_ROOT / "infrastructure/docker/Dockerfile.agent"
    dockerfile_text = dockerfile_path.read_text(encoding="utf-8")

    assert 'CMD ["python", "-m", "brain_researcher.services.agent.web_service"]' in dockerfile_text
    assert "web_service_langgraph" not in dockerfile_text
