from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "runtime"
    / "start_marimo_singleuser.sh"
)


def _write_fake_python(bin_dir: Path) -> None:
    python_path = bin_dir / "python"
    python_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    python_path.chmod(0o755)


def _write_logging_fake_python(bin_dir: Path, log_path: Path) -> None:
    python_path = bin_dir / "python"
    python_path.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {str(log_path)!r}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    python_path.chmod(0o755)


def test_start_marimo_singleuser_materializes_templates_into_workspace(tmp_path: Path) -> None:
    template_root = tmp_path / "templates"
    template_root.mkdir()
    (template_root / "br_quickstart.py").write_text("print('quickstart')\n", encoding="utf-8")
    (template_root / "behavior_task_builder.py").write_text(
        "print('behavior')\n", encoding="utf-8"
    )

    workspace_root = tmp_path / "workspace"
    notebooks_dir = workspace_root / "notebooks"
    notebooks_dir.mkdir(parents=True)
    existing_builder = notebooks_dir / "behavior_task_builder.py"
    existing_builder.write_text("print('keep-me')\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_python(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["BR_TEMPLATE_ROOT"] = str(template_root)
    env["BR_MARIMO_RUNTIME_WORKSPACE_HOME"] = str(workspace_root)
    env["BR_MARIMO_ENABLE_XVFB"] = "false"
    env["HOME"] = str(tmp_path / "home")

    subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "bash",
            "-lc",
            "test -f notebooks/br_quickstart.py && test -f notebooks/behavior_task_builder.py",
        ],
        check=True,
        cwd=workspace_root,
        env=env,
    )

    assert (notebooks_dir / "br_quickstart.py").read_text(encoding="utf-8") == (
        "print('quickstart')\n"
    )
    assert existing_builder.read_text(encoding="utf-8") == "print('keep-me')\n"


def test_start_marimo_singleuser_attempts_taskbeacon_materialization_when_requested(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "python.log"
    _write_logging_fake_python(bin_dir, log_path)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["BR_MARIMO_RUNTIME_WORKSPACE_HOME"] = str(workspace_root)
    env["BR_MARIMO_ENABLE_XVFB"] = "false"
    env["BR_MARIMO_RUNTIME_TASKBEACON_REPO"] = "TaskBeacon/T000015-ant"
    env["BR_MARIMO_RUNTIME_TASKBEACON_TARGET_PATH"] = (
        "projects/proj_demo/taskbeacon/T000015-ant"
    )
    env["BR_MARIMO_RUNTIME_TASKBEACON_REF"] = "main"
    env["HOME"] = str(tmp_path / "home")

    subprocess.run(
        ["bash", str(SCRIPT_PATH), "bash", "-lc", "true"],
        check=True,
        cwd=workspace_root,
        env=env,
    )

    log_text = log_path.read_text(encoding="utf-8")
    assert "brain_researcher.services.orchestrator.taskbeacon_handoff" in log_text
    assert "--repo TaskBeacon/T000015-ant" in log_text
    assert "--ref main" in log_text


def test_start_marimo_singleuser_starts_xvfb_when_enabled(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_python(bin_dir)
    xvfb_log = tmp_path / "xvfb.log"
    xvfb_path = bin_dir / "Xvfb"
    xvfb_path.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {str(xvfb_log)!r}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    xvfb_path.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["BR_TEMPLATE_ROOT"] = str(tmp_path / "missing_templates")
    env["BR_MARIMO_RUNTIME_WORKSPACE_HOME"] = str(workspace_root)
    env["BR_MARIMO_ENABLE_XVFB"] = "true"
    env["BR_MARIMO_XVFB_DISPLAY"] = ":88"
    env["BR_MARIMO_XVFB_SCREEN"] = "1280x720x24"
    env["HOME"] = str(tmp_path / "home")
    env.pop("DISPLAY", None)

    subprocess.run(
        ["bash", str(SCRIPT_PATH), "bash", "-lc", "test \"$DISPLAY\" = :88"],
        check=True,
        cwd=workspace_root,
        env=env,
    )

    assert "-screen 0 1280x720x24 -nolisten tcp" in xvfb_log.read_text(
        encoding="utf-8"
    )
