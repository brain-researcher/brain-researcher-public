"""Tests for scripts/mcp/resolve_br_mcp_token.sh."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts/mcp/resolve_br_mcp_token.sh"


def _run_script(*, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def _base_env(tmp_path: Path, repo_root: Path) -> dict[str, str]:
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home_dir),
        "BR_MCP_REPO_ROOT": str(repo_root),
    }


def test_resolver_prefers_env_variable(tmp_path: Path) -> None:
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir(parents=True, exist_ok=True)
    (fake_repo / ".env").write_text("BR_MCP_TOKEN=dotenv_token\n", encoding="utf-8")

    env = _base_env(tmp_path, fake_repo)
    (Path(env["HOME"]) / ".bashrc").write_text(
        "export BR_MCP_TOKEN=bashrc_token\n", encoding="utf-8"
    )
    env["BR_MCP_TOKEN"] = "env_token"

    result = _run_script(env=env)

    assert result.returncode == 0
    assert result.stdout.strip() == "env_token"


def test_resolver_falls_back_to_dotenv(tmp_path: Path) -> None:
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir(parents=True, exist_ok=True)
    (fake_repo / ".env").write_text(
        'BR_MCP_TOKEN = "dotenv_token"\n',
        encoding="utf-8",
    )

    env = _base_env(tmp_path, fake_repo)
    (Path(env["HOME"]) / ".bashrc").write_text(
        "export BR_MCP_TOKEN=bashrc_token\n", encoding="utf-8"
    )

    result = _run_script(env=env)

    assert result.returncode == 0
    assert result.stdout.strip() == "dotenv_token"


def test_resolver_falls_back_to_bashrc(tmp_path: Path) -> None:
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir(parents=True, exist_ok=True)
    (fake_repo / ".env").write_text("OPENAI_API_KEY=test\n", encoding="utf-8")

    env = _base_env(tmp_path, fake_repo)
    (Path(env["HOME"]) / ".bashrc").write_text(
        "export BR_MCP_TOKEN='bashrc_token'\n", encoding="utf-8"
    )

    result = _run_script(env=env)

    assert result.returncode == 0
    assert result.stdout.strip() == "bashrc_token"


def test_resolver_fails_with_readable_error_when_missing(tmp_path: Path) -> None:
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir(parents=True, exist_ok=True)
    (fake_repo / ".env").write_text("OPENAI_API_KEY=test\n", encoding="utf-8")

    env = _base_env(tmp_path, fake_repo)
    (Path(env["HOME"]) / ".bashrc").write_text(
        "export SOMETHING_ELSE=value\n", encoding="utf-8"
    )

    result = _run_script(env=env)

    assert result.returncode == 1
    assert result.stdout.strip() == ""
    assert "Unable to resolve BR_MCP_TOKEN." in result.stderr
    assert str(fake_repo / ".env") in result.stderr
    assert str(Path(env["HOME"]) / ".bashrc") in result.stderr
