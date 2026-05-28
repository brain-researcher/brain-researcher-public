from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from brain_researcher.research.predictive.liu_component_projection import (
    COMPONENT_COLUMN_TO_ROW_INDEX,
    EXPECTED_BEHAVIOR_COLUMNS,
    EXPECTED_HEADER3_NAMES,
    SUPPLEMENTARY_TABLE4_ROWS,
    behavior_column_mapping,
    infer_continuous_columns,
    inverse_gaussian_rank_transform,
    project_liu_component_scores,
    validate_header_alignment,
)


def test_supplementary_table_mapping_is_complete_and_unique() -> None:
    assert len(SUPPLEMENTARY_TABLE4_ROWS) == 109
    assert len(EXPECTED_BEHAVIOR_COLUMNS) == 109
    assert len(EXPECTED_HEADER3_NAMES) == 109
    assert len(set(EXPECTED_BEHAVIOR_COLUMNS)) == 109
    assert len(set(EXPECTED_HEADER3_NAMES)) == 109

    mapping = behavior_column_mapping()
    assert len(mapping) == 109
    assert mapping["Delay Discounting"] == "DDisc_AUC_200"
    assert mapping["Visual Contrast Sensitivity"] == "Mars_Final"
    assert mapping["Cocaine"] == "SSAGA_Times_Used_Cocaine"


def test_component_row_mapping_covers_five_rows_once() -> None:
    assert set(COMPONENT_COLUMN_TO_ROW_INDEX) == {
        "ICA_Cognition",
        "ICA_TobaccoUse",
        "ICA_PersonalityEmotion",
        "ICA_IllicitDrugUse",
        "ICA_MentalHealth",
    }
    assert sorted(COMPONENT_COLUMN_TO_ROW_INDEX.values()) == [0, 1, 2, 3, 4]


def test_validate_header_alignment_requires_exact_order() -> None:
    validate_header_alignment(EXPECTED_HEADER3_NAMES)
    bad_names = list(EXPECTED_HEADER3_NAMES)
    bad_names[0], bad_names[1] = bad_names[1], bad_names[0]
    try:
        validate_header_alignment(bad_names)
    except ValueError as exc:
        assert "header order differs" in str(exc)
    else:
        raise AssertionError("Expected header-order validation to fail")


def test_inverse_gaussian_rank_transform_preserves_rank_order() -> None:
    series = pd.Series([10.0, 20.0, 30.0, 40.0])
    transformed = inverse_gaussian_rank_transform(series)
    assert transformed.is_monotonic_increasing
    assert np.isclose(float(transformed.mean()), 0.0, atol=1e-12)


def test_infer_continuous_columns_matches_paper_count_with_overrides() -> None:
    rows = 12
    low_unique = {
        "PSQI_TooCold",
        "PSQI_TooHot",
        "PSQI_BadDream",
        "PSQI_Pain",
        "ER40ANG",
        "ER40HAP",
        "ER40SAD",
        "SSAGA_Alc_D4_Dp_Sx",
        "SSAGA_Alc_D4_Ab_Dx",
        "SSAGA_Alc_D4_Ab_Sx",
        "SSAGA_Alc_D4_Dp_Dx",
        "SSAGA_TB_Smoking_History",
        "SSAGA_TB_Still_Smoking",
        "SSAGA_Times_Used_Illicits",
        "SSAGA_Times_Used_Cocaine",
        "SSAGA_Times_Used_Hallucinogens",
        "SSAGA_Times_Used_Opiates",
        "SSAGA_Times_Used_Sedatives",
        "SSAGA_Times_Used_Stimulants",
        "SSAGA_Mj_Use",
        "SSAGA_Mj_Ab_Dep",
        "SSAGA_Mj_Times_Used",
    }

    payload: dict[str, list[float]] = {}
    for index, column in enumerate(EXPECTED_BEHAVIOR_COLUMNS):
        if column == "MMSE_Score":
            payload[column] = [23, 24, 25, 26, 27, 28, 29, 29, 30, 30, 30, 30]
        elif column == "Odor_Unadj":
            payload[column] = [82.74, 88.61, 93.38, 96.87, 101.12, 108.79, 122.25] * 2
            payload[column] = payload[column][:rows]
        elif column in low_unique:
            payload[column] = [float((i + index) % 4) for i in range(rows)]
        else:
            payload[column] = [float(index * 100 + i) for i in range(rows)]

    frame = pd.DataFrame(payload)
    continuous = infer_continuous_columns(frame)
    assert len(continuous) == 87
    assert "MMSE_Score" in continuous
    assert "Odor_Unadj" in continuous
    assert "SSAGA_TB_Still_Smoking" not in continuous


def test_project_component_scores_can_impute_selected_fc_subjects() -> None:
    rows = 12
    low_unique = {
        "PSQI_TooCold",
        "PSQI_TooHot",
        "PSQI_BadDream",
        "PSQI_Pain",
        "ER40ANG",
        "ER40HAP",
        "ER40SAD",
        "SSAGA_Alc_D4_Dp_Sx",
        "SSAGA_Alc_D4_Ab_Dx",
        "SSAGA_Alc_D4_Ab_Sx",
        "SSAGA_Alc_D4_Dp_Dx",
        "SSAGA_TB_Smoking_History",
        "SSAGA_TB_Still_Smoking",
        "SSAGA_Times_Used_Illicits",
        "SSAGA_Times_Used_Cocaine",
        "SSAGA_Times_Used_Hallucinogens",
        "SSAGA_Times_Used_Opiates",
        "SSAGA_Times_Used_Sedatives",
        "SSAGA_Times_Used_Stimulants",
        "SSAGA_Mj_Use",
        "SSAGA_Mj_Ab_Dep",
        "SSAGA_Mj_Times_Used",
    }

    payload: dict[str, list[float | str]] = {
        "Subject": [str(100000 + i) for i in range(rows)],
        "Age_in_Yrs": [22.0 + i for i in range(rows)],
        "Gender": ["F" if i % 2 else "M" for i in range(rows)],
    }
    for index, column in enumerate(EXPECTED_BEHAVIOR_COLUMNS):
        if column == "MMSE_Score":
            payload[column] = [23, 24, 25, 26, 27, 28, 29, 29, 30, 30, 30, 30]
        elif column == "Odor_Unadj":
            values = [82.74, 88.61, 93.38, 96.87, 101.12, 108.79, 122.25] * 2
            payload[column] = values[:rows]
        elif column in low_unique:
            payload[column] = [float((i + index) % 4) for i in range(rows)]
        else:
            payload[column] = [float(index * 100 + i) for i in range(rows)]

    frame = pd.DataFrame(payload)
    frame.loc[0, "Taste_Unadj"] = np.nan

    demixing = np.zeros((5, len(EXPECTED_HEADER3_NAMES)), dtype=float)
    demixing[0, 0] = 1.0
    demixing[1, 1] = 1.0
    demixing[2, 2] = 1.0
    demixing[3, 3] = 1.0
    demixing[4, 4] = 1.0

    selected_subjects = [frame.loc[i, "Subject"] for i in [0, 1, 2]]
    artifacts = project_liu_component_scores(
        frame,
        demixing_matrix=demixing,
        header3_names=EXPECTED_HEADER3_NAMES,
        source_behavior_csv_path=Path(__file__),
        demixing_mat_path=Path(__file__),
        selected_subject_ids=selected_subjects,
    )

    assert artifacts.component_scores["Subject"].tolist() == selected_subjects
    assert len(artifacts.component_scores) == 3
    assert not artifacts.component_scores.isna().any().any()
    summary = artifacts.provenance["local_projection_summary"]
    assert summary["output_row_count"] == 3
    assert summary["subjects_with_missing_items_before_imputation_count"] == 1
    assert summary["imputed_cell_count"] == 1
    assert selected_subjects[0] in summary["subjects_with_missing_items_before_imputation"]
