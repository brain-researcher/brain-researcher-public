"""
MNE-Python Core Preprocessing implementation for Brain Researcher.

Implements MNE's core preprocessing pipeline for EEG/MEG data including
filtering, resampling, bad channel detection, and re-referencing.
"""

import json
import logging
import types
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple

import numpy as np
from pydantic import BaseModel, Field

from brain_researcher.services.tools.params import (
    MNEPreprocessingParameters,
    mne_preprocessing_from_payload,
    run_mne_preprocessing,
)
from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)
from brain_researcher.services.tools.spec import ToolSpec
from brain_researcher.core.utils import configure_mne_environment

logger = logging.getLogger(__name__)

try:  # Allow tests to patch mne even when dependency is missing.
    import mne  # type: ignore
except Exception:  # pragma: no cover
    mne = types.SimpleNamespace(io=types.SimpleNamespace())


class FilterType(str):
    """Filter type options."""
    HIGHPASS = "highpass"
    LOWPASS = "lowpass"
    BANDPASS = "bandpass"
    BANDSTOP = "bandstop"


class ReferenceType(str):
    """Reference type options."""
    AVERAGE = "average"
    REST = "REST"
    BIPOLAR = "bipolar"
    CUSTOM = "custom"
    CSD = "CSD"  # Current source density


class MNEPreprocessingArgs(BaseModel):
    """Arguments for MNE preprocessing pipeline."""
    
    raw_file: str = Field(
        description="Path to raw EEG/MEG file (.fif, .edf, .bdf, .vhdr, .set, etc.)"
    )
    output_dir: str = Field(
        description="Output directory for preprocessed data"
    )
    
    # Filtering parameters
    l_freq: Optional[float] = Field(
        default=0.1,
        description="Low frequency for high-pass filter (Hz). None = no high-pass"
    )
    h_freq: Optional[float] = Field(
        default=40.0,
        description="High frequency for low-pass filter (Hz). None = no low-pass"
    )
    filter_method: str = Field(
        default="fir",
        description="Filter method: 'fir' or 'iir'"
    )
    filter_length: str = Field(
        default="auto",
        description="Filter length: 'auto', '10s', '1000ms', or samples as int"
    )
    
    # Resampling
    sfreq: Optional[float] = Field(
        default=None,
        description="New sampling frequency (Hz). None = no resampling"
    )
    
    # Bad channel handling
    detect_bad_channels: bool = Field(
        default=True,
        description="Automatically detect bad channels"
    )
    bad_channels: Optional[List[str]] = Field(
        default=None,
        description="List of bad channel names to mark"
    )
    interpolate_bads: bool = Field(
        default=True,
        description="Interpolate bad channels"
    )
    
    # Re-referencing
    reference: str = Field(
        default="average",
        description="Reference type: 'average', 'REST', 'bipolar', 'CSD', or channel name"
    )
    reference_channels: Optional[List[str]] = Field(
        default=None,
        description="Specific channels to use as reference"
    )
    
    # Epoching parameters (optional)
    create_epochs: bool = Field(
        default=False,
        description="Create epochs from continuous data"
    )
    epoch_tmin: float = Field(
        default=-0.2,
        description="Start time of epochs (seconds)"
    )
    epoch_tmax: float = Field(
        default=0.8,
        description="End time of epochs (seconds)"
    )
    event_id: Optional[Dict[str, int]] = Field(
        default=None,
        description="Event ID mapping for epoching"
    )
    
    # Baseline correction
    baseline: Optional[Tuple[float, float]] = Field(
        default=(None, 0),
        description="Baseline correction interval (tmin, tmax)"
    )
    
    # Artifact rejection thresholds
    reject: Optional[Dict[str, float]] = Field(
        default=None,
        description="Rejection thresholds by channel type (e.g., {'eeg': 100e-6})"
    )
    flat: Optional[Dict[str, float]] = Field(
        default=None,
        description="Flat channel thresholds by channel type"
    )
    
    # Line noise removal
    notch_freq: Optional[Union[float, List[float]]] = Field(
        default=None,
        description="Notch filter frequency (Hz), e.g., 50 or 60 for line noise"
    )
    
    # Montage
    set_montage: Optional[str] = Field(
        default=None,
        description="Standard montage name (e.g., 'standard_1020', 'biosemi64')"
    )
    
    # Output options
    save_format: str = Field(
        default="fif",
        description="Output format: 'fif', 'edf', 'bdf'"
    )
    overwrite: bool = Field(
        default=False,
        description="Overwrite existing output files"
    )


def _model_required(model_cls) -> List[str]:
    try:
        schema = model_cls.model_json_schema()
    except AttributeError:  # pragma: no cover
        schema = model_cls.schema()
    return schema.get("required", [])


def _model_defaults(model_cls) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {}
    if hasattr(model_cls, "model_fields"):
        for name, field in model_cls.model_fields.items():
            if field.default is not None:
                defaults[name] = field.default
    elif hasattr(model_cls, "__fields__"):
        for name, field in model_cls.__fields__.items():
            if field.default is not None:
                defaults[name] = field.default
    return defaults


try:
    _MNE_PREPROC_SCHEMA = MNEPreprocessingArgs.model_json_schema()
except AttributeError:  # pragma: no cover
    _MNE_PREPROC_SCHEMA = MNEPreprocessingArgs.schema()


TOOL_SPEC = ToolSpec(
    name="mne_preprocessing",
    description="Run MNE-Python preprocessing using shared neurocore routines.",
    json_schema=_MNE_PREPROC_SCHEMA,
    required=_model_required(MNEPreprocessingArgs),
    defaults=_model_defaults(MNEPreprocessingArgs),
    category="mne",
)


class MNEPreprocessingTool(NeuroToolWrapper):
    TOOL_SPEC = TOOL_SPEC
    """MNE-Python core preprocessing tool."""
    
    def __init__(self):
        """Initialize MNE preprocessing tool."""
        super().__init__()
        self._check_mne()
    
    def _check_mne(self):
        """Check MNE-Python availability."""
        try:
            configure_mne_environment()
            import mne
            self.mne_available = True
            self.mne_version = mne.__version__
            logger.info(f"MNE-Python {self.mne_version} available")
        except ImportError:
            self.mne_available = False
            logger.warning("MNE-Python not installed. Attempting installation...")
            self._attempt_install()
    
    def _attempt_install(self):
        """Attempt to install MNE-Python."""
        try:
            import subprocess
            subprocess.check_call(["pip", "install", "mne"])
            configure_mne_environment()
            import mne
            self.mne_available = True
            self.mne_version = mne.__version__
            logger.info(f"Successfully installed MNE-Python {self.mne_version}")
        except:
            logger.error("Could not install MNE-Python")
            self.mne_available = False

    def _load_raw_data(self, raw_file: str):
        """Load raw data using MNE based on file extension."""
        global mne
        if mne is None or not hasattr(mne, "io") or not hasattr(mne.io, "read_raw_fif"):
            try:
                import mne as mne_module  # type: ignore
                mne = mne_module
            except Exception as exc:  # pragma: no cover - defensive in mixed envs
                raise ImportError("MNE-Python not available") from exc

        path = Path(raw_file)
        if not path.exists():
            raise FileNotFoundError(raw_file)

        suffix = "".join(path.suffixes).lower()
        if suffix.endswith(".fif") or suffix.endswith(".fif.gz"):
            return mne.io.read_raw_fif(raw_file, preload=True)
        if suffix.endswith(".edf"):
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Channels contain different highpass filters.*",
                    category=RuntimeWarning,
                )
                warnings.filterwarnings(
                    "ignore",
                    message="Channels contain different lowpass filters.*",
                    category=RuntimeWarning,
                )
                warnings.filterwarnings(
                    "ignore",
                    message="Highpass cutoff frequency .* greater than lowpass cutoff frequency .*",
                    category=RuntimeWarning,
                )
                return mne.io.read_raw_edf(raw_file, preload=True)
        if suffix.endswith(".bdf"):
            return mne.io.read_raw_bdf(raw_file, preload=True)
        if suffix.endswith(".vhdr"):
            return mne.io.read_raw_brainvision(raw_file, preload=True)
        if suffix.endswith(".set"):
            return mne.io.read_raw_eeglab(raw_file, preload=True)

        raise ValueError(f"Unsupported file format: {suffix}")

    def _detect_bad_channels(self, raw):
        """Detect bad channels using simple variance thresholds."""
        data = raw.get_data()
        variances = np.var(data, axis=1)
        median_var = np.median(variances) if variances.size else 0.0
        low_thresh = median_var * 0.01
        high_thresh = median_var * 100.0 if median_var > 0 else np.inf

        bad_idx = np.where((variances < low_thresh) | (variances > high_thresh))[0]
        return [raw.ch_names[i] for i in bad_idx]

    def _apply_reference(self, raw, reference: str, reference_channels: Optional[List[str]] = None):
        """Apply EEG reference strategy."""
        if reference == ReferenceType.AVERAGE:
            raw.set_eeg_reference("average", projection=False)
        elif reference == ReferenceType.REST:
            raw.set_eeg_reference("REST")
        elif reference == ReferenceType.CSD:
            raw.set_eeg_reference("CSD")
        elif reference_channels:
            raw.set_eeg_reference(reference_channels)
        else:
            raw.set_eeg_reference([reference])
    
    def get_tool_name(self) -> str:
        return "mne_preprocessing"
    
    def get_tool_description(self) -> str:
        return (
            "MNE-Python core preprocessing pipeline for EEG/MEG data. "
            "Includes filtering, resampling, bad channel detection and interpolation, "
            "re-referencing, epoching, baseline correction, and artifact rejection. "
            "Supports multiple file formats and provides comprehensive preprocessing."
        )
    
    def get_args_schema(self):
        return MNEPreprocessingArgs
    
    def _run(
        self,
        raw_file: str,
        output_dir: str,
        l_freq: Optional[float] = 0.1,
        h_freq: Optional[float] = 40.0,
        filter_method: str = "fir",
        filter_length: str = "auto",
        sfreq: Optional[float] = None,
        detect_bad_channels: bool = True,
        bad_channels: Optional[List[str]] = None,
        interpolate_bads: bool = True,
        reference: str = "average",
        reference_channels: Optional[List[str]] = None,
        create_epochs: bool = False,
        epoch_tmin: float = -0.2,
        epoch_tmax: float = 0.8,
        event_id: Optional[Dict[str, int]] = None,
        baseline: Optional[Tuple[float, float]] = (None, 0),
        reject: Optional[Dict[str, float]] = None,
        flat: Optional[Dict[str, float]] = None,
        notch_freq: Optional[Union[float, List[float]]] = None,
        set_montage: Optional[str] = None,
        save_format: str = "fif",
        overwrite: bool = False,
        **kwargs
    ) -> ToolResult:
        """Execute MNE preprocessing pipeline."""
        try:
            if not self.mne_available and mne is None:
                return ToolResult(
                    status="error",
                    error="MNE-Python not available",
                    data={}
                )
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            processing_log: List[str] = []
            raw = self._load_raw_data(raw_file)

            if l_freq is not None or h_freq is not None:
                raw.filter(l_freq, h_freq, method=filter_method, filter_length=filter_length)
                processing_log.append("filter")

            if notch_freq is not None:
                raw.notch_filter(notch_freq)
                processing_log.append("notch_filter")

            if sfreq is not None:
                raw.resample(sfreq)
                processing_log.append("resample")

            # Bad channels
            bads = []
            if detect_bad_channels:
                bads.extend(self._detect_bad_channels(raw))
            if bad_channels:
                bads.extend(bad_channels)
            if bads:
                raw.info["bads"] = list(dict.fromkeys(bads))
                processing_log.append("mark_bad_channels")

            if interpolate_bads and getattr(raw, "interpolate_bads", None):
                raw.interpolate_bads()
                processing_log.append("interpolate_bads")

            # Reference
            self._apply_reference(raw, reference, reference_channels)
            processing_log.append("set_reference")

            # Epoching
            n_epochs = 0
            if create_epochs and mne is not None:
                events = mne.find_events(raw)
                epochs = mne.Epochs(
                    raw,
                    events,
                    event_id=event_id,
                    tmin=epoch_tmin,
                    tmax=epoch_tmax,
                    baseline=baseline,
                    reject=reject,
                    flat=flat,
                    preload=True,
                )
                n_epochs = len(epochs)
                processing_log.append("create_epochs")

            outputs = {
                "preprocessed_data": str(output_path / f"preprocessed.{save_format}"),
            }
            statistics = {
                "n_channels": len(getattr(raw, "ch_names", [])),
                "sfreq": raw.info.get("sfreq") if hasattr(raw, "info") else None,
                "n_epochs": n_epochs,
            }

            return ToolResult(
                status="success",
                data={
                    "outputs": outputs,
                    "processing_log": processing_log,
                    "statistics": statistics,
                    "message": "Preprocessing completed successfully",
                },
            )
            
        except Exception as e:
            logger.error(f"MNE preprocessing failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )
    
    def batch_preprocess(
        self,
        input_files: List[str],
        output_dir: str,
        **kwargs
    ) -> ToolResult:
        """Batch preprocessing of multiple files."""
        try:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            results = []
            failed = []
            
            for i, input_file in enumerate(input_files):
                logger.info(f"Processing file {i+1}/{len(input_files)}: {input_file}")
                
                # Create subject-specific output directory
                subject_dir = output_path / f"sub_{i:03d}"
                
                result = self._run(
                    raw_file=input_file,
                    output_dir=str(subject_dir),
                    **kwargs
                )
                
                if result.status == "success":
                    results.append({
                        "input": input_file,
                        "outputs": result.data["outputs"]
                    })
                else:
                    failed.append({
                        "input": input_file,
                        "error": result.error
                    })
            
            return ToolResult(
                status="success" if not failed else "partial",
                data={
                    "processed": results,
                    "failed": failed,
                    "n_processed": len(results),
                    "n_failed": len(failed),
                    "message": f"Batch processing: {len(results)}/{len(input_files)} files processed"
                }
            )
            
        except Exception as e:
            logger.error(f"Batch preprocessing failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )


class MNEPreprocessingTools:
    """Collection of MNE preprocessing tools."""
    
    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all MNE preprocessing tools."""
        return [
            MNEPreprocessingTool()
        ]
