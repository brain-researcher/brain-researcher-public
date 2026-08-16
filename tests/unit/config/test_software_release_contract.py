from __future__ import annotations

import json
import tomllib
from pathlib import Path

import yaml

from brain_researcher.core.contracts.version_ref import (
    VersionRefV1,
    _contracts_version,
    build_version_ref_v1,
)
from brain_researcher.services.agent.api_routes import SOFTWARE_VERSION
from brain_researcher.services.orchestrator import __version__ as orchestrator_version

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE = "0.3.0"
PREVIEW = f"{RELEASE}-oss-preview"


def _json(path: str) -> dict:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def _yaml(path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / path).read_text(encoding="utf-8"))


def test_software_release_versions_are_traceable() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    manifest = _json("release/manifest.json")

    assert manifest["schema_version"] == "brain-researcher-release-v1"
    assert manifest["software_release"]["version"] == RELEASE
    assert manifest["software_release"]["git_tag"] == f"v{RELEASE}"
    assert manifest["software_release"]["zenodo"] == {
        "status": "published",
        "concept_doi": "10.5281/zenodo.21282319",
        "version_doi": "10.5281/zenodo.21966011",
        "publication_date": "2026-08-16",
    }
    assert manifest["python"] == {
        "distribution": "brain_researcher",
        "version": RELEASE,
        "requires_python": ">=3.11,<3.12",
    }
    assert project["version"] == manifest["python"]["version"]
    assert project["requires-python"] == manifest["python"]["requires_python"]
    assert f'__version__ = "{RELEASE}"' in (
        REPO_ROOT / "src/brain_researcher/__init__.py"
    ).read_text(encoding="utf-8")
    assert SOFTWARE_VERSION == RELEASE
    assert orchestrator_version == RELEASE
    orchestrator_source = (
        REPO_ROOT
        / "src/brain_researcher/services/orchestrator/main_enhanced.py"
    ).read_text(encoding="utf-8")
    assert "version=SOFTWARE_VERSION" in orchestrator_source
    assert '"orchestrator_version": SOFTWARE_VERSION' in orchestrator_source


def test_contract_epoch_and_source_commit_binding_are_explicit() -> None:
    manifest = _json("release/manifest.json")
    contract_epoch = (
        (REPO_ROOT / "contracts/VERSION").read_text(encoding="utf-8").strip()
    )

    assert contract_epoch == "2026-05-27"
    assert manifest["mcp_contract"] == {
        "version": contract_epoch,
        "version_file": "contracts/VERSION",
    }
    assert manifest["software_release"]["source_commit_binding"] == {
        "mode": "release_gate",
        "value": None,
        "evidence": "release-gate-report.json",
    }


def test_version_ref_reads_contract_epoch_without_changing_legacy_default(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "brain_researcher.core.contracts.version_ref._pkg_version",
        lambda _name: RELEASE,
    )
    monkeypatch.setattr(
        "brain_researcher.core.contracts.version_ref._git_commit",
        lambda _root: "a" * 40,
    )

    assert VersionRefV1().contracts_version == "contracts-v1"
    assert (
        VersionRefV1.model_json_schema()["properties"]["contracts_version"]["default"]
        == "contracts-v1"
    )
    assert build_version_ref_v1().contracts_version == "2026-05-27"
    assert _contracts_version(tmp_path) == "2026-05-27"


def test_helm_and_container_preview_versions_are_not_publication_claims() -> None:
    manifest = _json("release/manifest.json")
    chart = _yaml("infrastructure/k8s/helm/brain-researcher/Chart.yaml")
    values = _yaml("infrastructure/k8s/helm/brain-researcher/values.yaml")
    jupyterhub = _yaml("infrastructure/jupyterhub/values.mvp.yaml")

    assert manifest["containers"]["tag"] == PREVIEW
    assert manifest["containers"]["status"] == "not_published"
    assert manifest["helm"] == {
        "chart_version": RELEASE,
        "app_version": PREVIEW,
        "status": "experimental_static_only",
    }
    assert chart["version"] == RELEASE
    assert chart["appVersion"] == PREVIEW

    preview_tags = (
        values["orchestrator"]["image"]["tag"],
        values["orchestrator"]["marimoRuntime"]["imageTag"],
        values["agent"]["image"]["tag"],
        values["br-kg"]["image"]["tag"],
        values["niclip"]["image"]["tag"],
        values["mcp"]["image"]["tag"],
        values["webUi"]["image"]["tag"],
        jupyterhub["singleuser"]["image"]["tag"],
    )
    assert set(preview_tags) == {PREVIEW}


def test_zenodo_identifiers_distinguish_release_and_historical_archive() -> None:
    manifest = _json("release/manifest.json")
    citation = _yaml("CITATION.cff")

    assert citation["version"] == RELEASE
    assert citation["doi"] == "10.5281/zenodo.21966011"
    assert citation["date-released"] == "2026-08-16"
    assert "identifiers" not in citation
    assert manifest["historical_artifacts"] == {
        "relationship": "earlier_version_under_same_zenodo_concept",
        "exact_reproducibility_archive": {
            "status": "historical_archive",
            "git_tag": "br-reproducibility-20260709.1",
            "version_doi": "10.5281/zenodo.21282320",
            "concept_doi": "10.5281/zenodo.21282319",
        },
    }
