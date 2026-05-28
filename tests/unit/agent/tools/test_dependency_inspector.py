from __future__ import annotations

from pathlib import Path

import pytest

from brain_researcher.services.tools.dependency_inspector import (
    collect_dependency_status,
    summarise_missing_by_category,
)


def write_manifest(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "dependencies:",
                "  - name: importlib",
                "    category: python-package",
                "    module: importlib",
                "    optional: false",
                "  - name: made-up-module",
                "    category: python-package",
                "    module: br_made_up_module_123",
                "    optional: true",
                "  - name: echo",
                "    category: executable",
                "    command: echo",
                "    optional: false",
                "  - name: imaginary-binary",
                "    category: executable",
                "    command: br_missing_binary_xyz",
                "    optional: true",
            ]
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def manifest_path(tmp_path: Path) -> Path:
    path = tmp_path / "deps.yaml"
    write_manifest(path)
    return path


def test_collect_dependency_status_reports_missing_entries(manifest_path: Path) -> None:
    statuses = collect_dependency_status(manifest_path)
    missing = [status for status in statuses if not status.present]

    assert any(status.spec.name == "importlib" and status.present for status in statuses)
    assert any(status.spec.name == "echo" and status.present for status in statuses)
    assert any(status.spec.name == "made-up-module" for status in missing)
    assert any(status.spec.name == "imaginary-binary" for status in missing)


def test_grouping_by_category(manifest_path: Path) -> None:
    statuses = collect_dependency_status(manifest_path)
    grouped = summarise_missing_by_category(statuses)

    assert "python-package" in grouped
    assert "executable" in grouped
    assert {s.spec.name for s in grouped["python-package"]} == {"made-up-module"}
    assert {s.spec.name for s in grouped["executable"]} == {"imaginary-binary"}
