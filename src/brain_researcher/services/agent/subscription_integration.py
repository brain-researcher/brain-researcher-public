"""Backward-compatible re-export shim for the subscription integration.

The implementation now lives in
``brain_researcher.services.tools.subscription_integration``. It carries no
agent-layer dependencies and is instantiated by ``tools.tool_registry``;
relocating it to the tools layer removes a ``tools -> agent`` import back-edge.
Importing it here (``services.agent`` -> ``services.tools``) is a forward,
layer-respecting dependency. Existing callers that import from
``brain_researcher.services.agent.subscription_integration`` continue to work
unchanged.
"""

from __future__ import annotations

from brain_researcher.services.tools.subscription_integration import (  # noqa: F401
    AgentNotification,
    AgentNotificationType,
    AgentSubscriptionManager,
    MockWebSocket,
    setup_agent_subscriptions,
    subscribe_agent_to_analysis_events,
)

__all__ = [
    "AgentNotification",
    "AgentNotificationType",
    "AgentSubscriptionManager",
    "MockWebSocket",
    "setup_agent_subscriptions",
    "subscribe_agent_to_analysis_events",
]
