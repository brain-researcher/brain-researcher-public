"""Helpers for streaming long-running command output back to the orchestrator.

Implementation relocated to ``services/shared/toolsagent_command_execution`` so
that the lower ``services/tools`` layer can depend on the emitter without a
tools -> agent back-edge. This module re-exports ``JobLogEmitter`` for callers.
"""

from __future__ import annotations

from brain_researcher.services.shared.toolsagent_command_execution import (
    JobLogEmitter,
)

__all__ = ["JobLogEmitter"]
