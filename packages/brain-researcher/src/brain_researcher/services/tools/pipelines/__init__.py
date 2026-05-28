"""Unified pipeline tools package.

This package provides a consistent interface for major neuroimaging pipelines:
- fMRIPrep: Comprehensive fMRI preprocessing
- FitLins: BIDS GLM analysis
- QSIPrep: Diffusion MRI preprocessing

Each pipeline tool conforms to the NeuroTool interface and delegates to
the existing agent tool implementations.

Usage:
    from brain_researcher.services.tools.pipelines import PipelineTools

    # Get all pipeline tools as NeuroTool instances
    tools = PipelineTools.get_all_tools()

    # Or get specific tools
    from brain_researcher.services.tools.pipelines.fmriprep import FMRIPrepPipeline
"""
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from brain_researcher.services.tools.base import NeuroTool


class PipelineTools:
    """Collection of pipeline tools."""

    @staticmethod
    def get_all_tools() -> List["NeuroTool"]:
        """Get all pipeline tools as NeuroTool instances.

        Returns:
            List of NeuroTool instances for all available pipelines.
        """
        # Import here to avoid circular imports
        from brain_researcher.services.tools.pipelines.fmriprep import (
            FMRIPrepPipeline,
            FMRIPrepQCPipeline,
        )
        from brain_researcher.services.tools.pipelines.fitlins import FitLinsPipeline
        from brain_researcher.services.tools.pipelines.qsiprep import (
            QSIPrepPipeline,
            QSIPrepReconPipeline,
            QSIPrepQCPipeline,
        )

        return [
            FMRIPrepPipeline(),
            FMRIPrepQCPipeline(),
            FitLinsPipeline(),
            QSIPrepPipeline(),
            QSIPrepReconPipeline(),
            QSIPrepQCPipeline(),
        ]


# Export unified pipeline parameters
from brain_researcher.services.tools.pipelines.params import (
    # FitLins
    FitLinsParameters,
    build_fitlins_command,
    build_fitlins_env,
    fitlins_from_payload,
    # fMRIPrep
    FMRIPrepParameters,
    build_fmriprep_command,
    build_fmriprep_env,
    fmriprep_from_payload,
    # QSIPrep
    QSIPrepParameters,
    build_qsiprep_command,
    build_qsiprep_env,
    qsiprep_from_payload,
    # MRIQC
    MRIQCParameters,
    build_mriqc_command,
    build_mriqc_env,
    mriqc_from_payload,
)

# Also export pipeline execution helpers
from brain_researcher.services.tools.pipelines.helpers import (
    run_fmriprep,
    run_fmriprep_from_dict,
    run_fitlins,
    run_fitlins_from_dict,
    run_qsiprep,
    run_qsiprep_from_dict,
    run_mriqc,
    run_mriqc_from_dict,
    FMRIPREP_IMAGE,
    FITLINS_IMAGE,
    QSIPREP_IMAGE,
    MRIQC_IMAGE,
)

# Backward compatibility alias
FitLinsConfig = FitLinsParameters

__all__ = [
    "PipelineTools",
    # Unified parameters
    "FitLinsParameters",
    "build_fitlins_command",
    "build_fitlins_env",
    "fitlins_from_payload",
    "FMRIPrepParameters",
    "build_fmriprep_command",
    "build_fmriprep_env",
    "fmriprep_from_payload",
    "QSIPrepParameters",
    "build_qsiprep_command",
    "build_qsiprep_env",
    "qsiprep_from_payload",
    "MRIQCParameters",
    "build_mriqc_command",
    "build_mriqc_env",
    "mriqc_from_payload",
    # Pipeline execution helpers
    "run_fmriprep",
    "run_fmriprep_from_dict",
    "run_fitlins",
    "run_fitlins_from_dict",
    "run_qsiprep",
    "run_qsiprep_from_dict",
    "run_mriqc",
    "run_mriqc_from_dict",
    # Container images
    "FMRIPREP_IMAGE",
    "FITLINS_IMAGE",
    "QSIPREP_IMAGE",
    "MRIQC_IMAGE",
    # Backward compatibility
    "FitLinsConfig",
]
