from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from brain_researcher.services.tools.resolve_bids_tool import (
    ResolveBIDSArgs,
    ResolveBIDSTool,
)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_quick_resolve_finds_session_files_without_session_hint(tmp_path: Path) -> None:
    bids_root = tmp_path / "ds001"
    pre_bold = (
        bids_root
        / "sub-01"
        / "ses-pre"
        / "func"
        / "sub-01_ses-pre_task-rest_bold.nii.gz"
    )
    post_bold = (
        bids_root
        / "sub-01"
        / "ses-post"
        / "func"
        / "sub-01_ses-post_task-rest_bold.nii.gz"
    )
    _touch(pre_bold)
    _touch(post_bold)

    args = ResolveBIDSArgs(
        bids_root=str(bids_root),
        subject_id="01",
        datatype="func",
        suffix="bold",
    )

    matches = ResolveBIDSTool._quick_resolve(args)
    assert len(matches) == 2
    assert str(pre_bold) in matches
    assert str(post_bold) in matches


def test_quick_resolve_filters_by_session_hint(tmp_path: Path) -> None:
    bids_root = tmp_path / "ds002"
    pre_bold = (
        bids_root
        / "sub-01"
        / "ses-pre"
        / "func"
        / "sub-01_ses-pre_task-rest_bold.nii.gz"
    )
    post_bold = (
        bids_root
        / "sub-01"
        / "ses-post"
        / "func"
        / "sub-01_ses-post_task-rest_bold.nii.gz"
    )
    _touch(pre_bold)
    _touch(post_bold)

    args = ResolveBIDSArgs(
        bids_root=str(bids_root),
        subject_id="sub-01",
        session_id="pre",
        datatype="func",
        suffix="bold",
    )

    matches = ResolveBIDSTool._quick_resolve(args)
    assert matches == [str(pre_bold)]


def test_quick_resolve_filters_by_task_hint(tmp_path: Path) -> None:
    bids_root = tmp_path / "ds000114"
    covert_bold = (
        bids_root
        / "sub-01"
        / "ses-test"
        / "func"
        / "sub-01_ses-test_task-covertverbgeneration_bold.nii.gz"
    )
    line_bold = (
        bids_root
        / "sub-01"
        / "ses-test"
        / "func"
        / "sub-01_ses-test_task-linebisection_bold.nii.gz"
    )
    line_extra_bold = (
        bids_root
        / "sub-01"
        / "ses-test"
        / "func"
        / "sub-01_ses-test_task-linebisectionextra_bold.nii.gz"
    )
    _touch(covert_bold)
    _touch(line_bold)
    _touch(line_extra_bold)

    args = ResolveBIDSArgs(
        bids_root=str(bids_root),
        subject_id="01",
        session_id="test",
        task_id=" task-linebisection ",
        datatype="func",
        suffix="bold",
    )

    matches = ResolveBIDSTool._quick_resolve(args)
    assert matches == [str(line_bold)]


def test_run_pybids_filter_uses_normalized_task_hint(
    tmp_path: Path, monkeypatch
) -> None:
    bids_root = tmp_path / "ds000114"
    bids_root.mkdir()
    captured: dict[str, object] = {}
    resolved_path = (
        bids_root
        / "sub-01"
        / "ses-test"
        / "func"
        / "sub-01_ses-test_task-linebisection_bold.nii.gz"
    )

    class FakeBIDSLayout:
        def __init__(self, root, validate, derivatives):
            captured["root"] = root
            captured["validate"] = validate
            captured["derivatives"] = derivatives

        def get(self, return_type, invalid_filters, **filters):
            captured["return_type"] = return_type
            captured["invalid_filters"] = invalid_filters
            captured["filters"] = filters
            return [str(resolved_path)]

    monkeypatch.setattr(
        ResolveBIDSTool, "_quick_resolve", staticmethod(lambda args: [])
    )
    monkeypatch.setitem(
        sys.modules, "bids", SimpleNamespace(BIDSLayout=FakeBIDSLayout)
    )

    result = ResolveBIDSTool()._run(
        bids_root=str(bids_root),
        subject_id="sub-01",
        session_id=" ses-test ",
        task_id=" task-linebisection ",
        datatype="func",
        suffix="bold",
    )

    assert result.status == "success"
    assert captured["invalid_filters"] == "drop"
    assert captured["filters"] == {
        "subject": "01",
        "session": "test",
        "task": "linebisection",
        "datatype": "func",
        "suffix": "bold",
        "extension": [".nii", ".nii.gz"],
    }
    metadata = result.data["outputs"]["metadata"]
    assert metadata["subject"] == "01"
    assert metadata["session"] == "test"
    assert metadata["task"] == "linebisection"
