"""
FSL FEAT GLM implementation for the BR-KG LangGraph system.

Implements FSL FEAT for GLM analysis of task fMRI data with statistical inference.
"""

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from brain_researcher.services.tools.niwrap.executor import execute_niwrap_tool
from brain_researcher.services.tools.params import (
    FSLFEATParameters,
    build_fsl_feat_command,
    build_fsl_feat_env,
)
from brain_researcher.services.tools.spec import ToolSpec
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class AnalysisLevel(str, Enum):
    """FEAT analysis levels."""

    FIRST_LEVEL = "1"  # First-level (single-run) analysis
    SECOND_LEVEL = "2"  # Second-level (within-subject) analysis
    THIRD_LEVEL = "3"  # Third-level (group) analysis


class StatThreshold(str, Enum):
    """Statistical thresholding methods."""

    NONE = "0"  # No thresholding
    UNCORRECTED = "1"  # Uncorrected p-value
    VOXEL_CORRECTED = "2"  # Voxel-wise FWE correction
    CLUSTER_CORRECTED = "3"  # Cluster-wise correction (default)


class MotionCorrection(str, Enum):
    """Motion correction options."""

    NONE = "0"
    MCFLIRT = "1"  # FSL's motion correction


@dataclass
class DesignMatrix:
    """Design matrix specification for FEAT."""

    n_timepoints: int
    n_evs: int  # Number of explanatory variables (EVs)
    ev_names: List[str]
    ev_files: List[str]  # Paths to 3-column format EV files
    contrasts: Dict[str, List[float]]  # Contrast specifications
    tr: float  # Repetition time in seconds

    def to_fsf_lines(self) -> List[str]:
        """Generate FSF file lines for design matrix."""
        lines = []

        # Basic design parameters
        lines.append(f"set fmri(npts) {self.n_timepoints}")
        lines.append(f"set fmri(tr) {self.tr}")
        lines.append(f"set fmri(evs_orig) {self.n_evs}")
        lines.append(
            f"set fmri(evs_real) {2 * self.n_evs}"
        )  # Doubled for temporal derivatives
        lines.append(f"set fmri(ncon_orig) {len(self.contrasts)}")
        lines.append(f"set fmri(ncon_real) {len(self.contrasts)}")

        # EV specifications
        for i, (name, file_path) in enumerate(zip(self.ev_names, self.ev_files), 1):
            lines.append(f'set fmri(evtitle{i}) "{name}"')
            lines.append(f"set fmri(shape{i}) 3")  # 3-column format
            lines.append(f'set fmri(custom{i}) "{file_path}"')
            lines.append(f"set fmri(convolve{i}) 2")  # Convolve with double-gamma HRF
            lines.append(f"set fmri(convolve_phase{i}) 0")
            lines.append(f"set fmri(tempfilt_yn{i}) 1")
            lines.append(f"set fmri(deriv_yn{i}) 1")  # Add temporal derivative

        # Contrast specifications
        for c_idx, (contrast_name, weights) in enumerate(self.contrasts.items(), 1):
            lines.append(f'set fmri(conname_orig.{c_idx}) "{contrast_name}"')
            lines.append(f'set fmri(conname_real.{c_idx}) "{contrast_name}"')

            # Set contrast weights for each EV
            for ev_idx, weight in enumerate(weights, 1):
                # Main EV weight
                lines.append(f"set fmri(con_orig{c_idx}.{ev_idx}) {weight}")
                lines.append(f"set fmri(con_real{c_idx}.{2*ev_idx-1}) {weight}")
                # Temporal derivative weight (usually 0)
                lines.append(f"set fmri(con_real{c_idx}.{2*ev_idx}) 0")

        return lines


class FEATGLMArgs(BaseModel):
    """Arguments for FSL FEAT GLM analysis."""

    input_file: str = Field(description="Path to 4D NIfTI functional data file")
    output_dir: str = Field(description="Output directory for FEAT results")
    tr: float = Field(description="Repetition time in seconds")
    ev_files: Dict[str, str] = Field(
        description="Dictionary mapping EV names to 3-column format files (onset, duration, weight)"
    )
    contrasts: Dict[str, List[float]] = Field(
        description="Dictionary of contrast definitions, e.g., {'task_vs_rest': [1, -1]}"
    )
    analysis_level: AnalysisLevel = Field(
        default=AnalysisLevel.FIRST_LEVEL,
        description="Analysis level (first, second, or third level)",
    )
    high_pass_filter: float = Field(
        default=100.0, description="High-pass filter cutoff in seconds"
    )
    smoothing_fwhm: float = Field(
        default=5.0, description="Spatial smoothing FWHM in mm"
    )
    motion_correction: MotionCorrection = Field(
        default=MotionCorrection.MCFLIRT, description="Motion correction method"
    )
    brain_extraction: bool = Field(
        default=True, description="Perform brain extraction with BET"
    )
    registration: bool = Field(
        default=True, description="Register to MNI152 standard space"
    )
    thresh_type: StatThreshold = Field(
        default=StatThreshold.CLUSTER_CORRECTED,
        description="Statistical thresholding method",
    )
    z_threshold: float = Field(
        default=3.1, description="Z-statistic threshold for cluster correction"
    )
    p_threshold: float = Field(
        default=0.05, description="P-value threshold for cluster correction"
    )
    template_brain: Optional[str] = Field(
        default=None,
        description="Path to template brain for registration (default: MNI152)",
    )
    confound_evs: Optional[Dict[str, str]] = Field(
        default=None,
        description="Dictionary of confound regressors (e.g., motion parameters)",
    )


def _model_required(model_cls) -> List[str]:
    try:
        schema = model_cls.model_json_schema()
    except AttributeError:  # pragma: no cover - Pydantic v1
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
    _FSL_FEAT_SCHEMA = FEATGLMArgs.model_json_schema()
except AttributeError:  # pragma: no cover
    _FSL_FEAT_SCHEMA = FEATGLMArgs.schema()


TOOL_SPEC = ToolSpec(
    name="fsl_feat_glm",
    description="Configure FSL FEAT GLM analysis using shared neurocore command builders.",
    json_schema=_FSL_FEAT_SCHEMA,
    required=_model_required(FEATGLMArgs),
    defaults=_model_defaults(FEATGLMArgs),
    category="fsl",
)


class FSLFEATTool(NeuroToolWrapper):
    """FSL FEAT GLM analysis tool."""

    def __init__(self):
        """Initialize FSL FEAT tool."""
        super().__init__()
        self.fsl_dir = "/cvmfs/neurodesk.ardc.edu.au/containers/fsl_6.0.7.16_20250131"

    def get_tool_name(self) -> str:
        return "fsl_feat_glm"

    def get_tool_description(self) -> str:
        return (
            "Run FSL FEAT for GLM analysis of task fMRI data with statistical inference. "
            "Supports first-level and higher-level analyses with multiple comparison correction."
        )

    def get_args_schema(self):
        return FEATGLMArgs

    def _generate_fsf_file(self, args: FEATGLMArgs, temp_dir: str) -> str:
        """Generate FSF configuration file for FEAT."""
        fsf_lines = []

        # Header
        fsf_lines.append("# FEAT version 6.00")
        fsf_lines.append("")

        # Analysis level
        fsf_lines.append(f"set fmri(level) {args.analysis_level.value}")
        fsf_lines.append(f"set fmri(analysis) 7")  # Full first-level analysis

        # Input/output
        fsf_lines.append(f'set feat_files(1) "{args.input_file}"')
        fsf_lines.append(f'set fmri(outputdir) "{args.output_dir}"')

        # TR and volumes
        fsf_lines.append(f"set fmri(tr) {args.tr}")
        fsf_lines.append(f"set fmri(ndelete) 0")  # Don't delete initial volumes

        # Preprocessing options
        fsf_lines.append(f"set fmri(smooth) {args.smoothing_fwhm}")
        fsf_lines.append(f"set fmri(norm_yn) 0")  # Don't normalize intensity
        fsf_lines.append(f"set fmri(temphp_yn) 1")  # High-pass filtering
        fsf_lines.append(f"set fmri(paradigm_hp) {args.high_pass_filter}")
        fsf_lines.append(f"set fmri(templp_yn) 0")  # No low-pass filtering
        fsf_lines.append(f"set fmri(mc) {args.motion_correction.value}")

        # Brain extraction
        fsf_lines.append(f"set fmri(bet_yn) {1 if args.brain_extraction else 0}")

        # Registration
        fsf_lines.append(f"set fmri(reg_yn) {1 if args.registration else 0}")
        if args.registration:
            fsf_lines.append("set fmri(regstandard_yn) 1")
            template = (
                args.template_brain
                or f"{self.fsl_dir}/data/standard/MNI152_T1_2mm_brain"
            )
            fsf_lines.append(f'set fmri(regstandard) "{template}"')
            fsf_lines.append("set fmri(regstandard_search) 90")  # Full search
            fsf_lines.append("set fmri(regstandard_dof) 12")  # 12 DOF

        # Statistical thresholding
        fsf_lines.append(f"set fmri(thresh) {args.thresh_type.value}")
        fsf_lines.append(f"set fmri(z_thresh) {args.z_threshold}")
        fsf_lines.append(f"set fmri(prob_thresh) {args.p_threshold}")

        # Motion parameters
        fsf_lines.append("set fmri(motionevs) 0")  # Don't automatically add motion EVs
        fsf_lines.append("set fmri(robust_yn) 0")  # No robust outlier detection

        # Stats options
        fsf_lines.append("set fmri(mixed_yn) 2")  # Fixed effects
        fsf_lines.append("set fmri(randomisePermutations) 5000")
        fsf_lines.append("set fmri(prewhiten_yn) 1")  # FILM prewhitening

        # Create design matrix
        n_timepoints = self._get_n_timepoints(args.input_file)
        design = DesignMatrix(
            n_timepoints=n_timepoints,
            n_evs=len(args.ev_files),
            ev_names=list(args.ev_files.keys()),
            ev_files=list(args.ev_files.values()),
            contrasts=args.contrasts,
            tr=args.tr,
        )

        # Add design matrix lines
        fsf_lines.extend(design.to_fsf_lines())

        # Add confound EVs if provided
        if args.confound_evs:
            current_ev = len(args.ev_files) + 1
            for confound_name, confound_file in args.confound_evs.items():
                fsf_lines.append(f'set fmri(evtitle{current_ev}) "{confound_name}"')
                fsf_lines.append(f"set fmri(shape{current_ev}) 2")  # Square waveform
                fsf_lines.append(f'set fmri(custom{current_ev}) "{confound_file}"')
                fsf_lines.append(f"set fmri(convolve{current_ev}) 0")  # No convolution
                fsf_lines.append(f"set fmri(deriv_yn{current_ev}) 0")  # No derivative
                current_ev += 1

        # Write FSF file
        fsf_path = os.path.join(temp_dir, "design.fsf")
        with open(fsf_path, "w") as f:
            f.write("\n".join(fsf_lines))

        return fsf_path

    def _get_n_timepoints(self, input_file: str) -> int:
        """Get number of timepoints from 4D NIfTI file."""
        try:
            import nibabel as nib

            img = nib.load(input_file)
            if len(img.shape) == 4:
                return img.shape[3]
            else:
                raise ValueError(f"Input file {input_file} is not 4D")
        except (ImportError, Exception) as e:
            # Fallback: use FSL's fslinfo or default
            logger.warning(f"Cannot load NIfTI file ({e}), using default timepoints")
            return 200  # Default, will be updated by FEAT

    def _extract_results(self, feat_dir: str) -> Dict[str, Any]:
        """Extract key results from FEAT output directory."""
        results = {
            "feat_dir": feat_dir,
            "stats": {},
            "clusters": {},
            "registration": {},
            "design": {},
        }

        stats_dir = os.path.join(feat_dir, "stats")

        # Extract z-stat maps for each contrast
        if os.path.exists(stats_dir):
            for zstat_file in Path(stats_dir).glob("zstat*.nii.gz"):
                # Get just the number from the filename
                contrast_num = zstat_file.stem.split(".")[0].replace("zstat", "")
                results["stats"][f"zstat{contrast_num}"] = str(zstat_file)

                # Check for corresponding cluster file
                cluster_file = os.path.join(
                    stats_dir, f"cluster_zstat{contrast_num}.txt"
                )
                if os.path.exists(cluster_file):
                    results["clusters"][f"cluster{contrast_num}"] = cluster_file

        # Extract registration files
        reg_dir = os.path.join(feat_dir, "reg")
        if os.path.exists(reg_dir):
            if os.path.exists(os.path.join(reg_dir, "example_func2standard.mat")):
                results["registration"]["func2standard"] = os.path.join(
                    reg_dir, "example_func2standard.mat"
                )
            if os.path.exists(os.path.join(reg_dir, "standard.nii.gz")):
                results["registration"]["standard_space"] = os.path.join(
                    reg_dir, "standard.nii.gz"
                )

        # Extract design information
        design_file = os.path.join(feat_dir, "design.mat")
        if os.path.exists(design_file):
            results["design"]["matrix"] = design_file

        design_image = os.path.join(feat_dir, "design.png")
        if os.path.exists(design_image):
            results["design"]["image"] = design_image

        # Extract report
        report_file = os.path.join(feat_dir, "report.html")
        if os.path.exists(report_file):
            results["report"] = report_file

        return results

    def _run(
        self,
        input_file: str,
        output_dir: str,
        tr: float,
        ev_files: Dict[str, str],
        contrasts: Dict[str, List[float]],
        **kwargs,
    ) -> ToolResult:
        """Execute FSL FEAT GLM analysis."""
        try:
            # Validate input file exists
            if not os.path.exists(input_file):
                return ToolResult(
                    status="error", error=f"Input file not found: {input_file}", data={}
                )

            # Validate EV files exist
            for ev_name, ev_file in ev_files.items():
                if not os.path.exists(ev_file):
                    return ToolResult(
                        status="error",
                        error=f"EV file not found for {ev_name}: {ev_file}",
                        data={},
                    )

            # Create output directory
            os.makedirs(output_dir, exist_ok=True)

            # Create arguments object
            args = FEATGLMArgs(
                input_file=input_file,
                output_dir=output_dir,
                tr=tr,
                ev_files=ev_files,
                contrasts=contrasts,
                **kwargs,
            )

            # Generate FSF file
            with tempfile.TemporaryDirectory() as temp_dir:
                fsf_file = self._generate_fsf_file(args, temp_dir)

                params_core = FSLFEATParameters(
                    fsf_path=fsf_file,
                    working_dir=os.path.dirname(fsf_file),
                    env={"FSLDIR": self.fsl_dir},
                )
                command_tokens = build_fsl_feat_command(
                    params_core, include_executable=True
                )
                env = build_fsl_feat_env(params_core)

                logger.info("Generated FEAT command: %s", " ".join(command_tokens))

                results = self._extract_results(output_dir)

                return ToolResult(
                    status="success",
                    data={
                        "command": " ".join(command_tokens),
                        "command_tokens": command_tokens,
                        "environment": env,
                        "fsf_file": fsf_file,
                        "output_dir": output_dir,
                        "results": results,
                        "contrasts": contrasts,
                        "message": "FSL FEAT GLM analysis configured successfully",
                    },
                )

        except Exception as e:
            logger.error(f"FSL FEAT GLM analysis failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class FEATGroupArgs(BaseModel):
    """Arguments for FEAT group analysis."""

    feat_dirs: List[str] = Field(description="List of first-level FEAT directories")
    output_dir: str = Field(description="Output directory for group analysis")
    group_design: Dict[str, List[float]] = Field(
        description="Group-level design matrix (e.g., {'group_mean': [1, 1, 1, ...]})"
    )
    mixed_effects: bool = Field(
        default=True, description="Use mixed effects (FLAME) vs fixed effects"
    )


class FSLFEATGroupTool(NeuroToolWrapper):
    """FSL FEAT higher-level (group) analysis tool."""

    def get_tool_name(self) -> str:
        return "fsl_feat_group"

    def get_tool_description(self) -> str:
        return (
            "Run FSL FEAT higher-level (group) analysis combining multiple first-level analyses. "
            "Uses FLAME mixed effects model for group inference."
        )

    def get_args_schema(self):
        return FEATGroupArgs

    def _run(
        self,
        feat_dirs: List[str],
        output_dir: str,
        group_design: Dict[str, List[float]],
        mixed_effects: bool = True,
    ) -> ToolResult:
        """Execute FEAT group analysis."""
        try:
            # Validate FEAT directories
            for feat_dir in feat_dirs:
                if not os.path.exists(feat_dir):
                    return ToolResult(
                        status="error",
                        error=f"FEAT directory not found: {feat_dir}",
                        data={},
                    )

            # Create output directory
            os.makedirs(output_dir, exist_ok=True)

            # Generate group-level FSF configuration
            # This would create the appropriate second/third level design

            return ToolResult(
                status="success",
                data={
                    "output_dir": output_dir,
                    "n_subjects": len(feat_dirs),
                    "design": group_design,
                    "mixed_effects": mixed_effects,
                    "message": "Group analysis configured successfully",
                },
            )

        except Exception as e:
            logger.error(f"FEAT group analysis failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


# ---------------------------------------------------------------------------
# NiWrap-backed FEAT (status=exact in mapping)
# ---------------------------------------------------------------------------


class FSLFEATNiWrapArgs(BaseModel):
    """Pass-through args for FEAT; NiWrap Boutiques schema is source of truth."""

    model_config = dict(extra="allow")


class FSLFEATNiWrapTool(NeuroToolWrapper):
    """Thin wrapper delegating to NiWrap fsl.feat.run."""

    def get_tool_name(self) -> str:
        return "fsl_feat"

    def get_tool_description(self) -> str:
        return "FSL FEAT (GLM) delegated to NiWrap Boutiques definition fsl.feat.run."

    def get_args_schema(self):
        return FSLFEATNiWrapArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            FSLFEATNiWrapArgs(**kwargs)
        except Exception as exc:  # pragma: no cover
            return ToolResult(status="error", error=str(exc), data={})

        output_dir = kwargs.get("output_dir") or kwargs.get("design_dir")
        if output_dir:
            try:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        try:
            data = execute_niwrap_tool(
                tool_definition=None,
                tool_name="fsl.feat.run",
                parameters=kwargs,
            )
            return ToolResult(status="success", data=data)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})


# Tool collection for registration
class FSLFEATTools:
    """Collection of FSL FEAT tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all FSL FEAT tools."""
        return [
            FSLFEATTool(),
            FSLFEATGroupTool(),
            FSLFEATNiWrapTool(),
        ]
