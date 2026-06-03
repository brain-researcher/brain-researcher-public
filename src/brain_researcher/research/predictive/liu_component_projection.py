"""Project HCP behavioral items into Liu-style ICA component scores."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import scipy.io as sio
from scipy import stats

SUBCORTEX_ICA_MAT_URL = (
    "https://raw.githubusercontent.com/yetianmed/subcortex/master/Behavior/ica.mat"
)
SUBCORTEX_SUPPLEMENT_URL = (
    "https://static-content.springer.com/esm/art%3A10.1038%2Fs41593-020-00711-6/"
    "MediaObjects/41593_2020_711_MOESM1_ESM.pdf"
)

SUPPLEMENTARY_TABLE4_ROWS: list[tuple[str, str]] = [
    ("MMSE_Score", "MMSE"),
    ("PSQI_Score", "PSQI"),
    ("PSQI_TooCold", "PSQI (TooCold)"),
    ("PSQI_TooHot", "PSQI (TooHot)"),
    ("PSQI_BadDream", "PSQI (BadDream)"),
    ("PSQI_Pain", "PSQI (Pain)"),
    ("PicSeq_Unadj", "Episodic Memory (PicSeq)"),
    ("CardSort_Unadj", "Cognitive Flexibility"),
    ("Flanker_Unadj", "Inhibition"),
    ("PMAT24_A_CR", "Fluid Intelligence (CR)"),
    ("PMAT24_A_SI", "Fluid Intelligence (SI)"),
    ("PMAT24_A_RTCR", "Fluid Intelligence (RTCR)"),
    ("ReadEng_Unadj", "Reading Decoding"),
    ("PicVocab_Unadj", "Vocabulary Comprehension "),
    ("ProcSpeed_Unadj", "Processing Speed"),
    ("DDisc_AUC_200", "Delay Discounting"),
    ("VSPLOT_TC", "Spatial Orientation (TC)"),
    ("VSPLOT_CRTE", "Spatial Orientation (CRTE)"),
    ("VSPLOT_OFF", "Spatial Orientation (OFF)"),
    ("SCPT_TPRT", "Sustained Attention (TPRT)"),
    ("SCPT_SEN", "Sustained Attention (SEN)"),
    ("SCPT_SPEC", "Sustained Attention (SPEC)"),
    ("SCPT_LRNR", "Sustained Attention (LRNR)"),
    ("IWRD_TOT", "Word Memory (TOT)"),
    ("IWRD_RTC", "Word Memory (RTC)"),
    ("ListSort_Unadj", "Working Memory"),
    ("CogFluidComp_Unadj", "CogFluidComp"),
    ("CogEarlyComp_Unadj", "CogEarlyComp"),
    ("CogTotalComp_Unadj", "CogTotalComp"),
    ("CogCrystalComp_Unadj", "CogCrystalComp"),
    ("ER40_CR", "Emotion Recognition (CR)"),
    ("ER40_CRT", "Emotion Recognition (CRT)"),
    ("ER40ANG", "Emotion Recognition (Anger)"),
    ("ER40FEAR", "Emotion Recognition (Fear)"),
    ("ER40HAP", "Emotion Recognition (Happy)"),
    ("ER40NOE", "Emotion Recognition (Neutral)"),
    ("ER40SAD", "Emotion Recognition (Sad)"),
    ("AngAffect_Unadj", "AngAffect"),
    ("AngHostil_Unadj", "AngHostil"),
    ("AngAggr_Unadj", "AngAggr"),
    ("FearAffect_Unadj", "FearAffect"),
    ("FearSomat_Unadj", "FearSomat"),
    ("Sadness_Unadj", "Sadness"),
    ("LifeSatisf_Unadj", "LifeSatisf"),
    ("MeanPurp_Unadj", "MeanPurp"),
    ("PosAffect_Unadj", "PosAffect"),
    ("Friendship_Unadj", "Friendship"),
    ("Loneliness_Unadj", "Loneliness"),
    ("PercHostil_Unadj", "PercHostil"),
    ("PercReject_Unadj", "PercReject"),
    ("EmotSupp_Unadj", "EmotSupp"),
    ("InstruSupp_Unadj", "InstruSupp"),
    ("PercStress_Unadj", "PercStress"),
    ("SelfEff_Unadj", "SelfEff"),
    ("Endurance_Unadj", "Endurance"),
    ("GaitSpeed_Comp", "GaitSpeed"),
    ("Dexterity_Unadj", "Dexterity"),
    ("Strength_Unadj", "Strength"),
    ("NEOFAC_A", "Agreeableness"),
    ("NEOFAC_O", "Openness"),
    ("NEOFAC_C", "Conscientiousness"),
    ("NEOFAC_N", "Neuroticism"),
    ("NEOFAC_E", "Extraversion"),
    ("Odor_Unadj", "Odor"),
    ("PainInterf_Tscore", "PainInterf"),
    ("Taste_Unadj", "Taste"),
    ("Mars_Final", "Visual Contrast Sensitivity"),
    ("DSM_Depr_Raw", "DSMDepr"),
    ("DSM_Anxi_Raw", "DSMAnxi"),
    ("DSM_Somp_Raw", "DSMSomp"),
    ("DSM_Avoid_Raw", "DSMAvoid"),
    ("DSM_Adh_Raw", "DSMAdh"),
    ("DSM_Inat_Raw", "DSMInat"),
    ("DSM_Hype_Raw", "DSMHype"),
    ("DSM_Antis_Raw", "DSMAntis"),
    ("ASR_Anxd_Raw", "ASRAnxd"),
    ("ASR_Witd_Raw", "ASRWitd"),
    ("ASR_Soma_Raw", "ASRSoma"),
    ("ASR_Thot_Raw", "ASRThot"),
    ("ASR_Attn_Raw", "ASRAttn"),
    ("ASR_Aggr_Raw", "ASRAggr"),
    ("ASR_Rule_Raw", "ASRRule"),
    ("ASR_Intr_Raw", "ASRIntr"),
    ("ASR_Oth_Raw", "ASROth"),
    ("ASR_Crit_Raw", "ASRCrit"),
    ("Num_Days_Drank_7days", "Alcohol Use"),
    ("SSAGA_Alc_D4_Dp_Sx", "Alcohol Dependence (Sx)"),
    ("SSAGA_Alc_D4_Ab_Dx", "Alcohol Abuse (Dx)"),
    ("SSAGA_Alc_D4_Ab_Sx", "Alcohol Abuse (Sx)"),
    ("SSAGA_Alc_D4_Dp_Dx", "Alcohol Dependence (Dx)"),
    ("Num_Days_Used_Any_Tobacco_7days", "Tobacco Use"),
    ("SSAGA_TB_Smoking_History", "Smoking History"),
    ("SSAGA_TB_Still_Smoking", "Current Smoking"),
    ("SSAGA_Times_Used_Illicits", "Illicits Use"),
    ("SSAGA_Times_Used_Cocaine", "Cocaine"),
    ("SSAGA_Times_Used_Hallucinogens", "Hallucinogens"),
    ("SSAGA_Times_Used_Opiates", "Opiates"),
    ("SSAGA_Times_Used_Sedatives", "Sedatives"),
    ("SSAGA_Times_Used_Stimulants", "Stimulants"),
    ("SSAGA_Mj_Use", "Marijuana History"),
    ("SSAGA_Mj_Ab_Dep", "Marijuana Dependence"),
    ("SSAGA_Mj_Times_Used", "Marijuana"),
    ("Emotion_Task_Acc", "Emotion Task"),
    ("Gambling_Task_Perc_Larger", "Gambling Task (Larger)"),
    ("Gambling_Task_Perc_Smaller", "Gambling Task (Smaller)"),
    ("Language_Task_Acc", "Language Task"),
    ("Relational_Task_Acc", "Relational Task"),
    ("Social_Task_Perc_TOM", "Social Task"),
    ("WM_Task_Acc", "WM Task"),
]

EXPECTED_HEADER3_NAMES = [row[1] for row in SUPPLEMENTARY_TABLE4_ROWS]
EXPECTED_BEHAVIOR_COLUMNS = [row[0] for row in SUPPLEMENTARY_TABLE4_ROWS]

COMPONENT_COLUMN_TO_ROW_INDEX = {
    "ICA_Cognition": 0,
    "ICA_TobaccoUse": 2,
    "ICA_PersonalityEmotion": 3,
    "ICA_IllicitDrugUse": 1,
    "ICA_MentalHealth": 4,
}

COMPONENT_TOP_WEIGHT_HINTS = {
    "ICA_Cognition": [
        "CogFluidComp",
        "CogEarlyComp",
        "CogTotalComp",
        "Cognitive Flexibility",
    ],
    "ICA_TobaccoUse": ["Tobacco Use", "Smoking History"],
    "ICA_PersonalityEmotion": ["Loneliness", "PercReject", "Sadness", "LifeSatisf"],
    "ICA_IllicitDrugUse": ["Marijuana", "Illicits Use", "Cocaine", "Hallucinogens"],
    "ICA_MentalHealth": ["DSMAdh", "DSMHype", "ASRIntr", "DSMAnxi"],
}

DEFAULT_CONTINUOUS_UNIQUE_THRESHOLD = 7
CONTINUOUS_UNIQUE_COUNT_OVERRIDES = {"MMSE_Score", "Odor_Unadj"}


@dataclass(frozen=True)
class LiuProjectionArtifacts:
    component_scores: pd.DataFrame
    provenance: dict[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_header3_names(mat_payload: dict[str, Any]) -> list[str]:
    return [
        str(x[0]) if hasattr(x, "__len__") else str(x)
        for x in mat_payload["header3"].ravel()
    ]


def behavior_column_mapping() -> dict[str, str]:
    return dict(zip(EXPECTED_HEADER3_NAMES, EXPECTED_BEHAVIOR_COLUMNS, strict=True))


def download_demixing_matrix(
    destination: Path, *, url: str = SUBCORTEX_ICA_MAT_URL
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return destination


def load_demixing_matrix(mat_path: Path) -> tuple[np.ndarray, list[str]]:
    payload = sio.loadmat(mat_path)
    if "w_final" not in payload or "header3" not in payload:
        raise ValueError(f"Unexpected ICA MAT payload keys: {sorted(payload)}")
    w_final = np.asarray(payload["w_final"], dtype=float)
    if w_final.shape != (5, 109):
        raise ValueError(f"Expected w_final shape (5, 109), found {w_final.shape}")
    header3_names = _read_header3_names(payload)
    return w_final, header3_names


def validate_header_alignment(header3_names: list[str]) -> None:
    if header3_names != EXPECTED_HEADER3_NAMES:
        raise ValueError(
            "Published de-mixing matrix header order differs from Supplementary Table 4 "
            f"mapping. Expected {EXPECTED_HEADER3_NAMES[:5]}..., got {header3_names[:5]}..."
        )


def encode_sex(series: pd.Series) -> pd.Series:
    mapping = {"M": 0.0, "Male": 0.0, "F": 1.0, "Female": 1.0, 0: 0.0, 1: 1.0}
    encoded = series.map(mapping)
    return pd.to_numeric(encoded, errors="coerce")


def inverse_gaussian_rank_transform(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="raise").to_numpy(dtype=float)
    if values.size == 0:
        return series.astype(float)
    ranks = stats.rankdata(values, method="average")
    transformed = stats.norm.ppf((ranks - 0.5) / values.size)
    return pd.Series(transformed, index=series.index, dtype=float)


def _impute_value(series: pd.Series, *, continuous: bool) -> float:
    if continuous:
        return float(series.median())
    mode = series.mode(dropna=True)
    if not mode.empty:
        return float(mode.iloc[0])
    return float(series.iloc[0])


def infer_continuous_columns(
    complete_cases: pd.DataFrame,
    *,
    unique_threshold: int = DEFAULT_CONTINUOUS_UNIQUE_THRESHOLD,
    overrides: set[str] | None = None,
) -> list[str]:
    overrides = CONTINUOUS_UNIQUE_COUNT_OVERRIDES if overrides is None else overrides
    continuous = []
    for column in EXPECTED_BEHAVIOR_COLUMNS:
        unique_count = complete_cases[column].nunique(dropna=True)
        if unique_count > unique_threshold or column in overrides:
            continuous.append(column)
    if len(continuous) != 87:
        raise ValueError(
            "Continuous-column heuristic no longer reproduces the paper's 87/109 split; "
            f"got {len(continuous)} columns"
        )
    return continuous


def top_weight_items_for_row(
    w_final: np.ndarray,
    header3_names: list[str],
    row_index: int,
    *,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    row = w_final[row_index]
    top_indices = np.argsort(-np.abs(row))[:top_k]
    return [
        {
            "header3_name": header3_names[index],
            "weight": float(row[index]),
            "abs_weight": float(abs(row[index])),
        }
        for index in top_indices
    ]


def project_liu_component_scores(
    behavior_df: pd.DataFrame,
    *,
    demixing_matrix: np.ndarray,
    header3_names: list[str],
    source_behavior_csv_path: Path,
    demixing_mat_path: Path,
    selected_subject_ids: list[str] | None = None,
    selected_subject_list_path: Path | None = None,
    age_column: str = "Age_in_Yrs",
    sex_column: str = "Gender",
    subject_id_column: str = "Subject",
) -> LiuProjectionArtifacts:
    validate_header_alignment(header3_names)

    required_columns = [
        subject_id_column,
        age_column,
        sex_column,
        *EXPECTED_BEHAVIOR_COLUMNS,
    ]
    missing_columns = [
        column for column in required_columns if column not in behavior_df.columns
    ]
    if missing_columns:
        raise ValueError(f"Missing required behavior columns: {missing_columns}")

    working = behavior_df.loc[:, required_columns].copy()
    working = working.replace({"": np.nan})
    working[age_column] = pd.to_numeric(working[age_column], errors="coerce")
    working[sex_column] = encode_sex(working[sex_column])
    for column in EXPECTED_BEHAVIOR_COLUMNS:
        working[column] = pd.to_numeric(working[column], errors="coerce")

    source_row_count = len(working)
    working = working.dropna(subset=[age_column, sex_column]).copy()
    age_sex_available_row_count = len(working)
    complete_cases = working.dropna(subset=EXPECTED_BEHAVIOR_COLUMNS).copy()
    if complete_cases.empty:
        raise ValueError(
            "No complete-case rows remain after filtering the 109 behavior items"
        )

    continuous_columns = infer_continuous_columns(complete_cases)
    working = working.assign(
        _subject_key=working[subject_id_column].astype(str),
    )
    if working["_subject_key"].duplicated().any():
        duplicated = (
            working.loc[working["_subject_key"].duplicated(), "_subject_key"]
            .astype(str)
            .tolist()
        )
        raise ValueError(f"Duplicate subject ids in behavior CSV: {duplicated[:10]}")

    residual_columns: dict[str, pd.Series] = {}
    residual_impute_values: dict[str, float] = {}
    raw_impute_values: dict[str, float] = {}
    for column in EXPECTED_BEHAVIOR_COLUMNS:
        observed_raw = working[column].dropna()
        if observed_raw.empty:
            raise ValueError(f"No observed values available for {column}")
        is_continuous = column in continuous_columns
        raw_impute_values[column] = _impute_value(
            observed_raw, continuous=is_continuous
        )

        transformed_column = pd.Series(np.nan, index=working.index, dtype=float)
        if is_continuous:
            transformed_observed = inverse_gaussian_rank_transform(
                observed_raw.astype(float)
            )
            transformed_column.loc[observed_raw.index] = transformed_observed.astype(
                float
            )
        else:
            transformed_column.loc[observed_raw.index] = observed_raw.astype(float)

        nonmissing_mask = transformed_column.notna()
        age_values = working.loc[nonmissing_mask, age_column].to_numpy(dtype=float)
        sex_values = working.loc[nonmissing_mask, sex_column].to_numpy(dtype=float)
        design = np.column_stack(
            [
                np.ones(nonmissing_mask.sum(), dtype=float),
                age_values - age_values.mean(),
                sex_values - sex_values.mean(),
            ]
        )
        outcome = transformed_column.loc[nonmissing_mask].to_numpy(dtype=float)
        beta, *_ = np.linalg.lstsq(design, outcome, rcond=None)
        residual = pd.Series(np.nan, index=working.index, dtype=float)
        residual.loc[nonmissing_mask] = outcome - design @ beta
        residual_columns[column] = residual
        residual_impute_values[column] = float(residual.loc[nonmissing_mask].median())

    residuals = pd.DataFrame(residual_columns, index=working.index)

    if selected_subject_ids is None:
        selected = complete_cases.copy()
        selected_subject_keys = selected[subject_id_column].astype(str).tolist()
        selected_subject_order_source = "full_complete_case_behavior_cohort"
        missing_subject_ids: list[str] = []
        per_subject_missing_columns: dict[str, list[str]] = {}
        imputed_cell_count = 0
    else:
        selected_subject_keys = [
            str(subject_id).strip()
            for subject_id in selected_subject_ids
            if str(subject_id).strip()
        ]
        subject_lookup = working.set_index("_subject_key", drop=False)
        missing_subject_ids = [
            subject_id
            for subject_id in selected_subject_keys
            if subject_id not in subject_lookup.index
        ]
        if missing_subject_ids:
            raise ValueError(
                "Selected subject ids are missing from the behavior CSV: "
                f"{missing_subject_ids[:20]}"
            )
        selected = subject_lookup.loc[selected_subject_keys].copy()
        selected_subject_order_source = "explicit_subject_list"
        per_subject_missing_columns = {}
        imputed_cell_count = 0
        residual_selected = (
            residuals.set_index(working["_subject_key"])
            .loc[selected_subject_keys]
            .copy()
        )
        raw_selected = selected.set_index("_subject_key", drop=False)
        for subject_id in selected_subject_keys:
            missing_columns = [
                column
                for column in EXPECTED_BEHAVIOR_COLUMNS
                if pd.isna(raw_selected.at[subject_id, column])
            ]
            if missing_columns:
                per_subject_missing_columns[subject_id] = missing_columns
            for column in missing_columns:
                residual_selected.at[subject_id, column] = residual_impute_values[
                    column
                ]
                raw_selected.at[subject_id, column] = raw_impute_values[column]
                imputed_cell_count += 1
        selected = raw_selected.reset_index(drop=True)
        residuals = residual_selected.reset_index(drop=True)

    if selected_subject_ids is None:
        residual_matrix = residuals.loc[
            complete_cases.index, EXPECTED_BEHAVIOR_COLUMNS
        ].to_numpy(dtype=float)
    else:
        residual_matrix = residuals.loc[:, EXPECTED_BEHAVIOR_COLUMNS].to_numpy(
            dtype=float
        )
    projected = residual_matrix @ demixing_matrix.T

    score_df = pd.DataFrame(
        {
            subject_id_column: selected_subject_keys,
            "ICA_Cognition": projected[
                :, COMPONENT_COLUMN_TO_ROW_INDEX["ICA_Cognition"]
            ],
            "ICA_TobaccoUse": projected[
                :, COMPONENT_COLUMN_TO_ROW_INDEX["ICA_TobaccoUse"]
            ],
            "ICA_PersonalityEmotion": projected[
                :, COMPONENT_COLUMN_TO_ROW_INDEX["ICA_PersonalityEmotion"]
            ],
            "ICA_IllicitDrugUse": projected[
                :, COMPONENT_COLUMN_TO_ROW_INDEX["ICA_IllicitDrugUse"]
            ],
            "ICA_MentalHealth": projected[
                :, COMPONENT_COLUMN_TO_ROW_INDEX["ICA_MentalHealth"]
            ],
        }
    )

    unique_counts = {
        column: int(complete_cases[column].nunique(dropna=True))
        for column in EXPECTED_BEHAVIOR_COLUMNS
    }
    provenance = {
        "line_name": "liu_component_autoresearch",
        "created_from_script_module": "brain_researcher.research.predictive.liu_component_projection",
        "source_behavior_csv_path": str(source_behavior_csv_path),
        "source_behavior_csv_sha256": _sha256(source_behavior_csv_path),
        "source_demixing_mat_path": str(demixing_mat_path),
        "source_demixing_mat_sha256": _sha256(demixing_mat_path),
        "source_demixing_mat_url": SUBCORTEX_ICA_MAT_URL,
        "source_supplement_url": SUBCORTEX_SUPPLEMENT_URL,
        "subject_id_column": subject_id_column,
        "age_column": age_column,
        "sex_column": sex_column,
        "sex_encoding": {"M": 0.0, "F": 1.0},
        "header_alignment_validated": True,
        "paper_method_summary": {
            "behavior_items": 109,
            "continuous_items_transformed": 87,
            "transform": "rank-based inverse Gaussian transformation via norm.ppf((rank - 0.5) / n)",
            "confounds_regressed": ["age", "sex"],
            "projection": "component_scores = residual_behavior_matrix @ demixing_matrix.T",
        },
        "local_projection_summary": {
            "source_row_count": source_row_count,
            "age_sex_available_row_count": age_sex_available_row_count,
            "complete_case_row_count": int(len(complete_cases)),
            "output_row_count": int(len(score_df)),
            "continuous_column_count": len(continuous_columns),
            "continuous_selection_rule": (
                "n_unique > 7 on complete-case cohort, plus MMSE_Score and Odor_Unadj overrides; "
                "matches the paper's 87/109 continuous-item count"
            ),
            "continuous_columns": continuous_columns,
            "subject_selection_mode": selected_subject_order_source,
            "selected_subject_list_path": (
                None
                if selected_subject_list_path is None
                else str(selected_subject_list_path)
            ),
            "requested_subject_count": (
                None if selected_subject_ids is None else len(selected_subject_ids)
            ),
            "missing_subject_ids_from_behavior": missing_subject_ids,
            "subjects_with_missing_items_before_imputation_count": len(
                per_subject_missing_columns
            ),
            "subjects_with_missing_items_before_imputation": per_subject_missing_columns,
            "imputed_cell_count": imputed_cell_count,
            "raw_imputation_strategy": {
                "continuous": "median of source cohort observed values",
                "categorical_or_discrete": "mode of source cohort observed values",
            },
            "residual_imputation_strategy": "median residual from source cohort observed values",
        },
        "supplementary_table4_mapping": [
            {"hcp_column": column, "header3_name": intuitive}
            for column, intuitive in SUPPLEMENTARY_TABLE4_ROWS
        ],
        "unique_value_counts_complete_case": unique_counts,
        "component_row_mapping": {
            component_column: {
                "row_index": row_index,
                "top_weight_hints": COMPONENT_TOP_WEIGHT_HINTS[component_column],
                "top_weight_items": top_weight_items_for_row(
                    demixing_matrix, header3_names, row_index
                ),
            }
            for component_column, row_index in COMPONENT_COLUMN_TO_ROW_INDEX.items()
        },
        "caveats": [
            (
                "The paper reports 958 participants after exclusions; the local ConnectomeDB export "
                f"yields {len(complete_cases)} strict complete-case rows for the 109 mapped items plus age/sex."
            ),
            (
                "This script uses the published de-mixing matrix and exact Supplementary Table 4 HCP "
                "column mapping, but reconstructs subject component scores locally because individual "
                "component weights are not publicly released."
            ),
            (
                "When an explicit FC subject list is supplied, missing behavioral items inside that "
                "cohort are imputed so the exported component CSV covers the full FC subject set."
            ),
        ],
    }
    return LiuProjectionArtifacts(component_scores=score_df, provenance=provenance)


def provenance_to_json_text(provenance: dict[str, Any]) -> str:
    return json.dumps(provenance, indent=2, sort_keys=True) + "\n"
