"""Unified AFNI tools package.

This package provides AFNI tools conforming to the NeuroTool interface.
All tools delegate to existing agent tool implementations to avoid duplication.
"""
from typing import List

from brain_researcher.services.tools.base import NeuroTool
from brain_researcher.services.tools.afni.clustsim import AFNIClustSimPipeline


class AFNITools:
    """Collection of all AFNI tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroTool]:
        """Get all AFNI tools as NeuroTool instances.

        Returns:
            List of NeuroTool instances for all AFNI tools.
        """
        return [
            AFNIClustSimPipeline(),
        ]


__all__ = [
    "AFNITools",
    "AFNIClustSimPipeline",
]
