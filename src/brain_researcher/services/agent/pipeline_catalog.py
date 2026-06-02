"""Lightweight pipeline search over Neo4j for planner/routing use.

Implementation relocated to ``services/shared/toolsagent_pipeline_catalog`` so
the lower ``services/tools`` layer can depend on it without importing from
``services/agent``. This module re-exports the public API for existing callers.
"""

from __future__ import annotations

from brain_researcher.services.shared.toolsagent_pipeline_catalog import (
    format_pipeline_summary,
    search_pipelines,
)

__all__ = ["search_pipelines", "format_pipeline_summary"]
