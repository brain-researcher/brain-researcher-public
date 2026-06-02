"""Brain Researcher SDK — thin Python client for MCP neuroimaging tools.

Quick start in a Marimo notebook::

    import brain_researcher.sdk as br

    client = br.connect()
    tools = br.search("skull stripping")
    recipe = br.recipe("fsl.bet", {"input": "t1.nii.gz"})
    kg_hits = br.call("kg_search_nodes", {"query": "working memory"})
"""

from brain_researcher.sdk import display, job_registry
from brain_researcher.sdk.chat import ChatResponse, chat
from brain_researcher.sdk.client import BRClient, connect
from brain_researcher.sdk.models import JobHandle, RunHandle, ToolCard, ToolResult

__all__ = [
    "connect",
    "BRClient",
    "ToolCard",
    "ToolResult",
    "JobHandle",
    "RunHandle",
    "ChatResponse",
    "chat",
    "display",
    "job_registry",
    "call",
    "attach_run",
]


def search(query: str, **kwargs) -> list[ToolCard]:
    """Shortcut: ``connect().search(query, **kwargs)``."""
    return connect().search(query, **kwargs)


def execute(tool_id: str, params=None, **kwargs) -> ToolResult | JobHandle:
    """Shortcut: ``connect().execute(tool_id, params, **kwargs)``."""
    return connect().execute(tool_id, params, **kwargs)


def recipe(tool_id: str, params=None, **kwargs) -> dict:
    """Shortcut: ``connect().recipe(tool_id, params, **kwargs)``."""
    return connect().recipe(tool_id, params, **kwargs)


def call(name: str, params=None) -> dict:
    """Shortcut: ``connect().call(name, params)``."""
    return connect().call(name, params)


def attach_run(run_id: str) -> RunHandle:
    """Shortcut: ``connect().attach_run(run_id)``."""
    return connect().attach_run(run_id)
