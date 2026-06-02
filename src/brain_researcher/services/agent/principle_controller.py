"""Backward-compatible re-export shim for the principle controller.

The implementation now lives in
``brain_researcher.services.shared.r2toolsagent_principle_controller`` so that
``services.tools`` can reuse it without creating a ``tools -> agent`` import
back-edge. Existing callers that import from
``brain_researcher.services.agent.principle_controller`` continue to work
unchanged.
"""

from __future__ import annotations

from brain_researcher.services.shared.r2toolsagent_principle_controller import (  # noqa: F401
    build_principle_session_key,
    initialize_principle_state,
    rerank_leverage_items,
    update_principle_state,
)

__all__ = [
    "build_principle_session_key",
    "initialize_principle_state",
    "rerank_leverage_items",
    "update_principle_state",
]
