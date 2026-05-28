from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.neurometabench_v1 import layer_a_baselines as baselines
from scripts.neurometabench_v1.shared import read_jsonl


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_layer_a_fixture(tmp_path: Path) -> tuple[Path, Path]:
    data_dir = tmp_path / "data"
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "topic": "Reward",
                "search": "reward fMRI",
                "inclusion": "whole-brain reward studies",
                "exclusion": "ROI-only",
                "method": "ALE",
                "modality": "fMRI",
                "selected_n": "1",
                "gt_pmids": ["1"],
                "has_gt": True,
                "primary_task_layer": "layer_a_screening_with_justification",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_csv(
        data_dir / "all_studies.csv",
        [
            {
                "meta_pmid": "123",
                "study_pmid": "1",
                "status": "YES",
                "final_status": "YES",
                "title": "Reward fMRI task",
                "year": "2020",
            },
            {
                "meta_pmid": "123",
                "study_pmid": "2",
                "status": "NO",
                "final_status": "NO",
                "title": "Motor control task",
                "year": "2020",
            },
        ],
    )
    return cases_path, data_dir


def _absent_detection() -> baselines.ExternalASReviewDetection:
    return baselines.ExternalASReviewDetection(
        checked=True,
        available=False,
        import_error="ModuleNotFoundError: No module named 'asreview'",
        import_error_type="ModuleNotFoundError",
    )


def test_detect_external_asreview_reports_absent_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baselines.importlib.util, "find_spec", lambda name: None)

    detection = baselines.detect_external_asreview()

    assert detection.checked is True
    assert detection.available is False
    assert detection.version is None
    assert detection.import_error_type == "ModuleNotFoundError"
    assert "No module named 'asreview'" in str(detection.import_error)


def test_external_asreview_mode_fails_clearly_when_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases_path, data_dir = _write_layer_a_fixture(tmp_path)
    output = tmp_path / "external_predictions.jsonl"
    monkeypatch.setattr(baselines, "detect_external_asreview", _absent_detection)

    with pytest.raises(RuntimeError, match="optional package 'asreview' is unavailable"):
        baselines.build_layer_a_baseline_predictions(
            cases_path,
            output,
            data_dir=data_dir,
            systems=["asreview_style"],
            candidate_source="closed_world",
            asreview_mode="external",
        )

    assert not output.exists()


def test_asreview_style_and_auto_fallback_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases_path, data_dir = _write_layer_a_fixture(tmp_path)

    def unexpected_detection() -> baselines.ExternalASReviewDetection:
        raise AssertionError("style mode should not probe optional ASReview")

    monkeypatch.setattr(baselines, "detect_external_asreview", unexpected_detection)
    style_output = tmp_path / "style_predictions.jsonl"
    style_summary = baselines.build_layer_a_baseline_predictions(
        cases_path,
        style_output,
        data_dir=data_dir,
        systems=["asreview_style"],
        candidate_source="closed_world",
        asreview_mode="style",
    )
    style_row = read_jsonl(style_output)[0]
    style_metadata = style_row["metadata"]

    assert style_summary["asreview_mode"] == "style"
    assert style_summary["external_asreview_detection"]["checked"] is False
    assert style_row["asreview_backend"] == "asreview_style"
    assert style_metadata["asreview_mode_requested"] == "style"
    assert style_metadata["asreview_mode_resolved"] == "style"
    assert style_metadata["asreview_backend"] == "asreview_style"
    assert style_metadata["fallback_from_external_asreview"] is False
    assert style_metadata["external_asreview_detection"]["checked"] is False

    monkeypatch.setattr(baselines, "detect_external_asreview", _absent_detection)
    auto_output = tmp_path / "auto_predictions.jsonl"
    auto_summary = baselines.build_layer_a_baseline_predictions(
        cases_path,
        auto_output,
        data_dir=data_dir,
        systems=["asreview_style"],
        candidate_source="closed_world",
        asreview_mode="auto",
    )
    auto_row = read_jsonl(auto_output)[0]
    auto_metadata = auto_row["metadata"]

    assert auto_summary["asreview_mode"] == "auto"
    assert auto_summary["external_asreview_detection"]["available"] is False
    assert auto_row["asreview_backend"] == "asreview_style"
    assert auto_metadata["asreview_mode_requested"] == "auto"
    assert auto_metadata["asreview_mode_resolved"] == "style"
    assert auto_metadata["asreview_backend"] == "asreview_style"
    assert auto_metadata["fallback_from_external_asreview"] is True
    assert auto_metadata["fallback_reason"] == "external_asreview_unavailable"
    assert auto_metadata["external_asreview_detection"]["available"] is False
