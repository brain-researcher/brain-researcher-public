from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "runtime"
    / "run_taskbeacon_task.sh"
)


def _write_fake_python(bin_dir: Path, log_path: Path) -> None:
    python_path = bin_dir / "python"
    python_path.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'python %s\\n' \"$*\" >> {str(log_path)!r}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    python_path.chmod(0o755)


def _write_fake_xvfb_run(bin_dir: Path, log_path: Path) -> None:
    xvfb_path = bin_dir / "xvfb-run"
    xvfb_path.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'xvfb-run %s\\n' \"$*\" >> {str(log_path)!r}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    xvfb_path.chmod(0o755)


def test_run_taskbeacon_uses_br_sim_config_under_xvfb(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    (task_dir / "config").mkdir(parents=True)
    (task_dir / "main.py").write_text("print('task')\n", encoding="utf-8")
    (task_dir / "config" / "br_config_sim.yaml").write_text("sim: {}\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "runner.log"
    _write_fake_python(bin_dir, log_path)
    _write_fake_xvfb_run(bin_dir, log_path)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env.pop("DISPLAY", None)

    subprocess.run(
        ["bash", str(SCRIPT_PATH), "sim", "--task-dir", str(task_dir)],
        check=True,
        cwd=tmp_path,
        env=env,
    )

    log_text = log_path.read_text(encoding="utf-8")
    assert "xvfb-run -a -s -screen 0 1920x1080x24" in log_text
    assert "main.py sim --config config/br_config_sim.yaml" in log_text


def test_run_taskbeacon_uses_python_directly_when_display_exists(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    (task_dir / "config").mkdir(parents=True)
    (task_dir / "main.py").write_text("print('task')\n", encoding="utf-8")
    (task_dir / "config" / "br_config_qa.yaml").write_text("qa: {}\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "runner.log"
    _write_fake_python(bin_dir, log_path)
    _write_fake_xvfb_run(bin_dir, log_path)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["DISPLAY"] = ":99"

    subprocess.run(
        ["bash", str(SCRIPT_PATH), "qa", "--task-dir", str(task_dir)],
        check=True,
        cwd=tmp_path,
        env=env,
    )

    log_text = log_path.read_text(encoding="utf-8")
    assert "xvfb-run" not in log_text
    assert "python main.py qa --config config/br_config_qa.yaml" in log_text


def test_run_taskbeacon_defaults_to_qa_when_first_arg_is_option(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    (task_dir / "config").mkdir(parents=True)
    (task_dir / "main.py").write_text("print('task')\n", encoding="utf-8")
    (task_dir / "config" / "br_config_qa.yaml").write_text("qa: {}\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "runner.log"
    _write_fake_python(bin_dir, log_path)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["DISPLAY"] = ":99"

    subprocess.run(
        ["bash", str(SCRIPT_PATH), "--task-dir", str(task_dir)],
        check=True,
        cwd=tmp_path,
        env=env,
    )

    assert "python main.py qa --config config/br_config_qa.yaml" in log_path.read_text(
        encoding="utf-8"
    )
