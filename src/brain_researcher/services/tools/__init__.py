"""Unified tools package for Brain Researcher.

This package provides a single, consistent interface for all neuroimaging tools
used by the agent, CLI, and other services. It unifies:
- NiWrap tools (~1900 Boutiques-based neuroimaging tools)
- Pipeline tools (fMRIPrep, FitLins, QSIPrep)
- Modality-specific tools (FSL, AFNI, FreeSurfer, ANTs)

Architecture:
    services/tools/
    ├── base.py           # NeuroTool base class
    ├── result.py         # ToolResult standard response
    ├── registry.py       # UnifiedToolRegistry facade
    ├── niwrap/           # NiWrap tools (Boutiques-based)
    ├── pipelines/        # Pipeline tools (fMRIPrep, etc.)
    ├── fsl/              # FSL tools (BET, FLIRT, FEAT, etc.)
    ├── afni/             # AFNI tools (ClustSim)
    ├── freesurfer/       # FreeSurfer tools (recon-all, etc.)
    ├── ants/             # ANTs tools (registration)
    └── executors/        # Container/subprocess execution

Usage:
    from brain_researcher.services.tools import UnifiedToolRegistry
    from brain_researcher.services.tools.niwrap import get_niwrap_tools
    from brain_researcher.services.tools.pipelines import PipelineTools
    from brain_researcher.services.tools.fsl import FSLTools
    from brain_researcher.services.tools.afni import AFNITools
    from brain_researcher.services.tools.freesurfer import FreeSurferTools
    from brain_researcher.services.tools.ants import ANTsTools

    # Get all tools as LangChain StructuredTools
    registry = UnifiedToolRegistry()
    tools = registry.get_all_tools()

    # Or get specific tool families
    pipeline_tools = PipelineTools.get_all_tools()
    fsl_tools = FSLTools.get_all_tools()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# These are safe to import eagerly (no circular dependencies)
from brain_researcher.services.tools.base import ExecutionMode, NeuroTool
from brain_researcher.services.tools.lookup_registry import register_tools_lookup
from brain_researcher.services.tools.registry import UnifiedToolRegistry
from brain_researcher.services.tools.result import ToolResult

# Lazy imports to avoid circular dependencies with tool subpackages
# These imports are deferred until actually accessed
if TYPE_CHECKING:
    from brain_researcher.services.tools.afni import AFNITools
    from brain_researcher.services.tools.ants import ANTsTools
    from brain_researcher.services.tools.freesurfer import FreeSurferTools
    from brain_researcher.services.tools.fsl import FSLTools
    from brain_researcher.services.tools.pipelines import PipelineTools


def __getattr__(name: str):
    """Lazy import handler to avoid circular imports with tool subpackages."""
    if name == "PipelineTools":
        from brain_researcher.services.tools.pipelines import PipelineTools

        return PipelineTools
    elif name == "FSLTools":
        from brain_researcher.services.tools.fsl import FSLTools

        return FSLTools
    elif name == "AFNITools":
        from brain_researcher.services.tools.afni import AFNITools

        return AFNITools
    elif name == "FreeSurferTools":
        from brain_researcher.services.tools.freesurfer import FreeSurferTools

        return FreeSurferTools
    elif name == "ANTsTools":
        from brain_researcher.services.tools.ants import ANTsTools

        return ANTsTools
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "NeuroTool",
    "ExecutionMode",
    "ToolResult",
    "UnifiedToolRegistry",
    "PipelineTools",
    "FSLTools",
    "AFNITools",
    "FreeSurferTools",
    "ANTsTools",
    "register_tools_lookup",
]

# Push the tool-spec lookup down to services/shared so the planner handoff can
# resolve allowed_phases/approval_level without importing the tools layer
# (breaks the shared -> tools back-edge). Cheap: the catalog load stays lazy.
# (Import is at the top with the other eager imports; this is the registration.)
register_tools_lookup()
