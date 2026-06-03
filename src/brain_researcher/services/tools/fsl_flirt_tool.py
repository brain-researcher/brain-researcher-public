"""FSL FLIRT registration tool wrapper."""

import logging
import subprocess
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.services.tools.qc_rendering import (
    render_registration_checkerboard_png,
)
from brain_researcher.services.tools.spec import (
    ToolQCPrecheckConfig,
    ToolQCRenderContract,
    ToolQCRetryRule,
    ToolQCSpec,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class FLIRTCostFunction(str, Enum):
    """FLIRT cost function options."""

    CORRELATION_RATIO = "corratio"  # Default, robust multi-modal
    MUTUAL_INFO = "mutualinfo"  # Mutual information
    LEAST_SQUARES = "leastsq"  # Least squares (same modality)
    NORMALIZED_CORRELATION = "normcorr"  # Normalized correlation
    NORMALIZED_MUTUAL_INFO = "normmi"  # Normalized mutual information
    LABELLED_SLICES = "labeldiff"  # For label images


class FLIRTSearchMethod(str, Enum):
    """FLIRT search method options."""

    REGULAR_STEP = "reg"  # Regular stepping (fast)
    GLOBAL_SEARCH = "global"  # Global search (slow but robust)


class FSLFLIRTArgs(BaseModel):
    """Arguments for FSL FLIRT registration."""

    input_file: str = Field(description="Input/source image to be registered")
    reference_file: str = Field(description="Reference/target image")
    output_file: str = Field(description="Output registered image")
    output_matrix: str | None = Field(
        default=None, description="Output affine transformation matrix file"
    )
    init_matrix: str | None = Field(
        default=None, description="Initial transformation matrix to apply"
    )
    dof: int = Field(
        default=12,
        ge=6,
        le=12,
        description="Degrees of freedom (6=rigid, 7=global rescale, 9=traditional, 12=affine)",
    )
    cost_function: FLIRTCostFunction = Field(
        default=FLIRTCostFunction.CORRELATION_RATIO,
        description="Cost function for registration",
    )
    search_method: FLIRTSearchMethod = Field(
        default=FLIRTSearchMethod.REGULAR_STEP,
        description="Search method for optimization",
    )
    search_range_x: tuple[float, float] = Field(
        default=(-90, 90), description="Search range in X (degrees)"
    )
    search_range_y: tuple[float, float] = Field(
        default=(-90, 90), description="Search range in Y (degrees)"
    )
    search_range_z: tuple[float, float] = Field(
        default=(-90, 90), description="Search range in Z (degrees)"
    )
    coarse_search: float | None = Field(
        default=None, description="Coarse search delta angle (degrees)"
    )
    fine_search: float | None = Field(
        default=None, description="Fine search delta angle (degrees)"
    )
    interp_method: str = Field(
        default="trilinear",
        description="Interpolation method (nearestneighbour, trilinear, sinc, spline)",
    )
    weighting_image: str | None = Field(
        default=None, description="Weighting image for reference"
    )
    no_search: bool = Field(
        default=False, description="Skip search, just apply transformation"
    )
    verbose: bool = Field(default=False, description="Verbose output")
    use_gradient: bool = Field(
        default=True, description="Use gradient information in cost function"
    )


QC_SPEC = ToolQCSpec(
    artifact_output_keys=["qc_png"],
    checklist=[
        "Confirm the registered image aligns to the reference without obvious translation or rotation errors.",
        "Look for gross cortical or ventricular boundary mismatch across the checkerboard.",
        "Confirm major anatomical structures overlap across sagittal, coronal, and axial views.",
    ],
    failure_modes=["misregistration", "output_missing", "uncertain"],
    render_contract=ToolQCRenderContract(
        kind="checkerboard",
        layout="tri_planar_montage",
        notes="Review the checkerboard montage for boundary mismatch and gross misalignment.",
    ),
    prechecks=ToolQCPrecheckConfig(
        required_outputs={
            "registered_image": "output_missing",
            "qc_png": "output_missing",
        }
    ),
    retry_rules=[
        ToolQCRetryRule(
            match_any_failure_modes=["misregistration"],
            min_attempt=0,
            max_attempt=0,
            param_updates={
                "search_method": FLIRTSearchMethod.GLOBAL_SEARCH.value,
                "cost_function": FLIRTCostFunction.NORMALIZED_MUTUAL_INFO.value,
                "no_search": False,
            },
            notes="Escalate FLIRT to a global search with a more robust multimodal cost.",
        ),
        ToolQCRetryRule(
            match_any_failure_modes=["misregistration"],
            min_attempt=1,
            max_attempt=1,
            fallback_tool="ants_registration",
            notes="Fallback to ANTs after one failed FLIRT retry.",
        ),
    ],
)


class FSLFLIRTTool(NeuroToolWrapper):
    """FSL FLIRT linear registration wrapper."""

    flirt_command = "flirt"
    applyxfm_command = "flirt"
    convert_xfm_command = "convert_xfm"
    QC_SPEC = QC_SPEC

    def get_tool_name(self) -> str:
        return "fsl_flirt"

    def get_tool_description(self) -> str:
        return "FSL FLIRT for linear (affine) registration."

    def get_args_schema(self):
        return FSLFLIRTArgs

    def _run(self, **kwargs) -> ToolResult:
        """Validate args then run FLIRT via subprocess."""
        try:
            args = FSLFLIRTArgs(**kwargs)
        except Exception as e:  # pragma: no cover
            return ToolResult(status="error", error=str(e), data={})

        for file_path, name in [
            (args.input_file, "Input"),
            (args.reference_file, "Reference"),
        ]:
            if not Path(file_path).exists():
                return ToolResult(
                    status="error",
                    error=f"{name} file not found: {file_path}",
                    data={},
                )

        try:
            Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        cmd = [
            self.flirt_command,
            "-in",
            args.input_file,
            "-ref",
            args.reference_file,
            "-out",
            args.output_file,
        ]

        if args.output_matrix:
            cmd.extend(["-omat", args.output_matrix])
        if args.init_matrix:
            cmd.extend(["-init", args.init_matrix])
        if args.dof:
            cmd.extend(["-dof", str(args.dof)])
        if args.cost_function:
            cmd.extend(["-cost", args.cost_function.value])
        if args.search_method == FLIRTSearchMethod.GLOBAL_SEARCH:
            cmd.extend(
                [
                    "-searchrx",
                    str(args.search_range_x[0]),
                    str(args.search_range_x[1]),
                    "-searchry",
                    str(args.search_range_y[0]),
                    str(args.search_range_y[1]),
                    "-searchrz",
                    str(args.search_range_z[0]),
                    str(args.search_range_z[1]),
                ]
            )
        if args.coarse_search is not None:
            cmd.extend(["-coarsesearch", str(args.coarse_search)])
        if args.fine_search is not None:
            cmd.extend(["-finesearch", str(args.fine_search)])
        if args.interp_method:
            cmd.extend(["-interp", args.interp_method])
        if args.weighting_image:
            cmd.extend(["-refweight", args.weighting_image])
        if args.no_search:
            cmd.append("-nosearch")
        if args.verbose:
            cmd.append("-v")

        command_str = " ".join(cmd)
        logger.info("Running FLIRT: %s", command_str)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except Exception as exc:  # pragma: no cover
            return ToolResult(
                status="error", error=str(exc), data={"command": command_str}
            )

        if result.returncode != 0:
            return ToolResult(
                status="error",
                error=f"Registration failed: {result.stderr}",
                data={"command": command_str},
            )

        outputs = {"registered_image": args.output_file}
        if args.output_matrix:
            outputs["transformation_matrix"] = args.output_matrix
        if Path(args.output_file).exists():
            try:
                qc_png = render_registration_checkerboard_png(
                    args.reference_file,
                    args.output_file,
                    Path(args.output_file).with_name(
                        f"{Path(args.output_file).stem}_qc.png"
                    ),
                    title="FSL FLIRT QC",
                )
                outputs["qc_png"] = qc_png
            except Exception as exc:
                logger.warning("Failed to render FLIRT QC PNG: %s", exc)

        return ToolResult(
            status="success",
            data={"command": command_str, "outputs": outputs},
        )

    def apply_transformation(
        self,
        input_file: str,
        reference_file: str,
        output_file: str,
        transformation_matrix: str,
        interp_method: str = "trilinear",
    ) -> ToolResult:
        """Apply a previously computed transformation matrix."""
        try:
            # Validate files
            for file, name in [
                (input_file, "Input"),
                (reference_file, "Reference"),
                (transformation_matrix, "Matrix"),
            ]:
                if not Path(file).exists():
                    return ToolResult(
                        status="error", error=f"{name} file not found: {file}", data={}
                    )

            # Construct command
            cmd = [
                self.applyxfm_command,
                "-in",
                input_file,
                "-ref",
                reference_file,
                "-out",
                output_file,
                "-init",
                transformation_matrix,
                "-applyxfm",
                "-interp",
                interp_method,
            ]

            command_str = " ".join(cmd)
            logger.info(f"Applying transformation: {command_str}")

            # Execute
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                return ToolResult(
                    status="error",
                    error=f"Apply transformation failed: {result.stderr}",
                    data={"command": command_str},
                )

            return ToolResult(
                status="success",
                data={
                    "command": command_str,
                    "output_file": output_file,
                    "message": "Transformation applied successfully",
                },
            )

        except Exception as e:
            logger.error(f"Apply transformation failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})

    def invert_transformation(
        self, input_matrix: str, output_matrix: str
    ) -> ToolResult:
        """Invert a transformation matrix."""
        try:
            if not Path(input_matrix).exists():
                return ToolResult(
                    status="error",
                    error=f"Input matrix not found: {input_matrix}",
                    data={},
                )

            # Use convert_xfm to invert
            cmd = [
                self.convert_xfm_command,
                "-omat",
                output_matrix,
                "-inverse",
                input_matrix,
            ]

            command_str = " ".join(cmd)
            logger.info(f"Inverting matrix: {command_str}")

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                return ToolResult(
                    status="error",
                    error=f"Matrix inversion failed: {result.stderr}",
                    data={"command": command_str},
                )

            return ToolResult(
                status="success",
                data={
                    "command": command_str,
                    "output_matrix": output_matrix,
                    "message": "Matrix inverted successfully",
                },
            )

        except Exception as e:
            logger.error(f"Matrix inversion failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})

    def concatenate_transformations(
        self, matrix1: str, matrix2: str, output_matrix: str
    ) -> ToolResult:
        """Concatenate two transformation matrices."""
        try:
            # Validate inputs
            for file, name in [(matrix1, "Matrix 1"), (matrix2, "Matrix 2")]:
                if not Path(file).exists():
                    return ToolResult(
                        status="error", error=f"{name} not found: {file}", data={}
                    )

            # Use convert_xfm to concatenate
            cmd = [
                self.convert_xfm_command,
                "-omat",
                output_matrix,
                "-concat",
                matrix2,
                matrix1,  # Note: order matters!
            ]

            command_str = " ".join(cmd)
            logger.info(f"Concatenating matrices: {command_str}")

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                return ToolResult(
                    status="error",
                    error=f"Matrix concatenation failed: {result.stderr}",
                    data={"command": command_str},
                )

            return ToolResult(
                status="success",
                data={
                    "command": command_str,
                    "output_matrix": output_matrix,
                    "message": "Matrices concatenated successfully",
                },
            )

        except Exception as e:
            logger.error(f"Matrix concatenation failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


def get_all_tools() -> list:
    """Public factory for registry discovery."""
    return [FSLFLIRTTool()]


class FSLFLIRTTools:
    """Back-compat collection wrapper for registry imports."""

    @staticmethod
    def get_all_tools() -> list:
        return get_all_tools()
