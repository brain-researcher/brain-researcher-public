from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPLOYMENT_GATE = REPO_ROOT / "scripts" / "ci" / "validate_deployment_static.sh"
TEST_RUNNER = REPO_ROOT / "tests" / "run_tests.sh"

EXPECTED_JOBS = (
    "clean-install",
    "unit",
    "contracts",
    "reproducibility",
    "docs",
    "services",
    "web",
    "deployment-static",
)
ACTION_PINS = {
    "actions/checkout": (
        "de0fac2e4500dabe0009e67214ff5f5447ce83dd",
        "v6.0.2",
    ),
    "actions/setup-python": (
        "a309ff8b426b58ec0e2a45f0f869d46889d02405",
        "v6.2.0",
    ),
    "actions/setup-node": (
        "48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e",
        "v6.4.0",
    ),
    "docker/setup-buildx-action": (
        "d7f5e7f509e45cec5c76c4d5afdd7de93d0b3df5",
        "v4.1.0",
    ),
    "azure/setup-helm": (
        "1a275c3b69536ee54be43f2070a358922e12c8d4",
        "v4.3.1",
    ),
}
ACTION_COUNTS = {
    "actions/checkout": 8,
    "actions/setup-python": 8,
    "actions/setup-node": 1,
    "docker/setup-buildx-action": 1,
    "azure/setup-helm": 1,
}


def _workflow() -> dict[str | bool, Any]:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _triggers(workflow: dict[str | bool, Any]) -> dict[str, Any]:
    # PyYAML 1.1 treats the unquoted workflow key ``on`` as boolean true.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _job_runs(job: dict[str, Any]) -> str:
    return "\n".join(
        step["run"] for step in job["steps"] if isinstance(step.get("run"), str)
    )


def test_required_check_inventory_and_trigger_scope_are_stable() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    triggers = _triggers(workflow)

    assert tuple(jobs) == EXPECTED_JOBS
    assert set(triggers) == {"pull_request", "push", "workflow_dispatch"}
    assert triggers["push"] == {"branches": ["main"]}
    assert "schedule" not in triggers
    assert "pull_request_target" not in triggers

    for event in triggers.values():
        if isinstance(event, dict):
            assert "paths" not in event
            assert "paths-ignore" not in event

    for job_id, job in jobs.items():
        assert job["name"] == job_id
        assert job["runs-on"] == "ubuntu-24.04"
        assert isinstance(job["timeout-minutes"], int)
        assert "permissions" not in job
        assert "needs" not in job


def test_workflow_has_only_read_permission_and_no_secret_channel() -> None:
    workflow = _workflow()
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow["permissions"] == {"contents": "read"}
    assert "${{ secrets." not in text
    assert not re.search(r"(?m)^\s*(?:id-token|packages|pull-requests):\s*write\s*$", text)
    assert "environment:" not in text


def test_every_action_is_immutable_and_matches_its_documented_tag() -> None:
    workflow = _workflow()
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    counts = dict.fromkeys(ACTION_PINS, 0)

    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "uses" not in step:
                continue
            match = re.fullmatch(
                r"(?P<action>[^@\s]+)@(?P<sha>[0-9a-f]{40})", step["uses"]
            )
            assert match is not None, step["uses"]
            action = match.group("action")
            assert action in ACTION_PINS, action
            sha, tag = ACTION_PINS[action]
            assert match.group("sha") == sha
            assert f"uses: {action}@{sha} # {tag}" in text
            if action == "actions/checkout":
                assert step["with"] == {"persist-credentials": False}
            counts[action] += 1

    assert counts == ACTION_COUNTS


def test_python_jobs_use_the_verified_311_profiles_and_test_runner() -> None:
    jobs = _workflow()["jobs"]

    clean_install = _job_runs(jobs["clean-install"])
    assert clean_install.strip() == (
        'BR_CLEAN_INSTALL_PIP_CACHE_DIR="$(python -m pip cache dir)" '
        "scripts/setup/smoke_clean_install.sh core"
    )

    expected_runner_commands = {
        "unit": "tests/run_tests.sh unit-pr-smoke",
        "contracts": "tests/run_tests.sh contracts",
        "reproducibility": "tests/run_tests.sh reproducibility",
        "services": "tests/run_tests.sh services",
    }
    for job_id in (
        "unit",
        "contracts",
        "reproducibility",
        "docs",
        "web",
        "deployment-static",
    ):
        job = jobs[job_id]
        setup_python = next(
            step for step in job["steps"] if step.get("uses", "").startswith(
                "actions/setup-python@"
            )
        )
        assert setup_python["with"]["python-version"] == "3.11"
        runs = _job_runs(job)
        assert "requirements/locks/ci-py311.txt" in runs
        assert "--no-deps --no-build-isolation -e" in runs
        assert "python -m pip check" in runs

    for job_id, command in expected_runner_commands.items():
        assert command in _job_runs(jobs[job_id])

    service = jobs["services"]
    service_setup_python = next(
        step
        for step in service["steps"]
        if step.get("uses", "").startswith("actions/setup-python@")
    )
    assert service_setup_python["with"] == {
        "python-version": "3.11",
        "cache": "pip",
        "cache-dependency-path": "requirements/locks/ci-services-py311.txt",
    }
    service_runs = _job_runs(service)
    assert "requirements/locks/ci-services-py311.txt" in service_runs
    assert '-e ".[ci-services]"' in service_runs
    assert "requirements/locks/agent-py311.txt" not in service_runs
    assert '-e ".[agent]"' not in service_runs
    assert "tests/run_tests.sh services" in service_runs

    docs_runs = _job_runs(jobs["docs"])
    assert "python -m mkdocs build --strict --clean" in docs_runs
    assert "python -m pytest -q tests/unit/config/test_docs_integrity.py" in docs_runs
    assert "--noconftest -p no:cacheprovider" in docs_runs


def test_web_job_uses_node20_npm10_and_the_offline_runner_boundary() -> None:
    web = _workflow()["jobs"]["web"]
    setup_node = next(
        step
        for step in web["steps"]
        if step.get("uses", "").startswith("actions/setup-node@")
    )
    assert setup_node["with"] == {
        "node-version": "20",
        "cache": "npm",
        "cache-dependency-path": "apps/web-ui/package-lock.json",
    }

    runs = _job_runs(web)
    assert "process.versions.node" in runs
    assert 'npm --version | cut -d. -f1)" = "10"' in runs
    assert "npm --prefix apps/web-ui ci" in runs
    assert "tests/run_tests.sh web" in runs
    assert "npm install" not in runs

    runner = TEST_RUNNER.read_text(encoding="utf-8")
    for command in (
        '"$NPM_BIN" --prefix apps/web-ui run lint:ci',
        '"$NPM_BIN" --prefix apps/web-ui test',
        '"$NPM_BIN" --prefix apps/web-ui run build',
    ):
        assert command in runner


def test_pr_jobs_do_not_select_network_or_privileged_scientific_tests() -> None:
    workflow = _workflow()
    all_runs = "\n".join(_job_runs(job) for job in workflow["jobs"].values())

    for forbidden in (
        " e2e",
        " realdata",
        " network",
        " requires_api",
        " requires_gpu",
        " scientific-rerun",
    ):
        assert forbidden not in all_runs.casefold()


def test_deployment_gate_is_static_and_preserves_experimental_boundaries() -> None:
    workflow_runs = _job_runs(_workflow()["jobs"]["deployment-static"])
    runner = TEST_RUNNER.read_text(encoding="utf-8")
    script = DEPLOYMENT_GATE.read_text(encoding="utf-8")

    assert workflow_runs.count("tests/run_tests.sh deployment-static") == 1
    assert "scripts/ci/validate_deployment_static.sh" not in workflow_runs
    assert "scripts/ci/validate_deployment_static.sh" in runner
    assert DEPLOYMENT_GATE.stat().st_mode & 0o111

    compose_calls = (
        (
            '"supported local base file (parse only)"',
            '${REPO_ROOT}/docker-compose.yml',
        ),
        (
            '"base plus experimental CC overlay (parse only)"',
            '${REPO_ROOT}/docker-compose.cc-stack.yml',
        ),
        (
            '"standalone production file (experimental parse only)"',
            '${REPO_ROOT}/docker-compose.prod.yml',
        ),
        (
            '"standalone test file (experimental parse only)"',
            (
                "${REPO_ROOT}/infrastructure/docker/compose/"
                "docker-compose.override.test.yml"
            ),
        ),
        (
            '"standalone production override (experimental parse only)"',
            (
                "${REPO_ROOT}/infrastructure/docker/compose/"
                "docker-compose.override.prod.yml"
            ),
        ),
        (
            '"standalone swarm file (experimental parse only)"',
            (
                "${REPO_ROOT}/infrastructure/docker/compose/"
                "docker-compose.override.swarm.yml"
            ),
        ),
        (
            '"standalone CI file (experimental parse only)"',
            "${REPO_ROOT}/infrastructure/docker/compose/docker-compose.ci.yml",
        ),
        (
            '"standalone monitoring file (experimental parse only)"',
            (
                "${REPO_ROOT}/infrastructure/monitoring/service_stack/"
                "docker-compose.monitoring.yml"
            ),
        ),
    )
    assert script.count("\ncompose_config \\\n") == 8
    for label, relative_path in compose_calls:
        assert label in script
        assert relative_path in script
    assert script.count('${REPO_ROOT}/docker-compose.yml') == 2

    for required in (
        "config --quiet",
        "docker buildx build --check",
        "helm lint --strict",
        "helm template",
        "experimental",
        "parse only",
        "render-only",
        'printf \'%s\\n\' "${PLACEHOLDERS[@]}" >"${PLACEHOLDER_ENV}"',
    ):
        assert required in script

    assert 'source "${PLACEHOLDER_ENV}"' in script
    assert "${REPO_ROOT}/.env" not in script
    assert "set -x" not in script
    assert 'cat "${PLACEHOLDER_ENV}"' not in script
    assert 'echo "${PLACEHOLDERS' not in script
    assert not re.search(
        r"(?m)^\s*(?:docker(?:\s+compose)?\s+(?:up|run|pull|push)|"
        r"helm\s+(?:install|upgrade)|kubectl\s+(?:apply|create))\b",
        script,
    )
    assert "--push" not in script
