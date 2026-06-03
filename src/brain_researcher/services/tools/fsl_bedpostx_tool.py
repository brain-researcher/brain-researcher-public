"""
FSL BEDPOSTX Diffusion Modeling implementation for Brain Researcher.

Implements FSL's Bayesian Estimation of Diffusion Parameters Obtained using
Sampling Techniques with Crossing Fibres (BEDPOSTX) for advanced diffusion MRI analysis.
"""

import logging
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import shutil

from pydantic import BaseModel, Field
from brain_researcher.services.tools.niwrap.executor import execute_niwrap_tool

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class FSLBEDPOSTXArgs(BaseModel):
    """Arguments for FSL BEDPOSTX diffusion modeling."""

    # Input data (required)
    data_dir: str = Field(
        description="Directory containing diffusion data, bvals, bvecs, and mask"
    )
    output_dir: str = Field(
        description="Output directory for BEDPOSTX results (will create .bedpostX subdirectory)"
    )

    # Required input files (in data_dir)
    data_file: Optional[str] = Field(
        default="data.nii.gz",
        description="Diffusion data filename (default: data.nii.gz)"
    )
    mask_file: Optional[str] = Field(
        default="nodif_brain_mask.nii.gz",
        description="Brain mask filename (default: nodif_brain_mask.nii.gz)"
    )
    bvals_file: Optional[str] = Field(
        default="bvals",
        description="b-values filename (default: bvals)"
    )
    bvecs_file: Optional[str] = Field(
        default="bvecs",
        description="b-vectors filename (default: bvecs)"
    )

    # Model parameters
    n_fibres: int = Field(
        default=3,
        description="Maximum number of crossing fibres to model (1-3)"
    )
    weight: float = Field(
        default=1.0,
        description="ARD weight for automatic relevance determination"
    )
    burnin: int = Field(
        default=1000,
        description="Number of burn-in iterations for MCMC"
    )
    n_jumps: int = Field(
        default=1250,
        description="Number of jumps for MCMC sampling"
    )
    sample_every: int = Field(
        default=25,
        description="Sample every N iterations"
    )

    # Model options
    model: str = Field(
        default="1",
        description="Deconvolution model: 1=ball&stick, 2=ball&stick with dispersion, 3=ball&zeppelins"
    )
    grad_nonlin: Optional[str] = Field(
        default=None,
        description="Gradient nonlinearity correction file"
    )

    # Additional options
    rician: bool = Field(
        default=False,
        description="Use Rician noise model instead of Gaussian"
    )
    f0_threshold: float = Field(
        default=0.01,
        description="Threshold for f0 (CSF volume fraction)"
    )
    no_spat: bool = Field(
        default=False,
        description="Disable spatial priors"
    )
    no_ard: bool = Field(
        default=False,
        description="Disable automatic relevance determination"
    )
    all_ard: bool = Field(
        default=False,
        description="Use ARD on all fibres"
    )

    # CUDA options
    use_gpu: bool = Field(
        default=False,
        description="Use GPU acceleration (requires CUDA)"
    )
    gpu_id: Optional[int] = Field(
        default=None,
        description="GPU device ID to use"
    )

    # Runtime options
    n_jobs: int = Field(
        default=1,
        description="Number of parallel jobs for CPU version"
    )
    verbose: bool = Field(
        default=False,
        description="Verbose output"
    )

    # Post-processing options
    run_probtrackx: bool = Field(
        default=False,
        description="Run probabilistic tractography after BEDPOSTX"
    )
    make_dyads: bool = Field(
        default=True,
        description="Generate dyad (fiber direction) files"
    )


class ProbtrackXArgs(BaseModel):
    """Arguments for probabilistic tractography."""

    samples_dir: str = Field(
        description="BEDPOSTX samples directory (.bedpostX)"
    )
    mask_file: str = Field(
        description="Brain mask file"
    )
    seed_file: str = Field(
        description="Seed mask or coordinate list"
    )
    output_dir: str = Field(
        description="Output directory for tractography"
    )

    # Tracking parameters
    n_samples: int = Field(
        default=5000,
        description="Number of samples per seed"
    )
    n_steps: int = Field(
        default=2000,
        description="Maximum number of steps"
    )
    step_length: float = Field(
        default=0.5,
        description="Step length in mm"
    )
    curvature_threshold: float = Field(
        default=0.2,
        description="Curvature threshold (cosine of minimum angle)"
    )

    # Target/waypoint/exclusion masks
    target_masks: Optional[List[str]] = Field(
        default=None,
        description="Target mask files"
    )
    waypoint_masks: Optional[List[str]] = Field(
        default=None,
        description="Waypoint mask files (AND operation)"
    )
    exclusion_mask: Optional[str] = Field(
        default=None,
        description="Exclusion mask file"
    )
    termination_mask: Optional[str] = Field(
        default=None,
        description="Termination mask file"
    )

    # Output options
    output_type: str = Field(
        default="volume",
        description="Output type: volume, surface, or matrix"
    )
    save_paths: bool = Field(
        default=False,
        description="Save individual streamline paths"
    )
    opd: bool = Field(
        default=True,
        description="Output path distribution"
    )
    pd: bool = Field(
        default=True,
        description="Correct for path length"
    )
    os2t: bool = Field(
        default=False,
        description="Output seeds to targets"
    )


class FSLBEDPOSTXTool(NeuroToolWrapper):
    """FSL BEDPOSTX diffusion modeling tool."""

    def __init__(self):
        """Initialize FSL BEDPOSTX tool."""
        super().__init__()
        self._check_fsl()

    def _check_fsl(self):
        """Check FSL and BEDPOSTX installation."""
        try:
            result = subprocess.run(
                ["which", "bedpostx"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                self.fsl_available = True
                self.bedpostx_path = result.stdout.strip()
                logger.info(f"FSL BEDPOSTX found at {self.bedpostx_path}")

                # Check for GPU version
                gpu_result = subprocess.run(
                    ["which", "bedpostx_gpu"],
                    capture_output=True,
                    text=True
                )
                self.gpu_available = gpu_result.returncode == 0
                if self.gpu_available:
                    logger.info("GPU-accelerated BEDPOSTX available")
            else:
                self.fsl_available = False
                logger.warning("FSL BEDPOSTX not found in PATH")
        except Exception as e:
            self.fsl_available = False
            logger.error(f"Error checking FSL: {e}")

    def get_tool_name(self) -> str:
        return "fsl_bedpostx"

    def get_tool_description(self) -> str:
        return (
            "FSL BEDPOSTX (Bayesian Estimation of Diffusion Parameters) for "
            "advanced diffusion MRI modeling. Estimates fiber orientations using "
            "MCMC sampling, supports multiple crossing fibers, and provides "
            "uncertainty quantification. Includes GPU acceleration and probabilistic "
            "tractography with probtrackx2."
        )

    def get_args_schema(self):
        return FSLBEDPOSTXArgs

    def _prepare_bedpostx_dir(self, data_dir: str, output_dir: str, **kwargs):
        """Prepare directory structure for BEDPOSTX."""
        data_path = Path(data_dir)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Create bedpostX subdirectory
        bedpost_dir = output_path / f"{data_path.name}.bedpostX"
        bedpost_dir.mkdir(exist_ok=True)

        # Copy/link required files
        required_files = {
            kwargs.get('data_file', 'data.nii.gz'): 'data.nii.gz',
            kwargs.get('mask_file', 'nodif_brain_mask.nii.gz'): 'nodif_brain_mask.nii.gz',
            kwargs.get('bvals_file', 'bvals'): 'bvals',
            kwargs.get('bvecs_file', 'bvecs'): 'bvecs'
        }

        for src_name, dst_name in required_files.items():
            src_file = data_path / src_name
            dst_file = bedpost_dir / dst_name

            if not src_file.exists():
                raise FileNotFoundError(f"Required file not found: {src_file}")

            # Create symbolic link or copy
            if not dst_file.exists():
                try:
                    dst_file.symlink_to(src_file.absolute())
                except:
                    shutil.copy2(src_file, dst_file)

        return bedpost_dir

    def _run_bedpostx_monitors(self, bedpost_dir: Path, n_fibres: int, **kwargs):
        """Run BEDPOSTX preprocessing monitors."""
        logger.info("Running BEDPOSTX preprocessing...")

        # Run bedpostx_preproc
        preproc_cmd = [
            "bedpostx_preproc.sh",
            str(bedpost_dir)
        ]

        result = subprocess.run(
            preproc_cmd,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            logger.warning(f"Preprocessing warning: {result.stderr}")

        # Create options file
        options_file = bedpost_dir / "options"
        with open(options_file, 'w') as f:
            f.write(f"--nf={n_fibres}\n")
            f.write(f"--fudge={kwargs.get('weight', 1.0)}\n")
            f.write(f"--bi={kwargs.get('burnin', 1000)}\n")
            f.write(f"--nj={kwargs.get('n_jumps', 1250)}\n")
            f.write(f"--se={kwargs.get('sample_every', 25)}\n")
            f.write(f"--model={kwargs.get('model', '1')}\n")

            if kwargs.get('rician', False):
                f.write("--rician\n")
            if kwargs.get('no_spat', False):
                f.write("--nospat\n")
            if kwargs.get('no_ard', False):
                f.write("--noard\n")
            if kwargs.get('all_ard', False):
                f.write("--allard\n")

        return True

    def _run(
        self,
        data_dir: str,
        output_dir: str,
        data_file: Optional[str] = "data.nii.gz",
        mask_file: Optional[str] = "nodif_brain_mask.nii.gz",
        bvals_file: Optional[str] = "bvals",
        bvecs_file: Optional[str] = "bvecs",
        n_fibres: int = 3,
        weight: float = 1.0,
        burnin: int = 1000,
        n_jumps: int = 1250,
        sample_every: int = 25,
        model: str = "1",
        grad_nonlin: Optional[str] = None,
        rician: bool = False,
        f0_threshold: float = 0.01,
        no_spat: bool = False,
        no_ard: bool = False,
        all_ard: bool = False,
        use_gpu: bool = False,
        gpu_id: Optional[int] = None,
        n_jobs: int = 1,
        verbose: bool = False,
        run_probtrackx: bool = False,
        make_dyads: bool = True,
        **kwargs
    ) -> ToolResult:
        """Execute FSL BEDPOSTX diffusion modeling."""
        try:
            if not self.fsl_available:
                return ToolResult(
                    status="error",
                    error="FSL BEDPOSTX not available. Please install FSL.",
                    data={}
                )

            # Validate n_fibres
            if n_fibres < 1 or n_fibres > 3:
                return ToolResult(
                    status="error",
                    error="n_fibres must be between 1 and 3",
                    data={}
                )

            # Prepare directory structure
            logger.info("Preparing BEDPOSTX directory structure")
            bedpost_dir = self._prepare_bedpostx_dir(
                data_dir, output_dir,
                data_file=data_file, mask_file=mask_file,
                bvals_file=bvals_file, bvecs_file=bvecs_file
            )

            # Run preprocessing
            self._run_bedpostx_monitors(
                bedpost_dir, n_fibres,
                weight=weight, burnin=burnin, n_jumps=n_jumps,
                sample_every=sample_every, model=model,
                rician=rician, no_spat=no_spat, no_ard=no_ard,
                all_ard=all_ard
            )

            # Build BEDPOSTX command
            if use_gpu and self.gpu_available:
                cmd = ["bedpostx_gpu", str(data_dir)]
                if gpu_id is not None:
                    cmd.extend(["-g", str(gpu_id)])
            else:
                cmd = ["bedpostx", str(data_dir)]
                if n_jobs > 1:
                    cmd.extend(["-n", str(n_jobs)])

            # Add options
            cmd.extend(["-n", str(n_fibres)])
            cmd.extend(["-w", str(weight)])
            cmd.extend(["-b", str(burnin)])
            cmd.extend(["-j", str(n_jumps)])
            cmd.extend(["-s", str(sample_every)])
            cmd.extend(["-model", str(model)])

            if grad_nonlin:
                cmd.extend(["-g", grad_nonlin])

            if rician:
                cmd.append("--rician")

            if verbose:
                cmd.append("-V")

            # Execute BEDPOSTX
            logger.info(f"Running BEDPOSTX: {' '.join(cmd)}")
            logger.info("This may take several hours depending on data size...")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=36000  # 10 hour timeout
            )

            if result.returncode != 0:
                # Check if it's a common error
                if "already exists" in result.stderr:
                    logger.info("BEDPOSTX output already exists, checking completion")
                    # Check if results are complete
                    if not self._check_bedpostx_complete(bedpost_dir):
                        return ToolResult(
                            status="error",
                            error=f"BEDPOSTX incomplete: {result.stderr}",
                            data={}
                        )
                else:
                    return ToolResult(
                        status="error",
                        error=f"BEDPOSTX failed: {result.stderr}",
                        data={"command": " ".join(cmd)}
                    )

            # Wait for completion and check results
            if not self._check_bedpostx_complete(bedpost_dir):
                return ToolResult(
                    status="error",
                    error="BEDPOSTX did not complete successfully",
                    data={}
                )

            # Generate dyads if requested
            if make_dyads:
                logger.info("Generating dyad files")
                self._make_dyads(bedpost_dir, n_fibres)

            # Get output summary
            outputs = self._get_bedpostx_outputs(bedpost_dir, n_fibres)

            # Calculate metrics
            metrics = self._calculate_metrics(bedpost_dir, n_fibres)

            # Run probtrackx if requested
            probtrackx_output = None
            if run_probtrackx and "seed_file" in kwargs:
                logger.info("Running probabilistic tractography")
                probtrackx_output = self._run_probtrackx(
                    bedpost_dir, kwargs.get("seed_file"),
                    kwargs.get("probtrackx_args", {})
                )

            # Generate report
            report = {
                "data_dir": data_dir,
                "output_dir": str(bedpost_dir),
                "n_fibres": n_fibres,
                "model": model,
                "mcmc_parameters": {
                    "burnin": burnin,
                    "n_jumps": n_jumps,
                    "sample_every": sample_every
                },
                "outputs": outputs,
                "metrics": metrics,
                "probtrackx": probtrackx_output,
                "command": " ".join(cmd)
            }

            # Save report
            report_file = bedpost_dir / "bedpostx_report.json"
            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2)

            return ToolResult(
                status="success",
                data={
                    "outputs": outputs,
                    "metrics": metrics,
                    "bedpost_dir": str(bedpost_dir),
                    "report": str(report_file),
                    "message": f"BEDPOSTX completed successfully ({n_fibres} fibres)"
                }
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                status="error",
                error="BEDPOSTX timed out after 10 hours",
                data={}
            )
        except Exception as e:
            logger.error(f"BEDPOSTX failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )

    def _check_bedpostx_complete(self, bedpost_dir: Path) -> bool:
        """Check if BEDPOSTX completed successfully."""
        # Check for key output files
        required_files = [
            "mean_f1samples.nii.gz",
            "mean_th1samples.nii.gz",
            "mean_ph1samples.nii.gz",
            "merged_f1samples.nii.gz",
            "merged_th1samples.nii.gz",
            "merged_ph1samples.nii.gz"
        ]

        for file_name in required_files:
            if not (bedpost_dir / file_name).exists():
                logger.warning(f"Missing output file: {file_name}")
                return False

        # Check for completion flag
        if (bedpost_dir / "logs" / "monitor").exists():
            with open(bedpost_dir / "logs" / "monitor") as f:
                content = f.read()
                if "Finished" in content or "DONE" in content:
                    return True

        return True  # Assume complete if files exist

    def _make_dyads(self, bedpost_dir: Path, n_fibres: int):
        """Generate dyad (fiber direction) files."""
        try:
            for i in range(1, n_fibres + 1):
                cmd = [
                    "make_dyadic_vectors",
                    str(bedpost_dir / f"merged_th{i}samples"),
                    str(bedpost_dir / f"merged_ph{i}samples"),
                    str(bedpost_dir / "nodif_brain_mask"),
                    str(bedpost_dir / f"dyads{i}")
                ]

                subprocess.run(cmd, capture_output=True)
                logger.info(f"Created dyads{i}")
        except Exception as e:
            logger.warning(f"Could not create dyads: {e}")

    def _get_bedpostx_outputs(self, bedpost_dir: Path, n_fibres: int) -> Dict[str, Any]:
        """Get BEDPOSTX output files."""
        outputs = {
            "mean_samples": {},
            "merged_samples": {},
            "dyads": {}
        }

        for i in range(1, n_fibres + 1):
            # Mean samples
            mean_files = {
                f"mean_f{i}": str(bedpost_dir / f"mean_f{i}samples.nii.gz"),
                f"mean_th{i}": str(bedpost_dir / f"mean_th{i}samples.nii.gz"),
                f"mean_ph{i}": str(bedpost_dir / f"mean_ph{i}samples.nii.gz")
            }
            outputs["mean_samples"][f"fibre_{i}"] = mean_files

            # Merged samples
            merged_files = {
                f"merged_f{i}": str(bedpost_dir / f"merged_f{i}samples.nii.gz"),
                f"merged_th{i}": str(bedpost_dir / f"merged_th{i}samples.nii.gz"),
                f"merged_ph{i}": str(bedpost_dir / f"merged_ph{i}samples.nii.gz")
            }
            outputs["merged_samples"][f"fibre_{i}"] = merged_files

            # Dyads
            dyad_file = bedpost_dir / f"dyads{i}.nii.gz"
            if dyad_file.exists():
                outputs["dyads"][f"fibre_{i}"] = str(dyad_file)

        # Other outputs
        outputs["mean_d"] = str(bedpost_dir / "mean_dsamples.nii.gz")
        outputs["mean_S0"] = str(bedpost_dir / "mean_S0samples.nii.gz")
        outputs["mean_f0"] = str(bedpost_dir / "mean_f0samples.nii.gz")

        return outputs

    def _calculate_metrics(self, bedpost_dir: Path, n_fibres: int) -> Dict[str, Any]:
        """Calculate diffusion metrics from BEDPOSTX results."""
        metrics = {}

        try:
            import nibabel as nib
            import numpy as np

            # Load mask
            mask_file = bedpost_dir / "nodif_brain_mask.nii.gz"
            if mask_file.exists():
                mask = nib.load(mask_file).get_fdata() > 0
                n_voxels = np.sum(mask)
                metrics["n_voxels"] = int(n_voxels)

            # Calculate mean FA for each fiber
            for i in range(1, n_fibres + 1):
                f_file = bedpost_dir / f"mean_f{i}samples.nii.gz"
                if f_file.exists():
                    f_data = nib.load(f_file).get_fdata()

                    # Mean volume fraction
                    metrics[f"mean_f{i}"] = float(np.mean(f_data[mask]))
                    metrics[f"std_f{i}"] = float(np.std(f_data[mask]))

                    # Voxels with significant fiber fraction
                    significant_voxels = np.sum(f_data[mask] > 0.05)
                    metrics[f"n_voxels_f{i}_gt_0.05"] = int(significant_voxels)

            # Mean diffusivity
            d_file = bedpost_dir / "mean_dsamples.nii.gz"
            if d_file.exists():
                d_data = nib.load(d_file).get_fdata()
                metrics["mean_diffusivity"] = float(np.mean(d_data[mask]))
                metrics["std_diffusivity"] = float(np.std(d_data[mask]))

        except Exception as e:
            logger.warning(f"Could not calculate all metrics: {e}")

        return metrics

    def _run_probtrackx(self, bedpost_dir: Path, seed_file: str,
                        probtrackx_args: Dict) -> Dict[str, Any]:
        """Run probabilistic tractography using probtrackx2."""
        try:
            output_dir = bedpost_dir / "probtrackx"
            output_dir.mkdir(exist_ok=True)

            cmd = [
                "probtrackx2",
                "-x", seed_file,
                "-l",
                "--onewaycondition",
                "--forcedir",
                "--opd",
                "-c", str(probtrackx_args.get("curvature", 0.2)),
                "-S", str(probtrackx_args.get("n_steps", 2000)),
                "--steplength", str(probtrackx_args.get("step_length", 0.5)),
                "-P", str(probtrackx_args.get("n_samples", 5000)),
                "--fibthresh", str(probtrackx_args.get("fib_thresh", 0.01)),
                "--distthresh", str(probtrackx_args.get("dist_thresh", 0.0)),
                "--sampvox", str(probtrackx_args.get("samp_vox", 0.0)),
                "-s", str(bedpost_dir),
                "-m", str(bedpost_dir / "nodif_brain_mask"),
                "--dir", str(output_dir)
            ]

            # Add optional targets
            if "target_masks" in probtrackx_args:
                for target in probtrackx_args["target_masks"]:
                    cmd.extend(["--stop", target])

            logger.info(f"Running probtrackx2: {' '.join(cmd)}")

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                return {
                    "output_dir": str(output_dir),
                    "fdt_paths": str(output_dir / "fdt_paths.nii.gz")
                }
            else:
                logger.warning(f"Probtrackx failed: {result.stderr}")
                return None

        except Exception as e:
            logger.warning(f"Could not run probtrackx: {e}")
            return None


# ---------------------------------------------------------------------------
# NiWrap-backed BEDPOSTX (status=exact)
# ---------------------------------------------------------------------------


class FSLBEDPOSTXNiWrapArgs(BaseModel):
    """Pass-through args for BEDPOSTX; NiWrap Boutiques schema is source of truth."""

    model_config = dict(extra="allow")


class FSLBEDPOSTXNiWrapTool(NeuroToolWrapper):
    """Thin wrapper delegating to NiWrap fsl.bedpostx.run."""

    def get_tool_name(self) -> str:
        return "fsl_bedpostx"

    def get_tool_description(self) -> str:
        return "FSL BEDPOSTX delegated to NiWrap Boutiques definition fsl.bedpostx.run."

    def get_args_schema(self):
        return FSLBEDPOSTXNiWrapArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            FSLBEDPOSTXNiWrapArgs(**kwargs)
        except Exception as exc:  # pragma: no cover
            return ToolResult(status="error", error=str(exc), data={})

        output_dir = kwargs.get("output_dir") or kwargs.get("data_dir")
        if output_dir:
            try:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        try:
            data = execute_niwrap_tool(
                tool_definition=None,
                tool_name="fsl.bedpostx.run",
                parameters=kwargs,
            )
            return ToolResult(status="success", data=data)
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})


class FSLBEDPOSTXTools:
    """Collection of FSL BEDPOSTX tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all FSL BEDPOSTX tools."""
        return [
            FSLBEDPOSTXNiWrapTool(),
            FSLBEDPOSTXTool(),
            # ProbtrackXTool(),  # TODO: Implement ProbtrackX tool
        ]
