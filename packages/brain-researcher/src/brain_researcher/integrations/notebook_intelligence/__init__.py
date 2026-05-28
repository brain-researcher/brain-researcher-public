"""Notebook Intelligence integration surfaces for Brain Researcher."""

from ._compat import NOTEBOOK_INTELLIGENCE_AVAILABLE, NOTEBOOK_INTELLIGENCE_IMPORT_ERROR
from .config import (
    BrainResearcherNotebookIntelligenceSettings,
    NotebookIntelligencePaths,
    build_extension_metadata,
    build_managed_mcp_server_config,
    build_user_config,
    build_user_mcp_config,
    resolve_notebook_intelligence_paths,
    write_extension_metadata,
    write_user_config,
    write_user_mcp_config,
)
from .extension import BrainResearcherNotebookIntelligenceExtension
from .participant import (
    BrainResearcherParticipant,
    build_brain_researcher_system_prompt,
)

__all__ = [
    "NOTEBOOK_INTELLIGENCE_AVAILABLE",
    "NOTEBOOK_INTELLIGENCE_IMPORT_ERROR",
    "BrainResearcherNotebookIntelligenceExtension",
    "BrainResearcherNotebookIntelligenceSettings",
    "BrainResearcherParticipant",
    "NotebookIntelligencePaths",
    "build_brain_researcher_system_prompt",
    "build_extension_metadata",
    "build_managed_mcp_server_config",
    "build_user_config",
    "build_user_mcp_config",
    "resolve_notebook_intelligence_paths",
    "write_extension_metadata",
    "write_user_config",
    "write_user_mcp_config",
]
