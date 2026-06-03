"""
FitLins BIDS GLM implementation for Brain Researcher.

Implements FitLins (Fitting Linear Models to BIDS Datasets) for standardized
first and second-level GLM analyses following BIDS conventions.
"""

import logging
import json
import os
import sys
import subprocess
import yaml
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple
import nibabel as nib
import warnings
try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)
from brain_researcher.core.multiverse.rule_engine import generate_variants
from brain_researcher.core.multiverse.confounds import (
    confounds_families_to_patterns,
    enforce_motion_consistency,
)
from brain_researcher.core.literature.references import gather_references
from brain_researcher.services.tools.literature_tool import GLMLiteratureTool
from brain_researcher.services.tools.pipelines import (
    FitLinsParameters,
    build_fitlins_command,
    build_fitlins_env,
    fitlins_from_payload,
)
from brain_researcher.services.tools.pipelines.helpers import run_fitlins_from_dict

logger = logging.getLogger(__name__)

# Backwards compatible alias for tests/importers
FitLinsConfig = FitLinsParameters

# Minimal BIDS Stats Model JSON schema (structural checks only)
_BIDS_MODEL_SCHEMA_MIN: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["Name", "BIDSModelVersion", "Input", "Nodes"],
    "properties": {
        "Name": {"type": "string"},
        "BIDSModelVersion": {"type": "string"},
        "Input": {"type": "object"},
        "Nodes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["Level", "Name", "Model"],
                "properties": {
                    "Level": {"type": "string"},
                    "Name": {"type": "string"},
                    "GroupBy": {"type": ["array", "null", "object", "string"]},
                    "Transformations": {"type": "object"},
                    "Model": {
                        "type": "object",
                        "required": ["Type", "X"],
                        "properties": {
                            "Type": {"type": "string"},
                            "X": {"type": ["array", "string", "object"]},
                        },
                    },
                    "Contrasts": {"type": ["array", "null"]},
                    "DummyContrasts": {"type": ["array", "null", "object"]},
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Internal helpers for multiverse transforms
# ---------------------------------------------------------------------------


def _find_run_node(model: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the first node with Level == 'Run' (case-insensitive)."""
    for node in model.get("Nodes", []):
        if str(node.get("Level", "")).lower() == "run":
            return node
    return None


def _find_convolve_idx(run_node: Dict[str, Any]) -> Optional[int]:
    instr = run_node.get("Transformations", {}).get("Instructions", [])
    for i, step in enumerate(instr):
        if step.get("Name", "").lower() == "convolve":
            return i
    return None


def _apply_hrf_variant(run_node: Dict[str, Any], convolve_idx: int, mode: str) -> None:
    """Mutate the run-level Convolve instruction according to mode."""
    instr = run_node.get("Transformations", {}).get("Instructions", [])
    if convolve_idx is None or convolve_idx >= len(instr):
        return
    step = instr[convolve_idx]
    mode = mode.lower()

    if mode in {"canonical", "spm"}:
        step.update({"Model": "spm", "Derivative": False, "Dispersion": False})
        for k in ["Window", "BinSize", "FirDelays"]:
            step.pop(k, None)
    elif mode in {"derivs", "spm_time"}:
        step.update({"Model": "spm", "Derivative": True, "Dispersion": False})
        for k in ["Window", "BinSize", "FirDelays"]:
            step.pop(k, None)
    elif mode == "spm_time_dispersion":
        step.update({"Model": "spm", "Derivative": True, "Dispersion": True})
        for k in ["Window", "BinSize", "FirDelays"]:
            step.pop(k, None)
    elif mode == "glover":
        step.update({"Model": "glover", "Derivative": False, "Dispersion": False})
        for k in ["Window", "BinSize", "FirDelays"]:
            step.pop(k, None)
    elif mode == "glover_time":
        step.update({"Model": "glover", "Derivative": True, "Dispersion": False})
        for k in ["Window", "BinSize", "FirDelays"]:
            step.pop(k, None)
    elif mode == "fir":
        # Use FirDelays (supported by pybids) instead of Window/BinSize.
        # Defaults chosen conservatively (0–18s delays in 2s steps).
        fir_delays = list(range(0, 20, 2))
        step.update({"Model": "fir", "FirDelays": fir_delays})
        for k in ["Window", "BinSize", "Derivative", "Dispersion"]:
            step.pop(k, None)
    else:
        # Unknown mode: leave unchanged
        return


_CONFOUND_PREFIXES = (
    "trans_",
    "rot_",
    "a_comp_cor",
    "t_comp_cor",
    "c_comp_cor",
    "w_comp_cor",
    "global_signal",
    "csf",
    "white_matter",
    "framewise_displacement",
    "dvars",
    "std_dvars",
    "cosine",
    "non_steady_state_outlier",
    "motion_outlier",
    "aroma_motion",
    "cardiac_signal_",
    "cardiac_retroicor_",
    "respiratory_signal_",
    "respiratory_retroicor_",
    "cardiorespiratory_sum_",
    "cardiorespiratory_diff_",
    "pupil_filtered_z",
    "pupil_derivative1_z",
    "pupil_tonic_z",
    "pupil_phasic_z",
    "pupil_blink_fraction",
)


def _normalize_fitlins_hrf_model(mode: str) -> str:
    normalized = str(mode or "glover").strip().lower()
    aliases = {
        "canonical": "spm",
        "derivs": "spm_time",
        "spm": "spm",
        "spm_time": "spm_time",
        "spm_time_dispersion": "spm_time_dispersion",
        "glover": "glover",
        "glover_time": "glover_time",
        "fir": "fir",
    }
    return aliases.get(normalized, normalized)


def _coerce_family_value(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"present", "true", "yes", "1"}:
            return True
        if lowered in {"absent", "false", "no", "0"}:
            return False
    return None


def _base_confounds_families(mode: str) -> Dict[str, bool]:
    mode = mode.lower()
    with_24 = "24mot" in mode
    with_acompcor = "acompcor" in mode
    with_physio = "physio" in mode or mode == "full"
    with_pupil = "pupil" in mode or mode == "full"
    families = {
        "confounds_motion_6": True,
        "confounds_motion_24": with_24,
        "confounds_acompcor": with_acompcor,
        "confounds_cosine_dct": True,
        "confounds_physio": with_physio,
        "confounds_pupil": with_pupil,
    }
    return families


def _merge_confounds_families(mode: str, families: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    merged = _base_confounds_families(mode)
    if families:
        for axis, val in families.items():
            coerced = _coerce_family_value(val)
            if coerced is None:
                continue
            merged[axis] = coerced
    return enforce_motion_consistency(merged)


def _apply_confounds_variant(
    run_node: Dict[str, Any],
    mode: str,
    families: Optional[Dict[str, Any]] = None,
) -> None:
    """Mutate Model.X confound patterns according to mode/family flags."""
    model = run_node.get("Model", {})
    x_list = list(model.get("X", []))

    # Remove existing confound patterns but keep task regressors and intercept.
    def is_confound(tok: Any) -> bool:
        if not isinstance(tok, str):
            return False
        lowered = tok.lower()
        return lowered.startswith(_CONFOUND_PREFIXES)

    x_base = [tok for tok in x_list if not is_confound(tok)]
    confound_flags = _merge_confounds_families(mode, families)
    confounds = confounds_families_to_patterns(confound_flags)

    model["X"] = x_base + confounds


def _apply_highpass_variant(run_node: Dict[str, Any], cutoff: int) -> None:
    """Set run-level high-pass filter cutoff (in seconds)."""
    model = run_node.setdefault("Model", {})
    opts = model.setdefault("Options", {})
    opts["HighPassFilterCutoff"] = cutoff


def _extract_contrast_names(model: Dict[str, Any]) -> List[str]:
    """Collect contrast names from BIDS Stats Model nodes."""
    names: List[str] = []
    for node in model.get("Nodes", []):
        if not isinstance(node, dict):
            continue
        for contrast in node.get("Contrasts") or []:
            if isinstance(contrast, dict) and contrast.get("Name"):
                names.append(str(contrast["Name"]))
    # Preserve order, remove duplicates
    seen = set()
    out = []
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def _extract_fitlins_params(model: Dict[str, Any]) -> Dict[str, Any]:
    """Extract FitLins-relevant parameters from a Stats Model spec."""
    params: Dict[str, Any] = {}
    run_node = _find_run_node(model)
    if run_node is None:
        return params

    # HRF model from Convolve transformation
    instr = run_node.get("Transformations", {}).get("Instructions", [])
    for step in instr:
        if str(step.get("Name", "")).lower() == "convolve":
            params["hrf_model"] = step.get("Model")
            params["hrf_derivative"] = step.get("Derivative")
            params["hrf_dispersion"] = step.get("Dispersion")
            params["convolve_input"] = step.get("Input")
            break

    model_block = run_node.get("Model", {}) if isinstance(run_node.get("Model"), dict) else {}
    if model_block.get("Type"):
        params["model_type"] = model_block.get("Type")

    opts = model_block.get("Options", {}) if isinstance(model_block.get("Options"), dict) else {}
    if opts:
        params["model_options"] = opts
        if "HighPassFilterCutoff" in opts:
            params["high_pass"] = opts.get("HighPassFilterCutoff")

    x_terms = model_block.get("X", [])
    confounds: List[str] = []
    for term in x_terms if isinstance(x_terms, list) else []:
        if not isinstance(term, str):
            continue
        lowered = term.lower()
        if lowered.startswith((
            "trans_",
            "rot_",
            "cardiac_signal_",
            "cardiac_retroicor_",
            "respiratory_signal_",
            "respiratory_retroicor_",
            "cardiorespiratory_sum_",
            "cardiorespiratory_diff_",
            "pupil_filtered_z",
            "pupil_derivative1_z",
            "pupil_tonic_z",
            "pupil_phasic_z",
            "pupil_blink_fraction",
        )):
            confounds.append(term)
        elif "comp_cor" in lowered or "cosine" in lowered or "motion" in lowered:
            confounds.append(term)
    if confounds:
        params["confounds_terms"] = sorted(set(confounds))

    return params


def _build_evidence_panel(manifests: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
    """Aggregate top literature hits into a compact evidence panel."""
    hits: List[Dict[str, Any]] = []
    for entry in manifests:
        evidence = entry.get("literature_evidence") or {}
        fs = evidence.get("file_search") or {}
        for chunk in fs.get("chunks") or []:
            hits.append(chunk)

    dedup: Dict[str, Dict[str, Any]] = {}
    for hit in hits:
        key = hit.get("pmcid") or hit.get("doi") or hit.get("title") or hit.get("snippet")
        if not key or key in dedup:
            continue
        dedup[key] = {
            "pmcid": hit.get("pmcid"),
            "pmid": hit.get("pmid"),
            "doi": hit.get("doi"),
            "title": hit.get("title"),
            "score": hit.get("score"),
            "snippet": hit.get("snippet"),
        }

    ordered = sorted(
        dedup.values(),
        key=lambda h: (h.get("score") is not None, h.get("score", 0.0)),
        reverse=True,
    )
    return ordered[:top_k]


def _validate_model(model: Dict[str, Any]) -> tuple[bool, str]:
    """Lightweight validation: required keys + run node sanity + Transformations structure."""
    required_top = ["Name", "BIDSModelVersion", "Input", "Nodes"]
    for k in required_top:
        if k not in model:
            return False, f"missing top-level key {k}"
    if not isinstance(model.get("Nodes"), list) or not model["Nodes"]:
        return False, "Nodes must be non-empty list"
    run_node = _find_run_node(model)
    if run_node is None:
        return False, "missing run-level node"
    if "Model" not in run_node or "X" not in run_node.get("Model", {}):
        return False, "run-level node missing Model.X"
    # ensure Transformations dict shape
    if "Transformations" in run_node:
        tx = run_node["Transformations"]
        if not isinstance(tx, dict) or "Instructions" not in tx or not isinstance(tx["Instructions"], list):
            return False, "run-level Transformations must have Instructions list"
    # crude regressor-count sanity check
    reg_count = len(run_node.get("Model", {}).get("X", []))
    if reg_count > 200:
        return False, f"too many regressors ({reg_count})"

    # JSON Schema validation (coarse but stricter than key checks)
    if jsonschema:
        try:
            jsonschema.validate(model, _BIDS_MODEL_SCHEMA_MIN)
        except Exception as exc:
            return False, f"jsonschema: {exc}"
    else:
        warnings.warn("jsonschema not installed; skipping schema validation", RuntimeWarning)

    return True, "ok"



class AnalysisLevel(str):
    """Analysis levels for FitLins."""
    RUN = "run"
    SESSION = "session"
    SUBJECT = "subject"
    DATASET = "dataset"


class EstimatorType(str):
    """Estimator types for FitLins."""
    NILEARN = "nilearn"
    AFNI = "afni"
    NISTATS = "nistats"


class SpaceType(str):
    """Standard spaces for analysis."""
    MNI152NLIN2009CASYM = "MNI152NLin2009cAsym"
    MNI152NLIN6ASYM = "MNI152NLin6Asym"
    MNI152LIN = "MNI152Lin"
    FSNATIVE = "fsnative"
    FSAVERAGE = "fsaverage"
    FSAVERAGE5 = "fsaverage5"
    FSAVERAGE6 = "fsaverage6"
    T1W = "T1w"


class FitLinsArgs(BaseModel):
    """Arguments for FitLins BIDS GLM analysis."""

    # BIDS dataset paths
    bids_dir: str = Field(
        description="Path to BIDS dataset root directory"
    )
    output_dir: str = Field(
        description="Output directory for FitLins results"
    )
    derivatives_dir: Optional[str] = Field(
        default=None,
        description="Path to fMRIPrep derivatives (auto-detected if None)"
    )

    # Analysis specification
    model: Optional[str] = Field(
        default=None,
        description="Path to BIDS Stats Model JSON file or model name"
    )
    analysis_level: str = Field(
        default="subject",
        description="Analysis level: run, session, subject, or dataset"
    )

    # Model configuration
    hrf_model: str = Field(
        default="glover",
        description="HRF model: glover, spm, spm_time, spm_time_dispersion, glover_time, fir (also accepts aliases canonical and derivs)"
    )
    drift_model: str = Field(
        default="cosine",
        description="Drift model: cosine, polynomial, or None"
    )
    drift_order: Optional[int] = Field(
        default=None,
        description="Order for polynomial drift model"
    )

    # Preprocessing options
    smoothing: Optional[float] = Field(
        default=None,
        description="Smoothing kernel FWHM in mm (None = no smoothing)"
    )
    slice_time_ref: Optional[float] = Field(
        default=0.5,
        description="Slice timing reference (0-1, 0.5 = middle slice)"
    )

    # Space and resolution
    space: str = Field(
        default="MNI152NLin2009cAsym",
        description="Standard space for analysis"
    )
    desc: Optional[str] = Field(
        default="preproc",
        description="Description label for preprocessed files"
    )

    # Participant selection
    participant_label: Optional[List[str]] = Field(
        default=None,
        description="Participant labels to analyze (None = all)"
    )
    exclude_participant: Optional[List[str]] = Field(
        default=None,
        description="Participant labels to exclude"
    )

    # Confounds and covariates
    include_confounds: List[str] = Field(
        default=["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z"],
        description="Confound regressors to include from fMRIPrep"
    )
    confounds_file: Optional[str] = Field(
        default=None,
        description="Optional merged confounds TSV. Native FitLins stages this into a derivative-compatible confounds file; Nilearn fallback reads it directly."
    )
    confounds_target_file: Optional[str] = Field(
        default=None,
        description="Optional native derivative confounds TSV to augment when confounds_file is used with FitLins. Required when the target run cannot be inferred uniquely."
    )
    confounds_map_file: Optional[str] = Field(
        default=None,
        description="Optional JSON mapping for staging multiple external confounds TSVs into native FitLins derivative confounds targets. Use this instead of confounds_file for multi-run or multi-subject overlays."
    )
    confound_strategy: str = Field(
        default="motion",
        description="Confound strategy: motion, compcor, physio, pupil, full, or custom"
    )
    n_compcor: Optional[int] = Field(
        default=None,
        description="Number of CompCor components to include"
    )

    # Contrasts
    contrasts: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Contrast specifications (can be complex nested structure)"
    )
    auto_contrasts: bool = Field(
        default=True,
        description="Automatically generate contrasts for each condition"
    )

    # Statistical parameters
    use_derivs: bool = Field(
        default=True,
        description="Include HRF derivatives in the model"
    )
    estimator: str = Field(
        default="nilearn",
        description="Estimator backend: nilearn, afni, or nistats"
    )
    error_ts: bool = Field(
        default=False,
        description="Output time series of errors"
    )

    # Output options
    reports_only: bool = Field(
        default=False,
        description="Only generate reports without model fitting"
    )
    write_graph: bool = Field(
        default=False,
        description="Write workflow graph"
    )
    work_dir: Optional[str] = Field(
        default=None,
        description="Working directory for intermediate files"
    )

    # Advanced options
    ignore: Optional[List[str]] = Field(
        default=None,
        description="Ignore certain BIDS aspects (e.g., ['slicetiming'])"
    )
    force_index: Optional[List[str]] = Field(
        default=None,
        description="Force indexing on these metadata fields"
    )
    model_minimize_memory: bool = Field(
        default=True,
        description="Minimize memory usage during model fitting"
    )


class FitLinsTool(NeuroToolWrapper):
    """FitLins BIDS GLM analysis tool."""

    def __init__(self):
        """Initialize FitLins tool."""
        super().__init__()
        self._check_dependencies()

    def _check_dependencies(self):
        """Check FitLins dependencies."""
        self.fitlins_available = False
        self.nilearn_available = False

        # Allow a local source checkout when FitLins is not pip-installed.
        # Default: repo_root/external/openneuro_glmfitlins or env FITLINS_PATH.
        local_fitlins = os.getenv("FITLINS_PATH")
        if not local_fitlins:
            repo_root = Path(__file__).resolve().parents[4]
            candidate = repo_root / "external" / "openneuro_glmfitlins"
            if candidate.exists():
                local_fitlins = str(candidate)
        if local_fitlins and local_fitlins not in sys.path:
            sys.path.append(local_fitlins)

        # If the repo has a uv-created .venv, add its site-packages
        if local_fitlins:
            venv_site = Path(local_fitlins) / ".venv" / "lib"
            if venv_site.exists():
                for pyver in venv_site.iterdir():
                    site_pkgs = pyver / "site-packages"
                    if site_pkgs.exists() and str(site_pkgs) not in sys.path:
                        sys.path.append(str(site_pkgs))

        try:
            import fitlins
            self.fitlins_available = True
            self.fitlins_version = fitlins.__version__
            logger.info(f"FitLins {self.fitlins_version} available")
        except ImportError:
            logger.info("FitLins not installed (optional dependency)")

        try:
            import nilearn
            self.nilearn_available = True
            logger.info("Nilearn available for fallback GLM")
        except ImportError:
            logger.info("Nilearn not available (optional dependency)")

    def get_tool_name(self) -> str:
        return "fitlins"

    def get_tool_description(self) -> str:
        return (
            "FitLins (Fitting Linear Models to BIDS Datasets) for standardized "
            "GLM analyses. Automatically handles BIDS dataset structure, integrates "
            "with fMRIPrep outputs, and produces BIDS-derivative compliant results. "
            "Supports hierarchical models from run to group level with automatic "
            "contrast generation and multiple estimator backends."
        )

    def get_args_schema(self):
        return FitLinsArgs

    def _create_bids_model(
        self,
        bids_dir: str,
        hrf_model: str = "glover",
        drift_model: str = "cosine",
        contrasts: Optional[Dict] = None,
        include_confounds: Optional[List[str]] = None,
    ) -> Dict:
        """Create a valid BIDS Stats Model specification for native FitLins."""
        normalized_hrf_model = _normalize_fitlins_hrf_model(hrf_model)
        run_terms: List[Any] = [1, "trial_type.*"]
        if include_confounds:
            run_terms.extend(list(dict.fromkeys(include_confounds)))

        run_node: Dict[str, Any] = {
            "Level": "Run",
            "Name": "run_level",
            "GroupBy": ["run", "subject"],
            "Transformations": {
                "Transformer": "pybids-transforms-v1",
                "Instructions": [
                    {
                        "Name": "Factor",
                        "Input": ["trial_type"],
                    },
                    {
                        "Name": "Convolve",
                        "Model": "glover",
                        "Input": ["trial_type.*"],
                        "Derivative": False,
                        "Dispersion": False,
                    },
                ],
            },
            "Model": {
                "Type": "glm",
                "X": run_terms,
            },
            "Contrasts": [],
        }
        _apply_hrf_variant(run_node, 1, normalized_hrf_model)

        if drift_model == "cosine":
            run_node["Model"]["Options"] = {"HighPassFilterCutoff": 128}

        model_spec: Dict[str, Any] = {
            "Name": "AutoGeneratedModel",
            "Description": "Automatically generated BIDS Stats Model",
            "BIDSModelVersion": "1.0.0",
            "Input": {"task": ["all"]},
            "Nodes": [
                run_node,
                {
                    "Level": "Subject",
                    "Name": "subject_level",
                    "GroupBy": ["subject", "contrast"],
                    "Model": {"Type": "meta", "X": [1]},
                    "Contrasts": [],
                },
            ],
        }

        if contrasts:
            for name, weights in contrasts.items():
                contrast_spec = {
                    "Name": name,
                    "ConditionList": list(weights.keys()),
                    "Weights": list(weights.values()),
                    "Test": "t",
                }
                run_node["Contrasts"].append(contrast_spec)

        return model_spec

    def _get_confound_strategy(self, strategy: str, n_compcor: Optional[int] = None) -> List[str]:
        """Get confound regressors based on strategy."""

        strategies = {
            "motion": [
                "trans_x", "trans_y", "trans_z",
                "rot_x", "rot_y", "rot_z"
            ],
            "motion_derivatives": [
                "trans_x", "trans_y", "trans_z",
                "rot_x", "rot_y", "rot_z",
                "trans_x_derivative1", "trans_y_derivative1", "trans_z_derivative1",
                "rot_x_derivative1", "rot_y_derivative1", "rot_z_derivative1"
            ],
            "compcor": [
                "trans_x", "trans_y", "trans_z",
                "rot_x", "rot_y", "rot_z"
            ],
            "physio": [
                "trans_x", "trans_y", "trans_z",
                "rot_x", "rot_y", "rot_z",
                "cardiac_signal_z", "cardiac_signal_derivative1",
                "cardiac_retroicor_sin1", "cardiac_retroicor_cos1",
                "respiratory_signal_z", "respiratory_signal_derivative1",
                "respiratory_retroicor_sin1", "respiratory_retroicor_cos1",
                "cardiorespiratory_sum_sin1", "cardiorespiratory_sum_cos1",
                "cardiorespiratory_diff_sin1", "cardiorespiratory_diff_cos1",
            ],
            "pupil": [
                "trans_x", "trans_y", "trans_z",
                "rot_x", "rot_y", "rot_z",
                "pupil_filtered_z", "pupil_derivative1_z",
                "pupil_tonic_z", "pupil_phasic_z",
                "pupil_blink_fraction",
            ],
            "full": [
                "trans_x", "trans_y", "trans_z",
                "rot_x", "rot_y", "rot_z",
                "trans_x_derivative1", "trans_y_derivative1", "trans_z_derivative1",
                "rot_x_derivative1", "rot_y_derivative1", "rot_z_derivative1",
                "trans_x_power2", "trans_y_power2", "trans_z_power2",
                "rot_x_power2", "rot_y_power2", "rot_z_power2",
                "framewise_displacement",
                "csf", "white_matter", "global_signal",
                "cardiac_signal_z", "cardiac_signal_derivative1",
                "cardiac_retroicor_sin1", "cardiac_retroicor_cos1",
                "respiratory_signal_z", "respiratory_signal_derivative1",
                "respiratory_retroicor_sin1", "respiratory_retroicor_cos1",
                "cardiorespiratory_sum_sin1", "cardiorespiratory_sum_cos1",
                "cardiorespiratory_diff_sin1", "cardiorespiratory_diff_cos1",
                "pupil_filtered_z", "pupil_derivative1_z",
                "pupil_tonic_z", "pupil_phasic_z",
                "pupil_blink_fraction",
            ]
        }

        confounds = strategies.get(strategy, strategies["motion"])

        # Add CompCor components if requested
        if strategy == "compcor" and n_compcor:
            for i in range(n_compcor):
                confounds.append(f"a_comp_cor_{i:02d}")

        return confounds

    def _run_nilearn_fallback(
        self,
        bids_dir: str,
        derivatives_dir: str,
        output_dir: str,
        space: str = "MNI152NLin2009cAsym",
        smoothing: Optional[float] = None,
        participant_label: Optional[List[str]] = None,
        confounds_file: Optional[str] = None,
        **kwargs
    ) -> Dict:
        """Run GLM using Nilearn as fallback when FitLins is not available."""

        from nilearn.glm.first_level import FirstLevelModel
        from bids import BIDSLayout

        logger.info("Using Nilearn fallback for GLM analysis")

        # Initialize BIDS layout
        layout = BIDSLayout(bids_dir, derivatives=[derivatives_dir])

        # Get subjects
        if participant_label:
            subjects = participant_label
        else:
            subjects = layout.get_subjects()

        results = {}

        for subject in subjects:
            logger.info(f"Processing subject: {subject}")

            # Get functional files
            func_files = layout.get(
                subject=subject,
                extension='nii.gz',
                suffix='bold',
                space=space,
                return_type='file'
            )

            if not func_files:
                logger.warning(f"No functional files found for subject {subject}")
                continue

            # Get events
            event_files = layout.get(
                subject=subject,
                extension='tsv',
                suffix='events',
                return_type='file'
            )

            # Get confounds
            confound_files = layout.get(
                subject=subject,
                extension='tsv',
                suffix='regressors',
                return_type='file'
            )

            # Get TR
            tr = layout.get_tr(func_files[0])

            # Create first-level model
            model = FirstLevelModel(
                t_r=tr,
                smoothing_fwhm=smoothing,
                minimize_memory=True,
                mask_img=None,
                standardize="zscore_sample",
                signal_scaling=0,
                noise_model='ar1'
            )

            # Load events and confounds
            events = pd.read_csv(event_files[0], sep='\t') if event_files else None
            if confounds_file:
                confounds = pd.read_csv(confounds_file, sep='\t')
            else:
                confounds = pd.read_csv(confound_files[0], sep='\t') if confound_files else None

            # Fit model
            model.fit(func_files[0], events=events, confounds=confounds)

            # Compute contrasts
            subject_results = {}

            if events is not None:
                conditions = events['trial_type'].unique()

                for condition in conditions:
                    try:
                        z_map = model.compute_contrast(condition, output_type='z_score')

                        # Save contrast map
                        output_path = Path(output_dir) / f"sub-{subject}"
                        output_path.mkdir(parents=True, exist_ok=True)

                        contrast_file = output_path / f"sub-{subject}_contrast-{condition}_stat-z.nii.gz"
                        nib.save(z_map, contrast_file)

                        subject_results[condition] = str(contrast_file)
                    except Exception as e:
                        logger.warning(f"Could not compute contrast {condition}: {e}")

            results[subject] = subject_results

        return results

    def _run_fitlins(
        self,
        bids_dir: str,
        output_dir: str,
        derivatives_dir: Optional[str] = None,
        model: Optional[str] = None,
        analysis_level: str = "subject",
        **kwargs
    ):
        """Run FitLins analysis."""
        from fitlins.cli.run import run_fitlins
        import sys

        # Prepare command-line arguments
        args = [
            bids_dir,
            output_dir,
            analysis_level
        ]

        # Add optional arguments
        if derivatives_dir:
            args.extend(['--derivatives', derivatives_dir])

        if model:
            args.extend(['--model', model])

        if kwargs.get('smoothing'):
            args.extend(['--smoothing', str(kwargs['smoothing'])])

        if kwargs.get('participant_label'):
            for p in kwargs['participant_label']:
                args.extend(['--participant-label', p])

        if kwargs.get('space'):
            args.extend(['--space', kwargs['space']])

        if kwargs.get('include_confounds'):
            for c in kwargs['include_confounds']:
                args.extend(['--include', c])

        # Run FitLins
        logger.info(f"Running FitLins with args: {args}")

        # Capture sys.argv
        original_argv = sys.argv
        try:
            sys.argv = ['fitlins'] + args
            run_fitlins()
        finally:
            sys.argv = original_argv

    def _run(
        self,
        bids_dir: str,
        output_dir: str,
        derivatives_dir: Optional[str] = None,
        model: Optional[str] = None,
        analysis_level: str = "subject",
        hrf_model: str = "glover",
        drift_model: str = "cosine",
        drift_order: Optional[int] = None,
        smoothing: Optional[float] = None,
        slice_time_ref: Optional[float] = 0.5,
        space: str = "MNI152NLin2009cAsym",
        desc: Optional[str] = "preproc",
        participant_label: Optional[List[str]] = None,
        exclude_participant: Optional[List[str]] = None,
        include_confounds: List[str] = ["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z"],
        confound_strategy: str = "motion",
        confounds_file: Optional[str] = None,
        confounds_target_file: Optional[str] = None,
        confounds_map_file: Optional[str] = None,
        n_compcor: Optional[int] = None,
        contrasts: Optional[Dict[str, Any]] = None,
        auto_contrasts: bool = True,
        use_derivs: bool = True,
        estimator: str = "nilearn",
        error_ts: bool = False,
        reports_only: bool = False,
        write_graph: bool = False,
        work_dir: Optional[str] = None,
        ignore: Optional[List[str]] = None,
        force_index: Optional[List[str]] = None,
        model_minimize_memory: bool = True,
        **kwargs
    ) -> ToolResult:
        """Execute FitLins BIDS GLM analysis."""
        try:
            bids_path = Path(bids_dir)
            if not bids_path.exists():
                return ToolResult(
                    status="error",
                    error=f"BIDS directory not found: {bids_dir}",
                    data={},
                )

            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            if not derivatives_dir:
                potential_dirs = [
                    bids_path / "derivatives" / "fmriprep",
                    bids_path / "derivatives",
                    bids_path.parent / "derivatives" / "fmriprep",
                ]
                for pdir in potential_dirs:
                    if pdir.exists():
                        derivatives_dir = str(pdir)
                        logger.info(f"Auto-detected derivatives at: {derivatives_dir}")
                        break

            if confound_strategy != "custom":
                include_confounds = self._get_confound_strategy(
                    confound_strategy,
                    n_compcor,
                )

            if not model:
                model_spec = self._create_bids_model(
                    bids_dir=bids_dir,
                    hrf_model=hrf_model,
                    drift_model=drift_model,
                    contrasts=contrasts,
                    include_confounds=include_confounds,
                )
                model_file = output_path / "model.json"
                with open(model_file, "w") as f:
                    json.dump(model_spec, f, indent=2)
                model = str(model_file)
                logger.info(f"Created BIDS model at: {model}")

            outputs: Dict[str, Any]
            requested_hrf = str(hrf_model or "").strip().lower()
            native_fitlins_requested = self.fitlins_available and requested_hrf != "flobs"

            if native_fitlins_requested:
                payload: Dict[str, Any] = {
                    "bids_dir": bids_dir,
                    "output_dir": output_dir,
                    "derivatives_dir": derivatives_dir,
                    "model": model,
                    "analysis_level": analysis_level,
                    "participant_label": participant_label,
                    "exclude_participant": exclude_participant,
                    "work_dir": work_dir,
                    "space": space,
                    "desc": desc,
                    "smoothing": smoothing,
                    "hrf_model": hrf_model,
                    "drift_model": drift_model,
                    "drift_order": drift_order,
                    "include_confounds": include_confounds,
                    "confounds_file": confounds_file,
                    "confounds_target_file": confounds_target_file,
                    "confounds_map_file": confounds_map_file,
                    "n_compcor": n_compcor,
                    "estimator": estimator,
                    "reports_only": reports_only,
                    "ignore": ignore,
                    "force_index": force_index,
                }
                try:
                    result = run_fitlins_from_dict(payload, runtime="wrapper")
                    if result.get("exit_code", 1) != 0:
                        raise RuntimeError(result.get("stderr") or result.get("stdout") or "FitLins execution failed")

                    contrast_files = list(output_path.glob("**/*stat*.nii.gz"))
                    report_files = list(output_path.glob("**/*.html"))
                    effective_model = output_path / "_fitlins_native" / "effective_model.json"
                    native_derivatives = output_path / "_fitlins_native_derivatives"
                    outputs = {
                        "contrasts": [str(f) for f in contrast_files],
                        "reports": [str(f) for f in report_files],
                        "model": str(effective_model if effective_model.exists() else Path(model)),
                        "native_derivatives_dir": str(native_derivatives) if native_derivatives.exists() else None,
                    }
                except Exception as exc:
                    logger.error(f"FitLins execution failed: {exc}")
                    if confounds_map_file:
                        raise RuntimeError(
                            "confounds_map_file is only supported through native FitLins execution"
                        ) from exc
                    if self.nilearn_available and derivatives_dir:
                        logger.info("Falling back to Nilearn GLM")
                        outputs = self._run_nilearn_fallback(
                            bids_dir=bids_dir,
                            derivatives_dir=derivatives_dir,
                            output_dir=output_dir,
                            space=space,
                            smoothing=smoothing,
                            participant_label=participant_label,
                            confounds_file=confounds_file,
                        )
                    else:
                        raise
            elif self.fitlins_available and requested_hrf == "flobs":
                if confounds_map_file:
                    return ToolResult(
                        status="error",
                        error="confounds_map_file is only supported through native FitLins execution, not the Nilearn FLOBS fallback",
                        data={},
                    )
                if self.nilearn_available and derivatives_dir:
                    logger.info("FLOBS requested; using Nilearn path because native FitLins does not support FLOBS")
                    outputs = self._run_nilearn_fallback(
                        bids_dir=bids_dir,
                        derivatives_dir=derivatives_dir,
                        output_dir=output_dir,
                        space=space,
                        smoothing=smoothing,
                        participant_label=participant_label,
                        confounds_file=confounds_file,
                    )
                else:
                    return ToolResult(
                        status="error",
                        error="FLOBS is only supported through the Nilearn path in this repository",
                        data={},
                    )
            elif self.nilearn_available and derivatives_dir:
                if confounds_map_file:
                    return ToolResult(
                        status="error",
                        error="confounds_map_file is only supported through native FitLins execution",
                        data={},
                    )
                logger.info("FitLins not available, using Nilearn")
                outputs = self._run_nilearn_fallback(
                    bids_dir=bids_dir,
                    derivatives_dir=derivatives_dir,
                    output_dir=output_dir,
                    space=space,
                    smoothing=smoothing,
                    participant_label=participant_label,
                    confounds_file=confounds_file,
                )
            else:
                return ToolResult(
                    status="error",
                    error="Neither FitLins nor Nilearn available for GLM analysis",
                    data={},
                )

            report = {
                "bids_dir": bids_dir,
                "derivatives_dir": derivatives_dir,
                "output_dir": output_dir,
                "analysis_level": analysis_level,
                "space": space,
                "smoothing": smoothing,
                "model": model if model else "auto-generated",
                "confounds": include_confounds,
                "confounds_file": confounds_file,
                "confounds_target_file": confounds_target_file,
                "confounds_map_file": confounds_map_file,
                "participants": participant_label if participant_label else "all",
                "outputs": outputs,
            }

            n_contrasts = (
                len(outputs.get("contrasts", []))
                if isinstance(outputs, dict)
                else sum(len(v) for v in outputs.values() if isinstance(v, dict))
            )

            report_file = output_path / "fitlins_report.json"
            with open(report_file, "w") as f:
                json.dump(report, f, indent=2, default=str)

            return ToolResult(
                status="success",
                data={
                    "outputs": outputs,
                    "report": str(report_file),
                    "n_contrasts": n_contrasts,
                    "analysis_level": analysis_level,
                    "message": f"BIDS GLM analysis completed: {n_contrasts} contrasts generated",
                },
            )

        except Exception as e:
            logger.error(f"FitLins analysis failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={},
            )

    def create_bids_model(
        self,
        output_file: str,
        name: str = "CustomModel",
        description: str = "Custom BIDS Stats Model",
        nodes: List[Dict] = None,
        **kwargs
    ) -> ToolResult:
        """Create a custom BIDS Stats Model specification."""
        try:
            model = {
                "Name": name,
                "Description": description,
                "BIDSModelVersion": "1.0.0",
                "Input": {
                    "task": kwargs.get("task", "all")
                },
                "Nodes": nodes or []
            }

            # Add default nodes if not provided
            if not nodes:
                model["Nodes"] = [
                    {
                        "Level": "Run",
                        "Name": "run_level",
                        "GroupBy": ["run", "subject"],
                        "Transformations": {
                            "Transformer": "pybids-transforms",
                            "Instructions": [
                                {
                                    "Name": "Convolve",
                                    "Input": ["trial_type"],
                                    "Model": "spm"
                                }
                            ]
                        },
                        "Model": {
                            "Type": "glm",
                            "X": ["trial_type.condition*"],
                            "Formula": "1 + trial_type"
                        },
                        "Contrasts": [
                            {
                                "Name": "task_vs_baseline",
                                "ConditionList": ["trial_type.condition*"],
                                "Weights": [1],
                                "Test": "t"
                            }
                        ]
                    },
                    {
                        "Level": "Subject",
                        "Name": "subject_level",
                        "GroupBy": ["subject", "contrast"],
                        "Model": {
                            "Type": "meta",
                            "X": [1]
                        },
                        "Contrasts": [
                            {
                                "Name": "group_mean",
                                "ConditionList": ["intercept"],
                                "Weights": [1],
                                "Test": "t"
                            }
                        ]
                    }
                ]

            # Save model
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, 'w') as f:
                json.dump(model, f, indent=2)

            return ToolResult(
                status="success",
                data={
                    "model_file": str(output_path),
                    "model": model,
                    "message": f"Created BIDS Stats Model: {name}"
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )


class FitLinsTools:
    """Collection of FitLins tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all FitLins tools."""
        return [
            FitLinsTool(),
            FitLinsCreateSeedSpecTool(),
            FitLinsGenerateMultiverseSpecsTool(),
            FitLinsRunMultiverseTool(),
            FitLinsMultiverseSummaryTool(),
        ]


# ---------------------------------------------------------------------------
# Multiverse helpers (lightweight, rule-based placeholders for pipeline wiring)
# ---------------------------------------------------------------------------


class CreateSeedSpecArgs(BaseModel):
    study_id: str
    task: str
    bids_root: Optional[str] = None
    derivatives_root: Optional[str] = None
    seed_spec: Optional[str] = Field(
        default=None,
        description="Optional existing seed spec path. If provided and exists, it is returned as-is.",
    )
    allow_stub: bool = Field(
        default=False,
        description="If True, create a minimal stub spec when no seed spec is found.",
    )


class FitLinsCreateSeedSpecTool(NeuroToolWrapper):
    """Locate or stub a seed BIDS Stats Model for a study/task."""

    def get_tool_name(self) -> str:
        return "fitlins.create_seed_spec"

    def get_tool_description(self) -> str:
        return "Locate an existing seed BIDS Stats Model (openneuro_glmfitlins layout) or create a minimal stub."

    def get_args_schema(self):
        return CreateSeedSpecArgs

    def _run(
        self,
        study_id: str,
        task: str,
        bids_root: Optional[str] = None,
        derivatives_root: Optional[str] = None,
        seed_spec: Optional[str] = None,
        allow_stub: bool = False,
    ) -> ToolResult:
        repo_root = Path(__file__).resolve().parents[4]
        candidates: List[Path] = []

        if seed_spec:
            candidates.append(Path(seed_spec))

        # Common locations used in openneuro_glmfitlins
        candidates.append(
            repo_root
            / "data"
            / "openneuro_glmfitlins"
            / "statsmodel_specs"
            / study_id
            / f"{study_id}-{task}_specs.json"
        )
        candidates.append(
            repo_root
            / "external"
            / "openneuro_glmfitlins"
            / "statsmodel_specs"
            / study_id
            / f"{study_id}-{task}_specs.json"
        )
        candidates.append(
            repo_root
            / "outputs"
            / "fitlins_multiverse"
            / study_id
            / f"{study_id}-{task}_seed_stub.json"
        )

        for path in candidates:
            if path.exists():
                return ToolResult(
                    status="success",
                    data={"outputs": {"seed_spec": str(path), "source": "found"}},
                )

        if not allow_stub:
            # Try to auto-generate via openneuro_glmfitlins script if available
            script = repo_root / "external" / "openneuro_glmfitlins" / "scripts" / "3_create_spec_file.sh"
            if script.exists():
                cmd = [str(script), study_id, task]
                try:
                    subprocess.run(cmd, check=True, capture_output=True)
                    # Re-scan candidates after generation
                    for path in candidates:
                        if path.exists():
                            return ToolResult(
                                status="success",
                                data={"outputs": {"seed_spec": str(path), "source": "generated"}},
                            )
                except subprocess.CalledProcessError as exc:
                    return ToolResult(
                        status="error",
                        error=f"Seed spec generation failed: {exc.stderr.decode() if exc.stderr else exc}",
                        data={"searched": [str(p) for p in candidates], "command": cmd},
                    )

            return ToolResult(
                status="error",
                error="Seed spec not found. Provide seed_spec or set allow_stub=True to auto-stub.",
                data={"searched": [str(p) for p in candidates]},
            )

        # Minimal stub spec (valid BIDS Stats Model skeleton)
        stub_dir = repo_root / "outputs" / "fitlins_multiverse" / study_id
        stub_dir.mkdir(parents=True, exist_ok=True)
        stub_path = stub_dir / f"{study_id}-{task}_seed_stub.json"
        stub_model = {
            "Name": f"{study_id}-{task}-seed-stub",
            "BIDSModelVersion": "1.0.0",
            "Input": {"task": task},
            "Steps": [
                {
                    "Level": "run",
                    "Model": {"Type": "glm", "X": ["trial_type"], "Options": {}},
                    "Contrasts": [],
                }
            ],
        }
        stub_path.write_text(json.dumps(stub_model, indent=2))
        return ToolResult(
            status="success",
            data={"outputs": {"seed_spec": str(stub_path), "source": "stub"}},
        )


class MultiverseSpecsArgs(BaseModel):
    study_id: str
    task: str
    seed_spec: str
    output_dir: Optional[str] = None
    max_models: int = Field(default=5, ge=1)
    include_seed: bool = Field(
        default=False, description="Include an mv00 copy of the seed in outputs"
    )
    seed: int = Field(default=0, description="Random seed for multiverse variant generation")
    priors: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional priors dict (e.g., from BR-KG) to prioritize axis values",
    )
    use_priors: bool = Field(default=True, description="If false, ignore priors even when provided")
    include_references: bool = Field(
        default=True, description="If true, attach literature/dataset references to each variant"
    )
    parcellations: Optional[List[str]] = Field(
        default=None,
        description="Optional parcellation names (e.g., ['Yeo2011-7']) to include atlas citations in manifest",
    )
    axis_overrides: Optional[Dict[str, List[Any]]] = Field(
        default=None,
        description=(
            "Optional explicit axis levels to override variant generation, "
            "e.g. {'hrf_basis': ['canonical','derivs','glover','fir']}."
        ),
    )


class FitLinsGenerateMultiverseSpecsTool(NeuroToolWrapper):
    """Create mvXX spec files by cloning the seed spec (placeholder logic)."""

    def get_tool_name(self) -> str:
        return "fitlins.generate_multiverse_specs"

    def get_tool_description(self) -> str:
        return "Generate multiverse BIDS Stats Model variants (mvXX). Current implementation clones the seed spec as placeholders."

    def get_args_schema(self):
        return MultiverseSpecsArgs

    def _run(
        self,
        study_id: str,
        task: str,
        seed_spec: str,
        output_dir: Optional[str] = None,
        max_models: int = 5,
        include_seed: bool = False,
        seed: int = 0,
        priors: Optional[Dict[str, Any]] = None,
        use_priors: bool = True,
        include_references: bool = True,
        parcellations: Optional[List[str]] = None,
        axis_overrides: Optional[Dict[str, List[Any]]] = None,
    ) -> ToolResult:
        seed_path = Path(seed_spec)
        if not seed_path.exists():
            return ToolResult(status="error", error=f"Seed spec not found: {seed_spec}")

        try:
            seed_model = json.loads(seed_path.read_text())
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(status="error", error=f"Failed to read seed spec: {exc}")

        out_dir = Path(output_dir) if output_dir else seed_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        run_node = _find_run_node(seed_model)
        if run_node is None:
            return ToolResult(status="error", error="Seed spec missing run-level node (Level=Run)")

        convolve_idx = _find_convolve_idx(run_node)
        if convolve_idx is None:
            # If missing, add a default Convolve with canonical HRF
            tx = run_node.setdefault("Transformations", {"Transformer": "pybids-transforms-v1", "Instructions": []})
            instructions = tx.setdefault("Instructions", [])
            instructions.append({"Name": "Convolve", "Model": "spm", "Derivative": False, "Dispersion": False, "Input": ["trial_type.*"]})
            convolve_idx = len(instructions) - 1

        # Generate variants via rule_engine (branch-aware + priors weighting)
        variants: List[Dict[str, Any]] = generate_variants(
            priors or {},
            max_models,
            use_priors=use_priors,
            seed=seed,
            axis_overrides=axis_overrides,
        )

        manifests: List[Dict[str, Any]] = []
        spec_paths: List[str] = []

        if include_seed:
            mv00 = out_dir / f"{study_id}-{task}-mv00_specs.json"
            mv00.write_text(json.dumps(seed_model, indent=2))
            spec_paths.append(str(mv00))
            seed_contrast = None
            seed_contrasts = _extract_contrast_names(seed_model)
            if seed_contrasts:
                seed_contrast = seed_contrasts[0]
            manifests.append(
                {
                    "model_id": "mv00",
                    "path": str(mv00),
                    "hrf": "seed",
                    "confounds": "seed",
                    "confounds_families": "seed",
                    "high_pass": "seed",
                    "contrast": seed_contrast,
                    "fitlins_params": _extract_fitlins_params(seed_model),
                }
            )

        for idx, variant in enumerate(variants, start=1):
            model = json.loads(json.dumps(seed_model))  # deep copy via json round-trip
            rnode = _find_run_node(model)
            cidx = _find_convolve_idx(rnode)
            _apply_hrf_variant(rnode, cidx, variant["hrf"])
            _apply_confounds_variant(
                rnode,
                variant["confounds"],
                variant.get("confounds_families"),
            )
            _apply_highpass_variant(rnode, variant["high_pass"])

            model_id = f"mv{idx:02d}"
            model["Name"] = model.get("Name", f"{study_id}-{task}") + f"-{model_id}"
            model.setdefault("Metadata", {})["multiverse_variant"] = variant

            ok, msg = _validate_model(model)
            if not ok:
                manifests.append(
                    {
                        "model_id": model_id,
                        "path": None,
                        **variant,
                        "error": msg,
                    }
                )
                continue

            mv_path = out_dir / f"{study_id}-{task}-{model_id}_specs.json"
            mv_path.write_text(json.dumps(model, indent=2))
            spec_paths.append(str(mv_path))
            references: List[Dict[str, Any]] = []
            literature_evidence: Dict[str, Any] = {}
            contrast_name = None
            contrasts = _extract_contrast_names(model)
            if contrasts:
                contrast_name = contrasts[0]
            if include_references:
                try:
                    lit = GLMLiteratureTool()._run(
                        dataset_id=study_id,
                        task=task,
                        contrast=contrast_name,
                        decision_points={
                            "hrf": variant["hrf"],
                            "confounds": variant["confounds"],
                            "confounds_families": variant.get("confounds_families"),
                            "high_pass": variant["high_pass"],
                        },
                        parcellations=parcellations or ["Yeo2011-7"],
                        use_br_kg=True,
                        include_static=True,
                        use_neo4j=True,
                        use_file_search=True,
                    )
                    references = lit.data.get("outputs", {}).get("references", [])
                    literature_evidence = lit.data.get("outputs", {}).get("evidence", {})
                except Exception:
                    references = gather_references(
                        study_id,
                        task,
                        {
                            "hrf": variant["hrf"],
                            "confounds": variant["confounds"],
                            "confounds_families": variant.get("confounds_families"),
                            "high_pass": variant["high_pass"],
                        },
                        datasets_folder=Path(__file__).resolve().parents[4] / "dataset" if Path(__file__).resolve().parents[4].exists() else None,
                    )
            manifests.append(
                {
                    "model_id": model_id,
                    "path": str(mv_path),
                    **variant,
                    "contrast": contrast_name,
                    "fitlins_params": _extract_fitlins_params(model),
                    "rationale": variant.get("rationale"),
                    "priors_used": variant.get("priors_used"),
                    "selection_reason": variant.get("selection_reason"),
                    "references": references,
                    "literature_evidence": literature_evidence,
                }
            )

        manifest_path = out_dir / "multiverse_manifest.json"
        manifest_payload = {
            "dataset_id": study_id,
            "task": task,
            "variants": manifests,
        }
        manifest_path.write_text(json.dumps(manifest_payload, indent=2))

        # Minimal evidence panel report (top literature hits)
        report_payload = {
            "dataset_id": study_id,
            "task": task,
            "evidence_panel": _build_evidence_panel(manifests, top_k=5),
        }
        report_path = out_dir / "multiverse_report.json"
        report_path.write_text(json.dumps(report_payload, indent=2))

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "multiverse_specs": spec_paths,
                    "manifest": manifests,
                    "manifest_json": str(manifest_path),
                    "report_json": str(report_path),
                }
            },
        )


class RunMultiverseArgs(BaseModel):
    study_id: str
    task: str
    bids_root: str
    derivatives_root: Optional[str] = None
    multiverse_specs: List[str]
    analysis_level: str = Field(default="dataset")
    participant_label: Optional[List[str]] = Field(
        default=None,
        description="Optional participant labels (without 'sub-') to restrict execution",
    )
    exclude_participant: Optional[List[str]] = Field(
        default=None,
        description="Optional participant labels to exclude from execution",
    )
    execute: bool = Field(
        default=False,
        description="If true, actually run FitLins; otherwise return planned commands (safe default).",
    )
    output_root: Optional[str] = None
    runtime: str = Field(
        default="apptainer",
        description="Runtime backend for FitLins (prefer apptainer or docker; wrapper is a development fallback).",
    )
    correction_method: Optional[str] = Field(
        default=None, description="Threshold/correction method label to carry through results"
    )


class FitLinsRunMultiverseTool(NeuroToolWrapper):
    """Run or plan FitLins for each mvXX spec."""

    def get_tool_name(self) -> str:
        return "fitlins.run_multiverse"

    def get_tool_description(self) -> str:
        return "Run FitLins for multiple mvXX specs, or return the planned commands when execute=False."

    def get_args_schema(self):
        return RunMultiverseArgs

    def _run(
        self,
        study_id: str,
        task: str,
        bids_root: str,
        multiverse_specs: List[str],
        derivatives_root: Optional[str] = None,
        analysis_level: str = "dataset",
        participant_label: Optional[List[str]] = None,
        exclude_participant: Optional[List[str]] = None,
        execute: bool = False,
        output_root: Optional[str] = None,
        runtime: str = "apptainer",
        correction_method: Optional[str] = None,
    ) -> ToolResult:
        repo_root = Path(__file__).resolve().parents[4]
        out_root = Path(output_root) if output_root else repo_root / "outputs" / "fitlins_multiverse" / study_id / task
        out_root.mkdir(parents=True, exist_ok=True)

        plans: List[Dict[str, Any]] = []
        results: List[Dict[str, Any]] = []

        for spec_path in multiverse_specs:
            spec_name = Path(spec_path).stem.replace("_specs", "")
            model_out = out_root / spec_name
            model_out.mkdir(parents=True, exist_ok=True)
            payload = {
                "bids_dir": bids_root,
                "derivatives_dir": derivatives_root,
                "output_dir": str(model_out),
                "analysis_level": analysis_level,
                "model": spec_path,
                # keep work dir colocated to avoid polluting other runs
                "work_dir": str(out_root / "work"),
            }
            if participant_label:
                payload["participant_label"] = participant_label
            if exclude_participant:
                payload["exclude_participant"] = exclude_participant

            params = fitlins_from_payload(payload)
            cmd = params.command(include_executable=True)
            plans.append({"spec": spec_path, "output": str(model_out), "cmd": cmd, "correction_method": correction_method})

            if execute:
                result = run_fitlins_from_dict(payload, runtime=runtime)
                results.append({"spec": spec_path, "correction_method": correction_method, **result})

        status = "success" if not execute or all(r.get("exit_code", 1) == 0 for r in results) else "error"
        # Check correction consistency
        corr_labels = {p.get("correction_method") for p in plans if p.get("correction_method")}
        correction_mixed = len(corr_labels) > 1

        outputs: Dict[str, Any] = {
            "plans": plans,
            "multiverse_results": results,
            "correction_labels": list(corr_labels),
            "correction_mixed": correction_mixed,
        }
        if results:
            outputs["results"] = results

        return ToolResult(status=status, data={"outputs": outputs})


class MultiverseSummaryArgs(BaseModel):
    study_id: str
    task: str
    multiverse_specs: List[str]
    multiverse_results: Optional[List[Dict[str, Any]]] = None
    output_manifest: Optional[str] = None


class FitLinsMultiverseSummaryTool(NeuroToolWrapper):
    """Summarize multiverse specs and (optionally) run results into a manifest CSV."""

    def get_tool_name(self) -> str:
        return "fitlins.multiverse_summary"

    def get_tool_description(self) -> str:
        return "Create a manifest of mvXX specs and (if available) execution outcomes for quick inspection."

    def get_args_schema(self):
        return MultiverseSummaryArgs

    def _run(
        self,
        study_id: str,
        task: str,
        multiverse_specs: List[str],
        multiverse_results: Optional[List[Dict[str, Any]]] = None,
        output_manifest: Optional[str] = None,
    ) -> ToolResult:
        repo_root = Path(__file__).resolve().parents[4]
        manifest_path = (
            Path(output_manifest)
            if output_manifest
            else repo_root / "outputs" / "fitlins_multiverse" / study_id / task / "multiverse_manifest.csv"
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        rows: List[Dict[str, Any]] = []
        for spec in multiverse_specs:
            model_id = Path(spec).stem.replace("_specs", "")
            rows.append({"model_id": model_id, "spec": spec})

        if multiverse_results:
            results_map = {Path(r.get("spec", "")).stem.replace("_specs", ""): r for r in multiverse_results}
            for row in rows:
                rid = row["model_id"]
                res = results_map.get(rid, {})
                row.update({
                    "exit_code": res.get("exit_code"),
                    "command_host": res.get("command_host"),
                    "stdout": res.get("stdout"),
                    "stderr": res.get("stderr"),
                })

        df = pd.DataFrame(rows)
        df.to_csv(manifest_path, index=False)

        return ToolResult(
            status="success",
            data={"outputs": {"manifest": str(manifest_path), "rows": rows}},
        )


# ---------------------------------------------------------------------------
# Multiverse Convergence Tool
# ---------------------------------------------------------------------------


class MultiverseConvergenceArgs(BaseModel):
    """Arguments for fitlins.multiverse_convergence tool."""

    manifest_path: str = Field(
        ...,
        description="Path to multiverse_manifest.csv with model_id and output_dir columns",
    )
    output_dir: str = Field(
        ...,
        description="Directory to write convergence analysis outputs",
    )
    threshold: float = Field(
        default=3.1,
        description="Z-score threshold for significance (default 3.1 ~ p<0.001 uncorrected)",
    )
    atlas: str = Field(
        default="schaefer-200",
        description="Atlas for ROI extraction (schaefer-200, aal, harvard-oxford, destrieux)",
    )
    contrast: Optional[str] = Field(
        default=None,
        description="Specific contrast to analyze. If None, uses first available.",
    )


class FitLinsMultiverseConvergenceTool(NeuroToolWrapper):
    """Compute convergence/overlap analysis across multiverse GLM results.

    This tool reads a multiverse manifest and group-level Z-maps from each model,
    then computes:
    1. Voxel-wise "fraction of models significant" overlap map
    2. ROI-wise mean effect sizes per model

    These outputs support paper figures demonstrating result robustness across
    analytical choices (HRF basis, confound strategy, high-pass filter).
    """

    def get_tool_name(self) -> str:
        return "fitlins.multiverse_convergence"

    def get_tool_description(self) -> str:
        return (
            "Compute convergence/overlap analysis across multiverse GLM results. "
            "Produces voxel-wise overlap maps (fraction of models significant) and "
            "ROI-wise effect summary tables for paper figures."
        )

    def get_args_schema(self):
        return MultiverseConvergenceArgs

    def _run(
        self,
        manifest_path: str,
        output_dir: str,
        threshold: float = 3.1,
        atlas: str = "schaefer-200",
        contrast: Optional[str] = None,
    ) -> ToolResult:
        """Run multiverse convergence analysis."""
        try:
            from brain_researcher.core.analysis.multiverse_convergence import (
                compute_multiverse_convergence,
            )
        except ImportError as e:
            return ToolResult(
                status="error",
                data={"error": f"Missing dependencies for convergence analysis: {e}"},
            )

        try:
            result = compute_multiverse_convergence(
                manifest_path=manifest_path,
                output_dir=output_dir,
                threshold=threshold,
                atlas=atlas,
                contrast=contrast,
            )
            return ToolResult(
                status="success",
                data={"outputs": result},
            )
        except Exception as e:
            logger.exception("Multiverse convergence analysis failed")
            return ToolResult(
                status="error",
                data={"error": str(e)},
            )
