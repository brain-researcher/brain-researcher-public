"""/tools/* routes for the BR-KG agent web service.

Carved out of ``agent/web_service.py``: the tool detail / run / execute(_async)
/ status / list handlers. Registered via ``register(app)``; the rate-limited and
ttl-cached routes are wrapped with ``rate_limit`` / ``ttl_cache`` at registration
time (matching the original ``@app.route``-over-``@decorator`` stacking). Cycle
-free; web_service helpers are imported back lazily inside the handlers.
"""

from __future__ import annotations

import os
from datetime import datetime

from flask import jsonify, request

from brain_researcher.services.agent.tool_metadata_bridge import (
    get_example_payload,
    get_output_examples,
    get_resource_hints,
)


def tool_detail(name):
    """Return detailed schema for a specific tool."""
    from brain_researcher.services.agent.web_service import (
        create_error_response,
        get_agent,
        logger,
    )
    agent = get_agent()
    registry = agent.tool_registry

    tool = registry.get_tool(name)
    if not tool:
        return create_error_response("NOT_FOUND", f"Tool '{name}' not found", 404)

    # Get pydantic model if available
    args_model = getattr(tool, "args_model", None)
    schema = None
    if args_model:
        try:
            schema = args_model.schema() if hasattr(args_model, "schema") else None
        except Exception as e:
            logger.debug(f"Could not get schema for {name}: {e}")

    # Get example arguments
    example_args = getattr(tool, "example_args", None)
    if not example_args:
        # Provide some common examples
        if name == "glm_analysis":
            example_args = {
                "data_file": "/path/to/data.nii.gz",
                "design_matrix": "/path/to/design.mat",
                "output_dir": "/path/to/output",
            }
        elif name == "find_related_concepts":
            example_args = {"concept": "hippocampus"}
        elif name == "coordinate_to_concept":
            example_args = {"x": 30, "y": -25, "z": -20}

    # Check availability
    try:
        is_available = tool.is_available() if hasattr(tool, "is_available") else True
    except Exception:
        is_available = False

    return jsonify(
        {
            "name": name,
            "description": getattr(tool, "description", ""),
            "category": getattr(tool, "category", "unknown"),
            "schema": schema,
            "example_args": example_args,
            "timeout_ms": getattr(tool, "timeout_ms", 30000),
            "is_available": is_available,
            "neurodesk_required": getattr(tool, "neurodesk_required", False),
        }
    )


def direct_tool_run():
    """
    Direct tool invocation endpoint for testing and guardrails.
    Bypasses LLM and directly executes specified tool.
    """
    from brain_researcher.services.agent.web_service import (
        _execute_tool_request,
        create_error_response,
    )
    data = request.get_json(silent=True) or {}
    tool_id = data.get("tool")
    params = data.get("args")
    if params is None:
        params = data.get("arguments", {})
    _ = data.get("timeout_ms", 30000)  # Kept for compatibility with existing clients.
    preview = bool(data.get("preview", False))
    work_dir = data.get("work_dir")
    output_dir = data.get("output_dir")

    if not tool_id:
        return create_error_response("INVALID_PARAMETER", "Missing tool parameter", 400)

    return _execute_tool_request(
        tool_id=str(tool_id),
        params=params,
        work_dir=work_dir,
        output_dir=output_dir,
        preview=preview,
        origin="tools_run_compat",
    )


def safe_tool_execute():
    """Policy-safe tool execution endpoint used by MCP fallback and API clients."""
    from brain_researcher.services.agent.web_service import (
        _execute_tool_request,
        create_error_response,
    )

    data = request.get_json(silent=True) or {}
    tool_id = data.get("tool_id")
    params = data.get("params", {})
    work_dir = data.get("work_dir")
    output_dir = data.get("output_dir")
    preview = bool(data.get("preview", False))
    origin = data.get("origin")

    if not tool_id:
        return create_error_response(
            "INVALID_PARAMETER", "Missing tool_id parameter", 400
        )

    return _execute_tool_request(
        tool_id=str(tool_id),
        params=params,
        work_dir=work_dir,
        output_dir=output_dir,
        preview=preview,
        origin=str(origin) if isinstance(origin, str) and origin.strip() else None,
    )


def safe_tool_execute_async():
    """Queue tool execution on the agent and return a durable run id."""
    from brain_researcher.services.agent.web_service import (
        _allowlist_violation_response,
        _is_tool_allowed_by_runtime_policy,
        create_error_response,
        logger,
    )

    data = request.get_json(silent=True) or {}
    tool_id = data.get("tool_id")
    params = data.get("params", {})
    work_dir = data.get("work_dir")
    output_dir = data.get("output_dir")
    preview = bool(data.get("preview", False))
    origin = data.get("origin")
    requested_run_id = data.get("run_id")

    if preview:
        return create_error_response(
            "INVALID_PARAMETER",
            "preview=true is not supported on /tools/execute_async",
            400,
        )
    if not tool_id:
        return create_error_response(
            "INVALID_PARAMETER", "Missing tool_id parameter", 400
        )
    if not isinstance(params, dict):
        return create_error_response(
            "INVALID_PARAMETER", "params must be an object", 400
        )
    if work_dir is not None and not isinstance(work_dir, str):
        return create_error_response(
            "INVALID_PARAMETER", "work_dir must be a string", 400
        )
    if output_dir is not None and not isinstance(output_dir, str):
        return create_error_response(
            "INVALID_PARAMETER", "output_dir must be a string", 400
        )
    if requested_run_id is not None and not isinstance(requested_run_id, str):
        return create_error_response(
            "INVALID_PARAMETER", "run_id must be a string", 400
        )

    if not _is_tool_allowed_by_runtime_policy(str(tool_id)):
        requested = [str(tool_id)]
        return _allowlist_violation_response(
            "Requested tool is not permitted by the environment allowlist",
            disallowed=requested,
            requested=requested,
            denied_tool_id=str(tool_id),
            denial_stage="tool_execute_async",
            denial_reason_code="requested_tool_not_permitted",
        )

    from brain_researcher.services.agent.job_service import get_job_service

    try:
        run = get_job_service().create_async_tool_run(
            tool_id=str(tool_id),
            params=params,
            work_dir=work_dir,
            output_dir=output_dir,
            origin=str(origin) if isinstance(origin, str) and origin.strip() else None,
            run_id=requested_run_id.strip()
            if isinstance(requested_run_id, str) and requested_run_id.strip()
            else None,
        )
    except ValueError as exc:
        return create_error_response("INVALID_PARAMETER", str(exc), 400)
    except Exception as exc:
        logger.exception("[/tools/execute_async] Failed to queue %s: %s", tool_id, exc)
        return create_error_response(
            "TOOL_ERROR", f"Tool execution queue failed: {exc}", 500
        )

    return (
        jsonify(
            {
                "ok": True,
                **run,
                "execution_mode": "agent_async",
                "status_url": f"/tools/execute_async/{run['run_id']}",
            }
        ),
        202,
    )


def safe_tool_execute_async_status(run_id: str):
    """Return the current status/result of an async tool execution."""

    from brain_researcher.services.agent.job_service import get_job_service

    payload = get_job_service().get_async_tool_status(run_id)
    if payload is None:
        return jsonify({"ok": False, "error": "run not found"}), 404
    return jsonify(payload)


def list_tools():
    """Return catalog of all registered tools from running agent."""
    from brain_researcher.services.agent.web_service import (
        get_agent,
        logger,
    )
    agent = get_agent()
    registry = agent.tool_registry

    # Optional filters
    q = request.args.get("q")
    only = request.args.get("only")  # e.g., only=available

    tools = registry.get_all_tools()
    rows = []

    for tool in tools:
        try:
            # Check if tool is available
            if hasattr(tool, "is_available") and callable(tool.is_available):
                avail = tool.is_available()
            else:
                avail = True
        except Exception as e:
            logger.debug(f"Error checking availability for {tool.get_tool_name()}: {e}")
            avail = False

        row = {
            "name": tool.get_tool_name(),
            "description": tool.get_tool_description()
            if hasattr(tool, "get_tool_description")
            else getattr(tool, "description", ""),
            "category": getattr(tool, "category", "unknown"),
            "status": "available" if avail else "unavailable",
            "timeout_ms": getattr(tool, "timeout_ms", 30000),
            "cost_hint": getattr(tool, "cost_hint", "medium"),
        }
        hints = get_resource_hints(row["name"])
        if hints:
            row["resource_hints"] = hints
        example = get_example_payload(row["name"])
        if example:
            row["example"] = example
        output_examples = get_output_examples(row["name"])
        if output_examples:
            row["output_examples"] = output_examples
        rows.append(row)

    # Apply filters
    if q:
        q_lower = q.lower()
        rows = [
            r for r in rows if q_lower in (r["name"] + r.get("description", "")).lower()
        ]

    if only == "available":
        rows = [r for r in rows if r["status"] == "available"]

    return jsonify(
        {
            "tools": rows,
            "metadata": {
                "total_tools": len(rows),
                "total_available": sum(1 for r in rows if r["status"] == "available"),
                "generated_at": datetime.utcnow().isoformat(),
                "neurodesk_path": os.environ.get(
                    "NEURODESK_PATH", "/cvmfs/neurodesk.ardc.edu.au"
                ),
                "cache_ttl_seconds": 300,
            },
        }
    )


def register(app):
    """Register the /tools/* routes on the Flask app (called each import)."""
    from brain_researcher.services.agent.web_service import rate_limit, ttl_cache
    app.add_url_rule('/tools/<name>', methods=['GET'], view_func=tool_detail)
    app.add_url_rule('/tools/run', methods=['POST'], view_func=rate_limit(max_per_minute=20)(direct_tool_run))
    app.add_url_rule('/tools/execute', methods=['POST'], view_func=rate_limit(max_per_minute=20)(safe_tool_execute))
    app.add_url_rule('/tools/execute_async', methods=['POST'], view_func=rate_limit(max_per_minute=20)(safe_tool_execute_async))
    app.add_url_rule('/tools/execute_async/<run_id>', methods=['GET'], view_func=safe_tool_execute_async_status)
    app.add_url_rule('/tools', methods=['GET'], view_func=ttl_cache(300)(list_tools))
