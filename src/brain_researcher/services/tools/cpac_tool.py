"""
C-PAC (Configurable Pipeline for the Analysis of Connectomes) implementation for Brain Researcher.

Implements C-PAC pipeline for comprehensive fMRI preprocessing and analysis.
"""

import logging
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class CPACPipelineArgs(BaseModel):
    """Arguments for C-PAC pipeline execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    bids_dir: str = Field(description="Path to BIDS dataset directory")
    output_dir: str = Field(description="Path to output directory")
    analysis_level: str = Field(
        default="participant",
        description="Level of analysis (participant, group, test_config)",
    )
    participant_label: list[str] | None = Field(
        default=None, description="List of participant labels to process"
    )
    pipeline_file: str | None = Field(
        default=None, description="Path to custom pipeline configuration YAML file"
    )
    preconfig: str | None = Field(
        default="default",
        description="Preconfigured pipeline to use (default, fmriprep-options, ndmg, etc.)",
    )
    skip_bids_validator: bool = Field(
        default=False, description="Skip BIDS dataset validation"
    )
    n_cpus: int | None = Field(default=None, description="Number of CPUs to use")
    mem_gb: float | None = Field(
        default=None, description="Maximum memory to use in GB"
    )
    save_working_dir: bool = Field(
        default=False, description="Save working directory for debugging"
    )


class CPACTool(NeuroToolWrapper):
    """C-PAC pipeline tool."""

    def __init__(self):
        """Initialize C-PAC tool."""
        super().__init__()
        self._check_cpac()

    def _check_cpac(self):
        """Check C-PAC availability via container."""
        self.cpac_available = False
        self.cpac_container = None

        # Check for Singularity/Apptainer
        for cmd in ["apptainer", "singularity"]:
            if subprocess.run(["which", cmd], capture_output=True).returncode == 0:
                self.container_cmd = cmd
                break
        else:
            logger.warning("No container runtime found (apptainer/singularity)")
            self.container_cmd = None

        # Check for Docker as fallback
        if not self.container_cmd:
            if subprocess.run(["which", "docker"], capture_output=True).returncode == 0:
                self.container_cmd = "docker"
                self.cpac_image = "fcpindi/c-pac:latest"
                self.cpac_available = True
                logger.info("C-PAC available via Docker")
            else:
                logger.warning("C-PAC not available - no container runtime found")
        else:
            # Check for local C-PAC singularity image
            cpac_sif = Path("/opt/containers/cpac_latest.sif")
            if cpac_sif.exists():
                self.cpac_container = str(cpac_sif)
                self.cpac_available = True
                logger.info(f"C-PAC available via {self.container_cmd}")
            else:
                logger.info("C-PAC container not found locally, will attempt to pull")
                self.cpac_available = True  # Will pull on first run

    def get_tool_name(self) -> str:
        return "cpac_pipeline"

    def get_tool_description(self) -> str:
        return (
            "C-PAC (Configurable Pipeline for the Analysis of Connectomes) for "
            "comprehensive fMRI preprocessing and analysis. Supports anatomical "
            "preprocessing, functional preprocessing, nuisance regression, and "
            "various connectivity analyses."
        )

    def get_args_schema(self):
        return CPACPipelineArgs

    def _run(
        self,
        bids_dir: str,
        output_dir: str,
        analysis_level: str = "participant",
        participant_label: list[str] | None = None,
        pipeline_file: str | None = None,
        preconfig: str | None = "default",
        skip_bids_validator: bool = False,
        n_cpus: int | None = None,
        mem_gb: float | None = None,
        save_working_dir: bool = False,
        **kwargs,
    ) -> ToolResult:
        """Execute C-PAC pipeline."""
        try:
            if not self.cpac_available:
                return ToolResult(
                    status="error",
                    error="C-PAC not available - no container runtime found",
                    data={},
                )

            # Validate inputs
            if not Path(bids_dir).exists():
                return ToolResult(
                    status="error",
                    error=f"BIDS directory not found: {bids_dir}",
                    data={},
                )

            # Create output directory
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Build C-PAC command
            if self.container_cmd == "docker":
                cmd = self._build_docker_command(
                    bids_dir,
                    output_dir,
                    analysis_level,
                    participant_label,
                    pipeline_file,
                    preconfig,
                    skip_bids_validator,
                    n_cpus,
                    mem_gb,
                    save_working_dir,
                )
            else:
                cmd = self._build_singularity_command(
                    bids_dir,
                    output_dir,
                    analysis_level,
                    participant_label,
                    pipeline_file,
                    preconfig,
                    skip_bids_validator,
                    n_cpus,
                    mem_gb,
                    save_working_dir,
                )

            logger.info(f"Running C-PAC command: {' '.join(cmd)}")

            # Execute C-PAC pipeline
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                # Parse outputs
                outputs = self._parse_outputs(output_dir, participant_label)

                return ToolResult(
                    status="success",
                    data={
                        "command": " ".join(cmd),
                        "output_dir": output_dir,
                        "outputs": outputs,
                        "message": "C-PAC pipeline completed successfully",
                    },
                )
            else:
                return ToolResult(
                    status="error",
                    error=f"C-PAC pipeline failed: {result.stderr}",
                    data={"command": " ".join(cmd)},
                )

        except Exception as e:
            logger.error(f"C-PAC pipeline failed: {str(e)}")
            return ToolResult(status="error", error=str(e), data={})

    def _build_docker_command(
        self,
        bids_dir: str,
        output_dir: str,
        analysis_level: str,
        participant_label: list[str] | None,
        pipeline_file: str | None,
        preconfig: str,
        skip_bids_validator: bool,
        n_cpus: int | None,
        mem_gb: float | None,
        save_working_dir: bool,
    ) -> list[str]:
        """Build Docker command for C-PAC."""
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{bids_dir}:/bids_dataset:ro",
            "-v",
            f"{output_dir}:/outputs",
        ]

        if pipeline_file:
            pipeline_dir = str(Path(pipeline_file).parent)
            cmd.extend(["-v", f"{pipeline_dir}:/pipeline:ro"])

        cmd.extend([self.cpac_image, "/bids_dataset", "/outputs", analysis_level])

        if participant_label:
            cmd.extend(["--participant_label"] + participant_label)

        if pipeline_file:
            cmd.extend(["--pipeline_file", f"/pipeline/{Path(pipeline_file).name}"])
        elif preconfig != "default":
            cmd.extend(["--preconfig", preconfig])

        if skip_bids_validator:
            cmd.append("--skip_bids_validator")

        if n_cpus:
            cmd.extend(["--n_cpus", str(n_cpus)])

        if mem_gb:
            cmd.extend(["--mem_gb", str(mem_gb)])

        if save_working_dir:
            cmd.append("--save_working_dir")

        return cmd

    def _build_singularity_command(
        self,
        bids_dir: str,
        output_dir: str,
        analysis_level: str,
        participant_label: list[str] | None,
        pipeline_file: str | None,
        preconfig: str,
        skip_bids_validator: bool,
        n_cpus: int | None,
        mem_gb: float | None,
        save_working_dir: bool,
    ) -> list[str]:
        """Build Singularity/Apptainer command for C-PAC."""
        # Pull container if needed
        if not self.cpac_container:
            self.cpac_container = "/tmp/cpac_latest.sif"
            pull_cmd = [
                self.container_cmd,
                "pull",
                self.cpac_container,
                "docker://fcpindi/c-pac:latest",
            ]
            logger.info(f"Pulling C-PAC container: {' '.join(pull_cmd)}")
            subprocess.run(pull_cmd, check=False)

        cmd = [
            self.container_cmd,
            "run",
            "--cleanenv",
            "-B",
            f"{bids_dir}:/bids_dataset:ro",
            "-B",
            f"{output_dir}:/outputs",
        ]

        if pipeline_file:
            pipeline_dir = str(Path(pipeline_file).parent)
            cmd.extend(["-B", f"{pipeline_dir}:/pipeline:ro"])

        cmd.extend([self.cpac_container, "/bids_dataset", "/outputs", analysis_level])

        if participant_label:
            cmd.extend(["--participant_label"] + participant_label)

        if pipeline_file:
            cmd.extend(["--pipeline_file", f"/pipeline/{Path(pipeline_file).name}"])
        elif preconfig != "default":
            cmd.extend(["--preconfig", preconfig])

        if skip_bids_validator:
            cmd.append("--skip_bids_validator")

        if n_cpus:
            cmd.extend(["--n_cpus", str(n_cpus)])

        if mem_gb:
            cmd.extend(["--mem_gb", str(mem_gb)])

        if save_working_dir:
            cmd.append("--save_working_dir")

        return cmd

    def _parse_outputs(
        self, output_dir: str, participant_label: list[str] | None
    ) -> dict:
        """Parse C-PAC output structure."""
        output_path = Path(output_dir)
        outputs = {"derivatives": [], "logs": [], "reports": []}

        # Check for derivatives
        derivatives_dir = output_path / "cpac_derivatives"
        if derivatives_dir.exists():
            for subdir in derivatives_dir.iterdir():
                if subdir.is_dir():
                    outputs["derivatives"].append(str(subdir))

        # Check for logs
        logs_dir = output_path / "logs"
        if logs_dir.exists():
            for log_file in logs_dir.glob("*.log"):
                outputs["logs"].append(str(log_file))

        # Check for QC reports
        qc_dir = output_path / "cpac_qc"
        if qc_dir.exists():
            for report in qc_dir.glob("*.html"):
                outputs["reports"].append(str(report))

        return outputs


class CPACTools:
    """Collection of C-PAC tools."""

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        """Get all C-PAC tools."""
        return [CPACTool()]
