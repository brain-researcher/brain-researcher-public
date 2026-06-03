"""Unified FSL tools package.

This package provides FSL tools conforming to the NeuroTool interface.
All tools delegate to existing agent tool implementations to avoid duplication.
"""
from typing import List

from brain_researcher.services.tools.base import NeuroTool
from brain_researcher.services.tools.fsl.bet import FSLBETPipeline
from brain_researcher.services.tools.fsl.flirt import FSLFLIRTPipeline
from brain_researcher.services.tools.fsl.fnirt import FSLFNIRTPipeline
from brain_researcher.services.tools.fsl.feat import FSLFEATPipeline, FSLFEATGroupPipeline
from brain_researcher.services.tools.fsl.melodic import FSLMELODICPipeline
from brain_researcher.services.tools.fsl.bedpostx import FSLBEDPOSTXPipeline
from brain_researcher.services.tools.fsl.fix import FSLFIXPipeline, FSLFIXMultiRunPipeline
from brain_researcher.services.tools.fsl.palm import FSLPALMPipeline


class FSLTools:
    """Collection of all FSL tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroTool]:
        """Get all FSL tools as NeuroTool instances.

        Returns:
            List of NeuroTool instances for all FSL tools.
        """
        return [
            # Brain extraction
            FSLBETPipeline(),
            # Linear registration
            FSLFLIRTPipeline(),
            # Non-linear registration
            FSLFNIRTPipeline(),
            # GLM analysis
            FSLFEATPipeline(),
            FSLFEATGroupPipeline(),
            # ICA analysis
            FSLMELODICPipeline(),
            # Diffusion modeling
            FSLBEDPOSTXPipeline(),
            # ICA artifact removal
            FSLFIXPipeline(),
            FSLFIXMultiRunPipeline(),
            # Permutation testing
            FSLPALMPipeline(),
        ]


__all__ = [
    "FSLTools",
    "FSLBETPipeline",
    "FSLFLIRTPipeline",
    "FSLFNIRTPipeline",
    "FSLFEATPipeline",
    "FSLFEATGroupPipeline",
    "FSLMELODICPipeline",
    "FSLBEDPOSTXPipeline",
    "FSLFIXPipeline",
    "FSLFIXMultiRunPipeline",
    "FSLPALMPipeline",
]
