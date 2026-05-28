from __future__ import annotations

from pathlib import Path


def test_orchestrator_dockerfile_includes_workflow_and_catalog_configs():
    """Orchestrator image must include preflight catalogs under /app/configs."""

    repo_root = Path(__file__).resolve().parents[3]
    dockerfile_path = repo_root / "infrastructure" / "docker" / "Dockerfile.orchestrator"
    content = dockerfile_path.read_text()

    assert "COPY configs/workflows /app/configs/workflows" in content
    assert "COPY configs/catalog /app/configs/catalog" in content
    assert "COPY configs/runtime /app/configs/runtime" in content
