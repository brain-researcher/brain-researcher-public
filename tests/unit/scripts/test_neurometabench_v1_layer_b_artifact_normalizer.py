from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.neurometabench_v1.layer_b_artifact_normalizer import (
    normalize_case_bundle,
)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({field for row in rows for field in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_layer_b_normalizer_writes_canonical_artifacts_without_overwriting_raw(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "layer_b_123_reward"
    _write_csv(
        case_dir / "coordinate_table.csv",
        [
            {
                "Study": "12345678-1",
                "contrast_id": "reward_gt_neutral",
                "coord_x": "1",
                "coord_y": "2.25",
                "coord_z": "-3",
                "coordinate_space": "MNI",
                "source_json": "reward.json",
            },
            {
                "Study": "87654321",
                "contrast_id": "",
                "coord_x": "bad",
                "coord_y": "4",
                "coord_z": "5",
                "coordinate_space": "Talairach",
                "source_json": "reward.json",
            },
        ],
    )
    _write_csv(
        case_dir / "included_studies.csv",
        [
            {
                "id": "12345678-1",
                "source_json": "reward.json",
                "sample_size_min": "20",
            },
            {
                "id": "87654321",
                "source_json": "reward.json",
                "sample_size_max": "24",
            },
        ],
    )
    raw_coordinate_text = (case_dir / "coordinate_table.csv").read_text(
        encoding="utf-8"
    )

    manifest = normalize_case_bundle(case_dir)

    normalized_dir = case_dir / "normalized_artifacts"
    coordinate_rows = _read_csv(normalized_dir / "coordinate_table.normalized.csv")
    study_rows = _read_csv(normalized_dir / "included_studies.normalized.csv")
    written_manifest = json.loads(
        (normalized_dir / "normalization_manifest.json").read_text(encoding="utf-8")
    )

    assert manifest == written_manifest
    assert (case_dir / "coordinate_table.csv").read_text(encoding="utf-8") == raw_coordinate_text
    assert coordinate_rows[0]["study_id"] == "12345678-1"
    assert coordinate_rows[0]["analysis_id"] == "reward_gt_neutral"
    assert coordinate_rows[0]["x"] == "1"
    assert coordinate_rows[0]["y"] == "2.25"
    assert coordinate_rows[0]["space"] == "MNI"
    assert coordinate_rows[1]["analysis_id"] == "analysis_2"
    assert coordinate_rows[1]["x"] == ""
    assert coordinate_rows[1]["space"] == "TAL"
    assert coordinate_rows[1]["source_space"] == "Talairach"
    assert study_rows[0]["study_pmid"] == "12345678"
    assert study_rows[1]["study_pmid"] == "87654321"
    assert written_manifest["normalized_contract"]["coordinate_table"][
        "parseable_coordinate_rows"
    ] == 1
    assert written_manifest["normalized_contract"]["included_studies"][
        "public_identifier_coverage"
    ] == 1.0
    assert written_manifest["normalization_delta"]["raw_artifacts_overwritten"] is False


def test_layer_b_normalizer_handles_missing_raw_files(tmp_path: Path) -> None:
    case_dir = tmp_path / "layer_b_123_missing"

    manifest = normalize_case_bundle(case_dir)

    assert manifest["raw_contract"]["coordinate_table"]["present"] is False
    assert manifest["raw_contract"]["included_studies"]["present"] is False
    assert (case_dir / "normalized_artifacts" / "coordinate_table.normalized.csv").exists()
    assert (case_dir / "normalized_artifacts" / "included_studies.normalized.csv").exists()


def test_layer_b_normalizer_accepts_mni_suffix_coordinate_aliases(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "layer_b_123_mni_suffix"
    _write_csv(
        case_dir / "coordinate_table.csv",
        [
            {
                "study_id": "study-1",
                "x_tal": "8",
                "y_tal": "9",
                "z_tal": "10",
                "x_mni": "1.5",
                "y_mni": "-2",
                "z_mni": "3",
                "space_original": "Talairach",
                "space_canonical": "MNI",
            }
        ],
    )
    _write_csv(case_dir / "included_studies.csv", [{"study_id": "study-1"}])

    manifest = normalize_case_bundle(case_dir)

    coordinate_rows = _read_csv(
        case_dir / "normalized_artifacts" / "coordinate_table.normalized.csv"
    )
    assert coordinate_rows[0]["x"] == "1.5"
    assert coordinate_rows[0]["y"] == "-2"
    assert coordinate_rows[0]["z"] == "3"
    assert coordinate_rows[0]["space"] == "MNI"
    assert coordinate_rows[0]["source_space"] == "Talairach"
    assert manifest["normalized_contract"]["coordinate_table"][
        "parseable_coordinate_rows"
    ] == 1


def test_layer_b_normalizer_infers_canonical_space_from_source_space(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "layer_b_123_source_space"
    _write_csv(
        case_dir / "coordinate_table.csv",
        [
            {
                "study_id": "study-1",
                "x": "1",
                "y": "2",
                "z": "3",
                "source_space": "mni152_2mm",
            }
        ],
    )
    _write_csv(case_dir / "included_studies.csv", [{"study_id": "study-1"}])

    normalize_case_bundle(case_dir)

    coordinate_rows = _read_csv(
        case_dir / "normalized_artifacts" / "coordinate_table.normalized.csv"
    )
    assert coordinate_rows[0]["space"] == "MNI"
    assert coordinate_rows[0]["source_space"] == "mni152_2mm"
