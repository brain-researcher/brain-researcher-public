from __future__ import annotations

import os
from typing import Any, Dict, Tuple

from brain_researcher.services.agent.agent_factory import get_llm_agent


_MULTI_STEP_INDICATORS = [
    r"\band\s+then\b",
    r"\bthen\b",
    r"\bfollowed\s+by\b",
    r"\bafter\s+that\b",
    r"\bfirst\s*,.*\bthen\b",
]


def _assess_complexity(query: str) -> str:
    q = query.lower()
    import re

    multi = sum(1 for p in _MULTI_STEP_INDICATORS if re.search(p, q))
    word_count = len(query.split())
    if multi >= 2 or word_count > 50:
        return "complex"
    if multi >= 1 or word_count > 25:
        return "moderate"
    return "simple"


def run_unified_agent(
    query: str,
    *,
    tool_mode: str = "auto",  # "auto" | "required" | "none"
) -> Tuple[str, Dict[str, Any]]:
    """Execute the NeuroAgentLLM (same path as /act_llm).

    Returns text and a metadata dict containing tool calls and basic execution info.
    """

    agent = get_llm_agent(force_tool_mode=tool_mode)
    complexity = _assess_complexity(query)
    final_state = agent.run(query, complexity=complexity)

    text = agent.get_last_ai_message(final_state) or ""

    tool_calls = []
    artifacts = []
    from langchain_core.messages import AIMessage, ToolMessage
    import time
    import json as _json

    for msg in final_state.get("messages", []):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls or []:
                try:
                    if isinstance(tc, dict):
                        name = tc.get("name", "unknown")
                        args = tc.get("args", {})
                    else:
                        name = getattr(tc, "name", "unknown")
                        args = getattr(tc, "args", {})
                    tool_calls.append(
                        {
                            "name": name or "unknown",
                            "arguments": args or {},
                            "status": "called",
                        }
                    )
                except Exception as exc:  # pragma: no cover - best effort
                    tool_calls.append(
                        {
                            "name": "unknown",
                            "arguments": {},
                            "status": "error",
                            "error": f"parse_error: {exc}",
                        }
                    )
        elif isinstance(msg, ToolMessage):
            name = getattr(msg, "name", "tool")
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                try:
                    parsed = _json.loads(content)
                except Exception:
                    parsed = {"text": content}
            elif isinstance(content, dict):
                parsed = content
            else:
                parsed = {"text": str(content)}

            tool_calls.append({"name": name, "result": parsed, "status": "ok"})
            if isinstance(parsed, dict) and parsed.get("data"):
                artifacts.append(
                    {
                        "id": f"tool_{name}_{int(time.time())}",
                        "type": "tool_result",
                        "name": f"{name} output",
                        "data": parsed.get("data"),
                    }
                )

    model_name = os.environ.get("DEFAULT_LLM_MODEL", "deepseek-chat")
    if "gemini" in model_name.lower():
        provider = "gemini"
    elif "gpt" in model_name.lower():
        provider = "openai"
    elif "claude" in model_name.lower():
        provider = "anthropic"
    elif "deepseek" in model_name.lower():
        provider = "deepseek"
    else:
        provider = "unknown"

    return text, {
        "tool_calls": tool_calls,
        "artifacts": artifacts,
        "provider": provider,
        "model": model_name,
        "tool_mode": tool_mode,
        "complexity": complexity,
    }

