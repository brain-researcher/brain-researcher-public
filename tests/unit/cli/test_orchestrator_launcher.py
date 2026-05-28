from __future__ import annotations

from brain_researcher.cli.commands.services import orchestrator_launcher
from brain_researcher.config.paths import get_package_root, get_repo_root


def test_launch_orchestrator_loads_repo_env_and_uses_repo_root(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    repo_root = get_repo_root()
    package_root = get_package_root()

    def _fake_ensure_env_loaded():
        monkeypatch.setenv("BR_DEV_MODE", "true")
        monkeypatch.setenv("BR_STUDIO_JUPYTER_BASE_URL", "http://127.0.0.1:8888")
        return repo_root / ".env.local"

    def _fake_run(cmd, cwd, env, check):  # noqa: ANN001
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        captured["check"] = check

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(orchestrator_launcher, "ensure_env_loaded", _fake_ensure_env_loaded)
    monkeypatch.setattr(orchestrator_launcher, "get_repo_root", lambda: repo_root)
    monkeypatch.setattr(orchestrator_launcher, "get_package_root", lambda: package_root)
    monkeypatch.setattr(orchestrator_launcher.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(orchestrator_launcher.subprocess, "run", _fake_run)

    orchestrator_launcher.launch_orchestrator(
        host="127.0.0.1",
        port=3101,
        reload=False,
        workers=1,
    )

    assert captured["cwd"] == repo_root
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["BR_DEV_MODE"] == "true"
    assert env["BR_STUDIO_JUPYTER_BASE_URL"] == "http://127.0.0.1:8888"
    assert captured["check"] is True
    assert captured["cmd"] == [
        orchestrator_launcher.sys.executable,
        "-m",
        "uvicorn",
        "brain_researcher.services.orchestrator.main_enhanced:app",
        "--host",
        "127.0.0.1",
        "--port",
        "3101",
        "--workers",
        "1",
    ]
