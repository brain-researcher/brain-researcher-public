"""Surrogate calibrated-perfusion workflow helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brain_researcher.services.tools.params.asl_perfusion import (
    ASLPerfusionParameters,
    asl_perfusion_from_payload,
    run_asl_perfusion,
)
from brain_researcher.services.tools.params.cvr_breath_hold import (
    CVRBreathHoldParameters,
    cvr_breath_hold_from_payload,
    run_cvr_breath_hold,
)

_ASL_PARAM_KEYS = {
    "asl_file",
    "m0_file",
    "asl_type",
    "labeling_duration",
    "post_labeling_delay",
    "multi_delay",
    "delays",
    "use_m0",
    "m0_scale",
    "cbf_units",
    "compute_snr",
    "compute_cnr",
    "temporal_snr",
    "save_cbf",
    "save_att",
    "save_qc",
    "save_perfusion_weighted",
    "visualize",
    "random_seed",
}

_CVR_PARAM_KEYS = {
    "signal_file",
    "signal_column",
    "time_column",
    "delimiter",
    "events_file",
    "event_onset_column",
    "event_duration_column",
    "event_type_column",
    "breath_hold_label",
    "breath_hold_onsets",
    "breath_hold_durations",
    "t_r",
    "n_scans",
    "scan_start_s",
    "lag_min_s",
    "lag_max_s",
    "lag_step_s",
    "baseline_window_s",
    "standardize",
    "detrend",
}


@dataclass(frozen=True)
class CalibratedPerfusionSurrogateParameters:
    """Configuration for a surrogate calibrated-perfusion bundle."""

    output_dir: str
    asl_payload: Mapping[str, Any] = field(default_factory=dict)
    cvr_payload: Mapping[str, Any] = field(default_factory=dict)


def _subset_payload(payload: Mapping[str, Any], keys: set[str]) -> dict[str, Any]:
    return {key: payload[key] for key in keys if key in payload}


def calibrated_perfusion_surrogate_from_payload(
    payload: Mapping[str, Any],
) -> CalibratedPerfusionSurrogateParameters:
    """Split a combined payload into ASL and CVR sub-configurations."""

    output_dir = (
        payload.get("output_dir") or Path.cwd() / "calibrated_perfusion_surrogate"
    )
    return CalibratedPerfusionSurrogateParameters(
        output_dir=str(output_dir),
        asl_payload=_subset_payload(payload, _ASL_PARAM_KEYS),
        cvr_payload=_subset_payload(payload, _CVR_PARAM_KEYS),
    )


def _selected_summary_fields(
    asl_summary: Mapping[str, Any], cvr_summary: Mapping[str, Any]
) -> dict[str, Any]:
    cbf_stats = dict(asl_summary.get("cbf_statistics") or {})
    qc_metrics = dict(asl_summary.get("qc_metrics") or {})
    selected = {
        "cbf_mean": cbf_stats.get("mean"),
        "cbf_std": cbf_stats.get("std"),
        "cbf_median": cbf_stats.get("median"),
        "cbf_min": cbf_stats.get("min"),
        "cbf_max": cbf_stats.get("max"),
        "asl_type": asl_summary.get("asl_type"),
        "best_cvr_lag_s": cvr_summary.get("best_lag_s"),
        "best_cvr_correlation": cvr_summary.get("best_correlation"),
        "best_cvr_beta": cvr_summary.get("best_beta"),
        "best_cvr_intercept": cvr_summary.get("best_intercept"),
        "cvr_n_events": cvr_summary.get("n_events"),
        "cvr_event_amplitude_mean": cvr_summary.get("event_amplitude_mean"),
        "cvr_event_percent_change_mean": cvr_summary.get("event_percent_change_mean"),
        "cvr_standardize": cvr_summary.get("standardize"),
        "cvr_detrend": cvr_summary.get("detrend"),
        "asl_snr": qc_metrics.get("snr"),
        "asl_cnr": qc_metrics.get("cnr"),
        "asl_temporal_snr": qc_metrics.get("temporal_snr"),
    }
    return selected


def run_calibrated_perfusion_surrogate(
    params: CalibratedPerfusionSurrogateParameters,
) -> dict[str, object]:
    """Run ASL perfusion and CVR breath-hold helpers and bundle their outputs.

    This is explicitly a surrogate, not a CMRO2/OEF estimator.
    """

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    asl_out_dir = out_dir / "asl"
    cvr_out_dir = out_dir / "cvr"
    asl_payload = dict(params.asl_payload)
    cvr_payload = dict(params.cvr_payload)
    asl_payload["output_dir"] = str(asl_out_dir)
    cvr_payload["output_dir"] = str(cvr_out_dir)

    asl_params: ASLPerfusionParameters = asl_perfusion_from_payload(asl_payload)
    cvr_params: CVRBreathHoldParameters = cvr_breath_hold_from_payload(cvr_payload)

    asl_result = run_asl_perfusion(asl_params)
    cvr_result = run_cvr_breath_hold(cvr_params)

    combined_summary = {
        "tool_id": "calibrated_perfusion_surrogate",
        "calibration_type": "surrogate",
        "cmro2_estimated": False,
        "oef_estimated": False,
        "interpretation": (
            "Bundles ASL perfusion and CVR breath-hold summaries to contextualize "
            "vascular contribution; does not estimate CMRO2."
        ),
        "asl_summary": asl_result["summary"],
        "cvr_summary": cvr_result["summary"],
        "selected_metrics": _selected_summary_fields(
            asl_result["summary"], cvr_result["summary"]
        ),
    }

    summary_path = out_dir / "calibrated_perfusion_surrogate_summary.json"
    summary_tsv = out_dir / "calibrated_perfusion_surrogate_summary.tsv"
    manifest_path = out_dir / "calibrated_perfusion_surrogate_manifest.json"

    summary_path.write_text(
        json.dumps(combined_summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    rows = ["metric\tvalue"]
    for key, value in combined_summary["selected_metrics"].items():
        rows.append(f"{key}\t{value}")
    summary_tsv.write_text("\n".join(rows) + "\n", encoding="utf-8")

    manifest = {
        "tool_id": "calibrated_perfusion_surrogate",
        "input_files": {
            "asl_file": str(Path(asl_params.asl_file)),
            "signal_file": str(Path(cvr_params.signal_file)),
        },
        "subtools": {
            "asl_perfusion": asl_result,
            "cvr_breath_hold": cvr_result,
        },
        "summary_json": str(summary_path),
        "summary_tsv": str(summary_tsv),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    return {
        "outputs": {
            "asl_outputs_dir": str(asl_out_dir),
            "cvr_outputs_dir": str(cvr_out_dir),
            "summary_json": str(summary_path),
            "summary_tsv": str(summary_tsv),
            "manifest_json": str(manifest_path),
        },
        "summary": combined_summary,
        "message": (
            "Surrogate calibrated-perfusion bundle completed; CMRO2 was not estimated."
        ),
    }


__all__ = [
    "CalibratedPerfusionSurrogateParameters",
    "calibrated_perfusion_surrogate_from_payload",
    "run_calibrated_perfusion_surrogate",
]
