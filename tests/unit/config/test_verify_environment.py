from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "setup" / "verify_environment.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_environment_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_declared_profiles_and_python_contract() -> None:
    module = _load_module()
    assert tuple(module.PROFILE_INCLUDES) == ("core", "mcp", "agent", "br-kg", "dev")
    assert module.PROFILE_INCLUDES["dev"] == ("mcp", "agent", "br-kg", "dev")
    assert module.check_python((3, 11, 13))["ok"] is True
    assert module.check_python((3, 10, 14))["ok"] is False
    assert module.check_python((3, 12, 1))["ok"] is False


def test_package_check_requires_distribution_and_import() -> None:
    module = _load_module()
    found = module.check_package(
        "demo",
        "demo_module",
        ">=1.2,<2",
        version_lookup=lambda _name: "1.2.3",
        module_importer=lambda _name: object(),
    )
    old_version = module.check_package(
        "demo",
        "demo_module",
        ">=2",
        version_lookup=lambda _name: "1.2.3",
        module_importer=lambda _name: object(),
    )

    def broken_import(_name):
        raise RuntimeError("compiled extension unavailable")

    broken = module.check_package(
        "demo",
        "demo_module",
        ">=1",
        version_lookup=lambda _name: "1.2.3",
        module_importer=broken_import,
    )
    assert found["ok"] is True
    assert found["version"] == "1.2.3"
    assert old_version["version_ok"] is False
    assert old_version["ok"] is False
    assert broken["import_error"] == "RuntimeError"
    assert broken["ok"] is False


def test_entrypoint_help_is_scoped_and_does_not_forward_secrets(monkeypatch) -> None:
    module = _load_module()
    secret = "never-forward-this"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    captured = {}

    def runner(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess([], 0, stdout="usage", stderr="")

    assert (
        module.check_entrypoint(
            "br", resolver=lambda _name: "/venv/bin/br", runner=runner
        )["ok"]
        is True
    )
    assert secret not in json.dumps(captured["kwargs"]["env"])
    assert "OPENAI_API_KEY" not in captured["kwargs"]["env"]
    assert captured["kwargs"]["cwd"] == str(Path(sys.prefix).resolve())
    assert module.check_entrypoint("br", resolver=lambda _name: None)["ok"] is False


def test_service_report_never_contains_secret_values() -> None:
    module = _load_module()
    secret = "do-not-print-this-value"
    row = module.check_service(
        "llm_provider", {"OPENAI_API_KEY": secret, "ANTHROPIC_API_KEY": ""}
    )
    rendered = json.dumps(row)
    assert row["status"] == "configured"
    assert row["configured_variables"] == ["OPENAI_API_KEY"]
    assert secret not in rendered


def _fake_conda(tmp_path: Path, *, activate_status: int) -> tuple[Path, dict[str, str]]:
    fake_bin = tmp_path / "bin"
    fake_base = tmp_path / "conda-base"
    conda_sh = fake_base / "etc" / "profile.d" / "conda.sh"
    fake_bin.mkdir()
    conda_sh.parent.mkdir(parents=True)
    conda = fake_bin / "conda"
    conda.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = info ] && [ "$2" = --base ]; then\n'
        "  printf '%s\\n' \"$FAKE_CONDA_BASE\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    conda.chmod(0o755)
    conda_sh.write_text(
        "conda() {\n"
        '  if [ "$1" = activate ]; then\n'
        f"    return {activate_status}\n"
        "  fi\n"
        "  return 1\n"
        "}\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "FAKE_CONDA_BASE": str(fake_base),
    }
    return fake_base, env


def test_activation_fails_closed_when_conda_activate_fails(tmp_path: Path) -> None:
    _fake_base, env = _fake_conda(tmp_path, activate_status=1)
    env["BR_CONDA_ENV"] = "missing-test-environment"
    completed = subprocess.run(
        ["bash", "-c", f"cd /tmp && source {REPO_ROOT / 'activate.sh'}"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode != 0
    assert "Failed to activate" in completed.stderr
    assert "environment 'missing-test-environment' activated" not in completed.stdout


def test_activation_resolves_repo_root_from_script_location(tmp_path: Path) -> None:
    _fake_base, env = _fake_conda(tmp_path, activate_status=0)
    env["BR_CONDA_ENV"] = "brain_researcher"
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            "bash",
            "-c",
            (
                f"cd /tmp && source {REPO_ROOT / 'activate.sh'} >/dev/null && "
                'printf \'%s\\n%s\\n\' "$PWD" "${PYTHONPATH%%:*}"'
            ),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == [str(REPO_ROOT), str(REPO_ROOT / "src")]


def test_environment_roles_and_activation_are_explicit() -> None:
    dev_environment = (REPO_ROOT / "environment.yml").read_text(encoding="utf-8")
    runtime_environment = (REPO_ROOT / "environment.brain_researcher.yml").read_text(
        encoding="utf-8"
    )
    activation = (REPO_ROOT / "activate.sh").read_text(encoding="utf-8")
    setup = (REPO_ROOT / "scripts" / "setup" / "setup_local_runtime.sh").read_text(
        encoding="utf-8"
    )
    archive = (
        REPO_ROOT
        / "docs"
        / "archive"
        / "environments"
        / "neuroimage_env_2025-08-20.yaml"
    )

    assert "name: brain_researcher-dev" in dev_environment
    assert "name: brain_researcher\n" in runtime_environment
    assert not (REPO_ROOT / "neuroimage_env.yaml").exists()
    assert archive.is_file()
    assert "HISTORICAL SNAPSHOT" in archive.read_text(encoding="utf-8")
    assert "BRAIN_RESEARCHER_HOME" not in activation
    assert "${BASH_SOURCE[0]}" in activation
    assert "${REPO_ROOT}/src" in activation
    assert "--force" not in setup
    assert "conda env update" in setup
    assert "conda env create" in setup
