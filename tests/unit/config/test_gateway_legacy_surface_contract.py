from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relpath: str) -> str:
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


def test_gateway_docs_mark_legacy_assets_as_not_public_shipped() -> None:
    deployment = _read("DEPLOYMENT.md")
    api_versioning = _read("docs/standards/API_VERSIONING.md")

    assert "No standalone API Gateway config or Docker image is shipped" in deployment
    assert "src/brain_researcher/services/shared/api_version.py" in api_versioning
    assert (
        "No standalone reverse-proxy config is shipped in the public tree."
        in api_versioning
    )

    assert "`src/brain_researcher/services/api_gateway/config.yaml`" not in deployment
    assert "archive/legacy/api_gateway_deployment/config.yaml" not in deployment
    assert "`brain_researcher/services/shared/api_version.py`" not in api_versioning
    assert "`brain_researcher/services/api_gateway/config.yaml`" not in api_versioning
    assert "archive/legacy/api_gateway_deployment/config.yaml" not in api_versioning


def test_active_compose_and_backup_do_not_reference_removed_archive_assets() -> None:
    compose = _read("infrastructure/docker/compose/docker-compose.override.swarm.yml")
    deploy_script = _read("scripts/deployment/deploy.sh")

    assert "dockerfile: infrastructure/docker/Dockerfile.orchestrator" in compose

    assert "  api-gateway:" not in compose
    assert "archive/legacy/api_gateway_deployment/Dockerfile" not in compose
    assert "archive/legacy/api_gateway_deployment/config.yaml" not in deploy_script
    assert "src/brain_researcher/services/api_gateway/Dockerfile" not in compose
    assert "src/brain_researcher/services/api_gateway/config.yaml" not in deploy_script
