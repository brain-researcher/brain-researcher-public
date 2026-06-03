"""/runs/* run-management routes for the BR-KG agent web service.

Carved out of ``agent/web_service.py``: the run status/logs/metrics/bundle/
scorecard/cancel handlers + the async run-execute endpoint. Registered via
``register(app)``; the one rate-limited route is wrapped with ``rate_limit`` at
registration time (matching the original ``@app.route`` over ``@rate_limit``
stacking). Cycle-free; the couple of web_service helpers used
(``create_error_response`` / ``logger``) are imported back lazily.
"""

from __future__ import annotations

from flask import jsonify, request


def safe_runs_execute_async():
    """Queue async execution for either a tool call or a normalized plan."""
    from brain_researcher.services.agent.web_service import (
        create_error_response,
        logger,
    )

    data = request.get_json(silent=True) or {}
    execution_type = str(data.get("execution_type") or "tool").strip().lower()
    origin = data.get("origin")
    requested_run_id = data.get("run_id")

    from brain_researcher.services.agent.job_service import get_job_service

    try:
        if execution_type == "plan":
            plan = data.get("plan")
            if not isinstance(plan, dict):
                return create_error_response(
                    "INVALID_PARAMETER", "plan must be an object", 400
                )
            run = get_job_service().create_async_plan_run(
                plan=plan,
                origin=str(origin)
                if isinstance(origin, str) and origin.strip()
                else None,
                run_id=requested_run_id.strip()
                if isinstance(requested_run_id, str) and requested_run_id.strip()
                else None,
            )
        else:
            tool_id = data.get("tool_id")
            params = data.get("params", {})
            work_dir = data.get("work_dir")
            output_dir = data.get("output_dir")
            if not tool_id:
                return create_error_response(
                    "INVALID_PARAMETER", "Missing tool_id parameter", 400
                )
            if not isinstance(params, dict):
                return create_error_response(
                    "INVALID_PARAMETER", "params must be an object", 400
                )
            run = get_job_service().create_async_tool_run(
                tool_id=str(tool_id),
                params=params,
                work_dir=work_dir if isinstance(work_dir, str) else None,
                output_dir=output_dir if isinstance(output_dir, str) else None,
                origin=str(origin)
                if isinstance(origin, str) and origin.strip()
                else None,
                run_id=requested_run_id.strip()
                if isinstance(requested_run_id, str) and requested_run_id.strip()
                else None,
            )
    except ValueError as exc:
        return create_error_response("INVALID_PARAMETER", str(exc), 400)
    except Exception as exc:
        logger.exception("[/runs/execute_async] Failed to queue execution: %s", exc)
        return create_error_response(
            "TOOL_ERROR", f"Execution queue failed: {exc}", 500
        )

    return jsonify(
        {
            "ok": True,
            **run,
            "execution_mode": "agent_async",
            "execution_type": execution_type,
        }
    ), 202


def internal_run_status(run_id: str):
    """Internal run status endpoint for MCP delegation."""
    from brain_researcher.services.agent.job_service import get_job_service
    from brain_researcher.services.agent.web_service import create_error_response

    run = get_job_service().get_run(run_id)
    if not run:
        return create_error_response("NOT_FOUND", "Run not found", 404)
    return jsonify({"ok": True, **run})


def internal_run_logs(run_id: str):
    """Internal run log endpoint for MCP delegation."""
    from brain_researcher.services.agent.job_service import get_job_service
    from brain_researcher.services.agent.web_service import create_error_response

    raw_offset = request.args.get("start_offset", "0")
    try:
        start_offset = max(0, int(raw_offset))
    except ValueError:
        return create_error_response(
            "INVALID_PARAMETER", "start_offset must be an integer", 400
        )

    job_service = get_job_service()
    run = job_service.get_run(run_id)
    if not run:
        return create_error_response("NOT_FOUND", "Run not found", 404)
    logs = job_service.get_logs(run_id, start_offset=start_offset)
    return jsonify({"ok": True, "run_id": run_id, "logs": logs})


def internal_run_metrics(run_id: str):
    """Internal metrics endpoint for delegated runs."""
    from brain_researcher.services.agent.job_service import get_job_service
    from brain_researcher.services.agent.web_service import create_error_response

    metrics = get_job_service().get_run_metrics(run_id)
    if metrics is None:
        return create_error_response("NOT_FOUND", "Run not found", 404)
    return jsonify({"ok": True, "run_id": run_id, "metrics": metrics})


def internal_run_bundle(run_id: str):
    """Internal bundle endpoint for delegated runs."""
    from brain_researcher.services.agent.job_service import get_job_service
    from brain_researcher.services.agent.web_service import create_error_response

    payload = get_job_service().get_run_bundle(run_id)
    if payload is None:
        return create_error_response("NOT_FOUND", "Run not found", 404)
    return jsonify(payload)


def internal_run_scorecard(run_id: str):
    """Internal scorecard endpoint for delegated runs."""
    from brain_researcher.services.agent.job_service import get_job_service
    from brain_researcher.services.agent.web_service import create_error_response

    profile_id = request.args.get("profile_id", "external_coding_v1")
    try:
        payload = get_job_service().get_run_scorecard(run_id, profile_id=profile_id)
    except ValueError as exc:
        return create_error_response("INVALID_PARAMETER", str(exc), 400)
    if payload is None:
        return create_error_response("NOT_FOUND", "Run not found", 404)
    return jsonify(payload)


def internal_run_cancel(run_id: str):
    """Internal cancellation endpoint for delegated runs."""
    from brain_researcher.services.agent.job_service import get_job_service
    from brain_researcher.services.agent.web_service import create_error_response

    data = request.get_json(silent=True) or {}
    reason = data.get("reason")
    cancelled = get_job_service().cancel_run(
        run_id,
        reason=str(reason)
        if isinstance(reason, str) and reason.strip()
        else "User requested",
    )
    if not cancelled:
        return create_error_response(
            "NOT_FOUND", "Run not found or already terminal", 404
        )
    return jsonify({"ok": True, "run_id": run_id, "cancelled": True})


def register(app):
    """Register the /runs/* routes on the Flask app (called each import)."""
    from brain_researcher.services.agent.web_service import rate_limit
    app.add_url_rule('/runs/execute_async', methods=['POST'], view_func=rate_limit(max_per_minute=20)(safe_runs_execute_async))
    app.add_url_rule('/runs/<run_id>', methods=['GET'], view_func=internal_run_status)
    app.add_url_rule('/runs/<run_id>/logs', methods=['GET'], view_func=internal_run_logs)
    app.add_url_rule('/runs/<run_id>/metrics', methods=['GET'], view_func=internal_run_metrics)
    app.add_url_rule('/runs/<run_id>/bundle', methods=['GET'], view_func=internal_run_bundle)
    app.add_url_rule('/runs/<run_id>/scorecard', methods=['GET'], view_func=internal_run_scorecard)
    app.add_url_rule('/runs/<run_id>/cancel', methods=['POST'], view_func=internal_run_cancel)
