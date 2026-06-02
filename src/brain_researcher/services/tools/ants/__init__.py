"""Unified ANTs tools package.

This package provides ANTs tools conforming to the NeuroTool interface.
All tools delegate to existing agent tool implementations to avoid duplication.
"""

from typing import List

from brain_researcher.services.tools.ants.registration import ANTsRegistrationPipeline
from brain_researcher.services.tools.base import NeuroTool


class ANTsTools:
    """Collection of all ANTs tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroTool]:
        """Get all ANTs tools as NeuroTool instances.

        Returns:
            List of NeuroTool instances for all ANTs tools.
        """
        return [
            ANTsRegistrationPipeline(),
        ]


__all__ = [
    "ANTsTools",
    "ANTsRegistrationPipeline",
]
