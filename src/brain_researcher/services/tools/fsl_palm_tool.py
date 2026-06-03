"""
FSL PALM (Permutation Analysis of Linear Models) implementation for Brain Researcher.

Implements permutation testing for complex general linear models with support
for exchangeability blocks, TFCE, and multiple comparison correction.
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from brain_researcher.services.tools.niwrap.executor import execute_niwrap_tool
from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class CorrectionMethod(str):
    """Multiple comparison correction methods."""

    NONE = "none"
    FWE = "fwe"  # Family-wise error
    FDR = "fdr"  # False discovery rate
    UNCORRECTED = "uncorrected"


class FSLPALMArgs(BaseModel):
    """Arguments for FSL PALM permutation testing."""

    # Input data
    input_file: str = Field(description="Input 4D data file (NIfTI format)")
    design_matrix: str = Field(description="Design matrix file (.mat or .csv)")
    contrast_file: str = Field(description="Contrast file (.con or .csv)")
    output_dir: str = Field(description="Output directory for results")

    # Mask
    mask_file: str | None = Field(
        default=None, description="Brain mask file (auto-generate if not provided)"
    )

    # Permutation settings
    n_permutations: int = Field(
        default=5000, description="Number of permutations (use 0 for exhaustive)"
    )
    exchangeability_blocks: str | None = Field(
        default=None, description="Exchangeability blocks file (.eb)"
    )

    # Statistical options
    two_tailed: bool = Field(default=True, description="Perform two-tailed tests")
    tfce: bool = Field(
        default=True, description="Use Threshold-Free Cluster Enhancement"
    )
    tfce_e: float = Field(default=0.5, description="TFCE extent parameter")
    tfce_h: float = Field(default=2.0, description="TFCE height parameter")

    # Correction methods
    correction_method: str = Field(
        default="fwe", description="Multiple comparison correction: none, fwe, fdr"
    )
    cluster_threshold: float | None = Field(
        default=None, description="Cluster-forming threshold (z-score)"
    )

    # Variance groups
    variance_groups: str | None = Field(
        default=None, description="Variance groups file for heteroscedasticity"
    )

    # Advanced options
    ise_flag: bool = Field(
        default=False,
        description="Use ISE (Independent and Symmetric Errors) assumption",
    )
    ee_flag: bool = Field(
        default=False, description="Use EE (Exchangeable Errors) assumption"
    )
    save_permutations: bool = Field(
        default=False, description="Save all permutation maps"
    )
    acceleration: str | None = Field(
        default=None, description="Acceleration method: tail, gamma, negbin"
    )

    # Surface data
    surface_file: str | None = Field(
        default=None, description="Surface file for surface-based analysis"
    )
    adjacency_file: str | None = Field(
        default=None, description="Surface adjacency file for clustering"
    )

    # Output options
    save_1p: bool = Field(default=True, description="Save 1-p values")
    save_log10p: bool = Field(default=False, description="Save -log10(p) values")
    output_prefix: str = Field(default="palm", description="Prefix for output files")


class FSLPALMTool(NeuroToolWrapper):
    """FSL PALM permutation testing tool."""

    def __init__(self):
        """Initialize FSL PALM tool."""
        super().__init__()
        self._check_palm()

    def _check_palm(self):
        """Check if PALM is available."""
        self.palm_available = False

        # Check for PALM in PATH
        try:
            result = subprocess.run(["which", "palm"], capture_output=True, text=True)
            if result.returncode == 0:
                self.palm_available = True
                self.palm_path = result.stdout.strip()
                logger.info(f"PALM available at {self.palm_path}")
        except:
            pass

        # Check FSL directory
        if not self.palm_available:
            fsl_dir = os.environ.get("FSLDIR")
            if fsl_dir:
                palm_path = os.path.join(fsl_dir, "bin", "palm")
                if os.path.exists(palm_path):
                    self.palm_available = True
                    self.palm_path = palm_path
                    logger.info(f"PALM found in FSL: {palm_path}")

        if not self.palm_available:
            # PALM is optional; avoid noisy warnings when absent
            logger.info(
                "PALM not available - install from FSL or standalone (optional)"
            )

    def get_tool_name(self) -> str:
        return "fsl_palm"

    def get_tool_description(self) -> str:
        return (
            "FSL PALM (Permutation Analysis of Linear Models) for non-parametric "
            "inference using permutation testing. Supports complex designs with "
            "exchangeability blocks, TFCE, and various acceleration methods. "
            "Handles both volume and surface-based data with FWE and FDR correction."
        )

    def get_args_schema(self):
        return FSLPALMArgs

    def _prepare_design_files(
        self, design_matrix: str, contrast_file: str, output_dir: Path
    ) -> tuple[str, str]:
        """Prepare design matrix and contrast files for PALM."""
        # Check if files are already in PALM format
        if design_matrix.endswith(".mat") and contrast_file.endswith(".con"):
            return design_matrix, contrast_file

        # Convert CSV to PALM format
        design_out = output_dir / "design.mat"
        contrast_out = output_dir / "design.con"

        if design_matrix.endswith(".csv"):
            # Load CSV and convert to FSL format
            design_df = pd.read_csv(design_matrix)
            design_array = design_df.values

            # Write as text file that Text2Vest can read
            design_txt = output_dir / "design.txt"
            np.savetxt(design_txt, design_array)

            # Convert to .mat using Text2Vest if available
            try:
                subprocess.run(
                    ["Text2Vest", str(design_txt), str(design_out)],
                    check=True,
                    capture_output=True,
                )
                design_matrix = str(design_out)
            except:
                logger.warning("Text2Vest not available, using text format")
                design_matrix = str(design_txt)

        if contrast_file.endswith(".csv"):
            # Load CSV and convert
            contrast_df = pd.read_csv(contrast_file)
            contrast_array = contrast_df.values

            contrast_txt = output_dir / "contrast.txt"
            np.savetxt(contrast_txt, contrast_array)

            try:
                subprocess.run(
                    ["Text2Vest", str(contrast_txt), str(contrast_out)],
                    check=True,
                    capture_output=True,
                )
                contrast_file = str(contrast_out)
            except:
                contrast_file = str(contrast_txt)

        return design_matrix, contrast_file

    def _create_exchangeability_blocks(
        self, n_subjects: int, block_structure: list[int] | None = None
    ) -> str:
        """Create exchangeability blocks file."""
        if block_structure:
            # Use provided block structure
            eb_array = np.array(block_structure)
        else:
            # Default: all subjects exchangeable
            eb_array = np.ones(n_subjects, dtype=int)

        return eb_array

    def _build_palm_command(
        self,
        input_file: str,
        design_matrix: str,
        contrast_file: str,
        output_prefix: str,
        **kwargs,
    ) -> list[str]:
        """Build PALM command with all options."""
        cmd = ["palm" if not self.palm_available else self.palm_path]

        # Input files
        cmd.extend(["-i", input_file])
        cmd.extend(["-d", design_matrix])
        cmd.extend(["-t", contrast_file])
        cmd.extend(["-o", output_prefix])

        # Mask
        if kwargs.get("mask_file"):
            cmd.extend(["-m", kwargs["mask_file"]])

        # Permutations
        n_perm = kwargs.get("n_permutations", 5000)
        cmd.extend(["-n", str(n_perm)])

        # Exchangeability blocks
        if kwargs.get("exchangeability_blocks"):
            cmd.extend(["-eb", kwargs["exchangeability_blocks"]])

        # Two-tailed test
        if kwargs.get("two_tailed", True):
            cmd.append("-twotail")

        # TFCE
        if kwargs.get("tfce", True):
            cmd.append("-T")
            if kwargs.get("tfce_e") and kwargs.get("tfce_h"):
                cmd.extend(["-tfce", f"E={kwargs['tfce_e']},H={kwargs['tfce_h']}"])

        # Cluster threshold
        if kwargs.get("cluster_threshold"):
            cmd.extend(["-C", str(kwargs["cluster_threshold"])])

        # Variance groups
        if kwargs.get("variance_groups"):
            cmd.extend(["-vg", kwargs["variance_groups"]])

        # ISE/EE flags
        if kwargs.get("ise_flag"):
            cmd.append("-ise")
        if kwargs.get("ee_flag"):
            cmd.append("-ee")

        # Save permutations
        if kwargs.get("save_permutations"):
            cmd.append("-saveperms")

        # Acceleration
        if kwargs.get("acceleration"):
            cmd.extend(["-accel", kwargs["acceleration"]])

        # Surface data
        if kwargs.get("surface_file"):
            cmd.extend(["-s", kwargs["surface_file"]])
            if kwargs.get("adjacency_file"):
                cmd.extend(["-adj", kwargs["adjacency_file"]])

        # Output options
        if kwargs.get("save_1p", True):
            cmd.append("-save1-p")
        if kwargs.get("save_log10p"):
            cmd.append("-logp")

        # Correction method
        correction = kwargs.get("correction_method", "fwe")
        if correction == "fdr":
            cmd.append("-fdr")
        elif correction == "none":
            cmd.append("-uncorrected")

        return cmd

    def _parse_palm_output(
        self, output_dir: Path, output_prefix: str
    ) -> dict[str, Any]:
        """Parse PALM output files and extract results."""
        results = {"output_files": [], "contrasts": {}, "statistics": {}}

        # Find all output files
        output_files = list(output_dir.glob(f"{output_prefix}_*.nii*"))
        results["output_files"] = [str(f) for f in output_files]

        # Parse different output types
        for output_file in output_files:
            filename = output_file.name

            # Parse filename to understand content
            # Format: prefix_vox_[tfce_]tstat/fstat_[c1/c2/f1]_[corrected].nii.gz
            if "_tstat_" in filename:
                # T-statistic map
                contrast_num = (
                    filename.split("_c")[-1].split("_")[0] if "_c" in filename else "1"
                )
                if contrast_num not in results["contrasts"]:
                    results["contrasts"][contrast_num] = {}

                if "_tfce_" in filename:
                    results["contrasts"][contrast_num]["tfce_tstat"] = str(output_file)
                else:
                    results["contrasts"][contrast_num]["tstat"] = str(output_file)

            elif "_fwep_" in filename:
                # FWE-corrected p-values
                contrast_num = (
                    filename.split("_c")[-1].split("_")[0] if "_c" in filename else "1"
                )
                if contrast_num not in results["contrasts"]:
                    results["contrasts"][contrast_num] = {}
                results["contrasts"][contrast_num]["fwe_pvalue"] = str(output_file)

            elif "_uncp_" in filename:
                # Uncorrected p-values
                contrast_num = (
                    filename.split("_c")[-1].split("_")[0] if "_c" in filename else "1"
                )
                if contrast_num not in results["contrasts"]:
                    results["contrasts"][contrast_num] = {}
                results["contrasts"][contrast_num]["uncorrected_pvalue"] = str(
                    output_file
                )

        # Load and analyze a sample result
        if results["contrasts"]:
            first_contrast = list(results["contrasts"].values())[0]
            if "fwe_pvalue" in first_contrast:
                try:
                    pval_img = nib.load(first_contrast["fwe_pvalue"])
                    pval_data = pval_img.get_fdata()

                    # Calculate statistics
                    results["statistics"]["min_pvalue"] = float(
                        np.min(pval_data[pval_data > 0])
                    )
                    results["statistics"]["n_significant_voxels"] = int(
                        np.sum(pval_data < 0.05)
                    )
                    results["statistics"]["volume_shape"] = pval_data.shape
                except:
                    pass

        return results

    def _run(
        self,
        input_file: str,
        design_matrix: str,
        contrast_file: str,
        output_dir: str,
        mask_file: str | None = None,
        n_permutations: int = 5000,
        exchangeability_blocks: str | None = None,
        two_tailed: bool = True,
        tfce: bool = True,
        tfce_e: float = 0.5,
        tfce_h: float = 2.0,
        correction_method: str = "fwe",
        cluster_threshold: float | None = None,
        variance_groups: str | None = None,
        ise_flag: bool = False,
        ee_flag: bool = False,
        save_permutations: bool = False,
        acceleration: str | None = None,
        surface_file: str | None = None,
        adjacency_file: str | None = None,
        save_1p: bool = True,
        save_log10p: bool = False,
        output_prefix: str = "palm",
        **kwargs,
    ) -> ToolResult:
        """Execute FSL PALM permutation testing."""
        try:
            # Validate input file
            if not Path(input_file).exists():
                return ToolResult(
                    status="error", error=f"Input file not found: {input_file}", data={}
                )

            # Create output directory
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Prepare design files
            design_matrix, contrast_file = self._prepare_design_files(
                design_matrix, contrast_file, output_path
            )

            # Full output prefix with path
            full_output_prefix = str(output_path / output_prefix)

            # Build PALM command
            cmd = self._build_palm_command(
                input_file=input_file,
                design_matrix=design_matrix,
                contrast_file=contrast_file,
                output_prefix=full_output_prefix,
                mask_file=mask_file,
                n_permutations=n_permutations,
                exchangeability_blocks=exchangeability_blocks,
                two_tailed=two_tailed,
                tfce=tfce,
                tfce_e=tfce_e,
                tfce_h=tfce_h,
                correction_method=correction_method,
                cluster_threshold=cluster_threshold,
                variance_groups=variance_groups,
                ise_flag=ise_flag,
                ee_flag=ee_flag,
                save_permutations=save_permutations,
                acceleration=acceleration,
                surface_file=surface_file,
                adjacency_file=adjacency_file,
                save_1p=save_1p,
                save_log10p=save_log10p,
            )

            # Generate command string
            command_str = " ".join(cmd)

            if not self.palm_available:
                # Return command for manual execution
                return ToolResult(
                    status="success",
                    data={
                        "command": command_str,
                        "message": "PALM command generated (PALM not available for execution)",
                        "output_dir": str(output_path),
                    },
                )

            # Execute PALM
            logger.info(f"Running PALM: {command_str}")

            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=str(output_path)
            )

            if result.returncode != 0:
                return ToolResult(
                    status="error",
                    error=f"PALM execution failed: {result.stderr}",
                    data={"command": command_str},
                )

            # Parse output
            palm_results = self._parse_palm_output(output_path, output_prefix)

            # Generate report
            report = {
                "input_file": input_file,
                "design_matrix": design_matrix,
                "contrast_file": contrast_file,
                "n_permutations": n_permutations,
                "tfce": tfce,
                "correction_method": correction_method,
                "results": palm_results,
                "command": command_str,
            }

            # Save report
            report_file = output_path / "palm_report.json"
            with open(report_file, "w") as f:
                json.dump(report, f, indent=2)

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "report": str(report_file),
                        "results": palm_results,
                        "output_dir": str(output_path),
                    },
                    "statistics": palm_results.get("statistics", {}),
                    "message": f"PALM analysis completed with {n_permutations} permutations",
                },
            )

        except Exception as e:
            logger.error(f"PALM processing failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})


class PALMSurfaceTool(NeuroToolWrapper):
    """PALM for surface-based analysis."""

    def __init__(self):
        """Initialize surface PALM tool."""
        super().__init__()
        self.base_tool = FSLPALMTool()

    def get_tool_name(self) -> str:
        return "palm_surface"

    def get_tool_description(self) -> str:
        return (
            "FSL PALM for surface-based permutation testing. Handles FreeSurfer "
            "and CIFTI surface data with appropriate neighborhood definitions "
            "for cluster-based inference."
        )

    def get_args_schema(self):
        class SurfaceArgs(FSLPALMArgs):
            surface_file: str = Field(
                description="Surface file (FreeSurfer or GIFTI format)"
            )
            surface_data: str = Field(
                description="Surface data file (func.gii or .mgh)"
            )
            input_file: str | None = Field(
                default=None, description="Not used for surface analysis"
            )

        return SurfaceArgs

    def _run(
        self,
        surface_file: str,
        surface_data: str,
        design_matrix: str,
        contrast_file: str,
        output_dir: str,
        **kwargs,
    ) -> ToolResult:
        """Execute surface-based PALM analysis."""
        # Set surface-specific parameters
        kwargs["surface_file"] = surface_file
        kwargs["input_file"] = surface_data  # Surface data as input

        # Run base PALM with surface parameters
        return self.base_tool._run(
            input_file=surface_data,
            design_matrix=design_matrix,
            contrast_file=contrast_file,
            output_dir=output_dir,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# NiWrap-backed PALM (descriptor presumed as fsl.palm.run)
# ---------------------------------------------------------------------------


class FSLPALMNiWrapArgs(BaseModel):
    """Pass-through args for PALM; NiWrap Boutiques schema is source of truth."""

    model_config = {"extra": "allow"}


class FSLPALMNiWrapTool(NeuroToolWrapper):
    """Thin wrapper delegating to NiWrap fsl.palm.run."""

    def get_tool_name(self) -> str:
        return "fsl_palm"

    def get_tool_description(self) -> str:
        return "FSL PALM delegated to NiWrap Boutiques definition fsl.palm.run (descriptor pending)."

    def get_args_schema(self):
        return FSLPALMNiWrapArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            FSLPALMNiWrapArgs(**kwargs)
        except Exception as exc:  # pragma: no cover
            return ToolResult(status="error", error=str(exc), data={})

        output_dir = kwargs.get("output_dir")
        if output_dir:
            try:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        try:
            data = execute_niwrap_tool(
                tool_definition=None,
                tool_name="fsl.palm.run",
                parameters=kwargs,
            )
            return ToolResult(status="success", data=data)
        except Exception as exc:
            logger.exception("FSL PALM NiWrap failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class FSLPALMTools:
    """Collection of FSL PALM tools."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        """Get all FSL PALM tools."""
        return [FSLPALMNiWrapTool(), FSLPALMTool(), PALMSurfaceTool()]
