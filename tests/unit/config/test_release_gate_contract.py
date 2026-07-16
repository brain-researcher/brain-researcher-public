from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE_PATH = REPO_ROOT / "scripts" / "ci" / "clean_clone_gate.sh"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release-readiness.yml"

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
        "9bc31f4ebc9c6b171d7bfbaa5d006ae7abdb4310",
        "v5.0.1",
    ),
    "actions/upload-artifact": (
        "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "v7.0.1",
    ),
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


def test_gate_requires_a_clean_nonlocal_clone_of_the_exact_source_sha() -> None:
    script = GATE_PATH.read_text(encoding="utf-8")

    assert GATE_PATH.stat().st_mode & 0o111
    assert "status --porcelain=v1 --untracked-files=all" in script
    assert "git clone --quiet --no-local --no-checkout" in script
    assert 'checkout --quiet --detach "${SOURCE_SHA}"' in script
    assert script.index("run_step source-clean") < script.index("run_step fresh-clone")
    assert script.index("run_step fresh-clone") < script.index(
        "run_step release-metadata"
    )
    assert '[[ "${clone_sha}" == "${SOURCE_SHA}" ]]' in script
    assert "source-unchanged" in script


def test_gate_records_release_versions_and_fails_closed_on_required_tools() -> None:
    script = GATE_PATH.read_text(encoding="utf-8")

    for key in (
        "source_commit",
        "package_version",
        "expected_tag",
        "mcp_contract_version",
        "python",
        "node",
        "npm",
        "docker",
        "docker_compose",
        "docker_buildx",
        "helm",
        "uv",
    ):
        assert key in script

    for constraint in (
        '"${python_minor}" != "3.11"',
        '"${node_major}" != "20"',
        '"${npm_major}" != "10"',
        '"${uv_version}" != "0.9.21"',
        "capture_tool_version docker_compose docker docker compose version",
        "capture_tool_version docker_buildx docker docker buildx version",
        "capture_tool_version helm helm helm version --short",
    ):
        assert constraint in script

    assert 'root / "release" / "manifest.json"' in script
    assert 'source_binding["mode"] == "release_gate"' in script
    assert 'source_binding["value"] is None' in script
    assert 'source_binding["evidence"] == "release-gate-report.json"' in script
    assert "requested_version == package_version" in script

    manifest = yaml.safe_load(
        (REPO_ROOT / "release" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["release_gate"]["permanent_release_assets"] == [
        "release-gate-report.json",
        "source-commit.txt",
        "versions.json",
        "SHA256SUMS",
        "release-gate-evidence.tar.gz",
    ]


def test_gate_reuses_every_required_check_and_locked_install_boundary() -> None:
    script = GATE_PATH.read_text(encoding="utf-8")

    ordered_steps = (
        "lock-freshness",
        "clean-ci-install",
        "release-contract",
        "unit-pr-smoke",
        "contracts",
        "reproducibility",
        "docs",
        "clean-ci-services-install",
        "services",
        "npm-ci",
        "web",
        "deployment-static",
    )
    offsets = [script.index(f"run_step {step}") for step in ordered_steps]
    assert offsets == sorted(offsets)

    for command in (
        "scripts/setup/refresh_locks.sh --check",
        'scripts/setup/smoke_clean_install.sh "${profile}"',
        'tests/run_tests.sh "${shard}"',
        "tests/unit/config/test_release_gate_contract.py",
        "tests/unit/config/test_software_release_contract.py",
        "-m mkdocs build --strict --clean",
        "tests/unit/config/test_docs_integrity.py",
        "tests/run_tests.sh services",
        "npm --prefix apps/web-ui ci",
        "tests/run_tests.sh web",
        "tests/run_tests.sh deployment-static",
    ):
        assert command in script

    assert "venvs/ci/bin/python" in script
    assert "venvs/ci-services/bin/python" in script
    assert "CI=true" in script
    assert "NEXT_TELEMETRY_DISABLED=1" in script
    docs_function = script.split("run_strict_docs() {", 1)[1].split("\n}", 1)[0]
    assert "-m mkdocs build --strict --clean || return" in docs_function


def test_gate_always_builds_failure_evidence_without_release_side_effects() -> None:
    script = GATE_PATH.read_text(encoding="utf-8")

    for artifact in (
        "release-gate-report.json",
        "source-commit.txt",
        "versions.json",
        "logs",
        "SHA256SUMS",
        "release-gate-evidence.tar.gz",
    ):
        assert artifact in script

    assert "trap on_exit EXIT" in script
    assert "finalize_evidence" in script
    assert '"status": "%s"' in script
    assert '"exit_code": %s' in script
    assert '"tagged": false' in script
    assert '"pushed": false' in script
    assert '"published": false' in script
    assert '"services_started": false' in script

    for forbidden in (
        r"(?m)^\s*git\s+(?:tag|push)\b",
        r"(?m)^\s*gh\s+(?:release|pr)\b",
        r"(?m)^\s*docker(?:\s+compose)?\s+(?:up|run|push)\b",
        r"(?m)^\s*helm\s+(?:install|upgrade)\b",
        r"(?m)^\s*kubectl\s+(?:apply|create)\b",
    ):
        assert not re.search(forbidden, script)


def test_release_workflow_is_manual_read_only_and_uses_immutable_actions() -> None:
    workflow = _workflow()
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    triggers = _triggers(workflow)
    job = workflow["jobs"]["release-readiness"]

    assert set(triggers) == {"workflow_dispatch"}
    release_input = triggers["workflow_dispatch"]["inputs"]["release_version"]
    assert release_input["required"] is True
    assert release_input["type"] == "string"
    assert workflow["permissions"] == {"contents": "read"}
    assert job["name"] == "release-readiness"
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == 180
    assert "${{ secrets." not in text
    assert "pull_request_target" not in text
    assert "environment:" not in text
    assert not re.search(r"(?m)^\s*(?:contents|packages|id-token):\s*write\s*$", text)

    seen: dict[str, int] = dict.fromkeys(ACTION_PINS, 0)
    for step in job["steps"]:
        if "uses" not in step:
            continue
        match = re.fullmatch(r"(?P<action>[^@\s]+)@(?P<sha>[0-9a-f]{40})", step["uses"])
        assert match is not None, step["uses"]
        action = match.group("action")
        assert action in ACTION_PINS
        sha, tag = ACTION_PINS[action]
        assert match.group("sha") == sha
        assert f"uses: {action}@{sha} # {tag}" in text
        seen[action] += 1
        if action == "actions/checkout":
            assert step["with"] == {"persist-credentials": False}
    assert seen == dict.fromkeys(ACTION_PINS, 1)


def test_release_workflow_sets_exact_toolchains_uploads_then_propagates() -> None:
    workflow = _workflow()
    job = workflow["jobs"]["release-readiness"]
    runs = _job_runs(job)
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    setup_python = next(
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/setup-python@")
    )
    setup_node = next(
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/setup-node@")
    )
    assert setup_python["with"]["python-version"] == "3.11"
    assert setup_node["with"]["node-version"] == "20"
    assert "npm install --global npm@10.9.4" in runs
    assert "python -m pip install uv==0.9.21" in runs
    assert "docker/setup-buildx-action@" in text
    assert "azure/setup-helm@" in text

    assert workflow["env"]["RELEASE_VERSION"] == "${{ inputs.release_version }}"
    assert '--release-version "${RELEASE_VERSION}"' in runs
    assert '--output-dir "${RUN_ROOT}"' in runs
    assert "gate_status=$?" in runs
    assert 'printf \'%s\\n\' "${gate_status}" > "${GATE_STATUS_FILE}"' in runs

    steps = job["steps"]
    assert steps[0]["name"] == "Prepare the external evidence directory"
    assert "bootstrap-status.txt" in steps[0]["run"]
    upload_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    propagate_index = next(
        index
        for index, step in enumerate(steps)
        if step["name"] == "Propagate the saved release-gate status"
    )
    assert upload_index < propagate_index == len(steps) - 1
    assert steps[upload_index]["if"] == "${{ always() }}"
    assert steps[upload_index]["with"]["path"] == "${{ env.RUN_ROOT }}"
    assert steps[upload_index]["with"]["if-no-files-found"] == "error"
    assert steps[propagate_index]["if"] == "${{ always() }}"
    assert 'exit "${gate_status}"' in steps[propagate_index]["run"]
