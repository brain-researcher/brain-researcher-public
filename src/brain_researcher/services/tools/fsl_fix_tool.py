"""
FSL FIX (FMRIB's ICA-based Xnoiseifier) implementation for Brain Researcher.

Implements automated ICA artifact classification and removal for fMRI data
using machine learning classifiers trained on hand-labeled components.
"""

import logging
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple
import subprocess

from pydantic import BaseModel, Field
from brain_researcher.services.tools.niwrap.executor import execute_niwrap_tool

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class FSLFIXArgs(BaseModel):
    """Arguments for FSL FIX artifact removal."""

    # Input data
    feat_dir: str = Field(
        description="Path to FEAT directory containing MELODIC ICA output"
    )
    training_data: str = Field(
        default="Standard",
        description="Training dataset to use (Standard, HCP_hp2000, WhII_MB6, etc.) or path to custom .RData"
    )
    threshold: float = Field(
        default=20.0,
        description="Classification threshold (0-100, higher = more aggressive)"
    )

    # Output options
    output_dir: Optional[str] = Field(
        default=None,
        description="Output directory (default: in-place in FEAT dir)"
    )

    # Classification options
    motion_cleanup: bool = Field(
        default=True,
        description="Apply aggressive motion cleanup"
    )
    highpass: Optional[float] = Field(
        default=None,
        description="High-pass filter cutoff in seconds (e.g., 150)"
    )

    # Training options (for custom training)
    train_mode: bool = Field(
        default=False,
        description="Train new classifier instead of applying existing"
    )
    hand_labels_file: Optional[str] = Field(
        default=None,
        description="File containing hand labels for training ([1 2 3 ...] for noise)"
    )

    # Advanced options
    feature_extraction: bool = Field(
        default=True,
        description="Extract features for classification"
    )
    multi_run_mode: bool = Field(
        default=False,
        description="Multi-run FIX mode for multiple sessions"
    )
    leave_one_out: bool = Field(
        default=False,
        description="Use leave-one-out cross-validation for threshold selection"
    )

    # Performance options
    use_gpu: bool = Field(
        default=False,
        description="Use GPU acceleration if available"
    )
    n_threads: Optional[int] = Field(
        default=None,
        description="Number of threads for parallel processing"
    )


# ---------------------------------------------------------------------------
# NiWrap-backed FIX (Boutiques: fsl.fslFixText.run)
# ---------------------------------------------------------------------------


class FSLFIXNiWrapArgs(BaseModel):
    """Pass-through args for FIX; NiWrap Boutiques schema is source of truth."""

    model_config = dict(extra="allow")


class FSLFIXNiWrapTool(NeuroToolWrapper):
    """Thin wrapper delegating to NiWrap fsl.fslFixText.run."""

    def get_tool_name(self) -> str:
        return "fsl_fix"

    def get_tool_description(self) -> str:
        return "FSL FIX delegated to NiWrap Boutiques definition fsl.fslFixText.run."

    def get_args_schema(self):
        return FSLFIXNiWrapArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            FSLFIXNiWrapArgs(**kwargs)
        except Exception as exc:  # pragma: no cover
            return ToolResult(status="error", error=str(exc), data={})

        output_dir = kwargs.get("output_dir") or kwargs.get("feat_dir")
        if output_dir:
            try:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        try:
            data = execute_niwrap_tool(
                tool_definition=None,
                tool_name="fsl.fslFixText.run",
                parameters=kwargs,
            )
            return ToolResult(status="success", data=data)
        except Exception as exc:
            logger.exception("FSL FIX NiWrap failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class FSLFIXTool(NeuroToolWrapper):
    """FSL FIX artifact removal tool."""

    def __init__(self):
        """Initialize FSL FIX tool."""
        super().__init__()
        self._check_fsl()

    def _check_fsl(self):
        """Check if FSL and FIX are available."""
        self.fsl_available = False
        self.fix_available = False

        # Check FSL
        fsl_dir = os.environ.get('FSLDIR')
        if fsl_dir and os.path.exists(fsl_dir):
            self.fsl_available = True
            self.fsl_dir = fsl_dir

            # Check for FIX
            fix_path = os.path.join(fsl_dir, 'bin', 'fix')
            if os.path.exists(fix_path):
                self.fix_available = True
                logger.info(f"FSL FIX available at {fix_path}")
            else:
                # FIX is optional; downgrade to info to avoid noisy logs when absent
                logger.info("FSL FIX not found in FSL installation (optional)")
        else:
            logger.info("FSL not available - set FSLDIR environment variable")

    def get_tool_name(self) -> str:
        return "fsl_fix"

    def get_tool_description(self) -> str:
        return (
            "FSL FIX (FMRIB's ICA-based Xnoiseifier) for automated artifact removal "
            "from fMRI data. Uses machine learning to classify and remove noise "
            "components from MELODIC ICA decompositions. Supports both pre-trained "
            "classifiers and custom training on hand-labeled data."
        )

    def get_args_schema(self):
        return FSLFIXArgs

    def _validate_feat_dir(self, feat_dir: str) -> Tuple[bool, str]:
        """Validate FEAT directory structure."""
        feat_path = Path(feat_dir)

        if not feat_path.exists():
            return False, f"FEAT directory not found: {feat_dir}"

        # Check for required MELODIC output
        melodic_dir = feat_path / "filtered_func_data.ica"
        if not melodic_dir.exists():
            # Try alternative location
            melodic_dir = feat_path / "reg_standard" / "filtered_func_data.ica"
            if not melodic_dir.exists():
                return False, "No MELODIC ICA output found in FEAT directory"

        # Check for required files
        required_files = [
            melodic_dir / "melodic_IC.nii.gz",
            melodic_dir / "melodic_mix",
            melodic_dir / "melodic_FTmix"
        ]

        for req_file in required_files:
            if not req_file.exists():
                return False, f"Required file missing: {req_file}"

        return True, str(melodic_dir)

    def _get_training_data_path(self, training_data: str) -> str:
        """Get path to training data file."""
        # Standard training datasets
        standard_datasets = {
            "Standard": "Standard.RData",
            "HCP_hp2000": "HCP_hp2000.RData",
            "WhII_MB6": "WhII_MB6.RData",
            "WhII_Standard": "WhII_Standard.RData",
            "UKBiobank": "UKBiobank.RData"
        }

        if training_data in standard_datasets:
            # Look for standard training data in FIX directory
            if self.fsl_available:
                fix_dir = os.path.join(self.fsl_dir, "data", "fix")
                training_file = os.path.join(fix_dir, standard_datasets[training_data])
                if os.path.exists(training_file):
                    return training_file

                # Alternative location
                fix_dir = os.path.join(self.fsl_dir, "fix", "training_files")
                training_file = os.path.join(fix_dir, standard_datasets[training_data])
                if os.path.exists(training_file):
                    return training_file

            # Default to name (FIX will search its paths)
            return training_data
        else:
            # Custom training data path
            return training_data

    def _extract_features(self, melodic_dir: str) -> Dict[str, Any]:
        """Extract features for FIX classification."""
        features = {}

        try:
            # Run FIX feature extraction
            if self.fix_available:
                cmd = ["fix", "-f", melodic_dir]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    env={**os.environ, 'FSLDIR': self.fsl_dir}
                )

                if result.returncode == 0:
                    # Parse feature file
                    feature_file = Path(melodic_dir) / "fix" / "features.txt"
                    if feature_file.exists():
                        with open(feature_file, 'r') as f:
                            lines = f.readlines()
                            features["n_components"] = len(lines)
                            features["feature_file"] = str(feature_file)

                    logger.info(f"Extracted features for {features.get('n_components', 0)} components")
        except Exception as e:
            logger.warning(f"Feature extraction failed: {e}")

        return features

    def _train_classifier(
        self,
        feat_dirs: List[str],
        hand_labels: List[str],
        output_file: str
    ) -> bool:
        """Train new FIX classifier."""
        if not self.fix_available:
            logger.error("FIX not available for training")
            return False

        try:
            # Create training list file
            training_list = Path(output_file).parent / "training_list.txt"
            with open(training_list, 'w') as f:
                for feat_dir, labels in zip(feat_dirs, hand_labels):
                    f.write(f"{feat_dir} {labels}\n")

            # Run FIX training
            cmd = [
                "fix", "-t", str(training_list),
                "-o", output_file
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env={**os.environ, 'FSLDIR': self.fsl_dir}
            )

            if result.returncode == 0:
                logger.info(f"Successfully trained classifier: {output_file}")
                return True
            else:
                logger.error(f"Training failed: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Training error: {e}")
            return False

    def _apply_cleanup(
        self,
        feat_dir: str,
        training_data: str,
        threshold: float,
        motion_cleanup: bool = True,
        highpass: Optional[float] = None
    ) -> Dict[str, Any]:
        """Apply FIX cleanup to remove artifacts."""
        results = {}

        if not self.fix_available:
            # Generate command for manual execution
            cmd_parts = ["fix"]
            cmd_parts.extend([feat_dir, training_data, str(threshold)])

            if motion_cleanup:
                cmd_parts.append("-m")

            if highpass:
                cmd_parts.extend(["-h", str(highpass)])

            results["command"] = " ".join(cmd_parts)
            results["status"] = "command_generated"
            return results

        try:
            # Build FIX command
            cmd = ["fix", feat_dir, training_data, str(threshold)]

            if motion_cleanup:
                cmd.append("-m")

            if highpass:
                cmd.extend(["-h", str(highpass)])

            # Run FIX
            logger.info(f"Running FIX cleanup: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env={**os.environ, 'FSLDIR': self.fsl_dir}
            )

            if result.returncode == 0:
                results["status"] = "success"

                # Parse output for classification results
                if "classified as noise" in result.stdout:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if "classified as noise" in line:
                            # Extract component numbers
                            import re
                            noise_comps = re.findall(r'\d+', line)
                            results["noise_components"] = [int(c) for c in noise_comps]
                            results["n_noise"] = len(noise_comps)

                # Check for cleaned data
                cleaned_file = Path(feat_dir) / "filtered_func_data_clean.nii.gz"
                if cleaned_file.exists():
                    results["cleaned_data"] = str(cleaned_file)

                logger.info(f"FIX cleanup successful: {results.get('n_noise', 0)} noise components removed")
            else:
                results["status"] = "failed"
                results["error"] = result.stderr
                logger.error(f"FIX cleanup failed: {result.stderr}")

        except Exception as e:
            results["status"] = "error"
            results["error"] = str(e)
            logger.error(f"FIX execution error: {e}")

        return results

    def _run(
        self,
        feat_dir: str,
        training_data: str = "Standard",
        threshold: float = 20.0,
        output_dir: Optional[str] = None,
        motion_cleanup: bool = True,
        highpass: Optional[float] = None,
        train_mode: bool = False,
        hand_labels_file: Optional[str] = None,
        feature_extraction: bool = True,
        multi_run_mode: bool = False,
        leave_one_out: bool = False,
        use_gpu: bool = False,
        n_threads: Optional[int] = None,
        **kwargs
    ) -> ToolResult:
        """Execute FSL FIX artifact removal."""
        try:
            # Validate FEAT directory
            valid, melodic_dir = self._validate_feat_dir(feat_dir)
            if not valid:
                return ToolResult(
                    status="error",
                    error=melodic_dir,  # Contains error message
                    data={}
                )

            # Set output directory
            if not output_dir:
                output_dir = Path(feat_dir) / "fix_output"
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Initialize results
            results = {
                "feat_dir": feat_dir,
                "melodic_dir": melodic_dir,
                "threshold": threshold,
                "training_data": training_data
            }

            # Training mode
            if train_mode:
                if not hand_labels_file:
                    return ToolResult(
                        status="error",
                        error="Hand labels file required for training mode",
                        data={}
                    )

                # Load hand labels
                with open(hand_labels_file, 'r') as f:
                    hand_labels = f.read().strip()

                # Train classifier
                training_output = output_path / f"custom_training_{Path(feat_dir).name}.RData"
                success = self._train_classifier(
                    [feat_dir],
                    [hand_labels],
                    str(training_output)
                )

                if success:
                    results["training_file"] = str(training_output)
                    results["mode"] = "training"

                    return ToolResult(
                        status="success",
                        data={
                            "outputs": results,
                            "message": f"Successfully trained FIX classifier: {training_output}"
                        }
                    )
                else:
                    return ToolResult(
                        status="error",
                        error="Failed to train FIX classifier",
                        data={}
                    )

            # Feature extraction
            if feature_extraction:
                features = self._extract_features(melodic_dir)
                results["features"] = features

            # Get training data path
            training_path = self._get_training_data_path(training_data)

            # Apply FIX cleanup
            cleanup_results = self._apply_cleanup(
                feat_dir,
                training_path,
                threshold,
                motion_cleanup,
                highpass
            )

            results.update(cleanup_results)

            # Generate report
            report = {
                "feat_directory": feat_dir,
                "training_dataset": training_data,
                "threshold": threshold,
                "motion_cleanup": motion_cleanup,
                "highpass_filter": highpass,
                "results": cleanup_results
            }

            # Save report
            report_file = output_path / "fix_report.json"
            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2)

            # Determine status
            if cleanup_results.get("status") == "success":
                return ToolResult(
                    status="success",
                    data={
                        "outputs": {
                            "cleaned_data": cleanup_results.get("cleaned_data"),
                            "report": str(report_file),
                            "noise_components": cleanup_results.get("noise_components", [])
                        },
                        "statistics": {
                            "n_noise_components": cleanup_results.get("n_noise", 0),
                            "threshold_used": threshold
                        },
                        "message": f"FIX cleanup completed: {cleanup_results.get('n_noise', 0)} noise components removed"
                    }
                )
            elif cleanup_results.get("status") == "command_generated":
                return ToolResult(
                    status="success",
                    data={
                        "command": cleanup_results["command"],
                        "message": "FIX command generated (FSL not available for execution)"
                    }
                )
            else:
                return ToolResult(
                    status="error",
                    error=cleanup_results.get("error", "FIX cleanup failed"),
                    data=results
                )

        except Exception as e:
            logger.error(f"FIX processing failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )


class FSLFIXMultiRunTool(NeuroToolWrapper):
    """FSL FIX for multiple runs/sessions."""

    def __init__(self):
        """Initialize multi-run FIX tool."""
        super().__init__()
        self.base_tool = FSLFIXTool()

    def get_tool_name(self) -> str:
        return "fsl_fix_multirun"

    def get_tool_description(self) -> str:
        return (
            "FSL FIX multi-run mode for processing multiple fMRI sessions together. "
            "Applies consistent artifact removal across all runs using the same "
            "classifier and threshold settings."
        )

    def get_args_schema(self):
        class MultiRunArgs(FSLFIXArgs):
            feat_dirs: List[str] = Field(
                description="List of FEAT directories to process together"
            )
            feat_dir: Optional[str] = Field(
                default=None,
                description="Not used in multi-run mode"
            )

        return MultiRunArgs

    def _run(
        self,
        feat_dirs: List[str],
        training_data: str = "Standard",
        threshold: float = 20.0,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Execute multi-run FIX processing."""
        try:
            if not output_dir:
                output_dir = Path(feat_dirs[0]).parent / "fix_multirun_output"
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            all_results = []
            all_noise_components = []

            # Process each run
            for i, feat_dir in enumerate(feat_dirs):
                logger.info(f"Processing run {i+1}/{len(feat_dirs)}: {feat_dir}")

                # Run FIX on this run
                result = self.base_tool._run(
                    feat_dir=feat_dir,
                    training_data=training_data,
                    threshold=threshold,
                    output_dir=str(output_path / f"run_{i:03d}"),
                    **kwargs
                )

                if result.status == "success":
                    all_results.append(result.data)
                    if "outputs" in result.data and "noise_components" in result.data["outputs"]:
                        all_noise_components.append(result.data["outputs"]["noise_components"])
                else:
                    logger.warning(f"Failed to process run {i+1}: {result.error}")

            # Generate summary report
            summary = {
                "n_runs": len(feat_dirs),
                "n_processed": len(all_results),
                "training_data": training_data,
                "threshold": threshold,
                "runs": all_results
            }

            summary_file = output_path / "multirun_summary.json"
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2)

            return ToolResult(
                status="success" if all_results else "error",
                data={
                    "outputs": {
                        "summary": str(summary_file),
                        "n_runs_processed": len(all_results),
                        "output_dir": str(output_path)
                    },
                    "message": f"Processed {len(all_results)}/{len(feat_dirs)} runs successfully"
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )


class FSLFIXTools:
    """Collection of FSL FIX tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all FSL FIX tools."""
        return [
            FSLFIXNiWrapTool(),
            FSLFIXTool(),
            FSLFIXMultiRunTool(),
        ]
