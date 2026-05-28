"""FSL BET tool for skull stripping and brain extraction."""

import logging
import subprocess
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.qc_rendering import render_mask_overlay_png
from brain_researcher.services.tools.niwrap.executor import execute_niwrap_tool
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult
from brain_researcher.services.tools.spec import (
    ToolQCPrecheckConfig,
    ToolQCRenderContract,
    ToolQCRetryRule,
    ToolQCSpec,
    ToolSpec,
)

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


class BETSurfaceEstimation(str, Enum):
    """BET surface estimation options."""
    DEFAULT = ""  # Default surface estimation
    ROBUST = "-R"  # Robust brain center estimation
    EYE_CLEANUP = "-S"  # Eye & optic nerve cleanup
    BIAS_FIELD = "-B"  # Bias field & neck cleanup


class FSLBETArgs(BaseModel):
    """Arguments for FSL BET brain extraction."""
    
    input_file: str = Field(
        description="Path to input NIfTI file (T1, T2, or functional)"
    )
    output_file: str = Field(
        description="Path to output brain-extracted file"
    )
    fractional_intensity: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Fractional intensity threshold (0-1); smaller values give larger brain outline"
    )
    gradient_threshold: float = Field(
        default=0.0,
        ge=0.0,
        description="Vertical gradient in fractional intensity threshold"
    )
    generate_mask: bool = Field(
        default=True,
        description="Generate binary brain mask"
    )
    generate_skull: bool = Field(
        default=False,
        description="Generate skull image"
    )
    generate_surface: bool = Field(
        default=False,
        description="Generate brain surface mesh"
    )
    surface_estimation: BETSurfaceEstimation = Field(
        default=BETSurfaceEstimation.DEFAULT,
        description="Surface estimation method"
    )
    apply_to_4d: bool = Field(
        default=False,
        description="Apply to 4D fMRI data"
    )
    reduce_bias: bool = Field(
        default=False,
        description="Reduce image bias and neck cleanup"
    )
    robust_center: bool = Field(
        default=False,
        description="Robust brain center estimation (iterative)"
    )
    center_coordinates: Optional[tuple] = Field(
        default=None,
        description="Center of gravity coordinates (x, y, z) in voxels"
    )
    radius: Optional[int] = Field(
        default=None,
        description="Head radius in mm (default auto-estimated)"
    )


def _model_required(model_cls) -> list[str]:
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


_FSL_BET_SCHEMA = FSLBETArgs.model_json_schema()


TOOL_SPEC = ToolSpec(
    name="fsl_bet",
    description="Run FSL BET brain extraction with shared neurocore command builder.",
    json_schema=_FSL_BET_SCHEMA,
    required=_model_required(FSLBETArgs),
    defaults=_model_defaults(FSLBETArgs),
    category="fsl",
    niwrap_id="fsl.bet.run",
    qc_spec=ToolQCSpec(
        artifact_output_keys=["qc_png"],
        checklist=[
            "Confirm the brain mask excludes scalp and skull.",
            "Confirm inferior frontal lobes, cerebellum, and brainstem are preserved.",
            "Look for obvious over-stripping near the orbitofrontal cortex and inferior slices.",
            "Look for obvious non-brain tissue retained around the skull boundary.",
        ],
        failure_modes=[
            "over_strip",
            "non_brain_retained",
            "centering_issue",
            "mask_missing",
            "output_missing",
        ],
        render_contract=ToolQCRenderContract(
            kind="mask_overlay",
            layout="tri_planar_montage",
            notes="Review the tri-planar mask overlay for missing brain tissue or retained skull.",
        ),
        prechecks=ToolQCPrecheckConfig(
            required_outputs={
                "mask": "mask_missing",
                "qc_png": "output_missing",
            }
        ),
        retry_rules=[
            ToolQCRetryRule(
                match_any_failure_modes=["over_strip"],
                param_updates={"fractional_intensity": 0.3, "robust_center": True},
                notes="Lower BET threshold when brain tissue is clipped.",
            ),
            ToolQCRetryRule(
                match_any_failure_modes=["non_brain_retained"],
                param_updates={"fractional_intensity": 0.6},
                notes="Raise BET threshold when scalp or skull remain.",
            ),
            ToolQCRetryRule(
                match_any_failure_modes=["centering_issue"],
                param_updates={"robust_center": True},
                notes="Enable robust center estimation for asymmetric failures.",
            ),
            ToolQCRetryRule(
                match_any_failure_modes=["mask_missing"],
                param_updates={"robust_center": True},
                notes="Retry once with robust center estimation when the BET mask is missing.",
            ),
        ],
    ),
)


class FSLBETTool(NeuroToolWrapper):
    """FSL BET thin wrapper backed by NiWrap (fsl.bet.run)."""

    TOOL_SPEC = TOOL_SPEC

    def get_tool_name(self) -> str:
        return "fsl_bet"

    def get_tool_description(self) -> str:
        return (
            "FSL BET (Brain Extraction Tool) for skull stripping and brain extraction. "
            "Implementation delegates to NiWrap Boutiques definition fsl.bet.run."
        )

    def get_args_schema(self):
        return FSLBETArgs

    def _validate_input(self, input_file: str) -> tuple[bool, str]:
        if not Path(input_file).exists():
            return False, f"Input file not found: {input_file}"
        if not (input_file.endswith(".nii") or input_file.endswith(".nii.gz")):
            return False, "Invalid file format. Expected NIfTI (.nii or .nii.gz)"
        return True, ""

    def _construct_command(self, args: FSLBETArgs) -> list[str]:
        cmd = ["bet", args.input_file, args.output_file]
        cmd.extend(["-f", str(args.fractional_intensity)])

        if args.gradient_threshold:
            cmd.extend(["-g", str(args.gradient_threshold)])
        if args.generate_mask:
            cmd.append("-m")
        if args.generate_skull:
            cmd.append("-s")
        if args.generate_surface:
            cmd.append("-o")
        if args.apply_to_4d:
            cmd.append("-F")
        if args.reduce_bias:
            cmd.append("-B")
        if args.robust_center:
            cmd.append("-R")

        if args.surface_estimation and args.surface_estimation.value:
            cmd.append(args.surface_estimation.value)

        if args.center_coordinates:
            cmd.append("-c")
            cmd.extend(str(v) for v in args.center_coordinates)
        if args.radius is not None:
            cmd.extend(["-r", str(args.radius)])

        return cmd

    def _detect_outputs(self, args: FSLBETArgs) -> Dict[str, str]:
        outputs: Dict[str, str] = {}
        output_file = Path(args.output_file)
        outputs["brain"] = str(output_file)

        stem = output_file.name
        if stem.endswith(".nii.gz"):
            base = stem[:-7]
        elif stem.endswith(".nii"):
            base = stem[:-4]
        else:
            base = output_file.stem

        if args.generate_mask:
            mask_file = output_file.with_name(f"{base}_mask.nii.gz")
            if mask_file.exists():
                outputs["mask"] = str(mask_file)
        if args.generate_skull:
            skull_file = output_file.with_name(f"{base}_skull.nii.gz")
            if skull_file.exists():
                outputs["skull"] = str(skull_file)

        return outputs

    def _run(self, **kwargs) -> ToolResult:
        """Run BET locally and return outputs."""
        try:
            args = FSLBETArgs(**kwargs)
        except Exception as e:
            return ToolResult(status="error", error=str(e), data={})

        valid, error = self._validate_input(args.input_file)
        if not valid:
            return ToolResult(status="error", error=error, data={})

        Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
        command = self._construct_command(args)
        command_str = " ".join(command)

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                status="error",
                error="BET command timed out",
                data={"command": command_str},
            )
        except FileNotFoundError:
            return ToolResult(
                status="error",
                error="BET executable not found",
                data={"command": command_str},
            )

        if completed.returncode != 0:
            return ToolResult(
                status="error",
                error=f"BET failed: {completed.stderr.strip()}",
                data={"command": command_str},
            )

        outputs = self._detect_outputs(args)
        qc_png = None
        mask_file = outputs.get("mask")
        if mask_file:
            try:
                qc_png = render_mask_overlay_png(
                    args.input_file,
                    mask_file,
                    Path(args.output_file).with_name(
                        f"{Path(args.output_file).stem}_qc.png"
                    ),
                    title="FSL BET QC",
                )
                outputs["qc_png"] = qc_png
            except Exception as exc:
                logger.warning("Failed to render BET QC PNG: %s", exc)
        return ToolResult(
            status="success",
            data={
                "command": command_str,
                "outputs": outputs,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )

    def extract_brain_batch(
        self,
        input_files: list[str],
        output_dir: str,
        fractional_intensity: float = 0.5,
    ) -> ToolResult:
        processed = []
        for input_file in input_files:
            output_file = str(Path(output_dir) / f"{Path(input_file).stem}_brain.nii.gz")
            result = self._run(
                input_file=input_file,
                output_file=output_file,
                fractional_intensity=fractional_intensity,
            )
            processed.append(
                {
                    "input": input_file,
                    "output": output_file,
                    "status": result.status,
                }
            )

        n_processed = len(processed)
        status = (
            "success"
            if all(item["status"] == "success" for item in processed)
            else "partial"
        )
        return ToolResult(
            status=status,
            data={"processed": processed, "n_processed": n_processed},
        )


def get_all_tools() -> list:
    """Public factory for registry discovery."""
    return [FSLBETTool()]


class FSLBETTools:
    """Back-compat collection wrapper for registry imports."""

    @staticmethod
    def get_all_tools() -> list:
        return get_all_tools()
