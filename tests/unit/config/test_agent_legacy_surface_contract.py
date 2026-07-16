from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_removed_agent_langgraph_entrypoints_stay_removed() -> None:
    canonical_path = REPO_ROOT / "src/brain_researcher/services/agent/web_service.py"
    removed_paths = (
        REPO_ROOT / "src/brain_researcher/legacy/agent/web_service_langgraph.py",
        REPO_ROOT / "src/brain_researcher/services/agent/web_service_langgraph.py",
    )

    assert canonical_path.is_file()
    assert "app.run(" in canonical_path.read_text(encoding="utf-8")
    for path in removed_paths:
        assert not path.exists(), f"Removed agent entrypoint returned: {path}"


def test_agent_docker_runtime_uses_canonical_web_service_entrypoint() -> None:
    dockerfile_path = REPO_ROOT / "infrastructure/docker/Dockerfile.agent"
    dockerfile_text = dockerfile_path.read_text(encoding="utf-8")

    assert 'CMD ["python", "-m", "brain_researcher.services.agent.web_service"]' in dockerfile_text
    assert "web_service_langgraph" not in dockerfile_text
