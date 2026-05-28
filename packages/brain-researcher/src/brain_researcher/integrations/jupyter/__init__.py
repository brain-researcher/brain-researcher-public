"""Jupyter integration surfaces for Brain Researcher."""

from .bridge import (
    BridgeSessionState,
    BridgeSessionStore,
    NotebookAssistantBridgeSettings,
    ProxyHttpResponse,
    build_bootstrap_payload,
    build_proxy_request_headers,
    get_bridge_session_store,
    issue_bridge_session,
    proxy_mcp_request,
)
from .runtime_client import (
    JupyterExecutionResult,
    JupyterRuntimeHandle,
    JupyterRuntimeTarget,
    create_session,
    ensure_session,
    execute_python_code,
    get_session,
    interrupt_kernel,
)

__all__ = [
    "BridgeSessionState",
    "BridgeSessionStore",
    "JupyterExecutionResult",
    "JupyterRuntimeHandle",
    "JupyterRuntimeTarget",
    "NotebookAssistantBridgeSettings",
    "ProxyHttpResponse",
    "build_bootstrap_payload",
    "build_proxy_request_headers",
    "create_session",
    "ensure_session",
    "execute_python_code",
    "get_bridge_session_store",
    "get_session",
    "interrupt_kernel",
    "issue_bridge_session",
    "proxy_mcp_request",
]
