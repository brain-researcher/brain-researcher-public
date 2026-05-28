from __future__ import annotations

from pathlib import Path

from brain_researcher.cli.commands.services.web_launcher import _get_web_ui_dir


def test_get_web_ui_dir_points_to_apps_web_ui() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    web_ui_dir = _get_web_ui_dir()

    assert web_ui_dir == repo_root / "apps" / "web-ui"
    assert web_ui_dir.exists()
    assert (web_ui_dir / "package.json").exists()
