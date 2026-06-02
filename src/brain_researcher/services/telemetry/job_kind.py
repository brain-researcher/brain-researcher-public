"""
Enumerations for orchestrator metrics job kinds.

These categories are intentionally low-cardinality so that Prometheus
dashboards and alerting rules remain stable as new tools/pipelines ship.
"""

from __future__ import annotations

from enum import Enum


class JobKind(str, Enum):
    """Stable job kind labels for orchestrator metrics."""

    GLM = "glm"
    CONNECTIVITY = "connectivity"
    PARCELLATION = "parcellation"
    REGISTRATION = "registration"
    QC = "qc"
    KG_INGEST = "kg_ingest"
    KG_QUERY = "kg_query"
    EMBEDDING = "embedding"
    RENDER_3D = "render_3d"
    FILE_IO = "file_io"
    PLANNER = "planner"
    AGENT_TOOL = "agent_tool"
    OTHER = "other"


__all__ = ["JobKind"]
