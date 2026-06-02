"""
FSL MELODIC ICA implementation for the BR-KG LangGraph system.

Implements FSL MELODIC for Independent Component Analysis of fMRI data with
automatic classification and denoising capabilities.
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
    FSLMELODICParameters,
    build_fsl_melodic_command,
)
from brain_researcher.services.tools.spec import ToolSpec
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class ICADimensionality(str, Enum):
    """ICA dimensionality estimation methods."""

    AUTOMATIC = "automatic"  # Automatic dimensionality estimation
    LAPLACE = "laplace"  # Laplace approximation
    BIC = "bic"  # Bayesian Information Criterion
    MDL = "mdl"  # Minimum Description Length
    AIC = "aic"  # Akaike Information Criterion
    MANUAL = "manual"  # Manual specification


class ApproachType(str, Enum):
    """MELODIC approach types."""

    CONCAT = "concat"  # Concatenate across time
    MIGP = "migp"  # MIGP group analysis
    TENSOR = "tensor"  # Tensor decomposition
    CONCAT_GROUP = "concat_group"  # Group concatenation


class NoiseClassification(str, Enum):
    """Noise component classification methods."""

    MANUAL = "manual"  # Manual classification
    FIX = "fix"  # FSL FIX automatic classification
    AROMA = "aroma"  # ICA-AROMA
    CUSTOM = "custom"  # Custom classifier


@dataclass
class MELODICConfig:
    """Configuration for MELODIC analysis."""

    approach: ApproachType
    n_components: Optional[int]
    dimensionality: ICADimensionality
    tr: float
    output_dir: str
    mask: Optional[str] = None
    bg_threshold: float = 10.0
    var_norm: bool = True  # Variance normalization
    output_all: bool = True  # Output all ICA outputs
    report: bool = True  # Generate HTML report

    def to_command_args(self) -> List[str]:
        """Convert configuration to MELODIC command arguments."""
        args = []

        # Approach type
        if self.approach == ApproachType.CONCAT:
            args.extend(["-a", "concat"])
        elif self.approach == ApproachType.MIGP:
            args.extend(["-a", "migp"])
        elif self.approach == ApproachType.TENSOR:
            args.extend(["-a", "tensor"])

        # Dimensionality
        if self.dimensionality == ICADimensionality.MANUAL and self.n_components:
            args.extend(["-d", str(self.n_components)])
        elif self.dimensionality == ICADimensionality.AUTOMATIC:
            args.extend(["-d", "0"])  # Automatic estimation
        elif self.dimensionality == ICADimensionality.LAPLACE:
            args.extend(["--dim_est=lap"])
        elif self.dimensionality == ICADimensionality.BIC:
            args.extend(["--dim_est=bic"])

        # TR
        args.extend(["--tr", str(self.tr)])

        # Output directory
        args.extend(["-o", self.output_dir])

        # Mask if provided
        if self.mask:
            args.extend(["-m", self.mask])

        # Background threshold
        args.extend(["--bgthreshold", str(self.bg_threshold)])

        # Variance normalization
        if self.var_norm:
            args.append("--vn")
        else:
            args.append("--no_vn")

        # Output options
        if self.output_all:
            args.append("--Oall")

        # Report generation
        if self.report:
            args.append("--report")

        return args


class MELODICArgs(BaseModel):
    """Arguments for FSL MELODIC ICA analysis."""

    input_files: Union[str, List[str]] = Field(
        description="Path to 4D NIfTI file(s) or text file listing multiple inputs"
    )
    output_dir: str = Field(description="Output directory for MELODIC results")
    tr: float = Field(description="Repetition time in seconds")
    approach: ApproachType = Field(
        default=ApproachType.CONCAT, description="ICA approach (concat, migp, tensor)"
    )
    n_components: Optional[int] = Field(
        default=None, description="Number of ICA components (None for automatic)"
    )
    dimensionality: ICADimensionality = Field(
        default=ICADimensionality.AUTOMATIC,
        description="Dimensionality estimation method",
    )
    mask: Optional[str] = Field(default=None, description="Brain mask file (optional)")
    bg_threshold: float = Field(
        default=10.0, description="Background threshold percentage"
    )
    var_norm: bool = Field(default=True, description="Apply variance normalization")
    output_all: bool = Field(default=True, description="Output all ICA outputs")
    generate_report: bool = Field(default=True, description="Generate HTML report")
    denoise: bool = Field(default=False, description="Apply denoising after ICA")
    noise_components: Optional[List[int]] = Field(
        default=None,
        description="Manual specification of noise component indices (1-based)",
    )


class DualRegressionArgs(BaseModel):
    """Arguments for dual regression analysis."""

    group_ica_dir: str = Field(description="Path to group MELODIC output directory")
    subject_files: List[str] = Field(description="List of subject 4D NIfTI files")
    output_dir: str = Field(description="Output directory for dual regression results")
    design_matrix: Optional[str] = Field(
        default=None, description="Design matrix for group comparison"
    )
    contrast_file: Optional[str] = Field(
        default=None, description="Contrast file for group comparison"
    )
    n_permutations: int = Field(
        default=5000, description="Number of permutations for inference"
    )
    var_norm: bool = Field(default=True, description="Apply variance normalization")


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
    _FSL_MELODIC_SCHEMA = MELODICArgs.model_json_schema()
except AttributeError:  # pragma: no cover
    _FSL_MELODIC_SCHEMA = MELODICArgs.schema()


TOOL_SPEC = ToolSpec(
    name="fsl_melodic_ica",
    description="Configure FSL MELODIC ICA analysis via neurocore command builders.",
    json_schema=_FSL_MELODIC_SCHEMA,
    required=_model_required(MELODICArgs),
    defaults=_model_defaults(MELODICArgs),
    category="fsl",
)


class FSLMELODICTool(NeuroToolWrapper):
    """FSL MELODIC ICA analysis tool."""

    def __init__(self):
        """Initialize FSL MELODIC tool."""
        super().__init__()
        self.fsl_dir = "/cvmfs/neurodesk.ardc.edu.au/containers/fsl_6.0.7.16_20250131"

    def get_tool_name(self) -> str:
        return "fsl_melodic_ica"

    def get_tool_description(self) -> str:
        return (
            "Run FSL MELODIC for Independent Component Analysis of fMRI data. "
            "Supports single-subject and group ICA with automatic dimensionality estimation, "
            "artifact classification, and denoising capabilities."
        )

    def get_args_schema(self):
        return MELODICArgs

    def _prepare_input_list(
        self, input_files: Union[str, List[str]], temp_dir: str
    ) -> str:
        """Prepare input file list for MELODIC."""
        if isinstance(input_files, str):
            # Single file
            return input_files
        else:
            # Multiple files - create text file listing them
            list_file = os.path.join(temp_dir, "input_files.txt")
            with open(list_file, "w") as f:
                for file_path in input_files:
                    f.write(f"{file_path}\n")
            return list_file

    def _run_melodic(
        self, config: MELODICConfig, input_target: str | List[str]
    ) -> Dict[str, Any]:
        """Build MELODIC command using shared neurocore helpers."""
        if isinstance(input_target, list):
            inputs_tuple = tuple(input_target)
        else:
            inputs_tuple = (input_target,)

        params = FSLMELODICParameters(
            input_files=inputs_tuple,
            output_dir=config.output_dir,
            tr=config.tr,
            approach=config.approach.value,
            dimensionality=config.dimensionality.value,
            n_components=config.n_components,
            mask=config.mask,
            bg_threshold=config.bg_threshold,
            var_norm=config.var_norm,
            output_all=config.output_all,
            report=config.report,
        )

        command_tokens = build_fsl_melodic_command(params, include_executable=True)
        logger.info("Generated MELODIC command: %s", " ".join(command_tokens))

        return {
            "command": " ".join(command_tokens),
            "command_tokens": command_tokens,
            "output_dir": config.output_dir,
            "approach": config.approach.value,
            "dimensionality": config.dimensionality.value,
            "n_components": config.n_components,
        }

    def _apply_denoising(
        self,
        melodic_dir: str,
        input_file: str,
        noise_components: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Apply denoising using identified noise components."""
        # If no noise components specified, would need automatic classification
        if noise_components is None:
            logger.warning("No noise components specified for denoising")
            return {"status": "skipped", "reason": "No noise components specified"}

        # Generate fsl_regfilt command for denoising
        denoised_file = input_file.replace(".nii", "_denoised.nii")

        # Convert component indices to comma-separated string
        noise_str = ",".join(str(c) for c in noise_components)

        regfilt_cmd = (
            f"{self.fsl_dir}/bin/fsl_regfilt "
            f"-i {input_file} "
            f"-o {denoised_file} "
            f"-d {melodic_dir}/melodic_mix "
            f"-f {noise_str}"
        )

        logger.info(f"Generated denoising command: {regfilt_cmd}")

        return {
            "command": regfilt_cmd,
            "denoised_file": denoised_file,
            "noise_components": noise_components,
            "melodic_dir": melodic_dir,
        }

    def _extract_results(self, melodic_dir: str) -> Dict[str, Any]:
        """Extract key results from MELODIC output directory."""
        results = {
            "melodic_dir": melodic_dir,
            "components": {},
            "stats": {},
            "report": None,
        }

        # Check for key output files
        if os.path.exists(melodic_dir):
            # Component maps
            ic_file = os.path.join(melodic_dir, "melodic_IC.nii.gz")
            if os.path.exists(ic_file):
                results["components"]["spatial_maps"] = ic_file

            # Mixing matrix
            mix_file = os.path.join(melodic_dir, "melodic_mix")
            if os.path.exists(mix_file):
                results["components"]["mixing_matrix"] = mix_file

            # Time series
            ts_file = os.path.join(melodic_dir, "melodic_Tmodes")
            if os.path.exists(ts_file):
                results["components"]["time_series"] = ts_file

            # Power spectra
            power_file = os.path.join(melodic_dir, "melodic_FTmix")
            if os.path.exists(power_file):
                results["components"]["power_spectra"] = power_file

            # Stats
            stats_dir = os.path.join(melodic_dir, "stats")
            if os.path.exists(stats_dir):
                # List threshold z-stat images
                for zstat_file in Path(stats_dir).glob("thresh_zstat*.nii.gz"):
                    # Extract just the number from the filename
                    comp_num = zstat_file.stem.split(".")[0].replace("thresh_zstat", "")
                    results["stats"][f"component_{comp_num}"] = str(zstat_file)

            # HTML report
            report_file = os.path.join(melodic_dir, "report.html")
            if os.path.exists(report_file):
                results["report"] = report_file

            # Log file
            log_file = os.path.join(melodic_dir, "log.txt")
            if os.path.exists(log_file):
                results["log"] = log_file

        return results

    def _run(
        self,
        input_files: Union[str, List[str]],
        output_dir: str,
        tr: float,
        approach: ApproachType = ApproachType.CONCAT,
        n_components: Optional[int] = None,
        dimensionality: ICADimensionality = ICADimensionality.AUTOMATIC,
        mask: Optional[str] = None,
        bg_threshold: float = 10.0,
        var_norm: bool = True,
        output_all: bool = True,
        generate_report: bool = True,
        denoise: bool = False,
        noise_components: Optional[List[int]] = None,
        **kwargs,
    ) -> ToolResult:
        """Execute FSL MELODIC ICA analysis."""
        try:
            # Validate input files
            if isinstance(input_files, str):
                if not os.path.exists(input_files):
                    return ToolResult(
                        status="error",
                        error=f"Input file not found: {input_files}",
                        data={},
                    )
            else:
                for file_path in input_files:
                    if not os.path.exists(file_path):
                        return ToolResult(
                            status="error",
                            error=f"Input file not found: {file_path}",
                            data={},
                        )

            # Create output directory
            os.makedirs(output_dir, exist_ok=True)

            # Prepare configuration
            with tempfile.TemporaryDirectory() as temp_dir:
                # Prepare input list
                input_file = self._prepare_input_list(input_files, temp_dir)

                # Create MELODIC configuration
                config = MELODICConfig(
                    approach=approach,
                    n_components=n_components,
                    dimensionality=dimensionality,
                    tr=tr,
                    output_dir=output_dir,
                    mask=mask,
                    bg_threshold=bg_threshold,
                    var_norm=var_norm,
                    output_all=output_all,
                    report=generate_report,
                )

                # Run MELODIC
                melodic_result = self._run_melodic(config, input_file)

                # Apply denoising if requested
                denoise_result = None
                if denoise:
                    if isinstance(input_files, str):
                        denoise_result = self._apply_denoising(
                            output_dir, input_files, noise_components
                        )
                    else:
                        logger.warning("Denoising not applied for multiple input files")

                # Extract results
                results = self._extract_results(output_dir)

                # Combine all results
                final_result = {
                    "melodic": melodic_result,
                    "results": results,
                    "denoising": denoise_result,
                    "message": "FSL MELODIC ICA analysis configured successfully",
                }

                return ToolResult(status="success", data=final_result)

        except Exception as e:
            logger.error(f"FSL MELODIC analysis failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class DualRegressionTool(NeuroToolWrapper):
    """FSL Dual Regression tool for group ICA analysis."""

    def __init__(self):
        """Initialize Dual Regression tool."""
        super().__init__()
        self.fsl_dir = "/cvmfs/neurodesk.ardc.edu.au/containers/fsl_6.0.7.16_20250131"

    def get_tool_name(self) -> str:
        return "fsl_dual_regression"

    def get_tool_description(self) -> str:
        return (
            "Run FSL dual regression for group ICA analysis. "
            "Projects group ICA components to individual subjects and performs "
            "group comparisons with permutation testing."
        )

    def get_args_schema(self):
        return DualRegressionArgs

    def _run(
        self,
        group_ica_dir: str,
        subject_files: List[str],
        output_dir: str,
        design_matrix: Optional[str] = None,
        contrast_file: Optional[str] = None,
        n_permutations: int = 5000,
        var_norm: bool = True,
        **kwargs,
    ) -> ToolResult:
        """Execute dual regression analysis."""
        try:
            # Validate group ICA directory
            if not os.path.exists(group_ica_dir):
                return ToolResult(
                    status="error",
                    error=f"Group ICA directory not found: {group_ica_dir}",
                    data={},
                )

            # Validate subject files
            for subject_file in subject_files:
                if not os.path.exists(subject_file):
                    return ToolResult(
                        status="error",
                        error=f"Subject file not found: {subject_file}",
                        data={},
                    )

            # Group ICA maps
            group_ic = os.path.join(group_ica_dir, "melodic_IC.nii.gz")
            if not os.path.exists(group_ic):
                return ToolResult(
                    status="error",
                    error=f"Group IC file not found: {group_ic}",
                    data={},
                )

            # Create output directory after all validation checks so permission
            # errors don't mask missing-input diagnostics.
            os.makedirs(output_dir, exist_ok=True)

            # Prepare dual regression command
            dr_cmd = [f"{self.fsl_dir}/bin/dual_regression"]

            dr_cmd.append(group_ic)

            # Design matrix (1 for single group if not provided)
            if design_matrix:
                dr_cmd.append("1")  # Use design matrix
                dr_cmd.append(design_matrix)
            else:
                dr_cmd.append("0")  # No design matrix

            # Contrast file
            if contrast_file:
                dr_cmd.append(contrast_file)
            else:
                dr_cmd.append("-1")  # No contrasts

            # Number of permutations
            dr_cmd.append(str(n_permutations))

            # Output directory
            dr_cmd.append(output_dir)

            # Variance normalization
            vn_flag = "1" if var_norm else "0"
            dr_cmd.append(vn_flag)

            # Add subject files
            dr_cmd.extend(subject_files)

            # Generate command string
            cmd_str = " ".join(dr_cmd)
            logger.info(f"Generated dual regression command: {cmd_str}")

            # Prepare results
            results = {
                "command": cmd_str,
                "output_dir": output_dir,
                "group_ica_dir": group_ica_dir,
                "n_subjects": len(subject_files),
                "n_permutations": n_permutations,
                "var_norm": var_norm,
            }

            if design_matrix:
                results["design_matrix"] = design_matrix
            if contrast_file:
                results["contrast_file"] = contrast_file

            return ToolResult(
                status="success",
                data={
                    "dual_regression": results,
                    "message": "Dual regression analysis configured successfully",
                },
            )

        except Exception as e:
            logger.error(f"Dual regression analysis failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


# ---------------------------------------------------------------------------
# NiWrap-backed MELODIC (status=exact)
# ---------------------------------------------------------------------------


class FSLMELODICNiWrapArgs(BaseModel):
    """Pass-through args for MELODIC; NiWrap Boutiques schema is source of truth."""

    model_config = dict(extra="allow")


class FSLMELODICNiWrapTool(NeuroToolWrapper):
    """Thin wrapper delegating to NiWrap fsl.melodic.run."""

    def get_tool_name(self) -> str:
        return "fsl_melodic"

    def get_tool_description(self) -> str:
        return "FSL MELODIC delegated to NiWrap Boutiques definition fsl.melodic.run."

    def get_args_schema(self):
        return FSLMELODICNiWrapArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            FSLMELODICNiWrapArgs(**kwargs)
        except Exception as exc:  # pragma: no cover
            return ToolResult(status="error", error=str(exc), data={})

        output_dir = kwargs.get("output_dir") or kwargs.get("out_dir")
        if output_dir:
            try:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        try:
            data = execute_niwrap_tool(
                tool_definition=None,
                tool_name="fsl.melodic.run",
                parameters=kwargs,
            )
            return ToolResult(status="success", data=data)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})


# Tool collection for registration
class FSLMELODICTools:
    """Collection of FSL MELODIC ICA tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all FSL MELODIC tools."""
        return [
            FSLMELODICTool(),
            DualRegressionTool(),
            FSLMELODICNiWrapTool(),
        ]
