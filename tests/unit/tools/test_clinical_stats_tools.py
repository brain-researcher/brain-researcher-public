"""Tests for clinical statistics tools in grandmaster/clinical_stats_tools.py."""

from __future__ import annotations

import pandas as pd
from pathlib import Path

import numpy as np

from brain_researcher.services.tools.grandmaster.clinical_stats_tools import (
    analyze_clinical_correlation_tool,
    analyze_longitudinal_lme_tool,
    compute_trajectory_similarity_tool,
    compare_to_normative_model_tool,
)


def test_analyze_clinical_correlation_tool(tmp_path: Path):
    """Test clinical correlation analysis between brain features and clinical scores."""
    np.random.seed(42)
    n = 10

    # Create test features data
    features = pd.DataFrame({
        'participant_id': [f'sub-{i:02d}' for i in range(1, n+1)],
        'fc_strength': np.random.rand(n) * 0.5 + 0.3,
        'network_efficiency': np.random.rand(n) * 0.3 + 0.5,
        'cortical_thickness': np.random.rand(n) * 0.4 + 1.5,
    })

    # Create test clinical data
    clinical = pd.DataFrame({
        'participant_id': [f'sub-{i:02d}' for i in range(1, n+1)],
        'age': np.random.randint(20, 40, n),
        'reaction_time': np.random.randint(400, 600, n),
        'score': np.random.rand(n) * 50 + 50,
    })

    features_file = tmp_path / "features.csv"
    clinical_file = tmp_path / "clinical.csv"
    output_file = tmp_path / "clinical_correlation.tsv"

    features.to_csv(features_file, index=False)
    clinical.to_csv(clinical_file, index=False)

    # Run the tool
    result = analyze_clinical_correlation_tool(
        features_file=str(features_file),
        clinical_file=str(clinical_file),
        output_file=str(output_file),
    )

    # Validate results
    assert result["status"] == "success"
    assert "outputs" in result
    assert "table" in result["outputs"]
    assert Path(result["outputs"]["table"]).exists()

    # Check output format
    output_df = pd.read_csv(result["outputs"]["table"], sep="\t")
    expected_cols = ["feature", "clinical", "beta", "pvalue", "n"]
    assert all(col in output_df.columns for col in expected_cols)

    # Validate data
    assert (output_df["pvalue"].between(0, 1)).all(), "P-values should be in [0, 1]"
    assert output_df.notna().all().all(), "No NaN values expected"


def test_compare_to_normative_model_tool(tmp_path: Path):
    """Test normative model comparison (z-score deviation)."""
    np.random.seed(42)

    # Create normative model data (group statistics)
    normative_mean = pd.DataFrame({
        'feature': ['fc_frontoparietal', 'fc_default_mode', 'fc_salience'],
        'stat': [0.45, 0.52, 0.38],
    })

    normative_std = pd.DataFrame({
        'feature': ['fc_frontoparietal', 'fc_default_mode', 'fc_salience'],
        'stat': [0.08, 0.10, 0.07],
    })

    # Create single subject data
    subject_features = pd.DataFrame({
        'feature': ['fc_frontoparietal', 'fc_default_mode', 'fc_salience'],
        'value': [0.55, 0.48, 0.41],
    })

    mean_file = tmp_path / "normative_mean.csv"
    std_file = tmp_path / "normative_std.csv"
    subject_file = tmp_path / "subject_features.csv"
    output_file = tmp_path / "normative_deviation.tsv"

    normative_mean.to_csv(mean_file, index=False)
    normative_std.to_csv(std_file, index=False)
    subject_features.to_csv(subject_file, index=False)

    # Run the tool
    result = compare_to_normative_model_tool(
        subject_features=str(subject_file),
        normative_mean=str(mean_file),
        normative_std=str(std_file),
        output_file=str(output_file),
    )

    # Validate results
    assert result["status"] == "success"
    assert Path(result["outputs"]["deviation_table"]).exists()

    # Check z-scores are computed correctly
    output_df = pd.read_csv(result["outputs"]["deviation_table"], sep="\t")
    assert "z" in output_df.columns
    assert output_df.notna().all().all()


def test_compute_trajectory_similarity_tool(tmp_path: Path):
    """Test longitudinal trajectory similarity analysis."""
    np.random.seed(42)

    # Create mock longitudinal trajectories
    data = []
    for sub_id in range(1, 4):
        trajectory = np.arange(1, 6) * 0.5 + np.random.randn(5) * 0.2 + sub_id * 0.3
        for t, val in enumerate(trajectory, 1):
            data.append({'id': f'sub-{sub_id:02d}', 'time': t, 'value': val})

    trajectories_file = tmp_path / "trajectories.csv"
    output_file = tmp_path / "trajectory_similarity.tsv"

    pd.DataFrame(data).to_csv(trajectories_file, index=False)

    # Run the tool
    result = compute_trajectory_similarity_tool(
        trajectories_file=str(trajectories_file),
        id_col='id',
        time_col='time',
        value_col='value',
        output_file=str(output_file),
    )

    # Validate results
    assert result["status"] == "success"
    assert Path(result["outputs"]["similarity_table"]).exists()

    # Check output format
    output_df = pd.read_csv(result["outputs"]["similarity_table"], sep="\t")
    expected_cols = ["id1", "id2", "pearson", "n"]
    assert all(col in output_df.columns for col in expected_cols)


def test_analyze_longitudinal_lme_tool(tmp_path: Path):
    """Test linear mixed-effects model for longitudinal data."""
    np.random.seed(42)

    # Create mock longitudinal data with repeated measures
    data = []
    for sub_id in range(1, 6):
        base_score = 10 + sub_id * 2
        for session in range(1, 4):
            score = base_score + session * 2 + np.random.randn() * 1
            data.append({
                'participant_id': f'sub-{sub_id:02d}',
                'session': session,
                'score': score,
            })

    features_file = tmp_path / "longitudinal_data.csv"
    output_file = tmp_path / "longitudinal_lme.tsv"

    pd.DataFrame(data).to_csv(features_file, index=False)

    # Run the tool
    result = analyze_longitudinal_lme_tool(
        features_file=str(features_file),
        subject_col='participant_id',
        time_col='session',
        dv_col='score',
        output_file=str(output_file),
    )

    # Validate results
    assert result["status"] == "success"
    assert Path(result["outputs"]["summary_txt"]).exists()

    # Check that summary contains fixed effects
    summary_text = Path(result["outputs"]["summary_txt"]).read_text()
    assert "Intercept" in summary_text or "session" in summary_text
