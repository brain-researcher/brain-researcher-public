"""Unified FreeSurfer tools package.

This package provides FreeSurfer tools conforming to the NeuroTool interface.
All tools delegate to existing agent tool implementations to avoid duplication.
"""

from typing import List

from brain_researcher.services.tools.base import NeuroTool
from brain_researcher.services.tools.freesurfer.tools import (
    FreeSurferParcellationPipeline,
    FreeSurferQCPipeline,
    FreeSurferReconAllPipeline,
    FreeSurferVolumetricPipeline,
)


class FreeSurferTools:
    """Collection of all FreeSurfer tools."""

    @staticmethod
    def get_all_tools() -> list[NeuroTool]:
        """Get all FreeSurfer tools as NeuroTool instances.

        Returns:
            List of NeuroTool instances for all FreeSurfer tools.
        """
        return [
            FreeSurferReconAllPipeline(),
            FreeSurferParcellationPipeline(),
            FreeSurferVolumetricPipeline(),
            FreeSurferQCPipeline(),
        ]


__all__ = [
    "FreeSurferTools",
    "FreeSurferReconAllPipeline",
    "FreeSurferParcellationPipeline",
    "FreeSurferVolumetricPipeline",
    "FreeSurferQCPipeline",
]
