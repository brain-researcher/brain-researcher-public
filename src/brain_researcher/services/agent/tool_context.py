"""Tool-context retrieval + registry helpers for the BR-KG agent web service.

Carved out of ``agent/web_service.py``: the helpers that build the relevant
tool-context string for a chat query (with a small in-process TTL cache), the
fallback tool registry, the contract tool retriever, and the legacy
tool-context path.

The TTL cache state (``_tool_context_cache`` / ``_tool_context_cache_time`` /
``_CACHE_TIMEOUT``) and the fallback registry (``_FALLBACK_TOOL_REGISTRY``) are
module-level state owned by this module (they are exclusive to these helpers).
The few web_service helpers/globals still needed (``_extract_keywords`` /
``get_agent`` / ``logger``) stay in ``web_service`` and are imported back lazily
inside the consuming functions (read at call time, so test patches of
``web_service.get_agent`` are honoured). Dependency is one-way
``web_service -> tool_context`` and cycle-free at module load. ``web_service``
re-exports the functions so the routes that delegate to them (simple_chat,
agent_plan_contract, agent_studio_plan) and the tests keep resolving.
"""

from __future__ import annotations

import os
import time

# --- tool-context cache state (carved with the retrieval helpers) ---
_tool_context_cache: dict = {}
_tool_context_cache_time = 0
_CACHE_TIMEOUT = 300  # 5 minutes
_FALLBACK_TOOL_REGISTRY = None


def _get_contract_tool_retriever():
    """Best-effort cached ToolRetriever for contract planning surfaces.

    Default to opt-in so read-only planning does not cold-start Neo4j-backed
    retrieval on every fresh MCP/client process unless explicitly requested.
    """
    from brain_researcher.services.agent.web_service import logger

    use_retriever = os.getenv("BR_USE_TOOL_RETRIEVER", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    if not use_retriever:
        return None

    try:
        from brain_researcher.services.agent.tool_retriever import ToolRetriever

        return ToolRetriever()
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Contract ToolRetriever init failed: %s", exc)
        return None


def _get_relevant_tool_context(
    query: str, max_tools: int = 15, allowed_tools: list[str] | None = None
) -> str:
    """
    Get relevant tool context for a query without executing tools.

    Args:
        query: User query to analyze
        max_tools: Maximum number of tools to include in context

    Returns:
        Formatted tool context string
    """
    from brain_researcher.services.agent.web_service import (
        _extract_keywords,
        get_agent,
        logger,
    )
    global _tool_context_cache, _tool_context_cache_time

    try:
        # Check cache first (tool list doesn't change frequently)
        current_time = time.time()
        if (
            current_time - _tool_context_cache_time < _CACHE_TIMEOUT
            and _tool_context_cache
        ):
            return _build_context_for_query(
                query, _tool_context_cache, max_tools, allowed_tools
            )

        # Initialize agent if needed and get tools
        agent = get_agent()
        all_tools = agent.tool_registry.get_all_tools()

        # Build tool summary cache
        tool_summaries = []
        for tool in all_tools:
            try:
                name = tool.get_tool_name()
                desc = (
                    tool.get_tool_description()
                    if hasattr(tool, "get_tool_description")
                    else "No description available"
                )
                category = getattr(tool, "CATEGORY", "general")

                tool_summaries.append(
                    {
                        "name": name,
                        "description": desc[:200],  # Limit description length
                        "category": category,
                        "keywords": _extract_keywords(name, desc, category),
                    }
                )
            except Exception as e:
                logger.debug(
                    f"Error processing tool {getattr(tool, 'name', 'unknown')}: {e}"
                )
                continue

        # Cache the summaries
        _tool_context_cache = tool_summaries
        _tool_context_cache_time = current_time

        return _build_context_for_query(query, tool_summaries, max_tools, allowed_tools)

    except Exception as e:
        logger.warning(f"Failed to get tool context: {e}")
        return ""


def _build_context_for_query(
    query: str,
    tool_summaries: list,
    max_tools: int,
    allowed_tools: list[str] | None = None,
) -> str:
    """Build relevant tool context based on query analysis."""
    query_lower = query.lower()
    summaries = tool_summaries
    if allowed_tools:
        allowed = {name.lower() for name in allowed_tools}
        filtered = [
            tool for tool in tool_summaries if tool.get("name", "").lower() in allowed
        ]
        if filtered:
            summaries = filtered

    # Check if query is asking about tools in general
    tool_inquiry_terms = [
        "tool",
        "tools",
        "available",
        "list",
        "what can",
        "help",
        "options",
    ]
    is_general_tool_query = any(term in query_lower for term in tool_inquiry_terms)

    if is_general_tool_query or "tool" in query_lower:
        # For general tool queries, provide a comprehensive overview
        total_tools = len(summaries)

        # Categorize tools
        categories = {}
        for tool in summaries:
            cat = tool["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(tool)

        context_parts = [
            f"I'm a neuroimaging analysis assistant with access to {total_tools} specialized tools.",
            "",
            "Tool Categories:",
        ]

        # Show top categories with examples
        for cat, tools in sorted(
            categories.items(), key=lambda x: len(x[1]), reverse=True
        )[:8]:
            if cat and cat != "general":
                example_tools = [t["name"] for t in tools[:3]]
                context_parts.append(
                    f"- {cat.title()}: {len(tools)} tools ({', '.join(example_tools)})"
                )

        context_parts.extend(
            [
                "",
                "Key Capabilities:",
                "- fMRI preprocessing and GLM analysis (FSL, fMRIPrep, Nilearn)",
                "- Structural analysis and registration (ANTs, FreeSurfer)",
                "- Connectivity and network analysis",
                "- Statistical modeling and visualization",
                "- BIDS data handling and quality control",
                "",
                "Ask me about specific analyses or tools you need!",
            ]
        )

        return "\\n".join(context_parts)

    else:
        # For specific queries, find relevant tools by keyword matching
        scored_tools = []
        for tool in summaries:
            score = 0

            # Score based on keyword matches
            for keyword in tool["keywords"]:
                if keyword in query_lower:
                    score += 5

            # Score based on name/description similarity
            query_words = query_lower.split()
            tool_text = f"{tool['name']} {tool['description']}".lower()
            for word in query_words:
                if len(word) > 3 and word in tool_text:
                    score += 2

            if score > 0:
                scored_tools.append((score, tool))

        # Sort by relevance and take top tools
        scored_tools.sort(key=lambda x: x[0], reverse=True)
        relevant_tools = [tool for _, tool in scored_tools[:max_tools]]

        if relevant_tools:
            context_parts = [
                f"I have {len(summaries)} neuroimaging tools available. Here are the most relevant:"
            ]

            for tool in relevant_tools:
                context_parts.append(f"- {tool['name']}: {tool['description'][:100]}")

            context_parts.append("")
            context_parts.append(
                "I can provide more details about any of these tools or help with your analysis."
            )

            return "\\n".join(context_parts)

        else:
            # No specific matches - provide general context
            return (
                f"I'm a neuroimaging assistant with {len(summaries)} analysis tools including "
                "fMRI preprocessing, statistical modeling, connectivity analysis, and visualization."
            )


def _get_fallback_tool_registry():
    """Best-effort access to the agent tool registry for signature checks."""
    from brain_researcher.services.agent.web_service import get_agent
    global _FALLBACK_TOOL_REGISTRY
    if _FALLBACK_TOOL_REGISTRY is None:
        try:
            _FALLBACK_TOOL_REGISTRY = get_agent().tool_registry
        except Exception:
            _FALLBACK_TOOL_REGISTRY = None
    return _FALLBACK_TOOL_REGISTRY


def _get_required_params(tool_name: str) -> set[str] | None:
    registry = _get_fallback_tool_registry()
    if not registry:
        return None
    tool = registry.get_tool(tool_name)
    if not tool:
        return None
    schema = getattr(tool, "get_args_schema", lambda: None)()
    if not schema or not isinstance(schema, type):
        return None

    required: set[str] = set()
    if hasattr(schema, "model_fields"):  # Pydantic v2
        for name, field in schema.model_fields.items():
            is_req = getattr(field, "is_required", None)
            required_flag = is_req() if callable(is_req) else bool(is_req)
            if required_flag:
                required.add(name)
    else:  # Pydantic v1
        for name, field in getattr(schema, "__fields__", {}).items():
            if getattr(field, "required", False):
                required.add(name)
    return required


def _get_relevant_tool_context_legacy(query: str, max_tools: int = 15) -> str:
    """
    Get relevant tool context for a query.

    Args:
        query: User query
        max_tools: Maximum number of tools to include

    Returns:
        Formatted tool context string or empty string if no tools
    """
    from brain_researcher.services.agent.web_service import get_agent, logger
    try:
        # Initialize agent to get tools
        agent = get_agent()
        all_tools = agent.tool_registry.get_all_tools()

        if not all_tools:
            return ""

        # Check if this is a general "list tools" query
        query_lower = query.lower()
        is_list_query = any(
            phrase in query_lower
            for phrase in [
                "list tools",
                "available tools",
                "what tools",
                "show tools",
                "list available",
                "what can you do",
                "capabilities",
            ]
        )

        if is_list_query:
            # Provide comprehensive tool overview
            tool_categories = {}
            for tool in all_tools:
                category = getattr(tool, "CATEGORY", "General")
                if category not in tool_categories:
                    tool_categories[category] = []
                tool_categories[category].append(tool.get_tool_name())

            context = f"You are a neuroimaging analysis assistant with access to {len(all_tools)} specialized tools.\n\n"
            context += "Available tool categories:\n"

            for category, tools in sorted(tool_categories.items())[
                :5
            ]:  # Top 5 categories
                example_tools = ", ".join(tools[:3])  # First 3 tools as examples
                context += f"- {category}: {len(tools)} tools (e.g., {example_tools})\n"

            context += "\nKey capabilities include:\n"
            context += (
                "- fMRI preprocessing and GLM analysis (fMRIPrep, FSL FEAT, SPM12)\n"
            )
            context += (
                "- Structural analysis and registration (FreeSurfer, ANTs, FSL BET)\n"
            )
            context += "- Connectivity and network analysis (Nilearn, CONN, MNE)\n"
            context += "- Statistical modeling and visualization\n"
            context += "- Quality control and validation\n"

            return context

        # For specific queries, find relevant tools
        tool_scores = []
        keywords = query_lower.split()

        for tool in all_tools:
            name = tool.get_tool_name().lower()
            desc = (
                tool.get_tool_description().lower()
                if hasattr(tool, "get_tool_description")
                else ""
            )

            score = 0
            # Score based on keyword matches
            for keyword in keywords:
                if len(keyword) > 2:  # Skip short words
                    if keyword in name:
                        score += 10
                    if keyword in desc:
                        score += 5

            if score > 0:
                tool_scores.append((score, tool))

        # Sort by relevance and take top tools
        tool_scores.sort(key=lambda x: x[0], reverse=True)
        relevant_tools = [tool for _, tool in tool_scores[:max_tools]]

        if not relevant_tools:
            # No specific tools found, provide general context
            return f"You are a neuroimaging analysis assistant with {len(all_tools)} tools available for various analyses."

        # Build context with relevant tools
        context = "You are a neuroimaging analysis assistant. Relevant tools for this query:\n"
        for tool in relevant_tools[:8]:  # Limit to 8 most relevant
            name = tool.get_tool_name()
            desc = (
                tool.get_tool_description()
                if hasattr(tool, "get_tool_description")
                else "Tool for neuroimaging analysis"
            )
            # Truncate description to save tokens
            desc = desc[:100] + "..." if len(desc) > 100 else desc
            context += f"- {name}: {desc}\n"

        return context

    except Exception as e:
        logger.warning(f"Failed to get tool context: {e}")
        return ""
