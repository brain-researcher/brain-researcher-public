from __future__ import annotations

import sys
from pathlib import Path

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10 compatibility.
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_CLI_DEPS = {
    "click": "click>=8.2.1",
    "typer": "typer>=0.24.0",
}


def _load_pyproject_dependencies() -> list[str]:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    return list(pyproject["project"]["dependencies"])


def _load_environment_pip_dependencies() -> list[str]:
    environment = yaml.safe_load(
        (REPO_ROOT / "environment.yml").read_text(encoding="utf-8")
    )
    pip_section = next(
        dependency["pip"]
        for dependency in environment["dependencies"]
        if isinstance(dependency, dict) and "pip" in dependency
    )
    return list(pip_section)


def test_cli_dependency_constraints_match_repo_contract() -> None:
    pyproject_dependencies = _load_pyproject_dependencies()
    environment_dependencies = _load_environment_pip_dependencies()

    for requirement in EXPECTED_CLI_DEPS.values():
        assert requirement in pyproject_dependencies
        assert requirement in environment_dependencies


def test_cli_dependency_constraints_stay_aligned_between_manifests() -> None:
    pyproject_dependencies = _load_pyproject_dependencies()
    environment_dependencies = _load_environment_pip_dependencies()

    for package_name in EXPECTED_CLI_DEPS:
        pyproject_requirement = next(
            requirement
            for requirement in pyproject_dependencies
            if requirement.startswith(f"{package_name}>=")
        )
        environment_requirement = next(
            requirement
            for requirement in environment_dependencies
            if requirement.startswith(f"{package_name}>=")
        )
        assert pyproject_requirement == environment_requirement
