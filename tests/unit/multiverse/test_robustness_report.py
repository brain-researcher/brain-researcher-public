import pandas as pd

from brain_researcher.core.analysis.multiverse_robustness_report import (
    build_multiverse_robustness_report,
)


def _make_summary_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in ("pct_active", "z_thr"):
        if col not in df.columns:
            df[col] = 0.0
    return df


def test_build_multiverse_report_defaults_and_sensitivity():
    # Four pipelines, with HRF driving the effect value for region r2.
    summary_rows = []
    for model_id, variant_id, _hrf, effect in [
        ("mv01", "v1", "canonical", 1.0),
        ("mv02", "v2", "canonical", 1.1),
        ("mv03", "v3", "derivs", 2.0),
        ("mv04", "v4", "derivs", 2.1),
    ]:
        for region_id, base in [("r1", 0.2), ("r2", effect), ("r3", -0.1)]:
            summary_rows.append(
                {
                    "model_id": model_id,
                    "variant_id": variant_id,
                    "contrast": "c1",
                    "metric": "mean_z",
                    "region_id": region_id,
                    "value": base,
                    "pct_active": 0.01,
                    "z_thr": 2.3,
                }
            )
        # Add a second contrast with fewer rows so c1 is chosen by default.
        summary_rows.append(
            {
                "model_id": model_id,
                "variant_id": variant_id,
                "contrast": "c2",
                "metric": "mean_z",
                "region_id": "r2",
                "value": 0.0,
                "pct_active": 0.0,
                "z_thr": 2.3,
            }
        )

    summary_df = _make_summary_df(summary_rows)

    variants_df = pd.DataFrame(
        [
            {
                "model_id": "mv01",
                "variant_id": "v1",
                "hrf": "canonical",
                "confounds": "24mot",
                "high_pass": 100,
            },
            {
                "model_id": "mv02",
                "variant_id": "v2",
                "hrf": "canonical",
                "confounds": "24mot",
                "high_pass": 128,
            },
            {
                "model_id": "mv03",
                "variant_id": "v3",
                "hrf": "derivs",
                "confounds": "24mot",
                "high_pass": 100,
            },
            {
                "model_id": "mv04",
                "variant_id": "v4",
                "hrf": "derivs",
                "confounds": "24mot",
                "high_pass": 128,
            },
        ]
    )

    report = build_multiverse_robustness_report(
        summary_df,
        variants_df=variants_df,
        claim="demo",
        contrast=None,
        metric="mean_z",
        region_id=None,
        active_threshold=0.0,
    )

    assert report["input"]["contrast"] == "c1"
    assert report["input"]["region_id"] == "r2"
    assert report["effect_distribution"]["n_pipelines"] == 4

    sens = report["sensitivity"]["eta2_norm"]
    assert "hrf" in sens
    assert sens["hrf"] > 0.8
    assert report["stability"]["sign_consistency"] == 1.0
    assert report["stability"]["active_frac"] == 1.0


def test_build_multiverse_report_single_pipeline_flags_caution():
    summary_df = _make_summary_df(
        [
            {
                "model_id": "mv01",
                "variant_id": "v1",
                "contrast": "c1",
                "metric": "mean_z",
                "region_id": "r1",
                "value": 1.0,
                "pct_active": 0.01,
                "z_thr": 2.3,
            }
        ]
    )
    variants_df = pd.DataFrame(
        [
            {
                "model_id": "mv01",
                "variant_id": "v1",
                "hrf": "canonical",
                "confounds": "24mot",
                "high_pass": 100,
            }
        ]
    )

    report = build_multiverse_robustness_report(
        summary_df,
        variants_df=variants_df,
        claim="demo",
        contrast="c1",
        metric="mean_z",
        region_id="r1",
        active_threshold=0.0,
    )

    assert report["effect_distribution"]["n_pipelines"] == 1
    caution = " ".join(report["stability"]["caution"])
    assert "Only one pipeline variant" in caution
