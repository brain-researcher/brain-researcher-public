"""
Parameter Inference System for Brain Researcher Agent.

AGENT-005: Automatically infers parameters from BIDS metadata, context,
and previous analysis results to reduce manual parameter specification.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import nibabel as nib
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BIDSEntity:
    """Represents a BIDS entity extracted from filename or metadata."""

    subject: Optional[str] = None
    session: Optional[str] = None
    task: Optional[str] = None
    run: Optional[int] = None
    acquisition: Optional[str] = None
    space: Optional[str] = None
    resolution: Optional[str] = None
    description: Optional[str] = None
    suffix: Optional[str] = None  # bold, T1w, etc.
    extension: Optional[str] = None  # .nii.gz, .json, etc.

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class ImageMetadata:
    """Metadata extracted from neuroimaging files."""

    shape: Tuple[int, ...] = field(default_factory=tuple)
    voxel_size: Tuple[float, ...] = field(default_factory=tuple)
    tr: Optional[float] = None
    te: Optional[float] = None
    flip_angle: Optional[float] = None
    slice_timing: Optional[List[float]] = None
    phase_encoding_direction: Optional[str] = None
    total_readout_time: Optional[float] = None
    n_volumes: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for parameter mapping."""
        data = {}
        if self.shape:
            data["dimensions"] = self.shape
        if self.voxel_size:
            data["voxel_size"] = self.voxel_size
        if self.tr is not None:
            data["repetition_time"] = self.tr
        if self.te is not None:
            data["echo_time"] = self.te
        if self.n_volumes:
            data["n_timepoints"] = self.n_volumes
        if self.phase_encoding_direction:
            data["phase_encoding"] = self.phase_encoding_direction
        return data


@dataclass
class InferredParameters:
    """Container for inferred parameters with confidence scores."""

    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: Dict[str, float] = field(default_factory=dict)
    sources: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def add_parameter(
        self,
        name: str,
        value: Any,
        confidence: float = 1.0,
        source: str = "unknown",
    ):
        """Add an inferred parameter with metadata."""
        self.parameters[name] = value
        self.confidence[name] = confidence
        self.sources[name] = source

    def merge(self, other: "InferredParameters", override: bool = False):
        """Merge another InferredParameters object."""
        for name, value in other.parameters.items():
            if name not in self.parameters or override:
                self.parameters[name] = value
                self.confidence[name] = other.confidence.get(name, 0.5)
                self.sources[name] = other.sources.get(name, "merged")

        self.warnings.extend(other.warnings)


class BIDSParser:
    """Parses BIDS datasets and extracts metadata."""

    # BIDS entity patterns
    ENTITY_PATTERNS = {
        "subject": r"sub-([a-zA-Z0-9]+)",
        "session": r"ses-([a-zA-Z0-9]+)",
        "task": r"task-([a-zA-Z0-9]+)",
        "run": r"run-(\d+)",
        "acquisition": r"acq-([a-zA-Z0-9]+)",
        "space": r"space-([a-zA-Z0-9]+)",
        "resolution": r"res-([a-zA-Z0-9]+)",
        "description": r"desc-([a-zA-Z0-9]+)",
    }

    # Common BIDS suffixes
    SUFFIXES = {
        "anat": ["T1w", "T2w", "FLAIR", "T1rho", "T1map", "T2map"],
        "func": ["bold", "sbref", "events", "physio", "stim"],
        "dwi": ["dwi", "bvec", "bval"],
        "fmap": [
            "phasediff",
            "phase1",
            "phase2",
            "magnitude",
            "magnitude1",
            "magnitude2",
            "epi",
        ],
        "perf": ["asl", "m0scan"],
    }

    def parse_filename(self, filename: str) -> BIDSEntity:
        """Parse BIDS entities from filename."""
        entity = BIDSEntity()

        # Parse entities
        for entity_name, pattern in self.ENTITY_PATTERNS.items():
            match = re.search(pattern, filename)
            if match:
                value = match.group(1)
                if entity_name == "run":
                    value = int(value)
                setattr(entity, entity_name, value)

        # Parse suffix and extension
        path = Path(filename)

        # Handle compressed extensions
        if path.suffix == ".gz" and len(path.suffixes) > 1:
            entity.extension = "".join(path.suffixes[-2:])
            stem = path.stem.replace(path.suffixes[-2], "")
        else:
            entity.extension = path.suffix
            stem = path.stem

        # Extract suffix (last part after final underscore)
        parts = stem.split("_")
        if parts:
            potential_suffix = parts[-1]
            for category, suffixes in self.SUFFIXES.items():
                if potential_suffix in suffixes:
                    entity.suffix = potential_suffix
                    break

        return entity

    def read_json_sidecar(self, json_path: Union[str, Path]) -> Dict[str, Any]:
        """Read BIDS JSON sidecar file."""
        try:
            with open(json_path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to read JSON sidecar {json_path}: {e}")
            return {}

    def extract_image_metadata(self, nifti_path: Union[str, Path]) -> ImageMetadata:
        """Extract metadata from NIfTI file."""
        metadata = ImageMetadata()

        try:
            img = nib.load(nifti_path)

            # Basic shape and voxel size
            metadata.shape = img.shape
            metadata.voxel_size = tuple(img.header.get_zooms())

            # Number of volumes for 4D data
            if len(img.shape) == 4:
                metadata.n_volumes = img.shape[3]

            # Try to get TR from header (if available)
            if hasattr(img.header, "get_xyzt_units"):
                units = img.header.get_xyzt_units()
                if len(metadata.voxel_size) > 3:
                    # Fourth element is TR in the units specified
                    tr_raw = metadata.voxel_size[3]
                    if units[1] == "sec":
                        metadata.tr = tr_raw
                    elif units[1] == "msec":
                        metadata.tr = tr_raw / 1000.0

        except Exception as e:
            logger.warning(f"Failed to extract metadata from {nifti_path}: {e}")

        return metadata

    def find_associated_files(
        self,
        base_path: Union[str, Path],
        entity: BIDSEntity,
    ) -> Dict[str, Path]:
        """Find associated BIDS files (sidecars, events, etc.)."""
        base_path = Path(base_path)
        parent_dir = base_path.parent

        associated = {}

        # Look for JSON sidecar
        json_path = base_path.with_suffix(".json")
        if json_path.exists():
            associated["sidecar"] = json_path

        # Look for events file (for func data)
        if entity.suffix == "bold":
            events_pattern = base_path.stem.replace("_bold", "_events.tsv")
            events_path = parent_dir / events_pattern
            if events_path.exists():
                associated["events"] = events_path

        # Look for physio data
        if entity.suffix in ["bold", "perf"]:
            physio_pattern = base_path.stem.replace(
                f"_{entity.suffix}", "_physio.tsv.gz"
            )
            physio_path = parent_dir / physio_pattern
            if physio_path.exists():
                associated["physio"] = physio_path

        return associated


class ContextAnalyzer:
    """Analyzes context to infer parameters."""

    def __init__(self):
        """Initialize context analyzer."""
        self.context_patterns = self._load_context_patterns()

    def _load_context_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Load patterns for context-based inference."""
        return {
            # Task-based patterns
            "motor_task": {
                "keywords": ["motor", "finger", "tapping", "movement"],
                "inferred_params": {
                    "contrast_type": "task>rest",
                    "smoothing_kernel": 6.0,
                    "high_pass_filter": 128,
                },
            },
            "visual_task": {
                "keywords": ["visual", "checkerboard", "faces", "objects"],
                "inferred_params": {
                    "contrast_type": "stimulus>baseline",
                    "smoothing_kernel": 8.0,
                    "roi_focus": ["V1", "V2", "fusiform"],
                },
            },
            "language_task": {
                "keywords": ["language", "words", "semantic", "phonological"],
                "inferred_params": {
                    "contrast_type": "language>control",
                    "smoothing_kernel": 8.0,
                    "roi_focus": ["Broca", "Wernicke", "IFG"],
                },
            },
            "rest_state": {
                "keywords": ["rest", "resting", "rs-fMRI", "rsfMRI"],
                "inferred_params": {
                    "analysis_type": "connectivity",
                    "smoothing_kernel": 6.0,
                    "bandpass_filter": [0.01, 0.1],
                    "motion_correction": "aggressive",
                },
            },
            # Analysis type patterns
            "group_analysis": {
                "keywords": [
                    "group-level",
                    "group analysis",
                    "across all subjects",
                    "population",
                    "cohort",
                ],
                "inferred_params": {
                    "analysis_level": "group",
                    "normalization_space": "MNI152",
                    "cluster_threshold": 3.1,
                },
            },
            "single_subject": {
                "keywords": ["single subject", "individual", "participant"],
                "inferred_params": {
                    "analysis_level": "subject",
                    "normalization_space": "native",
                },
            },
            # Quality patterns
            "high_resolution": {
                "keywords": ["high-res", "highres", "7T", "submillimeter"],
                "inferred_params": {
                    "smoothing_kernel": 3.0,  # Less smoothing for high-res
                    "interpolation": "sinc",
                },
            },
        }

    def analyze_query(self, query: str) -> InferredParameters:
        """Analyze user query to infer parameters."""
        inferred = InferredParameters()
        query_lower = query.lower()

        for pattern_name, pattern_data in self.context_patterns.items():
            # Check if any keywords match
            if any(keyword in query_lower for keyword in pattern_data["keywords"]):
                for param_name, param_value in pattern_data["inferred_params"].items():
                    inferred.add_parameter(
                        param_name,
                        param_value,
                        confidence=0.8,
                        source=f"context:{pattern_name}",
                    )

        return inferred

    def analyze_previous_results(
        self,
        previous_results: List[Dict[str, Any]],
    ) -> InferredParameters:
        """Analyze previous results to infer parameters."""
        inferred = InferredParameters()

        if not previous_results:
            return inferred

        # Extract common parameters from previous runs
        param_counts: Dict[str, Dict[Any, int]] = {}

        for result in previous_results:
            if "parameters" in result:
                for param_name, param_value in result["parameters"].items():
                    if param_name not in param_counts:
                        param_counts[param_name] = {}

                    # Convert unhashable types to strings
                    if isinstance(param_value, (list, dict)):
                        param_value = json.dumps(param_value, sort_keys=True)

                    param_counts[param_name][param_value] = (
                        param_counts[param_name].get(param_value, 0) + 1
                    )

        # Use most common values as defaults
        for param_name, value_counts in param_counts.items():
            if value_counts:
                most_common_value = max(value_counts, key=value_counts.get)
                frequency = value_counts[most_common_value] / len(previous_results)

                # Only use if sufficiently common
                if frequency > 0.5:
                    # Convert back from string if needed
                    try:
                        if isinstance(
                            most_common_value, str
                        ) and most_common_value.startswith(("[", "{")):
                            most_common_value = json.loads(most_common_value)
                    except:
                        pass

                    inferred.add_parameter(
                        param_name,
                        most_common_value,
                        confidence=min(0.9, frequency),
                        source="previous_results",
                    )

        return inferred


class ParameterInferenceEngine:
    """Main engine for parameter inference."""

    def __init__(self):
        """Initialize the inference engine."""
        self.bids_parser = BIDSParser()
        self.context_analyzer = ContextAnalyzer()
        self.parameter_mappings = self._load_parameter_mappings()
        self.cache: Dict[str, InferredParameters] = {}

    def _load_parameter_mappings(self) -> Dict[str, Dict[str, str]]:
        """Load mappings from BIDS/context to tool parameters."""
        return {
            # BIDS to FSL mappings
            "fsl": {
                "repetition_time": "tr",
                "echo_time": "te",
                "n_timepoints": "npts",
                "smoothing_kernel": "smooth",
                "high_pass_filter": "paradigm_hp",
                "slice_timing": "st",
                "phase_encoding": "echospacing",
            },
            # BIDS to SPM mappings
            "spm": {
                "repetition_time": "TR",
                "echo_time": "TE",
                "n_timepoints": "nscans",
                "smoothing_kernel": "fwhm",
                "slice_timing": "slice_order",
            },
            # BIDS to AFNI mappings
            "afni": {
                "repetition_time": "tr",
                "n_timepoints": "nt",
                "smoothing_kernel": "blur",
            },
            # BIDS to Nilearn mappings
            "nilearn": {
                "repetition_time": "t_r",
                "smoothing_kernel": "smoothing_fwhm",
                "high_pass_filter": "high_pass",
                "low_pass_filter": "low_pass",
            },
        }

    def infer_from_bids(
        self,
        file_path: Union[str, Path],
        tool_name: Optional[str] = None,
    ) -> InferredParameters:
        """Infer parameters from BIDS file and metadata."""
        file_path = Path(file_path)
        inferred = InferredParameters()

        # Parse BIDS entities from filename
        entity = self.bids_parser.parse_filename(str(file_path))

        # Add basic BIDS entities as parameters
        for key, value in entity.to_dict().items():
            if value is not None:
                inferred.add_parameter(
                    key,
                    value,
                    confidence=1.0,
                    source="bids:filename",
                )

        # Find and read JSON sidecar
        associated = self.bids_parser.find_associated_files(file_path, entity)

        if "sidecar" in associated:
            sidecar_data = self.bids_parser.read_json_sidecar(associated["sidecar"])

            # Common BIDS JSON fields
            if "RepetitionTime" in sidecar_data:
                inferred.add_parameter(
                    "repetition_time",
                    sidecar_data["RepetitionTime"],
                    confidence=1.0,
                    source="bids:sidecar",
                )

            if "EchoTime" in sidecar_data:
                inferred.add_parameter(
                    "echo_time",
                    sidecar_data["EchoTime"],
                    confidence=1.0,
                    source="bids:sidecar",
                )

            if "SliceTiming" in sidecar_data:
                inferred.add_parameter(
                    "slice_timing",
                    sidecar_data["SliceTiming"],
                    confidence=1.0,
                    source="bids:sidecar",
                )

            if "PhaseEncodingDirection" in sidecar_data:
                inferred.add_parameter(
                    "phase_encoding_direction",
                    sidecar_data["PhaseEncodingDirection"],
                    confidence=1.0,
                    source="bids:sidecar",
                )

            if "TotalReadoutTime" in sidecar_data:
                inferred.add_parameter(
                    "total_readout_time",
                    sidecar_data["TotalReadoutTime"],
                    confidence=1.0,
                    source="bids:sidecar",
                )

        # Extract metadata from image file
        if file_path.suffix in [".nii", ".gz"]:
            img_metadata = self.bids_parser.extract_image_metadata(file_path)

            for key, value in img_metadata.to_dict().items():
                if value is not None:
                    inferred.add_parameter(
                        key,
                        value,
                        confidence=0.9,
                        source="bids:image",
                    )

        # Add events file if found
        if "events" in associated:
            inferred.add_parameter(
                "events_file",
                str(associated["events"]),
                confidence=1.0,
                source="bids:associated",
            )

        # Map to tool-specific parameters if tool specified
        if tool_name and tool_name.lower() in self.parameter_mappings:
            mapped_params = InferredParameters()
            mappings = self.parameter_mappings[tool_name.lower()]

            for generic_name, tool_param in mappings.items():
                if generic_name in inferred.parameters:
                    mapped_params.add_parameter(
                        tool_param,
                        inferred.parameters[generic_name],
                        confidence=inferred.confidence[generic_name],
                        source=f"mapped:{inferred.sources[generic_name]}",
                    )

            # Keep both generic and mapped parameters
            inferred.merge(mapped_params)

        return inferred

    def infer_from_context(
        self,
        query: str,
        file_paths: Optional[List[str]] = None,
        previous_results: Optional[List[Dict[str, Any]]] = None,
        tool_name: Optional[str] = None,
    ) -> InferredParameters:
        """Infer parameters from query context and history."""
        # Check cache
        cache_key = f"{query}:{tool_name}:{str(file_paths)}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        inferred = InferredParameters()

        # Analyze query
        query_params = self.context_analyzer.analyze_query(query)
        inferred.merge(query_params)

        # Analyze previous results
        if previous_results:
            history_params = self.context_analyzer.analyze_previous_results(
                previous_results
            )
            inferred.merge(history_params)

        # Infer from BIDS files if provided
        if file_paths:
            for file_path in file_paths:
                if Path(file_path).exists():
                    bids_params = self.infer_from_bids(file_path, tool_name)
                    inferred.merge(bids_params, override=False)

        # Add default parameters based on common patterns
        self._add_intelligent_defaults(inferred, query, tool_name)

        # Cache the result
        self.cache[cache_key] = inferred

        return inferred

    def _add_intelligent_defaults(
        self,
        inferred: InferredParameters,
        query: str,
        tool_name: Optional[str] = None,
    ):
        """Add intelligent default parameters based on context."""
        query_lower = query.lower()

        # GLM-specific defaults
        if tool_name == "glm_analysis" or "glm" in query_lower:
            if "smoothing_kernel" not in inferred.parameters:
                inferred.add_parameter(
                    "smoothing_kernel",
                    6.0,
                    confidence=0.6,
                    source="default:glm",
                )

            if "high_pass_filter" not in inferred.parameters:
                inferred.add_parameter(
                    "high_pass_filter",
                    128,
                    confidence=0.6,
                    source="default:glm",
                )

        # Connectivity-specific defaults
        if "connectivity" in query_lower or "correlation" in query_lower:
            if "correlation_method" not in inferred.parameters:
                inferred.add_parameter(
                    "correlation_method",
                    "pearson",
                    confidence=0.7,
                    source="default:connectivity",
                )

            if "bandpass_filter" not in inferred.parameters:
                inferred.add_parameter(
                    "bandpass_filter",
                    [0.01, 0.1],
                    confidence=0.6,
                    source="default:connectivity",
                )

        # Registration defaults
        if "registration" in query_lower or "normalize" in query_lower:
            if "template" not in inferred.parameters:
                inferred.add_parameter(
                    "template",
                    "MNI152_2mm",
                    confidence=0.7,
                    source="default:registration",
                )

            if "cost_function" not in inferred.parameters:
                inferred.add_parameter(
                    "cost_function",
                    "corratio",
                    confidence=0.6,
                    source="default:registration",
                )

        # Group analysis defaults
        if "group" in query_lower and "analysis_level" not in inferred.parameters:
            inferred.add_parameter(
                "analysis_level",
                "group",
                confidence=0.8,
                source="default:context",
            )

            if "mixed_effects" not in inferred.parameters:
                inferred.add_parameter(
                    "mixed_effects",
                    "flame1",
                    confidence=0.6,
                    source="default:group",
                )

    def validate_and_complete(
        self,
        parameters: Dict[str, Any],
        required_params: List[str],
        tool_name: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Validate parameters and complete missing required ones."""
        completed = parameters.copy()
        missing = []

        for param in required_params:
            if param not in completed:
                # Try to infer from existing parameters
                if param == "n_timepoints" and "dimensions" in completed:
                    dims = completed["dimensions"]
                    if len(dims) == 4:
                        completed["n_timepoints"] = dims[3]
                        continue

                if param == "tr" and "repetition_time" in completed:
                    completed["tr"] = completed["repetition_time"]
                    continue

                # Mark as missing if can't infer
                missing.append(param)

        return completed, missing

    def get_confidence_summary(self, inferred: InferredParameters) -> str:
        """Generate a summary of inference confidence."""
        if not inferred.confidence:
            return "No parameters inferred"

        avg_confidence = sum(inferred.confidence.values()) / len(inferred.confidence)

        high_conf = [k for k, v in inferred.confidence.items() if v >= 0.8]
        medium_conf = [k for k, v in inferred.confidence.items() if 0.5 <= v < 0.8]
        low_conf = [k for k, v in inferred.confidence.items() if v < 0.5]

        summary = f"Average confidence: {avg_confidence:.2f}\n"

        if high_conf:
            summary += f"High confidence: {', '.join(high_conf)}\n"
        if medium_conf:
            summary += f"Medium confidence: {', '.join(medium_conf)}\n"
        if low_conf:
            summary += f"Low confidence: {', '.join(low_conf)}\n"

        return summary
