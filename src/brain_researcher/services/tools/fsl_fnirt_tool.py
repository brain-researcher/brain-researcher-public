"""FSL FNIRT non-linear registration tool wrapper."""

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.spec import ToolSpec
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class FSLFNIRTArgs(BaseModel):
    """Arguments for FSL FNIRT non-linear registration."""

    in_file: str = Field(description="Input image to be registered (NIfTI format)")
    ref_file: str = Field(
        description="Reference/template image (e.g., MNI152 template)"
    )
    output_dir: str = Field(description="Output directory for results")

    out_file: Optional[str] = Field(
        default=None, description="Output warped image name"
    )
    field_file: Optional[str] = Field(
        default=None, description="Output warp field file"
    )
    jacobian_file: Optional[str] = Field(
        default=None, description="Output Jacobian determinant file"
    )
    affine_file: Optional[str] = Field(
        default=None, description="Initial affine transformation matrix"
    )
    in_intensitymap_file: Optional[str] = Field(
        default=None, description="Input intensity mapping file"
    )
    config_file: Optional[str] = Field(
        default=None, description="Configuration file name or path"
    )

    warp_resolution: Optional[str] = Field(
        default="10,10,10", description="Warp field resolution in mm"
    )
    spline_order: Optional[int] = Field(
        default=3, description="Spline order for warping"
    )
    regularization_lambda: Optional[str] = Field(
        default=None, description="Regularization parameter(s)"
    )
    regularization_model: Optional[str] = Field(
        default="bending_energy", description="Regularization model"
    )
    max_iterations: Optional[str] = Field(
        default="5,5,5,5", description="Iterations per resolution level"
    )
    subsample_levels: Optional[str] = Field(
        default="4,2,1,1", description="Subsampling levels"
    )

    intensity_mapping: Optional[bool] = Field(
        default=False, description="Use intensity mapping/bias correction"
    )
    intensity_mapping_order: Optional[int] = Field(
        default=5, description="Polynomial order for intensity mapping"
    )

    ref_mask: Optional[str] = Field(
        default=None, description="Reference image mask file"
    )
    in_mask: Optional[str] = Field(default=None, description="Input image mask file")
    apply_ref_mask: Optional[int] = Field(
        default=1, description="Apply reference mask (0/1)"
    )
    apply_in_mask: Optional[int] = Field(
        default=1, description="Apply input mask (0/1)"
    )

    in_smoothing: Optional[str] = Field(
        default=None, description="Input smoothing sigma values"
    )
    ref_smoothing: Optional[str] = Field(
        default=None, description="Reference smoothing sigma values"
    )

    use_gradient_images: Optional[bool] = Field(
        default=False, description="Use gradient magnitude images"
    )
    jacobian_range: Optional[str] = Field(
        default="0.01,100.0", description="Allowable Jacobian range"
    )
    derive_from_ref: Optional[bool] = Field(
        default=False, description="Derive field from reference to input"
    )

    verbose: Optional[bool] = Field(default=False, description="Verbose output")
    debug: Optional[bool] = Field(
        default=False, description="Debug mode (keep intermediate files)"
    )


_FSL_FNIRT_SCHEMA = FSLFNIRTArgs.model_json_schema()

TOOL_SPEC = ToolSpec(
    name="fsl_fnirt",
    description="Configure FSL FNIRT non-linear registration.",
    json_schema=_FSL_FNIRT_SCHEMA,
    required=_FSL_FNIRT_SCHEMA.get("required", []),
    defaults={},
    category="fsl",
)


class FSLFNIRTTool(NeuroToolWrapper):
    """FSL FNIRT non-linear registration wrapper."""

    fnirt_command = "fnirt"
    applywarp_command = "applywarp"
    invwarp_command = "invwarp"

    def get_tool_name(self) -> str:
        return "fsl_fnirt"

    def get_tool_description(self) -> str:
        return "FSL FNIRT non-linear registration."

    def get_args_schema(self):
        return FSLFNIRTArgs

    def _run(self, **kwargs) -> ToolResult:
        """Validate args then run FNIRT via subprocess."""
        try:
            args = FSLFNIRTArgs(**kwargs)
        except Exception as e:  # pragma: no cover
            return ToolResult(status="error", error=str(e), data={})

        if not Path(args.in_file).exists():
            return ToolResult(
                status="error",
                error=f"Input file not found: {args.in_file}",
                data={},
            )
        if not Path(args.ref_file).exists():
            return ToolResult(
                status="error",
                error=f"Reference file not found: {args.ref_file}",
                data={},
            )

        output_dir = Path(args.output_dir)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        out_file = args.out_file or str(output_dir / "warped.nii.gz")
        field_file = args.field_file or str(output_dir / "warp_field.nii.gz")
        jacobian_file = args.jacobian_file

        cmd = [
            self.fnirt_command,
            "--in",
            args.in_file,
            "--ref",
            args.ref_file,
            "--iout",
            out_file,
            "--fout",
            field_file,
        ]

        if args.affine_file:
            cmd.extend(["--aff", args.affine_file])
        if args.ref_mask:
            cmd.extend(["--refmask", args.ref_mask])
        if args.in_mask:
            cmd.extend(["--inmask", args.in_mask])
        if args.apply_ref_mask is not None:
            cmd.extend(["--applyrefmask", str(args.apply_ref_mask)])
        if args.apply_in_mask is not None:
            cmd.extend(["--applyinmask", str(args.apply_in_mask)])
        if args.intensity_mapping:
            cmd.append("--intmod")
            cmd.extend(["--intorder", str(args.intensity_mapping_order)])
        if args.jacobian_file:
            cmd.extend(["--jout", jacobian_file])
        if args.jacobian_range:
            cmd.extend(["--jacrange", args.jacobian_range])
        if args.regularization_model:
            cmd.append(f"--regmod={args.regularization_model}")
        if args.regularization_lambda:
            cmd.extend(["--lambda", args.regularization_lambda])
        if args.max_iterations:
            cmd.extend(["--miter", args.max_iterations])
        if args.subsample_levels:
            cmd.extend(["--subsamp", args.subsample_levels])
        if args.in_smoothing:
            cmd.extend(["--infwhm", args.in_smoothing])
        if args.ref_smoothing:
            cmd.extend(["--reffwhm", args.ref_smoothing])
        if args.warp_resolution:
            cmd.extend(["--warpres", args.warp_resolution])
        if args.spline_order is not None:
            cmd.extend(["--splineorder", str(args.spline_order)])
        if args.config_file:
            cmd.extend(["--config", args.config_file])
        if args.verbose:
            cmd.append("--verbose")
        if args.debug:
            cmd.append("--debug")

        command_str = " ".join(cmd)
        logger.info("Running FNIRT: %s", command_str)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,
            )
        except subprocess.TimeoutExpired as exc:
            return ToolResult(
                status="error",
                error=f"FNIRT timed out: {exc}",
                data={"command": command_str},
            )
        except Exception as exc:  # pragma: no cover
            return ToolResult(
                status="error",
                error=str(exc),
                data={"command": command_str},
            )

        if result.returncode != 0:
            return ToolResult(
                status="error",
                error=f"Registration failed: {result.stderr}",
                data={"command": command_str},
            )

        outputs: Dict[str, Any] = {
            "warped_image": out_file,
            "warp_field": field_file,
        }
        if jacobian_file:
            outputs["jacobian"] = jacobian_file

        if kwargs.get("derive_from_ref") is False:
            inverse_warp = str(output_dir / "inverse_warp.nii.gz")
            invwarp_cmd = [
                self.invwarp_command,
                "--warp",
                field_file,
                "--ref",
                args.in_file,
                "--out",
                inverse_warp,
            ]
            invwarp_str = " ".join(invwarp_cmd)
            logger.info("Running invwarp: %s", invwarp_str)
            try:
                invwarp_result = subprocess.run(
                    invwarp_cmd,
                    capture_output=True,
                    text=True,
                    timeout=3600,
                )
            except subprocess.TimeoutExpired as exc:
                return ToolResult(
                    status="error",
                    error=f"Invwarp timed out: {exc}",
                    data={"command": invwarp_str},
                )
            if invwarp_result.returncode != 0:
                return ToolResult(
                    status="error",
                    error=f"Inverse warp failed: {invwarp_result.stderr}",
                    data={"command": invwarp_str},
                )
            outputs["inverse_warp"] = inverse_warp

        return ToolResult(
            status="success",
            data={"command": command_str, "outputs": outputs},
        )

    def apply_warp(
        self,
        in_file: str,
        ref_file: str,
        warp_file: str,
        out_file: str,
        interp: str = "trilinear",
    ) -> ToolResult:
        """Apply a warp field to an image."""
        for path, name in [
            (in_file, "Input"),
            (ref_file, "Reference"),
            (warp_file, "Warp"),
        ]:
            if not Path(path).exists():
                return ToolResult(
                    status="error",
                    error=f"{name} file not found: {path}",
                    data={},
                )

        cmd = [
            self.applywarp_command,
            "--in",
            in_file,
            "--ref",
            ref_file,
            "--warp",
            warp_file,
            "--out",
            out_file,
            "--interp",
            interp,
        ]
        command_str = " ".join(cmd)
        logger.info("Running applywarp: %s", command_str)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,
            )
        except subprocess.TimeoutExpired as exc:
            return ToolResult(
                status="error",
                error=f"Applywarp timed out: {exc}",
                data={"command": command_str},
            )
        except Exception as exc:  # pragma: no cover
            return ToolResult(
                status="error",
                error=str(exc),
                data={"command": command_str},
            )

        if result.returncode != 0:
            return ToolResult(
                status="error",
                error=f"Applywarp failed: {result.stderr}",
                data={"command": command_str},
            )

        return ToolResult(
            status="success",
            data={"command": command_str, "output_file": out_file},
        )


def get_all_tools() -> List[NeuroToolWrapper]:
    """Public factory for registry discovery."""
    return [FSLFNIRTTool()]


class FSLFNIRTTools:
    """Back-compat collection wrapper for registry imports."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        return get_all_tools()


__all__ = ["FSLFNIRTTool", "FSLFNIRTTools", "FSLFNIRTArgs", "TOOL_SPEC"]
