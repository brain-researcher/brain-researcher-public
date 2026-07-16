from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_DIR = REPO_ROOT / "requirements" / "locks"
EXPECTED_PROFILES = {
    "core": set(),
    "mcp": {"mcp"},
    "agent": {"langgraph"},
    "br-kg": {"nilearn"},
    "ci": {"mkdocs", "mkdocs-material", "mkdocstrings", "pytest"},
    "ci-services": {
        "fastapi",
        "langchain-anthropic",
        "langchain-openai",
        "neuromaps",
        "nilearn",
        "openneuro-py",
        "pytest",
    },
    "dev": {"mcp", "nilearn", "pytest"},
}


def _requirement_lines(profile: str) -> list[str]:
    path = LOCK_DIR / f"{profile}-py311.txt"
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _distribution_names(lines: list[str]) -> set[str]:
    names = set()
    for line in lines:
        match = re.match(r"([A-Za-z0-9_.-]+)", line)
        assert match is not None, line
        names.add(match.group(1).lower().replace("_", "-"))
    return names


def test_exact_lock_export_inventory_and_profile_mapping() -> None:
    assert {path.name for path in LOCK_DIR.glob("*-py311.txt")} == {
        f"{profile}-py311.txt" for profile in EXPECTED_PROFILES
    }

    script = (REPO_ROOT / "scripts/setup/refresh_locks.sh").read_text(encoding="utf-8")
    for declaration in (
        '[core]=""',
        '[mcp]="mcp"',
        '[agent]="agent"',
        '[br-kg]="br-kg"',
        '[ci]="ci"',
        '[ci-services]="ci-services"',
        '[dev]="all"',
    ):
        assert declaration in script
    assert "--extra build" in script


def test_clean_install_smoke_uses_an_isolated_home_and_environment() -> None:
    script = (REPO_ROOT / "scripts/setup/smoke_clean_install.sh").read_text(
        encoding="utf-8"
    )
    readme = (LOCK_DIR / "README.md").read_text(encoding="utf-8")

    assert "env -i" in script
    assert 'HOME="${venv_dir}/home"' in script
    assert 'BR_CLEAN_INSTALL_PIP_CACHE_DIR:-${SMOKE_ROOT}/pip-cache' in script
    assert 'PIP_CACHE_DIR="${PIP_CACHE_DIR}"' in script
    assert "PIP_CONFIG_FILE=/dev/null" in script
    assert "GIT_CONFIG_GLOBAL=/dev/null" in script
    assert 'BR_CONFIG_ROOT="${REPO_ROOT}"' in script
    assert 'smoke_profile_inner "${profile}" 2>&1 | tee "${log_file}"' in script
    assert 'statuses=("${PIPESTATUS[@]}")' in script
    assert "exec > >(tee" not in script
    assert "repo-level `configs/`" in readme
    assert "do not certify a standalone wheel" in readme


def test_uv_lock_matches_project_contract() -> None:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))

    assert pyproject["tool"]["uv"]["required-version"] == "==0.9.21"
    assert pyproject["project"]["requires-python"] == ">=3.11,<3.12"
    assert lock["requires-python"] == "==3.11.*"
    root = next(
        package for package in lock["package"] if package["name"] == "brain-researcher"
    )
    assert root["version"] == pyproject["project"]["version"]
    assert root["source"] in ({"editable": "."}, {"virtual": "."})


def test_ci_services_extra_stays_bounded_to_focused_runtime_imports() -> None:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    extras = pyproject["project"]["optional-dependencies"]

    assert extras["ci-services"] == [
        "brain_researcher[ci]",
        "openneuro-py>=2026.3.0",
        "neuromaps>=0.0.5",
        "nilearn>=0.10.0",
        "langchain-anthropic>=0.0.1",
        "langchain-openai>=0.0.5",
        "fastapi>=0.104.0",
    ]

    smoke = (REPO_ROOT / "scripts/setup/smoke_clean_install.sh").read_text(
        encoding="utf-8"
    )
    assert 'find_spec("torch") is None' in smoke
    assert 'find_spec("nvidia") is None' in smoke


def test_pytest_ini_is_the_single_root_pytest_configuration() -> None:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    pytest_ini = (REPO_ROOT / "pytest.ini").read_text(encoding="utf-8")

    assert "pytest" not in pyproject.get("tool", {})
    assert pytest_ini.startswith("[pytest]\n")
    for excluded_marker in (
        "network",
        "requires_api",
        "requires_gpu",
    ):
        assert f"not {excluded_marker}" in pytest_ini


def test_fast_runner_preserves_all_default_marker_exclusions() -> None:
    runner = (REPO_ROOT / "tests/run_tests.sh").read_text(encoding="utf-8")
    marker_expression = (
        "not slow and not e2e and not realdata and not network and "
        "not requires_api and not requires_gpu"
    )

    assert f'-m "{marker_expression}"' in runner


def test_exports_are_portable_and_fully_pinned() -> None:
    for profile in EXPECTED_PROFILES:
        for line in _requirement_lines(profile):
            lowered = line.lower()
            assert "-e ." not in lowered
            assert "file://" not in lowered
            assert "/home/" not in lowered
            assert "/tmp/" not in lowered
            if "git+" in lowered:
                requirement = line.split(" ;", maxsplit=1)[0]
                assert re.search(r"@[0-9a-f]{40}$", requirement), line
            else:
                requirement = line.split(" ;", maxsplit=1)[0]
                assert "==" in requirement, line


def test_profile_sentinel_packages_are_present() -> None:
    for profile, sentinels in EXPECTED_PROFILES.items():
        names = _distribution_names(_requirement_lines(profile))
        assert "pyyaml" in names
        assert {"setuptools", "wheel"} <= names
        assert sentinels <= names

    ci_services = _distribution_names(_requirement_lines("ci-services"))
    assert "torch" not in ci_services
    assert not any(name.startswith("nvidia-") for name in ci_services)


def test_all_uv_git_sources_are_immutable() -> None:
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    git_sources = [
        package["source"]["git"]
        for package in lock["package"]
        if "git" in package.get("source", {})
    ]

    assert git_sources
    for source in git_sources:
        assert re.search(r"[?#]rev=[0-9a-f]{40}(?:[&#]|$)", source), source
