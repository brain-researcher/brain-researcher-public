from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _project_metadata() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]


def _pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _root_readme() -> str:
    return (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def test_python_support_and_base_dependency_contract() -> None:
    project = _project_metadata()
    dependencies = project["dependencies"]

    assert project["requires-python"] == ">=3.11,<3.12"
    assert "PyYAML>=6,<7" in dependencies
    assert not any(requirement.startswith("mcp") for requirement in dependencies)


def test_distribution_version_and_namespace_discovery_contract() -> None:
    config = _pyproject()
    init_text = (REPO_ROOT / "src/brain_researcher/__init__.py").read_text(
        encoding="utf-8"
    )

    assert config["project"]["version"] == "0.1.0"
    assert '__version__ = "0.1.0"' in init_text
    assert config["tool"]["setuptools"]["packages"]["find"]["namespaces"] is True
    assert (
        REPO_ROOT / "src/brain_researcher/core/ingestion/loaders"
    ).is_dir(), "namespace discovery sentinel is missing"


def test_mcp_extra_matches_current_heavy_server_composition() -> None:
    extras = _project_metadata()["optional-dependencies"]

    assert extras["build"] == ["setuptools>=61,<84", "wheel>=0.41,<0.48"]
    assert "brain_researcher[agent]" in extras["mcp"]
    assert "mcp>=1.12.0" in extras["mcp"]


def test_vcs_dependencies_use_immutable_upstream_refs() -> None:
    extras = _project_metadata()["optional-dependencies"]

    assert (
        "caiman @ git+https://github.com/flatironinstitute/CaImAn.git@"
        "a30d1b1bce481704deb7d92bafb93641ef044a6e" in extras["optical_realtime"]
    )
    assert (
        "neurostore-sdk @ "
        "git+https://github.com/neurostuff/neurostore-python-sdk.git@"
        "28fe10f575e1c1f7a6ef5303ea03dd5bb0cd7ce6" in extras["br-kg"]
    )


def test_root_install_instructions_match_python_and_cli_contract() -> None:
    readme = _root_readme()

    assert "Python 3.11 environment" in readme
    assert "Python 3.10–3.12" not in readme
    assert "python3.11 -m venv .venv" in readme
    assert "brain-researcher --help" in readme
    assert "brain-researcher-mcp --help" in readme
    assert "requirements/locks/README.md" in readme
